use crate::diagnostics::{RequestDetails, classify};
use anyhow::{Context, Result, ensure};
use reqwest::header::{COOKIE, ORIGIN, SET_COOKIE};
use reqwest::{Client, Method};
use serde_json::Value;
use std::sync::atomic::{AtomicU64, Ordering};
use std::{
  sync::{Arc, Mutex},
  time::{Duration, Instant},
};
use tokio::sync::mpsc;

use crate::{
  model::{Manifest, ResolvedTradePair, Sample, id_value},
  ws::Deliveries,
};

pub(crate) const ENTRY_COOKIE: &str = "__Host-se_entry";
pub(crate) const SESSION_COOKIE: &str = "__Host-se_session";
pub(crate) const CSRF_COOKIE: &str = "__Host-se_csrf";

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct Session {
  /// Full `name=value` pair, sent as the Cookie header on every request.
  pub(crate) cookie: String,
  pub(crate) csrf: String,
  pub(crate) account_id: u64,
}

/// Measurement window and sample sink. Capacity stages swap both while the
/// long-lived recipient WebSockets keep running, so socket-side retrieval
/// samples are attributed to the stage that received them.
pub(crate) struct Reporter {
  begin: Mutex<Option<Instant>>,
  window: Mutex<(Duration, Duration)>,
  capture_drain: Mutex<bool>,
  events: Mutex<mpsc::UnboundedSender<Sample>>,
}

impl Reporter {
  pub(crate) fn new(events: mpsc::UnboundedSender<Sample>) -> Self {
    Self {
      begin: Mutex::new(None),
      window: Mutex::new((Duration::ZERO, Duration::ZERO)),
      capture_drain: Mutex::new(false),
      events: Mutex::new(events),
    }
  }

  pub(crate) fn set_begin(&self, begin: Instant) {
    *self.begin.lock().unwrap() = Some(begin);
  }

  pub(crate) fn begin(&self) -> Option<Instant> {
    *self.begin.lock().unwrap()
  }

  pub(crate) fn set_window(&self, warmup: Duration, duration: Duration) {
    *self.window.lock().unwrap() = (warmup, duration);
  }

  pub(crate) fn window(&self) -> (Duration, Duration) {
    *self.window.lock().unwrap()
  }

  pub(crate) fn set_capture_drain(&self, capture: bool) {
    *self.capture_drain.lock().unwrap() = capture;
  }

  pub(crate) fn set_events(&self, events: mpsc::UnboundedSender<Sample>) {
    *self.events.lock().unwrap() = events;
  }

  pub(crate) fn events(&self) -> mpsc::UnboundedSender<Sample> {
    self.events.lock().unwrap().clone()
  }

  pub(crate) fn send(&self, sample: Sample) {
    let _ = self.events.lock().unwrap().send(sample);
  }
}

#[derive(Clone)]
pub(crate) struct Driver {
  pub(crate) client: Client,
  pub(crate) origin: String,
  pub(crate) ws_origin: String,
  pub(crate) sessions: Arc<Vec<Session>>,
  pub(crate) manifest: Arc<Manifest>,
  pub(crate) images: Arc<Vec<Vec<u8>>>,
  pub(crate) browse_products: Arc<Vec<u64>>,
  pub(crate) trade_pairs: Arc<Vec<ResolvedTradePair>>,
  pub(crate) prepublished_images: Arc<Mutex<Vec<Option<String>>>>,
  pub(crate) sequence: Arc<AtomicU64>,
  pub(crate) pending: Deliveries,
  pub(crate) reporter: Arc<Reporter>,
  pub(crate) warmup: Duration,
  pub(crate) duration: Duration,
  pub(crate) run_id: String,
}

impl Driver {
  pub(crate) fn session(&self, user: usize) -> &Session {
    &self.sessions[user]
  }

  pub(crate) fn begin_instant(&self) -> Option<Instant> {
    self.reporter.begin()
  }

