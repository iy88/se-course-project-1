use super::diagnostics::{RequestDetails, classify};

#[tokio::test]
async fn invalid_request_preserves_category_without_secrets() {
    let error = reqwest::Client::new()
        .get("invalid://private.invalid/secret-token")
        .send()
        .await
        .unwrap_err();
    let (category, causes) = classify(&error);
    assert_eq!(category, "request_builder");
    let json = serde_json::to_string(&RequestDetails {
        request_id: "test-1".into(),
        started_ms: 0.,
        category: Some(category),
        causes,
    })
    .unwrap();
    assert!(!json.contains("private.invalid"));
    assert!(!json.contains("secret-token"));
}
