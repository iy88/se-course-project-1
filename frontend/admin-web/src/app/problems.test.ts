import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ApiError } from "../api/errors";
import { describeProblem } from "./problems";

describe("administrative problem copy", () => {
  it("uses the reviewed copy for a known management code", () => {
    const problem = describeProblem(new ApiError(403, "MANAGEMENT_NOT_ALLOWED", "forbidden"));
    assert.equal(problem.message, "需要平台管理权限。");
    assert.equal(problem.retryable, false);
  });

  it("maps unknown codes by HTTP status", () => {
    assert.equal(describeProblem(new ApiError(409, "SOMETHING_ELSE", "x")).retryable, true);
    assert.equal(
      describeProblem(new ApiError(404, "SOMETHING_ELSE", "x")).message,
      "内容不存在，或当前账号无权查看。",
    );
  });

  it("keeps the server message for an unclassified client failure", () => {
    const problem = describeProblem(new ApiError(400, "SOMETHING_ELSE", "明细不可用"));
    assert.equal(problem.message, "明细不可用");
  });

  it("treats unexpected values as a retryable unknown failure", () => {
    assert.equal(describeProblem(new Error("boom")).retryable, true);
  });
});
