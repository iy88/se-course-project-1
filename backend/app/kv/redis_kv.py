"""Redis KV implementation with atomic fixed windows, GETDEL and owner leases.

All operations run on a bounded *control* pool. The blocking XREAD reader uses a
separate connection (see ``app.realtime.stream``) so long polls cannot starve
verification, ticket or rate-limit commands. Errors are re-raised as a stable
category without keys, values or connection strings.
"""

from __future__ import annotations

from typing import Any

from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from app.kv.base import KeyValueStore, KVError
from app.kv.redis_pool import ObservedBlockingConnectionPool

_INCR_TTL = """
local value = redis.call('INCR', KEYS[1])
if value == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
return value
"""

_CONSUME_ONCE = """
local value = redis.call('GET', KEYS[1])
if value then
  redis.call('DEL', KEYS[1])
end
return value
"""

_ACQUIRE = """
if redis.call('SET', KEYS[1], ARGV[1], 'NX', 'PX', ARGV[2]) then
  return 1
end
return 0
"""

_RENEW = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

_REGISTER_CONNECTION = """
local now = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
local count = redis.call('ZCARD', KEYS[1])
if count >= tonumber(ARGV[4]) then
  return -1
end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[3]), ARGV[1])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[3]) * 1000)
return count + 1
"""

_UNREGISTER_CONNECTION = """
redis.call('ZREM', KEYS[1], ARGV[1])
return 1
"""


def _category(exc: BaseException) -> str:
    name = type(exc).__name__.lower()
    if 'timeout' in name:
        return 'timeout'
    if 'connection' in name:
        return 'connection'
    if 'authentication' in name or 'permission' in name or 'noauth' in name:
        return 'auth'
    if 'response' in name or 'script' in name:
        return 'command'
    return 'redis'


class RedisKV(KeyValueStore):
    def __init__(self, url: str, prefix: str = "", *, max_connections: int = 16,
                 connect_timeout: float = 1.0, socket_timeout: float = 2.0,
                 pool_timeout: float = 1.0) -> None:
        import redis.asyncio as aioredis

        self.prefix = prefix
        self._pool = ObservedBlockingConnectionPool.from_url(
            url,
            decode_responses=True,
            max_connections=max_connections,
            timeout=pool_timeout,
            metric_prefix="redis.control",
            socket_connect_timeout=connect_timeout,
            socket_timeout=socket_timeout,
            health_check_interval=30,
            retry_on_timeout=False,
            retry=Retry(NoBackoff(), 0),
        )
        self._redis = aioredis.Redis(connection_pool=self._pool)
        self._incr = self._redis.register_script(_INCR_TTL)
        self._consume = self._redis.register_script(_CONSUME_ONCE)
        self._acquire = self._redis.register_script(_ACQUIRE)
        self._renew = self._redis.register_script(_RENEW)
        self._release = self._redis.register_script(_RELEASE)
        self._register_connection = self._redis.register_script(_REGISTER_CONNECTION)
        self._unregister_connection = self._redis.register_script(_UNREGISTER_CONNECTION)

    def _key(self, key: str) -> str:
        return self.prefix + key

    async def _run(self, awaitable: Any) -> Any:
        try:
            return await awaitable
        except RedisError as exc:
            raise KVError(_category(exc)) from None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._run(self._redis.set(self._key(key), value, ex=ttl_seconds))

    async def get(self, key: str) -> str | None:
        return await self._run(self._redis.get(self._key(key)))

    async def delete(self, key: str) -> None:
        await self._run(self._redis.delete(self._key(key)))

    async def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        result = await self._run(self._incr(keys=[self._key(key)], args=[max(1, ttl_seconds) * 1000]))
        return int(result)

    async def consume_once(self, key: str) -> str | None:
        return await self._run(self._consume(keys=[self._key(key)]))

    async def acquire_lease(self, key: str, owner: str, ttl_seconds: int) -> bool:
        result = await self._run(self._acquire(keys=[self._key(key)], args=[owner, max(1, ttl_seconds) * 1000]))
        return bool(int(result))

    async def renew_lease(self, key: str, owner: str, ttl_seconds: int) -> bool:
        result = await self._run(self._renew(keys=[self._key(key)], args=[owner, max(1, ttl_seconds) * 1000]))
        return bool(int(result))

    async def release_lease(self, key: str, owner: str) -> bool:
        result = await self._run(self._release(keys=[self._key(key)], args=[owner]))
        return bool(int(result))

    async def register_connection(self, key: str, member: str, ttl_seconds: int, limit: int) -> int | None:
        import time

        result = await self._run(self._register_connection(
            keys=[self._key(key)],
            args=[member, int(time.time()), max(1, ttl_seconds), max(1, limit)],
        ))
        value = int(result)
        return None if value < 0 else value

    async def unregister_connection(self, key: str, member: str) -> None:
        await self._run(self._unregister_connection(keys=[self._key(key)], args=[member]))

    async def ping(self) -> None:
        await self._run(self._redis.ping())

    async def close(self) -> None:
        import contextlib

        with contextlib.suppress(Exception):
            await self._redis.aclose()
        with contextlib.suppress(Exception):
            await self._pool.disconnect()
