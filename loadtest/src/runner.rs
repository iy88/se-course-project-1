use crate::{
  config::{Args, CapacityCase, Mode, SingleOperation},
  http::{Driver, Reporter, login},
  model::{Manifest, browse_products, resolve_trade_pairs, validate},
  report::{REQUIRED, phase_has_errors, request_errors, summary},
  ws::{Deliveries, socket},
};
use anyhow::{Context, Result, ensure};
use base64::{Engine, engine::general_purpose::STANDARD};
use reqwest::Client;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
  collections::{HashMap, HashSet},
  sync::{Arc, Mutex},
  time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tokio::{
  sync::{mpsc, watch},
  task::JoinSet,
  time::sleep,
};

async fn stop_sockets(shutdown: &watch::Sender<bool>, sockets: Vec<tokio::task::JoinHandle<()>>) {
  let _ = shutdown.send(true);
  for mut task in sockets {
    if tokio::time::timeout(Duration::from_secs(5), &mut task)
      .await
      .is_err()
    {
      task.abort();
      let _ = task.await;
    }
  }
}

fn socket_failures(samples: &[crate::model::Sample]) -> (usize, usize) {
  let disconnects = samples
    .iter()
    .filter(|sample| sample.operation == "ws_disconnect")
    .count();
  let reconnects = samples
    .iter()
    .filter(|sample| sample.operation == "ws_reconnect_failed")
    .count();
  (disconnects, reconnects)
}

