import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ApiError } from "../api/errors";
import { describeProblem, problemMessage, requiresLogin } from "./problems";
import {
  agreementStatusLabels,
  caseDecisionLabels,
  notificationTypeLabel,
  productLifecycleLabels,
  tradeActionLabels,
  tradeStageLabel,
  tradeStatusLabels,
} from "./labels";

describe("failure copy", () => {
  it("maps a reviewed error code to actionable copy", () => {
    const problem = describeProblem(new ApiError(409, "VERSION_CONFLICT", "stale"));
    assert.equal(problem.message, "内容已被更新，请刷新后重试。");
    assert.equal(problem.retryable, true);
    assert.equal(problem.requiresLogin, false);
  });

  it("marks an expired session as requiring a new login", () => {
    const problem = describeProblem(new ApiError(401, "AUTHENTICATION_REQUIRED", "expired"));
    assert.equal(problem.requiresLogin, true);
    assert.equal(problem.retryable, false);
    assert.equal(requiresLogin(new ApiError(401, "AUTHENTICATION_REQUIRED", "expired")), true);
  });

  it("falls back to the status class for codes without reviewed copy", () => {
    assert.equal(
      describeProblem(new ApiError(422, "SOMETHING_NEW", "raw")).message,
      "填写内容不符合要求，请检查后重试。",
    );
    assert.equal(
      describeProblem(new ApiError(404, "SOMETHING_NEW", "raw")).message,
      "内容不存在，或你当前无权查看。",
    );
    assert.equal(
      describeProblem(new ApiError(503, "SOMETHING_NEW", "raw")).message,
      "依赖服务暂时不可用，请稍后重试。",
    );
  });

  it("treats an offline client as a retryable failure", () => {
    const problem = describeProblem(new ApiError(0, "NETWORK_UNAVAILABLE", "offline"));
    assert.equal(problem.retryable, true);
    assert.equal(problem.requiresLogin, false);
  });

  it("never throws on an unexpected value", () => {
    // A plain string is not an Error, so the reviewed fallback copy is used
    // instead of echoing an arbitrary value into the interface.
    assert.equal(problemMessage("boom"), "操作未能完成，请稍后重试。");
    assert.equal(problemMessage(undefined), "操作未能完成，请稍后重试。");
    assert.equal(problemMessage({ weird: true }), "操作未能完成，请稍后重试。");
    assert.equal(problemMessage(new Error("依赖超时")), "依赖超时");
  });
});

describe("enum labels", () => {
  it("covers every trade status", () => {
    const statuses = [
      "pending_acceptance",
      "rejected",
      "withdrawn",
      "closed",
      "in_progress",
      "disputed",
      "abnormal",
      "terminated",
      "completed",
    ] as const;
    for (const status of statuses) {
      assert.ok(tradeStatusLabels[status].length > 0, status);
    }
  });

  it("distinguishes the two in-progress stages", () => {
    assert.equal(tradeStageLabel("in_progress", "first_agreement_pending"), "等待约定生效");
    assert.equal(tradeStageLabel("in_progress", "awaiting_completion"), "等待双方完成确认");
    assert.equal(tradeStageLabel("completed", null), "已完成");
  });

  it("labels the seller-facing lifecycle states", () => {
    assert.equal(productLifecycleLabels.pending_review, "待审核");
    assert.equal(productLifecycleLabels.review_rejected, "审核未通过");
    assert.equal(productLifecycleLabels.off_shelf, "已下架");
  });

  it("groups notification event types by their owning module", () => {
    assert.equal(notificationTypeLabel("trade.request_accepted"), "交易");
    assert.equal(notificationTypeLabel("product_audit.rejected"), "商品审核");
    assert.equal(notificationTypeLabel("case.inquiry_created"), "事项");
    assert.equal(notificationTypeLabel("unknown.type"), "通知");
  });

  it("labels every cancellable trade action and case decision", () => {
    assert.ok(tradeActionLabels.submit_confirmation.length > 0);
    assert.equal(caseDecisionLabels.violation, "违规成立");
    assert.equal(agreementStatusLabels.effective, "已生效");
  });
});
