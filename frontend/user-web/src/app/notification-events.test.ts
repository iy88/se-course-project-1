import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { RealtimeEventFrame } from "../api/contracts";
import {
  notificationIdFromFrame,
  refreshesNotificationDetail,
  refreshesNotificationList,
} from "./notification-events";

function frame(eventType: RealtimeEventFrame["event_type"], data: Record<string, unknown> = {}) {
  return {
    type: "event",
    epoch: "epoch-1",
    event_id: "event-1",
    account_seq: 1,
    schema_version: 1,
    occurred_at: "2026-11-20T09:00:00Z",
    event_type: eventType,
    data,
  } satisfies RealtimeEventFrame;
}

describe("notification realtime matching", () => {
  it("accepts created and read events and keeps string ids", () => {
    const created = frame("notification_created", { notification_id: "42" });
    assert.equal(refreshesNotificationList(created), true);
    assert.equal(notificationIdFromFrame(created), "42");
  });

  it("does not refresh a detail for another notification", () => {
    const read = frame("notification_read", { notification_id: "42" });
    assert.equal(refreshesNotificationDetail(read, "42"), true);
    assert.equal(refreshesNotificationDetail(read, "43"), false);
  });

  it("ignores unrelated business frames", () => {
    const message = frame("message_created", { conversation_id: "1" });
    assert.equal(refreshesNotificationList(message), false);
    assert.equal(notificationIdFromFrame(message), null);
  });

  it("accepts a legacy numeric notification id", () => {
    assert.equal(
      notificationIdFromFrame(frame("notification_created", { notification_id: 7 })),
      "7",
    );
  });
});
