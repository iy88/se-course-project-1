import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ProductDetail } from "../api/contracts";
import { saveProductEditAndResubmit } from "./product-edit-submission";

function product(canSubmitReview: boolean): ProductDetail {
  return {
    id: "2",
    content_version: 2,
    permissions: {
      can_edit: true,
      can_off_shelf: false,
      can_relist: false,
      can_withdraw_review: false,
      can_submit_review: canSubmitReview,
    },
  } as ProductDetail;
}

describe("product edit submission", () => {
  it("creates a new review after saving when the server permits resubmission", async () => {
    const calls: string[] = [];
    const updated = product(true);

    const result = await saveProductEditAndResubmit(
      async () => {
        calls.push("update");
        return updated;
      },
      async (saved) => {
        assert.equal(saved, updated);
        assert.equal(saved.content_version, 2);
        calls.push("resubmit");
      },
    );

    assert.deepEqual(calls, ["update", "resubmit"]);
    assert.equal(result.product, updated);
    assert.equal(result.resubmitted, true);
  });

  it("only saves when the updated product cannot start another review", async () => {
    const calls: string[] = [];
    const updated = product(false);

    const result = await saveProductEditAndResubmit(
      async () => {
        calls.push("update");
        return updated;
      },
      async () => {
        calls.push("resubmit");
      },
    );

    assert.deepEqual(calls, ["update"]);
    assert.equal(result.product, updated);
    assert.equal(result.resubmitted, false);
  });
});
