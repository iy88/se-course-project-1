/*
 * Unread notification count shown on the navigation.
 *
 * Views refresh the count after a write; the shell refreshes it on navigation.
 */
import { ref } from "vue";
import { listNotifications } from "../api/notifications";
import { AbortedError } from "../api/errors";
import { session } from "./session";

const notificationUnread = ref(0);
let inFlight: AbortController | null = null;

export async function refreshBadges(): Promise<void> {
  inFlight?.abort();
  if (!session.isAuthenticated.value) {
    notificationUnread.value = 0;
    return;
  }
  inFlight = new AbortController();
  const signal = inFlight.signal;
  try {
    const notifications = await listNotifications(
      { page: 1, page_size: 1, read: "unread" },
      signal,
    );
    notificationUnread.value = notifications.unread_count;
  } catch (error) {
    if (error instanceof AbortedError) return;
    // A failed badge refresh must not break navigation; the destination screen
    // reports its own failure with a retry.
  }
}

export const badges = {
  notificationUnread,
};

export function resetBadges(): void {
  notificationUnread.value = 0;
}
