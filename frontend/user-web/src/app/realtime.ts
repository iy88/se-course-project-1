/*
 * Realtime transport for the user client (API-COM-RT-001／002).
 *
 * Frames follow `实时与任务.md` and the server implementation: the first client
 * frame is `hello {protocol_version, csrf_token, cursor?}`; the server answers
 * `hello_ok {epoch, head_seq, replay_floor, connection_id, heartbeat_seconds,
 * max_frame_bytes}` and then pushes `event`／`cursor_advance`. The client
 * acknowledges with `ack {epoch, through_seq}` only once the event is queued for
 * refresh, answers the server heartbeat with the same nonce, and on `sync_reset`
 * records the head first, reloads the snapshot, then resumes from that recorded
 * head so nothing written during the snapshot read is skipped.
 *
 * Only `event` frames reach business subscribers: every other frame type is
 * either handled here or ignored, so an unknown control frame can never corrupt
 * the cursor.
 *
 * One connection per tab. Sockets, the head request and the CSRF source are
 * injectable so the protocol can be exercised without a server.
 */
import { readonly, ref } from "vue";
import type { EventHead, RealtimeEventFrame } from "../api/contracts";
import { readCsrfToken } from "./csrf";

type Handler = (frame: RealtimeEventFrame) => void;

export type RealtimeState =
  | "idle"
  | "connecting"
  | "ready"
  | "reconnecting"
  | "unauthenticated"
  | "protocol_error";

/** The subset of the WebSocket API this client uses. */
export interface RealtimeSocket {
  readonly readyState: number;
  send(data: string): void;
  close(): void;
  addEventListener(type: string, listener: (event: unknown) => void): void;
}

export interface RealtimeDeps {
  createSocket(url: string): RealtimeSocket;
  fetchHead(): Promise<EventHead>;
  csrfToken(): string | null;
}

const PROTOCOL_VERSION = 1;
const SOCKET_OPEN = 1;
const MAX_BACKOFF_MS = 30_000;
/** Close codes defined by the realtime contract. */
const CLOSE_UNAUTHORIZED = 4401;
const CLOSE_FORBIDDEN = 4403;
const CLOSE_PROTOCOL = 4400;
const CLOSE_QUOTA = 4409;

const state = ref<RealtimeState>("idle");

const handlers = new Set<Handler>();
const snapshotReloaders = new Set<() => Promise<void> | void>();
let socket: RealtimeSocket | null = null;
let epoch: string | null = null;
let cursor = 0;
let attempt = 0;
let closedByCaller = false;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;

function realtimeUrl(): string {
  const location = globalThis.location;
  const protocol = location?.protocol === "https:" ? "wss:" : "ws:";
  const host = location?.host ?? "127.0.0.1";
  return `${protocol}//${host}/api/v1/realtime`;
}

