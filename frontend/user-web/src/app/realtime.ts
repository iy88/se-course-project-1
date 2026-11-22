/*
 * Realtime transport for the user client.
 *
 * One connection per browser tab. The client keeps the account event cursor,
 * acknowledges the last contiguous sequence it has processed, and when the server
 * answers `sync_reset` it reloads the snapshot through the existing HTTP queries
 * before resuming from the new head — the resync order described in #79's
 * coordination comment.
 *
 * The client-to-server frames (`hello`, `ack`, `resume`) are not part of the
 * published OpenAPI; they follow the delivery description in
 * README「实时 HTTP 与 WebSocket」and need confirmation from the S3-01 work
 * package before the connection is used against a real server.
 */
import { readonly, ref } from "vue";
import { getDataSource } from "../api/http";
import type { EventHead, RealtimeEventFrame, RealtimeFrame } from "../api/contracts";
import { refreshBadges } from "./badges";

type Handler = (frame: RealtimeEventFrame) => void;

type ConnectionState = "idle" | "connecting" | "ready" | "reconnecting" | "disabled";

const state = ref<ConnectionState>("idle");
const lastSequenced = ref(0);

const handlers = new Set<Handler>();
const snapshotReloaders = new Set<() => Promise<void> | void>();
let socket: WebSocket | null = null;
let epoch: string | null = null;
let cursor = 0;
let attempt = 0;
let closedByCaller = false;
let retryTimer: number | null = null;

const MAX_BACKOFF_MS = 30_000;

function realtimeUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/v1/realtime`;
}

async function fetchHead(): Promise<EventHead> {
  const response = await fetch("/api/v1/account/events/head", {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  if (!response.ok) throw new Error(`事件头读取失败（HTTP ${response.status}）`);
  return (await response.json()) as EventHead;
}

function send(payload: unknown): void {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
}

/** Reload every subscribed snapshot; the caller resumes only after all succeed. */
export async function reloadRealtimeSnapshot(): Promise<void> {
  await refreshBadges();
  await Promise.all([...snapshotReloaders].map((reload) => reload()));
}

function dispatch(frame: RealtimeFrame): void {
  if (frame.type === "cursor_advance") {
    // Carries no business payload: those sequences were already handled by the
    // connection that produced the write.
    cursor = Math.max(cursor, frame.through_seq);
    lastSequenced.value = cursor;
    return;
  }
  cursor = Math.max(cursor, frame.account_seq);
  lastSequenced.value = cursor;
  send({ type: "ack", epoch: frame.epoch, account_seq: cursor });
  for (const handler of handlers) handler(frame);
}

async function open(): Promise<void> {
  state.value = attempt === 0 ? "connecting" : "reconnecting";
  if (!epoch) {
    const head = await fetchHead();
    epoch = head.epoch;
    cursor = Math.max(head.replay_floor, cursor);
  }
  const connection = new WebSocket(realtimeUrl());
  socket = connection;

  connection.addEventListener("open", () => {
    send({ type: "hello", version: 1, epoch, after_seq: cursor });
    state.value = "ready";
    attempt = 0;
  });

  connection.addEventListener("message", (event) => {
    let payload: unknown;
    try {
      payload = JSON.parse(String(event.data));
    } catch {
      return;
    }
    const record = payload as { type?: string };
    if (record.type === "sync_reset") {
      void handleSyncReset();
      return;
    }
    if (record.type === "ready" || record.type === "resume_ok") return;
    dispatch(payload as RealtimeFrame);
  });

  connection.addEventListener("close", () => {
    if (socket === connection) socket = null;
    if (closedByCaller) {
      state.value = "idle";
      return;
    }
    scheduleReconnect();
  });

  connection.addEventListener("error", () => {
    // A `close` event always follows; the retry policy lives there so it runs once.
  });
}

async function handleSyncReset(): Promise<void> {
  try {
    await reloadRealtimeSnapshot();
    const head = await fetchHead();
    epoch = head.epoch;
    cursor = Math.max(head.replay_floor, head.head_seq);
    send({ type: "resume", epoch, after_seq: cursor });
  } catch {
    scheduleReconnect();
  }
}

function scheduleReconnect(): void {
  state.value = "reconnecting";
  attempt += 1;
  const delay = Math.min(MAX_BACKOFF_MS, 1_000 * 2 ** Math.min(attempt, 5));
  if (retryTimer !== null) window.clearTimeout(retryTimer);
  retryTimer = window.setTimeout(() => {
    void open().catch(() => scheduleReconnect());
  }, delay);
}

export function startRealtime(): void {
  if (getDataSource() === "mock") {
    // The simulated data source answers over HTTP only; screens refetch after each
    // write instead of receiving pushed frames.
    state.value = "disabled";
    return;
  }
  if (socket) return;
  closedByCaller = false;
  attempt = 0;
  void open().catch(() => scheduleReconnect());
}

export function stopRealtime(): void {
  closedByCaller = true;
  if (retryTimer !== null) {
    window.clearTimeout(retryTimer);
    retryTimer = null;
  }
  socket?.close();
  socket = null;
  state.value = "idle";
}

/** Register a business-frame handler; returns the disposer. */
export function subscribeRealtime(handler: Handler): () => void {
  handlers.add(handler);
  if (handlers.size === 1) startRealtime();
  return () => {
    handlers.delete(handler);
    if (handlers.size === 0) stopRealtime();
  };
}

/** Register a snapshot reloader consulted before resuming after `sync_reset`. */
export function registerSnapshotReloader(reload: () => Promise<void> | void): () => void {
  snapshotReloaders.add(reload);
  return () => {
    snapshotReloaders.delete(reload);
  };
}

/** Forget the cursor after re-authentication so the next connection starts clean. */
export function resetRealtimeCursor(): void {
  epoch = null;
  cursor = 0;
  lastSequenced.value = 0;
}

export const realtime = {
  state: readonly(state),
  lastSequenced: readonly(lastSequenced),
};
