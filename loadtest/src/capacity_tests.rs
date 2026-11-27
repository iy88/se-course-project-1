use super::stage::{LiveLatency, Progress, growing_backlog};
use super::*;
use crate::http::Session;
use crate::model::ResolvedTradePair;
use std::time::{Duration, Instant};
use tokio::sync::mpsc;

#[test]
fn mixed_live_guard_uses_each_operation_sla_not_whole_trade_duration() {
  let mut live = LiveLatency::default();
  let mut sample = crate::model::Sample {
    user: 0,
    operation: "search".into(),
    elapsed_ms: 100.,
    ok: true,
    status: Some(200),
    phase: "measured".into(),
    details: None,
  };
  for _ in 0..18 {
    live.observe(&sample);
  }
  sample.elapsed_ms = 3001.;
  live.observe(&sample);
  assert!(!live.violates(20));
  live.observe(&sample);
  assert!(live.violates(20));
  let mut flow = LiveLatency::default();
  sample.operation = "scenario_trade".into();
  for _ in 0..20 {
    flow.observe(&sample);
  }
  assert!(!flow.violates(20));
}

#[test]
fn mixed_400_fits_default_budget_but_unbounded_inputs_are_rejected() {
  let mut args = Args::parse_from([
    "test",
    "--mode",
    "capacity",
    "--capacity-case",
    "mixed",
    "--capacity-max-rate",
    "400",
  ]);
  assert!(validate(&args).is_ok());
  args.capacity.capacity_max_rate = 4000.;
  assert!(validate(&args).is_err());
  args.capacity.capacity_max_rate = 400.;
  args.capacity.capacity_start_rate = f64::NAN;
  assert!(validate(&args).is_err());
}

#[test]
fn default_start_tracks_half_the_ceiling_and_refinement_rates_are_integer() {
  let mut args = Args::parse_from(["test", "--mode", "capacity"]);
  assert_eq!(start_rate(&args), 200.);
  args.capacity.capacity_max_rate = 800.;
  assert_eq!(start_rate(&args), 400.);
  args.capacity.capacity_max_rate = 801.;
  assert_eq!(start_rate(&args), 401.);
  args.capacity.capacity_start_rate = 25.;
  assert_eq!(start_rate(&args), 25.);
  args.capacity.capacity_start_rate = 25.5;
  assert!(validate(&args).is_err());
  args.capacity.capacity_start_rate = 25.;
  args.capacity.capacity_resolution = 0.5;
  assert!(validate(&args).is_err());
}

#[test]
fn explicit_error_budget_is_reflected_in_operation_verdict() {
  let mut args = Args::parse_from(["test", "--mode", "capacity"]);
  let mut metrics = json!({"search":{"samples":20,"errors":1,"p95_ms":100.,"threshold_ms":3000.,"enough_samples":true}});
  assert!(!metrics_pass(&mut metrics, &args).1);
  assert_eq!(metrics["search"]["passed"], false);
  args.capacity.capacity_max_error_rate = 0.1;
  assert!(metrics_pass(&mut metrics, &args).1);
  assert_eq!(metrics["search"]["passed"], true);
}
fn trade_pair(buyer: usize, product_id: u64) -> ResolvedTradePair {
  ResolvedTradePair {
    buyer,
    seller: (buyer + 1) % 3,
    product_id,
    product_version: 1,
  }
}

#[test]
fn inventory_never_reuses_unfinished_trade_and_rotates() {
  let pairs = vec![
    trade_pair(0, 10),
    trade_pair(0, 11),
    trade_pair(0, 12),
    trade_pair(1, 20),
  ];
  let mut pool = Inventory::default();
  let a = pool.acquire(0, &pairs).unwrap();
  let b = pool.acquire(0, &pairs).unwrap();
  assert_ne!(a, b);
  assert!(pool.acquire(0, &pairs).is_some());
  assert!(pool.acquire(0, &pairs).is_none());
  assert!(pool.acquire(1, &pairs).is_some());
  pool.busy.remove(&a);
  assert!(pool.acquire(0, &pairs).is_some());
}
#[test]
fn detects_growing_inflight_not_constant_concurrency() {
  let points = |growing: bool| {
    (0..30)
      .map(|i| Progress {
        seconds: i as f64,
        started: i * 100,
        completed: i * 100,
        in_flight: if growing { i * 10 } else { 10 },
      })
      .collect::<Vec<_>>()
  };
  assert!(growing_backlog(&points(true), 100.).1);
  assert!(!growing_backlog(&points(false), 100.).1);
}
#[test]
fn single_im_requires_send_delivery_and_retrieval() {
  let args = Args::parse_from([
    "test",
    "--mode",
    "capacity",
    "--capacity-case",
    "single",
    "--single-operation",
    "im",
  ]);
  assert_eq!(
    required(&args),
    vec!["im_send", "im_delivery", "im_retrieval"]
  );
}

