import { request } from "./http";

export type NotificationFilter = "all" | "unread" | "read";

export interface ManagementNotification {
  notification_id: string;
  summary: string;
  subject?: string;
  occurred_at: string;
  read_at: string | null;
  source: { resource_type: string; resource_id: string } | null;
  body?: string;
  anchor?: string;
}

interface NotificationPage {
  items: ManagementNotification[];
  total: number;
  unread_count: number;
}

const path = "/account/notifications";
const audience = "management";

export function listNotifications(
  page: number,
  pageSize: number,
  read: NotificationFilter,
  signal: AbortSignal,
) {
  return request<NotificationPage>("GET", path, {
    query: { audience, page, page_size: pageSize, read },
    signal,
  });
}

export function readNotification(id: string, signal: AbortSignal) {
  return request<ManagementNotification>("GET", `${path}/${encodeURIComponent(id)}`, {
    query: { audience },
    signal,
  });
}

export function markNotificationRead(id: string, idempotencyKey: string, signal: AbortSignal) {
  return request<{ read_at: string }>("PUT", `${path}/${encodeURIComponent(id)}/read`, {
    query: { audience },
    idempotencyKey,
    signal,
  });
}
