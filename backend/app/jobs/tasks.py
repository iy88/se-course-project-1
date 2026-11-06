"""Bounded Taskiq tasks and their official schedules.

Every task has a versioned name and accepts only small control values (no JWT,
message body, signed URL or secret). Taskiq's JSON serializer is the broker
default, so no executable pickle context is introduced.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from taskiq.abc.broker import AsyncBroker

from app.core.config import Settings, get_settings
from app.jobs.broker import get_default_bundle
from app.jobs.errors import RetryableJobError
from app.jobs.state import get_outbox_service
from app.realtime.dispatcher import OutboxPublishError

T = TypeVar("T")

OUTBOX_TASK = "project1.jobs.outbox_dispatch.v1"
TIMEOUT_TASK = "project1.jobs.timeout_scan.v1"
RETENTION_TASK = "project1.jobs.retention.v1"
IDEMPOTENCY_TASK = "project1.jobs.idempotency_cleanup.v1"
PROBE_TASK = "project1.jobs.probe.v1"
TASK_PROTOCOL_VERSION = 1


async def _bounded(settings: Settings, call: Callable[[], Awaitable[T]]) -> T:
    """Apply the configured per-task timeout and stable retryable categories."""
    try:
        async with asyncio.timeout(settings.taskiq_task_timeout_seconds):
            return await call()
    except TimeoutError:
        raise RetryableJobError("timeout") from None
    except RetryableJobError:
        raise
    except OutboxPublishError as exc:
        raise RetryableJobError(exc.category) from None
    except (SQLAlchemyError, RedisError, OSError, ConnectionError) as exc:
        raise RetryableJobError(type(exc).__name__) from None


async def _write_probe_result(settings: Settings, token: str, *, status: str,
                              category: str | None = None) -> None:
    payload = {
        "status": status,
        "release_id": settings.release_id,
        "protocol_version": settings.realtime_protocol_version,
        "task_protocol_version": TASK_PROTOCOL_VERSION,
        "pid": os.getpid(),
        "at": datetime.now(UTC).isoformat(),
    }
    if category:
        payload["category"] = category[:64]
    if settings.redis_url.strip():
        import redis.asyncio as aioredis
        from redis.backoff import NoBackoff
        from redis.retry import Retry

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
            await client.set(
                settings.redis_key_prefix + "jobs:probe:" + token,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                ex=max(30, settings.taskiq_probe_ttl_seconds),
            )
        finally:
            with contextlib.suppress(Exception):
                await client.aclose()
        return
    from app.db.session import get_sessionmaker
    from app.realtime.heartbeat import beat

    async with get_sessionmaker()() as db, db.begin():
        await beat(db, settings, name="probe:" + token, status=status, details=payload)


def register_tasks(broker: AsyncBroker, settings: Settings | None = None) -> None:
    """Register tasks on a broker (idempotent per broker/task name)."""
    settings = settings or getattr(broker, "_project1_settings", None) or get_settings()
    if broker.find_task(OUTBOX_TASK) is not None:
        return

    labels = {
        "retry_on_error": True,
        "max_retries": settings.taskiq_retry_max_retries,
        "delay": settings.taskiq_retry_delay_seconds,
        "ack_type": "when_executed",
        "task_protocol_version": TASK_PROTOCOL_VERSION,
    }

    @broker.task(
        OUTBOX_TASK,
        schedule=[{"schedule_id": "project1-jobs-outbox-v1",
                   "interval": settings.taskiq_outbox_interval_seconds}],
        **labels,
    )
    async def outbox_dispatch() -> dict[str, int]:
        return await _bounded(settings, lambda: get_outbox_service(settings).run_bounded())

    @broker.task(
        TIMEOUT_TASK,
        schedule=[{"schedule_id": "project1-jobs-timeout-scan-v1",
                   "interval": settings.timeout_scan_interval_seconds}],
        **labels,
    )
    async def timeout_scan() -> str:
        from app.services.trade_timeout import scan_once

        async def run() -> str:
            # Shared lease avoids overlapping scans when one invocation exceeds
            # the schedule interval; DB row locks remain the correctness backstop.
            from app.kv.base import KVError, get_kv

            owner = f"taskiq-timeout:{os.getpid()}:{secrets.token_hex(8)}"
            key = "jobs:timeout-scan"
            try:
                acquired = await get_kv().acquire_lease(
                    key, owner, ttl_seconds=max(30, settings.timeout_scan_interval_seconds * 3)
                )
            except KVError as exc:
                raise RetryableJobError(type(exc).__name__) from None
            if not acquired:
                return "skipped:lease"
            try:
                await scan_once()
                return "ok"
            finally:
                with contextlib.suppress(KVError):
                    await get_kv().release_lease(key, owner)

        return await _bounded(settings, run)

    @broker.task(
        RETENTION_TASK,
        schedule=[{"schedule_id": "project1-jobs-retention-v1",
                   "interval": settings.taskiq_retention_interval_seconds}],
        **labels,
    )
    async def retention_cleanup() -> int:
        async def run() -> int:
            deleted = 0
            for _ in range(max(1, settings.outbox_max_batches_per_run)):
                batch = await get_outbox_service(settings).cleanup_retention()
                deleted += batch
                if batch < settings.realtime_replay_max_events:
                    break
            return deleted

        return await _bounded(settings, run)

    @broker.task(
        IDEMPOTENCY_TASK,
        schedule=[{"schedule_id": "project1-jobs-idempotency-cleanup-v1",
                   "interval": settings.taskiq_idempotency_cleanup_interval_seconds}],
        **labels,
    )
    async def idempotency_cleanup() -> int:
        return await _bounded(settings, lambda: get_outbox_service(settings).cleanup_idempotency())

    @broker.task(PROBE_TASK, **labels)
    async def probe(token: str, expected_release: str) -> str:
        async def run() -> str:
            if not token or len(token) > 64 or not token.isalnum():
                raise ValueError("invalid probe token")
            # The probe deliberately records the *actual* release executing the
            # task; the CLI compares it with the activated release.
            await _write_probe_result(settings, token, status="ok")
            return settings.release_id

        return await _bounded(settings, run)


# Native Taskiq CLI imports this module after importing the default broker.
register_tasks(get_default_bundle().broker, get_default_bundle().broker._project1_settings)  # type: ignore[attr-defined]
