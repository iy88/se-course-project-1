import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { productEditChanges } from "./product-edit-changes";

describe("product edit history projection", () => {
  it("renders permitted before/after values and formats prices", () => {
    const changes = productEditChanges(
      { title: "旧标题", price_cents: 4500, private_note: "never shown" },
      { title: "新标题", price_cents: 5200, private_note: "never shown" },
    );
    assert.deepEqual(
      changes.map((change) => change.key),
      ["title", "price_cents"],
    );
    assert.equal(changes[1].before, "¥45.00");
    assert.equal(changes[1].after, "¥52.00");
  });

  it("omits unchanged and absent fields instead of inventing a change", () => {
    const changes = productEditChanges(
      { title: "不变", description: "旧描述" },
      { title: "不变", description: "新描述" },
    );
    assert.deepEqual(
      changes.map((change) => change.label),
      ["描述"],
    );
  });
});
