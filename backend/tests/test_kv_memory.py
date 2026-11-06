"""Offline KV semantics: fixed windows, one-time values, owner leases, limits.

MemoryKV is explicitly not production shared state; these tests only prove that
the fallback follows the same observable contract as the Redis implementation.
"""

import asyncio

from app.kv.base import MemoryKV


async def test_fixed_window_does_not_extend_existing_ttl():
    kv = MemoryKV()
    assert await kv.incr_with_ttl("window", 1) == 1
    first_expiry = kv._data["window"][1]
    await asyncio.sleep(0.2)
    assert await kv.incr_with_ttl("window", 1) == 2
    assert kv._data["window"][1] == first_expiry
    await asyncio.sleep(0.9)
    assert await kv.get("window") is None


async def test_consume_once_has_exactly_one_winner():
    kv = MemoryKV()
    await kv.set("ticket", "payload", 30)
    results = await asyncio.gather(kv.consume_once("ticket"), kv.consume_once("ticket"))
    assert sorted(value for value in results if value is not None) == ["payload"]


async def test_owner_token_lease_compare_and_release():
    kv = MemoryKV()
    assert await kv.acquire_lease("lease", "a", 30) is True
    assert await kv.acquire_lease("lease", "b", 30) is False
    assert await kv.release_lease("lease", "b") is False
    assert await kv.renew_lease("lease", "b", 30) is False
    assert await kv.renew_lease("lease", "a", 30) is True
    assert await kv.release_lease("lease", "a") is True


async def test_connection_limit_is_shared_and_released():
    kv = MemoryKV()
    assert await kv.register_connection("conns:1", "a", 30, 2) == 1
    assert await kv.register_connection("conns:1", "b", 30, 2) == 2
    assert await kv.register_connection("conns:1", "c", 30, 2) is None
    await kv.unregister_connection("conns:1", "a")
    assert await kv.register_connection("conns:1", "c", 30, 2) == 2


async def test_expired_connection_slots_are_reclaimed():
    kv = MemoryKV()
    assert await kv.register_connection("conns:2", "a", 1, 1) == 1
    await asyncio.sleep(1.1)
    assert await kv.register_connection("conns:2", "b", 30, 1) == 1
