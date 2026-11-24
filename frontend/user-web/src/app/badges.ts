/*
 * Unread counters shown on the navigation.
 *
 * The counts come from the same list endpoints the destination screens use, so
 * the badge can never disagree with the page it points at. Views refresh them
 * after a write; the shell refreshes them on navigation.
 */
import { ref } from "vue";
import { listConversations } from "../api/conversations";
import { listNotifications } from "../api/notifications";
import { AbortedError } from "../api/errors";
import { session } from "./session";

const notificationUnread = ref(0);
const conversationUnread = ref(0);
let inFlight: AbortController | null = null;

export async function refreshBadges(): Promise<void> {
  if (!session.isAuthenticated.value) {
    notificationUnread.value = 0;
    conversationUnread.value = 0;
    return;
  }
  inFlight?.abort();
  inFlight = new AbortController();
  const signal = inFlight.signal;
  try {
    const [notifications, conversations] = await Promise.all([
      listNotifications({ page: 1, page_size: 1, read: "unread" }, signal),
      listConversations(1, 50, signal),
    ]);
    notificationUnread.value = notifications.unread_count;
    conversationUnread.value = conversations.items.reduce(
      (sum, entry) =>
        sum + entry.branches.reduce((inner, branch) => inner + branch.unread_count, 0),
      0,
    );
  } catch (error) {
    if (error instanceof AbortedError) return;
    // A failed badge refresh must not break navigation; the destination screen
    // reports its own failure with a retry.
  }
}

export const badges = {
  notificationUnread,
  conversationUnread,
};

export function resetBadges(): void {
  notificationUnread.value = 0;
  conversationUnread.value = 0;
}
