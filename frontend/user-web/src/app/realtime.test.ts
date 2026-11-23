/*
 * Protocol test for the realtime client.
 *
 * A simulated server drives the frames the backend actually sends
 * (`hello_ok`, `ping`, `event`, `cursor_advance`, `sync_reset`) so the handshake
 * shape, heartbeat answer, acknowledgement bound and resync ordering are checked
 * without a running stack.
 */
import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import type { EventHead, RealtimeEventFrame } from "../api/contracts";
import {
  registerSnapshotReloader,
  resetRealtimeCursor,
  realtimeState,
  startRealtime,
  stopRealtime,
  subscribeRealtime,
  useRealtimeDeps,
  type RealtimeSocket,
} from "./realtime";

type Frame = Record<string, unknown>;

class FakeSocket implements RealtimeSocket {
  readyState = 1;
  readonly sent: Frame[] = [];
  private readonly listeners = new Map<string, ((event: unknown) => void)[]>();

  addEventListener(type: string, listener: (event: unknown) => void): void {
    const existing = this.listeners.get(type) ?? [];
    existing.push(listener);
    this.listeners.set(type, existing);
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data) as Frame);
  }

  close(): void {
    this.readyState = 3;
    this.emit("close", { code: 1000 });
  }

  emit(type: string, event: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }

  /** Simulate a frame pushed by the server. */
  push(frame: Frame): void {
    this.emit("message", { data: JSON.stringify(frame) });
  }

  last(): Frame {
    const frame = this.sent[this.sent.length - 1];
    assert.ok(frame, "expected the client to have sent a frame");
    return frame;
  }
}

const HEAD: EventHead = { epoch: "epoch-1", head_seq: 4, replay_floor: 0 };

function tick(times = 3): Promise<void> {
  let promise = Promise.resolve();
  for (let index = 0; index < times; index++) {
    promise = promise.then(() => new Promise<void>((resolve) => setTimeout(resolve, 0)));
  }
  return promise;
}

interface Harness {
  socket: FakeSocket;
  state(): string;
  restore(): void;
}

/** Wire the client to a fake socket and one head response. */
async function connect(options: { head?: EventHead; csrf?: string | null } = {}): Promise<Harness> {
  const socket = new FakeSocket();
  const head = options.head ?? HEAD;
  const restore = useRealtimeDeps({
    createSocket: () => socket,
    fetchHead: async () => head,
    csrfToken: () => (options.csrf === undefined ? "csrf-token" : options.csrf),
  });
  startRealtime();
  await tick();
  socket.emit("open", {});
  await tick();
  return { socket, state: () => realtimeState.value, restore };
}

const disposers: (() => void)[] = [];

afterEach(() => {
  stopRealtime();
  resetRealtimeCursor();
  while (disposers.length > 0) disposers.pop()?.();
});

