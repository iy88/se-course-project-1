//! Open-loop arrivals. Single means one application HTTP operation; mixed means
//! one complete business scenario. Never reports mixed scenario/s as HTTP RPS.
mod stage;
use crate::{
    config::{Args, CapacityCase, SingleOperation},
    http::Driver,
    report::REQUIRED,
};
use anyhow::{Result, ensure};
use serde_json::{Value, json};
use stage::{StageSpec, stage};
use std::{
    collections::HashSet,
    path::Path,
    sync::{Arc, Mutex},
};

pub(crate) fn validate(args: &Args) -> Result<()> {
    let c = &args.capacity;
    ensure!(
        c.capacity_start_rate.is_finite()
            && c.capacity_max_rate.is_finite()
            && c.capacity_resolution.is_finite()
            && c.capacity_start_rate > 0.
            && c.capacity_max_rate >= c.capacity_start_rate
            && c.capacity_max_rate <= 100000.
            && c.capacity_resolution > 0.
            && c.capacity_stage_seconds > 0
            && c.capacity_stage_seconds <= 3600
            && c.capacity_validation_seconds >= c.capacity_stage_seconds
            && c.capacity_validation_seconds <= 3600
            && c.capacity_warmup_seconds <= 300
            && c.capacity_max_in_flight > 0
            && c.capacity_max_in_flight <= 100000
            && c.capacity_max_lag_ms > 0
            && c.capacity_refinements <= 12
            && (1..=5_000_000).contains(&c.capacity_max_arrivals)
            && (1..=5_000_000).contains(&c.capacity_max_samples)
            && c.capacity_max_error_rate.is_finite()
            && (0. ..1.).contains(&c.capacity_max_error_rate),
        "invalid capacity options"
    );
    ensure!(
        c.capacity_max_rate * (c.capacity_validation_seconds + c.capacity_warmup_seconds) as f64
            <= c.capacity_max_arrivals as f64,
        "stage exceeds arrival budget; adjust capacity-max-arrivals, rate or duration"
    );
    Ok(())
}

#[derive(Default)]
struct Inventory {
    busy: HashSet<usize>,
    cursor: usize,
    first_row: usize,
}
impl Inventory {
    fn acquire(&mut self, buyer: usize, users: usize, products: usize) -> Option<usize> {
        let seller = (buyer + 1) % users;
        let count = (products - 1 - seller) / users + 1 - self.first_row;
        for offset in 0..count {
            let index = seller + (self.first_row + (self.cursor + offset) % count) * users;
            if self.busy.insert(index) {
                self.cursor += 1;
                return Some(index);
            }
        }
        None
    }
}

fn operation(case: CapacityCase, single: SingleOperation, ordinal: usize) -> &'static str {
    if case == CapacityCase::Single {
        return match single {
            SingleOperation::Home => "home",
            SingleOperation::Search => "search",
            SingleOperation::Detail => "detail",
            SingleOperation::Publish => "publish",
            SingleOperation::Im => "im",
        };
    }
    match ordinal % 20 {
        0..=5 => "home",
        6..=10 => "search",
        11..=15 => "detail",
        16 => "publish",
        17 => "trade",
        _ => "im",
    }
}

async fn execute(
    d: &Driver,
    case: CapacityCase,
    op: &str,
    user: usize,
    ordinal: usize,
    product: Option<u64>,
) -> Result<()> {
    match op {
        "publish" if case == CapacityCase::Single => {
            // A pre-seeded committed image owned by this user. Only POST /products
            // is sent; backend validation/OSS HEAD remain part of this endpoint.
            let key = format!("product/load_{}/{user:08}.jpg", d.manifest.tag);
            d.submit_product(user, ordinal, &key).await.map(|_| ())
        }
        "publish" => d.publish(user, ordinal).await,
        "trade" => {
            d.trade_product(user, ordinal, product.expect("trade fixture reserved"))
                .await
        }
        "im" => d.im(user, ordinal).await,
        _ => d.browse(user, op, ordinal).await,
    }
}

