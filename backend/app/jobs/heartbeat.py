"""Worker/scheduler heartbeat sinks.

Workers publish a SQL ``service_heartbeats`` row from Taskiq middleware and only
count as ready after a task actually succeeded. The scheduler has no SQL pool of
its own; it publishes a short-TTL Redis heartbeat updated by the schedule source
and by every successful dispatch. The combined/dev fallback uses SQL only when
Redis is absent.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import uuid
from datetime import UTC, datetime

from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from app.core.config import Settings
from app.db.session import get_sessionmaker
from app.models.realtime import ServiceHeartbeat
from app.realtime.heartbeat import beat

SCHEDULER_KEY_PREFIX = "jobs:scheduler:heartbeat:"


def scheduler_key(settings: Settings) -> str:
    return settings.redis_key_prefix + SCHEDULER_KEY_PREFIX + settings.release_id


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class SchedulerHeartbeat:
    """Scheduler-owned heartbeat without a SQL pool in split deployments."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.name = f"scheduler:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.started_at = datetime.now(UTC)
        self.dispatch_count = 0
        self.last_dispatch_at: datetime | None = None
        self.last_task: str | None = None
        self.schedule_count = 0
        self.schedule_ids: list[str] = []
        self.status = "starting"
        self._client = None
        self._lock = __import__("asyncio").Lock()

    def _redis(self):
        if self._client is None:
            import redis.asyncio as aioredis

            self._client = aioredis.Redis.from_url(
                self.settings.redis_url,
                decode_responses=True,
                max_connections=max(1, self.settings.taskiq_heartbeat_max_connections),
                socket_connect_timeout=self.settings.redis_connect_timeout_seconds,
                socket_timeout=self.settings.redis_socket_timeout_seconds,
                retry_on_timeout=False,
                retry=Retry(NoBackoff(), 0),
            )
        return self._client

    def details(self, *, status: str | None = None) -> dict:
        return {
            "role": "scheduler",
            "status": status or self.status,
            "release_id": self.settings.release_id,
            "protocol_version": self.settings.realtime_protocol_version,
            "pid": os.getpid(),
            "started_at": _iso(self.started_at),
            "heartbeat_at": _iso(datetime.now(UTC)),
            "dispatch_count": self.dispatch_count,
            "last_dispatch_at": _iso(self.last_dispatch_at),
            "last_task": self.last_task,
            "schedule_count": self.schedule_count,
            "schedule_ids": list(self.schedule_ids)[:32],
        }

    async def beat(self, *, status: str | None = None, schedule_count: int | None = None,
                   schedule_ids: list[str] | None = None) -> None:
        if status is not None:
            self.status = status
        if schedule_count is not None:
            self.schedule_count = schedule_count
        if schedule_ids is not None:
            self.schedule_ids = sorted(set(schedule_ids))
        details = self.details()
        # Schedule-source refresh and dispatch progress can race; one
        # heartbeat connection is enough and the write is serialized.
        async with self._lock:
            try:
                if self.settings.redis_url.strip():
                    await self._redis().set(
                        scheduler_key(self.settings),
                        json.dumps(details, ensure_ascii=False, separators=(",", ":")),
                        ex=max(30, self.settings.taskiq_scheduler_heartbeat_ttl_seconds),
                    )
                    return
                # Combined/dev without Redis: a SQL row is the only shared store.
                async with get_sessionmaker()() as db, db.begin():
                    await beat(db, self.settings, name=self.name, status=self.status,
                               details=details, started_at=self.started_at)
            except Exception as exc:  # noqa: BLE001 - heartbeat must not kill scheduling
                # Stable log category only; readiness will expose staleness.
                import logging

                logging.getLogger(__name__).warning("scheduler heartbeat write failed: %s", type(exc).__name__)

    async def dispatched(self, task_name: str) -> None:
        self.dispatch_count += 1
        self.last_dispatch_at = datetime.now(UTC)
        self.last_task = task_name
        await self.beat()

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            if self._client is not None:
                await self.beat(status="stopping")
        with contextlib.suppress(Exception):
            if self._client is not None:
                await self._client.aclose()
        self._client = None


async def read_scheduler_heartbeat(settings: Settings) -> dict | None:
    if not settings.redis_url.strip():
        return None
    import redis.asyncio as aioredis

    client = aioredis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=1,
        socket_connect_timeout=settings.redis_connect_timeout_seconds,
        socket_timeout=settings.redis_socket_timeout_seconds,
        retry_on_timeout=False,
        retry=Retry(NoBackoff(), 0),
    )
    try:
        raw = await client.get(scheduler_key(settings))
        return json.loads(raw) if raw else None
    except (RedisError, ValueError):
        return None
    finally:
        with contextlib.suppress(Exception):
            await client.aclose()


async def read_scheduler_heartbeat_sql(db, settings: Settings) -> dict | None:
    from sqlmodel import select

    row = (
        await db.exec(
            select(ServiceHeartbeat)
            .where(
                ServiceHeartbeat.name.startswith("scheduler:"),
                ServiceHeartbeat.release_id == settings.release_id,
                ServiceHeartbeat.status != "stopping",
            )
            .order_by(ServiceHeartbeat.heartbeat_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    details = dict(row.details or {})
    details.setdefault("status", row.status)
    details["heartbeat_at"] = _iso(row.heartbeat_at)
    details["release_id"] = row.release_id
    details["protocol_version"] = row.protocol_version
    details["pid"] = row.pid
    return details
