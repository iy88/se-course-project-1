use anyhow::{Result, ensure};
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::Value;
use std::collections::HashSet;

/// Account ids appear as decimal strings in the current API and as numbers in
/// older seed manifests. Keep one numeric representation internally.
fn id_from_string_or_number<'de, D>(deserializer: D) -> std::result::Result<u64, D::Error>
where
  D: Deserializer<'de>,
{
  struct IdVisitor;

  impl serde::de::Visitor<'_> for IdVisitor {
    type Value = u64;

    fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
      formatter.write_str("a positive decimal id or string")
    }

    fn visit_u64<E: serde::de::Error>(self, value: u64) -> std::result::Result<u64, E> {
      if value == 0 {
        return Err(serde::de::Error::custom("id must be positive"));
      }
      Ok(value)
    }

    fn visit_i64<E: serde::de::Error>(self, value: i64) -> std::result::Result<u64, E> {
      u64::try_from(value)
        .ok()
        .filter(|value| *value > 0)
        .ok_or_else(|| serde::de::Error::custom("id must be positive"))
    }

    fn visit_u128<E: serde::de::Error>(self, value: u128) -> std::result::Result<u64, E> {
      u64::try_from(value).map_err(|_| serde::de::Error::custom("id out of range"))
    }

    fn visit_i128<E: serde::de::Error>(self, value: i128) -> std::result::Result<u64, E> {
      u64::try_from(value)
        .ok()
        .filter(|value| *value > 0)
        .ok_or_else(|| serde::de::Error::custom("id must be positive"))
    }

    fn visit_str<E: serde::de::Error>(self, value: &str) -> std::result::Result<u64, E> {
      value
        .parse::<u64>()
        .ok()
        .filter(|value| *value > 0)
        .ok_or_else(|| serde::de::Error::custom("id must be a positive decimal string"))
    }

    fn visit_string<E: serde::de::Error>(self, value: String) -> std::result::Result<u64, E> {
      self.visit_str(&value)
    }
  }

  deserializer.deserialize_any(IdVisitor)
}

#[derive(Deserialize)]
pub(crate) struct Account {
  #[serde(deserialize_with = "id_from_string_or_number")]
  pub(crate) id: u64,
  pub(crate) email: String,
}

#[derive(Deserialize)]
pub(crate) struct TradePair {
  #[serde(deserialize_with = "id_from_string_or_number")]
  pub(crate) user: u64,
  #[serde(deserialize_with = "id_from_string_or_number")]
  pub(crate) peer: u64,
  pub(crate) product_id: u64,
  pub(crate) product_version: u32,
}

#[derive(Deserialize)]
pub(crate) struct Manifest {
  pub(crate) version: u64,
  pub(crate) complete: bool,
  #[serde(default)]
  pub(crate) mode: Option<String>,
  #[serde(default)]
  pub(crate) run_id: Option<String>,
  pub(crate) tag: String,
  pub(crate) password: String,
  pub(crate) users: usize,
  pub(crate) products: usize,
  pub(crate) accounts: Vec<Account>,
  pub(crate) product_ids: Vec<u64>,
  #[serde(default)]
  pub(crate) browse_product_ids: Vec<u64>,
  #[serde(default)]
  pub(crate) trade_pairs: Vec<TradePair>,
  pub(crate) category_ids: Vec<u64>,
  pub(crate) conversation_ids: Vec<u64>,
  pub(crate) image_base64: String,
  pub(crate) image_sha256: String,
  #[serde(default)]
  pub(crate) image_assets: Vec<ImageAsset>,
  #[serde(default)]
  pub(crate) search_terms: Vec<String>,
  #[serde(default)]
  pub(crate) scenarios: Option<Value>,
}

