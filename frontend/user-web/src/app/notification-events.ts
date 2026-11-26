/*
 * Pure rules for consuming notification realtime frames.
 *
 * Business frames only carry a stable reference; the listed notification still
 * has to be read through its own endpoint. Keeping the matching rules here stops
 * list and detail screens from reacting to unrelated events or from treating a
 * replay as a read write.
 */
import type { RealtimeEventFrame } from "../api/contracts";

export const NOTIFICATION_EVENT_TYPES = ["notification_created", "notification_read"] as const;

export function isNotificationEventType(eventType: string): boolean {
  return (NOTIFICATION_EVENT_TYPES as readonly string[]).includes(eventType);
}

/** Read the notification reference from a frame; legacy numeric ids are accepted. */
export function notificationIdFromFrame(frame: RealtimeEventFrame): string | null {
  const value = frame.data.notification_id;
  if (typeof value === "string" && value !== "") return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

/** A notification event may change the unread badge and an open list page. */
export function refreshesNotificationList(frame: RealtimeEventFrame): boolean {
  return isNotificationEventType(frame.event_type);
}

/** Only a frame for the notification currently open may refresh that detail. */
export function refreshesNotificationDetail(
  frame: RealtimeEventFrame,
  notificationId: string,
): boolean {
  return (
    isNotificationEventType(frame.event_type) && notificationIdFromFrame(frame) === notificationId
  );
}
