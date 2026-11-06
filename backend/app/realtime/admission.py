"""Soft outbox admission gate evaluated before counter allocation.

The check reads PostgreSQL pending count/age, not a Redis flag, so a Redis
outage cannot accidentally admit an already-full outbox. It runs in the same
business transaction before counter locks and before any event row is inserted;
rejection rolls back the business/audit rows. The per-process cache is a short
soft-budget window, not a global hard cap.

No global DB lock or row lock is taken. A simple process-local dict is used for
the cache; SQL I/O happens outside any threading lock. Cache entries are keyed
by engine identity + database/schema + configured budgets and are cleared when
the engine is disposed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.realtime import RealtimeEvent
from app.observability import counters


class OutboxAdmissionError(RuntimeError):
    """Stable, content-free admission failure."""

    def __init__(self, reason: str, *, pending: int = 0, age_seconds: int = 0,
                 retry_after: int = 30) -> None:
        super().__init__(f"realtime outbox admission: {reason}")
        self.reason = reason
        self.pending = int(pending)
        self.age_seconds = int(age_seconds)
        self.retry_after = max(1, int(retry_after))


@dataclass(frozen=True)
class _Snapshot:
    at: float
    pending: int
    age_seconds: int


_CACHE: dict[tuple, _Snapshot] = {}


async def _admission_handler(_request, exc: OutboxAdmissionError):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        {"detail": "实时事件积压超过当前预算，请稍后重试"},
        status_code=503,
        headers={"Retry-After": str(exc.retry_after)},
    )


def install_admission_handler(app) -> None:
    from fastapi import FastAPI

    if isinstance(app, FastAPI):
        app.add_exception_handler(OutboxAdmissionError, _admission_handler)


def clear_admission_cache() -> None:
    _CACHE.clear()


def _engine_identity(session: Session) -> tuple:
    engine = session.get_bind()
    try:
        database = str(engine.url.database or "")
    except Exception:  # noqa: BLE001 - identity must not fail the gate
        database = ""
    return (id(engine), database)


def _read_snapshot(session: Session) -> tuple[int, int]:
    pending = int(session.execute(
        select(func.count()).select_from(RealtimeEvent).where(RealtimeEvent.delivered_at.is_(None))
    ).scalar_one() or 0)
    oldest = session.execute(
        select(func.min(RealtimeEvent.created_at)).where(RealtimeEvent.delivered_at.is_(None))
    ).scalar_one()
    age = 0
    if oldest is not None:
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=UTC)
        age = max(0, int((datetime.now(UTC) - oldest).total_seconds()))
    return pending, age


def check_outbox_admission(session: Session, *, incoming: int = 0) -> None:
    settings = get_settings()
    if not settings.realtime_admission_enabled:
        return
    now = time.monotonic()
    key = (*_engine_identity(session), settings.environment, settings.database_schema,
           settings.realtime_outbox_max_pending, settings.realtime_outbox_max_age_seconds)
    cached = _CACHE.get(key)
    cache_seconds = settings.realtime_outbox_admission_cache_seconds
    if cache_seconds > 0 and cached is not None and now - cached.at <= cache_seconds:
        counters.incr("outbox.admission_cache_hit")
        snapshot = cached
    else:
        try:
            pending, age = _read_snapshot(session)
        except (SQLAlchemyError, OSError) as exc:
            counters.incr("outbox.admission_unavailable")
            raise OutboxAdmissionError("unavailable", retry_after=settings.realtime_outbox_retry_after_seconds) from exc
        snapshot = _Snapshot(now, pending, age)
        _CACHE[key] = snapshot
    counters.observe("outbox.pending", float(snapshot.pending))
    counters.observe("outbox.oldest_age_seconds", float(snapshot.age_seconds))
    counters.observe("outbox.admission_cache_age_ms", (now - snapshot.at) * 1000)
    projected = snapshot.pending + max(0, int(incoming))
    if projected > settings.realtime_outbox_max_pending or \
            snapshot.age_seconds > settings.realtime_outbox_max_age_seconds:
        counters.incr("outbox.admission_rejected")
        raise OutboxAdmissionError(
            "backlog", pending=projected, age_seconds=snapshot.age_seconds,
            retry_after=settings.realtime_outbox_retry_after_seconds,
        )
