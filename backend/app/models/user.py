"""C-01 user accounts and C-14 account restriction records."""

from datetime import datetime
from typing import Any, cast

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship

from app.db.session import Base
from app.models.enums import RestrictionStatus, RestrictionType


class User(Base, table=True):
    __tablename__ = cast(Any, "users")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    email: str = Field(sa_column=Column(String(254), unique=True, index=True, nullable=False))  # login identifier, unique platform-wide (BR-20/21)
    password_hash: str = Field(sa_column=Column(String(128), nullable=False))
    display_name: str = Field(sa_column=Column(Text, nullable=False))
    avatar_key: str | None = Field(default=None, sa_column=Column(String(512), nullable=True))
    avatar_pending_key: str | None = Field(default=None, sa_column=Column(String(512), nullable=True))
    avatar_review_status: str | None = Field(default=None, sa_column=Column(String(16), nullable=True))
    avatar_review_reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    role: str = Field(default='user', sa_column=Column(String(16), default="user", nullable=False))  # user / admin
    status: str = Field(default='normal', sa_column=Column(String(16), default="normal", index=True, nullable=False))  # normal / banned
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))

    restrictions: list["AccountRestriction"] = Relationship(sa_relationship=relationship(
        back_populates="user", foreign_keys="AccountRestriction.user_id"
    ))


class AccountRestriction(Base, table=True):
    """C-14: ban records (actor, reason, activation, and lifting). Trade freezing is not stored in this table (BR-33)."""

    __tablename__ = cast(Any, "account_restrictions")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    user_id: int = Field(sa_column=Column(ForeignKey("users.id"), index=True, nullable=False))
    type: str = Field(default=RestrictionType.BAN.value, sa_column=Column(String(16), default=RestrictionType.BAN.value, nullable=False))
    status: str = Field(default=RestrictionStatus.ACTIVE.value, sa_column=Column(String(16), default=RestrictionStatus.ACTIVE.value, index=True, nullable=False))
    reason: str = Field(sa_column=Column(Text, nullable=False))
    basis: str | None = Field(default=None, sa_column=Column(Text, nullable=True))  # related disposal basis
    case_id: int | None = Field(default=None, sa_column=Column(ForeignKey("disposal_cases.id"), nullable=True))
    created_by_id: int = Field(sa_column=Column(ForeignKey("users.id"), nullable=False))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    lifted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    lifted_by_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))
    lift_reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True))

    user: User = Relationship(sa_relationship=relationship(back_populates="restrictions", foreign_keys="AccountRestriction.user_id"))
