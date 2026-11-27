//! Discrete boundary search: never probe a fractional or already tested rate.
pub(super) fn midpoint(low: u32, high: u32, resolution: u32) -> Option<u32> {
  let width = high.checked_sub(low)?;
  if width <= resolution.max(1) {
    return None;
  }
  Some(low + width / 2)
}

#[cfg(test)]
mod tests {
  use super::midpoint;

  #[test]
  fn converges_to_adjacent_integer_boundary_without_repeating_probes() {
    let (mut low, mut high) = (200, 400);
    let mut probes = std::collections::HashSet::new();
    while let Some(rate) = midpoint(low, high, 1) {
      assert!(low < rate && rate < high);
      assert!(probes.insert(rate));
      if rate <= 237 {
        low = rate;
      } else {
        high = rate;
      }
    }
    assert_eq!((low, high), (237, 238));
    assert!(probes.len() <= 8);
  }

  #[test]
  fn handles_first_stage_failure_and_odd_adjacent_or_invalid_bounds() {
    assert_eq!(midpoint(0, 3, 1), Some(1));
    assert_eq!(midpoint(1, 3, 1), Some(2));
    assert_eq!(midpoint(1, 2, 1), None);
    assert_eq!(midpoint(4, 4, 1), None);
    assert_eq!(midpoint(5, 4, 1), None);
    assert_eq!(midpoint(200, 205, 5), None);
  }
}
