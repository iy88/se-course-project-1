"""In-process Taskiq runtime for the combined/dev boundary and legacy jobs role.

Split production uses the native Taskiq worker/scheduler CLI through
``app.manage taskiq-worker`` / ``taskiq-scheduler``. This module exists so the
compatibility ``serve``/``serve-jobs`` entries run the official
``Receiver``/``SchedulerLoop`` instead of any hand-written consumer loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from taskiq.acks import AcknowledgeType
from taskiq.cli.scheduler.run import SchedulerLoop
from taskiq.receiver import Receiver

from app.core.config import Settings
from app.jobs.broker import BrokerBundle, build_bundle
from app.jobs.tasks import register_tasks


class JobsRuntime:
    def __init__(self, settings: Settings, *, inline: bool = False) -> None:
        self.settings = settings
        self.bundle: BrokerBundle = build_bundle(settings, inline=inline)
        register_tasks(self.bundle.broker, settings)
        self._scheduler_task: asyncio.Task | None = None
        self._receiver_task: asyncio.Task | None = None
        self._finish = asyncio.Event()
        self._executor: ThreadPoolExecutor | None = None
        self._receiver: Receiver | None = None

    @property
    def inline(self) -> bool:
        return self.bundle.inline

    async def start(self) -> None:
        broker = self.bundle.broker
        # The in-process receiver is a real consumer in this process.
        broker.is_worker_process = True
        if self.inline:
            # InMemoryBroker's internal Receiver executes kicks immediately;
            # startup is required for middleware (heartbeat) lifecycle.
            await broker.startup()  # type: ignore[func-returns-value]
        else:
            self._executor = ThreadPoolExecutor(
                max_workers=max(2, self.settings.taskiq_max_async_tasks),
                thread_name_prefix="taskiq-sync",
            )
            self._receiver = Receiver(
                broker=broker,
                executor=self._executor,
                validate_params=True,
                max_async_tasks=self.settings.taskiq_max_async_tasks,
                max_prefetch=self.settings.taskiq_max_prefetch,
                propagate_exceptions=False,
                ack_type=AcknowledgeType.WHEN_EXECUTED,
                wait_tasks_timeout=self.settings.taskiq_shutdown_timeout_seconds,
            )
            self._receiver_task = asyncio.create_task(
                self._receiver.listen(self._finish), name="taskiq-receiver"
            )
        for source in self.bundle.scheduler.sources:
            await source.startup()
        self._scheduler_task = asyncio.create_task(
            SchedulerLoop(self.bundle.scheduler).run(
                update_interval=timedelta(seconds=self.settings.taskiq_scheduler_update_interval_seconds),
                loop_interval=timedelta(seconds=self.settings.taskiq_scheduler_loop_interval_seconds),
                send_timeout=self.settings.taskiq_scheduler_send_timeout_seconds,
            ),
            name="taskiq-scheduler-loop",
        )
        # Serve readiness only after at least one scheduled task executed, so
        # an immediately-following /api/health is not a false "not_ready".
        deadline = time.monotonic() + max(3.0, self.settings.taskiq_outbox_interval_seconds + 2.0)
        while self.bundle.heartbeat.last_success_at is None and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if self.bundle.heartbeat.last_success_at is not None:
            await self.bundle.heartbeat._write("ready", force=True)

    async def stop(self) -> None:
        self._finish.set()
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scheduler_task
            self._scheduler_task = None
        if self._receiver_task is not None:
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self._receiver_task,
                                       timeout=self.settings.taskiq_shutdown_timeout_seconds + 5)
            self._receiver_task = None
        if self.inline:
            with contextlib.suppress(Exception):
                await self.bundle.broker.wait_all()  # type: ignore[attr-defined]
        # Scheduler shutdown closes the broker and scheduler heartbeat; sources
        # still need their own shutdown, exactly like the native CLI.
        with contextlib.suppress(Exception):
            await self.bundle.scheduler.shutdown()
        for source in self.bundle.scheduler.sources:
            with contextlib.suppress(Exception):
                await source.shutdown()
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None
        if self.inline:
            with contextlib.suppress(Exception):
                await self.bundle.scheduler_heartbeat.close()
