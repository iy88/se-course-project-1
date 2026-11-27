use crate::{
  http::Driver,
  model::{Sample, id_string, id_value},
};
use anyhow::{Context, Result, ensure};
use futures_util::{SinkExt, StreamExt};
use serde_json::{Value, json};
use std::{
  collections::HashMap,
  sync::{Arc, Mutex},
  time::{Duration, Instant},
};
use tokio::{
  net::TcpStream,
  sync::{oneshot, watch},
  time::timeout,
};
use tokio_tungstenite::{
  MaybeTlsStream, WebSocketStream, connect_async,
  tungstenite::{Message, client::IntoClientRequest},
};

pub(crate) struct Pending {
  pub(crate) recipient: usize,
  pub(crate) conversation_kind: String,
  pub(crate) conversation: u64,
  started: Instant,
  expected: Option<DeliveryObservation>,
  early: Option<EarlyDelivery>,
  tx: oneshot::Sender<DeliveryResult>,
}
pub(crate) type Deliveries = Arc<Mutex<HashMap<String, Pending>>>;

#[derive(Clone, Debug, PartialEq, Eq)]
struct DeliveryObservation {
  message_id: String,
  message_seq: u64,
}

#[derive(Debug)]
struct EarlyDelivery {
  observation: DeliveryObservation,
  elapsed_ms: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub(crate) struct DeliveryResult {
  pub(crate) elapsed_ms: f64,
  pub(crate) matched: bool,
}

pub(crate) enum PendingProgress {
  Waiting,
  Complete(DeliveryResult),
}

impl Pending {
  pub(crate) fn new(
    recipient: usize,
    conversation_kind: String,
    conversation: u64,
    started: Instant,
    tx: oneshot::Sender<DeliveryResult>,
  ) -> Self {
    Self {
      recipient,
      conversation_kind,
      conversation,
      started,
      expected: None,
      early: None,
      tx,
    }
  }

  fn observation(hint: &DeliveryHint) -> DeliveryObservation {
    DeliveryObservation {
      message_id: hint.message_id.clone(),
      message_seq: hint.message_seq,
    }
  }

  /// A recipient hint can be delivered before the sender has the HTTP response.
  /// Keep its real arrival time, then validate it after the send response binds
  /// the expected message ID and sequence.
  pub(crate) fn elapsed_ms(&self) -> f64 {
    self.started.elapsed().as_secs_f64() * 1000.
  }

  fn retrieved(&mut self, hint: &DeliveryHint, elapsed_ms: f64) -> PendingProgress {
    let observation = Self::observation(hint);
    if let Some(expected) = &self.expected {
      return PendingProgress::Complete(DeliveryResult {
        elapsed_ms,
        matched: expected == &observation,
      });
    }
    if self.early.is_none() {
      self.early = Some(EarlyDelivery {
        observation,
        elapsed_ms,
      });
    }
    PendingProgress::Waiting
  }

  pub(crate) fn sent(&mut self, message_id: String, message_seq: u64) -> PendingProgress {
    self.expected = Some(DeliveryObservation {
      message_id,
      message_seq,
    });
    let Some(early) = self.early.take() else {
      return PendingProgress::Waiting;
    };
    PendingProgress::Complete(DeliveryResult {
      elapsed_ms: early.elapsed_ms,
      matched: self.expected.as_ref() == Some(&early.observation),
    })
  }

