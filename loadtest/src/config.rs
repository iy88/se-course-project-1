use clap::{Parser, ValueEnum};
use serde::Serialize;
use std::path::PathBuf;
#[derive(Clone, Copy, Debug, Serialize, ValueEnum, PartialEq)]
pub(crate) enum Mode {
    Steady,
    Race,
    Capacity,
}
#[derive(Clone, Copy, Debug, Serialize, ValueEnum, PartialEq)]
pub(crate) enum CapacityCase {
    Single,
    Mixed,
}
#[derive(Clone, Copy, Debug, Serialize, ValueEnum, PartialEq)]
pub(crate) enum SingleOperation {
    Home,
    Search,
    Detail,
    Publish,
    Im,
}
#[derive(clap::Args, Debug, Serialize)]
pub(crate) struct CapacityArgs {
    #[arg(long, value_enum, default_value_t=CapacityCase::Single)]
    pub(crate) capacity_case: CapacityCase,
    #[arg(long, value_enum, default_value_t=SingleOperation::Search)]
    pub(crate) single_operation: SingleOperation,
    /// HTTP requests/s for single, scenario starts/s for mixed.
    /// 0 (default) starts at half the configured ceiling, rounded up to an integer.
    #[arg(long, default_value_t = 0.)]
    pub(crate) capacity_start_rate: f64,
    #[arg(long, default_value_t = 400.)]
    pub(crate) capacity_max_rate: f64,
    #[arg(long, default_value_t = 30)]
    pub(crate) capacity_stage_seconds: u64,
    #[arg(long, default_value_t = 5)]
    pub(crate) capacity_warmup_seconds: u64,
    #[arg(long, default_value_t = 300)]
    pub(crate) capacity_validation_seconds: u64,
    #[arg(long, default_value_t = 12)]
    pub(crate) capacity_refinements: usize,
    #[arg(long, default_value_t = 1.)]
    pub(crate) capacity_resolution: f64,
    #[arg(long, default_value_t = 2048)]
    pub(crate) capacity_max_in_flight: usize,
    /// Scheduler skips overdue arrivals rather than issuing a catch-up burst.
    #[arg(long, default_value_t = 100)]
    pub(crate) capacity_max_lag_ms: u64,
    #[arg(long, default_value_t = 0.)]
    pub(crate) capacity_max_error_rate: f64,
    /// Bound per-stage planned arrivals (explicitly raise for larger experiments).
    #[arg(long, default_value_t = 200_000)]
    pub(crate) capacity_max_arrivals: usize,
    /// Reaching this raw-event cap invalidates the stage rather than hiding data loss.
    #[arg(long, default_value_t = 500_000)]
    pub(crate) capacity_max_samples: usize,
    /// Local process IDs only; adds CPU/RSS samples, never inspects command lines.
    #[arg(long, value_delimiter = ',')]
    pub(crate) monitor_pid: Vec<u32>,
}
#[derive(Parser, Debug, Serialize)]
#[command(about = "Real HTTP + recipient WebSocket load for issue #34; seed separately")]
pub(crate) struct Args {
    #[command(flatten)]
    pub(crate) capacity: CapacityArgs,
    #[arg(long, value_enum, default_value_t=Mode::Steady)]
    pub(crate) mode: Mode,
    #[arg(long, default_value_t = 5)]
    pub(crate) race_rounds: usize,
    /// Origin only, e.g. http://127.0.0.1:8000 (no /api suffix)
    #[arg(long, default_value = "http://127.0.0.1:8000")]
    pub(crate) base_url: String,
    /// Optional separate WS service HTTP origin; tickets still come from base-url.
    #[arg(long)]
    pub(crate) ws_base_url: Option<String>,
    #[arg(long, default_value = "../var/load/manifest.json")]
    pub(crate) manifest: PathBuf,
    #[arg(long, default_value = "../var/load/report.json")]
    pub(crate) output: PathBuf,
    #[arg(long, default_value_t = 100)]
    pub(crate) users: usize,
    #[arg(long, default_value_t = 30)]
    pub(crate) warmup_seconds: u64,
    #[arg(long, default_value_t = 120)]
    pub(crate) duration_seconds: u64,
    /// Closed-loop virtual users; pause after each scenario (not each HTTP call).
    #[arg(long, default_value_t = 1000)]
    pub(crate) think_ms: u64,
    #[arg(long, default_value_t = 60)]
    pub(crate) timeout_seconds: u64,
    #[arg(long, default_value_t = 20)]
    pub(crate) min_samples: usize,
}
