/*
 * Realtime transport for the user client (API-COM-RT-001／002).
 *
 * Frames follow `实时与任务.md`: the first client frame is
 * `hello {protocol_version, csrf_token, cursor?}`, the server answers
 * `hello_ok {connection_id, epoch, replay_floor, head_seq, heartbeat_seconds,
 * max_frame_bytes}` and then pushes `event`／`cursor_advance` frames. The client
 * acknowledges with `ack {epoch, through_seq}` only after the event is queued for
 * refresh, keeps a heartbeat via `ping`／`pong`, and on `sync_reset` reloads the
 * snapshot, then resumes from the head the server just reported.
 *
 * One connection per tab. Business screens subscribe to frames and re-read their
 * own data through the regular HTTP queries; the frame never carries message or
 * notification bodies.
 */
import { readonly, ref } from "vue";
import type { EventHead, RealtimeEventFrame, RealtimeFrame } from "../api/contracts";
import { refreshBadges } from "./badges";
import { readCsrfToken } from "./csrf";

type Handler = (frame: RealtimeEventFrame) => void;

export type RealtimeState =
  | "idle"
  | "connecting"
  | "ready"
  | "reconnecting"
  | "unauthenticated"
  | "protocol_error";

const PROTOCOL_VERSION = 1;
const MAX_BACKOFF_MS = 30_000;
/** Close codes defined by the realtime contract. */
const CLOSE_UNAUTHORIZED = 4401;
const CLOSE_FORBIDDEN = 4403;
const CLOSE_PROTOCOL = 4400;
const CLOSE_QUOTA = 4409;

const state = ref<RealtimeState>("idle");

const handlers = new Set<Handler>();
const snapshotReloaders = new Set<() => Promise<void> | void>();
let socket: WebSocket | null = null;
let epoch: string | null = null;
let cursor = 0;
let attempt = 0;
let closedByCaller = false;
let retryTimer: number | null = null;
let heartbeatTimer: number | null = null;
let lastHeartbeatAt = 0;

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

function send(payload: Record<string, unknown>): boolean {
  if (socket?.readyState !== WebSocket.OPEN) return false;
  socket.send(JSON.stringify(payload));
  return true;
}

/** Reload every subscribed snapshot; the caller resumes only after all succeed. */
export async function reloadRealtimeSnapshot(): Promise<void> {
  await refreshBadges();
  await Promise.all([...snapshotReloaders].map((reload) => reload()));
}

function clearHeartbeat(): void {
  if (heartbeatTimer !== null) {
    window.clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

function scheduleHeartbeat(seconds: number): void {
  clearHeartbeat();
  const interval = Math.max(1, seconds) * 1000;
  heartbeatTimer = window.setInterval(() => {
    lastHeartbeatAt = Date.now();
    send({ type: "ping", nonce: String(lastHeartbeatAt) });
  }, interval);
}

function acknowledge(): void {
  if (epoch === null || cursor <= 0) return;
  send({ type: "ack", epoch, through_seq: cursor });
}

function dispatch(frame: RealtimeFrame): void {
  if (frame.type === "cursor_advance") {
    // Those sequences were already handled by the connection that produced the
    // write; advance the local cursor without touching business state.
    cursor = Math.max(cursor, frame.through_seq);
    acknowledge();
    return;
  }
  cursor = Math.max(cursor, frame.account_seq);
  for (const handler of handlers) handler(frame);
  // Acknowledge only after the frame reached the local refresh queue; loading the
  // referenced bodies is a separate, retryable step.
  acknowledge();
}

async function open(): Promise<void> {
  const csrfToken = readCsrfToken();
  if (csrfToken === null) {
    // Without the session CSRF credential the server will reject the handshake,
    // so report the state instead of opening a connection that cannot succeed.
    state.value = "unauthenticated";
    return;
  }
  state.value = attempt === 0 ? "connecting" : "reconnecting";
  if (!epoch) {
    const head = await fetchHead();
    epoch = head.epoch;
    cursor = Math.max(head.replay_floor, cursor);
  }
  const connection = new WebSocket(realtimeUrl());
  socket = connection;

  connection.addEventListener("open", () => {
    const hello: Record<string, unknown> = {
      type: "hello",
      protocol_version: PROTOCOL_VERSION,
      csrf_token: csrfToken,
    };
    if (epoch !== null) hello.cursor = { epoch, after_seq: cursor };
    send(hello);
  });

  connection.addEventListener("message", (event) => {
    let payload: unknown;
    try {
      payload = JSON.parse(String(event.data));
    } catch {
      return;
    }
    const frame = payload as { type?: string };
    switch (frame.type) {
      case "hello_ok": {
        const accepted = payload as {
          epoch?: string;
          head_seq?: number;
          heartbeat_seconds?: number;
        };
        if (typeof accepted.epoch === "string") epoch = accepted.epoch;
        if (typeof accepted.head_seq === "number") cursor = Math.max(accepted.head_seq, cursor);
        state.value = "ready";
        attempt = 0;
        scheduleHeartbeat(accepted.heartbeat_seconds ?? 20);
        return;
      }
      case "ping":
        // Answer the server heartbeat with the same nonce.
        send({ type: "pong", nonce: (payload as { nonce?: string }).nonce ?? "" });
        return;
      case "pong":
        return;
      case "sync_reset":
        void handleSyncReset();
        return;
      case "auth_required":
        state.value = "unauthenticated";
        stopRealtime();
        return;
      default:
        dispatch(payload as RealtimeFrame);
    }
  });

  connection.addEventListener("close", (closeEvent) => {
    if (socket === connection) socket = null;
    clearHeartbeat();
    if (closedByCaller) {
      state.value = "idle";
      return;
    }
    if (closeEvent.code === CLOSE_UNAUTHORIZED || closeEvent.code === CLOSE_FORBIDDEN) {
      state.value = "unauthenticated";
      return;
    }
    if (closeEvent.code === CLOSE_PROTOCOL) {
      // A protocol mismatch is not fixed by retrying the same frames.
      state.value = "protocol_error";
      return;
    }
    scheduleReconnect(closeEvent.code === CLOSE_QUOTA ? 4 : 1);
  });

  connection.addEventListener("error", () => {
    // A `close` event always follows; the retry policy lives there so it runs once.
  });
}

async function handleSyncReset(): Promise<void> {
  try {
    // Load the snapshot first, then resume from the head the server reports so no
    // event between the old cursor and the new head is skipped.
    await reloadRealtimeSnapshot();
    const head = await fetchHead();
    epoch = head.epoch;
    cursor = Math.max(head.replay_floor, head.head_seq);
    send({ type: "resume", epoch, after_seq: cursor });
  } catch {
    scheduleReconnect(1);
  }
}

function scheduleReconnect(multiplier: number): void {
  state.value = "reconnecting";
  attempt += 1;
  const delay = Math.min(MAX_BACKOFF_MS, multiplier * 1_000 * 2 ** Math.min(attempt, 5));
  if (retryTimer !== null) window.clearTimeout(retryTimer);
  retryTimer = window.setTimeout(() => {
    void open().catch(() => scheduleReconnect(1));
  }, delay);
}

export function startRealtime(): void {
  if (socket) return;
  closedByCaller = false;
  attempt = 0;
  void open().catch(() => scheduleReconnect(1));
}

export function stopRealtime(): void {
  closedByCaller = true;
  if (retryTimer !== null) {
    window.clearTimeout(retryTimer);
    retryTimer = null;
  }
  clearHeartbeat();
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
}

/** Connection state for a subtle "reconnecting" hint in the business screens. */
export const realtimeState = readonly(state);
