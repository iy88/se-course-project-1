"""History bursts need producer backpressure; live slow sockets stay isolated."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

from app.core.config import get_settings
from app.realtime import gateway as module


class Socket:
    def __init__(self):
        self.sequences = []
        self.complete = asyncio.Event()

    async def send_text(self, data):
        # 1,000 frames/s is a healthy receiver; a server-side history burst must
        # not classify it as slow merely because one SQL page exceeds the queue.
        await asyncio.sleep(0.001)
        frame = json.loads(data)
        if frame["type"] == "event":
            self.sequences.append(frame["user_seq"])
        elif frame["type"] == "replay_complete":
            self.complete.set()

    async def close(self, **_kwargs):
        pass


def settings():
    return get_settings().model_copy(update={
        "ws_queue_max_messages": 4, "ws_queue_max_bytes": 256 * 4,
        "ws_max_frame_bytes": 256, "realtime_replay_batch_size": 20,
        "ws_send_timeout_seconds": 0.5,
    })


async def test_history_page_larger_than_queue_reaches_healthy_receiver(monkeypatch):
    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

    async def high(*_args):
        return 20

    async def low(*_args):
        return 1

    async def replay(_db, _user, *, after_seq, **_kwargs):
        return [SimpleNamespace(
            event_id=f"event-{seq}", recipient_user_id=1, user_seq=seq,
            event_type="probe", entity_type=None, entity_id=None, version=1,
            payload={}, created_at=datetime.now(UTC),
        ) for seq in range(after_seq + 1, 21)]

    monkeypatch.setattr(module, "get_sessionmaker", lambda: Session)
    monkeypatch.setattr(module, "high_watermark", high)
    monkeypatch.setattr(module, "low_watermark", low)
    monkeypatch.setattr(module, "replay_events", replay)
    config = settings()
    gateway = module.Gateway(config)
    socket = Socket()
    conn = module.Connection(ws=socket, user_id=1, since=0, auth_expires_at=0, settings=config)
    writer = asyncio.create_task(gateway._writer(conn))
    try:
        await gateway._catch_up(conn)
        await asyncio.wait_for(socket.complete.wait(), timeout=1)
        assert not conn.closed
        assert socket.sequences == list(range(1, 21))
    finally:
        await gateway._close(conn, 1000, "test complete")
        await asyncio.wait_for(writer, timeout=1)


async def test_live_delivery_does_not_wait_for_a_full_consumer_queue():
    config = settings()
    gateway = module.Gateway(config)
    conn = module.Connection(ws=Socket(), user_id=1, since=0, auth_expires_at=0, settings=config)
    for _ in range(config.ws_queue_max_messages):
        assert await gateway._enqueue(conn, {"type": "ping"})
    assert not await asyncio.wait_for(gateway._enqueue(conn, {"type": "ping"}), timeout=0.1)
    assert conn.closed
