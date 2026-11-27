use crate::diagnostics::{RequestDetails, classify};
use crate::{
  http::Driver,
  model::{ResolvedTradePair, id_string, id_value},
  ws::{Pending, PendingProgress},
};
use anyhow::{Context, Result, ensure};
use reqwest::Method;
use serde_json::{Value, json};
use std::time::{Duration, Instant};
use tokio::{sync::oneshot, time::timeout};

const FUTURE_DELIVERY_AT: &str = "2099-01-01T00:00:00Z";

fn encode_component(value: &str) -> String {
  let mut encoded = String::new();
  for byte in value.as_bytes() {
    match byte {
      b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
        encoded.push(char::from(*byte));
      }
      _ => encoded.push_str(&format!("%{byte:02X}")),
    }
  }
  encoded
}

fn version(value: &Value) -> Result<u64> {
  value["version"].as_u64().context("trade version missing")
}

impl Driver {
  pub(crate) async fn browse(&self, user: usize, op: &str, step: usize) -> Result<()> {
    let path = match op {
      "home" => "/products?page_size=20".to_string(),
      "search" => {
        let term = self
          .manifest
          .search_terms
          .get(step % self.manifest.search_terms.len().max(1))
          .map(String::as_str)
          .unwrap_or("校园");
        let categories = &self.manifest.category_ids;
        let category = categories[step % categories.len()];
        format!(
          "/products?keyword={}&category_ids={}&page={}&page_size=20",
          encode_component(term),
          category,
          1 + step % 10
        )
      }
      _ => {
        let pool = &self.browse_products;
        ensure!(!pool.is_empty(), "browse product pool is empty");
        let index = (step * 101 + user * 97) % pool.len();
        format!("/products/{}", pool[index])
      }
    };
    let data = self.api(user, op, Method::GET, &path, None).await?;
    if op == "detail" {
      ensure!(
        id_value(&data["id"]).is_some() && data["images"].is_array(),
        "unusable detail"
      );
    } else {
      ensure!(
        data["total"].is_number() && data["items"].is_array(),
        "unusable product list"
      );
    }
    Ok(())
  }

  pub(crate) async fn upload(&self, user: usize, step: usize) -> Result<String> {
    let index = (user + step) % self.images.len();
    let image = &self.images[index];
    let lease = self
      .api(
        user,
        "upload_lease",
        Method::POST,
        "/files/uploads",
        Some(json!({
            "purpose": "product_image",
            // Current Jackson SNAKE_CASE contract; the camel spellings are
            // accepted as harmless duplicates for older callers.
            "declared_size": image.len(),
            "declared_content_type": "image/jpeg",
            "declaredSize": image.len(),
            "declaredContentType": "image/jpeg"
        })),
      )
      .await?;
    let file_id = id_string(&lease["file_id"])
      .or_else(|| id_string(&lease["fileId"]))
      .context("upload file id missing")?;
    ensure!(
      lease["upload"]["method"] == "POST",
      "upload form is not POST"
    );
    let raw = lease["upload"]["url"]
      .as_str()
      .context("upload form URL missing")?;
    let url = if raw.starts_with('/') {
      format!("{}{raw}", self.origin)
    } else {
      raw.to_string()
    };
    let fields = lease["upload"]["fields"]
      .as_object()
      .context("upload form fields missing")?;
    let boundary = format!(
      "----campus-loadtest-{}-{}",
      std::process::id(),
      self
        .sequence
        .fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    );
    let mut body = Vec::new();
    for (name, value) in fields {
      let value = value.as_str().context("upload field is not a string")?;
      body.extend_from_slice(format!("--{boundary}\r\n").as_bytes());
      body.extend_from_slice(
        format!("Content-Disposition: form-data; name=\"{name}\"\r\n\r\n").as_bytes(),
      );
      body.extend_from_slice(value.as_bytes());
      body.extend_from_slice(b"\r\n");
    }
    body.extend_from_slice(format!("--{boundary}\r\n").as_bytes());
    body.extend_from_slice(
            b"Content-Disposition: form-data; name=\"file\"; filename=\"load.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n",
        );
    body.extend_from_slice(image);
    body.extend_from_slice(format!("\r\n--{boundary}--\r\n").as_bytes());
    let start = Instant::now();
    // Separate request: never send application cookies, Origin or CSRF to OSS.
    let response = self
      .client
      .post(url)
      .header(
        reqwest::header::CONTENT_TYPE,
        format!("multipart/form-data; boundary={boundary}"),
      )
      .body(body)
      .send()
      .await;
    let mut diagnostic = response.as_ref().err().map(classify);
    let status = response.as_ref().ok().map(|r| r.status().as_u16());
    let ok = if let Ok(response) = response {
      let allowed = response.status().is_success();
      match response.bytes().await {
        Ok(_) => allowed,
        Err(error) => {
          diagnostic = Some(classify(&error));
          false
        }
      }
    } else {
      false
    };
    let since = self.begin_instant().map_or(0., |begin| {
      start.saturating_duration_since(begin).as_secs_f64() * 1000.
    });
    if let Some(phase) = self.phase_at(start) {
      self.reporter.send(crate::model::Sample {
        user,
        operation: "upload_bytes".into(),
        elapsed_ms: start.elapsed().as_secs_f64() * 1000.,
        ok,
        status,
        phase: phase.into(),
        details: Some(RequestDetails {
          request_id: format!("oss-{user}-{step}"),
          started_ms: since,
          category: diagnostic.as_ref().map(|d| d.0).or(if ok {
            None
          } else {
            Some("upload_response")
          }),
          causes: diagnostic.map(|d| d.1).unwrap_or_default(),
        }),
      });
    }
    ensure!(ok, "OSS multipart upload failed");
    self
      .api(
        user,
        "upload_complete",
        Method::POST,
        &format!("/files/{file_id}/completion"),
        Some(json!({})),
      )
      .await?;
    Ok(file_id)
  }

