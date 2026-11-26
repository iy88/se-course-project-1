/*
 * Peer directory shared by the conversation list and the thread.
 *
 * The list endpoint returns both the counterparty name and account id for each
 * branch, so the thread can show the name and, for a trade branch, offer the
 * private-chat entry point without re-reading the conversation list. The map is
 * a cache: a missing entry falls back to the kind label or a trade lookup.
 */
import { ref } from "vue";

interface PeerRecord {
  accountId: string | null;
  displayName: string;
}

const peers = ref<Map<string, PeerRecord>>(new Map());

/** Stable key for one conversation branch. */
export function conversationKey(kind: string, conversationId: string): string {
  return `${kind}:${conversationId}`;
}

export function rememberPeer(
  kind: string,
  conversationId: string,
  displayName: string,
  accountId?: string,
): void {
  const key = conversationKey(kind, conversationId);
  const existing = peers.value.get(key);
  const nextId = accountId ?? existing?.accountId ?? null;
  if (existing?.displayName === displayName && existing.accountId === nextId) return;
  const next = new Map(peers.value);
  next.set(key, { accountId: nextId, displayName });
  peers.value = next;
}

export function peerName(kind: string, conversationId: string): string | null {
  return peers.value.get(conversationKey(kind, conversationId))?.displayName ?? null;
}

export function peerAccountId(kind: string, conversationId: string): string | null {
  return peers.value.get(conversationKey(kind, conversationId))?.accountId ?? null;
}
