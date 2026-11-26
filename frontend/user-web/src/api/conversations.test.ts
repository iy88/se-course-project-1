/*
 * Message normalisation.
 *
 * API-CONV-003 lets trade threads answer `message_id`／`message_type` and case
 * threads answer `case_message_id`／`message_kind`. The client keeps one internal
 * shape so the thread view never branches on the conversation kind.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { normalizeMessagesPage } from "./conversations";

const sender = { account_id: "7", display_name: "联调测试员", sender_kind: "user" as const };

describe("message normalisation", () => {
  it("keeps the trade naming set", () => {
    const page = normalizeMessagesPage({
      items: [
        {
          message_id: "42",
          seq: 12,
          sender,
          message_type: "text",
          body: "在吗",
          created_at: "2026-11-23T10:00:00Z",
        },
      ],
      trade_id: "19",
      next_before_seq: 11,
      branch_status: "active",
    });

    assert.equal(page.items[0].message_id, "42");
    assert.equal(page.items[0].message_type, "text");
    assert.equal(page.trade_id, "19");
    assert.equal(page.next_before_seq, 11);
    assert.equal(page.next_after_seq, null);
  });

  it("maps the case naming set onto the same shape", () => {
    const page = normalizeMessagesPage({
      items: [
        {
          case_message_id: "88",
          seq: 3,
          sender: { account_id: null, display_name: "系统", sender_kind: "system" },
          message_kind: "statement",
          body: "请补充说明",
          created_at: "2026-11-23T10:05:00Z",
        },
      ],
      branch_status: "archived",
    });

    assert.equal(page.items[0].message_id, "88");
    assert.equal(page.items[0].message_type, "statement");
    assert.equal(page.branch_status, "archived");
    assert.equal(page.trade_id, undefined);
  });

  it("prefers the trade fields when a server sends both", () => {
    const page = normalizeMessagesPage({
      items: [
        {
          message_id: "1",
          case_message_id: "2",
          seq: 1,
          sender,
          message_type: "text",
          message_kind: "statement",
          body: "hi",
          created_at: "2026-11-23T10:00:00Z",
        },
      ],
      branch_status: "active",
    });

    assert.equal(page.items[0].message_id, "1");
    assert.equal(page.items[0].message_type, "text");
  });

  it("keeps timed-out optional fields null", () => {
    const page = normalizeMessagesPage({
      items: [{ message_id: "3", seq: 1, sender, body: "x", created_at: "2026-11-23T10:00:00Z" }],
      branch_status: "active",
    });

    assert.equal(page.items[0].event_type, null);
    assert.equal(page.items[0].source_ref, null);
    assert.equal(page.items[0].message_type, "statement");
  });
});