  pub(crate) async fn prepare_publish_image(&self, user: usize, step: usize) -> Result<()> {
    let file_id = self.upload(user, step).await?;
    self.remember_prepared_image(user, file_id);
    Ok(())
  }

  pub(crate) async fn publish(&self, user: usize, step: usize) -> Result<()> {
    let file_id = self.upload(user, step).await?;
    self.submit_product(user, step, &file_id).await.map(|_| ())
  }

  pub(crate) async fn publish_prepared(&self, user: usize, step: usize) -> Result<()> {
    let file_id = self
      .prepared_image(user)
      .context("prepared publish image missing")?;
    self.submit_product(user, step, &file_id).await.map(|_| ())
  }

  pub(crate) async fn submit_product(
    &self,
    user: usize,
    step: usize,
    file_id: &str,
  ) -> Result<u64> {
    let categories = &self.manifest.category_ids;
    let category = categories[step % categories.len()];
    let product = self
      .api(
        user,
        "publish",
        Method::POST,
        "/products",
        Some(json!({
            "title": format!("压测发布 {} {user} {step}", self.run_id),
            "description": "独立压测工具通过真实上传与发布接口创建",
            "price_cents": 1234,
            "image_file_ids": [file_id],
            "category_ids": [category.to_string()],
            "imageFileIds": [file_id],
            "categoryIds": [category.to_string()]
        })),
      )
      .await?;
    ensure!(
      id_value(&product["id"]).is_some() && product["lifecycle_state"] == "pending_review",
      "publish not pending review"
    );
    id_value(&product["id"]).context("product id missing")
  }

  fn select_trade_pair(&self, user: usize, step: usize, explicit: Option<usize>) -> Result<usize> {
    if let Some(index) = explicit {
      ensure!(
        index < self.trade_pairs.len(),
        "trade pair index out of range"
      );
      let pair = &self.trade_pairs[index];
      ensure!(pair.buyer == user, "trade pair belongs to another buyer");
      return Ok(index);
    }
    let mut owned = self
      .trade_pairs
      .iter()
      .enumerate()
      .filter(|(_, pair)| pair.buyer == user)
      .map(|(index, _)| index)
      .collect::<Vec<_>>();
    ensure!(!owned.is_empty(), "no trade fixture for user");
    owned.sort_unstable();
    Ok(owned[(step / 20) % owned.len()])
  }

  pub(crate) async fn trade(&self, user: usize, step: usize) -> Result<()> {
    let index = self.select_trade_pair(user, step, None)?;
    self.trade_pair(user, step, index).await
  }

  async fn trade_read(&self, user: usize, trade_id: u64, op: &str) -> Result<Value> {
    let trade = self
      .api(user, op, Method::GET, &format!("/trades/{trade_id}"), None)
      .await?;
    ensure!(
      id_value(&trade["id"]) == Some(trade_id),
      "trade id mismatch"
    );
    Ok(trade)
  }

