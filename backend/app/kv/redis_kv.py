"""Redis KV 实现。"""

from app.kv.base import KeyValueStore


class RedisKV(KeyValueStore):
    def __init__(self, url: str, prefix: str = "") -> None:
        import redis.asyncio as aioredis

        self.prefix = prefix
        self._redis = aioredis.from_url(url, decode_responses=True)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self._redis.set(self.prefix + key, value, ex=ttl_seconds)

    async def get(self, key: str) -> str | None:
        value = await self._redis.get(self.prefix + key)
        return value.decode("utf-8") if isinstance(value, bytes) else value

    async def delete(self, key: str) -> None:
        await self._redis.delete(self.prefix + key)
