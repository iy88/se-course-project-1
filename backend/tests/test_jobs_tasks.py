"""Taskiq wiring is real framework wiring, not a renamed hand-written loop."""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.jobs.broker import build_bundle
from app.jobs.probe import run_probe
from app.jobs.tasks import (
    IDEMPOTENCY_TASK,
    OUTBOX_TASK,
    PROBE_TASK,
    RETENTION_TASK,
    TIMEOUT_TASK,
    register_tasks,
)


def _redis_config():
    return get_settings().model_copy(update={
        "redis_url": "redis://127.0.0.1:6399/0",
        "redis_key_prefix": "test-jobs:",
        "realtime_stream_name": "realtime:v1:events",
    })


def test_task_stream_namespace_is_separate_and_not_trimmed():
    settings = _redis_config()
    bundle = build_bundle(settings)
    broker = bundle.broker
    assert broker.queue_name == "test-jobs:jobs:v1:taskiq"
    assert broker.consumer_group_name == "test-jobs:jobs:v1:workers"
    assert broker.queue_name != settings.redis_key_prefix + settings.realtime_stream_name
    # Pending/unacked task entries must never be dropped by MAXLEN trimming.
    assert broker.maxlen is None
    assert bundle.retry_source is not None
    # The official retry/schedule source uses JSON, never pickle.
    from taskiq.serializers import JSONSerializer

    assert isinstance(bundle.retry_source._serializer, JSONSerializer)


def test_versioned_task_names_and_static_schedules_are_stable_across_restart():
    settings = get_settings()
    bundle = build_bundle(settings, inline=True)
    register_tasks(bundle.broker, settings)
    names = set(bundle.broker.local_task_registry)
    assert {OUTBOX_TASK, TIMEOUT_TASK, RETENTION_TASK, IDEMPOTENCY_TASK, PROBE_TASK} <= names
    source = bundle.scheduler.sources[0]

    async def run() -> None:
        await source.startup()
        first = {sid: (task.task_name, task.interval) for sid, task in source.schedules.items()}
        # A restart rebuilds the same explicit IDs instead of appending random
        # duplicates to the scheduler.
        await source.startup()
        second = {sid: (task.task_name, task.interval) for sid, task in source.schedules.items()}
        assert first == second
        assert len(second) == len(set(second))

    asyncio.run(run())


async def test_probe_roundtrip_executes_through_taskiq_receiver():
    from app.db.session import Base, dispose_engine, engine

    settings = get_settings()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        result = await run_probe(settings, timeout=5)
        assert result["status"] == "ok"
        assert result["release_id"] == settings.release_id
    finally:
        await dispose_engine()


async def test_outbox_publish_failure_is_retryable_by_taskiq():
    from app.jobs.errors import RetryableJobError
    from app.jobs.tasks import _bounded
    from app.realtime.dispatcher import OutboxPublishError

    settings = get_settings()

    async def fail():
        raise OutboxPublishError("connection")

    try:
        await _bounded(settings, fail)
    except RetryableJobError as exc:
        assert exc.category == "connection"
    else:  # pragma: no cover
        raise AssertionError("outbox publish failure was not made retryable")