  pub(crate) async fn trade_pair(&self, user: usize, step: usize, pair_index: usize) -> Result<()> {
    let pair: &ResolvedTradePair = self
      .trade_pairs
      .get(pair_index)
      .context("trade fixture missing")?;
    ensure!(pair.buyer == user, "trade fixture does not belong to buyer");
    let seller = pair.seller;
    let product_id = pair.product_id;
    let request = self
      .api(
        user,
        "trade_request",
        Method::POST,
        &format!("/products/{product_id}/purchase-requests"),
        Some(json!({
            "note": format!("load {step}"),
            "expected_product_version": pair.product_version
        })),
      )
      .await?;
    let trade_id = id_value(&request["id"]).context("trade id missing")?;
    ensure!(
      request["status"] == "pending_acceptance",
      "purchase request not pending acceptance"
    );
    let accepted_version = version(&request).context("purchase request version")?;
    self
      .api(
        seller,
        "trade_accept",
        Method::POST,
        &format!("/trades/{trade_id}/accept"),
        Some(json!({"expected_version": accepted_version})),
      )
      .await?;

    let trade = self.trade_read(user, trade_id, "trade_read").await?;
    let agreement = self
      .api(
        user,
        "trade_agreement",
        Method::POST,
        &format!("/trades/{trade_id}/agreements"),
        Some(json!({
            "delivery_at": FUTURE_DELIVERY_AT,
            "delivery_place_text": "校园图书馆",
            "delivery_method": "当面交付",
            "amount_cents": 1234,
            "payment_method": "线下支付",
            "payment_timing": "交付时",
            "expected_version": version(&trade)?
        })),
      )
      .await?;
    let agreement_id = id_value(&agreement["agreement"]["id"])
      .or_else(|| id_value(&agreement["id"]))
      .context("agreement id missing")?;

    let trade = self.trade_read(seller, trade_id, "trade_read").await?;
    self
      .api(
        seller,
        "trade_agree",
        Method::POST,
        &format!("/trades/{trade_id}/agreements/{agreement_id}/decisions"),
        Some(json!({
            "decision": "accept",
            "expected_version": version(&trade)?
        })),
      )
      .await?;

    let trade = self.trade_read(user, trade_id, "trade_read").await?;
    self
      .api(
        user,
        "trade_confirm_buyer",
        Method::POST,
        &format!("/trades/{trade_id}/completion-confirmations"),
        Some(json!({
            "note": format!("load {step}"),
            "expected_version": version(&trade)?
        })),
      )
      .await?;

    let trade = self.trade_read(seller, trade_id, "trade_read").await?;
    self
      .api(
        seller,
        "trade_confirm_seller",
        Method::POST,
        &format!("/trades/{trade_id}/completion-confirmations"),
        Some(json!({
            "note": format!("load {step}"),
            "expected_version": version(&trade)?
        })),
      )
      .await?;

    let mut completed = false;
    for _ in 0..10 {
      let trade = self.trade_read(user, trade_id, "trade_verify").await?;
      if trade["status"] == "completed" {
        completed = true;
        break;
      }
      tokio::time::sleep(Duration::from_millis(50)).await;
    }
    ensure!(completed, "trade did not complete");
    self
      .api(
        seller,
        "trade_relist",
        Method::POST,
        &format!("/products/{product_id}/on-shelf"),
        Some(json!({"expected_version": pair.product_version, "expectedVersion": pair.product_version})),
      )
      .await?;
    Ok(())
  }

  pub(crate) async fn mark_read(
    &self,
    user: usize,
    conversation_id: u64,
    displayed_seq: u64,
  ) -> Result<()> {
    self
      .api(
        user,
        "im_read",
        Method::POST,
        &format!("/conversations/chat/{conversation_id}/read-progress"),
        Some(json!({"displayed_seq": displayed_seq})),
      )
      .await?;
    Ok(())
  }

  pub(crate) async fn im(&self, user: usize, step: usize) -> Result<()> {
    let content = format!("load:{}:{user}:{step}", self.run_id);
    let conversation = *self
      .manifest
      .conversation_ids
      .get(user)
      .context("conversation fixture missing")?;
    let recipient = (user + 1) % self.sessions.len();
    let start = Instant::now();
    let (tx, rx) = oneshot::channel();
    self.pending.lock().unwrap().insert(
      content.clone(),
      Pending::new(recipient, "chat".into(), conversation, start, tx),
    );
    let sent = self
      .api(
        user,
        "im_send",
        Method::POST,
        &format!("/conversations/chat/{conversation}/messages"),
        Some(json!({"body": content})),
      )
      .await;
    let mut displayed_seq = None;
    if let Ok(response) = &sent {
      let message_id = id_string(&response["message_id"]);
      let message_seq = response["seq"].as_u64().filter(|seq| *seq > 0);
      let (Some(message_id), Some(message_seq)) = (message_id, message_seq) else {
        self.pending.lock().unwrap().remove(&content);
        return Err(anyhow::anyhow!(
          "message id or seq missing from send response"
        ));
      };
      displayed_seq = Some(message_seq);
      let mut pending = self.pending.lock().unwrap();
      let candidate = pending
        .get_mut(&content)
        .context("pending IM delivery disappeared")?;
      if let PendingProgress::Complete(result) = candidate.sent(message_id, message_seq)
        && let Some(candidate) = pending.remove(&content)
      {
        candidate.finish(result);
      }
    }
    let delivered = if sent.is_ok() {
      timeout(Duration::from_secs(10), rx)
        .await
        .ok()
        .and_then(|result| result.ok())
    } else {
      None
    };
    self.pending.lock().unwrap().remove(&content);
    self.record(
      user,
      "im_delivery",
      start,
      delivered.as_ref().map_or_else(
        || start.elapsed().as_secs_f64() * 1000.,
        |result| result.elapsed_ms,
      ),
      delivered.as_ref().is_some_and(|result| result.matched),
      None,
    );
    sent?;
    ensure!(
      delivered.as_ref().is_some_and(|result| result.matched),
      "recipient did not retrieve the matching message"
    );
    if let Some(seq) = displayed_seq {
      self.mark_read(user, conversation, seq).await?;
    }
    Ok(())
  }
}

#[cfg(test)]
mod tests {
  use super::encode_component;

  #[test]
  fn query_terms_are_percent_encoded() {
    assert_eq!(encode_component("校园 book"), "%E6%A0%A1%E5%9B%AD%20book");
    assert_eq!(encode_component("a-b_c.d~e"), "a-b_c.d~e");
  }
}