  pub(crate) fn finish(self, result: DeliveryResult) {
    let _ = self.tx.send(result);
  }
}

type Socket = WebSocketStream<MaybeTlsStream<TcpStream>>;

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct DeliveryHint {
  pub(crate) conversation_kind: String,
  pub(crate) conversation_id: u64,
  pub(crate) message_id: String,
  pub(crate) message_seq: u64,
}

#[derive(Clone, Debug)]
pub(crate) struct Head {
  pub(crate) epoch: String,
  pub(crate) head_seq: u64,
  pub(crate) replay_floor: u64,
}

#[derive(Clone, Debug)]
struct Cursor {
  epoch: String,
  last: u64,
}

#[derive(Debug)]
enum Outcome {
  Planned,
  Closed(u16),
  Transport,
  Protocol,
}

/// First client frame for protocol v1. The server never requires a ticket or a
/// query token; identity comes from the session Cookie header.
pub(crate) fn hello_frame(csrf_token: &str, epoch: &str, after_seq: u64) -> String {
  json!({
      "type": "hello",
      "protocol_version": 1,
      "csrf_token": csrf_token,
      "cursor": {"epoch": epoch, "after_seq": after_seq}
  })
  .to_string()
}

/// ACK for an event (`account_seq`) or a cursor advance (`through_seq`).
pub(crate) fn ack_frame(epoch: &str, through_seq: u64) -> String {
  json!({"type": "ack", "epoch": epoch, "through_seq": through_seq}).to_string()
}

pub(crate) fn resume_frame(epoch: &str, after_seq: u64) -> String {
  json!({"type": "resume", "epoch": epoch, "after_seq": after_seq}).to_string()
}

pub(crate) fn pong_frame(nonce: &str) -> String {
  json!({"type": "pong", "nonce": nonce}).to_string()
}

fn event_sequence(value: &Value) -> Option<u64> {
  value["account_seq"].as_u64().filter(|seq| *seq > 0)
}

fn advance_event(last: &mut u64, seq: u64) -> Result<bool> {
  ensure!(seq > 0, "event sequence must be positive");
  if seq <= *last {
    return Ok(false);
  }
  ensure!(seq == last.saturating_add(1), "event sequence gap");
  *last = seq;
  Ok(true)
}

fn advance_cursor(last: &mut u64, through_seq: u64) -> Result<bool> {
  if through_seq <= *last {
    return Ok(false);
  }
  *last = through_seq;
  Ok(true)
}

/// The message hint carries no body. The recipient must read the message back
/// through the authoritative HTTP endpoint before a delivery is considered
/// complete.
pub(crate) fn delivery_hint(value: &Value) -> Option<DeliveryHint> {
  if value["type"] != "event" {
    return None;
  }
  let data = &value["data"];
  let conversation_kind = data["conversation_kind"]
    .as_str()
    .filter(|kind| matches!(*kind, "chat" | "trade" | "case"))?;
  let conversation_id = id_value(&data["conversation_id"])?;
  let message_id = id_string(&data["message_id"])?;
  let message_seq = data["message_seq"].as_u64().filter(|seq| *seq > 0)?;
  Some(DeliveryHint {
    conversation_kind: conversation_kind.to_string(),
    conversation_id,
    message_id,
    message_seq,
  })
}

/// Find the message named by the hint. Returns its body only when both the
/// message id and sequence match; callers separately require the body to equal
/// the content the sender posted.
pub(crate) fn matched_message(page: &Value, hint: &DeliveryHint) -> Option<String> {
  page["items"].as_array()?.iter().find_map(|item| {
    (id_string(&item["message_id"]).as_deref() == Some(hint.message_id.as_str())
      && item["seq"].as_u64() == Some(hint.message_seq))
    .then(|| item["body"].as_str().map(str::to_string))
    .flatten()
  })
}

fn websocket_url(origin: &str) -> Result<String> {
  if let Some(rest) = origin.strip_prefix("https://") {
    return Ok(format!("wss://{rest}/api/v1/realtime"));
  }
  if let Some(rest) = origin.strip_prefix("http://") {
    return Ok(format!("ws://{rest}/api/v1/realtime"));
  }
  anyhow::bail!("WS origin must be HTTP(S)")
}

async fn head(driver: &Driver, user: usize) -> Result<Head> {
  let value = driver
    .get_untracked(user, "/account/events/head")
    .await
    .context("events head failed")?;
  let epoch = value["epoch"]
    .as_str()
    .filter(|epoch| !epoch.is_empty())
    .context("events head epoch missing")?
    .to_string();
  let head_seq = value["head_seq"]
    .as_u64()
    .context("events head_seq missing")?;
  let replay_floor = value["replay_floor"].as_u64().unwrap_or(0);
  Ok(Head {
    epoch,
    head_seq,
    replay_floor,
  })
}

async fn connect_once(
  driver: &Driver,
  user: usize,
  cursor: &Cursor,
) -> Result<(Socket, String, u64)> {
  let url = websocket_url(&driver.ws_origin)?;
  let session = driver.session(user);
  let mut request = url.into_client_request().context("invalid WS URL")?;
  request.headers_mut().insert(
    "origin",
    driver.origin.parse().context("invalid WS origin")?,
  );
  request.headers_mut().insert(
    "cookie",
    session.cookie.parse().context("invalid session cookie")?,
  );
  let (mut socket, _) = timeout(Duration::from_secs(15), connect_async(request))
    .await
    .context("WS connect timeout")?
    .map_err(|_| anyhow::anyhow!("WS connect failed"))?;
  let hello = hello_frame(&session.csrf, &cursor.epoch, cursor.last);
  timeout(Duration::from_secs(15), async {
    socket
      .send(Message::Text(hello.into()))
      .await
      .context("WS hello send failed")?;
    loop {
      let frame = socket
        .next()
        .await
        .context("WS closed during handshake")?
        .context("WS handshake transport failed")?;
      let Message::Text(text) = frame else {
        if frame.is_close() {
          anyhow::bail!("WS closed during handshake");
        }
        continue;
      };
      let Ok(value) = serde_json::from_str::<Value>(&text) else {
        continue;
      };
      match value["type"].as_str() {
        Some("hello_ok") => {
          let epoch = value["epoch"]
            .as_str()
            .filter(|epoch| !epoch.is_empty())
            .context("WS hello_ok epoch missing")?
            .to_string();
          let replay_floor = value["replay_floor"].as_u64().unwrap_or(0);
          if let Some(nonce) = value["nonce"].as_str() {
            socket.send(Message::Text(pong_frame(nonce).into())).await?;
          }
          return Ok::<_, anyhow::Error>((epoch, replay_floor));
        }
        Some("ping") => {
          if let Some(nonce) = value["nonce"].as_str() {
            socket.send(Message::Text(pong_frame(nonce).into())).await?;
          }
        }
        Some("auth_required" | "dependency_unavailable") => {
          anyhow::bail!("WS rejected the session during handshake")
        }
        Some(other) => anyhow::bail!("unexpected WS handshake frame: {other}"),
        None => anyhow::bail!("WS handshake frame missing type"),
      }
    }
  })
  .await
  .context("WS hello timeout")?
  .map(|(epoch, replay_floor)| (socket, epoch, replay_floor))
}

pub(crate) async fn socket(
  driver: &Driver,
  user: usize,
  shutdown: watch::Receiver<bool>,
) -> Result<tokio::task::JoinHandle<()>> {
  let mut cursor = head(driver, user).await.map(|head| Cursor {
    epoch: head.epoch,
    last: head.head_seq,
  })?;
  let (socket, epoch, replay_floor) = connect_once(driver, user, &cursor).await?;
  if epoch != cursor.epoch {
    cursor.epoch = epoch;
    cursor.last = replay_floor;
  }
  let driver = driver.clone();
  Ok(tokio::spawn(async move {
    run(driver, user, socket, cursor, shutdown).await;
  }))
}

async fn run(
  driver: Driver,
  user: usize,
  mut socket: Socket,
  mut cursor: Cursor,
  mut shutdown: watch::Receiver<bool>,
) {
  let mut backoff = Duration::from_millis(250);
  loop {
    if *shutdown.borrow() {
      let _ = socket.send(Message::Close(None)).await;
      return;
    }
    let outcome = run_socket(&driver, user, &mut socket, &mut cursor, &mut shutdown).await;
    match outcome {
      Outcome::Planned => return,
      Outcome::Closed(code) => {
        runtime_sample(&driver, user, &format!("ws_close_{code}"), false);
        runtime_sample(&driver, user, "ws_disconnect", false);
        if matches!(code, 4401 | 4403) {
          return;
        }
      }
      Outcome::Transport => {
        runtime_sample(&driver, user, "ws_disconnect", false);
      }
      Outcome::Protocol => {
        runtime_sample(&driver, user, "ws_protocol_error", false);
        runtime_sample(&driver, user, "ws_disconnect", false);
      }
    }
    let Some((next_socket, next_cursor)) =
      reconnect(&driver, user, cursor, &mut shutdown, &mut backoff).await
    else {
      return;
    };
    socket = next_socket;
    cursor = next_cursor;
  }
}

async fn reconnect(
  driver: &Driver,
  user: usize,
  cursor: Cursor,
  shutdown: &mut watch::Receiver<bool>,
  backoff: &mut Duration,
) -> Option<(Socket, Cursor)> {
  loop {
    if *shutdown.borrow() {
      return None;
    }
    let head = head(driver, user).await;
    let candidate = match head {
      Ok(head) => {
        let next = if head.epoch == cursor.epoch {
          Cursor {
            epoch: head.epoch,
            last: if cursor.last < head.replay_floor {
              head.head_seq
            } else {
              cursor.last
            },
          }
        } else {
          Cursor {
            epoch: head.epoch,
            last: head.head_seq,
          }
        };
        connect_once(driver, user, &next)
          .await
          .map(|(socket, epoch, replay_floor)| {
            let mut next = next;
            if epoch != next.epoch {
              next.epoch = epoch;
              next.last = replay_floor;
            }
            (socket, next)
          })
      }
      Err(_) => Err(anyhow::anyhow!("events head failed")),
    };
    match candidate {
      Ok(connection) => return Some(connection),
      Err(_) => runtime_sample(driver, user, "ws_reconnect_failed", false),
    }
    let delay = *backoff;
    *backoff = (*backoff * 2).min(Duration::from_secs(5));
    tokio::select! {
        _ = tokio::time::sleep(delay) => {}
        changed = shutdown.changed() => {
            if changed.is_err() || *shutdown.borrow() {
                return None;
            }
        }
    }
  }
}

async fn run_socket(
  driver: &Driver,
  user: usize,
  socket: &mut Socket,
  cursor: &mut Cursor,
  shutdown: &mut watch::Receiver<bool>,
) -> Outcome {
  loop {
    tokio::select! {
        changed = shutdown.changed() => {
            if changed.is_err() || *shutdown.borrow() {
                let _ = socket.send(Message::Close(None)).await;
                return Outcome::Planned;
            }
        }
        frame = socket.next() => {
            let Some(Ok(frame)) = frame else { return Outcome::Transport; };
            match frame {
                Message::Close(close) => {
                    return Outcome::Closed(close.map_or(1000, |frame| u16::from(frame.code)));
                }
                Message::Ping(payload) => {
                    if socket.send(Message::Pong(payload)).await.is_err() {
                        return Outcome::Transport;
                    }
                }
                Message::Pong(_) | Message::Frame(_) => {}
                Message::Binary(_) => {}
                Message::Text(text) => {
                    let Ok(value) = serde_json::from_str::<Value>(&text) else {
                        continue;
                    };
                    let Some(kind) = value["type"].as_str() else { continue; };
                    if kind == "ping" {
                        let Some(nonce) = value["nonce"].as_str() else {
                            return Outcome::Protocol;
                        };
                        if socket.send(Message::Text(pong_frame(nonce).into())).await.is_err() {
                            return Outcome::Transport;
                        }
                        continue;
                    }
                    match kind {
                        "event" => {
                            let Some(seq) = event_sequence(&value) else {
                                return Outcome::Protocol;
                            };
                            match advance_event(&mut cursor.last, seq) {
                                Ok(false) => continue,
                                Ok(true) => {}
                                Err(_) => return Outcome::Protocol,
                            }
                            if socket.send(Message::Text(ack_frame(&cursor.epoch, seq).into())).await.is_err() {
                                return Outcome::Transport;
                            }
                            if let Some(hint) = delivery_hint(&value)
                                && has_pending(driver, user, &hint)
                            {
                                spawn_retrieval(driver.clone(), user, hint);
                            }
                        }
                        "cursor_advance" => {
                            let Some(epoch) = value["epoch"].as_str() else {
                                return Outcome::Protocol;
                            };
                            if epoch != cursor.epoch {
                                return Outcome::Protocol;
                            }
                            let Some(through) = value["through_seq"].as_u64() else {
                                return Outcome::Protocol;
                            };
                            match advance_cursor(&mut cursor.last, through) {
                                Ok(false) => continue,
                                Ok(true) => {}
                                Err(_) => return Outcome::Protocol,
                            }
                            if socket.send(Message::Text(ack_frame(&cursor.epoch, through).into())).await.is_err() {
                                return Outcome::Transport;
                            }
                        }
                        "sync_reset" => {
                            let Some(epoch) = value["epoch"].as_str() else {
                                return Outcome::Protocol;
                            };
                            let Some(head_seq) = value["head_seq"].as_u64() else {
                                return Outcome::Protocol;
                            };
                            cursor.epoch = epoch.to_string();
                            cursor.last = head_seq;
                            if socket.send(Message::Text(resume_frame(epoch, head_seq).into())).await.is_err() {
                                return Outcome::Transport;
                            }
                            runtime_sample(driver, user, "ws_sync_reset", true);
                        }
                        "hello_ok" | "pong" | "auth_required" | "dependency_unavailable" => {}
                        _ => {}
                    }
                }
            }
        }
    }
  }
}

fn runtime_sample(driver: &Driver, user: usize, operation: &str, ok: bool) {
  driver.reporter.send(Sample {
    user,
    operation: operation.into(),
    elapsed_ms: 0.,
    ok,
    status: None,
    phase: "runtime".into(),
    details: None,
  });
}

fn has_pending(driver: &Driver, user: usize, hint: &DeliveryHint) -> bool {
  driver.pending.lock().unwrap().values().any(|pending| {
    pending.recipient == user
      && pending.conversation_kind == hint.conversation_kind
      && pending.conversation == hint.conversation_id
  })
}

fn spawn_retrieval(driver: Driver, user: usize, hint: DeliveryHint) {
  tokio::spawn(async move {
    let received = Instant::now();
    let path = format!(
      "/conversations/{}/{}/messages?after_seq={}&limit=20",
      hint.conversation_kind,
      hint.conversation_id,
      hint.message_seq.saturating_sub(1)
    );
    let result = driver.get_untracked(user, &path).await;
    let body = result
      .as_ref()
      .ok()
      .and_then(|page| matched_message(page, &hint));
    driver.record(
      user,
      "im_retrieval",
      received,
      received.elapsed().as_secs_f64() * 1000.,
      body.is_some(),
      None,
    );
    let Some(body) = body else {
      return;
    };
    let mut pending = driver.pending.lock().unwrap();
    let key = pending
      .iter()
      .find(|(content, candidate)| {
        candidate.recipient == user
          && candidate.conversation_kind == hint.conversation_kind
          && candidate.conversation == hint.conversation_id
          && content.as_str() == body
      })
      .map(|(content, _)| content.clone());
    let Some(key) = key else {
      return;
    };
    let candidate = pending.get_mut(&key).expect("pending key from same map");
    let elapsed_ms = candidate.elapsed_ms();
    let progress = candidate.retrieved(&hint, elapsed_ms);
    if let PendingProgress::Complete(result) = progress
      && let Some(candidate) = pending.remove(&key)
    {
      let _ = candidate.tx.send(result);
    }
  });
}

#[cfg(test)]
mod tests {
  use super::*;

