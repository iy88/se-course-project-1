use crate::{
    config::{Args, Mode},
    http::Driver,
    model::Manifest,
    report::{REQUIRED, phase_has_errors, request_errors, summary},
    ws::{Deliveries, socket},
};
use anyhow::{Context, Result, ensure};
use base64::{Engine, engine::general_purpose::STANDARD};
use reqwest::Client;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tokio::{sync::mpsc, task::JoinSet, time::sleep};
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
    ensure!(
        matches!(manifest.version, 1 | 2)
            && manifest.complete
            && manifest.users == manifest.accounts.len()
            && manifest.products == manifest.product_ids.len()
            && args.users <= manifest.users
            && manifest.conversation_ids.len() == manifest.users
            && manifest.category_ids.len() == 5,
        "manifest incomplete or scale mismatch"
    );
    // Ring conversations require the full seeded cohort; avoid silently measuring absent peers.
    ensure!(
        args.users == manifest.users,
        "users must match seeded cohort (reseed for a different scale)"
    );
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
                bytes.len() == asset.size_bytes
                    && format!("{:x}", Sha256::digest(&bytes)) == asset.sha256,
                "asset mismatch"
            );
            images.push(bytes);
        }
    }
    ensure!(args.race_rounds > 0, "race rounds must be positive");
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
        while let Some(s) = rx.recv().await {
            samples.push(s);
        }
        samples
    });
    let mut tokens = Vec::new();
    let mut login_ms = Vec::new();
    // Login is setup, deliberately outside the steady-state window and still measured separately.
    for (u, account) in manifest.accounts.iter().enumerate() {
        let start = Instant::now();
        let r = client
            .post(format!("{origin}/api/v1/auth/login"))
            .json(&json!({"email":account.email,"password":manifest.password}))
            .send()
            .await
            .map_err(|_| anyhow::anyhow!("login transport failed for user {u}"))?;
        ensure!(
            r.status().is_success(),
            "login failed for user {u}: {}",
            r.status().as_u16()
        );
        let data: Value = r.json().await.context("login JSON")?;
        ensure!(
            data["user"]["id"].as_u64() == Some(account.id),
            "target account mismatch"
        );
        tokens.push(
            data["access_token"]
                .as_str()
                .context("missing access token")?
                .to_string(),
        );
        login_ms.push(start.elapsed().as_secs_f64() * 1000.);
    }
    let pending: Deliveries = Arc::new(Mutex::new(HashMap::new()));
    let mut sockets = Vec::new();
    for (u, token) in tokens.iter().enumerate().filter(|_| {
        args.mode == Mode::Steady
            || args.mode == Mode::Capacity
                && (args.capacity.capacity_case == crate::config::CapacityCase::Mixed
                    || args.capacity.single_operation == crate::config::SingleOperation::Im)
    }) {
        sockets.push(socket(&origin, token, u, pending.clone(), tx.clone()).await?);
    }
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
    let started_at_unix_ms = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis();
    let begin = Instant::now() + Duration::from_millis(100);
    let driver = Driver {
        client,
        origin,
        tokens: Arc::new(tokens),
        manifest: manifest.clone(),
        images: Arc::new(images),
        sequence: Arc::new(std::sync::atomic::AtomicU64::new(0)),
        pending,
        events: tx.clone(),
        begin,
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
        run_id: format!(
            "{}-{}",
            manifest.tag,
            SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis()
        ),
        capture_drain: false,
        detail_range_end: None,
    };
    tokio::time::sleep_until(begin.into()).await;
    if args.mode == Mode::Capacity {
        let mut report = crate::capacity::run(&driver, args).await?;
        for task in sockets {
            task.abort();
            let _ = task.await;
        }
        drop(driver);
        drop(tx);
        let events = collector.await?;
        let disconnects = events
            .iter()
            .filter(|s| s.operation == "ws_disconnect")
            .count();
        report["websocket_disconnects"] = json!(disconnects);
        if disconnects > 0 {
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
    for u in (0..args.users).filter(|_| args.mode == Mode::Steady) {
        let d = driver.clone();
        let think = Duration::from_millis(args.think_ms);
        users.spawn(async move {
            tokio::time::sleep_until(d.begin.into()).await;
            let mut step = 0;
            while Instant::now() < d.begin + d.warmup + d.duration {
                let slot = (step + u) % 20;
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
                    "publish" => d.publish(u, step).await,
                    "trade" => d.trade(u, step).await,
                    "im" => d.im(u, step).await,
                    _ => d.browse(u, name, step).await,
                };
                d.record(
                    u,
                    &format!("scenario_{name}"),
                    start,
                    start.elapsed().as_secs_f64() * 1000.,
                    result.is_ok(),
                    None,
                );
                if result.is_err() {
                    // Do not print errors containing URLs, response bodies, tokens or signed object URLs.
                    eprintln!("user {u}: {name} scenario failed at iteration {step}");
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
    for task in sockets {
        task.abort();
        let _ = task.await;
    }
    drop(driver);
    drop(tx);
    let samples = collector.await?;
    let (metrics, passed_metrics) = summary(&samples, "measured", args.min_samples);
    let (warmup, _) = summary(&samples, "warmup", 1);
    let disconnects = samples
        .iter()
        .filter(|s| s.operation == "ws_disconnect")
        .count();
    let active = samples
        .iter()
        .filter(|s| s.phase == "measured")
        .map(|s| s.user)
        .collect::<std::collections::BTreeSet<_>>()
        .len();
    let http_requests = samples
        .iter()
        .filter(|s| {
            s.phase == "measured"
                && !s.operation.starts_with("scenario_")
                && s.operation != "im_delivery"
        })
        .count();
    let warmup_errors = request_errors(&samples, "warmup");
    let warmup_failed = phase_has_errors(&samples, "warmup");
    let steady_passed = tasks_ok && passed_metrics && disconnects == 0 && active == args.users;
    let race_passed = !race_checks.is_empty()
        && race_checks.iter().all(|c| c["passed"] == true)
        && samples.iter().all(|s| s.ok);
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
        "parameters":args,"dataset":{"tag":manifest.tag,"users":manifest.users,"products":manifest.products,"image_bytes":STANDARD.decode(&manifest.image_base64)?.len()},
        "model":"closed-loop; 20-slot cycle per user, staggered by user index; 6 home, 5 search, 5 detail, 1 publish, 1 full trade, 2 IM; think after each scenario",
        "timing":"monotonic client clock; request start through full response body; delivery from before POST to recipient matching WS frame; samples attributed by operation start, final in-flight operations drain",
        "scope":"real HTTP/API and recipient WebSocket; excludes browser rendering, UI display, WAN simulation, SMTP and external payment/delivery",
        "active_users":active,"websocket_disconnects":disconnects,"task_panics":!tasks_ok,
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
