"""Official Taskiq broker and scheduler construction.

* ``RedisStreamBroker`` with at-least-once acknowledgement (the worker CLI sets
  ``--ack-type WHEN_EXECUTED``) and Taskiq's own consumer group.
* The task stream is a separate key/namespace from ``realtime:v1:events``. WS
  gateways never join this group.
* ``SmartRetryMiddleware`` owns delayed retries via the official
  ``ListRedisScheduleSource``. The source is configured with a JSON serializer,
  not pickle.
* The broker stream is never MAXLEN-trimmed. Redis 8.2+ XACKDEL ACKED reclaims
  completed payloads without deleting pending or unread work.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from taskiq import TaskiqScheduler
from taskiq.brokers.inmemory_broker import InMemoryBroker
from taskiq.middlewares import SmartRetryMiddleware
from taskiq.schedule_sources import LabelScheduleSource
from taskiq.scheduler.scheduled_task import ScheduledTask
from taskiq.serializers import JSONSerializer
from taskiq_redis import ListRedisScheduleSource, RedisStreamBroker

from app.core.config import Settings, get_settings
from app.jobs.errors import RetryableJobError
from app.jobs.heartbeat import SchedulerHeartbeat
from app.jobs.middleware import JobHeartbeatMiddleware


def _redis_common(settings: Settings) -> dict:
    return {
        "socket_connect_timeout": settings.redis_connect_timeout_seconds,
        "socket_timeout": max(settings.redis_socket_timeout_seconds,
                              settings.taskiq_xread_block_ms / 1000.0 + 1.0),
        "retry_on_timeout": False,
        "retry": Retry(NoBackoff(), 0),
        "health_check_interval": 30,
    }


class ReclaimingRedisStreamBroker(RedisStreamBroker):
    """Redis Streams broker with safe acknowledgement-time reclamation.

    ``XACKDEL ... REF_POLICY ACKED`` (Redis 8.2+) acknowledges the message and
    deletes only when every consumer group has acknowledged it; unread or
    pending work is preserved. The broker keeps Taskiq's official
    receive/claim/retry loop and only overrides the ACK hook. Older Redis
    versions are rejected at startup rather than silently weakening storage
    semantics. Startup probes the actual command/ACL with the impossible entry
    ID 0-0, after creating the group; no task payload is changed.
    """

    async def startup(self) -> None:
        await super().startup()
        await self._assert_ackdel_capability()

    async def _assert_ackdel_capability(self) -> None:
        async with Redis(connection_pool=self.connection_pool) as redis_conn:
            try:
                # Redis never assigns stream ID 0-0. Exercise the actual ACK
                # permission and group visibility without altering any payload.
                await redis_conn.xackdel(self.queue_name, self.consumer_group_name,
                                         "0-0", ref_policy="ACKED")
            except Exception:  # noqa: BLE001 - stable startup category, no URL
                raise RuntimeError(
                    "Redis 8.2+ and XACKDEL ACKED permission on the task group are required"
                ) from None

    def _ack_generator(self, id: str, queue_name: str) -> Callable[[], Awaitable[None]]:
        async def _ack() -> None:
            async with Redis(connection_pool=self.connection_pool) as redis_conn:
                await redis_conn.xackdel(
                    queue_name,
                    self.consumer_group_name,
                    id,
                    ref_policy="ACKED",
                )

        return _ack


class ObservedLabelScheduleSource(LabelScheduleSource):
    """Static interval/cron schedules plus scheduler progress heartbeat."""

    def __init__(self, broker, heartbeat: SchedulerHeartbeat) -> None:
        super().__init__(broker)
        self.heartbeat = heartbeat

    async def startup(self) -> None:
        await super().startup()
        await self.heartbeat.beat(status="ready", schedule_count=len(self.schedules),
                                  schedule_ids=list(self.schedules))

    async def get_schedules(self) -> list[ScheduledTask]:
        schedules = await super().get_schedules()
        merged: dict[str, ScheduledTask] = {task.schedule_id: task for task in schedules}
        # Retry/time schedules from the Redis source are merged by TaskiqScheduler;
        # this source only owns the static labels. Heartbeat records its own set.
        await self.heartbeat.beat(status="ready", schedule_count=len(merged),
                                  schedule_ids=list(merged))
        return schedules


class ObservedTaskiqScheduler(TaskiqScheduler):
    """Taskiq scheduler that records successful dispatch progress."""

    def __init__(self, broker, sources, heartbeat: SchedulerHeartbeat) -> None:
        super().__init__(broker=broker, sources=sources)
        self.heartbeat = heartbeat

    async def startup(self) -> None:
        await super().startup()
        await self.heartbeat.beat(status="ready")

    async def on_ready(self, source, task: ScheduledTask) -> None:
        await super().on_ready(source, task)
        await self.heartbeat.dispatched(task.task_name)

    async def shutdown(self) -> None:
        await self.heartbeat.beat(status="stopping")
        await super().shutdown()
        await self.heartbeat.close()


@dataclass
class BrokerBundle:
    broker: object
    scheduler: ObservedTaskiqScheduler
    retry_source: ListRedisScheduleSource | None
    heartbeat: JobHeartbeatMiddleware
    scheduler_heartbeat: SchedulerHeartbeat
    inline: bool


def build_bundle(settings: Settings, *, inline: bool = False) -> BrokerBundle:
    worker_heartbeat = JobHeartbeatMiddleware(settings)
    scheduler_heartbeat = SchedulerHeartbeat(settings)
    if inline or not settings.redis_url.strip():
        broker = InMemoryBroker(
            max_async_tasks=settings.taskiq_max_async_tasks,
            await_inplace=False,
        )
        broker.with_middlewares(
            SmartRetryMiddleware(
                default_retry_count=settings.taskiq_retry_max_retries,
                default_retry_label=False,
                default_delay=settings.taskiq_retry_delay_seconds,
                use_jitter=settings.taskiq_retry_jitter,
                use_delay_exponent=settings.taskiq_retry_exponent,
                max_delay_exponent=float(settings.taskiq_retry_max_delay_seconds),
                types_of_exceptions=(RetryableJobError,),
            ),
            worker_heartbeat,
        )
        retry_source = None
    else:
        retry_source = ListRedisScheduleSource(
            settings.redis_url,
            prefix=settings.redis_key_prefix + settings.taskiq_retry_prefix,
            max_connection_pool_size=settings.taskiq_schedule_max_connections,
            serializer=JSONSerializer(),
            **_redis_common(settings),
        )
        broker = ReclaimingRedisStreamBroker(
            settings.redis_url,
            queue_name=settings.redis_key_prefix + settings.taskiq_queue_name,
            consumer_group_name=settings.redis_key_prefix + settings.taskiq_consumer_group,
            max_connection_pool_size=settings.taskiq_broker_max_connections,
            consumer_id="0-0",
            mkstream=True,
            xread_block=settings.taskiq_xread_block_ms,
            xread_count=settings.taskiq_xread_count,
            # Deliberately no maxlen: pending/unacked task entries must not be
            # trimmed away. Outbox retry/backfill is the durable recovery path.
            maxlen=None,
            idle_timeout=settings.taskiq_reclaim_idle_ms,
            unacknowledged_batch_size=settings.taskiq_unacknowledged_batch_size,
            unacknowledged_lock_timeout=settings.taskiq_unacknowledged_lock_timeout_seconds,
            **_redis_common(settings),
        )
        broker.with_middlewares(
            SmartRetryMiddleware(
                default_retry_count=settings.taskiq_retry_max_retries,
                default_retry_label=False,
                default_delay=settings.taskiq_retry_delay_seconds,
                use_jitter=settings.taskiq_retry_jitter,
                use_delay_exponent=settings.taskiq_retry_exponent,
                max_delay_exponent=float(settings.taskiq_retry_max_delay_seconds),
                schedule_source=retry_source,
                types_of_exceptions=(RetryableJobError,),
            ),
            worker_heartbeat,
        )
    broker._project1_settings = settings  # type: ignore[attr-defined]
    sources = [ObservedLabelScheduleSource(broker, scheduler_heartbeat)]
    if retry_source is not None:
        sources.append(retry_source)
    scheduler = ObservedTaskiqScheduler(broker, sources, scheduler_heartbeat)
    return BrokerBundle(
        broker=broker,
        scheduler=scheduler,
        retry_source=retry_source,
        heartbeat=worker_heartbeat,
        scheduler_heartbeat=scheduler_heartbeat,
        inline=inline or not settings.redis_url.strip(),
    )


# Lazy module-level objects imported by the native Taskiq CLI / manage wrapper.
# Construction only builds pools; no connection is opened until a task starts.
_default_bundle: BrokerBundle | None = None


def get_default_bundle() -> BrokerBundle:
    global _default_bundle
    if _default_bundle is None:
        _default_bundle = build_bundle(get_settings())
    return _default_bundle


def __getattr__(name: str):
    if name == "broker":
        return get_default_bundle().broker
    if name == "scheduler":
        return get_default_bundle().scheduler
    raise AttributeError(name)
