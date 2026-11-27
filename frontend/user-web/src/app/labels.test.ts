import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { reviewReasonLabel } from "./labels";

describe("review reason label", () => {
  it("labels a rejection as the rejection reason", () => {
    assert.equal(reviewReasonLabel("rejected"), "拒绝原因");
  });

  it("labels every other outcome as a review note", () => {
    for (const status of ["passed", "withdrawn", "pending"]) {
      assert.equal(reviewReasonLabel(status), "审核说明");
    }
  });
});
