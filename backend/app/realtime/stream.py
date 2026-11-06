"""Redis Streams as a short-lived delivery accelerator.

Every gateway owns its own cursor and performs XREAD on a dedicated blocking
connection. Gateways must NOT share a consumer group: a group would hand an
event to a gateway that has no local connection for the recipient. PostgreSQL
replay/reconciliation remains the correctness mechanism when Redis is lost,
trimmed or restarted.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from app.core.config import Settings
from app.kv.redis_pool import ObservedBlockingConnectionPool

logger = logging.getLogger(__name__)


class StreamError(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(f"realtime stream unavailable: {category}")
        self.category = category


def _category(exc: BaseException) -> str:
    name = type(exc).__name__.lower()
    if 'timeout' in name:
        return 'timeout'
    if 'connection' in name:
        return 'connection'
    return 'command'


class RealtimeStream:
    def __init__(self, settings: Settings) -> None:
        import redis.asyncio as aioredis

        self._settings = settings
        self._name = settings.redis_key_prefix + settings.realtime_stream_name
        self._pool = ObservedBlockingConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=settings.redis_publish_max_connections,
            client_name=f"{settings.redis_key_prefix}publish:{os.getpid()}",
            timeout=settings.redis_publish_pool_timeout_seconds,
            metric_prefix="redis.publish",
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
            retry_on_timeout=False,
            retry=Retry(NoBackoff(), 0),
        )
        self._client = aioredis.Redis(connection_pool=self._pool)

    @property
    def name(self) -> str:
        return self._name

    async def publish(self, frame: dict, *, event_id: str, user_id: int, user_seq: int) -> str:
        try:
            return await self._client.xadd(
                self._name,
                {
                    "event_id": event_id,
                    "user_id": str(user_id),
                    "user_seq": str(user_seq),
                    "frame": json.dumps(frame, ensure_ascii=False, separators=(",", ":")),
                },
                maxlen=self._settings.realtime_stream_maxlen,
                approximate=True,
            )
        except RedisError as exc:
            raise StreamError(_category(exc)) from None

    async def ping(self) -> None:
        try:
            await self._client.ping()
        except RedisError as exc:
            raise StreamError(_category(exc)) from None

    async def close(self) -> None:
        import contextlib

        with contextlib.suppress(Exception):
            await self._client.aclose()
        with contextlib.suppress(Exception):
            await self._pool.disconnect()


class StreamReader:
    """One dedicated blocking connection per WS process."""

    def __init__(self, settings: Settings, stream_name: str) -> None:
        import redis.asyncio as aioredis

        self._name = stream_name
        self._block_ms = settings.redis_stream_block_ms
        self._pool = ObservedBlockingConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=1,
            client_name=f"{settings.redis_key_prefix}ws-reader:{os.getpid()}",
            timeout=settings.redis_reader_pool_timeout_seconds,
            metric_prefix="redis.reader",
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            # XREAD BLOCK must finish before the socket read timeout.
            socket_timeout=settings.redis_stream_socket_timeout_seconds,
            retry_on_timeout=False,
            retry=Retry(NoBackoff(), 0),
        )
        self._client = aioredis.Redis(connection_pool=self._pool)

    async def read(self, cursor: str, *, count: int = 200) -> list[tuple[str, dict[str, str]]]:
        try:
            result = await self._client.xread(
                {self._name: cursor},
                count=max(1, count),
                block=self._block_ms,
            )
        except RedisError as exc:
            raise StreamError(_category(exc)) from None
        if not result:
            return []
        rows: list[tuple[str, dict[str, str]]] = []
        for _stream, entries in result:
            for entry_id, fields in entries:
                rows.append((entry_id, fields))
        return rows

    async def close(self) -> None:
        import contextlib

        with contextlib.suppress(Exception):
            await self._client.aclose()
        with contextlib.suppress(Exception):
            await self._pool.disconnect()


def decode_frame(fields: dict[str, Any]) -> dict | None:
    raw = fields.get("frame")
    if not isinstance(raw, str):
        return None
    try:
        frame = json.loads(raw)
    except ValueError:
        return None
    return frame if isinstance(frame, dict) else None


_stream_singleton: RealtimeStream | None = None
_stream_settings_token: tuple | None = None


def get_realtime_stream(settings: Settings) -> RealtimeStream:
    """Process-local publisher pool shared by Taskiq outbox tasks.

    Taskiq may run several async tasks concurrently in one process; creating a
    Redis pool per task would multiply the configured connection budget. The
    pool is created in the running event loop and closed by the jobs lifecycle.
    """
    global _stream_singleton, _stream_settings_token
    token = (settings.redis_url, settings.redis_key_prefix, settings.realtime_stream_name,
             settings.redis_publish_max_connections, settings.redis_publish_pool_timeout_seconds)
    if _stream_singleton is None or _stream_settings_token != token:
        _stream_singleton = RealtimeStream(settings)
        _stream_settings_token = token
    return _stream_singleton


async def close_realtime_stream() -> None:
    global _stream_singleton, _stream_settings_token
    current = _stream_singleton
    _stream_singleton = None
    _stream_settings_token = None
    if current is not None:
        await current.close()
