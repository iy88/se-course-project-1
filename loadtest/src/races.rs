//! Conflict tests use the same real API, manifest accounts and seeded products.
//! Expected 409/400 responses are successful checks, never unexpected-error masks.
use crate::http::Driver;
use anyhow::{Context, Result, ensure};
use reqwest::Method;
use serde_json::{Value, json};

async fn state(d: &Driver, u: usize, tid: u64) -> Result<Value> {
    d.api(
        u,
        "race_trade_read",
        Method::GET,
        &format!("/trades/{tid}"),
        None,
    )
    .await
}

async fn round(d: &Driver, round: usize, checks: &mut Vec<Value>) -> Result<()> {
    let seller = 0;
    let a = 1;
    let b = 2;
    let pid = *d
        .manifest
        .product_ids
        .get(d.manifest.users * (round + 1))
        .context("insufficient reserved race products")?;
    let request = json!({"product_id":pid,"note":format!("race {} {round}",d.run_id)});
    let (first, duplicate) = tokio::join!(
        d.post(
            a,
            "race_duplicate_request",
            "/trades/requests",
            request.clone()
        ),
        d.post(
            a,
            "race_duplicate_request",
            "/trades/requests",
            request.clone()
        )
    );
    let (first, duplicate) = (first?, duplicate?);
    ensure!(
        first["id"] == duplicate["id"]
            && (first["existing"] == true || duplicate["existing"] == true),
        "duplicate requests did not return the same transaction"
    );
    let ta = first["id"].as_u64().context("trade id")?;
    let second = d
        .post(b, "race_second_buyer", "/trades/requests", request)
        .await?;
    let tb = second["id"].as_u64().context("second trade id")?;
    checks.push(json!({"round":round,"check":"duplicate_request","passed":true,"trade_id":ta}));
    let path_a = format!("/trades/{ta}/accept");
    let path_b = format!("/trades/{tb}/accept");
    let (ra, rb) = tokio::join!(
        d.api_expected(
            seller,
            "race_accept",
            Method::POST,
            &path_a,
            Some(json!({})),
            &[200, 409]
        ),
        d.api_expected(
            seller,
            "race_accept",
            Method::POST,
            &path_b,
            Some(json!({})),
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
        state(d, buyer, winner).await?["status"] == "in_progress",
        "winner not locked"
    );
    ensure!(
        state(d, loser_buyer, loser).await?["status"] == "closed",
        "losing request not closed"
    );
    for (tid, expected) in [(winner, 1), (loser, 0)] {
        let transitions = d
            .api(
                seller,
                "race_transitions",
                Method::GET,
                &format!("/trades/{tid}/transitions"),
                None,
            )
            .await?;
        let accepted = transitions
            .as_array()
            .context("transitions")?
            .iter()
            .filter(|t| t["trigger"] == "request_accepted")
            .count();
        ensure!(accepted == expected, "unexpected accept transition count");
    }
    checks.push(json!({"round":round,"check":"accept_same_product","passed":true,"statuses":statuses,"winner":winner,"loser":loser}));
    let agreement=d.post(buyer,"race_agreement",&format!("/trades/{winner}/agreements"),json!({
        "delivery_time":"测试时间","delivery_location":"校内","delivery_method":"面交","amount_cents":1234,
        "payment_method":"线下","payment_timing":"交付时"})).await?;
    let aid = agreement["id"].as_u64().context("agreement id")?;
    d.post(
        seller,
        "race_agree",
        &format!("/trades/{winner}/agreements/{aid}/confirm"),
        json!({}),
    )
    .await?;
    let complete = format!("/trades/{winner}/confirmations");
    let (ba, sa) = tokio::join!(
        d.post(buyer, "race_confirm", &complete, json!({})),
        d.post(seller, "race_confirm", &complete, json!({}))
    );
    ba?;
    sa?;
    ensure!(
        state(d, buyer, winner).await?["status"] == "completed",
        "parallel confirmations did not complete the trade"
    );
    let transitions = d
        .api(
            seller,
            "race_complete_transitions",
            Method::GET,
            &format!("/trades/{winner}/transitions"),
            None,
        )
        .await?;
    ensure!(
        transitions
            .as_array()
            .context("transitions")?
            .iter()
            .filter(|t| t["to_status"] == "completed")
            .count()
            == 1,
        "duplicate completion transition"
    );
    checks
        .push(json!({"round":round,"check":"parallel_completion","passed":true,"trade_id":winner}));
    d.post(
        seller,
        "race_restore_relist",
        &format!("/products/{pid}/relist"),
        json!({}),
    )
    .await?;

    // The new request either commits before locking and is closed, or is rejected
    // after locking. A pending request must never survive acceptance.
    let pending = d
        .post(
            a,
            "race_request_setup",
            "/trades/requests",
            json!({"product_id":pid}),
        )
        .await?;
    let tid = pending["id"].as_u64().context("request id")?;
    let accept_path = format!("/trades/{tid}/accept");
    let (accepted, requested) = tokio::join!(
        d.post(seller, "race_accept_vs_request", &accept_path, json!({})),
        d.api_expected(
            b,
            "race_request_vs_accept",
            Method::POST,
            "/trades/requests",
            Some(json!({"product_id":pid})),
            &[200, 404]
        )
    );
    accepted?;
    let (code, body) = requested?;
    if code == 200 {
        let other = body["id"].as_u64().context("racing request id")?;
        ensure!(
            state(d, b, other).await?["status"] == "closed",
            "pending request survived locking"
        );
    }
    ensure!(
        state(d, a, tid).await?["status"] == "in_progress",
        "acceptance missing"
    );
    checks.push(json!({"round":round,"check":"request_vs_accept","passed":true,"request_status":code,"trade_id":tid}));
    d.post(
        a,
        "race_restore_cancel",
        &format!("/trades/{tid}/cancel"),
        json!({"reason":"restore race fixture"}),
    )
    .await?;
    d.post(
        seller,
        "race_restore_relist",
        &format!("/products/{pid}/relist"),
        json!({}),
    )
    .await?;

    let lease = d.upload(seller, round).await?;
    let lid = lease["lease_id"].as_str().context("lease id")?;
    let key = lease["key"].as_str().context("image key")?;
    let path = format!("/files/upload-leases/{lid}/complete");
    let (ca, cb) = tokio::join!(
        d.post(seller, "race_upload_complete", &path, json!({})),
        d.post(seller, "race_upload_complete", &path, json!({}))
    );
    let (ca, cb) = (ca?, cb?);
    ensure!(
        ca["key"] == key && cb["key"] == key,
        "lease completions disagree"
    );
    checks.push(json!({"round":round,"check":"duplicate_upload_complete","passed":true}));
    // Two distinct submissions may share a verified image (supported by StoredObject).
    let (pa, pb) = tokio::join!(
        d.submit_product(seller, round * 2, key),
        d.submit_product(seller, round * 2 + 1, key)
    );
    let (pa, pb) = (pa?, pb?);
    ensure!(pa != pb, "distinct publications must have distinct ids");
    for pid in [pa, pb] {
        let reviews = d
            .api(
                seller,
                "race_publish_review",
                Method::GET,
                &format!("/products/{pid}/review-records"),
                None,
            )
            .await?;
        ensure!(
            reviews.as_array().context("reviews")?.len() == 1,
            "publication must have exactly one review"
        );
    }
    checks.push(
        json!({"round":round,"check":"parallel_publications","passed":true,"product_ids":[pa,pb]}),
    );
    let invalid_title = format!("race-rollback-{}-{round}", d.run_id);
    let invalid = json!({"title":invalid_title,"description":"must roll back","price_cents":100,"image_keys":[key],"tags":[{"category_id":-1}]});
    d.api_expected(
        seller,
        "race_publish_rejected",
        Method::POST,
        "/products",
        Some(invalid),
        &[400],
    )
    .await?;
    let mine = d
        .api(
            seller,
            "race_publish_rollback_read",
            Method::GET,
            "/products/mine",
            None,
        )
        .await?;
    ensure!(
        !mine
            .as_array()
            .context("my products")?
            .iter()
            .any(|p| p["title"] == invalid_title),
        "failed publication leaked a product"
    );
    checks.push(json!({"round":round,"check":"publish_transaction_rollback","passed":true}));
    Ok(())
}

pub(crate) async fn run(d: &Driver, rounds: usize) -> Vec<Value> {
    let mut checks = vec![];
    for index in 0..rounds {
        if let Err(error) = round(d, index, &mut checks).await {
            checks.push(json!({"round":index,"check":"round_failed","passed":false,"reason":error.to_string()}));
        }
    }
    checks
}