describe("realtime client", () => {
  it("sends the framed hello and only reports ready after hello_ok", async () => {
    const harness = await connect();
    disposers.push(harness.restore);

    assert.deepEqual(harness.socket.sent[0], {
      type: "hello",
      protocol_version: 1,
      csrf_token: "csrf-token",
      cursor: { epoch: "epoch-1", after_seq: 0 },
    });
    assert.notEqual(harness.state(), "ready");

    harness.socket.push({ type: "hello_ok", epoch: "epoch-1", head_seq: 4, heartbeat_seconds: 60 });
    await tick();
    assert.equal(harness.state(), "ready");
  });

  it("does not open a connection without the session CSRF credential", async () => {
    const harness = await connect({ csrf: null });
    disposers.push(harness.restore);

    assert.equal(harness.state(), "unauthenticated");
    assert.equal(harness.socket.sent.length, 0);
  });

  it("answers a server ping with the same nonce", async () => {
    const harness = await connect();
    disposers.push(harness.restore);
    harness.socket.push({ type: "hello_ok", epoch: "epoch-1", head_seq: 4, heartbeat_seconds: 60 });
    await tick();

    harness.socket.push({ type: "ping", nonce: "nonce-7" });
    await tick();
    assert.deepEqual(harness.socket.last(), { type: "pong", nonce: "nonce-7" });
  });

  it("acks an event with the sequence and covers cursor advances in through_seq", async () => {
    const harness = await connect();
    disposers.push(harness.restore);
    harness.socket.push({ type: "hello_ok", epoch: "epoch-1", head_seq: 0, heartbeat_seconds: 60 });
    await tick();

    const seen: RealtimeEventFrame[] = [];
    const dispose = subscribeRealtime((frame) => seen.push(frame));
    disposers.push(dispose);

    harness.socket.push({
      type: "event",
      epoch: "epoch-1",
      event_id: "evt-1",
      account_seq: 5,
      event_type: "message_created",
      data: { conversation_id: "c1" },
    });
    await tick();
    assert.equal(seen.length, 1);
    assert.deepEqual(harness.socket.last(), { type: "ack", epoch: "epoch-1", through_seq: 5 });

    harness.socket.push({ type: "cursor_advance", epoch: "epoch-1", from_seq: 5, through_seq: 9 });
    await tick();
    assert.deepEqual(harness.socket.last(), { type: "ack", epoch: "epoch-1", through_seq: 9 });
  });

  it("ignores unknown control frames without corrupting the cursor", async () => {
    const harness = await connect();
    disposers.push(harness.restore);
    harness.socket.push({ type: "hello_ok", epoch: "epoch-1", head_seq: 0, heartbeat_seconds: 60 });
    await tick();

    const seen: RealtimeEventFrame[] = [];
    const dispose = subscribeRealtime((frame) => seen.push(frame));
    disposers.push(dispose);

    // Not a business frame and carries no sequence.
    harness.socket.push({ type: "future_control", note: "unknown" });
    await tick();
    assert.equal(seen.length, 0);

    harness.socket.push({
      type: "event",
      epoch: "epoch-1",
      event_id: "evt-2",
      account_seq: 9,
      event_type: "notification_created",
      data: {},
    });
    await tick();
    const ack = harness.socket.last();
    assert.equal(ack.type, "ack");
    assert.equal(ack.through_seq, 9);
    assert.equal(Number.isNaN(ack.through_seq as number), false);
  });

  it("records the head before reloading snapshots and resumes from that head", async () => {
    const order: string[] = [];
    const socket = new FakeSocket();
    const before: EventHead = { epoch: "epoch-1", head_seq: 4, replay_floor: 0 };
    const recorded: EventHead = { epoch: "epoch-2", head_seq: 20, replay_floor: 0 };
    let headReads = 0;
    const restore = useRealtimeDeps({
      createSocket: () => socket,
      fetchHead: async () => {
        // The first read opens the connection, the later one serves the resync and
        // reports a newer head than the snapshot covers.
        order.push("head");
        headReads += 1;
        return headReads === 1 ? before : recorded;
      },
      csrfToken: () => "csrf-token",
    });
    disposers.push(restore);
    const unregister = registerSnapshotReloader(() => {
      order.push("snapshot");
    });
    disposers.push(unregister);

    startRealtime();
    await tick();
    socket.emit("open", {});
    await tick();
    socket.push({ type: "hello_ok", epoch: "epoch-1", head_seq: 4, heartbeat_seconds: 60 });
    await tick();
    order.length = 0;

    socket.push({ type: "sync_reset" });
    await tick(6);

    assert.deepEqual(order, ["head", "snapshot"]);
    assert.deepEqual(socket.last(), { type: "resume", epoch: "epoch-2", after_seq: 20 });
  });

  it("stops on an unauthorized close instead of retrying", async () => {
    const harness = await connect();
    disposers.push(harness.restore);
    harness.socket.push({ type: "hello_ok", epoch: "epoch-1", head_seq: 4, heartbeat_seconds: 60 });
    await tick();

    harness.socket.emit("close", { code: 4401 });
    await tick();
    assert.equal(harness.state(), "unauthenticated");
    // A protocol mismatch must not be retried with a new socket either.
    assert.equal(harness.socket.sent.filter((frame) => frame.type === "hello").length, 1);
  });
});
