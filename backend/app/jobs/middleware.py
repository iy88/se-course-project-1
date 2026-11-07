"""Taskiq middleware: real worker heartbeats and terminal failure visibility."""

from __future__ import annotations

import contextlib
import json
import time
from datetime import UTC, datetime

from taskiq.abc.middleware import TaskiqMiddleware
from taskiq.message import TaskiqMessage
from taskiq.result import TaskiqResult

from app.core.config import Settings
from app.db.session import dispose_engine, get_sessionmaker
from app.realtime.heartbeat import beat, instance_name


class JobHeartbeatMiddleware(TaskiqMiddleware):
    """Publishes *execution* evidence, not merely a process heartbeat.

    ``last_success_at`` is only advanced after a task result without an error,
    so readiness that found a worker row but no successful execution still
    fails. Terminal retry exhaustion is recorded in both the SQL details and a
    short-lived Redis key for operator visibility. No task args/payloads are
    stored.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.name = instance_name(settings)
        self.started_at = datetime.now(UTC)
        self.successes = 0
        self.failures = 0
        self.terminal_failures = 0
        self.last_success_at: datetime | None = None
        self.last_task: str | None = None
        self.last_error: str | None = None
        self.last_terminal: dict | None = None
        self._last_write = 0.0
        self._started = False

    def _active(self) -> bool:
        """Only a real consumer writes.

        Probe/scheduler factory processes import the same broker/tasks but must
        not manufacture worker rows or dispose a shared producer engine.
        """
        if self.settings.app_role == "scheduler":
            return False
        return bool(getattr(self.broker, "is_worker_process", False))

    def details(self, status: str = "ready") -> dict:
        return {
            "role": "worker",
            "status": status,
            "release_id": self.settings.release_id,
            "protocol_version": self.settings.realtime_protocol_version,
            "last_task": self.last_task,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "successes": self.successes,
            "failures": self.failures,
            "terminal_failures": self.terminal_failures,
            "last_error": self.last_error,
            "last_terminal_failure": self.last_terminal,
        }

    async def _write(self, status: str = "ready", *, force: bool = False) -> None:
        if not self._active():
            return
        now = time.monotonic()
        if not force and now - self._last_write < 1.0:
            return
        self._last_write = now
        try:
            async with get_sessionmaker()() as db, db.begin():
                await beat(db, self.settings, name=self.name, status=status,
                           details=self.details(status), started_at=self.started_at)
        except Exception as exc:  # noqa: BLE001 - visibility must not break tasks
            import logging

            logging.getLogger(__name__).warning("worker heartbeat write failed: %s", type(exc).__name__)

    async def _write_terminal(self, message: TaskiqMessage, error: BaseException) -> None:
        self.terminal_failures += 1
        self.last_terminal = {
            "task_name": message.task_name,
            "task_id": message.task_id,
            "error": type(error).__name__,
            "at": datetime.now(UTC).isoformat(),
            "retries": int(message.labels.get("_retries", 0) or 0),
        }
        if self.settings.redis_url.strip():
            try:
                import redis.asyncio as aioredis

                client = aioredis.Redis.from_url(
                    self.settings.redis_url, decode_responses=True, max_connections=1,
                    socket_connect_timeout=self.settings.redis_connect_timeout_seconds,
                    socket_timeout=self.settings.redis_socket_timeout_seconds,
                )
                try:
                    await client.set(
                        self.settings.redis_key_prefix + "jobs:terminal-failure:" + self.settings.release_id,
                        json.dumps(self.last_terminal, ensure_ascii=False, separators=(",", ":")),
                        ex=max(3600, self.settings.realtime_event_retention_hours * 3600),
                    )
                finally:
                    with contextlib.suppress(Exception):
                        await client.aclose()
            except Exception as exc:  # noqa: BLE001
                import logging

                logging.getLogger(__name__).warning("terminal failure record failed: %s", type(exc).__name__)
        await self._write("degraded", force=True)

    async def startup(self) -> None:
        # Native scheduler is only a producer and must never open a SQL pool.
        if self.settings.app_role == "scheduler":
            return
        self._started = True
        await self._write("starting", force=True)

    async def shutdown(self) -> None:
        # A short-lived probe producer never called startup; it must not write
        # a false worker shutdown heartbeat or dispose another owner's engine.
        if not self._started:
            return
        self._started = False
        await self._write("stopping", force=True)
        from app.jobs.state import close_job_resources

        await close_job_resources()
        if self.settings.app_role == "worker":
            await dispose_engine()

    async def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        self.last_task = message.task_name
        return message

    async def post_execute(self, message: TaskiqMessage, result: TaskiqResult) -> None:
        if not result.is_err:
            first_success = self.last_success_at is None
            self.successes += 1
            self.last_success_at = datetime.now(UTC)
            self.last_error = None
            # The first success must be visible before a startup health probe;
            # the normal 1s throttle would leave the row at "starting".
            await self._write("ready", force=first_success)
        else:
            self.last_error = type(result.error).__name__ if result.error is not None else "ExecutionError"
            await self._write("degraded")

    async def on_error(self, message: TaskiqMessage, result: TaskiqResult,
                        exception: BaseException) -> None:
        self.failures += 1
        self.last_error = type(exception).__name__
        current = int(message.labels.get("_retries", 0) or 0)
        from app.jobs.errors import RetryableJobError

        ceiling = int(message.labels.get("max_retries", self.settings.taskiq_retry_max_retries))
        retry_enabled = str(message.labels.get("retry_on_error", False)).lower() == "true"
        if not isinstance(exception, RetryableJobError) or not retry_enabled or current + 1 >= ceiling:
            await self._write_terminal(message, exception)
        else:
            await self._write("degraded")