#[test]
fn exact_mixed_mix_and_single_operation() {
  let ops = (0..20)
    .map(|i| operation(CapacityCase::Mixed, SingleOperation::Search, i))
    .collect::<Vec<_>>();
  assert_eq!(ops.iter().filter(|&&s| s == "trade").count(), 1);
  assert_eq!(ops.iter().filter(|&&s| s == "home").count(), 6);
  assert!(
    (0..20).all(|i| operation(CapacityCase::Single, SingleOperation::Publish, i) == "publish")
  );
}

use clap::Parser;
use std::{
  path::PathBuf,
  sync::{
    Mutex,
    atomic::{AtomicUsize, Ordering},
  },
};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
struct Target {
  root: PathBuf,
  server: tokio::task::JoinHandle<()>,
}
impl Drop for Target {
  fn drop(&mut self) {
    self.server.abort();
    let _ = std::fs::remove_dir_all(&self.root);
  }
}
async fn target(
  delay_ms: u64,
  server_limit: usize,
  max_in_flight: usize,
) -> (Driver, Args, Target) {
  let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
  let address = listener.local_addr().unwrap();
  let active = Arc::new(AtomicUsize::new(0));
  let server = tokio::spawn(async move {
    loop {
      let Ok((mut socket, _)) = listener.accept().await else {
        break;
      };
      let active = active.clone();
      tokio::spawn(async move {
        let mut buffer = [0; 4096];
        if socket.read(&mut buffer).await.is_err() {
          return;
        }
        let count = active.fetch_add(1, Ordering::SeqCst) + 1;
        tokio::time::sleep(Duration::from_millis(delay_ms)).await;
        let (status, body) = if count > server_limit {
          (
            "500 Internal Server Error",
            r#"{"detail":"controlled overload"}"#,
          )
        } else {
          ("200 OK", r#"{"items":[],"total":0}"#)
        };
        let response = format!(
          "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
          body.len()
        );
        let _ = socket.write_all(response.as_bytes()).await;
        active.fetch_sub(1, Ordering::SeqCst);
      });
    }
  });
  let root = std::env::temp_dir().join(format!(
    "campus-capacity-test-{}-{}",
    std::process::id(),
    std::time::SystemTime::now()
      .duration_since(std::time::UNIX_EPOCH)
      .unwrap()
      .as_nanos()
  ));
  std::fs::create_dir_all(&root).unwrap();
  let mut args = Args::parse_from([
    "test",
    "--mode",
    "capacity",
    "--users",
    "3",
    "--min-samples",
    "1",
    "--capacity-start-rate",
    "4",
    "--capacity-max-rate",
    "16",
    "--capacity-stage-seconds",
    "1",
    "--capacity-warmup-seconds",
    "0",
    "--capacity-validation-seconds",
    "1",
    "--capacity-resolution",
    "1",
    "--capacity-refinements",
    "2",
    "--capacity-max-lag-ms",
    "1000",
  ]);
  args.output = root.join("result.json");
  args.capacity.capacity_max_in_flight = max_in_flight;
  let manifest=serde_json::from_value(json!({"version":1,"complete":true,"tag":"test","password":"test","users":3,"products":12,"accounts":[{"id":1,"email":"a@example.com"},{"id":2,"email":"b@example.com"},{"id":3,"email":"c@example.com"}],"product_ids":(1..=12).collect::<Vec<_>>(),"category_ids":[1,2,3,4,5],"conversation_ids":[1,2,3],"image_base64":"AQ==","image_sha256":"unused"})).unwrap();
  let (events, _) = mpsc::unbounded_channel();
  let reporter = Arc::new(crate::http::Reporter::new(events));
  reporter.set_window(Duration::ZERO, Duration::from_secs(1000));
  reporter.set_begin(Instant::now());
  let origin = format!("http://{address}");
  let driver = Driver {
    client: reqwest::Client::builder()
      .no_proxy()
      .retry(reqwest::retry::never())
      .build()
      .unwrap(),
    origin: origin.clone(),
    ws_origin: origin,
    sessions: Arc::new(vec![
      Session {
        cookie: "__Host-se_session=a".into(),
        csrf: "csrf-a".into(),
        account_id: 1,
      },
      Session {
        cookie: "__Host-se_session=b".into(),
        csrf: "csrf-b".into(),
        account_id: 2,
      },
      Session {
        cookie: "__Host-se_session=c".into(),
        csrf: "csrf-c".into(),
        account_id: 3,
      },
    ]),
    manifest: Arc::new(manifest),
    images: Arc::new(vec![vec![1]]),
    browse_products: Arc::new((1..=12).collect()),
    trade_pairs: Arc::new(vec![]),
    prepublished_images: Arc::new(Mutex::new(vec![None; 3])),
    sequence: Arc::new(std::sync::atomic::AtomicU64::new(0)),
    pending: Arc::new(Mutex::new(Default::default())),
    reporter,
    warmup: Duration::ZERO,
    duration: Duration::from_secs(1000),
    run_id: "test".into(),
  };
  (driver, args, Target { root, server })
}
#[tokio::test]
async fn open_loop_keeps_arrival_rate_and_accounts_for_drain() {
  let (d, args, target) = target(250, 1000, 100).await;
  let report = stage(
    &d,
    &args,
    StageSpec {
      rate: 20.,
      seconds: 2,
      index: 0,
      kind: "test",
    },
    Arc::new(Mutex::new(Inventory::default())),
    &target.root,
  )
  .await
  .unwrap();
  assert_eq!(report["started_arrivals"], 40);
  assert_eq!(report["http_requests_started_in_window"], 40);
  assert!(report["pending_at_window_end"].as_u64().unwrap() > 0);
  assert!(report["drain_seconds"].as_f64().unwrap() > 0.);
  assert!(report["http_completions_in_window"].as_u64().unwrap() < 40);
  assert_eq!(report["passed"], true);
}
#[tokio::test]
async fn admission_limit_is_not_reported_as_service_capacity() {
  let (d, args, target) = target(250, 1000, 1).await;
  let report = stage(
    &d,
    &args,
    StageSpec {
      rate: 20.,
      seconds: 1,
      index: 0,
      kind: "test",
    },
    Arc::new(Mutex::new(Inventory::default())),
    &target.root,
  )
  .await
  .unwrap();
  assert!(report["in_flight_limit_drops"].as_u64().unwrap() > 0);
  assert_eq!(
    report["outcome"],
    "inconclusive_generator_or_in_flight_limit"
  );
  assert_eq!(report["passed"], false);
}

#[tokio::test]
async fn completed_response_rate_includes_warmup_carry_in() {
  let (d, mut args, target) = target(250, 1000, 100).await;
  args.capacity.capacity_warmup_seconds = 1;
  let report = stage(
    &d,
    &args,
    StageSpec {
      rate: 20.,
      seconds: 1,
      index: 0,
      kind: "test",
    },
    Arc::new(Mutex::new(Inventory::default())),
    &target.root,
  )
  .await
  .unwrap();
  assert!(
    report["http_successful_responses_completed_in_window"]
      .as_u64()
      .unwrap()
      > report["http_completions_in_window"].as_u64().unwrap()
  );
  assert_eq!(report["latency_sla_passed"], true);
  assert_eq!(report["error_budget_passed"], true);
}
#[tokio::test]
async fn controller_finds_failure_bracket_and_validates_lower_rate() {
  let (d, args, _target) = target(400, 3, 100).await;
  let report = run(&d, &args).await.unwrap();
  assert_eq!(report["passed"], true);
  assert_eq!(report["boundary_bracketed"], true);
  let low = report["highest_validated_rate"].as_f64().unwrap();
  let high = report["first_observed_failing_rate"].as_f64().unwrap();
  assert!(low < high && high <= 16.);
  assert!(
    report["stages"]
      .as_array()
      .unwrap()
      .iter()
      .any(|s| s["kind"] == "validation" && s["passed"] == true)
  );
  assert_eq!(report["long_validation"], false);
  assert_eq!(report["refinement_strategy"], "integer_binary_search");
  assert!(
    report["stages"]
      .as_array()
      .unwrap()
      .iter()
      .all(|stage| { stage["target_rate"].as_f64().unwrap().fract() == 0. })
  );
}

#[tokio::test]
async fn early_failure_uses_actual_window_and_stops_scheduling() {
  let (d, args, target) = target(50, 0, 100).await;
  let report = stage(
    &d,
    &args,
    StageSpec {
      rate: 10.,
      seconds: 20,
      index: 0,
      kind: "test",
    },
    Arc::new(Mutex::new(Inventory::default())),
    &target.root,
  )
  .await
  .unwrap();
  assert_eq!(report["early_stop_reason"], "error_budget_exceeded");
  assert_eq!(report["outcome"], "service_failed");
  let seconds = report["sample_seconds"].as_f64().unwrap();
  assert!((9. ..12.).contains(&seconds));
  assert_eq!(report["planned_sample_seconds"], 20);
  assert!((9. ..11.).contains(&report["started_rate"].as_f64().unwrap()));
  assert!(report["started_arrivals"].as_u64().unwrap() < 150);
}
