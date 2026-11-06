use serde::{Deserialize, Serialize};
#[derive(Deserialize)]
pub(crate) struct Account {
    pub(crate) id: u64,
    pub(crate) email: String,
}
#[derive(Deserialize)]
pub(crate) struct Manifest {
    pub(crate) version: u64,
    pub(crate) complete: bool,
    pub(crate) tag: String,
    pub(crate) password: String,
    pub(crate) users: usize,
    pub(crate) products: usize,
    pub(crate) accounts: Vec<Account>,
    pub(crate) product_ids: Vec<u64>,
    pub(crate) category_ids: Vec<u64>,
    pub(crate) conversation_ids: Vec<u64>,
    pub(crate) image_base64: String,
    pub(crate) image_sha256: String,
    #[serde(default)]
    pub(crate) image_assets: Vec<ImageAsset>,
    #[serde(default)]
    pub(crate) search_terms: Vec<String>,
}
#[derive(Deserialize)]
pub(crate) struct ImageAsset {
    pub(crate) base64: String,
    pub(crate) sha256: String,
    pub(crate) size_bytes: usize,
}
#[derive(Clone, Serialize)]
pub(crate) struct Sample {
    pub(crate) user: usize,
    pub(crate) operation: String,
    pub(crate) elapsed_ms: f64,
    pub(crate) ok: bool,
    pub(crate) status: Option<u16>,
    pub(crate) phase: String,
    pub(crate) details: Option<crate::diagnostics::RequestDetails>,
}
