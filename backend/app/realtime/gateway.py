"""WS gateway: one writer per connection, bounded queues and replay.

Delivery order is always ``user_seq``. The Redis stream is only a hint: when it
is unavailable, trimmed, restarted or loses the final entry, the periodic
PostgreSQL reconciliation still fetches every committed event above the
connection's sent cursor. A connection is registered before the high watermark
is read, so events arriving during replay are either included in the replay or
picked up by reconciliation afterwards; they are never silently dropped.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from fastapi import WebSocket
from sqlmodel import select
from starlette.websockets import WebSocketDisconnect, WebSocketDisconnected

from app.core.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.kv.base import KVError, get_kv
from app.observability import counters
from app.realtime.events import event_wire, high_watermark, low_watermark, replay_events
from app.realtime.stream import RealtimeStream, StreamError, StreamReader, decode_frame

logger = logging.getLogger(__name__)

CLOSE_AUTH = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_POLICY = 1008
CLOSE_TOO_LARGE = 1009
CLOSE_OVERLOAD = 1013
CLOSE_LIMIT = 4429

_FRAME_BUCKET_CAPACITY = 40
_FRAME_BUCKET_RATE = 20.0  # frames/second


@dataclass
class Connection:
    ws: WebSocket
    user_id: int
    since: int
    auth_expires_at: int
    settings: Settings
    ip: str | None = None
    legacy: bool = False
    conn_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    # One bounded AnyIO memory stream per connection. Live fanout uses
    # ``send_nowait`` (full => close that socket only); history/reconciliation
    # uses a bounded ``await send`` with a timeout. The writer is the only
    # consumer, so cursor/frame ordering stays serialized.
    send_stream: MemoryObjectSendStream[Any] = field(init=False)
    recv_stream: MemoryObjectReceiveStream[Any] = field(init=False)
    sent_seq: int = 0
    acked_seq: int = 0
    replay_done: bool = False
    resync_pending: bool = False
    last_seen: float = field(default_factory=time.monotonic)
    closed: bool = False
    writer_task: asyncio.Task | None = None
    fill_task: asyncio.Task | None = None
    tokens: float = _FRAME_BUCKET_CAPACITY
    tokens_at: float = field(default_factory=time.monotonic)
    last_ping: float = 0.0
    delivery_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    close_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    close_code: int = 1000
    close_reason: str = ""

    def __post_init__(self) -> None:
        capacity = self.settings.ws_effective_queue_capacity
        self.send_stream, self.recv_stream = anyio.create_memory_object_stream(capacity)

    @property
    def member(self) -> str:
        return f"{id(self):x}:{self.conn_id}"


class Gateway:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._connections: dict[int, dict[str, Connection]] = {}
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._stream: RealtimeStream | None = None
        self._reader: StreamReader | None = None
        self._cursor = "$"
        self._stream_ok = False
        self._reconcile_ok = False
        self._started = False
        self._degraded_reason: str | None = None
        self._user_fill_tasks: dict[int, asyncio.Task] = {}
        self._reconcile_sem = asyncio.Semaphore(8)

    @property
    def ready(self) -> bool:
        return self._started and not self._stop.is_set() and self._reconcile_ok

    @property
    def degraded(self) -> bool:
        return not self._stream_ok or not self._reconcile_ok

    def status(self) -> dict:
        return {
            "connections": sum(len(items) for items in self._connections.values()),
            "users": len(self._connections),
            "stream_ok": self._stream_ok,
            "reconcile_ok": self._reconcile_ok,
            "degraded_reason": self._degraded_reason,
            "degraded": self.degraded,
            "ready": self.ready,
        }

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop.clear()
        if self.settings.redis_url.strip():
            self._stream = RealtimeStream(self.settings)
            self._reader = StreamReader(self.settings, self._stream.name)
        self._tasks = [
            asyncio.create_task(self._stream_loop(), name="realtime-stream"),
            asyncio.create_task(self._reconcile_loop(), name="realtime-reconcile"),
            asyncio.create_task(self._reaper_loop(), name="realtime-reaper"),
        ]

    async def stop(self, *, drain_seconds: int | None = None) -> None:
        self._stop.set()
        timeout = drain_seconds if drain_seconds is not None else max(1, self.settings.graceful_shutdown_seconds // 2)
        await self._drain(timeout)
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        if self._stream is not None:
            await self._stream.close()
            self._stream = None
        if self._reader is not None:
            await self._reader.close()
            self._reader = None
        self._started = False

    async def _drain(self, seconds: int) -> None:
        async with self._lock:
            connections = [conn for items in self._connections.values() for conn in items.values()]
        if not connections:
            return
        for conn in connections:
            await self._enqueue(conn, {"type": "drain", "retry_after_ms": 500})
        deadline = time.monotonic() + max(1, seconds)
        while time.monotonic() < deadline:
            async with self._lock:
                count = sum(len(items) for items in self._connections.values())
            if count == 0:
                break
            await asyncio.sleep(0.1)
        for conn in connections:
            await self._close(conn, 1001, "server draining")

    async def serve(self, ws: WebSocket, *, user_id: int, since: int, auth_expires_at: int,
                    ip: str | None, legacy: bool = False) -> None:
        if auth_expires_at and auth_expires_at < int(datetime.now(UTC).timestamp()):
            await _reject(ws, CLOSE_AUTH)
            return
        if not await self._admit_ip(ip):
            counters.incr("ws.rejected.handshake_rate")
            await _reject(ws, CLOSE_LIMIT)
            return
        initial = max(0, since)
        if legacy:
            # Capture before acknowledging the handshake: an old client may
            # send HTTP immediately after 101. Its first new message must not
            # be absorbed into a watermark captured after that message commits.
            async with get_sessionmaker()() as db:
                initial = await high_watermark(db, user_id)
        try:
            await ws.accept()
        except (WebSocketDisconnect, WebSocketDisconnected, OSError):
            return

        conn = Connection(ws=ws, user_id=user_id, since=initial, sent_seq=initial,
                          auth_expires_at=auth_expires_at, settings=self.settings, ip=ip,
                          legacy=legacy)
        if not await self._register(conn):
            counters.incr("ws.rejected.connection_limit")
            with contextlib.suppress(Exception):
                await ws.close(code=CLOSE_LIMIT, reason="connection limit")
            return
        conn.writer_task = asyncio.create_task(self._writer(conn), name=f"ws-writer-{conn.conn_id}")
        counters.incr("ws.connections.accepted")
        try:
            if conn.legacy:
                # Transitional old-client mode: no envelope/hello/ACK. Start at
                # the committed high watermark (old backend did not replay
                # history), then deliver new events as old payloads.
                conn.replay_done = True
            else:
                await self._enqueue(conn, {
                    "type": "hello",
                    "protocol_version": self.settings.realtime_protocol_version,
                    "user_id": user_id,
                    "heartbeat_seconds": self.settings.ws_heartbeat_seconds,
                    "reconcile_seconds": self.settings.ws_reconcile_seconds,
                    "degraded": self.degraded,
                })
                await self._catch_up(conn)
            await self._reader_loop(conn)
        finally:
            await self._close(conn, 1000, "closed")
            await self._unregister(conn)
            if conn.writer_task is not None:
                with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                    await asyncio.wait_for(conn.writer_task, timeout=self.settings.ws_send_timeout_seconds + 1)
            if conn.fill_task is not None:
                conn.fill_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await conn.fill_task

    async def _admit_ip(self, ip: str | None) -> bool:
        if not ip:
            return True
        try:
            key = f"ws:handshake:{ip}"
            count = await get_kv().incr_with_ttl(key, self.settings.ws_handshake_rate_window_seconds)
            return count <= self.settings.ws_handshake_rate_limit
        except KVError:
            # Security-related KV is fail-closed: without shared state we cannot
            # bound handshake floods, so the gateway refuses new connections.
            logger.warning("ws handshake rate unavailable; rejecting new connection")
            return False

    async def _register(self, conn: Connection) -> bool:
        async with self._lock:
            existing = self._connections.setdefault(conn.user_id, {})
            if len(existing) >= self.settings.ws_max_connections_per_user:
                if not existing:
                    self._connections.pop(conn.user_id, None)
                return False
            try:
                key = f"ws:conns:{conn.user_id}"
                count = await get_kv().register_connection(
                    key, conn.member,
                    ttl_seconds=max(self.settings.ws_heartbeat_timeout_seconds * 2, 60),
                    limit=self.settings.ws_max_connections_per_user,
                )
            except KVError:
                logger.warning("ws connection limit unavailable; rejecting new connection")
                if not existing:
                    self._connections.pop(conn.user_id, None)
                return False
            if count is None:
                if not existing:
                    self._connections.pop(conn.user_id, None)
                return False
            if conn.ip:
                try:
                    ip_count = await get_kv().register_connection(
                        f"ws:ips:{conn.ip}", conn.member,
                        ttl_seconds=max(self.settings.ws_heartbeat_timeout_seconds * 2, 60),
                        limit=self.settings.ws_max_connections_per_ip,
                    )
                except KVError:
                    ip_count = None
                if ip_count is None:
                    with contextlib.suppress(KVError):
                        await get_kv().unregister_connection(f"ws:conns:{conn.user_id}", conn.member)
                    if not existing:
                        self._connections.pop(conn.user_id, None)
                    return False
            existing[conn.conn_id] = conn
            return True

    async def _unregister(self, conn: Connection) -> None:
        async with self._lock:
            existing = self._connections.get(conn.user_id)
            if existing is not None:
                existing.pop(conn.conn_id, None)
                if not existing:
                    self._connections.pop(conn.user_id, None)
        with contextlib.suppress(KVError):
            await get_kv().unregister_connection(f"ws:conns:{conn.user_id}", conn.member)
            if conn.ip:
                await get_kv().unregister_connection(f"ws:ips:{conn.ip}", conn.member)

    async def _enqueue(self, conn: Connection, frame: dict, *, wait_for_space: bool = False) -> bool:
        if conn.closed:
            return False
        try:
            data = json.dumps(frame, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return False
        size = len(data.encode("utf-8"))
        if size > self.settings.ws_max_frame_bytes:
            await self._close(conn, CLOSE_TOO_LARGE, "frame too large")
            return False
        try:
            if wait_for_space:
                # History/reconciliation producers may wait for capacity, but
                # never past the send timeout. AnyIO owns the wake-up/cancel
                # semantics; no condition variable or byte bookkeeping here.
                with anyio.fail_after(self.settings.ws_send_timeout_seconds):
                    await conn.send_stream.send(data)
                return True
            # Live fanout must never wait for one slow socket: a full native
            # stream closes that connection so peers keep receiving.
            conn.send_stream.send_nowait(data)
            return True
        except anyio.WouldBlock:
            counters.incr("ws.closed.slow_consumer")
            await self._close(conn, CLOSE_OVERLOAD, "slow consumer")
            return False
        except TimeoutError:
            counters.incr("ws.closed.slow_consumer")
            await self._close(conn, CLOSE_OVERLOAD, "replay consumer timeout")
            return False
        except (anyio.ClosedResourceError, anyio.BrokenResourceError):
            return False

    async def _deliver_frame(self, conn: Connection, seq: int, frame: dict,
                             *, wait_for_space: bool = False) -> bool:
        """Serialize cursor check, enqueue and cursor advance for one connection."""
        async with conn.delivery_lock:
            if conn.closed:
                return False
            if conn.legacy:
                # A legacy connection starts at the committed high watermark.
                # A stream entry read after registration may still belong to
                # that already-covered history; do not replay it as "new".
                if seq <= conn.sent_seq:
                    return True
                payload = frame.get("payload", frame)
                # Legacy query-token mode has no per-device identity, so it
                # preserves the old single-device echo contract: advance the
                # contiguous cursor but do not enqueue the sender's own message.
                # Ticket/v2 clients still receive sender self-events for other
                # devices.
                if (isinstance(payload, dict) and payload.get("type") == "message"
                        and int(payload.get("sender_id") or 0) == conn.user_id):
                    conn.sent_seq = max(conn.sent_seq, seq)
                    return True
                if await self._enqueue(conn, payload, wait_for_space=wait_for_space):
                    conn.sent_seq = max(conn.sent_seq, seq)
                    return True
                return False
            if seq <= conn.sent_seq:
                return True
            if seq != conn.sent_seq + 1:
                return False
            if not await self._enqueue(conn, frame, wait_for_space=wait_for_space):
                return False
            conn.sent_seq = seq
            return True

    async def _deliver_event(self, conn: Connection, event, *, wait_for_space: bool = False) -> bool:
        wire = event_wire(event)
        return await self._deliver_frame(conn, int(event.user_seq), wire, wait_for_space=wait_for_space)

    async def _close(self, conn: Connection, code: int, reason: str) -> None:
        async with conn.close_lock:
            if conn.closed:
                return
            conn.closed = True
            conn.close_code = code
            conn.close_reason = reason[:120]
            # Close the receive side first: buffered frames are explicitly
            # discarded on close, and any producer blocked in ``await send`` is
            # woken with BrokenResourceError. There is no sentinel push and no
            # manual queue draining.
            with contextlib.suppress(anyio.ClosedResourceError, anyio.BrokenResourceError):
                await conn.recv_stream.aclose()
            with contextlib.suppress(anyio.ClosedResourceError, anyio.BrokenResourceError):
                await conn.send_stream.aclose()

    async def _writer(self, conn: Connection) -> None:
        # The writer exclusively owns the WebSocket close. Lifecycle close only
        # closes the streams; this task then flushes/terminates and closes once.
        try:
            async for item in conn.recv_stream:
                try:
                    await asyncio.wait_for(
                        conn.ws.send_text(item), timeout=self.settings.ws_send_timeout_seconds
                    )
                except (TimeoutError, WebSocketDisconnect, WebSocketDisconnected, OSError, RuntimeError):
                    counters.incr("ws.closed.send_timeout")
                    await self._close(conn, CLOSE_OVERLOAD, "send timeout")
                    break
        except (anyio.ClosedResourceError, anyio.BrokenResourceError, anyio.EndOfStream):
            pass
        finally:
            code = conn.close_code
            reason = conn.close_reason
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    conn.ws.close(code=code, reason=reason),
                    timeout=self.settings.ws_send_timeout_seconds,
                )

    async def _reader_loop(self, conn: Connection) -> None:
        while not conn.closed and not self._stop.is_set():
            try:
                message = await asyncio.wait_for(conn.ws.receive(), timeout=self.settings.ws_heartbeat_timeout_seconds)
            except TimeoutError:
                await self._close(conn, 1001, "heartbeat timeout")
                return
            except (WebSocketDisconnect, WebSocketDisconnected, OSError):
                return
            if message.get("type") == "websocket.disconnect":
                return
            conn.last_seen = time.monotonic()
            text = message.get("text")
            if text is None:
                await self._close(conn, CLOSE_POLICY, "binary frames unsupported")
                return
            if len(text.encode("utf-8")) > self.settings.ws_max_frame_bytes:
                await self._close(conn, CLOSE_TOO_LARGE, "frame too large")
                return
            if not self._take_token(conn):
                await self._close(conn, CLOSE_POLICY, "frame rate exceeded")
                return
            try:
                data = json.loads(text)
            except ValueError:
                await self._close(conn, CLOSE_POLICY, "invalid frame")
                return
            if not isinstance(data, dict):
                await self._close(conn, CLOSE_POLICY, "invalid frame")
                return
            kind = data.get("type")
            if kind in {"ping", "pong"}:
                if kind == "ping":
                    await self._enqueue(conn, {"type": "pong"})
            elif kind == "ack":
                self._ack(conn, data)
            else:
                await self._close(conn, CLOSE_POLICY, "unsupported frame")

    def _take_token(self, conn: Connection) -> bool:
        now = time.monotonic()
        conn.tokens = min(_FRAME_BUCKET_CAPACITY, conn.tokens + (now - conn.tokens_at) * _FRAME_BUCKET_RATE)
        conn.tokens_at = now
        if conn.tokens < 1:
            return False
        conn.tokens -= 1
        return True

    def _ack(self, conn: Connection, data: dict) -> None:
        try:
            seq = int(data.get("user_seq", 0))
        except (TypeError, ValueError):
            return
        if 0 < seq <= conn.sent_seq:
            conn.acked_seq = max(conn.acked_seq, seq)
            counters.incr("ws.ack")

    async def _catch_up(self, conn: Connection) -> None:
        try:
            async with get_sessionmaker()() as db:
                high = await high_watermark(db, conn.user_id)
                low = await low_watermark(db, conn.user_id)
            if conn.since > high:
                await self._resync(conn, low, high, "cursor_ahead")
                return
            if conn.since < low - 1:
                await self._resync(conn, low, high, "cursor_expired")
                return
            if high - conn.since > self.settings.realtime_replay_max_events:
                await self._resync(conn, low, high, "replay_too_large")
                return
            cursor = conn.since
            while cursor < high and not conn.closed:
                # Release the SQL lease before waiting for a client's outbound
                # queue. Long history/replay must not monopolize the DB pool.
                async with get_sessionmaker()() as db:
                    events = await replay_events(db, conn.user_id, after_seq=cursor, upto_seq=high,
                                                 limit=self.settings.realtime_replay_batch_size)
                if not events:
                    await self._resync(conn, low, high, "replay_gap")
                    return
                for event in events:
                    if event.user_seq <= conn.sent_seq:
                        cursor = max(cursor, int(event.user_seq))
                        continue
                    if not await self._deliver_event(conn, event, wait_for_space=True):
                        if not conn.closed:
                            await self._resync(conn, low, high, "replay_gap")
                        return
                    cursor = int(event.user_seq)
            if conn.closed:
                return
            if await self._enqueue(conn, {
                "type": "replay_complete", "user_seq": conn.sent_seq, "high_seq": high,
            }, wait_for_space=True):
                conn.replay_done = True
                self._reconcile_ok = True
        except Exception as exc:  # noqa: BLE001 - connection-local failure
            logger.warning("ws catch-up failed: %s", type(exc).__name__)
            counters.incr("ws.replay_errors")
            await self._close(conn, 1011, "replay unavailable")

    async def _resync(self, conn: Connection, low: int, high: int, reason: str) -> None:
        counters.incr("ws.resync_required")
        conn.resync_pending = True
        conn.replay_done = False
        await self._enqueue(conn, {
            "type": "resync_required",
            "reason": reason,
            "low_seq": low,
            "high_seq": high,
        })
        # Do not silently advance the cursor and do not keep polling/re-sending
        # old events: the client refreshes its authoritative snapshot and opens
        # a new ticket with since=high_seq.

    async def _head(self, user_id: int) -> tuple[int, int]:
        """Read high/low watermarks in one short, closed SQL session."""
        async with get_sessionmaker()() as db:
            return await high_watermark(db, user_id), await low_watermark(db, user_id)

    async def _page(self, user_id: int, cursor: int, high: int):
        """Read one replay page and close SQL before any socket wait."""
        async with get_sessionmaker()() as db:
            return list(await replay_events(
                db, user_id, after_seq=cursor, upto_seq=high,
                limit=self.settings.realtime_replay_batch_size,
            ))

    async def _fill(self, conn: Connection) -> None:
        if conn.resync_pending:
            return
        try:
            high, low = await self._head(conn.user_id)
            if not conn.legacy and conn.sent_seq < low - 1:
                await self._resync(conn, low, high, "cursor_expired")
                return
            cursor = conn.sent_seq
            delivered = 0
            while cursor < high and not conn.closed and delivered < self.settings.realtime_replay_max_events:
                events = await self._page(conn.user_id, cursor, high)
                if not events:
                    break
                for event in events:
                    if event.user_seq <= conn.sent_seq:
                        continue
                    if not await self._deliver_event(conn, event, wait_for_space=True):
                        return
                    cursor = int(event.user_seq)
                    delivered += 1
            self._reconcile_ok = True
            if self._stream_ok:
                self._degraded_reason = None
        except Exception as exc:  # noqa: BLE001
            self._reconcile_ok = False
            self._degraded_reason = type(exc).__name__
            counters.incr("ws.reconcile_errors")
            logger.warning("ws reconciliation failed: %s", type(exc).__name__)

    async def _fill_user(self, user_id: int, conns: list[Connection]) -> None:
        async with self._reconcile_sem:
            try:
                high, low = await self._head(user_id)
                active: list[Connection] = []
                for conn in conns:
                    if conn.legacy:
                        active.append(conn)
                    elif conn.sent_seq < low - 1:
                        await self._resync(conn, low, high, "cursor_expired")
                    else:
                        active.append(conn)
                if not active:
                    return
                cursor = min(conn.sent_seq for conn in active)
                delivered = 0
                while cursor < high and delivered < self.settings.realtime_replay_max_events:
                    events = await self._page(user_id, cursor, high)
                    if not events:
                        break
                    for event in events:
                        for conn in active:
                            if event.user_seq > conn.sent_seq:
                                await self._deliver_event(conn, event, wait_for_space=True)
                        cursor = int(event.user_seq)
                        delivered += 1
                self._reconcile_ok = True
            except Exception as exc:  # noqa: BLE001
                self._reconcile_ok = False
                self._degraded_reason = type(exc).__name__
                counters.incr("ws.reconcile_errors")
                logger.warning("ws user reconciliation failed: %s", type(exc).__name__)

    def _schedule_user_fill(self, user_id: int, conns: list[Connection]) -> None:
        if self._reconcile_sem.locked():
            return  # bounded recovery: leave the rest for the next reconcile tick
        task = self._user_fill_tasks.get(user_id)
        if task is not None and not task.done():
            return
        self._user_fill_tasks[user_id] = asyncio.create_task(
            self._fill_user(user_id, conns), name=f"ws-user-fill-{user_id}"
        )

    def _schedule_fill(self, conn: Connection) -> None:
        if conn.resync_pending or conn.closed or not conn.replay_done:
            return
        if conn.fill_task is not None and not conn.fill_task.done():
            return
        conn.fill_task = asyncio.create_task(self._fill(conn), name=f"ws-fill-{conn.conn_id}")

    async def _broadcast(self, frame: dict) -> None:
        try:
            user_id = int(frame["recipient_user_id"])
            seq = int(frame["user_seq"])
        except (KeyError, TypeError, ValueError):
            return
        async with self._lock:
            connections = list(self._connections.get(user_id, {}).values())
        for conn in connections:
            if conn.closed or not conn.replay_done:
                continue
            if conn.delivery_lock.locked():
                # History can be waiting for this connection's stream capacity.
                # Never make the shared Redis reader wait on that socket;
                # PostgreSQL fill owns recovery for this connection instead.
                self._schedule_fill(conn)
                continue
            delivered = await self._deliver_frame(conn, seq, frame)
            if not delivered and not conn.closed and not conn.legacy:
                # Parallel dispatchers may publish out of order or an entry may
                # be lost; always refill in user_seq order from PostgreSQL.
                self._schedule_fill(conn)

    async def _stream_loop(self) -> None:
        if self._reader is None:
            self._stream_ok = True  # memory/dev mode relies on reconciliation
            return
        while not self._stop.is_set():
            try:
                rows = await self._reader.read(self._cursor)
                self._stream_ok = True
                self._degraded_reason = None
                for entry_id, fields in rows:
                    self._cursor = entry_id
                    frame = decode_frame(fields)
                    if frame is not None:
                        await self._broadcast(frame)
            except StreamError as exc:
                self._stream_ok = False
                self._degraded_reason = exc.category
                counters.incr("ws.stream_errors")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=1.0)
                except TimeoutError:
                    pass
            except Exception as exc:  # noqa: BLE001
                self._stream_ok = False
                self._degraded_reason = type(exc).__name__
                logger.warning("ws stream loop failed: %s", type(exc).__name__)
                await asyncio.sleep(1)

    async def _reconcile_loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            for uid, task in list(self._user_fill_tasks.items()):
                if task.done():
                    self._user_fill_tasks.pop(uid, None)
            async with self._lock:
                grouped = {
                    uid: [conn for conn in items.values() if not conn.closed and conn.replay_done]
                    for uid, items in self._connections.items()
                }
            if not any(grouped.values()) and not self._reconcile_ok:
                try:
                    async with get_sessionmaker()() as db:
                        await db.exec(select(1))
                    self._reconcile_ok = True
                except Exception:  # noqa: BLE001
                    self._reconcile_ok = False
            for uid, conns in grouped.items():
                if conns:
                    self._schedule_user_fill(uid, conns)
            elapsed = time.monotonic() - started
            try:
                await asyncio.wait_for(self._stop.wait(),
                                       timeout=max(0.1, self.settings.ws_reconcile_seconds - elapsed))
            except TimeoutError:
                pass

    async def _reap_once(self) -> None:
        now = time.monotonic()
        async with self._lock:
            connections = [conn for items in self._connections.values() for conn in items.values()]
        wall = int(datetime.now(UTC).timestamp())
        for conn in connections:
            if conn.auth_expires_at and wall > conn.auth_expires_at:
                await self._close(conn, 4401, "authorization expired")
                continue
            if now - conn.last_seen > self.settings.ws_heartbeat_timeout_seconds:
                await self._close(conn, 1001, "heartbeat timeout")
                continue
            with contextlib.suppress(KVError):
                ttl = max(self.settings.ws_heartbeat_timeout_seconds * 2, 60)
                await get_kv().register_connection(
                    f"ws:conns:{conn.user_id}", conn.member,
                    ttl_seconds=ttl, limit=self.settings.ws_max_connections_per_user,
                )
                if conn.ip:
                    await get_kv().register_connection(
                        f"ws:ips:{conn.ip}", conn.member,
                        ttl_seconds=ttl, limit=self.settings.ws_max_connections_per_ip,
                    )
            if now - conn.last_ping >= self.settings.ws_heartbeat_seconds:
                conn.last_ping = now
                await self._enqueue(conn, {"type": "ping"})

    async def _reaper_loop(self) -> None:
        while not self._stop.is_set():
            await self._reap_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=5.0)
            except TimeoutError:
                pass

async def _reject(ws: WebSocket, code: int) -> None:
    """Complete the handshake so browsers see a business close code."""
    try:
        await ws.accept()
    except (WebSocketDisconnect, WebSocketDisconnected, OSError):
        return
    with contextlib.suppress(Exception):
        await ws.close(code=code)


_gateway: Gateway | None = None


def get_gateway() -> Gateway:
    global _gateway
    if _gateway is None:
        _gateway = Gateway()
    return _gateway


async def reset_gateway() -> None:
    global _gateway
    current = _gateway
    _gateway = None
    if current is not None:
        await current.stop(drain_seconds=1)