#[derive(Deserialize)]
pub(crate) struct ImageAsset {
  pub(crate) base64: String,
  pub(crate) sha256: String,
  pub(crate) size_bytes: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct ResolvedTradePair {
  pub(crate) buyer: usize,
  pub(crate) seller: usize,
  pub(crate) product_id: u64,
  pub(crate) product_version: u32,
}

/// Validate the parts of a manifest that do not need image decoding. Version 1
/// and 2 remain readable so older seeds can still be inspected; the current
/// traffic itself targets the v3 seed contract.
pub(crate) fn validate(manifest: &Manifest, requested_users: usize) -> Result<()> {
  ensure!(
    matches!(manifest.version, 1..=3),
    "unsupported manifest version"
  );
  ensure!(manifest.complete, "manifest is not complete");
  ensure!(
    !manifest.tag.is_empty() && !manifest.password.is_empty(),
    "manifest tag/password missing"
  );
  if let Some(mode) = &manifest.mode {
    ensure!(!mode.is_empty(), "manifest mode is empty");
  }
  if let Some(run_id) = &manifest.run_id {
    ensure!(!run_id.is_empty(), "manifest run_id is empty");
  }
  if let Some(scenarios) = &manifest.scenarios {
    ensure!(
      scenarios.is_object() || scenarios.is_array(),
      "manifest scenarios must be an object or array"
    );
  }
  ensure!(
    manifest.users > 0 && manifest.products > 0,
    "manifest scale is empty"
  );
  ensure!(
    manifest.accounts.len() == manifest.users,
    "account count does not match users"
  );
  ensure!(
    manifest.product_ids.len() == manifest.products,
    "product_ids do not match products"
  );
  ensure!(
    requested_users == manifest.users,
    "users must match the full seeded cohort (reseed for a different scale)"
  );
  ensure!(
    manifest.conversation_ids.len() == manifest.users,
    "conversation ids do not cover the seeded cohort"
  );
  ensure!(
    !manifest.category_ids.is_empty(),
    "manifest needs at least one category"
  );
  ensure!(
    manifest.products >= manifest.users,
    "manifest needs at least one product per user"
  );

  let mut account_ids = HashSet::new();
  let mut emails = HashSet::new();
  for account in &manifest.accounts {
    ensure!(
      account_ids.insert(account.id),
      "duplicate account id in manifest"
    );
    ensure!(
      !account.email.is_empty() && emails.insert(account.email.clone()),
      "duplicate or empty account email in manifest"
    );
  }
  ensure!(
    manifest.category_ids.iter().all(|id| *id > 0),
    "category ids must be positive"
  );
  ensure!(
    manifest.product_ids.iter().all(|id| *id > 0),
    "product ids must be positive"
  );
  let unique_products = manifest.product_ids.iter().copied().collect::<HashSet<_>>();
  ensure!(
    unique_products.len() == manifest.product_ids.len(),
    "duplicate product ids in manifest"
  );
  ensure!(
    manifest.conversation_ids.iter().all(|id| *id > 0)
      && manifest
        .conversation_ids
        .iter()
        .copied()
        .collect::<HashSet<_>>()
        .len()
        == manifest.conversation_ids.len(),
    "conversation ids must be positive and unique"
  );

  if manifest.version >= 3 {
    ensure!(
      !manifest.browse_product_ids.is_empty(),
      "v3 manifest needs a browse product pool"
    );
    let browse = manifest
      .browse_product_ids
      .iter()
      .copied()
      .collect::<HashSet<_>>();
    ensure!(
      browse.len() == manifest.browse_product_ids.len(),
      "duplicate browse product ids in manifest"
    );
    ensure!(
      browse.iter().all(|id| unique_products.contains(id)),
      "browse product ids must reference product_ids"
    );
    ensure!(
      !manifest.trade_pairs.is_empty(),
      "v3 manifest needs trade pairs"
    );
    for pair in &manifest.trade_pairs {
      ensure!(
        pair.product_version > 0,
        "trade pair product_version must be positive"
      );
      ensure!(
        unique_products.contains(&pair.product_id),
        "trade pair product is not in product_ids"
      );
      ensure!(
        !browse.contains(&pair.product_id),
        "trade and browse pools must be disjoint"
      );
    }
  } else {
    ensure!(
      manifest.browse_product_ids.is_empty()
        || manifest
          .browse_product_ids
          .iter()
          .all(|id| unique_products.contains(id)),
      "browse product ids must reference product_ids"
    );
  }
  Ok(())
}

pub(crate) fn account_index(manifest: &Manifest, value: u64) -> Option<usize> {
  manifest
    .accounts
    .iter()
    .position(|account| account.id == value)
    .or_else(|| (value < manifest.users as u64).then_some(value as usize))
}

/// Resolve manifest trade pairs into account indexes. Older manifests did not
/// carry pairs; synthesize the original ring assignment so v1/v2 stays usable.
pub(crate) fn resolve_trade_pairs(manifest: &Manifest) -> Result<Vec<ResolvedTradePair>> {
  let mut resolved = Vec::new();
  if !manifest.trade_pairs.is_empty() {
    for pair in &manifest.trade_pairs {
      let buyer = account_index(manifest, pair.user)
        .ok_or_else(|| anyhow::anyhow!("trade pair user is not in the cohort"))?;
      let seller = account_index(manifest, pair.peer)
        .ok_or_else(|| anyhow::anyhow!("trade pair peer is not in the cohort"))?;
      ensure!(buyer != seller, "trade pair must have distinct parties");
      ensure!(
        manifest.product_ids.contains(&pair.product_id),
        "trade pair product is not in product_ids"
      );
      ensure!(
        pair.product_version > 0,
        "trade pair product_version must be positive"
      );
      resolved.push(ResolvedTradePair {
        buyer,
        seller,
        product_id: pair.product_id,
        product_version: pair.product_version,
      });
    }
    return Ok(resolved);
  }
  ensure!(
    manifest.version < 3,
    "v3 manifest trade pairs did not resolve"
  );
  for buyer in 0..manifest.users {
    let seller = (buyer + 1) % manifest.users;
    if manifest.users == 0 || manifest.products <= seller {
      continue;
    }
    let inventory = (manifest.products - 1 - seller) / manifest.users + 1;
    for row in 0..inventory {
      let index = seller + row * manifest.users;
      let Some(product_id) = manifest.product_ids.get(index) else {
        break;
      };
      resolved.push(ResolvedTradePair {
        buyer,
        seller,
        product_id: *product_id,
        product_version: 1,
      });
    }
  }
  ensure!(!resolved.is_empty(), "manifest has no trade fixtures");
  Ok(resolved)
}

/// Browse pool used for home/search/detail. v3 separates it from trade fixtures;
/// older manifests fall back to the full product list.
pub(crate) fn browse_products(manifest: &Manifest) -> Vec<u64> {
  if !manifest.browse_product_ids.is_empty() {
    manifest.browse_product_ids.clone()
  } else {
    manifest.product_ids.clone()
  }
}

/// Extract a positive decimal id from either a JSON string or number.
pub(crate) fn id_value(value: &Value) -> Option<u64> {
  if let Some(text) = value.as_str() {
    return text.parse::<u64>().ok().filter(|id| *id > 0);
  }
  value.as_u64().filter(|id| *id > 0)
}

pub(crate) fn id_string(value: &Value) -> Option<String> {
  id_value(value).map(|id| id.to_string())
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

#[cfg(test)]
mod tests {
  use super::*;
  use serde_json::json;

  fn manifest(version: u64) -> Manifest {
    serde_json::from_value(json!({
        "version": version,
        "complete": true,
        "mode": "steady",
        "run_id": "seed-1",
        "tag": "test",
        "password": "secret",
        "users": 2,
        "products": 4,
        "accounts": [
            {"id": "11", "email": "a@example.com"},
            {"id": 12, "email": "b@example.com"}
        ],
        "product_ids": [101, 102, 103, 104],
        "browse_product_ids": [101, 102],
        "trade_pairs": [
            {"user": "11", "peer": 12, "product_id": 103, "product_version": 1},
            {"user": 12, "peer": "11", "product_id": 104, "product_version": 3}
        ],
        "category_ids": [1],
        "conversation_ids": [201, 202],
        "image_base64": "AQ==",
        "image_sha256": "x",
        "image_assets": [],
        "search_terms": ["book"],
        "scenarios": {"duration": 1}
    }))
    .unwrap()
  }

  #[test]
  fn parses_v3_ids_from_strings_and_numbers_and_resolves_pairs() {
    let manifest = manifest(3);
    validate(&manifest, 2).unwrap();
    assert_eq!(manifest.accounts[0].id, 11);
    assert_eq!(manifest.accounts[1].id, 12);
    assert_eq!(browse_products(&manifest), vec![101, 102]);
    let pairs = resolve_trade_pairs(&manifest).unwrap();
    assert_eq!(pairs.len(), 2);
    assert_eq!(pairs[0].buyer, 0);
    assert_eq!(pairs[0].seller, 1);
    assert_eq!(pairs[1].product_version, 3);
  }

  #[test]
  fn rejects_overlapping_browse_and_trade_pools() {
    let mut manifest = manifest(3);
    manifest.trade_pairs[0].product_id = 101;
    assert!(validate(&manifest, 2).is_err());
  }

  #[test]
  fn accepts_one_or_more_categories_and_requires_the_full_cohort() {
    let mut manifest = manifest(3);
    assert!(validate(&manifest, 1).is_err());
    manifest.category_ids = vec![7, 8, 9, 10, 11];
    assert!(validate(&manifest, 2).is_ok());
  }

  #[test]
  fn id_value_accepts_decimal_strings_or_numbers_only() {
    assert_eq!(id_value(&json!("42")), Some(42));
    assert_eq!(id_value(&json!(42)), Some(42));
    assert_eq!(id_value(&json!("0")), None);
    assert_eq!(id_value(&json!(-1)), None);
    assert_eq!(id_value(&json!("abc")), None);
    assert_eq!(id_string(&json!(42)).as_deref(), Some("42"));
  }
}
