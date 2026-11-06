use crate::diagnostics::{RequestDetails, classify};
use anyhow::{Result, ensure};
use reqwest::{Client, Method};
use serde_json::Value;
use std::sync::atomic::{AtomicU64, Ordering};
use std::{
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::mpsc;

use crate::{
    model::{Manifest, Sample},
    ws::Deliveries,
};
#[derive(Clone)]
pub(crate) struct Driver {
    pub(crate) client: Client,
    pub(crate) origin: String,
    pub(crate) tokens: Arc<Vec<String>>,
    pub(crate) manifest: Arc<Manifest>,
    pub(crate) images: Arc<Vec<Vec<u8>>>,
    pub(crate) sequence: Arc<AtomicU64>,
    pub(crate) pending: Deliveries,
    pub(crate) events: mpsc::UnboundedSender<Sample>,
    pub(crate) begin: Instant,
    pub(crate) warmup: Duration,
    pub(crate) duration: Duration,
    pub(crate) run_id: String,
    pub(crate) capture_drain: bool,
    pub(crate) detail_range_end: Option<usize>,
}
impl Driver {
    pub(crate) fn phase_at(&self, start: Instant) -> Option<&'static str> {
        if start < self.begin {
            return None;
        }
        let elapsed = start.duration_since(self.begin);
        if elapsed < self.warmup {
            Some("warmup")
        } else if elapsed < self.warmup + self.duration {
            Some("measured")
        } else if self.capture_drain {
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
        let _ = self.events.send(Sample {
            user,
            operation: op.into(),
            elapsed_ms,
            ok,
            status,
            phase: phase.into(),
            details: None,
        });
    }
    pub(crate) async fn api(
        &self,
        user: usize,
        op: &str,
        method: Method,
        path: &str,
        body: Option<Value>,
    ) -> Result<Value> {
        let (_, data) = self.api_expected(user, op, method, path, body, &[]).await?;
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
        let start = Instant::now();
        let request_id = format!(
            "{}-{}",
            self.run_id,
            self.sequence.fetch_add(1, Ordering::Relaxed)
        );
        let mut request = self
            .client
            .request(method, format!("{}/api/v1{path}", self.origin))
            .bearer_auth(&self.tokens[user])
            .header("X-Request-ID", &request_id);
        if let Some(body) = body {
            request = request.json(&body);
        }
        let mut details = RequestDetails {
            request_id,
            started_ms: start.saturating_duration_since(self.begin).as_secs_f64() * 1000.,
            category: None,
            causes: vec![],
        };
        let mut status = None;
        let result = async {
            let response = request.send().await.map_err(|e| {
                let (category, causes) = classify(&e);
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
            let data = response.json::<Value>().await.map_err(|e| {
                let (category, causes) = classify(&e);
                details.category = Some(category);
                details.causes = causes;
                anyhow::anyhow!("response failed: {category}")
            })?;
            Ok((code, data))
        }
        .await;
        if let Some(phase) = self.phase_at(start) {
            let _ = self.events.send(Sample {
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
    pub(crate) async fn post(&self, u: usize, op: &str, path: &str, body: Value) -> Result<Value> {
        self.api(u, op, Method::POST, path, Some(body)).await
    }
}
