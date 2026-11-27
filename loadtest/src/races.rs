//! Conflict tests use the same real API, manifest accounts and seeded products.
//! Expected 409/422 responses are successful checks, never unexpected-error masks.
use crate::http::Driver;
use anyhow::{Context, Result, ensure};
use reqwest::Method;
use serde_json::{Value, json};

const FUTURE_DELIVERY_AT: &str = "2099-01-01T00:00:00Z";

async fn state(driver: &Driver, user: usize, trade_id: u64) -> Result<Value> {
  driver
    .api(
      user,
      "race_trade_read",
      Method::GET,
      &format!("/trades/{trade_id}"),
      None,
    )
    .await
}

fn version(trade: &Value) -> Result<u64> {
  trade["version"].as_u64().context("trade version missing")
}

fn id(value: &Value) -> Result<u64> {
  crate::model::id_value(&value["id"]).context("trade id missing")
}

async fn propose_agreement(
  driver: &Driver,
  buyer: usize,
  trade_id: u64,
  expected_version: u64,
) -> Result<u64> {
  let envelope = driver
    .api(
      buyer,
      "race_agreement",
      Method::POST,
      &format!("/trades/{trade_id}/agreements"),
      Some(json!({
          "delivery_at": FUTURE_DELIVERY_AT,
          "delivery_place_text": "校内",
          "delivery_method": "面交",
          "amount_cents": 1234,
          "payment_method": "线下",
          "payment_timing": "交付时",
          "expected_version": expected_version
      })),
    )
    .await?;
  crate::model::id_value(&envelope["agreement"]["id"])
    .or_else(|| crate::model::id_value(&envelope["id"]))
    .context("agreement id missing")
}

async fn complete_trade(driver: &Driver, seller: usize, buyer: usize, trade_id: u64) -> Result<()> {
  let trade = state(driver, buyer, trade_id).await?;
  let agreement = propose_agreement(driver, buyer, trade_id, version(&trade)?).await?;
  let trade = state(driver, seller, trade_id).await?;
  driver
    .api(
      seller,
      "race_agree",
      Method::POST,
      &format!("/trades/{trade_id}/agreements/{agreement}/decisions"),
      Some(json!({"decision": "accept", "expected_version": version(&trade)?})),
    )
    .await?;
  let trade = state(driver, buyer, trade_id).await?;
  let initial_version = version(&trade)?;
  let path = format!("/trades/{trade_id}/completion-confirmations");
  let body = json!({"note": "race", "expected_version": initial_version});
  let (buyer_result, seller_result) = tokio::join!(
    driver.api_expected(
      buyer,
      "race_confirm",
      Method::POST,
      &path,
      Some(body.clone()),
      &[201, 409]
    ),
    driver.api_expected(
      seller,
      "race_confirm",
      Method::POST,
      &path,
      Some(body),
      &[201, 409]
    )
  );
  let buyer_status = buyer_result?.0;
  let seller_status = seller_result?.0;
  ensure!(
    buyer_status == 201 || seller_status == 201,
    "neither party confirmed"
  );
  let retry_actor = match (buyer_status, seller_status) {
    (409, 201) => Some(buyer),
    (201, 409) => Some(seller),
    _ => None,
  };
  if let Some(actor) = retry_actor {
    let trade = state(driver, actor, trade_id).await?;
    driver
      .api_expected(
        actor,
        "race_confirm_after_version_conflict",
        Method::POST,
        &path,
        Some(json!({"note": "race", "expected_version": version(&trade)?})),
        &[201],
      )
      .await?;
  }
  let mut completed = false;
  for _ in 0..10 {
    if state(driver, buyer, trade_id).await?["status"] == "completed" {
      completed = true;
      break;
    }
    tokio::time::sleep(std::time::Duration::from_millis(50)).await;
  }
  ensure!(
    completed,
    "parallel confirmations did not complete the trade"
  );
  Ok(())
}