pub(crate) async fn run(args: &Args) -> Result<bool> {
  if args.mode == Mode::Capacity {
    crate::capacity::validate(args)?;
  }
  ensure!(
    args.users >= 3
      && args.duration_seconds > 0
      && args.timeout_seconds > 0
      && args.min_samples > 0,
    "invalid scale/time options"
  );
  let url = reqwest::Url::parse(&args.base_url)?;
  ensure!(
    matches!(url.scheme(), "http" | "https")
      && url.host_str().is_some()
      && url.username().is_empty()
      && url.password().is_none()
      && url.query().is_none()
      && url.fragment().is_none()
      && url.path() == "/",
    "base-url must be an HTTP origin"
  );
  let ws_origin = args.ws_base_url.as_deref().unwrap_or(&args.base_url);
  let ws_url = reqwest::Url::parse(ws_origin)?;
  ensure!(
    matches!(ws_url.scheme(), "http" | "https")
      && ws_url.host_str().is_some()
      && ws_url.username().is_empty()
      && ws_url.password().is_none()
      && ws_url.query().is_none()
      && ws_url.fragment().is_none()
      && ws_url.path() == "/",
    "ws-base-url must be an HTTP origin"
  );
  let ws_origin = ws_origin.trim_end_matches('/').to_string();
  let metadata = std::fs::symlink_metadata(&args.manifest).context("manifest unreadable")?;
  ensure!(
    metadata.is_file() && !metadata.file_type().is_symlink(),
    "manifest must be a regular private file"
  );
  #[cfg(unix)]
  {
    use std::os::unix::fs::PermissionsExt;
    ensure!(
      metadata.permissions().mode() & 0o777 == 0o600,
      "manifest permissions must be 0600"
    );
  }
  let manifest: Manifest = serde_json::from_slice(&std::fs::read(&args.manifest)?)?;
  validate(&manifest, args.users)?;
  let image = STANDARD.decode(&manifest.image_base64)?;
  ensure!(
    format!("{:x}", Sha256::digest(&image)) == manifest.image_sha256,
    "fixture image hash mismatch"
  );
  let mut images = vec![image];
  if !manifest.image_assets.is_empty() {
    images.clear();
    for asset in &manifest.image_assets {
      let bytes = STANDARD.decode(&asset.base64)?;
      ensure!(
        bytes.len() == asset.size_bytes && format!("{:x}", Sha256::digest(&bytes)) == asset.sha256,
        "asset mismatch"
      );
      images.push(bytes);
    }
  }
  ensure!(args.race_rounds > 0, "race rounds must be positive");
  let trade_pairs = resolve_trade_pairs(&manifest)?;
  if args.mode == Mode::Race {
    ensure!(
      trade_pairs.len() >= args.race_rounds,
      "race needs at least one reserved trade pair per round"
    );
  }
  if args.mode == Mode::Steady
    || (args.mode == Mode::Capacity && args.capacity.capacity_case == CapacityCase::Mixed)
  {
    for user in 0..args.users {
      ensure!(
        trade_pairs.iter().any(|pair| pair.buyer == user),
        "trade pairs do not cover the full seeded cohort"
      );
    }
  }
  let mut browse_products = browse_products(&manifest);
  if manifest.version < 3 {
    let trade_products = trade_pairs
      .iter()
      .map(|pair| pair.product_id)
      .collect::<HashSet<_>>();
    let filtered = browse_products
      .iter()
      .copied()
      .filter(|id| !trade_products.contains(id))
      .collect::<Vec<_>>();
    if !filtered.is_empty() {
      browse_products = filtered;
    }
  }
  ensure!(
    !browse_products.is_empty(),
    "manifest has no browse products"
  );
  let driver_browse_count = browse_products.len();
  let resolved_trade_pairs = trade_pairs.len();
  let manifest = Arc::new(manifest);
  let origin = args.base_url.trim_end_matches('/').to_string();
  let client = Client::builder()
    .timeout(Duration::from_secs(args.timeout_seconds))
    .retry(reqwest::retry::never())
    .redirect(reqwest::redirect::Policy::none())
    .build()?;
  let (tx, mut rx) = mpsc::unbounded_channel();
  let collector = tokio::spawn(async move {
    let mut samples = Vec::new();
    while let Some(sample) = rx.recv().await {
      samples.push(sample);
    }
    samples
  });
  let mut sessions = Vec::new();
  let mut login_ms = Vec::new();
  // Login is setup, deliberately outside the steady-state window and still measured separately.
  for (user, account) in manifest.accounts.iter().enumerate() {
    let start = Instant::now();
    let session = login(
      &client,
      &origin,
      &account.email,
      &manifest.password,
      account.id,
    )
    .await
    .with_context(|| format!("login failed for user {user}"))?;
    sessions.push(session);
    login_ms.push(start.elapsed().as_secs_f64() * 1000.);
  }
  let pending: Deliveries = Arc::new(Mutex::new(HashMap::new()));
  let started_at_unix_ms = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis();
  let run_id = format!(
    "{}-{}",
    manifest.run_id.as_deref().unwrap_or(&manifest.tag),
    started_at_unix_ms
  );
  let reporter = Arc::new(Reporter::new(tx.clone()));
  let driver = Driver {
    client,
    origin: origin.clone(),
    ws_origin,
    sessions: Arc::new(sessions),
    manifest: manifest.clone(),
    images: Arc::new(images),
    browse_products: Arc::new(browse_products),
    trade_pairs: Arc::new(trade_pairs),
    prepublished_images: Arc::new(Mutex::new(vec![None; args.users])),
    sequence: Arc::new(std::sync::atomic::AtomicU64::new(0)),
    pending: pending.clone(),
    reporter: reporter.clone(),
    warmup: Duration::from_secs(if args.mode == Mode::Race {
      0
    } else {
      args.warmup_seconds
    }),
    duration: Duration::from_secs(if args.mode == Mode::Race {
      86400
    } else {
      args.duration_seconds
    }),
    run_id: run_id.clone(),
  };
  if args.mode == Mode::Capacity
    && args.capacity.capacity_case == CapacityCase::Single
    && args.capacity.single_operation == SingleOperation::Publish
  {
    for user in 0..args.users {
      driver.prepare_publish_image(user, user).await?;
    }
  }
  let (shutdown_tx, shutdown_rx) = watch::channel(false);
  let mut sockets = Vec::new();
  for (user, _) in driver.sessions.iter().enumerate().filter(|_| {
    args.mode == Mode::Steady
      || args.mode == Mode::Capacity
        && (args.capacity.capacity_case == CapacityCase::Mixed
          || args.capacity.single_operation == SingleOperation::Im)
  }) {
    sockets.push(socket(&driver, user, shutdown_rx.clone()).await?);
  }
  reporter.set_window(driver.warmup, driver.duration);
  reporter.set_begin(Instant::now() + Duration::from_millis(100));
  if args.mode == Mode::Race {
    println!(
      "Ready: {} authenticated accounts; {} conflict-test rounds (not a 100-active-user performance verdict)",
      args.users, args.race_rounds
    );
  } else if args.mode == Mode::Capacity {
    println!(
      "Ready: capacity {:?}; {} authenticated accounts, {} recipient WebSockets",
      args.capacity.capacity_case,
      args.users,
      sockets.len()
    );
  } else {
    println!(
      "Ready: {} authenticated HTTP users + {} recipient WebSockets; warmup {}s, measure {}s",
      args.users,
      sockets.len(),
      args.warmup_seconds,
      args.duration_seconds
    );
  }
  let begin = driver
    .begin_instant()
    .context("measurement start missing")?;
  tokio::time::sleep_until(begin.into()).await;
  if args.mode == Mode::Capacity {
    let mut report = crate::capacity::run(&driver, args).await?;
    // Capacity stages swap the shared reporter; restore the run-level sink for
    // shutdown/transport observations before stopping the long-lived sockets.
    reporter.set_capture_drain(false);
    reporter.set_window(driver.warmup, driver.duration);
    reporter.set_begin(begin);
    reporter.set_events(tx.clone());
    stop_sockets(&shutdown_tx, sockets).await;
    drop(driver);
    drop(reporter);
    drop(tx);
    let events = collector.await?;
    let (disconnects, reconnects) = socket_failures(&events);
    let stages = report["stages"].as_array();
    let stage_disconnects: u64 = stages
      .map(|stages| {
        stages
          .iter()
          .map(|stage| stage["websocket_disconnects"].as_u64().unwrap_or(0))
          .sum()
      })
      .unwrap_or(0);
    let stage_reconnects: u64 = stages
      .map(|stages| {
        stages
          .iter()
          .map(|stage| stage["websocket_reconnect_failures"].as_u64().unwrap_or(0))
          .sum()
      })
      .unwrap_or(0);
    let disconnects = disconnects as u64 + stage_disconnects;
    let reconnects = reconnects as u64 + stage_reconnects;
    report["websocket_disconnects"] = json!(disconnects);
    report["websocket_reconnect_failures"] = json!(reconnects);
    if disconnects > 0 || reconnects > 0 {
      report["passed"] = json!(false);
      report["conclusion"] = json!("inconclusive_websocket_disconnect");
      report["highest_validated_rate"] = Value::Null;
      report["long_validation"] = json!(false);
      report["boundary_bracketed"] = json!(false);
    }
    report["login_ms"] = json!(login_ms);
    crate::capacity::write(&args.output, &report)?;
    println!(
      "Capacity report: {}; validated={}, conclusion={}",
      args.output.display(),
      report["highest_validated_rate"],
      report["conclusion"]
    );
    return Ok(report["passed"] == true);
  }
  let race_checks = if args.mode == Mode::Race {
    crate::races::run(&driver, args.race_rounds).await
  } else {
    vec![]
  };
  let mut users = JoinSet::new();
  for user in (0..args.users).filter(|_| args.mode == Mode::Steady) {
    let driver = driver.clone();
    let think = Duration::from_millis(args.think_ms);
    users.spawn(async move {
      tokio::time::sleep_until(begin.into()).await;
      let mut step = 0;
      while Instant::now() < begin + driver.warmup + driver.duration {
        let slot = (step + user) % 20;
        let name = match slot {
          0..=5 => "home",
          6..=10 => "search",
          11..=15 => "detail",
          16 => "publish",
          17 => "trade",
          _ => "im",
        };
        let start = Instant::now();
        let result = match name {
          "publish" => driver.publish(user, step).await,
          "trade" => driver.trade(user, step).await,
          "im" => driver.im(user, step).await,
          _ => driver.browse(user, name, step).await,
        };
        driver.record(
          user,
          &format!("scenario_{name}"),
          start,
          start.elapsed().as_secs_f64() * 1000.,
          result.is_ok(),
          None,
        );
        if result.is_err() {
          // Do not print errors containing URLs, response bodies, cookies or signed object URLs.
          eprintln!("user {user}: {name} scenario failed at iteration {step}");
        }
        step += 1;
        sleep(think).await;
      }
    });
  }
  let mut tasks_ok = true;
  while let Some(result) = users.join_next().await {
    tasks_ok &= result.is_ok();
  }
  stop_sockets(&shutdown_tx, sockets).await;
  drop(driver);
  drop(reporter);
  drop(tx);
  let samples = collector.await?;
  let (metrics, passed_metrics) = summary(&samples, "measured", args.min_samples);
  let (warmup, _) = summary(&samples, "warmup", 1);
  let (disconnects, reconnects) = socket_failures(&samples);
  let active = samples
    .iter()
    .filter(|sample| sample.phase == "measured")
    .map(|sample| sample.user)
    .collect::<std::collections::BTreeSet<_>>()
    .len();
  let http_requests = samples
    .iter()
    .filter(|sample| {
      sample.phase == "measured"
        && !sample.operation.starts_with("scenario_")
        && sample.operation != "im_delivery"
    })
    .count();
  let warmup_errors = request_errors(&samples, "warmup");
  let warmup_failed = phase_has_errors(&samples, "warmup");
  let steady_passed =
    tasks_ok && passed_metrics && disconnects == 0 && reconnects == 0 && active == args.users;
  let race_passed = !race_checks.is_empty()
    && race_checks.iter().all(|check| check["passed"] == true)
    && samples.iter().all(|sample| sample.ok);
  let passed = if args.mode == Mode::Race {
    race_passed
  } else {
    steady_passed && !warmup_failed
  };
  let measured_seconds = if args.mode == Mode::Race {
    begin.elapsed().as_secs_f64()
  } else {
    args.duration_seconds as f64
  };
  let acceptance_scale = args.users >= 100 && manifest.products >= 10000;
  let report = json!({"format_version":2,"tool_version":env!("CARGO_PKG_VERSION"),"started_at_unix_ms":started_at_unix_ms,"passed":passed,"issue_34_scale_met":acceptance_scale,
        "issue_34_api_ws_passed":passed && acceptance_scale && args.mode==Mode::Steady,
        "steady_state_passed":args.mode==Mode::Steady && steady_passed,"warmup_request_errors":warmup_errors,"warmup_passed":!warmup_failed,"race_checks":race_checks,
        "parameters":args,"dataset":{"tag":manifest.tag,"users":manifest.users,"products":manifest.products,"browse_products":driver_browse_count,"trade_pairs":resolved_trade_pairs,"conversations":manifest.conversation_ids.len(),"image_bytes":STANDARD.decode(&manifest.image_base64)?.len()},
        "model":"closed-loop; 20-slot cycle per user, staggered by user index; 6 home, 5 search, 5 detail, 1 publish, 1 full trade, 2 IM; think after each scenario",
        "timing":"monotonic client clock; request start through full response body; IM delivery from before POST through verified recipient retrieval; IM retrieval from received event hint through verified HTTP read; samples attributed by operation start, final in-flight operations drain",
        "scope":"real session HTTP/API and recipient WebSocket; excludes browser rendering, UI display, WAN simulation, SMTP and external payment/delivery",
        "active_users":active,"websocket_disconnects":disconnects,"websocket_reconnect_failures":reconnects,"task_panics":!tasks_ok,
        "measured_http_requests":http_requests,"http_requests_per_second":http_requests as f64/measured_seconds,
        "login_ms":login_ms,"warmup":warmup,"operations":metrics,"samples":samples});
  if let Some(parent) = args.output.parent() {
    std::fs::create_dir_all(parent)?;
  }
  std::fs::write(&args.output, serde_json::to_vec_pretty(&report)?)?;
  println!(
    "Report: {}; passed={passed}, issue34_scale={acceptance_scale}, users={active}, HTTP requests={http_requests}, rate={:.2}/s",
    args.output.display(),
    http_requests as f64 / measured_seconds
  );
  for op in REQUIRED.iter().filter(|_| args.mode == Mode::Steady) {
    println!(
      "{op}: n={}, errors={}, p95={}ms, passed={}",
      report["operations"][op]["samples"],
      report["operations"][op]["errors"],
      report["operations"][op]["p95_ms"],
      report["operations"][op]["passed"]
    );
  }
  Ok(passed)
}
