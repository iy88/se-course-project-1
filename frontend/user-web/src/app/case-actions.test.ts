/*
 * Case action projection: the server wins when it answers, the client rules apply
 * only while `available_actions` is still absent.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  CASE_APPEAL,
  CASE_RESPOND,
  CASE_SUPPLEMENT,
  caseActionAvailability,
  type CaseActionInput,
} from "./case-actions";

function input(overrides: Partial<CaseActionInput> = {}): CaseActionInput {
  return {
    projected: undefined,
    archived: false,
    reporterView: false,
    caseType: "report",
    appealOpen: false,
    pendingInquiryCount: 0,
    ...overrides,
  };
}

describe("case action availability", () => {
  it("uses the client rules while the backend does not project actions", () => {
    const availability = caseActionAvailability(
      input({ reporterView: true, caseType: "report", appealOpen: true, pendingInquiryCount: 2 }),
    );

    assert.equal(availability.projected, false);
    assert.equal(availability.supplement, true);
    assert.equal(availability.appeal, true);
    assert.equal(availability.respond, true);
  });

  it("hides the reporter entry for a viewpoint that is not the reporter", () => {
    const availability = caseActionAvailability(input({ reporterView: false }));

    assert.equal(availability.supplement, false);
  });

  it("hides the reporter entry on an archived case", () => {
    const availability = caseActionAvailability(input({ reporterView: true, archived: true }));

    assert.equal(availability.supplement, false);
  });

  it("trusts an empty projection and hides every write entry", () => {
    const availability = caseActionAvailability(
      input({ projected: [], reporterView: true, appealOpen: true, pendingInquiryCount: 1 }),
    );

    assert.equal(availability.projected, true);
    assert.equal(availability.supplement, false);
    assert.equal(availability.respond, false);
    assert.equal(availability.appeal, false);
  });

  it("shows only the actions the server projected", () => {
    const availability = caseActionAvailability(
      input({
        projected: [CASE_APPEAL],
        reporterView: true,
        appealOpen: false,
        pendingInquiryCount: 1,
      }),
    );

    assert.equal(availability.appeal, true);
    assert.equal(availability.supplement, false);
    assert.equal(availability.respond, false);
  });

  it("keeps a reply entry hidden when no inquiry is pending", () => {
    const availability = caseActionAvailability(
      input({ projected: [CASE_RESPOND], pendingInquiryCount: 0 }),
    );

    assert.equal(availability.respond, false);
  });

  it("accepts unknown or differently cased action names without breaking", () => {
    const availability = caseActionAvailability(
      input({
        projected: [CASE_SUPPLEMENT.toUpperCase(), "future_action", "  "],
        reporterView: true,
      }),
    );

    assert.equal(availability.supplement, true);
    assert.equal(availability.appeal, false);
    assert.equal(availability.respond, false);
  });

  it("treats a null projection as absent and keeps the client rules", () => {
    const availability = caseActionAvailability(
      input({ projected: null, reporterView: true, caseType: "report" }),
    );

    assert.equal(availability.projected, false);
    assert.equal(availability.supplement, true);
  });
});
