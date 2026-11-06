"""Producer health checks cannot impersonate workers or acquire SQL pools."""

from unittest.mock import AsyncMock

from app.core.config import get_settings
from app.jobs.heartbeat import SchedulerHeartbeat
from app.jobs.middleware import JobHeartbeatMiddleware


async def test_scheduler_lifecycle_never_opens_worker_sql_resources(monkeypatch):
    middleware = JobHeartbeatMiddleware(get_settings().model_copy(update={"app_role": "scheduler"}))
    write = AsyncMock()
    dispose = AsyncMock()
    monkeypatch.setattr(middleware, "_write", write)
    monkeypatch.setattr("app.jobs.middleware.dispose_engine", dispose)
    await middleware.startup()
    await middleware.shutdown()
    write.assert_not_awaited()
    dispose.assert_not_awaited()


async def test_probe_producer_close_does_not_overwrite_live_scheduler(monkeypatch):
    settings = get_settings().model_copy(update={"redis_url": "redis://127.0.0.1:1/0"})
    heartbeat = SchedulerHeartbeat(settings)
    beat = AsyncMock()
    monkeypatch.setattr(heartbeat, "beat", beat)
    await heartbeat.close()
    beat.assert_not_awaited()


async def test_probe_producer_shutdown_does_not_write_false_worker_status(monkeypatch):
    middleware = JobHeartbeatMiddleware(get_settings().model_copy(update={"app_role": "worker"}))
    write = AsyncMock()
    dispose = AsyncMock()
    monkeypatch.setattr(middleware, "_write", write)
    monkeypatch.setattr("app.jobs.middleware.dispose_engine", dispose)
    await middleware.shutdown()
    write.assert_not_awaited()
    dispose.assert_not_awaited()


async def test_first_success_heartbeat_is_written_immediately(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from taskiq.result import TaskiqResult

    middleware = JobHeartbeatMiddleware(get_settings().model_copy(update={"app_role": "worker"}))
    middleware.set_broker(SimpleNamespace(is_worker_process=True))
    write = AsyncMock()
    monkeypatch.setattr(middleware, "_write", write)
    result = TaskiqResult(is_err=False, return_value=None, execution_time=0.1)
    message = SimpleNamespace(task_name="probe", task_id="t1", labels={})
    await middleware.post_execute(message, result)
    assert write.await_args.kwargs.get("force") is True
    await middleware.post_execute(message, result)
    assert write.await_args.kwargs.get("force") is False