  pub(crate) fn phase_at(&self, start: Instant) -> Option<&'static str> {
    let begin = self.begin_instant()?;
    if start < begin {
      return None;
    }
    let elapsed = start.duration_since(begin);
    let (warmup, duration) = self.reporter.window();
    if elapsed < warmup {
      Some("warmup")
    } else if elapsed < warmup + duration {
      Some("measured")
    } else if *self.reporter.capture_drain.lock().unwrap() {
      Some("drain")
    } else {
      None
    }
  }

  pub(crate) fn record(
    &self,
    user: usize,
    op: &str,
    start: Instant,
    elapsed_ms: f64,
    ok: bool,
    status: Option<u16>,
  ) {
    let Some(phase) = self.phase_at(start) else {
      return;
    };
    self.reporter.send(Sample {
      user,
      operation: op.into(),
      elapsed_ms,
      ok,
      status,
      phase: phase.into(),
      details: None,
    });
  }

  pub(crate) fn request_id(&self) -> String {
    let scope: String = self
      .run_id
      .chars()
      .filter(char::is_ascii_graphic)
      .take(32)
      .collect();
    let scope = if scope.is_empty() { "run" } else { &scope };
    format!("{scope}-{}", self.sequence.fetch_add(1, Ordering::Relaxed))
  }

  pub(crate) fn idempotency_key(&self, user: usize, operation: &str) -> String {
    let sequence = self.sequence.fetch_add(1, Ordering::Relaxed);
    let scope: String = self
      .run_id
      .chars()
      .filter(char::is_ascii_graphic)
      .take(48)
      .collect();
    let scope = if scope.is_empty() { "run" } else { &scope };
    format!("lt-{scope}-{user}-{sequence}-{operation}")
  }

  pub(crate) fn prepared_image(&self, user: usize) -> Option<String> {
    self
      .prepublished_images
      .lock()
      .unwrap()
      .get(user)
      .cloned()
      .flatten()
  }

  pub(crate) fn remember_prepared_image(&self, user: usize, file_id: String) {
    let mut values = self.prepublished_images.lock().unwrap();
    if let Some(slot) = values.get_mut(user) {
      *slot = Some(file_id);
    }
  }

  pub(crate) async fn api(
    &self,
    user: usize,
    op: &str,
    method: Method,
    path: &str,
    body: Option<Value>,
  ) -> Result<Value> {
    let (_, data) = self
      .request(user, op, method, path, body, None, &[])
      .await?;
    Ok(data)
  }

  pub(crate) async fn api_expected(
    &self,
    user: usize,
    op: &str,
    method: Method,
    path: &str,
    body: Option<Value>,
    expected: &[u16],
  ) -> Result<(u16, Value)> {
    self
      .request(user, op, method, path, body, None, expected)
      .await
  }

  #[allow(clippy::too_many_arguments)]
  pub(crate) async fn api_with_key(
    &self,
    user: usize,
    op: &str,
    method: Method,
    path: &str,
    body: Option<Value>,
    key: &str,
    expected: &[u16],
  ) -> Result<(u16, Value)> {
    self
      .request(user, op, method, path, body, Some(key), expected)
      .await
  }

  #[allow(clippy::too_many_arguments)]
  pub(crate) async fn request(
    &self,
    user: usize,
    op: &str,
    method: Method,
    path: &str,
    body: Option<Value>,
    idempotency_key: Option<&str>,
    expected: &[u16],
  ) -> Result<(u16, Value)> {
    let start = Instant::now();
    let request_id = self.request_id();
    let session = self.session(user);
    let safe = matches!(
      method,
      Method::GET | Method::HEAD | Method::OPTIONS | Method::TRACE
    );
    let mut request = self
      .client
      .request(method, format!("{}/api/v1{path}", self.origin))
      .header(COOKIE, &session.cookie)
      .header("X-Request-ID", &request_id);
    if !safe {
      let generated = self.idempotency_key(user, op);
      request = request
        .header(ORIGIN, &self.origin)
        .header("X-CSRF-Token", &session.csrf)
        .header("Idempotency-Key", idempotency_key.unwrap_or(&generated));
    }
    if let Some(body) = body {
      request = request.json(&body);
    }
    let mut details = RequestDetails {
      request_id,
      started_ms: self.begin_instant().map_or(0., |begin| {
        start.saturating_duration_since(begin).as_secs_f64() * 1000.
      }),
      category: None,
      causes: vec![],
    };
    let mut status = None;
    let result = async {
      let response = request.send().await.map_err(|error| {
        let (category, causes) = classify(&error);
        details.category = Some(category);
        details.causes = causes;
        anyhow::anyhow!("request failed: {category}")
      })?;
      let code = response.status().as_u16();
      status = Some(code);
      let allowed = if expected.is_empty() {
        response.status().is_success()
      } else {
        expected.contains(&code)
      };
      if !allowed {
        details.category = Some("http_status");
      }
      ensure!(allowed, "HTTP {code}");
      let data = response.json::<Value>().await.map_err(|error| {
        let (category, causes) = classify(&error);
        details.category = Some(category);
        details.causes = causes;
        anyhow::anyhow!("response failed: {category}")
      })?;
      Ok((code, data))
    }
    .await;
    if let Some(phase) = self.phase_at(start) {
      self.reporter.send(Sample {
        user,
        operation: op.into(),
        elapsed_ms: start.elapsed().as_secs_f64() * 1000.,
        ok: result.is_ok(),
        status,
        phase: phase.into(),
        details: Some(details),
      });
    }
    result
  }

  /// Safe GET used by the recipient WebSocket path. It deliberately emits no
  /// HTTP sample; the caller measures the end-to-end retrieval separately.
  pub(crate) async fn get_untracked(&self, user: usize, path: &str) -> Result<Value> {
    let session = self.session(user);
    let response = self
      .client
      .get(format!("{}/api/v1{path}", self.origin))
      .header(COOKIE, &session.cookie)
      .header("X-Request-ID", self.request_id())
      .send()
      .await
      .map_err(|error| {
        let (category, _) = classify(&error);
        anyhow::anyhow!("retrieval transport failed: {category}")
      })?;
    ensure!(
      response.status().is_success(),
      "retrieval HTTP {}",
      response.status().as_u16()
    );
    response
      .json::<Value>()
      .await
      .context("retrieval response JSON")
  }
}

