/*
 * Case viewpoint memory and Chinese label fallbacks.
 *
 * The detail endpoint cannot state the viewpoint, so the reporter-only entry has to
 * come from the list scope; these tests pin that memory (including a case that is
 * both reported and received) and the neutral copy used for unknown server values.
 */
import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";
import { caseHasScope, clearCaseScopes, rememberCaseScope } from "./case-directory";
import {
  caseActionKindText,
  caseActorKindText,
  enforcementActionText,
  enforcementStateText,
} from "./labels";

describe("case viewpoint memory", () => {
  beforeEach(() => {
    clearCaseScopes();
  });

  it("remembers the scope a case was listed under", () => {
    rememberCaseScope("11", "mine");

    assert.equal(caseHasScope("11", "mine"), true);
    assert.equal(caseHasScope("11", "received"), false);
  });

  it("keeps both scopes when the same case appears in each list", () => {
    rememberCaseScope("12", "mine");
    rememberCaseScope("12", "received");

    assert.equal(caseHasScope("12", "mine"), true);
    assert.equal(caseHasScope("12", "received"), true);
  });

  it("treats an unvisited case as unknown rather than as the reporter", () => {
    assert.equal(caseHasScope("13", "mine"), false);
    assert.equal(caseHasScope("13", "received"), false);
  });

  it("forgets everything when the session ends", () => {
    rememberCaseScope("14", "mine");
    clearCaseScopes();

    assert.equal(caseHasScope("14", "mine"), false);
  });
});

describe("case label fallbacks", () => {
  it("translates the registered names", () => {
    assert.equal(caseActionKindText("inquire"), "发起问询");
    assert.equal(caseActorKindText("manager"), "管理员");
    assert.equal(enforcementActionText("freeze_trade"), "冻结交易");
    assert.equal(enforcementStateText("restricted"), "受限");
  });

  it("uses neutral copy for values this client does not know yet", () => {
    assert.equal(caseActionKindText("future_action"), "其他处理");
    assert.equal(caseActorKindText("future_actor"), "参与方");
    assert.equal(enforcementActionText("future_enforcement"), "处置措施");
    assert.equal(enforcementStateText("future_state"), "已记录");
  });
});
