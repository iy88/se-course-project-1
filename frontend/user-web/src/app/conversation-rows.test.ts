/*
 * Conversation row rules and composer keys.
 *
 * These pin the message-screen behaviour that is otherwise only visible in a
 * browser: day separators, merged consecutive messages, side alignment, system
 * events, and whether Enter sends or belongs to the IME.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { ConversationMessage } from "../api/contracts";
import { shouldSendOnEnter } from "./composer";
import { buildConversationRows, dayLabel, type MessageRow } from "./conversation-rows";

const VIEWER = "7";

function message(
  id: string,
  senderId: string | null,
  createdAt: string,
  senderKind: "user" | "system" | "manager" = "user",
): ConversationMessage {
  return {
    message_id: id,
    seq: Number(id.replace(/\D/g, "")) || 1,
    sender: { account_id: senderId, display_name: senderId ?? "系统", sender_kind: senderKind },
    message_type: "text",
    body: `消息 ${id}`,
    created_at: createdAt,
  };
}

function messageRows(rows: ReturnType<typeof buildConversationRows>): MessageRow[] {
  return rows.filter((row): row is MessageRow => row.kind === "message");
}

describe("conversation rows", () => {
  it("returns nothing for an empty branch", () => {
    assert.deepEqual(buildConversationRows([], { viewerAccountId: VIEWER }), []);
  });

  it("puts my messages on my side and the peer's on theirs", () => {
    const rows = buildConversationRows(
      [message("1", "9", "2026-11-22T10:00:00Z"), message("2", VIEWER, "2026-11-22T10:01:00Z")],
      { viewerAccountId: VIEWER, now: new Date("2026-11-22T12:00:00Z") },
    );
    const [first, second] = messageRows(rows);

    assert.equal(first.mine, false);
    assert.equal(second.mine, true);
  });

  it("never treats a system event as mine", () => {
    const rows = buildConversationRows([message("1", VIEWER, "2026-11-22T10:00:00Z", "system")], {
      viewerAccountId: VIEWER,
      now: new Date("2026-11-22T12:00:00Z"),
    });
    const [row] = messageRows(rows);

    assert.equal(row.system, true);
    assert.equal(row.mine, false);
  });

  it("merges consecutive messages from one sender inside the same minute", () => {
    const rows = buildConversationRows(
      [message("1", "9", "2026-11-22T10:00:10Z"), message("2", "9", "2026-11-22T10:00:40Z")],
      { viewerAccountId: VIEWER, now: new Date("2026-11-22T12:00:00Z") },
    );
    const [first, second] = messageRows(rows);

    assert.equal(first.merged, false);
    assert.equal(second.merged, true);
  });

  it("does not merge across a minute change or a sender change", () => {
    const rows = buildConversationRows(
      [
        message("1", "9", "2026-11-22T10:00:10Z"),
        message("2", "9", "2026-11-22T10:01:10Z"),
        message("3", VIEWER, "2026-11-22T10:01:20Z"),
      ],
      { viewerAccountId: VIEWER, now: new Date("2026-11-22T12:00:00Z") },
    );
    const [, second, third] = messageRows(rows);

    assert.equal(second.merged, false);
    assert.equal(third.merged, false);
  });

  it("does not merge consecutive system events", () => {
    const rows = buildConversationRows(
      [
        message("1", null, "2026-11-22T10:00:10Z", "system"),
        message("2", null, "2026-11-22T10:00:20Z", "system"),
      ],
      { viewerAccountId: VIEWER, now: new Date("2026-11-22T12:00:00Z") },
    );
    const [, second] = messageRows(rows);

    assert.equal(second.merged, false);
  });

  it("starts a new day separator and breaks merging across days", () => {
    const rows = buildConversationRows(
      [message("1", "9", "2026-11-21T10:00:10Z"), message("2", "9", "2026-11-22T10:00:10Z")],
      { viewerAccountId: VIEWER, now: new Date("2026-11-22T12:00:00Z") },
    );

    assert.deepEqual(
      rows.map((row) => row.kind),
      ["date", "message", "date", "message"],
    );
    const second = messageRows(rows)[1];
    assert.equal(second.merged, false);
  });

  it("treats an unknown day as neither today nor yesterday", () => {
    const now = new Date("2026-11-22T12:00:00Z");
    const rows = buildConversationRows([message("1", "9", "2026-11-01T10:00:00Z")], {
      viewerAccountId: VIEWER,
      now,
    });

    assert.notEqual(rows[0].kind === "date" ? rows[0].label : "", "今天");
    assert.equal(dayLabel("2026-11-22T09:00:00Z", now), "今天");
    assert.equal(dayLabel("2026-11-21T09:00:00Z", now), "昨天");
  });
});

describe("composer keys", () => {
  it("sends on a plain Enter", () => {
    assert.equal(
      shouldSendOnEnter({ key: "Enter", shiftKey: false, isComposing: false }, false),
      true,
    );
  });

  it("keeps Shift+Enter for a line break", () => {
    assert.equal(
      shouldSendOnEnter({ key: "Enter", shiftKey: true, isComposing: false }, false),
      false,
    );
  });

  it("leaves Enter to the IME while composing", () => {
    assert.equal(
      shouldSendOnEnter({ key: "Enter", shiftKey: false, isComposing: true }, false),
      false,
    );
    assert.equal(
      shouldSendOnEnter({ key: "Enter", shiftKey: false, isComposing: false }, true),
      false,
    );
  });

  it("ignores other keys", () => {
    assert.equal(
      shouldSendOnEnter({ key: "a", shiftKey: false, isComposing: false }, false),
      false,
    );
  });
});