async fn round(driver: &Driver, round: usize, checks: &mut Vec<Value>) -> Result<()> {
  let pair = driver
    .trade_pairs
    .get(round)
    .context("insufficient reserved race trade pairs")?;
  let seller = pair.seller;
  let a = pair.buyer;
  let b = (0..driver.sessions.len())
    .find(|candidate| *candidate != seller && *candidate != a)
    .context("race needs a third account")?;
  let product_id = pair.product_id;
  let product_version = pair.product_version;
  let request_path = format!("/products/{product_id}/purchase-requests");
  let request_body = json!({"note": format!("race {} {round}", driver.run_id), "expected_product_version": product_version});
  let duplicate_key = driver.idempotency_key(a, "race_duplicate_request");
  let (_, first) = driver
    .api_with_key(
      a,
      "race_duplicate_request",
      Method::POST,
      &request_path,
      Some(request_body.clone()),
      &duplicate_key,
      &[201],
    )
    .await?;
  // Same key after the first commit must replay the original response. A
  // concurrent duplicate is a legitimate 409 while the claim is still open, so
  // this check uses the deterministic replayed path.
  let (_, duplicate) = driver
    .api_with_key(
      a,
      "race_duplicate_request",
      Method::POST,
      &request_path,
      Some(request_body.clone()),
      &duplicate_key,
      &[201],
    )
    .await?;
  let ta = id(&first)?;
  ensure!(
    ta == id(&duplicate)?,
    "duplicate idempotent requests returned different trades"
  );
  let (_, second) = driver
    .api_expected(
      b,
      "race_second_buyer",
      Method::POST,
      &request_path,
      Some(request_body),
      &[201],
    )
    .await?;
  let tb = id(&second)?;
  checks.push(json!({"round":round,"check":"duplicate_request","passed":true,"trade_id":ta}));

  let path_a = format!("/trades/{ta}/accept");
  let path_b = format!("/trades/{tb}/accept");
  let (ra, rb) = tokio::join!(
    driver.api_expected(
      seller,
      "race_accept",
      Method::POST,
      &path_a,
      Some(json!({"expected_version": version(&first)?})),
      &[200, 409]
    ),
    driver.api_expected(
      seller,
      "race_accept",
      Method::POST,
      &path_b,
      Some(json!({"expected_version": version(&second)?})),
      &[200, 409]
    )
  );
  let (ra, rb) = (ra?, rb?);
  let mut statuses = [ra.0, rb.0];
  statuses.sort();
  ensure!(
    statuses == [200, 409],
    "accept race must have one winner and one conflict"
  );
  let (winner, loser, buyer, loser_buyer) = if ra.0 == 200 {
    (ta, tb, a, b)
  } else {
    (tb, ta, b, a)
  };
  ensure!(
    state(driver, buyer, winner).await?["status"] == "in_progress",
    "winner not locked"
  );
  ensure!(
    state(driver, loser_buyer, loser).await?["status"] == "closed",
    "losing request not closed"
  );
  checks.push(json!({"round":round,"check":"accept_same_product","passed":true,"statuses":statuses,"winner":winner,"loser":loser}));

  complete_trade(driver, seller, buyer, winner).await?;
  checks.push(json!({"round":round,"check":"parallel_completion","passed":true,"trade_id":winner}));
  driver
    .api(
      seller,
      "race_restore_relist",
      Method::POST,
      &format!("/products/{product_id}/on-shelf"),
      Some(json!({"expected_version": product_version, "expectedVersion": product_version})),
    )
    .await?;

  // A third buyer's request either commits before locking and is closed, or is
  // rejected once the product is occupied. A pending request must never survive.
  let (_, pending) = driver
    .api_expected(
      a,
      "race_request_setup",
      Method::POST,
      &request_path,
      Some(json!({"note": "race request vs accept", "expected_product_version": product_version})),
      &[201],
    )
    .await?;
  let tid = id(&pending)?;
  let accept_path = format!("/trades/{tid}/accept");
  let (accepted, requested) = tokio::join!(
    driver.api_expected(
      seller,
      "race_accept_vs_request",
      Method::POST,
      &accept_path,
      Some(json!({"expected_version": version(&pending)?})),
      &[200]
    ),
    driver.api_expected(
      b,
      "race_request_vs_accept",
      Method::POST,
      &request_path,
      Some(json!({"note": "race racing request", "expected_product_version": product_version})),
      &[201, 409, 404]
    )
  );
  accepted?;
  let (code, body) = requested?;
  if code == 201 {
    let other = id(&body)?;
    ensure!(
      state(driver, b, other).await?["status"] == "closed",
      "pending request survived locking"
    );
  }
  ensure!(
    state(driver, a, tid).await?["status"] == "in_progress",
    "acceptance missing"
  );
  checks.push(json!({"round":round,"check":"request_vs_accept","passed":true,"request_status":code,"trade_id":tid}));

  let file_id = driver.upload(seller, round).await?;
  let completion_path = format!("/files/{file_id}/completion");
  let completion_key = driver.idempotency_key(seller, "race_upload_complete");
  let ca = driver
    .api_with_key(
      seller,
      "race_upload_complete",
      Method::POST,
      &completion_path,
      Some(json!({})),
      &completion_key,
      &[200],
    )
    .await?;
  let cb = driver
    .api_with_key(
      seller,
      "race_upload_complete",
      Method::POST,
      &completion_path,
      Some(json!({})),
      &completion_key,
      &[200],
    )
    .await?;
  ensure!(
    crate::model::id_string(&ca.1["file_id"]).as_deref() == Some(file_id.as_str())
      && crate::model::id_string(&cb.1["file_id"]).as_deref() == Some(file_id.as_str()),
    "duplicate completions disagree"
  );
  checks.push(json!({"round":round,"check":"duplicate_upload_complete","passed":true}));

  let (pa, pb) = tokio::join!(
    driver.submit_product(seller, round * 2, &file_id),
    driver.submit_product(seller, round * 2 + 1, &file_id)
  );
  let (pa, pb) = (pa?, pb?);
  ensure!(pa != pb, "distinct publications must have distinct ids");
  for product in [pa, pb] {
    let detail = driver
      .api(
        seller,
        "race_publish_read",
        Method::GET,
        &format!("/products/{product}"),
        None,
      )
      .await?;
    ensure!(
      detail["lifecycle_state"] == "pending_review",
      "publication must remain pending review"
    );
  }
  checks.push(
    json!({"round":round,"check":"parallel_publications","passed":true,"product_ids":[pa,pb]}),
  );
  let invalid_title = format!("race-rollback-{}-{round}", driver.run_id);
  let invalid = json!({
      "title": invalid_title,
      "description": "must roll back",
      "price_cents": 100,
      "imageFileIds": [file_id],
      "categoryIds": ["-1"]
  });
  driver
    .api_expected(
      seller,
      "race_publish_rejected",
      Method::POST,
      "/products",
      Some(invalid),
      &[400, 422],
    )
    .await?;
  let mine = driver
    .api(
      seller,
      "race_publish_rollback_read",
      Method::GET,
      "/account/resources?kind=product&page_size=100",
      None,
    )
    .await?;
  ensure!(
    !mine["items"]
      .as_array()
      .context("my products")?
      .iter()
      .any(|item| item["title"] == invalid_title),
    "failed publication leaked a product"
  );
  checks.push(json!({"round":round,"check":"publish_transaction_rollback","passed":true}));
  Ok(())
}

pub(crate) async fn run(driver: &Driver, rounds: usize) -> Vec<Value> {
  let mut checks = vec![];
  for index in 0..rounds {
    if let Err(error) = round(driver, index, &mut checks).await {
      checks.push(
        json!({"round":index,"check":"round_failed","passed":false,"reason":error.to_string()}),
      );
    }
  }
  checks
}
