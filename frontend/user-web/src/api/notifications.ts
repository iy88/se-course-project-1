/*
 * In-site notifications for the current account.
 * Paths follow docs/design/detailed-design/interfaces/账户与通知.md
 * (API-COM-NOTIFY-002—004).
 */
import { request } from "./http";
import type {
  ListNotificationsQuery,
  MarkNotificationReadResult,
  NotificationPage,
  NotificationDetail,
} from "./contracts";

export function listNotifications(
  query: ListNotificationsQuery,
  signal?: AbortSignal,
): Promise<NotificationPage> {
  return request<NotificationPage>("GET", "/account/notifications", {
    query,
    signal,
  });
}

export function getNotification(
  notificationId: string,
  signal?: AbortSignal,
): Promise<NotificationDetail> {
  return request<NotificationDetail>("GET", `/account/notifications/${notificationId}`, {
    signal,
  });
}

export function markNotificationRead(
  notificationId: string,
  idempotencyKey: string,
): Promise<MarkNotificationReadResult> {
  return request<MarkNotificationReadResult>(
    "PUT",
    `/account/notifications/${notificationId}/read`,
    { idempotencyKey },
  );
}