  #[test]
  fn protocol_frames_are_protocol_v1_without_ticket_or_watermark() {
    let hello: Value = serde_json::from_str(&hello_frame("csrf", "epoch-1", 41)).unwrap();
    assert_eq!(hello["type"], "hello");
    assert_eq!(hello["protocol_version"], 1);
    assert_eq!(hello["csrf_token"], "csrf");
    assert_eq!(hello["cursor"]["epoch"], "epoch-1");
    assert_eq!(hello["cursor"]["after_seq"], 41);
    let ack: Value = serde_json::from_str(&ack_frame("epoch-1", 41)).unwrap();
    assert_eq!(
      ack,
      json!({"type": "ack", "epoch": "epoch-1", "through_seq": 41})
    );
    let resume: Value = serde_json::from_str(&resume_frame("epoch-1", 99)).unwrap();
    assert_eq!(
      resume,
      json!({"type": "resume", "epoch": "epoch-1", "after_seq": 99})
    );
    let pong: Value = serde_json::from_str(&pong_frame("n-1")).unwrap();
    assert_eq!(pong, json!({"type": "pong", "nonce": "n-1"}));
  }

  #[test]
  fn cursor_dedupes_events_and_accepts_cursor_advances() {
    let mut last = 41;
    assert!(advance_event(&mut last, 42).unwrap());
    assert!(!advance_event(&mut last, 42).unwrap());
    assert!(advance_event(&mut last, 44).is_err());
    assert_eq!(last, 42);
    assert!(advance_cursor(&mut last, 50).unwrap());
    assert_eq!(last, 50);
    assert!(!advance_cursor(&mut last, 50).unwrap());
    assert!(!advance_cursor(&mut last, 49).unwrap());
  }

