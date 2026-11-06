use crate::model::Sample;
use anyhow::{Context, Result, ensure};
use futures_util::{SinkExt, StreamExt};
use serde_json::Value;
use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use tokio::{
    sync::{mpsc, oneshot},
    time::timeout,
};
use tokio_tungstenite::{connect_async, tungstenite::Message};
pub(crate) struct Pending {
    pub(crate) recipient: usize,
    pub(crate) sender: u64,
    pub(crate) conversation: u64,
    pub(crate) started: Instant,
    pub(crate) tx: oneshot::Sender<f64>,
}
pub(crate) type Deliveries = Arc<Mutex<HashMap<String, Pending>>>;

pub(crate) async fn socket(
    origin: &str,
    token: &str,
    user: usize,
    pending: Deliveries,
    events: mpsc::UnboundedSender<Sample>,
) -> Result<tokio::task::JoinHandle<()>> {
    let ws_origin = origin.replacen("http", "ws", 1);
    let (mut ws, _) = timeout(
        Duration::from_secs(15),
        connect_async(format!("{ws_origin}/ws?token={token}")),
    )
    .await
    .context("WS connect timeout")?
    .map_err(|_| anyhow::anyhow!("WS connect failed"))?;
    ws.send(Message::Text(r#"{"type":"ping"}"#.into()))
        .await
        .map_err(|_| anyhow::anyhow!("WS ping failed"))?;
    let ready = timeout(Duration::from_secs(15), ws.next())
        .await
        .context("WS auth timeout")?
        .context("WS closed")?
        .map_err(|_| anyhow::anyhow!("WS read failed"))?;
    ensure!(
        ready
            .to_text()
            .ok()
            .and_then(|s| serde_json::from_str::<Value>(s).ok())
            .is_some_and(|v| v["type"] == "pong"),
        "WS not authenticated"
    );
    Ok(tokio::spawn(async move {
        let mut heartbeat = tokio::time::interval(Duration::from_secs(20));
        loop {
            tokio::select! {
                _ = heartbeat.tick() => {
                    if ws.send(Message::Text(r#"{"type":"ping"}"#.into())).await.is_err() { break; }
                }
                frame = ws.next() => {
                    let Some(Ok(frame)) = frame else { break; };
                    if frame.is_close() { break; }
                    let Ok(text) = frame.to_text() else { continue; };
                    let Ok(v) = serde_json::from_str::<Value>(text) else { continue; };
                    if v["type"] != "message" { continue; }
                    if let Some(key) = v["content"].as_str() {
                        let mut map = pending.lock().unwrap();
                        if map.get(key).is_some_and(|p| p.recipient == user && Some(p.sender) == v["sender_id"].as_u64()
                            && Some(p.conversation) == v["conversation_id"].as_u64())
                            && let Some(p) = map.remove(key) {
                            let _ = p.tx.send(p.started.elapsed().as_secs_f64()*1000.);
                        }
                    }
                }
            }
        }
        let _ = events.send(Sample {
            user,
            operation: "ws_disconnect".into(),
            elapsed_ms: 0.,
            ok: false,
            status: None,
            phase: "runtime".into(),
            details: None,
        });
    }))
}
