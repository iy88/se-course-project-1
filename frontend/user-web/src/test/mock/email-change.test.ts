/*
 * Email-change verification tickets.
 *
 * An email change sends one code to the current mailbox and one to the new one, and
 * the S2-02 handoff distinguishes them by purpose (`email_change_old` /
 * `email_change_new`) rather than by position. These cases pin that contract and the
 * fallback used for older servers that label both tickets `email_change`.
 */
import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";
import type { EmailVerificationTicket } from "../../api/contracts";
import { handleMockRequest, resetMockState } from "./handlers";

async function requestVerification(purpose: string, email: string) {
  return (await handleMockRequest("POST", "/account/email-verifications", {
    body: { purpose, email },
    idempotencyKey: `verification-${purpose}`,
  })) as { requests: EmailVerificationTicket[] };
}

/** Mirrors the selection the settings screen performs. */
function pickTicket(
  tickets: EmailVerificationTicket[],
  purpose: EmailVerificationTicket["purpose"],
  fallbackIndex: number,
): EmailVerificationTicket | undefined {
  const matches = tickets.filter((ticket) => ticket.purpose === purpose);
  if (matches.length > 0) return matches[0];
  return tickets[fallbackIndex];
}

describe("email change tickets", () => {
  beforeEach(() => {
    resetMockState();
  });

  it("returns one ticket for a single-mailbox purpose", async () => {
    const accepted = await requestVerification("registration", "new@example.com");

    assert.equal(accepted.requests.length, 1);
    assert.equal(accepted.requests[0].purpose, "registration");
  });

  it("returns distinct old and new tickets for an email change", async () => {
    const accepted = await requestVerification("email_change", "new@example.com");

    assert.equal(accepted.requests.length, 2);
    assert.deepEqual(
      accepted.requests.map((ticket) => ticket.purpose),
      ["email_change_old", "email_change_new"],
    );
    assert.notEqual(
      accepted.requests[0].verification_id,
      accepted.requests[1].verification_id,
      "the two mailboxes must not share a verification id",
    );
  });

  it("selects the tickets by purpose, independent of their order", async () => {
    const accepted = await requestVerification("email_change", "new@example.com");
    const reordered = [...accepted.requests].reverse();

    const old = pickTicket(reordered, "email_change_old", 0);
    const fresh = pickTicket(reordered, "email_change_new", 1);

    assert.equal(old?.purpose, "email_change_old");
    assert.equal(fresh?.purpose, "email_change_new");
  });

  it("falls back to the documented order for tickets labelled email_change", async () => {
    const legacy = [
      { verification_id: "old", purpose: "email_change", expires_at: "" },
      { verification_id: "new", purpose: "email_change", expires_at: "" },
    ] as EmailVerificationTicket[];

    assert.equal(pickTicket(legacy, "email_change_old", 0)?.verification_id, "old");
    assert.equal(pickTicket(legacy, "email_change_new", 1)?.verification_id, "new");
  });
});