  #[test]
  fn extracts_message_hint_and_requires_id_seq_and_body_to_match() {
    let event = json!({
        "type": "event",
        "epoch": "epoch-1",
        "event_id": "e-1",
        "account_seq": 7,
        "event_type": "message_created",
        "schema_version": 1,
        "data": {
            "conversation_kind": "chat",
            "conversation_id": "99",
            "message_id": "1234",
            "message_seq": 5
        }
    });
    let hint = delivery_hint(&event).unwrap();
    assert_eq!(hint.conversation_kind, "chat");
    assert_eq!(hint.conversation_id, 99);
    assert_eq!(hint.message_id, "1234");
    assert_eq!(hint.message_seq, 5);
    let page = json!({"items": [
        {"message_id": "1233", "seq": 4, "body": "older"},
        {"message_id": "1234", "seq": 5, "body": "hello"}
    ]});
    assert_eq!(matched_message(&page, &hint).as_deref(), Some("hello"));
    let mismatched = json!({"items": [{"message_id": "1234", "seq": 4, "body": "hello"}]});
    assert!(matched_message(&mismatched, &hint).is_none());
    assert!(
      delivery_hint(&json!({"type": "event", "data": {"conversation_kind": "chat"}})).is_none()
    );
  }

  #[test]
  fn non_message_events_are_ignored() {
    assert!(delivery_hint(&json!({"type": "hello_ok", "epoch": "e"})).is_none());
    assert!(
      delivery_hint(&json!({"type": "event", "data": {
          "conversation_kind": "notification", "conversation_id": "1",
          "message_id": "2", "message_seq": 3
      }}))
      .is_none()
    );
  }

