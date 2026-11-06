use crate::diagnostics::{RequestDetails, classify};
use crate::{http::Driver, ws::Pending};
use anyhow::{Context, Result, ensure};
use reqwest::Method;
use serde_json::Value;
use serde_json::json;
use std::time::{Duration, Instant};
use tokio::{sync::oneshot, time::timeout};
impl Driver {
    pub(crate) async fn browse(&self, u: usize, op: &str, step: usize) -> Result<()> {
        let path = match op {
            "home" => "/products/search?page_size=20".into(),
            "search" => format!(
                "/products/search?keyword={}&category_ids={}&page={}&page_size=20",
                self.manifest
                    .search_terms
                    .get(step % self.manifest.search_terms.len().max(1))
                    .map(String::as_str)
                    .unwrap_or("校园"),
                self.manifest.category_ids[step % 5],
                1 + step % 10
            ),
            _ => {
                // Keep detail browsing away from fixtures temporarily delisted by trade completion.
                let reserved = self.manifest.users;
                let end = self.detail_range_end.unwrap_or(self.manifest.products);
                let index = if end > reserved {
                    reserved + (step * 101 + u * 97) % (end - reserved)
                } else {
                    u
                }; // Seller can always view their own fixture at minimum scale.
                format!("/products/{}", self.manifest.product_ids[index])
            }
        };
        let data = self.api(u, op, Method::GET, &path, None).await?;
        if op == "detail" {
            ensure!(
                data["id"].is_u64() && !data["image_urls"].as_array().context("images")?.is_empty(),
                "unusable detail"
            );
        } else {
            ensure!(
                data["total"].is_u64() && data["items"].is_array(),
                "unusable search"
            );
        }
        Ok(())
    }
    pub(crate) async fn upload(&self, u: usize, step: usize) -> Result<Value> {
        let index = (u + step) % self.images.len();
        let image = &self.images[index];
        let sha = self
            .manifest
            .image_assets
            .get(index)
            .map(|a| a.sha256.as_str())
            .unwrap_or(&self.manifest.image_sha256);
        let lease = self
            .post(
                u,
                "upload_lease",
                "/files/upload-leases",
                json!({"namespace":"product",
            "filename":"load.jpg", "content_type":"image/jpeg", "size_bytes":image.len(),
            "sha256":sha}),
            )
            .await?;
        let raw = lease["upload"]["url"].as_str().context("missing PUT URL")?;
        let url = if raw.starts_with('/') {
            format!("{}{raw}", self.origin)
        } else {
            raw.to_string()
        };
        let start = Instant::now();
        // Separate client request: never attach application Authorization to a signed OSS PUT.
        let mut request = self.client.put(url).body(image.clone());
        for (k, v) in lease["upload"]["headers"]
            .as_object()
            .context("upload headers")?
        {
            request = request.header(k, v.as_str().context("header type")?);
        }
        let response = request.send().await;
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
        let since = start.saturating_duration_since(self.begin);
        if let Some(phase) = self.phase_at(start) {
            let _ = self.events.send(crate::model::Sample {
                user: u,
                operation: "upload_bytes".into(),
                elapsed_ms: start.elapsed().as_secs_f64() * 1000.,
                ok,
                status,
                phase: phase.into(),
                details: Some(RequestDetails {
                    request_id: format!("{}-oss-{u}-{step}", self.run_id),
                    started_ms: since.as_secs_f64() * 1000.,
                    category: diagnostic.as_ref().map(|d| d.0).or(if ok {
                        None
                    } else {
                        Some("upload_response")
                    }),
                    causes: diagnostic.map(|d| d.1).unwrap_or_default(),
                }),
            });
        }
        ensure!(ok, "upload failed");
        Ok(lease)
    }
    pub(crate) async fn publish(&self, u: usize, step: usize) -> Result<()> {
        let lease = self.upload(u, step).await?;
        let lease_id = lease["lease_id"].as_str().context("lease id")?;
        self.post(
            u,
            "upload_complete",
            &format!("/files/upload-leases/{lease_id}/complete"),
            json!({}),
        )
        .await?;
        self.submit_product(u, step, lease["key"].as_str().context("upload key")?)
            .await?;
        Ok(())
    }
    pub(crate) async fn submit_product(&self, u: usize, step: usize, key: &str) -> Result<u64> {
        let product = self.post(u, "publish", "/products", json!({
            "title":format!("压测发布 {} {u} {step}", self.run_id), "description":"独立压测工具通过真实上传与发布接口创建",
            "price_cents":1234, "image_keys":[key], "tags":[{"category_id":self.manifest.category_ids[u%5]}]
        })).await?;
        ensure!(
            product["id"].is_u64() && product["status"] == "pending_review",
            "publish not pending review"
        );
        product["id"].as_u64().context("product id")
    }
    pub(crate) async fn trade(&self, u: usize, step: usize) -> Result<()> {
        let seller = (u + 1) % self.tokens.len();
        // Each buyer rotates across their partner's inventory, preserving exclusivity.
        let inventory = (self.manifest.products - 1 - seller) / self.manifest.users + 1;
        let index = seller + (step / 20 % inventory) * self.manifest.users;
        let pid = self.manifest.product_ids[index];
        self.trade_product(u, step, pid).await
    }
    pub(crate) async fn trade_product(&self, u: usize, step: usize, pid: u64) -> Result<()> {
        let seller = (u + 1) % self.tokens.len();
        let request = self
            .post(
                u,
                "trade_request",
                "/trades/requests",
                json!({"product_id":pid,"note":format!("load {step}")}),
            )
            .await?;
        ensure!(
            request["existing"] != true,
            "stale pending request; reseed before retrying"
        );
        let tid = request["id"].as_u64().context("trade id")?;
        self.post(
            seller,
            "trade_accept",
            &format!("/trades/{tid}/accept"),
            json!({}),
        )
        .await?;
        let agreement = self.post(u, "trade_agreement", &format!("/trades/{tid}/agreements"), json!({
            "delivery_time":"双方约定时间", "delivery_location":"校园图书馆", "delivery_method":"当面交付",
            "amount_cents":1234, "payment_method":"线下支付", "payment_timing":"交付时"
        })).await?;
        let aid = agreement["id"].as_u64().context("agreement id")?;
        self.post(
            seller,
            "trade_agree",
            &format!("/trades/{tid}/agreements/{aid}/confirm"),
            json!({}),
        )
        .await?;
        self.post(
            u,
            "trade_confirm_buyer",
            &format!("/trades/{tid}/confirmations"),
            json!({}),
        )
        .await?;
        self.post(
            seller,
            "trade_confirm_seller",
            &format!("/trades/{tid}/confirmations"),
            json!({}),
        )
        .await?;
        let final_state = self
            .api(
                u,
                "trade_verify",
                Method::GET,
                &format!("/trades/{tid}"),
                None,
            )
            .await?;
        ensure!(
            final_state["status"] == "completed",
            "trade did not complete"
        );
        self.post(
            seller,
            "trade_relist",
            &format!("/products/{pid}/relist"),
            json!({}),
        )
        .await?;
        Ok(())
    }
    pub(crate) async fn im(&self, u: usize, step: usize) -> Result<()> {
        let content = format!("load:{}:{u}:{step}", self.run_id);
        let cid = self.manifest.conversation_ids[u];
        let start = Instant::now();
        let (tx, rx) = oneshot::channel();
        self.pending.lock().unwrap().insert(
            content.clone(),
            Pending {
                recipient: (u + 1) % self.tokens.len(),
                sender: self.manifest.accounts[u].id,
                conversation: cid,
                started: start,
                tx,
            },
        );
        let sent = self
            .post(
                u,
                "im_send",
                &format!("/conversations/{cid}/messages"),
                json!({"content":content}),
            )
            .await;
        let delivered = if sent.is_ok() {
            timeout(Duration::from_secs(10), rx)
                .await
                .ok()
                .and_then(|r| r.ok())
        } else {
            None
        };
        self.pending.lock().unwrap().remove(&content);
        self.record(
            u,
            "im_delivery",
            start,
            delivered.unwrap_or(start.elapsed().as_secs_f64() * 1000.),
            delivered.is_some(),
            None,
        );
        sent?;
        ensure!(
            delivered.is_some(),
            "recipient did not receive matching WebSocket message"
        );
        Ok(())
    }
}
