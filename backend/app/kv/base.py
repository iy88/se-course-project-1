"""短时 KV 抽象：验证码、频控计数、一次性 ticket 与 owner-token lease。

生产/多进程只允许 Redis。``MemoryKV`` 只用于离线单进程开发与测试；它实现与
Redis 相同的方法语义，但明确不提供跨进程共享状态。
"""

from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod


class KVError(RuntimeError):
    """Stable, redacted KV failure category (never contains keys or values)."""

    def __init__(self, category: str) -> None:
        super().__init__(f"kv unavailable: {category}")
        self.category = category


class KeyValueStore(ABC):
    @abstractmethod
    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    async def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        """Fixed-window counter: TTL is set only when the key is first created."""
        current = await self.get(key)
        value = int(current) + 1 if current else 1
        # TTL must not be refreshed on subsequent hits; this default path is
        # only safe for the single-process MemoryKV which overrides it atomically.
        await self.set(key, str(value), ttl_seconds)
        return value

    async def consume_once(self, key: str) -> str | None:
        """Atomically read and delete a one-time value (ticket)."""
        value = await self.get(key)
        if value is not None:
            await self.delete(key)
        return value

    async def acquire_lease(self, key: str, owner: str, ttl_seconds: int) -> bool:
        """Acquire an owner-token lease; only the owner may release it."""
        if await self.get(key) is not None:
            return False
        await self.set(key, owner, ttl_seconds)
        return True

    async def renew_lease(self, key: str, owner: str, ttl_seconds: int) -> bool:
        if await self.get(key) != owner:
            return False
        await self.set(key, owner, ttl_seconds)
        return True

    async def release_lease(self, key: str, owner: str) -> bool:
        """Compare-and-delete: never delete another owner's lease."""
        if await self.get(key) != owner:
            return False
        await self.delete(key)
        return True

    async def register_connection(self, key: str, member: str, ttl_seconds: int, limit: int) -> int | None:
        """Cross-process connection slot; returns count or None when over limit."""
        return 1

    async def unregister_connection(self, key: str, member: str) -> None:
        return None

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


class MemoryKV(KeyValueStore):
    """Offline single-process store with the same observable semantics."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _expired(expire_at: float | None) -> bool:
        return expire_at is not None and expire_at <= time.time()

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        async with self._lock:
            self._data[key] = (value, time.time() + ttl_seconds if ttl_seconds > 0 else None)

    async def get(self, key: str) -> str | None:
        async with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            value, expire_at = item
            if self._expired(expire_at):
                self._data.pop(key, None)
                return None
            return value

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        async with self._lock:
            item = self._data.get(key)
            if item is None or self._expired(item[1]):
                value = 1
                expire_at = time.time() + ttl_seconds if ttl_seconds > 0 else None
            else:
                value = int(item[0]) + 1
                expire_at = item[1]
            self._data[key] = (str(value), expire_at)
            return value

    async def consume_once(self, key: str) -> str | None:
        async with self._lock:
            item = self._data.pop(key, None)
            if item is None or self._expired(item[1]):
                return None
            return item[0]

    async def acquire_lease(self, key: str, owner: str, ttl_seconds: int) -> bool:
        async with self._lock:
            item = self._data.get(key)
            if item is not None and not self._expired(item[1]):
                return False
            self._data[key] = (owner, time.time() + ttl_seconds)
            return True

    async def renew_lease(self, key: str, owner: str, ttl_seconds: int) -> bool:
        async with self._lock:
            item = self._data.get(key)
            if item is None or self._expired(item[1]) or item[0] != owner:
                return False
            self._data[key] = (owner, time.time() + ttl_seconds)
            return True

    async def release_lease(self, key: str, owner: str) -> bool:
        async with self._lock:
            item = self._data.get(key)
            if item is None or self._expired(item[1]) or item[0] != owner:
                return False
            self._data.pop(key, None)
            return True

    async def register_connection(self, key: str, member: str, ttl_seconds: int, limit: int) -> int | None:
        async with self._lock:
            now = time.time()
            entry = self._data.get(key)
            active: dict[str, float] = {}
            if entry is not None and not self._expired(entry[1]):
                try:
                    raw = json.loads(entry[0])
                    active = {str(k): float(v) for k, v in raw.items() if float(v) > now}
                except (TypeError, ValueError):
                    active = {}
            active.pop(member, None)
            if len(active) >= limit:
                return None
            active[member] = now + ttl_seconds
            self._data[key] = (json.dumps(active), now + ttl_seconds)
            return len(active)

    async def unregister_connection(self, key: str, member: str) -> None:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return
            try:
                active = {str(k): float(v) for k, v in json.loads(entry[0]).items()}
            except (TypeError, ValueError):
                active = {}
            active.pop(member, None)
            if active:
                self._data[key] = (json.dumps(active), max(active.values()))
            else:
                self._data.pop(key, None)


_kv: KeyValueStore | None = None


def get_kv() -> KeyValueStore:
    global _kv
    if _kv is None:
        from app.core.config import get_settings

        settings = get_settings()
        if settings.kv_backend == "redis":
            from app.kv.redis_kv import RedisKV

            _kv = RedisKV(
                settings.redis_url,
                settings.redis_key_prefix,
                max_connections=settings.redis_control_limit,
                connect_timeout=settings.redis_connect_timeout_seconds,
                socket_timeout=settings.redis_socket_timeout_seconds,
                pool_timeout=settings.redis_control_pool_timeout_seconds,
            )
            return _kv
        _kv = MemoryKV()
    return _kv


async def reset_kv() -> None:
    """Close and forget the process-local KV handle without flushing Redis."""
    global _kv
    current = _kv
    _kv = None
    if current is not None:
        import contextlib

        with contextlib.suppress(Exception):
            await current.close()


def set_kv_for_tests(store: KeyValueStore | None) -> None:
    """Inject an isolated store in tests; never touches shared Redis state."""
    global _kv
    _kv = store