fn required(args: &Args) -> Vec<&'static str> {
    if args.capacity.capacity_case == CapacityCase::Mixed {
        return REQUIRED.to_vec();
    }
    match args.capacity.single_operation {
        SingleOperation::Home => vec!["home"],
        SingleOperation::Search => vec!["search"],
        SingleOperation::Detail => vec!["detail"],
        SingleOperation::Publish => vec!["publish"],
        SingleOperation::Im => vec!["im_send", "im_delivery"],
    }
}

fn metrics_pass(metrics: &mut Value, args: &Args) -> (bool, bool) {
    let enough = required(args)
        .iter()
        .all(|op| metrics[*op]["samples"].as_u64().unwrap_or(0) >= args.min_samples as u64);
    let mut ok = metrics.is_object();
    if let Some(m) = metrics.as_object_mut() {
        for v in m.values_mut() {
            let n = v["samples"].as_f64().unwrap_or(0.);
            let error_rate = v["errors"].as_f64().unwrap_or(1.) / n.max(1.);
            let passed = error_rate <= args.capacity.capacity_max_error_rate
                && v["threshold_ms"]
                    .as_f64()
                    .is_none_or(|bound| v["p95_ms"].as_f64().unwrap_or(f64::INFINITY) <= bound);
            ok &= passed;
            v["error_rate"] = json!(error_rate);
            v["error_rate_limit"] = json!(args.capacity.capacity_max_error_rate);
            v["passed"] = json!(passed && v["enough_samples"] == true);
        }
    }
    (enough, ok)
}

pub(crate) fn write(path: &Path, value: &Value) -> Result<()> {
    if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent)?;
    }
    let temp = path.with_extension("json.tmp");
    std::fs::write(&temp, serde_json::to_vec_pretty(value)?)?;
    std::fs::rename(temp, path)?;
    Ok(())
}

