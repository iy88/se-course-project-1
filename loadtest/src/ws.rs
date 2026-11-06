use crate::model::Sample;
use anyhow::{Context, Result, ensure};
use futures_util::{SinkExt, StreamExt};
use serde_json::{Value, json};
use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use tokio::{
    sync::{mpsc, oneshot},
    time::timeout,
};
use tokio_tungstenite::{
    connect_async,
    tungstenite::{Message, client::IntoClientRequest},
};
pub(crate) struct Pending {
    pub(crate) recipient: usize,
    pub(crate) sender: u64,
    pub(crate) conversation: u64,
    pub(crate) started: Instant,
    pub(crate) tx: oneshot::Sender<f64>,
}
pub(crate) type Deliveries = Arc<Mutex<HashMap<String, Pending>>>;

/// The load driver requires protocol v2 (ticket handshake + user_seq ACK).
/// Old backends without `/api/v1/realtime/ticket` fail here explicitly rather
/// than silently falling back to the query-token protocol.
pub(crate) async fn ticket(
    origin: &str,
    token: &str,
) -> Result<(String, String, u64, u64)> {
    let client = reqwest::Client::builder()
        .retry(reqwest::retry::never())
        .timeout(Duration::from_secs(15))
        .build()?;
    // A fresh load session measures subsequent traffic, not retained business
    // history from earlier runs of the same persistent seed. Events committed
    // after this watermark are still covered by the server's replay boundary.
    let watermark = client
        .get(format!("{origin}/api/v1/realtime/watermark"))
        .bearer_auth(token)
        .send()
        .await
        .map_err(|_| anyhow::anyhow!("WS watermark transport failed"))?;
    ensure!(watermark.status().is_success(), "WS watermark rejected");
    let watermark: Value = watermark.json().await.context("WS watermark JSON")?;
    let since = watermark["high_seq"].as_u64().context("WS watermark missing")?;
    let response = timeout(
        Duration::from_secs(15),
        client
            .post(format!("{origin}/api/v1/realtime/ticket"))
            .bearer_auth(token)
            .json(&json!({"since": since}))
            .send(),
    )
    .await
    .context("WS ticket timeout")?
    .context("WS ticket transport")?;
    ensure!(
        response.status().is_success(),
        "WS ticket rejected (backend protocol v2 required): {}",
        response.status().as_u16()
    );
    let data: Value = response.json().await.context("WS ticket JSON")?;
    let ticket = data["ticket"]
        .as_str()
        .context("WS ticket missing")?
        .to_string();
    let path = data["ws_path"].as_str().unwrap_or("/ws").to_string();
    let version = data["protocol_version"].as_u64().unwrap_or(0);
    ensure!(version >= 2, "backend realtime protocol is older than v2");
    Ok((ticket, path, version, since))
}

fn advance_cursor(last: &mut u64, event: &Value) -> Result<bool> {
    let seq = event["user_seq"].as_u64().context("invalid WS event sequence")?;
    ensure!(seq > 0 && event["event_id"].as_str().is_some_and(|id| !id.is_empty()),
            "invalid WS event identity");
    ensure!(seq <= last.saturating_add(1), "WS event sequence gap");
    if seq <= *last {
        return Ok(false);
    }
    *last = seq;
    Ok(true)
}

/// Extract a measurable message delivery from an event envelope.
pub(crate) fn delivery_payload(v: &Value) -> Option<&Value> {
    if v["type"] != "event" {
        return None;
    }
    let payload = &v["payload"];
    (payload["type"] == "message").then_some(payload)
}

pub(crate) fn ack_json(event: &Value) -> Option<String> {
    let seq = event["user_seq"].as_u64()?;
    let id = event["event_id"].as_str()?;
    Some(json!({"type": "ack", "user_seq": seq, "event_id": id}).to_string())
}

