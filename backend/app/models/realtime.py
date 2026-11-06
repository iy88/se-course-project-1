"""Durable realtime events, per-user sequence counters and retention watermarks.

The PostgreSQL event table is the source of truth. Redis Streams only accelerate
delivery; losing a stream entry, trimming past a cursor or crashing after XADD
must still be recoverable from this table. ``user_seq`` is allocated from a
per-recipient counter row inside the business transaction, ordered by user ID,
and is never the global ``messages.id`` sequence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlmodel import Field

from app.db.session import Base

JSONType = JSON().with_variant(JSONB, "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class RealtimeEvent(Base, table=True):
    """One durable delivery unit for exactly one recipient user."""

    __tablename__ = cast(Any, "realtime_events")
    __table_args__ = (
        UniqueConstraint("recipient_user_id", "user_seq", name="uq_realtime_events_recipient_seq"),
        Index("ix_realtime_events_recipient_seq", "recipient_user_id", "user_seq"),
        Index("ix_realtime_events_pending", "delivered_at", "next_retry_at"),
        Index("ix_realtime_events_created_at", "created_at"),
        Index("ix_realtime_events_lease", "lease_expires_at"),
        Index("ix_realtime_events_dead", "dead_at"),
    )

    event_id: str = Field(default_factory=lambda: str(uuid4()), sa_column=Column(String(36), primary_key=True, nullable=False))
    recipient_user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    user_seq: int = Field(sa_column=Column(BigInteger, nullable=False))
    event_type: str = Field(sa_column=Column(String(64), nullable=False))
    entity_type: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    entity_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    version: int = Field(default=1, sa_column=Column(Integer, nullable=False, default=1, server_default="1"))
    payload: dict = Field(default_factory=dict, sa_column=Column(JSONType, nullable=False, default=dict))
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    ))

    # Delivery is at-least-once. A worker claims with a short lease, publishes,
    # then conditionally confirms in another short transaction.
    delivered_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    lease_owner: str | None = Field(default=None, sa_column=Column(String(96), nullable=True))
    lease_expires_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    attempts: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0, server_default="0"))
    next_retry_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    # Terminal failure is recorded here after the bounded attempt ceiling. The
    # claim scan excludes it; manual recovery clears it (realtime-retry).
    dead_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    # Only the stable exception category is stored; no payload or connection data.
    last_error: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))


class UserEventCounter(Base, table=True):
    """Per-recipient committed high watermark used to allocate ``user_seq``."""

    __tablename__ = cast(Any, "user_event_counters")

    user_id: int = Field(sa_column=Column(BigInteger, primary_key=True, nullable=False))
    last_seq: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, default=0, server_default="0"))
    updated_at: datetime = Field(default_factory=utcnow, sa_column=Column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now(), onupdate=func.now()
    ))


class RealtimeRetention(Base, table=True):
    """Lowest sequence still replayable for a recipient; ``low_seq`` is inclusive."""

    __tablename__ = cast(Any, "realtime_retention")

    user_id: int = Field(sa_column=Column(BigInteger, primary_key=True, nullable=False))
    low_seq: int = Field(default=1, sa_column=Column(BigInteger, nullable=False, default=1, server_default="1"))
    high_seq: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, default=0, server_default="0"))
    updated_at: datetime = Field(default_factory=utcnow, sa_column=Column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now(), onupdate=func.now()
    ))


class IdempotencyRecord(Base, table=True):
    """Optional request idempotency result committed with the business write."""

    __tablename__ = cast(Any, "idempotency_records")
    __table_args__ = (
        UniqueConstraint("user_id", "operation", "key", name="uq_idempotency_scope"),
        Index("ix_idempotency_expires_at", "expires_at"),
    )

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    user_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    operation: str = Field(sa_column=Column(String(64), nullable=False))
    key: str = Field(sa_column=Column(String(128), nullable=False))
    request_hash: str = Field(sa_column=Column(String(64), nullable=False))
    status_code: int = Field(sa_column=Column(Integer, nullable=False))
    response: dict | None = Field(default=None, sa_column=Column(JSONType, nullable=True))
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    ))
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class ServiceHeartbeat(Base, table=True):
    """Per-process readiness/heartbeat row; liveness is process-local."""

    __tablename__ = cast(Any, "service_heartbeats")
    __table_args__ = (Index("ix_service_heartbeats_heartbeat_at", "heartbeat_at"),)

    name: str = Field(sa_column=Column(String(128), primary_key=True, nullable=False))
    role: str = Field(sa_column=Column(String(16), nullable=False))
    instance_id: str = Field(sa_column=Column(String(64), nullable=False))
    release_id: str = Field(default='', sa_column=Column(String(128), nullable=False, default=''))
    protocol_version: int = Field(default=2, sa_column=Column(Integer, nullable=False, default=2))
    status: str = Field(default='starting', sa_column=Column(String(16), nullable=False, default='starting'))
    details: dict = Field(default_factory=dict, sa_column=Column(JSONType, nullable=False, default=dict))
    pid: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    started_at: datetime = Field(default_factory=utcnow, sa_column=Column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    ))
    heartbeat_at: datetime = Field(default_factory=utcnow, sa_column=Column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now(), onupdate=func.now()
    ))