  #[test]
  fn early_delivery_waits_for_send_response_and_keeps_received_time() {
    let (tx, mut rx) = oneshot::channel();
    let started = Instant::now() - Duration::from_millis(250);
    let mut pending = Pending::new(1, "chat".into(), 99, started, tx);
    let hint = DeliveryHint {
      conversation_kind: "chat".into(),
      conversation_id: 99,
      message_id: "1234".into(),
      message_seq: 5,
    };
    let elapsed_ms = pending.elapsed_ms();
    assert!(elapsed_ms >= 250.);
    assert!(matches!(
      pending.retrieved(&hint, elapsed_ms),
      PendingProgress::Waiting
    ));
    assert!(matches!(
      rx.try_recv(),
      Err(tokio::sync::oneshot::error::TryRecvError::Empty)
    ));
    let PendingProgress::Complete(result) = pending.sent("1234".into(), 5) else {
      panic!("early delivery was not completed after the send response");
    };
    assert!(result.matched);
    assert!(result.elapsed_ms >= 250.);
  }

  #[test]
  fn early_delivery_rejects_sender_id_or_sequence_mismatch() {
    for (message_id, message_seq) in [("9999", 5), ("1234", 6)] {
      let (tx, _rx) = oneshot::channel();
      let mut pending = Pending::new(1, "chat".into(), 99, Instant::now(), tx);
      let hint = DeliveryHint {
        conversation_kind: "chat".into(),
        conversation_id: 99,
        message_id: "1234".into(),
        message_seq: 5,
      };
      assert!(matches!(
        pending.retrieved(&hint, 7.25),
        PendingProgress::Waiting
      ));
      let PendingProgress::Complete(result) = pending.sent(message_id.into(), message_seq) else {
        panic!("mismatched delivery was not evaluated");
      };
      assert_eq!(
        result,
        DeliveryResult {
          elapsed_ms: 7.25,
          matched: false
        }
      );
    }
  }

  #[test]
  fn websocket_url_preserves_scheme_and_base_path() {
    assert_eq!(
      websocket_url("http://127.0.0.1:8000").unwrap(),
      "ws://127.0.0.1:8000/api/v1/realtime"
    );
    assert_eq!(
      websocket_url("https://example.test").unwrap(),
      "wss://example.test/api/v1/realtime"
    );
    assert!(websocket_url("ftp://example.test").is_err());
  }
}