pub(crate) async fn socket(
    origin: &str,
    ws_base_origin: &str,
    token: &str,
    user: usize,
    pending: Deliveries,
    events: mpsc::UnboundedSender<Sample>,
) -> Result<tokio::task::JoinHandle<()>> {
    let (ticket, path, _version, mut last_seq) = ticket(origin, token).await?;
    let ws_origin = ws_base_origin.replacen("http", "ws", 1);
    let mut request = format!("{ws_origin}{path}?ticket={ticket}")
        .into_client_request()
        .context("invalid WS URL")?;
    request.headers_mut().insert(
        "origin",
        origin.parse().context("invalid WS origin")?,
    );
    let (mut ws, _) = timeout(Duration::from_secs(15), connect_async(request))
        .await
        .context("WS connect timeout")?
        .map_err(|_| anyhow::anyhow!("WS connect failed"))?;

    // Wait for the server's hello and durable replay boundary before traffic
    // starts. Receiving events before replay_complete is expected and buffered
    // by the server, not treated as a handshake failure.
    timeout(Duration::from_secs(15), async {
        loop {
            let frame = ws.next().await.context("WS closed during handshake")??;
            let Some(text) = frame.to_text().ok() else { continue; };
            let Ok(value) = serde_json::from_str::<Value>(text) else { continue; };
            match value["type"].as_str() {
                Some("hello") => {}
                Some("replay_complete") => return Ok::<(), anyhow::Error>(()),
                Some("resync_required") => anyhow::bail!("WS requires resync during handshake"),
                Some("event") => {
                    advance_cursor(&mut last_seq, &value)?;
                    if let Some(ack) = ack_json(&value) {
                        ws.send(Message::Text(ack.into())).await?;
                    }
                }
                _ => continue,
            }
        }
    })
    .await
    .context("WS auth timeout")??;

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
                    if v["type"] == "resync_required" {
                        let _ = events.send(Sample {
                            user,
                            operation: "ws_resync_required".into(),
                            elapsed_ms: 0.,
                            ok: false,
                            status: None,
                            phase: "runtime".into(),
                            details: None,
                        });
                        break;
                    }
                    if v["type"] != "event" { continue; }
                    let first = match advance_cursor(&mut last_seq, &v) {
                        Ok(first) => first,
                        Err(_) => {
                            let _ = events.send(Sample {
                                user, operation: "ws_protocol_error".into(), elapsed_ms: 0.,
                                ok: false, status: None, phase: "runtime".into(), details: None,
                            });
                            break;
                        }
                    };
                    if first
                        && let Some(payload) = delivery_payload(&v)
                        && let Some(key) = payload["content"].as_str()
                    {
                        let mut map = pending.lock().unwrap();
                        if map.get(key).is_some_and(|p| p.recipient == user && Some(p.sender) == payload["sender_id"].as_u64()
                            && Some(p.conversation) == payload["conversation_id"].as_u64())
                            && let Some(p) = map.remove(key) {
                            let _ = p.tx.send(p.started.elapsed().as_secs_f64()*1000.);
                        }
                    }
                    if let Some(ack) = ack_json(&v) {
                        let _ = ws.send(Message::Text(ack.into())).await;
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

#[cfg(test)]
mod tests {
    use super::{ack_json, advance_cursor, delivery_payload};
    use serde_json::json;

    #[tokio::test]
    async fn ticket_uses_current_watermark_instead_of_replaying_seed_history() {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let origin = format!("http://{}", listener.local_addr().unwrap());
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
                    assert!(request.len() < 8192);
                };
                let headers = String::from_utf8_lossy(&request[..header_end]).to_lowercase();
                assert!(headers.contains("authorization: bearer test-token"));
                let body = if index == 0 {
                    assert!(headers.starts_with("get /api/v1/realtime/watermark "));
                    json!({"high_seq": 9001}).to_string()
                } else {
                    assert!(headers.starts_with("post /api/v1/realtime/ticket "));
                    let length: usize = headers.lines().find_map(|line| line.strip_prefix("content-length: "))
                        .unwrap().trim().parse().unwrap();
                    while request.len() < header_end + length {
                        let mut chunk = [0u8; 1024];
                        let count = socket.read(&mut chunk).await.unwrap();
                        assert!(count > 0);
                        request.extend_from_slice(&chunk[..count]);
                    }
                    let payload: serde_json::Value = serde_json::from_slice(&request[header_end..header_end + length]).unwrap();
                    assert_eq!(payload["since"], 9001);
                    json!({"ticket": "one-use", "ws_path": "/ws", "protocol_version": 2}).to_string()
                };
                let response = format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", body.len(), body);
                socket.write_all(response.as_bytes()).await.unwrap();
            }
        });
        let result = super::ticket(&origin, "test-token").await.unwrap();
        assert_eq!(result, ("one-use".into(), "/ws".into(), 2, 9001));
        tokio::time::timeout(std::time::Duration::from_secs(5), server).await.unwrap().unwrap();
    }

    #[test]
    fn event_envelope_extracts_legacy_payload_and_ack() {
        let event = json!({
            "type": "event",
            "event_id": "e-1",
            "user_seq": 4,
            "payload": {"type": "message", "content": "hello", "sender_id": 2, "conversation_id": 9}
        });
        assert_eq!(delivery_payload(&event).unwrap()["content"], "hello");
        let ack: serde_json::Value = serde_json::from_str(&ack_json(&event).unwrap()).unwrap();
        assert_eq!(ack["user_seq"], 4);
        assert_eq!(ack["event_id"], "e-1");
    }

    #[test]
    fn non_message_or_malformed_event_is_ignored() {
        assert!(delivery_payload(&json!({"type": "event", "payload": {"type": "notification"}})).is_none());
        assert!(delivery_payload(&json!({"type": "message"})).is_none());
        assert!(ack_json(&json!({"type": "event"})).is_none());
    }

    #[test]
    fn cursor_dedupes_without_an_unbounded_event_id_set_and_rejects_gaps() {
        let mut cursor = 41;
        let event = json!({"user_seq":42,"event_id":"e-42"});
        assert!(advance_cursor(&mut cursor, &event).unwrap());
        assert!(!advance_cursor(&mut cursor, &event).unwrap());
        assert!(advance_cursor(&mut cursor, &json!({"user_seq":44,"event_id":"e-44"})).is_err());
        assert_eq!(cursor, 42);
        assert!(advance_cursor(&mut cursor, &json!({"user_seq":43})).is_err());
    }
}
