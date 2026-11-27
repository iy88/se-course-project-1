import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { reviewReasonLabel, tradeTerminalReasonLabel } from "./labels";

describe("trade terminal reason label", () => {
  it("identifies an administrator completing a trade with one confirmation", () => {
    const history = [{ action: "trade.completed", actor_kind: "admin", to_status: "completed" }];
    assert.equal(tradeTerminalReasonLabel("completed", false, history), "管理员处置完成");
  });

  it("labels completion based on both confirmations even without state history", () => {
    assert.equal(tradeTerminalReasonLabel("completed", true, undefined), "双方确认完成");
  });

  it("uses a generic completion label when the source cannot be verified", () => {
    const history = [{ action: "trade.frozen", actor_kind: "admin" }];
    assert.equal(tradeTerminalReasonLabel("completed", false, history), "交易已完成");
  });

  it("preserves the other terminal reason labels", () => {
    assert.equal(tradeTerminalReasonLabel("admin_terminated", false, undefined), "管理终止");
    assert.equal(tradeTerminalReasonLabel("cancelled", false, undefined), "已取消");
    assert.equal(tradeTerminalReasonLabel(null, false, undefined), null);
  });
});

describe("review reason label", () => {
  it("labels a rejection as the rejection reason", () => {
    assert.equal(reviewReasonLabel("rejected"), "拒绝原因");
  });

  it("labels every other outcome as a review note", () => {
    for (const status of ["passed", "withdrawn", "pending"] as const) {
      assert.equal(reviewReasonLabel(status), "审核说明");
    }
  });
});