async function defaultFetchHead(): Promise<EventHead> {
  const response = await fetch("/api/v1/account/events/head", {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  if (!response.ok) throw new Error(`事件头读取失败（HTTP ${response.status}）`);
  return (await response.json()) as EventHead;
}

let deps: RealtimeDeps = {
  createSocket: (url) => new WebSocket(url) as unknown as RealtimeSocket,
  fetchHead: defaultFetchHead,
  csrfToken: readCsrfToken,
};

/** Replace transport dependencies; returns a restore function. */
export function useRealtimeDeps(overrides: Partial<RealtimeDeps>): () => void {
  const previous = deps;
  deps = { ...deps, ...overrides };
  return () => {
    deps = previous;
  };
}

function send(payload: Record<string, unknown>): boolean {
  if (socket?.readyState !== SOCKET_OPEN) return false;
  socket.send(JSON.stringify(payload));
  return true;
}

/** Reload every registered snapshot; the caller resumes only after all succeed. */
export async function reloadRealtimeSnapshot(): Promise<void> {
  await Promise.all([...snapshotReloaders].map((reload) => reload()));
}

function clearHeartbeat(): void {
  if (heartbeatTimer !== null) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

function scheduleHeartbeat(seconds: number): void {
  clearHeartbeat();
  heartbeatTimer = setInterval(
    () => {
      send({ type: "ping", nonce: `${Date.now()}` });
    },
    Math.max(1, seconds) * 1000,
  );
}

function acknowledge(): void {
  if (epoch === null || cursor <= 0) return;
  // `through_seq` covers every sequence already advanced, including cursor_advance.
  send({ type: "ack", epoch, through_seq: cursor });
}

function dispatchEvent(frame: RealtimeEventFrame): void {
  if (typeof frame.account_seq !== "number") return;
  cursor = Math.max(cursor, frame.account_seq);
  for (const handler of handlers) handler(frame);
  acknowledge();
}

async function open(): Promise<void> {
  const csrfToken = deps.csrfToken();
  if (csrfToken === null) {
    // Without the session CSRF credential the server rejects the handshake with
    // 4400, so report the state instead of opening a connection that cannot work.
    state.value = "unauthenticated";
    return;
  }
  state.value = attempt === 0 ? "connecting" : "reconnecting";
  if (!epoch) {
    const head = await deps.fetchHead();
    epoch = head.epoch;
    cursor = Math.max(head.replay_floor, cursor);
  }
  const connection = deps.createSocket(realtimeUrl());
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
      payload = JSON.parse(String((event as { data: unknown }).data));
    } catch {
      return;
    }
    if (typeof payload !== "object" || payload === null) return;
    switch ((payload as { type?: unknown }).type) {
      case "hello_ok": {
        const accepted = payload as {
          epoch?: unknown;
          heartbeat_seconds?: unknown;
        };
        if (typeof accepted.epoch === "string") epoch = accepted.epoch;
        /*
         * `head_seq` is deliberately ignored: it is the server's newest sequence, not
         * a sequence this client received. Adopting it would acknowledge events the
         * server never sent (a backlog replay from 10 with head 100 would ACK 100 on
         * the first event). Only `event` and `cursor_advance` advance the cursor.
         */
        state.value = "ready";
        attempt = 0;
        if (typeof accepted.heartbeat_seconds === "number") {
          scheduleHeartbeat(accepted.heartbeat_seconds);
        }
        return;
      }
      case "ping":
        // Answer with the same nonce; the server rejects a mismatched pong.
        send({ type: "pong", nonce: (payload as { nonce?: unknown }).nonce ?? "" });
        return;
      case "pong":
        return;
      case "sync_reset":
        void handleSyncReset(payload as SyncResetFrame, connection);
        return;
      case "auth_required":
        state.value = "unauthenticated";
        stopRealtime();
        return;
      case "cursor_advance": {
        const advance = payload as { through_seq?: unknown };
        if (typeof advance.through_seq !== "number") return;
        cursor = Math.max(cursor, advance.through_seq);
        acknowledge();
        return;
      }
      case "event":
        dispatchEvent(payload as RealtimeEventFrame);
        return;
      default:
        // Unknown control frames never touch the cursor.
        return;
    }
  });

  connection.addEventListener("close", (event) => {
    if (socket === connection) socket = null;
    clearHeartbeat();
    if (closedByCaller) {
      state.value = "idle";
      return;
    }
    const code = (event as { code?: number }).code ?? 1006;
    if (code === CLOSE_UNAUTHORIZED || code === CLOSE_FORBIDDEN) {
      state.value = "unauthenticated";
      return;
    }
    if (code === CLOSE_PROTOCOL) {
      // Retrying the same frames cannot fix a protocol mismatch.
      state.value = "protocol_error";
      return;
    }
    scheduleReconnect(code === CLOSE_QUOTA ? 4 : 1);
  });

  connection.addEventListener("error", () => {
    // A `close` event always follows, so the retry policy lives there.
  });
}

/**
 * The reset frame carries the head the server will replay from, so no extra HTTP
 * read is needed and the resume always belongs to the connection that asked for it.
 */
interface SyncResetFrame {
  epoch?: unknown;
  head_seq?: unknown;
  replay_floor?: unknown;
}

/**
 * Resynchronise after `sync_reset`.
 *
 * The snapshot is reloaded first and the resume is sent only to the connection that
 * received the reset and is still the active one; a stale connection must not write
 * the shared cursor or resume a newer socket. When the snapshot fails the original
 * connection is closed so the single close path owns reconnection.
 */
async function handleSyncReset(frame: SyncResetFrame, connection: RealtimeSocket): Promise<void> {
  const resetEpoch = typeof frame.epoch === "string" ? frame.epoch : null;
  const resetHead = typeof frame.head_seq === "number" ? frame.head_seq : null;
  const resetFloor = typeof frame.replay_floor === "number" ? frame.replay_floor : 0;
  try {
    await reloadRealtimeSnapshot();
  } catch {
    connection.close();
    return;
  }
  if (socket !== connection || connection.readyState !== SOCKET_OPEN) return;
  if (resetEpoch !== null) epoch = resetEpoch;
  if (resetHead !== null) cursor = Math.max(resetFloor, resetHead);
  send({ type: "resume", epoch, after_seq: cursor });
}

function scheduleReconnect(multiplier: number): void {
  state.value = "reconnecting";
  attempt += 1;
  const delay = Math.min(MAX_BACKOFF_MS, multiplier * 1_000 * 2 ** Math.min(attempt, 5));
  if (retryTimer !== null) clearTimeout(retryTimer);
  retryTimer = setTimeout(() => {
    retryTimer = null;
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
    clearTimeout(retryTimer);
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
