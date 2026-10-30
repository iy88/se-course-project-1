"""C-01 用户账户 与 C-14 账户限制记录。"""

from datetime import datetime
from typing import Any, cast

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship

from app.db.session import Base
from app.models.enums import RestrictionStatus, RestrictionType


class User(Base, table=True):
    __tablename__ = cast(Any, "users")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    email: str = Field(sa_column=Column(String(254), unique=True, index=True, nullable=False))  # 登录标识，全平台唯一（BR-20/21）
    password_hash: str = Field(sa_column=Column(String(128), nullable=False))
    display_name: str = Field(sa_column=Column(String(64), nullable=False))
    role: str = Field(default='user', sa_column=Column(String(16), default="user", nullable=False))  # user / admin
    status: str = Field(default='normal', sa_column=Column(String(16), default="normal", index=True, nullable=False))  # normal / banned
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))

    restrictions: list["AccountRestriction"] = Relationship(sa_relationship=relationship(
        back_populates="user", foreign_keys="AccountRestriction.user_id"
    ))


class AccountRestriction(Base, table=True):
    """C-14：封禁记录（执行者、理由、生效与解除）。交易冻结不入本表（BR-33）。"""

    __tablename__ = cast(Any, "account_restrictions")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    user_id: int = Field(sa_column=Column(ForeignKey("users.id"), index=True, nullable=False))
    type: str = Field(default=RestrictionType.BAN.value, sa_column=Column(String(16), default=RestrictionType.BAN.value, nullable=False))
    status: str = Field(default=RestrictionStatus.ACTIVE.value, sa_column=Column(String(16), default=RestrictionStatus.ACTIVE.value, index=True, nullable=False))
    reason: str = Field(sa_column=Column(String(500), nullable=False))
    basis: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))  # 关联处置依据
    case_id: int | None = Field(default=None, sa_column=Column(ForeignKey("disposal_cases.id"), nullable=True))
    created_by_id: int = Field(sa_column=Column(ForeignKey("users.id"), nullable=False))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    lifted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    lifted_by_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))
    lift_reason: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))

    user: User = Relationship(sa_relationship=relationship(back_populates="restrictions", foreign_keys="AccountRestriction.user_id"))
