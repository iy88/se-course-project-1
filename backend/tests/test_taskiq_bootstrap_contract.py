"""A durable task queue must consume work that predates its consumer group."""

from taskiq_redis import RedisStreamBroker

from app.core.config import get_settings
from app.jobs.broker import build_bundle


async def test_startup_checks_actual_ack_permission_not_just_command_inventory(monkeypatch):
    from unittest.mock import AsyncMock

    import pytest

    from app.jobs import broker as module

    settings = get_settings().model_copy(update={"redis_url": "redis://127.0.0.1:1/0"})
    broker = build_bundle(settings).broker
    base_start = AsyncMock()
    monkeypatch.setattr(RedisStreamBroker, "startup", base_start)
    acknowledge = AsyncMock(side_effect=PermissionError("denied"))

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        xackdel = acknowledge

    monkeypatch.setattr(module, "Redis", lambda **_kwargs: Client())
    with pytest.raises(RuntimeError, match="XACKDEL ACKED permission"):
        await broker.startup()
    base_start.assert_awaited_once()
    acknowledge.assert_awaited_once_with(broker.queue_name, broker.consumer_group_name,
                                        "0-0", ref_policy="ACKED")


def test_task_group_starts_from_retained_work_and_never_trims_pending():
    settings = get_settings().model_copy(update={
        "redis_url": "redis://127.0.0.1:1/0", "redis_key_prefix": "contract-test:",
    })
    broker = build_bundle(settings).broker
    assert isinstance(broker, RedisStreamBroker)
    # '$' silently abandons retained tasks if a group is created/recreated.
    assert broker.consumer_id in {"0", "0-0"}
    assert broker.maxlen is None
