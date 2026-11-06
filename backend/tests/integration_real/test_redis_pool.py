"""Real Redis bounded-pool and cancellation semantics."""

from __future__ import annotations

import asyncio
import os

import pytest
from app.kv.redis_pool import ObservedBlockingConnectionPool
from app.observability import counters
from redis.exceptions import ConnectionError as RedisConnectionError


async def test_pool_full_waits_bounded_then_recovers_and_cancel_does_not_leak():
    pool = ObservedBlockingConnectionPool.from_url(
        os.environ["CI_REALTIME_REDIS_URL"],
        decode_responses=True,
        max_connections=1,
        timeout=0.25,
        metric_prefix="redis.pooltest",
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        first = await pool.get_connection()
        started = asyncio.get_running_loop().time()
        with pytest.raises(RedisConnectionError):
            await pool.get_connection()
        assert asyncio.get_running_loop().time() - started >= 0.15
        await pool.release(first)
        recovered = await pool.get_connection()
        await pool.release(recovered)

        held = await pool.get_connection()
        waiting = asyncio.create_task(pool.get_connection())
        await asyncio.sleep(0.05)
        waiting.cancel()
        with pytest.raises((asyncio.CancelledError, RedisConnectionError)):
            await waiting
        await pool.release(held)
        after_cancel = await pool.get_connection()
        await pool.release(after_cancel)
    finally:
        await pool.disconnect()
    snapshot = counters.snapshot()
    assert snapshot.get("redis.pooltest.acquire_exhausted", 0) >= 1
    assert snapshot.get("redis.pooltest.acquire_ms.count", 0) >= 1


async def test_blocking_xread_uses_a_separate_pool_from_control_commands():
    from app.core.config import get_settings
    from app.kv.base import get_kv
    from app.realtime.stream import RealtimeStream, StreamReader

    settings = get_settings()
    stream = RealtimeStream(settings)
    reader = StreamReader(settings, settings.redis_key_prefix + "pooltest:stream")
    try:
        task = asyncio.create_task(reader.read("$", count=1))
        await asyncio.sleep(0.05)
        # Control pool remains usable while the reader blocks on its own connection.
        await asyncio.wait_for(get_kv().ping(), timeout=1)
        await asyncio.wait_for(task, timeout=3)
    finally:
        await reader.close()
        await stream.close()