pub(crate) async fn run(d: &Driver, args: &Args) -> Result<Value> {
    validate(args)?;
    let c = &args.capacity;
    ensure!(
        c.capacity_case != CapacityCase::Mixed || d.manifest.products >= 2 * args.users,
        "mixed capacity requires at least two products per user for separate read/trade pools"
    );
    let inventory = Arc::new(Mutex::new(Inventory {
        first_row: if c.capacity_case == CapacityCase::Mixed {
            d.manifest.products / args.users / 2
        } else {
            0
        },
        ..Inventory::default()
    }));
    let parent = args
        .output
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let stem = args
        .output
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("capacity");
    let directory = parent.join(format!("{stem}-stages-{}", d.run_id));
    std::fs::create_dir_all(&directory)?;
    let mut reports = vec![];
    let mut passing = vec![];
    let mut upper = None;
    let mut stop_reason = "configured_ceiling_reached";
    let mut rate = c.capacity_start_rate;
    loop {
        let report = stage(
            d,
            args,
            StageSpec {
                rate,
                seconds: c.capacity_stage_seconds,
                index: reports.len(),
                kind: "coarse",
            },
            inventory.clone(),
            &directory,
        )
        .await?;
        let outcome = report["outcome"].as_str().unwrap().to_string();
        let passed = report["passed"] == true;
        reports.push(report);
        if passed {
            passing.push(rate);
        } else {
            if outcome == "service_failed" {
                upper = Some(rate);
                stop_reason = "service_failure_bracketed";
            } else {
                stop_reason = "inconclusive_load_delivery_or_samples";
            }
            break;
        }
        if rate >= c.capacity_max_rate {
            break;
        }
        rate = (rate * 2.).min(c.capacity_max_rate);
    }
    if let Some(mut high) = upper {
        let mut low = passing.last().copied().unwrap_or(0.);
        for _ in 0..c.capacity_refinements {
            if high - low <= c.capacity_resolution {
                break;
            }
            let mid = (low + high) / 2.;
            let report = stage(
                d,
                args,
                StageSpec {
                    rate: mid,
                    seconds: c.capacity_stage_seconds,
                    index: reports.len(),
                    kind: "refine",
                },
                inventory.clone(),
                &directory,
            )
            .await?;
            let passed = report["passed"] == true;
            let outcome = report["outcome"].as_str().unwrap().to_string();
            reports.push(report);
            if passed {
                passing.push(mid);
                low = mid;
            } else if outcome == "service_failed" {
                high = mid;
            } else {
                stop_reason = "inconclusive_refinement";
                break;
            }
        }
        upper = Some(high);
    }
    passing.sort_by(f64::total_cmp);
    passing.dedup();
    let mut validated = None;
    let mut attempted = HashSet::new();
    let mut validation_refinements = 0;
    loop {
        passing.sort_by(f64::total_cmp);
        passing.dedup();
        let Some(candidate) = passing
            .iter()
            .rev()
            .copied()
            .find(|r| !attempted.contains(&r.to_bits()))
        else {
            break;
        };
        attempted.insert(candidate.to_bits());
        let report = stage(
            d,
            args,
            StageSpec {
                rate: candidate,
                seconds: c.capacity_validation_seconds,
                index: reports.len(),
                kind: "validation",
            },
            inventory.clone(),
            &directory,
        )
        .await?;
        let passed = report["passed"] == true;
        let service_failed = report["outcome"] == "service_failed";
        reports.push(report);
        if passed {
            validated = Some(candidate);
            break;
        }
        stop_reason = "validation_failed_trying_lower_observed_rate";
        if service_failed {
            upper = Some(upper.map_or(candidate, |u| u.min(candidate)));
            let low = passing
                .iter()
                .rev()
                .copied()
                .find(|r| *r < candidate)
                .unwrap_or(0.);
            if candidate - low > c.capacity_resolution
                && validation_refinements < c.capacity_refinements
            {
                validation_refinements += 1;
                let mid = (low + candidate) / 2.;
                let refined = stage(
                    d,
                    args,
                    StageSpec {
                        rate: mid,
                        seconds: c.capacity_stage_seconds,
                        index: reports.len(),
                        kind: "refine_after_validation",
                    },
                    inventory.clone(),
                    &directory,
                )
                .await?;
                if refined["passed"] == true {
                    passing.push(mid);
                } else if refined["outcome"] == "service_failed" {
                    upper = Some(upper.unwrap().min(mid));
                }
                reports.push(refined);
            }
        }
    }
    let latency_limit = validated.filter(|v| upper.is_some_and(|u| u > *v));
    let mut quarantined = inventory
        .lock()
        .unwrap()
        .busy
        .iter()
        .map(|&i| d.manifest.product_ids[i])
        .collect::<Vec<_>>();
    quarantined.sort_unstable();
    let report = json!({"format_version":1,"mode":"capacity","case":c.capacity_case,"single_operation":if c.capacity_case==CapacityCase::Single {Some(c.single_operation)} else {None},
        "parameters":args,"passed":validated.is_some(),"highest_validated_rate":validated,"first_observed_failing_rate":upper,
        "boundary_bracketed":latency_limit.is_some(),"configured_ceiling_reached":passing.contains(&c.capacity_max_rate),"stop_reason":stop_reason,
        "conclusion":if validated.is_none() {"no_rate_validated"} else if latency_limit.is_some() {"observed_capacity_bracket"} else {"validated_lower_bound_only_upper_limit_unknown"},
        "rate_unit":if c.capacity_case==CapacityCase::Single {"HTTP RPS"} else {"business scenarios/s; actual HTTP RPS reported separately"},
        "boundary_criteria":"latency SLA, configured error budget, complete load delivery and sustained validation; not a proof of hardware saturation",
        "validation_seconds":c.capacity_validation_seconds,"long_validation":validated.is_some() && c.capacity_validation_seconds>=300,"quarantined_product_ids":quarantined,
        "notes":["No automatic request retries; expected arrival times never shift to hide latency.","Latency is HTTP request start through usable response, and mixed business flow latency is reported separately.","In-flight limits, skipped arrivals, fixture exhaustion and missing samples cannot establish a service upper bound.","Resource ps CPU/RSS samples are local observations; remote backend and PostgreSQL lock/connection monitoring require separate telemetry.","Published records and completed trades accumulate; failed trade fixtures are quarantined rather than silently reused."],
        "stages":reports});
    write(&args.output, &report)?;
    Ok(report)
}

#[cfg(test)]
#[path = "capacity_tests.rs"]
mod tests;
