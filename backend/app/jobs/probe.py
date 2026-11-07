"""Real task-execution probe used by deployment readiness.

Nothing here calls a task function directly: the probe is enqueued through the
official Taskiq broker and must be picked up by a worker process, then its
result is read from Redis (or SQL in the offline test path).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import time
from datetime import UTC, datetime

from app.core.config import Settings
from app.jobs.broker import build_bundle
from app.jobs.tasks import PROBE_TASK, register_tasks


async def _read_result(settings: Settings, token: str) -> dict | None:
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
            raw = await client.get(settings.redis_key_prefix + "jobs:probe:" + token)
            return json.loads(raw) if raw else None
        except ValueError:
            return None
        finally:
            with contextlib.suppress(Exception):
                await client.aclose()

    from app.db.session import get_sessionmaker
    from app.models.realtime import ServiceHeartbeat

    async with get_sessionmaker()() as db:
        row = await db.get(ServiceHeartbeat, "probe:" + token)
        return dict(row.details or {}) if row is not None else None


async def run_probe(settings: Settings, *, timeout: float | None = None) -> dict:
    token = secrets.token_hex(16)
    deadline = time.monotonic() + (timeout or settings.taskiq_probe_timeout_seconds)
    bundle = build_bundle(settings)
    register_tasks(bundle.broker, settings)
    task = bundle.broker.find_task(PROBE_TASK)
    if task is None:
        raise RuntimeError("probe task is not registered")
    try:
        await task.kiq(token, settings.release_id)
        if bundle.inline:
            with contextlib.suppress(Exception):
                await bundle.broker.wait_all()  # type: ignore[attr-defined]
    finally:
        # Factory process: close broker/schedule pools; the worker owns its own.
        with contextlib.suppress(Exception):
            await bundle.broker.shutdown()
        with contextlib.suppress(Exception):
            await bundle.scheduler_heartbeat.close()
    result: dict | None = None
    while time.monotonic() < deadline:
        result = await _read_result(settings, token)
        if result is not None and result.get("status") == "ok":
            break
        await asyncio.sleep(0.2)
    if result is None or result.get("status") != "ok":
        raise TimeoutError("task probe was not executed before the deadline")
    if str(result.get("release_id")) != settings.release_id:
        raise RuntimeError("task probe ran on a different release")
    return {
        "status": "ok",
        "release_id": result.get("release_id"),
        "protocol_version": result.get("protocol_version"),
        "task_protocol_version": result.get("task_protocol_version"),
        "observed_at": datetime.now(UTC).isoformat(),
    }
