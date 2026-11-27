use super::{Inventory, execute, metrics_pass, operation, write};
use crate::{
  config::{Args, CapacityCase, SingleOperation},
  http::Driver,
  model::Sample,
  report::{percentile, summary},
  resources,
};
use anyhow::{Context, Result};
use serde::Serialize;
use serde_json::{Value, json};
use std::{
  collections::HashMap,
  path::Path,
  sync::{Arc, Mutex},
  time::{Duration, Instant},
};
use tokio::{sync::mpsc, task::JoinSet};

#[derive(Default)]
pub(super) struct LiveLatency(HashMap<String, (usize, usize)>);
impl LiveLatency {
  pub(super) fn observe(&mut self, sample: &Sample) {
    if sample.phase != "measured" {
      return;
    }
    if let Some(bound) = crate::report::limit(&sample.operation) {
      let row = self.0.entry(sample.operation.clone()).or_default();
      row.0 += 1;
      if sample.elapsed_ms > bound {
        row.1 += 1;
      }
    }
  }
  pub(super) fn violates(&self, min: usize) -> bool {
    self
      .0
      .values()
      .any(|&(n, slow)| n >= min && n - slow < ((n as f64) * 0.95).ceil() as usize)
  }
}
struct Completion {
  measured: bool,
  ended: Instant,
  ok: bool,
  scheduled_ms: f64,
}
#[derive(Serialize)]
pub(super) struct Progress {
  pub(super) seconds: f64,
  pub(super) started: usize,
  pub(super) completed: usize,
  pub(super) in_flight: usize,
}

fn account(
  result: std::result::Result<Completion, tokio::task::JoinError>,
  end: Instant,
  completed: &mut usize,
  in_window: &mut usize,
  errors: &mut usize,
  latencies: &mut Vec<f64>,
) {
  *completed += 1;
  match result {
    Ok(c) => {
      if c.measured {
        latencies.push(c.scheduled_ms);
      }
      if c.measured && c.ended < end {
        *in_window += 1;
      }
      if c.measured && !c.ok {
        *errors += 1;
      }
    }
    Err(_) => *errors += 1,
  }
}

pub(super) fn growing_backlog(progress: &[Progress], rate: f64) -> (f64, bool) {
  let tail = &progress[progress.len() / 3..];
  if tail.len() < 4 {
    return (0., false);
  }
  let x = tail.iter().map(|p| p.seconds).sum::<f64>() / tail.len() as f64;
  let y = tail.iter().map(|p| p.in_flight as f64).sum::<f64>() / tail.len() as f64;
  let denominator = tail.iter().map(|p| (p.seconds - x).powi(2)).sum::<f64>();
  let slope = tail
    .iter()
    .map(|p| (p.seconds - x) * (p.in_flight as f64 - y))
    .sum::<f64>()
    / denominator.max(1e-9);
  (slope, slope > 1_f64.max(rate * 0.02))
}

pub(super) struct StageSpec<'a> {
  pub(super) rate: f64,
  pub(super) seconds: u64,
  pub(super) index: usize,
  pub(super) kind: &'a str,
}

