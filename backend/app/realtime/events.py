"""Transactional event intents, finalized at commit.

``emit_events`` never locks a counter and never touches Redis/socket. It records
an intent on ``Session.info`` for the current transaction. A single class-level
SQLAlchemy ``before_commit`` listener flushes the business rows first, then
locks all independent per-user counter rows in stable user-ID order, allocates
every intent of the whole transaction, inserts durable events and flushes them
before the commit. Thus all business locks are acquired before any counter lock,
and unrelated transactions never contend on a global realtime lock.

The listener is synchronous SQLAlchemy code. AsyncSession.commit runs it in the
greenlet context, so ordinary sync Session/execute calls are valid there. The
same listener applies to production SessionLocal and to tests' own SQLAlchemy
sessions because it is registered once on the ORM Session class, not on a
specific engine.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import event, select, text
from sqlalchemy.orm import Session
from sqlmodel import col, func
from sqlmodel import select as sm_select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings
from app.models.realtime import RealtimeEvent, RealtimeRetention, UserEventCounter
from app.realtime.admission import check_outbox_admission

_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.]{1,63}$")
_ENTITY_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_INTENTS_KEY = "realtime_event_intents"
_FINALIZING_KEY = "realtime_event_finalizing"
_SAVEPOINTS_KEY = "realtime_event_savepoints"


class EventValidationError(ValueError):
    """Payload/event contract violation; callers must roll back the business tx."""


@dataclass
class EventIntent:
    user_id: int
    event_type: str
    payload: dict
    entity_type: str | None = None
    entity_id: str | None = None
    version: int = 1


def event_wire(event: RealtimeEvent) -> dict:
    """Stable WebSocket frame. Legacy callback fields live under ``payload``."""
    return {
        "type": "event",
        "event_id": event.event_id,
        "recipient_user_id": int(event.recipient_user_id),
        "user_seq": int(event.user_seq),
        "event_type": event.event_type,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "version": int(event.version),
        "payload": event.payload or {},
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def validate_payload(event_type: str, payload: dict) -> dict:
    settings = get_settings()
    if not isinstance(payload, dict):
        raise EventValidationError("event payload must be an object")
    if not _EVENT_TYPE_RE.fullmatch(str(event_type)):
        raise EventValidationError("invalid event type")
    try:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    except (TypeError, ValueError):
        raise EventValidationError("event payload is not JSON serializable") from None
    if len(encoded) > settings.realtime_payload_max_bytes:
        raise EventValidationError("event payload exceeds configured limit")
    return payload


def _clear_intents(session: Session) -> None:
    session.info.pop(_INTENTS_KEY, None)
    session.info.pop(_SAVEPOINTS_KEY, None)


def _insert_ignore(session: Session):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert

        return dialect_insert
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert

        return dialect_insert
    raise EventValidationError("unsupported database dialect for realtime counters")


def _ensure_counter(session: Session, user_id: int) -> None:
    insert_stmt = _insert_ignore(session)(UserEventCounter).values(user_id=user_id, last_seq=0)
    session.execute(insert_stmt.on_conflict_do_nothing(index_elements=["user_id"]))


def _ensure_retention(session: Session, user_id: int) -> None:
    insert_stmt = _insert_ignore(session)(RealtimeRetention).values(user_id=user_id, low_seq=1, high_seq=0)
    session.execute(insert_stmt.on_conflict_do_nothing(index_elements=["user_id"]))


def _finalize_events(session: Session) -> None:
    intents: list[EventIntent] = list(session.info.get(_INTENTS_KEY, ()))
    if not intents:
        return
    if session.info.get(_FINALIZING_KEY):
        return
    session.info[_FINALIZING_KEY] = True
    try:
        # Business rows must be flushed before counter locks: callers may have
        # acquired product/trade locks and still have pending writes. The event
        # listener runs before SQLAlchemy's own commit flush.
        session.flush()
        # Admission is evaluated after all business rows/locks and all intents
        # are known, but before any counter/event row is written.
        check_outbox_admission(session, incoming=len(intents))
        by_user: dict[int, list[EventIntent]] = {}
        for intent in intents:
            by_user.setdefault(int(intent.user_id), []).append(intent)
        recipients = sorted(by_user)
        for uid in recipients:
            _ensure_counter(session, uid)
            _ensure_retention(session, uid)
        rows = session.execute(
            select(UserEventCounter)
            .where(col(UserEventCounter.user_id).in_(recipients))
            .order_by(UserEventCounter.user_id)
            .with_for_update()
        ).scalars().all()
        if len(rows) != len(recipients):
            raise EventValidationError("realtime counter initialization race")
        counters = {int(row.user_id): row for row in rows}
        for uid in recipients:
            counter = counters[uid]
            for intent in by_user[uid]:
                counter.last_seq = int(counter.last_seq) + 1
                session.add(RealtimeEvent(
                    recipient_user_id=uid,
                    user_seq=int(counter.last_seq),
                    event_type=intent.event_type,
                    entity_type=intent.entity_type,
                    entity_id=intent.entity_id,
                    version=max(1, int(intent.version)),
                    payload=intent.payload,
                ))
        session.flush()
        # Only clear after the events are flushed. If commit itself later fails,
        # rollback discards both events and intents; a retry must re-emit.
        session.info.pop(_INTENTS_KEY, None)
        session.info.pop(_SAVEPOINTS_KEY, None)
    finally:
        session.info.pop(_FINALIZING_KEY, None)


def _before_commit(session: Session) -> None:
    # A savepoint release is not the business commit. Keep intents and counter
    # locks out of nested commits; only the outer commit finalizes.
    if session.get_nested_transaction() is not None:
        return
    _finalize_events(session)


def _after_transaction_end(session: Session, transaction) -> None:
    # close()/rollback() of an abandoned outer transaction must not leave
    # intents in session.info for the next transaction. Nested savepoints are
    # handled by after_soft_rollback because their committed intents survive.
    if not getattr(transaction, "nested", False) and not session.in_transaction():
        _clear_intents(session)


def _after_transaction_create(session: Session, transaction) -> None:
    if getattr(transaction, "nested", False):
        stack = session.info.setdefault(_SAVEPOINTS_KEY, [])
        stack.append((transaction, list(session.info.get(_INTENTS_KEY, ()))))


def _after_soft_rollback(session: Session, previous_transaction) -> None:
    if not getattr(previous_transaction, "nested", False):
        # A failed flush can roll back SQLAlchemy's internal subtransaction
        # while a user savepoint is still active. That is not an outer business
        # rollback: restore the pre-savepoint snapshot instead of discarding
        # intents that belong to the outer transaction.
        if session.get_nested_transaction() is not None:
            stack = session.info.get(_SAVEPOINTS_KEY, [])
            if stack:
                _transaction, snapshot = stack[-1]
                session.info[_INTENTS_KEY] = list(snapshot)
                return
        _clear_intents(session)
        return
    stack = session.info.get(_SAVEPOINTS_KEY, [])
    for index in range(len(stack) - 1, -1, -1):
        transaction, snapshot = stack[index]
        if transaction is previous_transaction:
            session.info[_INTENTS_KEY] = list(snapshot)
            session.info[_SAVEPOINTS_KEY] = stack[:index]
            return
    # Fallback for driver/version differences: restore the most recent savepoint
    # snapshot rather than leaving intents from a rolled-back savepoint.
    if stack:
        _transaction, snapshot = stack.pop()
        session.info[_INTENTS_KEY] = list(snapshot)


def install_event_listener() -> None:
    if event.contains(Session, "before_commit", _before_commit):
        return
    event.listen(Session, "before_commit", _before_commit)
    event.listen(Session, "after_transaction_create", _after_transaction_create)
    event.listen(Session, "after_transaction_end", _after_transaction_end)
    event.listen(Session, "after_soft_rollback", _after_soft_rollback)


async def emit_event_intents(db: AsyncSession, *, event_type: str, intents: Iterable[tuple[int, dict, str | None, str | None, int]]) -> list[EventIntent]:
    """Queue per-recipient intents in the current transaction (no DB I/O)."""
    created: list[EventIntent] = []
    if not db.in_transaction():
        # Start only the logical transaction: rollback/close needs its lifecycle
        # events, but recording an intent must not force a physical checkout.
        await db.begin()
    queued: list[EventIntent] = list(db.sync_session.info.get(_INTENTS_KEY, ()))
    for user_id, payload, entity_type, entity_id, version in intents:
        uid = int(user_id)
        if uid <= 0:
            continue
        if entity_type is not None and not _ENTITY_TYPE_RE.fullmatch(entity_type):
            raise EventValidationError("invalid entity type")
        validated = validate_payload(event_type, payload)
        intent = EventIntent(
            user_id=uid,
            event_type=event_type,
            payload=validated,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            version=max(1, int(version)),
        )
        queued.append(intent)
        created.append(intent)
    db.sync_session.info[_INTENTS_KEY] = queued
    return created


async def emit_events(
    db: AsyncSession,
    recipients: Iterable[int],
    *,
    event_type: str,
    payload: dict,
    entity_type: str | None = None,
    entity_id: int | str | None = None,
    version: int = 1,
) -> list[EventIntent]:
    """Record intents for many recipients sharing one payload. Commit finalizes."""
    users = sorted({int(uid) for uid in recipients if uid is not None and int(uid) > 0})
    if not users:
        return []
    validated = validate_payload(event_type, payload)
    return await emit_event_intents(
        db,
        event_type=event_type,
        intents=[(uid, validated, entity_type, str(entity_id) if entity_id is not None else None, version)
                 for uid in users],
    )


async def high_watermark(db: AsyncSession, user_id: int) -> int:
    value = (
        await db.exec(sm_select(UserEventCounter.last_seq).where(UserEventCounter.user_id == user_id))
    ).first()
    return int(value or 0)


async def low_watermark(db: AsyncSession, user_id: int) -> int:
    value = (
        await db.exec(sm_select(RealtimeRetention.low_seq).where(RealtimeRetention.user_id == user_id))
    ).first()
    return int(value or 1)


async def replay_events(
    db: AsyncSession,
    user_id: int,
    *,
    after_seq: int,
    upto_seq: int | None = None,
    limit: int | None = None,
) -> list[RealtimeEvent]:
    """Ordered, paginated replay for one authorized recipient."""
    settings = get_settings()
    ceiling = upto_seq if upto_seq is not None else await high_watermark(db, user_id)
    page = limit or settings.realtime_replay_batch_size
    if ceiling <= after_seq or page <= 0:
        return []
    rows = (
        await db.exec(
            sm_select(RealtimeEvent)
            .where(
                RealtimeEvent.recipient_user_id == user_id,
                RealtimeEvent.user_seq > max(0, after_seq),
                RealtimeEvent.user_seq <= ceiling,
            )
            .order_by(RealtimeEvent.user_seq)
            .limit(min(page, settings.realtime_replay_max_events))
        )
    ).all()
    return list(rows)


async def pending_stats(db: AsyncSession) -> dict[str, int]:
    now = datetime.now(UTC)
    pending = (
        await db.exec(sm_select(func.count()).select_from(RealtimeEvent).where(RealtimeEvent.delivered_at.is_(None)))
    ).first() or 0
    oldest = (
        await db.exec(sm_select(func.min(RealtimeEvent.created_at)).where(RealtimeEvent.delivered_at.is_(None)))
    ).first()
    if oldest is not None and oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=UTC)
    age = int((now - oldest).total_seconds()) if oldest else 0
    return {"pending": int(pending), "oldest_age_seconds": max(0, age)}


async def advance_retention(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Delete only each user's expired, delivered, contiguous prefix.

    A delivered event behind an undelivered/leased event is retained: low_seq
    never moves past a sequence still needed for ordered replay. Cleanup is
    serialized with a transaction advisory lock, and the low watermark is
    monotonic.
    """
    from datetime import timedelta

    settings = get_settings()
    cutoff = (now or datetime.now(UTC)) - timedelta(hours=settings.realtime_event_retention_hours)
    dialect = db.bind.dialect.name if db.bind is not None else ""
    if dialect == "postgresql":
        await db.exec(text("SELECT pg_advisory_xact_lock(hashtextextended('realtime:retention', 0))"))

    users = [
        int(uid) for uid in (
            await db.exec(
                sm_select(RealtimeEvent.recipient_user_id)
                .where(
                    RealtimeEvent.delivered_at.is_not(None),
                    RealtimeEvent.created_at < cutoff,
                )
                .distinct()
                .order_by(RealtimeEvent.recipient_user_id)
            )
        ).all()
    ]
    deleted_total = 0
    for uid in users:
        retention = await db.get(RealtimeRetention, uid, with_for_update=True)
        if retention is None:
            continue
        low = max(1, int(retention.low_seq))
        high = await high_watermark(db, uid)
        events = (await db.exec(
            sm_select(RealtimeEvent)
            .where(
                RealtimeEvent.recipient_user_id == uid,
                RealtimeEvent.user_seq >= low,
            )
            .order_by(RealtimeEvent.user_seq)
            .limit(settings.realtime_replay_max_events)
        )).all()
        next_low = low
        deleted: list[RealtimeEvent] = []
        for row in events:
            seq = int(row.user_seq)
            if seq < next_low:
                continue
            next_low = max(next_low, seq)
            delivered = row.delivered_at is not None
            created = row.created_at
            if created is not None and created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if not delivered or created is None or created >= cutoff:
                break
            deleted.append(row)
            next_low = seq + 1
        if not events:
            next_low = max(low, high + 1)
        for row in deleted:
            await db.delete(row)
        if deleted:
            await db.flush()
            deleted_total += len(deleted)
        retention.low_seq = max(int(retention.low_seq), next_low)
        retention.high_seq = high
        retention.updated_at = datetime.now(UTC)
        db.add(retention)
    await db.flush()
    return deleted_total


install_event_listener()
