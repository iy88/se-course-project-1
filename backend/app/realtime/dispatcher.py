"""Bounded outbox domain service (claim -> publish -> confirm).

This module no longer owns a permanent ``run()`` loop, polling sleeps or a
hand-written exponential backoff scheduler. Taskiq (the official
``RedisStreamBroker`` plus ``SmartRetryMiddleware``) owns task consumption,
acknowledgement, retry timing and concurrency; the periodic Taskiq sweep is the
durability backstop for a lost/crashed task. ``next_retry_at`` is kept for schema
and manual recovery compatibility but is not read by claim, so framework retries
and the old DB delay scheduler cannot double-schedule the same event.

A claim is committed before any Redis I/O, so a slow/failed Redis never holds a
PostgreSQL transaction or row lock. Publication is at-least-once: a crash after
XADD but before confirm causes a duplicate after lease takeover; clients dedupe
by ``event_id`` and only advance their contiguous ``user_seq`` cursor after
applying business effects.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, update
from sqlmodel import col, select

from app.core.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.models.realtime import RealtimeEvent
from app.observability import counters
from app.realtime.events import advance_retention, event_wire
from app.realtime.stream import RealtimeStream, StreamError, get_realtime_stream

logger = logging.getLogger(__name__)


class OutboxPublishError(RuntimeError):
    """Retryable framework-visible publication failure (stable category only)."""

    def __init__(self, category: str) -> None:
        super().__init__(f"outbox publish failed: {category}")
        self.category = category


class ClaimedEvent:
    __slots__ = ("attempts", "event_id", "frame", "user_id", "user_seq")

    def __init__(self, event_id: str, user_id: int, user_seq: int, frame: dict, attempts: int) -> None:
        self.event_id = event_id
        self.user_id = user_id
        self.user_seq = user_seq
        self.frame = frame
        self.attempts = attempts


class OutboxService:
    """Finite-batch domain service. Taskiq invokes ``run_bounded``."""

    def __init__(self, settings: Settings | None = None, *, stream: RealtimeStream | None = None) -> None:
        self.settings = settings or get_settings()
        self.worker_id = f"taskiq:{uuid.uuid4().hex[:16]}"
        self._injected_stream = stream
        self._last_error: str | None = None
        self._last_error_at = 0.0

    @property
    def stream(self) -> RealtimeStream | None:
        if self._injected_stream is not None:
            return self._injected_stream
        if not self.settings.redis_url.strip():
            return None
        return get_realtime_stream(self.settings)

    async def _claim(self) -> list[ClaimedEvent]:
        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=self.settings.outbox_lease_seconds)
        async with get_sessionmaker()() as db, db.begin():
            rows = (
                await db.exec(
                    select(RealtimeEvent)
                    .where(
                        RealtimeEvent.delivered_at.is_(None),
                        RealtimeEvent.dead_at.is_(None),
                        or_(RealtimeEvent.lease_expires_at.is_(None),
                            RealtimeEvent.lease_expires_at < now),
                    )
                    .order_by(RealtimeEvent.created_at, RealtimeEvent.event_id)
                    .limit(self.settings.outbox_batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            claimed: list[ClaimedEvent] = []
            for row in rows:
                row.lease_owner = self.worker_id
                row.lease_expires_at = lease_until
                row.attempts = int(row.attempts) + 1
                db.add(row)
                # Copy everything needed for Redis before the session closes.
                claimed.append(ClaimedEvent(
                    event_id=row.event_id,
                    user_id=int(row.recipient_user_id),
                    user_seq=int(row.user_seq),
                    frame=event_wire(row),
                    attempts=int(row.attempts),
                ))
            await db.flush()
        counters.observe("outbox.claimed", float(len(claimed)))
        return claimed

    async def _confirm(self, events: list[ClaimedEvent]) -> None:
        if not events:
            return
        now = datetime.now(UTC)
        async with get_sessionmaker()() as db, db.begin():
            await db.execute(
                update(RealtimeEvent)
                .where(
                    col(RealtimeEvent.event_id).in_([event.event_id for event in events]),
                    RealtimeEvent.lease_owner == self.worker_id,
                )
                .values(delivered_at=now, lease_owner=None, lease_expires_at=None, next_retry_at=None)
            )

    async def _fail(self, events: list[ClaimedEvent], category: str) -> list[ClaimedEvent]:
        """Release the lease; mark the bounded attempt ceiling as terminal.

        No ``next_retry_at`` is written: Taskiq owns retry delay and the periodic
        sweep claims lease-expired rows. Returned events are not terminal and
        require a framework retry.
        """
        if not events:
            return []
        try:
            return await self._fail_tx(events, category)
        except Exception as exc:  # noqa: BLE001 - task framework must see the failure
            self._last_error = type(exc).__name__
            self._last_error_at = time.monotonic()
            logger.warning("outbox retry write failed: %s", type(exc).__name__)
            return list(events)

    async def _fail_tx(self, events: list[ClaimedEvent], category: str) -> list[ClaimedEvent]:
        now = datetime.now(UTC)
        retryable: list[ClaimedEvent] = []
        async with get_sessionmaker()() as db, db.begin():
            for event in events:
                terminal = int(event.attempts) >= self.settings.outbox_max_attempts
                if not terminal:
                    retryable.append(event)
                await db.execute(
                    update(RealtimeEvent)
                    .where(
                        RealtimeEvent.event_id == event.event_id,
                        RealtimeEvent.lease_owner == self.worker_id,
                    )
                    .values(
                        lease_owner=None,
                        lease_expires_at=None,
                        last_error=category[:64],
                        dead_at=now if terminal else None,
                    )
                )
        counters.incr("outbox.failed")
        if len(retryable) != len(events):
            counters.incr("outbox.dead", float(len(events) - len(retryable)))
        return retryable

    async def _publish(self, events: list[ClaimedEvent]) -> None:
        stream = self.stream
        if stream is None:
            # No Redis acceleration (offline/combined dev). PostgreSQL
            # reconciliation in the gateway still delivers; marking delivered
            # keeps the outbox bounded and events remain replayable.
            return
        for event in events:
            await stream.publish(event.frame, event_id=event.event_id, user_id=event.user_id, user_seq=event.user_seq)
            counters.incr("outbox.published")

    async def dispatch_batch(self) -> int:
        """Claim and publish at most one bounded batch. Raises on retryable error."""
        try:
            events = await self._claim()
        except Exception:
            counters.incr("outbox.claim_errors")
            raise
        if not events:
            return 0
        try:
            await self._publish(events)
        except StreamError as exc:
            self._last_error, self._last_error_at = exc.category, time.monotonic()
            retryable = await self._fail(events, exc.category)
            if retryable:
                raise OutboxPublishError(exc.category) from None
            return 0
        except Exception as exc:  # noqa: BLE001 - stable category only
            category = type(exc).__name__[:64]
            self._last_error, self._last_error_at = category, time.monotonic()
            retryable = await self._fail(events, category)
            if retryable:
                raise OutboxPublishError(category) from None
            return 0
        try:
            await self._confirm(events)
        except Exception as exc:  # noqa: BLE001 - lease takeover will repeat publish
            logger.warning("outbox confirm failed: %s", type(exc).__name__)
            counters.incr("outbox.confirm_errors")
            raise OutboxPublishError(type(exc).__name__[:64]) from None
        if events:
            oldest = min(
                (datetime.fromisoformat(event.frame["created_at"]) for event in events
                 if event.frame.get("created_at")),
                default=datetime.now(UTC),
            )
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=UTC)
            counters.observe("outbox.age_seconds", max(0.0, (datetime.now(UTC) - oldest).total_seconds()))
        self._last_error = None
        return len(events)

    async def run_bounded(self) -> dict[str, int]:
        """Run a finite number of batches within a finite time budget."""
        started = time.monotonic()
        batches = 0
        published = 0
        for _ in range(self.settings.outbox_max_batches_per_run):
            if time.monotonic() - started >= self.settings.outbox_run_time_budget_seconds:
                break
            published += await self.dispatch_batch()
            batches += 1
        return {"batches": batches, "published": published}

    async def run_once(self) -> int:
        """Compatibility alias for one bounded batch (tests/legacy callers)."""
        return await self.dispatch_batch()

    async def cleanup_retention(self) -> int:
        async with get_sessionmaker()() as db, db.begin():
            deleted = await advance_retention(db)
        if deleted:
            counters.incr("outbox.retention_deleted", float(deleted))
        return int(deleted)

    async def cleanup_idempotency(self) -> int:
        """Delete expired idempotency records in bounded batches."""
        from app.api.idempotency import cleanup_expired

        return await cleanup_expired(self.settings.idempotency_cleanup_batch_size)


# Backwards-compatible import name for call sites/tests that still refer to the
# dispatcher; it is now a bounded domain service, not a loop owner.
OutboxDispatcher = OutboxService


class HeartbeatLoop:
    """Periodic SQL heartbeat for roles that do not own a Taskiq middleware."""

    def __init__(self, settings: Settings, *, name: str, details: dict | None = None) -> None:
        self.settings = settings
        self.name = name
        self.details = details or {}
        self._stop = asyncio.Event()

    async def run(self) -> None:
        from app.realtime.heartbeat import beat

        started = datetime.now(UTC)
        while not self._stop.is_set():
            try:
                async with get_sessionmaker()() as db, db.begin():
                    await beat(db, self.settings, name=self.name, details=self.details, started_at=started)
            except Exception as exc:  # noqa: BLE001
                logger.warning("heartbeat failed: %s", type(exc).__name__)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=5)
            except TimeoutError:
                pass
        with contextlib.suppress(Exception):
            async with get_sessionmaker()() as db, db.begin():
                await beat(db, self.settings, name=self.name, status="stopping", details=self.details,
                           started_at=started)

    def stop(self) -> None:
        self._stop.set()
