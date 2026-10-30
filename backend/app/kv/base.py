"""短时 KV 抽象：验证码、频控计数等。

配置 REDIS_URL 时使用 Redis 实现；否则进程内字典兜底（TTL 靠惰性清理）。
"""

import time
from abc import ABC, abstractmethod


class KeyValueStore(ABC):
    @abstractmethod
    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    async def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        """计数并返回自增后的值（频控用）。"""
        current = await self.get(key)
        value = int(current) + 1 if current else 1
        await self.set(key, str(value), ttl_seconds)
        return value


class MemoryKV(KeyValueStore):
    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}

    def _expired(self, expire_at: float) -> bool:
        return expire_at < time.time()

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._data[key] = (value, time.time() + ttl_seconds)

    async def get(self, key: str) -> str | None:
        item = self._data.get(key)
        if not item:
            return None
        value, expire_at = item
        if self._expired(expire_at):
            self._data.pop(key, None)
            return None
        return value

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


_kv: KeyValueStore | None = None


def get_kv() -> KeyValueStore:
    global _kv
    if _kv is None:
        from app.core.config import get_settings

        settings = get_settings()
        if settings.kv_backend == "redis":
            from app.kv.redis_kv import RedisKV

            _kv = RedisKV(settings.redis_url, settings.redis_key_prefix)
            return _kv
        _kv = MemoryKV()
    return _kv
