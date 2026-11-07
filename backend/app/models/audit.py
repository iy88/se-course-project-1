"""P3 login and change audit: an independent, append-only event table (fixed name audit_events).

Successful business changes and their audit rows are committed by the caller in the
same SQLAlchemy transaction; this model exposes no update/delete entry points.
Table-level SELECT/INSERT grants and revoked UPDATE/DELETE/TRUNCATE are handled by migrations.
"""

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlmodel import Field

from app.db.session import Base


class AuditEvent(Base, table=True):
    """Audit event: the field set is a stable contract; before/after values contain only the necessary redacted fields."""

    __tablename__ = cast(Any, "audit_events")
    __table_args__ = (
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_event_type", "event_type"),
        Index("ix_audit_events_actor_id", "actor_id"),
        Index("ix_audit_events_request_id", "request_id"),
        Index("ix_audit_events_target", "target_type", "target_id"),
    )

    event_id: int = Field(default=None, sa_column=Column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    ))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_column=Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    ))
    request_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    actor_id: int | None = Field(default=None, sa_column=Column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=True
    ))
    actor_role: str = Field(default='user', sa_column=Column(String(16), nullable=False, default="user", server_default="user"))
    event_type: str = Field(sa_column=Column(String(64), nullable=False))
    target_type: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    target_id: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    result: str = Field(default='success', sa_column=Column(String(16), nullable=False, default="success", server_default="success"))
    reason_code: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    before_json: dict | None = Field(default=None, sa_column=Column(JSON().with_variant(JSONB, "postgresql"), nullable=True))
    after_json: dict | None = Field(default=None, sa_column=Column(JSON().with_variant(JSONB, "postgresql"), nullable=True))
    ip: str | None = Field(default=None, sa_column=Column(String(45), nullable=True))
    user_agent: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
