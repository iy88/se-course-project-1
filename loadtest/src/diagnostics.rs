use serde::Serialize;
use std::error::Error;

#[derive(Clone, Serialize)]
pub(crate) struct RequestDetails {
  pub(crate) request_id: String,
  pub(crate) started_ms: f64,
  pub(crate) category: Option<&'static str>,
  pub(crate) causes: Vec<&'static str>,
}

// Inspect error messages in memory, persist only allowlisted labels. Never save
// URLs, bearer tokens, signed headers, response bodies or arbitrary error text.
pub(crate) fn classify(error: &reqwest::Error) -> (&'static str, Vec<&'static str>) {
  let category = if error.is_timeout() {
    "timeout"
  } else if error.is_connect() {
    "connect"
  } else if error.is_builder() {
    "request_builder"
  } else if error.is_decode() {
    "decode"
  } else if error.is_body() {
    "body"
  } else {
    "transport"
  };
  let mut causes = Vec::new();
  let mut current: Option<&(dyn Error + 'static)> = Some(error);
  for _ in 0..12 {
    let Some(cause) = current else {
      break;
    };
    let text = cause.to_string().to_lowercase();
    for (pattern, label) in [
      ("reset", "connection_reset"),
      ("closed", "connection_closed"),
      ("incomplete", "incomplete_message"),
      ("broken pipe", "broken_pipe"),
      ("timed out", "timeout"),
      ("dns", "dns"),
      ("certificate", "tls_certificate"),
      ("canceled", "canceled"),
      ("refused", "connection_refused"),
    ] {
      if text.contains(pattern) && !causes.contains(&label) {
        causes.push(label);
      }
    }
    current = cause.source();
  }
  (category, causes)
}
