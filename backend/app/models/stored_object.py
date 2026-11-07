"""Object registry: staged after upload, committed after a business reference.

A physical object and a database transaction cannot commit across systems, so when
an upload succeeds but registration fails, only the object just created by that
attempt may be deleted as compensation. Once a business record references an
object, its registration state becomes committed; any automatic cleanup may only
process objects with state=staged that a live reference query confirms are unused.
"""

from datetime import datetime
from typing import Any, cast

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlmodel import Field

from app.db.session import Base
from app.db.types import JSONType


class StoredObject(Base, table=True):
    """Registration and reference state for one logical object key; stores no object content, signed URL, or credentials."""

    __tablename__ = cast(Any, "stored_objects")
    __table_args__ = (
        CheckConstraint(
            "state IN ('staged', 'committed', 'deleted')",
            name="state_allowed",
        ),
        CheckConstraint(
            "bucket_role IN ('media', 'evidence')",
            name="bucket_role_allowed",
        ),
        CheckConstraint(
            "(ref_type IS NULL) = (ref_id IS NULL)",
            name="reference_pair",
        ),
        Index("ix_stored_objects_state_created_at", "state", "created_at"),
        Index("ix_stored_objects_ref", "ref_type", "ref_id"),
    )

    key: str = Field(sa_column=Column(String(512), primary_key=True))
    namespace: str = Field(sa_column=Column(String(32), index=True, nullable=False))
    bucket_role: str = Field(sa_column=Column(String(16), nullable=False))
    owner_id: int | None = Field(default=None, sa_column=Column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    ))
    content_type: str = Field(sa_column=Column(String(64), nullable=False))
    size_bytes: int = Field(sa_column=Column(BigInteger, nullable=False))
    # Only non-sensitive metadata (original filename, image type, etc.); never URLs, tokens, or object bodies.
    object_metadata: dict = Field(default_factory=dict, sa_column=Column(JSONType, default=dict, nullable=False))
    state: str = Field(default='staged', sa_column=Column(String(16), default="staged", index=True, nullable=False))
    ref_type: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    ref_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    committed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    deleted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
