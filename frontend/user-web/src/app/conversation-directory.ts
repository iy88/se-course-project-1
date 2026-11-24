/*
 * Peer directory shared by the conversation list and the thread.
 *
 * The list endpoint is the only place that returns the counterparty name for a
 * branch, so the thread reads it from here instead of showing a bare kind label.
 * The map is filled by the list pane and treated as a cache: an unknown id simply
 * falls back to the kind label.
 */
import { ref } from "vue";

const names = ref<Map<string, string>>(new Map());

/** Stable key for one conversation branch. */
export function conversationKey(kind: string, conversationId: string): string {
  return `${kind}:${conversationId}`;
}

export function rememberPeer(kind: string, conversationId: string, displayName: string): void {
  const key = conversationKey(kind, conversationId);
  if (names.value.get(key) === displayName) return;
  const next = new Map(names.value);
  next.set(key, displayName);
  names.value = next;
}

export function peerName(kind: string, conversationId: string): string | null {
  return names.value.get(conversationKey(kind, conversationId)) ?? null;
}
