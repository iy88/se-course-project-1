"""Immutable declarations for direct image uploads."""
from datetime import datetime
from typing import Any, cast

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, String
from sqlmodel import Field

from app.db.session import Base


class UploadLease(Base, table=True):
    __tablename__ = cast(Any, 'upload_leases')
    __table_args__ = (
        CheckConstraint("state IN ('pending','completed','failed')",name="upload_state_allowed"),
        CheckConstraint("length(sha256) = 64",name="upload_sha256_length"),
    )
    id: str = Field(sa_column=Column(String(32), primary_key=True))
    key: str = Field(sa_column=Column(String(512), nullable=False, unique=True))
    owner_id: int = Field(sa_column=Column(BigInteger, ForeignKey('users.id'), nullable=False, index=True))
    namespace: str = Field(sa_column=Column(String(32), nullable=False))
    filename: str = Field(sa_column=Column(String(255), nullable=False))
    content_type: str = Field(sa_column=Column(String(64), nullable=False))
    size_bytes: int = Field(sa_column=Column(BigInteger, nullable=False))
    sha256: str = Field(sa_column=Column(String(64), nullable=False))
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    state: str = Field(sa_column=Column(String(16), nullable=False))