pub(super) async fn stage(
  base: &Driver,
  args: &Args,
  spec: StageSpec<'_>,
  inventory: Arc<Mutex<Inventory>>,
  directory: &Path,
) -> Result<Value> {
  let StageSpec {
    rate,
    seconds,
    index,
    kind,
  } = spec;
  let c = &args.capacity;
  let sample_limit = c.capacity_max_samples;
  let live = Arc::new(Mutex::new(LiveLatency::default()));
  let observed = live.clone();
  let (tx, mut rx) = mpsc::unbounded_channel();
  let collector = tokio::spawn(async move {
    let mut samples = vec![];
    let mut omitted = 0usize;
    while let Some(s) = rx.recv().await {
      observed.lock().unwrap().observe(&s);
      if samples.len() < sample_limit {
        samples.push(s);
      } else {
        omitted += 1;
      }
    }
    (samples, omitted)
  });
  let previous_events = base.reporter.events();
  let mut d = base.clone();
  d.reporter.set_events(tx);
  d.reporter.set_window(
    Duration::from_secs(c.capacity_warmup_seconds),
    Duration::from_secs(seconds),
  );
  d.reporter
    .set_begin(Instant::now() + Duration::from_millis(50));
  d.warmup = Duration::from_secs(c.capacity_warmup_seconds);
  d.duration = Duration::from_secs(seconds);
  d.reporter.set_capture_drain(true);
  d.run_id = format!("{}-capacity-{index}", base.run_id);
  let stage_unix_ms = (std::time::SystemTime::now() + Duration::from_millis(50))
    .duration_since(std::time::UNIX_EPOCH)?
    .as_millis();
  let begin = d.begin_instant().context("stage start missing")?;
  let window = begin + d.warmup;
  let end = window + d.duration;
  let total = (rate * (seconds + c.capacity_warmup_seconds) as f64).ceil() as usize;
  let mut tasks = JoinSet::new();
  let mut completed = 0;
  let mut completed_in_window = 0;
  let mut errors = 0;
  let mut latencies = vec![];
  let mut started = 0;
  let mut measured_started = 0;
  let mut expected = 0;
  let mut late = 0;
  let mut dropped = 0;
  let mut fixture_drops = 0;
  let mut warmup_drops = 0;
  let mut warmup_fixture_drops = 0;
  let mut lags = vec![];
  let mut progress = vec![];
  let mut next_progress = 0.;
  let mut max_in_flight = 0;
  let mut actual_end = end;
  let mut early_stop_reason = None;
  let mut next_health_check = window + Duration::from_secs(10);
  let (resource_stop, resource_task) = resources::start(c.monitor_pid.clone());
  println!(
    "capacity {kind} #{index}: target={rate:.2} {unit}, warmup={}s, sample={seconds}s",
    c.capacity_warmup_seconds,
    unit = if c.capacity_case == CapacityCase::Single {
      "HTTP RPS"
    } else {
      "scenarios/s"
    }
  );
  for ordinal in 0..total {
    let due = begin + Duration::from_secs_f64(ordinal as f64 / rate);
    if due >= end {
      break;
    }
    tokio::time::sleep_until(due.into()).await;
    while let Some(done) = tasks.try_join_next() {
      account(
        done,
        end,
        &mut completed,
        &mut completed_in_window,
        &mut errors,
        &mut latencies,
      );
    }
    let now = Instant::now();
    if now >= next_health_check {
      next_health_check = now + Duration::from_secs(5);
      let errors_bad =
        errors > 0 && errors as f64 / measured_started.max(1) as f64 > c.capacity_max_error_rate;
      let bound = if c.single_operation == SingleOperation::Im {
        2000.
      } else {
        3000.
      };
      let slow = latencies.iter().filter(|&&ms| ms > bound).count();
      let scheduled_bad = c.capacity_case == CapacityCase::Single
        && latencies.len() >= args.min_samples
        && latencies.len() - slow < ((latencies.len() as f64) * 0.95).ceil() as usize;
      let operation_bad = live.lock().unwrap().violates(args.min_samples);
      if errors_bad || scheduled_bad || operation_bad {
        actual_end = now;
        early_stop_reason = Some(if errors_bad {
          "error_budget_exceeded"
        } else if operation_bad {
          "operation_latency_sla_exceeded"
        } else {
          "scheduled_latency_sla_exceeded"
        });
        break;
      }
    }
    let measured = due >= window;
    let lag = now.saturating_duration_since(due).as_secs_f64() * 1000.;
    if measured {
      expected += 1;
      lags.push(lag);
    }
    if now >= end || lag > c.capacity_max_lag_ms as f64 {
      if measured {
        late += 1;
      } else {
        warmup_drops += 1;
      }
      continue;
    }
    if tasks.len() >= c.capacity_max_in_flight {
      if measured {
        dropped += 1;
      } else {
        warmup_drops += 1;
      }
      continue;
    }
    let op = operation(c.capacity_case, c.single_operation, ordinal);
    let user = (ordinal + ordinal / 20) % args.users;
    let lease = if op == "trade" {
      inventory.lock().unwrap().acquire(user, &d.trade_pairs)
    } else {
      None
    };
    if op == "trade" && lease.is_none() {
      if measured {
        fixture_drops += 1;
      } else {
        warmup_fixture_drops += 1;
      }
      continue;
    }
    let pair = lease;
    let driver = d.clone();
    let pool = inventory.clone();
    let case = c.capacity_case;
    tasks.spawn(async move {
      let start = Instant::now();
      let result = execute(&driver, case, op, user, ordinal, pair).await;
      // Failed/cancelled trades remain quarantined; do not reuse unknown state.
      if result.is_ok()
        && let Some(i) = lease
      {
        pool.lock().unwrap().busy.remove(&i);
      }
      driver.record(
        user,
        &format!("scenario_{op}"),
        start,
        start.elapsed().as_secs_f64() * 1000.,
        result.is_ok(),
        None,
      );
      Completion {
        measured,
        ended: Instant::now(),
        ok: result.is_ok(),
        scheduled_ms: Instant::now().saturating_duration_since(due).as_secs_f64() * 1000.,
      }
    });
    started += 1;
    if measured {
      measured_started += 1;
    }
    max_in_flight = max_in_flight.max(tasks.len());
    let elapsed = now.saturating_duration_since(window).as_secs_f64();
    if measured && elapsed >= next_progress {
      progress.push(Progress {
        seconds: elapsed,
        started: measured_started,
        completed: completed_in_window,
        in_flight: tasks.len(),
      });
      next_progress = elapsed.floor() + 1.;
    }
  }
  let end = actual_end;
  let actual_seconds = end
    .saturating_duration_since(window)
    .as_secs_f64()
    .max(1e-6);
  tokio::time::sleep_until(end.into()).await;
  while let Some(done) = tasks.try_join_next() {
    account(
      done,
      end,
      &mut completed,
      &mut completed_in_window,
      &mut errors,
      &mut latencies,
    );
  }
  let pending_at_end = tasks.len();
  progress.push(Progress {
    seconds: actual_seconds,
    started: measured_started,
    completed: completed_in_window,
    in_flight: pending_at_end,
  });
  let drain_start = Instant::now();
  let drained = tokio::time::timeout(Duration::from_secs(args.timeout_seconds + 15), async {
    while let Some(done) = tasks.join_next().await {
      account(
        done,
        end,
        &mut completed,
        &mut completed_in_window,
        &mut errors,
        &mut latencies,
      );
    }
  })
  .await
  .is_ok();
  if !drained {
    tasks.abort_all();
    while let Some(done) = tasks.join_next().await {
      account(
        done,
        end,
        &mut completed,
        &mut completed_in_window,
        &mut errors,
        &mut latencies,
      );
    }
  }
  let drain_seconds = drain_start.elapsed().as_secs_f64();
  let _ = resource_stop.send(true);
  let resource_samples = resource_task.await?;
  // The long-lived sockets share the reporter, so restore the previous sink
  // before waiting for this stage's collector to close.
  d.reporter.set_events(previous_events);
  drop(d);
  let (mut samples, omitted_samples): (Vec<Sample>, usize) = collector.await?;
  let boundary_ms = (c.capacity_warmup_seconds as f64 + actual_seconds) * 1000.;
  for sample in &mut samples {
    if sample.phase == "measured"
      && sample
        .details
        .as_ref()
        .is_some_and(|d| d.started_ms >= boundary_ms)
    {
      sample.phase = "drain".into();
    }
  }
  let (mut metrics, _) = summary(&samples, "measured", args.min_samples);
  let (warmup_metrics, _) = summary(&samples, "warmup", 1);
  let (enough, latency_errors_ok) = metrics_pass(&mut metrics, args);
  let warmup_ok = samples.iter().all(|s| s.phase != "warmup" || s.ok) && warmup_drops == 0;
  let (growth, growing) = growing_backlog(&progress, rate);
  latencies.sort_by(f64::total_cmp);
  let scheduled_p95 = percentile(&latencies, 0.95);
  let scheduled_ok = c.capacity_case == CapacityCase::Mixed
    || scheduled_p95
      <= if c.single_operation == SingleOperation::Im {
        2000.
      } else {
        3000.
      };
  let generator_ok = late == 0 && dropped == 0 && warmup_drops == 0 && omitted_samples == 0;
  let fixture_ok = fixture_drops == 0 && warmup_fixture_drops == 0;
  let scenario_ok = errors as f64 / measured_started.max(1) as f64 <= c.capacity_max_error_rate;
  let latency_sla_ok = scheduled_ok
    && metrics.as_object().is_some_and(|m| {
      m.values().all(|v| {
        v["threshold_ms"]
          .as_f64()
          .is_none_or(|bound| v["p95_ms"].as_f64().unwrap_or(f64::INFINITY) <= bound)
      })
    });
  let error_budget_ok = scenario_ok
    && metrics.as_object().is_some_and(|m| {
      m.values()
        .all(|v| v["error_rate"].as_f64().unwrap_or(1.) <= c.capacity_max_error_rate)
    });
  let websocket_disconnects = samples
    .iter()
    .filter(|sample| sample.operation == "ws_disconnect")
    .count();
  let websocket_reconnect_failures = samples
    .iter()
    .filter(|sample| sample.operation == "ws_reconnect_failed")
    .count();
  let passed = generator_ok
    && fixture_ok
    && enough
    && latency_errors_ok
    && scenario_ok
    && warmup_ok
    && !growing
    && drained
    && scheduled_ok
    && early_stop_reason.is_none()
    && websocket_disconnects == 0
    && websocket_reconnect_failures == 0;
  let outcome = if websocket_disconnects > 0 || websocket_reconnect_failures > 0 {
    "inconclusive_websocket_disconnect"
  } else if !generator_ok {
    "inconclusive_generator_or_in_flight_limit"
  } else if !fixture_ok {
    "inconclusive_fixture_exhausted"
  } else if !enough {
    "inconclusive_samples"
  } else if passed {
    "passed"
  } else {
    "service_failed"
  };
  lags.sort_by(f64::total_cmp);
  let http = samples
    .iter()
    .filter(|s| {
      s.phase == "measured" && !s.operation.starts_with("scenario_") && s.operation != "im_delivery"
    })
    .count();
  let path = directory.join(format!("{index:02}-{kind}.json"));
  let storage_http = samples
    .iter()
    .filter(|s| s.phase == "measured" && s.operation == "upload_bytes")
    .count();
  let successful_responses = samples
    .iter()
    .filter(|s| {
      s.ok
        && !s.operation.starts_with("scenario_")
        && s.operation != "im_delivery"
        && s.details.as_ref().is_some_and(|d| {
          d.started_ms + s.elapsed_ms >= c.capacity_warmup_seconds as f64 * 1000.
            && d.started_ms + s.elapsed_ms < boundary_ms
        })
    })
    .collect::<Vec<_>>();
  let application_responses = successful_responses
    .iter()
    .filter(|s| s.operation != "upload_bytes")
    .count();
  let mut report = json!({"index":index,"kind":kind,"target_rate":rate,"unit":if c.capacity_case==CapacityCase::Single {"http_requests_per_second"} else {"scenario_starts_per_second"},
        "started_at_unix_ms":stage_unix_ms,"scheduled_to_complete_p50_ms":percentile(&latencies,0.5),"scheduled_to_complete_p95_ms":scheduled_p95,"scheduled_to_complete_p99_ms":percentile(&latencies,0.99),"scheduled_latency_passed":scheduled_ok,"sample_seconds":actual_seconds,"planned_sample_seconds":seconds,"early_stop_reason":early_stop_reason,"warmup_seconds":c.capacity_warmup_seconds,"outcome":outcome,"passed":passed,
        "expected_arrivals":expected,"started_arrivals":measured_started,"started_rate":measured_started as f64/actual_seconds,
        "completed_scenarios_in_window":completed_in_window,"scenario_completions_per_second":completed_in_window as f64/actual_seconds,
        "scenario_errors":errors,"scenario_error_rate":errors as f64/measured_started.max(1) as f64,
        "http_requests_started_in_window":http,"http_rps":http as f64/actual_seconds,
        "application_http_requests_started_in_window":http-storage_http,"application_http_rps":(http-storage_http) as f64/actual_seconds,
        "storage_http_puts_started_in_window":storage_http,"storage_http_put_rps":storage_http as f64/actual_seconds,
        "http_completions_in_window":samples.iter().filter(|s|s.phase=="measured" && !s.operation.starts_with("scenario_") && s.operation!="im_delivery" && s.details.as_ref().is_some_and(|d|d.started_ms+s.elapsed_ms<boundary_ms)).count(),
        "late_arrivals_skipped":late,"in_flight_limit_drops":dropped,"fixture_drops":fixture_drops,"warmup_admission_drops":warmup_drops,"warmup_fixture_drops":warmup_fixture_drops,"omitted_samples":omitted_samples,
    "websocket_disconnects":websocket_disconnects,"websocket_reconnect_failures":websocket_reconnect_failures});
  let details = json!({
        "latency_sla_passed":latency_sla_ok,"error_budget_passed":error_budget_ok,
        "http_successful_responses_completed_in_window":successful_responses.len(),"http_successful_response_rps":successful_responses.len() as f64/actual_seconds,
        "application_successful_response_rps":application_responses as f64/actual_seconds,
        "completion_scope":"legacy completion fields track measured-start cohort; successful_response fields include warmup carry-in responses completed during measurement",
        "max_in_flight":max_in_flight,"pending_at_window_end":pending_at_end,"backlog_growth_per_second":growth,"growing_backlog":growing,
        "scheduling_lag_p95_ms":percentile(&lags,0.95),"scheduling_lag_max_ms":lags.last(),
        "drained":drained,"drain_seconds":drain_seconds,"warmup_passed":warmup_ok,"enough_samples":enough,
        "operations":metrics,"warmup":warmup_metrics,"progress":progress,"local_resources":resource_samples,
        "total_started_including_warmup":started,"total_completed_including_warmup_and_drain":completed,
        "artifact":path,"samples":samples});
  if let Value::Object(details) = details {
    report.as_object_mut().unwrap().extend(details);
  }
  write(&path, &report)?;
  report.as_object_mut().unwrap().remove("samples");
  println!(
    "capacity #{index}: {outcome}; started={:.2}/s, actual HTTP={:.2}/s, pending={pending_at_end}, skipped={late}, admission_drops={dropped}",
    measured_started as f64 / actual_seconds,
    http as f64 / actual_seconds
  );
  Ok(report)
}
