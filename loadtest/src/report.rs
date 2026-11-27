use crate::model::Sample;
use serde_json::{Value, json};
use std::collections::BTreeMap;
pub(crate) fn percentile(sorted: &[f64], q: f64) -> f64 {
  if sorted.is_empty() {
    return 0.;
  }
  sorted[((sorted.len() as f64 * q).ceil() as usize)
    .saturating_sub(1)
    .min(sorted.len() - 1)]
}
pub(crate) fn limit(op: &str) -> Option<f64> {
  match op {
    "im_delivery" | "im_retrieval" => Some(2000.),
    "upload_bytes" | "upload_lease" | "upload_complete" => None,
    op if op.starts_with("scenario_") => None,
    _ => Some(3000.),
  }
}
pub(crate) const REQUIRED: &[&str] = &[
  "home",
  "search",
  "detail",
  "publish",
  "trade_request",
  "trade_accept",
  "trade_agreement",
  "trade_agree",
  "trade_confirm_buyer",
  "trade_confirm_seller",
  "trade_verify",
  "trade_relist",
  "im_send",
  "im_delivery",
  "im_retrieval",
];

pub(crate) fn summary(samples: &[Sample], phase: &str, min_samples: usize) -> (Value, bool) {
  let mut groups: BTreeMap<&str, Vec<&Sample>> = BTreeMap::new();
  for sample in samples.iter().filter(|s| s.phase == phase) {
    groups.entry(&sample.operation).or_default().push(sample);
  }
  let mut ok = REQUIRED.iter().all(|op| groups.contains_key(op));
  let mut metrics = BTreeMap::new();
  for (op, values) in groups {
    let mut times: Vec<f64> = values.iter().map(|s| s.elapsed_ms).collect();
    times.sort_by(f64::total_cmp);
    let errors = values.iter().filter(|s| !s.ok).count();
    let bound = limit(op);
    let p95 = percentile(&times, 0.95);
    let enough = bound.is_none() || times.len() >= min_samples;
    let passed = errors == 0 && enough && bound.is_none_or(|b| p95 <= b);
    ok &= passed;
    let mut statuses = BTreeMap::new();
    for value in &values {
      *statuses
        .entry(value.status.map_or("none".into(), |s| s.to_string()))
        .or_insert(0usize) += 1;
    }
    metrics.insert(op, json!({"samples":times.len(), "errors":errors, "min_ms":times[0],
            "p50_ms":percentile(&times,0.5), "p95_ms":p95, "p99_ms":percentile(&times,0.99),
            "max_ms":times[times.len()-1], "threshold_ms":bound, "enough_samples":enough,"passed":passed,"statuses":statuses}));
  }
  (json!(metrics), ok)
}

pub(crate) fn request_errors(samples: &[Sample], phase: &str) -> usize {
  samples
    .iter()
    .filter(|s| {
      s.phase == phase
        && !s.ok
        && !s.operation.starts_with("scenario_")
        && s.operation != "im_delivery"
    })
    .count()
}

pub(crate) fn phase_has_errors(samples: &[Sample], phase: &str) -> bool {
  samples.iter().any(|s| s.phase == phase && !s.ok)
}

#[cfg(test)]
mod tests {
  use super::*;
  #[test]
  pub(crate) fn nearest_rank_and_fail_closed_acceptance() {
    assert_eq!(
      percentile(&(1..=100).map(f64::from).collect::<Vec<_>>(), 0.95),
      95.
    );
    assert!(!summary(&[], "measured", 1).1);
    let mut samples: Vec<Sample> = REQUIRED
      .iter()
      .map(|op| Sample {
        user: 0,
        operation: op.to_string(),
        elapsed_ms: 100.,
        ok: true,
        status: Some(200),
        phase: "measured".into(),
        details: None,
      })
      .collect();
    assert!(summary(&samples, "measured", 1).1);
    assert!(!summary(&samples, "measured", 2).1);
    samples.last_mut().unwrap().elapsed_ms = 2001.;
    assert!(!summary(&samples, "measured", 1).1);
    samples.last_mut().unwrap().elapsed_ms = 100.;
    samples[0].ok = false;
    assert!(!summary(&samples, "measured", 1).1);
    samples[0].phase = "warmup".into();
    let mut scenario = samples[0].clone();
    scenario.operation = "scenario_home".into();
    samples.push(scenario);
    assert_eq!(request_errors(&samples, "warmup"), 1);
    assert_eq!(request_errors(&samples, "measured"), 0);
    assert!(phase_has_errors(&samples, "warmup"));
    for sample in &mut samples {
      sample.ok = true;
    }
    let mut delivery = samples[0].clone();
    delivery.operation = "im_delivery".into();
    delivery.ok = false;
    samples.push(delivery);
    assert_eq!(request_errors(&samples, "warmup"), 0);
    assert!(phase_has_errors(&samples, "warmup"));
  }
}