/// Parse a Set-Cookie header into its name/value pair, dropping attributes.
pub(crate) fn cookie_pair(set_cookie: &str) -> Option<(String, String)> {
  let pair = set_cookie.split(';').next()?.trim();
  let (name, value) = pair.split_once('=')?;
  let name = name.trim();
  if name.is_empty() {
    return None;
  }
  Some((name.to_string(), value.trim().to_string()))
}

pub(crate) fn cookie_value(pairs: &[(String, String)], name: &str) -> Option<String> {
  pairs
    .iter()
    .find(|(candidate, _)| candidate == name)
    .map(|(_, value)| value.clone())
}

fn response_cookies(headers: &reqwest::header::HeaderMap) -> Vec<(String, String)> {
  headers
    .get_all(SET_COOKIE)
    .iter()
    .filter_map(|value| value.to_str().ok())
    .filter_map(cookie_pair)
    .collect()
}

/// Authenticate one seeded account:
/// 1. GET entry-context captures the entry cookie and entry CSRF token.
/// 2. POST session with Origin, entry cookie and entry CSRF token.
/// 3. Capture the `__Host-se_session` and `__Host-se_csrf` cookies.
pub(crate) async fn login(
  client: &Client,
  origin: &str,
  email: &str,
  password: &str,
  expected_account_id: u64,
) -> Result<Session> {
  let entry = client
    .get(format!("{origin}/api/v1/account/entry-context"))
    .send()
    .await
    .map_err(|_| anyhow::anyhow!("entry-context transport failed"))?;
  ensure!(
    entry.status().is_success(),
    "entry-context rejected: {}",
    entry.status().as_u16()
  );
  let entry_cookies = response_cookies(entry.headers());
  let entry_cookie = cookie_value(&entry_cookies, ENTRY_COOKIE)
    .context("entry cookie missing from entry-context")?;
  let context: Value = entry.json().await.context("entry-context response JSON")?;
  let entry_csrf = context["csrf_token"]
    .as_str()
    .or_else(|| context["csrfToken"].as_str())
    .filter(|token| !token.is_empty())
    .context("entry csrf token missing")?;

  let response = client
    .post(format!("{origin}/api/v1/account/session"))
    .header(ORIGIN, origin)
    .header("X-CSRF-Token", entry_csrf)
    .header(COOKIE, format!("{ENTRY_COOKIE}={entry_cookie}"))
    .json(&serde_json::json!({"email": email, "password": password}))
    .send()
    .await
    .map_err(|_| anyhow::anyhow!("session transport failed"))?;
  ensure!(
    response.status().is_success(),
    "session rejected: {}",
    response.status().as_u16()
  );
  let cookies = response_cookies(response.headers());
  let session_cookie =
    cookie_value(&cookies, SESSION_COOKIE).context("session cookie missing from login response")?;
  let csrf_cookie =
    cookie_value(&cookies, CSRF_COOKIE).context("csrf cookie missing from login response")?;
  let identity: Value = response.json().await.context("login response JSON")?;
  let account_id = id_value(
    identity["account"]
      .get("account_id")
      .or_else(|| identity["account"].get("accountId"))
      .unwrap_or(&Value::Null),
  )
  .context("login account id missing")?;
  ensure!(account_id == expected_account_id, "target account mismatch");
  Ok(Session {
    cookie: format!("{SESSION_COOKIE}={session_cookie}"),
    csrf: csrf_cookie,
    account_id,
  })
}

