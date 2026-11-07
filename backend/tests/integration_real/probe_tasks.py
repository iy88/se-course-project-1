"""Test-only Taskiq tasks for reclaim/retry gates.

The runner adds this module through TASKIQ_EXTRA_TASK_MODULES; production keeps
only ``app.jobs.tasks``. Arguments are small control values, never payloads or
secrets.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from datetime import UTC, datetime

from app.jobs.broker import get_default_bundle

SLOW_PROBE_TASK = "project1.jobs.test.slow_probe.v1"
RETRY_PROBE_TASK = "project1.jobs.test.retry_probe.v1"


def register(broker, settings) -> None:
    if broker.find_task(SLOW_PROBE_TASK) is not None:
        return

    async def _redis():
        import redis.asyncio as aioredis

        return aioredis.Redis.from_url(settings.redis_url, decode_responses=True, max_connections=2)

    async def _write(token: str, payload: dict) -> None:
        client = await _redis()
        try:
            await client.set(settings.redis_key_prefix + "test:task:" + token,
                             json.dumps(payload, ensure_ascii=False), ex=300)
        finally:
            with contextlib.suppress(Exception):
                await client.aclose()

    @broker.task(
        SLOW_PROBE_TASK,
        retry_on_error=False,
        max_retries=0,
        ack_type="when_executed",
    )
    async def slow_probe(token: str) -> str:
        await _write(token, {"phase": "started", "pid": os.getpid(),
                             "at": datetime.now(UTC).isoformat()})
        client = await _redis()
        try:
            gate = settings.redis_key_prefix + "test:release:" + token
            async with asyncio.timeout(30):
                while not await client.exists(gate):
                    await asyncio.sleep(0.05)
        finally:
            await client.aclose()
        await _write(token, {"phase": "done", "pid": os.getpid(),
                             "at": datetime.now(UTC).isoformat()})
        return "done"

    @broker.task(
        RETRY_PROBE_TASK,
        retry_on_error=True,
        max_retries=settings.taskiq_retry_max_retries,
        delay=settings.taskiq_retry_delay_seconds,
        ack_type="when_executed",
    )
    async def retry_probe(token: str, fail_times: int = 1) -> str:
        from app.jobs.errors import RetryableJobError

        client = await _redis()
        try:
            key = settings.redis_key_prefix + "test:retry:" + token
            count = int(await client.incr(key))
            await client.expire(key, 300)
            await _write(token, {"phase": "attempt", "count": count,
                                 "at": datetime.now(UTC).isoformat()})
        finally:
            with contextlib.suppress(Exception):
                await client.aclose()
        if count <= fail_times:
            raise RetryableJobError("test_transient")
        await _write(token, {"phase": "success", "count": count,
                             "at": datetime.now(UTC).isoformat()})
        return "ok"


_default = get_default_bundle()
_settings = _default.broker._project1_settings  # type: ignore[attr-defined]
register(_default.broker, _settings)
