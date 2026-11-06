"""Offline gateway backpressure/control-frame tests (no real socket)."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import anyio
from app.core.config import get_settings
from app.realtime.events import event_wire
from app.realtime.gateway import Connection, Gateway


class DummyWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = None

    async def send_text(self, value: str) -> None:
        self.sent.append(value)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = (code, reason)


def config(**updates):
    base = {
        "ws_max_frame_bytes": 256,
        "ws_queue_max_bytes": 256 * 8,
        "ws_queue_max_messages": 8,
        "ws_send_timeout_seconds": 0.2,
    }
    base.update(updates)
    return get_settings().model_copy(update=base)


def connection(settings, ws=None) -> Connection:
    return Connection(
        ws=ws or DummyWebSocket(),
        user_id=1,
        since=0,
        auth_expires_at=int(datetime.now(UTC).timestamp()) + 60,
        settings=settings,
    )


def receive(conn: Connection) -> dict:
    return json.loads(conn.recv_stream.receive_nowait())


async def test_message_count_bound_closes_slow_consumer():
    settings = config(ws_queue_max_messages=2, ws_queue_max_bytes=256 * 4)
    gateway = Gateway(settings)
    conn = connection(settings)
    assert await gateway._enqueue(conn, {"type": "event", "n": 1}) is True
    assert await gateway._enqueue(conn, {"type": "event", "n": 2}) is True
    assert await gateway._enqueue(conn, {"type": "event", "n": 3}) is False
    assert conn.closed is True
    assert conn.close_code == 1013


async def test_history_delivery_lock_does_not_stall_live_peer_or_stream_reader(monkeypatch):
    settings = config()
    gateway = Gateway(settings)
    slow, healthy = connection(settings), connection(settings)
    slow.replay_done = healthy.replay_done = True
    gateway._connections[1] = {slow.conn_id: slow, healthy.conn_id: healthy}
    recovery = []
    monkeypatch.setattr(gateway, "_schedule_fill", recovery.append)
    await slow.delivery_lock.acquire()
    try:
        await asyncio.wait_for(gateway._broadcast({
            "type": "event", "recipient_user_id": 1, "user_seq": 1,
            "event_id": "first", "payload": {"type": "notification"},
        }), timeout=0.1)
        assert receive(healthy)["event_id"] == "first"
        assert recovery == [slow]
        assert not healthy.closed
    finally:
        slow.delivery_lock.release()


async def test_byte_bound_and_oversized_frame_close_connection():
    settings = config(ws_queue_max_messages=100, ws_queue_max_bytes=256 * 2,
                      ws_max_frame_bytes=256)
    gateway = Gateway(settings)
    conn = connection(settings)
    assert await gateway._enqueue(conn, {"type": "event", "text": "x" * 30}) is True
    assert await gateway._enqueue(conn, {"type": "event", "text": "y" * 30}) is True
    assert await gateway._enqueue(conn, {"type": "event", "text": "z" * 30}) is False
    assert conn.close_code == 1013
    conn2 = connection(settings)
    assert await gateway._enqueue(conn2, {"type": "event", "text": "z" * 600}) is False
    assert conn2.close_code == 1009


def test_effective_capacity_is_conservative_and_never_exceeds_byte_budget():
    by_messages = config(ws_queue_max_messages=2, ws_queue_max_bytes=256 * 8)
    assert by_messages.ws_effective_queue_capacity == 2
    by_bytes = config(ws_queue_max_messages=128, ws_queue_max_bytes=256 * 3)
    assert by_bytes.ws_effective_queue_capacity == 3
    # The settings contract rejects a byte budget that cannot hold one frame.
    import pytest
    from app.core.config import ConfigurationError

    with pytest.raises(ConfigurationError, match="WS_QUEUE_MAX_BYTES"):
        config(ws_queue_max_bytes=128, ws_max_frame_bytes=256).validate_for_runtime()


async def test_close_wakes_blocked_history_sender_without_waiting_for_timeout():
    settings = config(ws_queue_max_messages=1, ws_queue_max_bytes=256 * 2,
                      ws_send_timeout_seconds=5.0)
    gateway = Gateway(settings)
    conn = connection(settings)
    assert await gateway._enqueue(conn, {"type": "ping"})
    blocked = asyncio.create_task(gateway._enqueue(conn, {"type": "event", "n": 2},
                                                   wait_for_space=True))
    await asyncio.sleep(0.05)
    assert not blocked.done()
    await gateway._close(conn, 1013, "closed during history")
    assert await asyncio.wait_for(blocked, timeout=0.5) is False
    assert conn.closed


async def test_cancelled_history_sender_releases_without_corrupting_stream():
    settings = config(ws_queue_max_messages=1, ws_queue_max_bytes=256 * 2,
                      ws_send_timeout_seconds=5.0)
    gateway = Gateway(settings)
    conn = connection(settings)
    assert await gateway._enqueue(conn, {"type": "ping"})
    blocked = asyncio.create_task(gateway._enqueue(conn, {"type": "event", "n": 2},
                                                   wait_for_space=True))
    await asyncio.sleep(0.05)
    blocked.cancel()
    with anyio.CancelScope() as scope:  # pragma: no cover - cancellation is deterministic
        scope.cancel()
        try:
            await blocked
        except asyncio.CancelledError:
            pass
    assert not conn.closed
    assert receive(conn) == {"type": "ping"}


async def test_writer_drains_stream_and_closes_websocket_exactly_once():
    settings = config()
    gateway = Gateway(settings)
    socket = DummyWebSocket()
    conn = connection(settings, socket)
    writer = asyncio.create_task(gateway._writer(conn))
    assert await gateway._enqueue(conn, {"type": "event", "n": 1})
    await asyncio.sleep(0.05)
    await gateway._close(conn, 1000, "test")
    await asyncio.wait_for(writer, timeout=1)
    assert json.loads(socket.sent[0])["n"] == 1
    assert socket.closed == (1000, "test")


async def test_wire_contract_has_order_and_legacy_payload():
    event = SimpleNamespace(
        event_id="e-1",
        recipient_user_id=7,
        user_seq=3,
        event_type="im.message",
        entity_type="conversation",
        entity_id="5",
        version=1,
        payload={"type": "message", "message_id": 9},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    frame = event_wire(event)  # type: ignore[arg-type]
    assert frame["type"] == "event"
    assert frame["user_seq"] == 3
    assert frame["recipient_user_id"] == 7
    assert frame["payload"]["type"] == "message"


def test_access_log_filter_redacts_ticket_and_token():
    import logging

    from app.observability import RedactSecretsFilter

    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", "/ws?ticket=secret-value&x=1", "1.1", 101),
        None,
    )
    RedactSecretsFilter().filter(record)
    assert "secret-value" not in str(record.args)
    assert "ticket=[redacted]" in str(record.args)

    legacy = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1,
                               'GET /ws?token=legacy-secret HTTP/1.1', (), None)
    RedactSecretsFilter().filter(legacy)
    assert "legacy-secret" not in legacy.msg


async def test_legacy_connection_receives_old_payload_without_envelope():
    settings = config(ws_queue_max_messages=4)
    gateway = Gateway(settings)
    conn = connection(settings)
    conn.legacy = True
    conn.replay_done = True
    gateway._connections[1] = {conn.conn_id: conn}
    await gateway._broadcast({
        "type": "event",
        "recipient_user_id": 1,
        "user_seq": 7,
        "event_id": "e-7",
        "payload": {"type": "message", "message_id": 3, "content": "old"},
    })
    frame = receive(conn)
    assert frame["type"] == "message"
    assert frame["message_id"] == 3
    assert conn.sent_seq == 7


async def test_legacy_connection_does_not_replay_pre_watermark_stream_entries():
    settings = config()
    gateway = Gateway(settings)
    conn = connection(settings)
    conn.legacy = True
    conn.replay_done = True
    conn.sent_seq = 7
    old = {"type": "event", "recipient_user_id": 1, "user_seq": 6, "event_id": "e-6",
           "payload": {"type": "message", "message_id": 6}}
    assert await gateway._deliver_frame(conn, 6, old) is True
    import pytest
    with pytest.raises(anyio.WouldBlock):
        conn.recv_stream.receive_nowait()
    new = {"type": "event", "recipient_user_id": 1, "user_seq": 8, "event_id": "e-8",
           "payload": {"type": "message", "message_id": 8}}
    assert await gateway._deliver_frame(conn, 8, new) is True
    assert receive(conn)["message_id"] == 8
    assert conn.sent_seq == 8


async def test_delivery_serialization_never_regresses_or_skips_gap():
    settings = config()
    gateway = Gateway(settings)
    conn = connection(settings)
    conn.replay_done = True
    frame1 = {"type": "event", "recipient_user_id": 1, "user_seq": 1, "event_id": "e-1", "payload": {"type": "message"}}
    frame2 = {"type": "event", "recipient_user_id": 1, "user_seq": 2, "event_id": "e-2", "payload": {"type": "message"}}
    assert await gateway._deliver_frame(conn, 2, frame2) is False  # gap: no skip
    assert conn.sent_seq == 0
    assert await gateway._deliver_frame(conn, 1, frame1) is True
    assert await gateway._deliver_frame(conn, 2, frame2) is True
    assert conn.sent_seq == 2
    assert receive(conn)["user_seq"] == 1
    assert receive(conn)["user_seq"] == 2


async def test_resync_does_not_replay_or_repeat_until_client_reconnects():
    settings = config()
    gateway = Gateway(settings)
    conn = connection(settings)
    conn.replay_done = True
    await gateway._resync(conn, 5, 9, "cursor_expired")
    assert conn.resync_pending is True
    assert conn.replay_done is False
    assert receive(conn)["type"] == "resync_required"
    await gateway._fill(conn)  # must not query/replay while resync is pending
    import pytest

    with pytest.raises(anyio.WouldBlock):
        conn.recv_stream.receive_nowait()


async def test_outbox_failure_write_does_not_kill_dispatcher(monkeypatch):
    from app.realtime.dispatcher import ClaimedEvent, OutboxService

    settings = get_settings()
    dispatcher = OutboxService(settings)
    events = [ClaimedEvent("e-1", 1, 1, {"type": "event"}, 1)]

    async def broken(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(dispatcher, "_fail_tx", broken)
    retryable = await dispatcher._fail(events, "timeout")  # must absorb the write failure
    assert dispatcher._last_error == "RuntimeError"
    assert retryable == events


async def test_reaper_closes_expired_authorization():
    from datetime import timedelta

    settings = config()
    gateway = Gateway(settings)
    conn = connection(settings)
    conn.auth_expires_at = int((datetime.now(UTC) - timedelta(seconds=1)).timestamp())
    gateway._connections[1] = {conn.conn_id: conn}
    await gateway._reap_once()
    assert conn.closed is True
    assert conn.close_code == 4401


async def test_legacy_mode_does_not_echo_own_message_but_ticket_mode_does():
    settings = config()
    gateway = Gateway(settings)
    legacy = connection(settings)
    legacy.legacy = True
    legacy.replay_done = True
    frame = {"type": "event", "recipient_user_id": 1, "user_seq": 1, "event_id": "e-1",
             "created_at": datetime.now(UTC).isoformat(),
             "payload": {"type": "message", "message_id": 1, "sender_id": 1}}
    assert await gateway._deliver_frame(legacy, 1, frame) is True
    assert legacy.sent_seq == 1
    import pytest
    with pytest.raises(anyio.WouldBlock):
        legacy.recv_stream.receive_nowait()
    other = {"type": "event", "recipient_user_id": 1, "user_seq": 2, "event_id": "e-2",
             "created_at": datetime.now(UTC).isoformat(),
             "payload": {"type": "message", "message_id": 2, "sender_id": 2}}
    assert await gateway._deliver_frame(legacy, 2, other) is True
    assert receive(legacy)["message_id"] == 2
    assert legacy.sent_seq == 2

    modern = connection(settings)
    modern.replay_done = True
    assert await gateway._deliver_frame(modern, 1, frame) is True
    assert receive(modern)["payload"]["sender_id"] == 1


async def test_fill_and_user_fill_release_sql_before_blocking_socket_send(monkeypatch):
    """A slow history sender must never hold a SQL session/lease."""
    from types import SimpleNamespace

    from app.realtime import gateway as module

    sessions = []

    class Session:
        def __init__(self):
            self.closed = False
            sessions.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            self.closed = True

    async def high(_db, _user):
        return 2

    async def low(_db, _user):
        return 1

    async def replay(_db, _user, *, after_seq, **_kwargs):
        return [SimpleNamespace(user_seq=1), SimpleNamespace(user_seq=2)]

    delivered = []

    async def deliver(_self, conn, event, **_kwargs):
        assert sessions and all(session.closed for session in sessions)
        delivered.append(event.user_seq)
        conn.sent_seq = event.user_seq
        return True

    monkeypatch.setattr(module, "get_sessionmaker", lambda: Session)
    monkeypatch.setattr(module, "high_watermark", high)
    monkeypatch.setattr(module, "low_watermark", low)
    monkeypatch.setattr(module, "replay_events", replay)
    monkeypatch.setattr(module.Gateway, "_deliver_event", deliver)

    settings = config()
    gateway = module.Gateway(settings)
    conn = connection(settings)
    conn.replay_done = True
    await gateway._fill(conn)
    assert delivered == [1, 2]

    delivered.clear()
    conn2 = connection(settings)
    conn2.replay_done = True
    await gateway._fill_user(1, [conn2])
    assert delivered == [1, 2]
    assert all(session.closed for session in sessions)