#[cfg(test)]
mod tests {
  use super::*;
  use serde_json::json;
  use tokio::io::{AsyncReadExt, AsyncWriteExt};

  #[test]
  fn extracts_cookie_values_and_ignores_attributes() {
    let pairs = [
      cookie_pair("__Host-se_session=abc.def; Path=/; Secure; HttpOnly; SameSite=Lax").unwrap(),
      cookie_pair("__Host-se_csrf=token%2Bvalue; Path=/; Secure; SameSite=Lax").unwrap(),
    ];
    assert_eq!(
      cookie_value(&pairs, SESSION_COOKIE).as_deref(),
      Some("abc.def")
    );
    assert_eq!(
      cookie_value(&pairs, CSRF_COOKIE).as_deref(),
      Some("token%2Bvalue")
    );
    assert!(cookie_pair("garbage").is_none());
  }

  #[tokio::test]
  async fn login_uses_entry_cookie_csrf_origin_then_captures_session_cookies() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let origin = format!("http://{}", listener.local_addr().unwrap());
    let server_origin = origin.clone();
    let server = tokio::spawn(async move {
      for index in 0..2 {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut request = Vec::new();
        let header_end = loop {
          let mut chunk = [0u8; 1024];
          let count = socket.read(&mut chunk).await.unwrap();
          assert!(count > 0);
          request.extend_from_slice(&chunk[..count]);
          if let Some(pos) = request.windows(4).position(|bytes| bytes == b"\r\n\r\n") {
            break pos + 4;
          }
          assert!(request.len() < 16_384);
        };
        let headers = String::from_utf8_lossy(&request[..header_end]).to_lowercase();
        let body = if index == 0 {
          assert!(headers.starts_with("get /api/v1/account/entry-context "));
          (json!({"csrf_token": "entry-csrf", "expires_at": "2030-01-01T00:00:00Z"})).to_string()
        } else {
          assert!(headers.starts_with("post /api/v1/account/session "));
          assert!(headers.contains(&format!("origin: {}", server_origin.to_lowercase())));
          assert!(headers.contains("x-csrf-token: entry-csrf"));
          assert!(headers.contains("cookie: __host-se_entry=entry-cookie"));
          let length: usize = headers
            .lines()
            .find_map(|line| line.strip_prefix("content-length: "))
            .unwrap()
            .trim()
            .parse()
            .unwrap();
          while request.len() < header_end + length {
            let mut chunk = [0u8; 1024];
            let count = socket.read(&mut chunk).await.unwrap();
            assert!(count > 0);
            request.extend_from_slice(&chunk[..count]);
          }
          let payload: Value =
            serde_json::from_slice(&request[header_end..header_end + length]).unwrap();
          assert_eq!(payload["email"], "a@example.com");
          assert_eq!(payload["password"], "secret");
          json!({"account": {"account_id": "11"}}).to_string()
        };
        let cookies = if index == 0 {
          "Set-Cookie: __Host-se_entry=entry-cookie; Path=/; Secure; HttpOnly\r\n".to_string()
        } else {
          "Set-Cookie: __Host-se_session=session-value; Path=/; Secure; HttpOnly\r\n\
                     Set-Cookie: __Host-se_csrf=csrf-value; Path=/; Secure\r\n"
            .to_string()
        };
        let response = format!(
          "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n{cookies}Content-Length: {}\r\nConnection: close\r\n\r\n{}",
          body.len(),
          body
        );
        socket.write_all(response.as_bytes()).await.unwrap();
      }
    });
    let client = Client::builder()
      .retry(reqwest::retry::never())
      .build()
      .unwrap();
    let session = login(&client, &origin, "a@example.com", "secret", 11)
      .await
      .unwrap();
    assert_eq!(session.account_id, 11);
    assert_eq!(session.cookie, "__Host-se_session=session-value");
    assert_eq!(session.csrf, "csrf-value");
    tokio::time::timeout(Duration::from_secs(5), server)
      .await
      .unwrap()
      .unwrap();
  }
}
