"""Role-aware liveness/readiness probes.

Liveness only proves the process can answer. Readiness checks the dependency
that actually makes the role useful: DB for API, gateway+DB for WS, real task
execution evidence for worker/jobs, and scheduler dispatch progress for
scheduler. The scheduler deliberately does not open a SQL pool; its heartbeat
lives in Redis. A worker row without a recent successful task execution is not
ready, so an idle PID cannot impersonate consumption.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings
from app.db.session import get_sessionmaker
from app.models.realtime import RealtimeEvent, ServiceHeartbeat
from app.observability import counters


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _fresh(value, *, seconds: float, now: datetime) -> bool:
    parsed = _parse_ts(value)
    return parsed is not None and (now - parsed).total_seconds() <= seconds


async def _database_ok(db: AsyncSession) -> bool:
    try:
        await asyncio.wait_for(db.exec(select(1)), timeout=2)
        return True
    except Exception:  # noqa: BLE001
        return False


async def _redis_ok(settings: Settings) -> bool:
    if not settings.redis_url.strip():
        return True
    try:
        if settings.redis_control_limit > 0:
            from app.kv.base import get_kv

            await asyncio.wait_for(get_kv().ping(), timeout=2)
        else:
            # Scheduler owns no control pool; use one short-lived heartbeat
            # connection instead of pretending to have a control budget.
            import redis.asyncio as aioredis

            client = aioredis.Redis.from_url(
                settings.redis_url, max_connections=1,
                socket_connect_timeout=settings.redis_connect_timeout_seconds,
                socket_timeout=settings.redis_socket_timeout_seconds,
            )
            try:
                await asyncio.wait_for(client.ping(), timeout=2)
            finally:
                await client.aclose()
        return True
    except Exception:  # noqa: BLE001
        return False


async def _scheduler_check(settings: Settings, payload: dict, now: datetime, db=None) -> tuple[bool, bool]:
    """Return (critical_ok, degraded) for scheduler progress."""
    from app.jobs.heartbeat import (
        read_scheduler_heartbeat,
        read_scheduler_heartbeat_sql,
    )

    details = await read_scheduler_heartbeat(settings)
    if details is None and db is not None:
        details = await read_scheduler_heartbeat_sql(db, settings)
    if details is None or details.get("status") == "stopping":
        payload["checks"]["scheduler"] = "missing" if details is None else "stopping"
        return False, False
    freshness = max(15.0, settings.taskiq_scheduler_update_interval_seconds * 3.0)
    schedule_ok = _fresh(details.get("heartbeat_at"), seconds=freshness, now=now)
    dispatch_ok = _fresh(
        details.get("last_dispatch_at"),
        seconds=max(30.0, settings.taskiq_outbox_interval_seconds * 3.0),
        now=now,
    )
    payload["checks"]["scheduler"] = {
        "status": details.get("status"),
        "heartbeat_fresh": schedule_ok,
        "dispatch_count": int(details.get("dispatch_count") or 0),
        "last_dispatch_at": details.get("last_dispatch_at"),
        "schedule_count": int(details.get("schedule_count") or 0),
        "last_task": details.get("last_task"),
    }
    identity_ok = (details.get("status") == "ready"
                   and details.get("release_id") == settings.release_id
                   and details.get("protocol_version") == settings.realtime_protocol_version)
    ok = identity_ok and schedule_ok and dispatch_ok and int(details.get("dispatch_count") or 0) > 0
    return ok, False


async def readiness(settings: Settings, *, gateway=None) -> tuple[dict, bool]:
    """Return (payload, http_ok). Degraded is explicit but may remain ready."""
    now = datetime.now(UTC)
    payload: dict = {
        "role": settings.app_role,
        "release_id": settings.release_id,
        "protocol_version": settings.realtime_protocol_version,
        "app": settings.app_name,
        "checks": {},
    }
    if settings.app_role == "scheduler":
        # No SQL connection is opened for the scheduler role.
        payload["checks"]["database"] = "not_used"
        redis = await _redis_ok(settings)
        payload["checks"]["redis"] = "ok" if redis else "failed"
        critical_ok = redis
        sched_ok, sched_degraded = await _scheduler_check(settings, payload, now)
        critical_ok = critical_ok and sched_ok
        degraded = sched_degraded
        payload["degraded"] = degraded
        payload["status"] = "ready" if critical_ok and not degraded else ("degraded" if critical_ok else "not_ready")
        payload["counters"] = counters.snapshot()
        return payload, critical_ok

    db_ok = False
    degraded = False
    async with get_sessionmaker()() as db:
        db_ok = await _database_ok(db)
        payload["checks"]["database"] = "ok" if db_ok else "failed"
        critical_ok = db_ok

        if settings.app_role == "ws":
            if gateway is not None:
                status = gateway.status()
                payload["checks"]["websocket"] = status
                if not status["ready"]:
                    critical_ok = False
                degraded = degraded or status["degraded"] or not status["stream_ok"]
            else:
                fresh = now - timedelta(seconds=max(15, settings.ws_heartbeat_timeout_seconds))
                row = (
                    await db.exec(
                        select(ServiceHeartbeat)
                        .where(
                            ServiceHeartbeat.role == "ws",
                            ServiceHeartbeat.release_id == settings.release_id,
                            ServiceHeartbeat.status != "stopping",
                            ServiceHeartbeat.heartbeat_at >= fresh,
                        )
                        .order_by(ServiceHeartbeat.heartbeat_at.desc())
                        .limit(1)
                    )
                ).first()
                payload["checks"]["websocket"] = "heartbeat" if row else "missing"
                if row is None:
                    critical_ok = False

        if settings.app_role == "worker":
            fresh_after = now - timedelta(
                seconds=max(30.0, settings.taskiq_outbox_interval_seconds * 3.0 + 5.0)
            )
            row = (
                await db.exec(
                    select(ServiceHeartbeat)
                    .where(
                        ServiceHeartbeat.role == "worker",
                        col(ServiceHeartbeat.details)["role"].as_string() == "worker",
                        ServiceHeartbeat.release_id == settings.release_id,
                        ServiceHeartbeat.status != "stopping",
                        ServiceHeartbeat.heartbeat_at >= fresh_after,
                    )
                    .order_by(ServiceHeartbeat.heartbeat_at.desc())
                    .limit(1)
                )
            ).first()
            worker_details = dict(row.details or {}) if row else {}
            execution_ok = bool(row) and worker_details.get("role") == "worker" and _fresh(
                worker_details.get("last_success_at"),
                seconds=max(30.0, settings.taskiq_outbox_interval_seconds * 3.0 + 5.0),
                now=now,
            )
            payload["checks"]["worker"] = {
                "status": worker_details.get("status", row.status if row else None),
                "heartbeat_at": row.heartbeat_at.isoformat() if row else None,
                "last_success_at": worker_details.get("last_success_at"),
                "successes": int(worker_details.get("successes") or 0),
                "failures": int(worker_details.get("failures") or 0),
                "terminal_failures": int(worker_details.get("terminal_failures") or 0),
                "last_error": worker_details.get("last_error"),
                "last_terminal_failure": worker_details.get("last_terminal_failure"),
            }
            if not execution_ok:
                critical_ok = False
            elif worker_details.get("status") == "degraded":
                degraded = True

            pending = (
                await db.exec(
                    select(func.count()).select_from(RealtimeEvent).where(
                        RealtimeEvent.delivered_at.is_(None),
                        RealtimeEvent.dead_at.is_(None),
                    )
                )
            ).first() or 0
            dead = (
                await db.exec(
                    select(func.count()).select_from(RealtimeEvent).where(
                        RealtimeEvent.dead_at.is_not(None),
                    )
                )
            ).first() or 0
            oldest = (
                await db.exec(
                    select(func.min(RealtimeEvent.created_at)).where(
                        RealtimeEvent.delivered_at.is_(None),
                        RealtimeEvent.dead_at.is_(None),
                    )
                )
            ).first()
            age = 0
            if oldest is not None:
                if oldest.tzinfo is None:
                    oldest = oldest.replace(tzinfo=UTC)
                age = int((now - oldest).total_seconds())
            payload["checks"]["outbox"] = {
                "pending": int(pending), "dead": int(dead), "oldest_age_seconds": max(0, age)
            }
            if dead:
                degraded = True
            if age > max(60, settings.outbox_lease_seconds * 2) or pending > settings.realtime_pending_degraded_threshold:
                degraded = True

        if settings.redis_url.strip():
            redis = await _redis_ok(settings)
            payload["checks"]["redis"] = "ok" if redis else "failed"
            degraded = degraded or not redis

    payload["degraded"] = degraded
    payload["status"] = "ready" if critical_ok and not degraded else ("degraded" if critical_ok else "not_ready")
    payload["counters"] = counters.snapshot()
    return payload, critical_ok
