"""C-01 用户账户 与 C-14 账户限制记录。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import RestrictionStatus, RestrictionType


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)  # 登录标识，全平台唯一（BR-20/21）
    password_hash: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16), default="user")  # user / admin
    status: Mapped[str] = mapped_column(String(16), default="normal", index=True)  # normal / banned
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    restrictions: Mapped[list["AccountRestriction"]] = relationship(
        back_populates="user", foreign_keys="AccountRestriction.user_id"
    )


class AccountRestriction(Base):
    """C-14：封禁记录（执行者、理由、生效与解除）。交易冻结不入本表（BR-33）。"""

    __tablename__ = "account_restrictions"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(16), default=RestrictionType.BAN.value)
    status: Mapped[str] = mapped_column(String(16), default=RestrictionStatus.ACTIVE.value, index=True)
    reason: Mapped[str] = mapped_column(String(500))
    basis: Mapped[str | None] = mapped_column(String(500))  # 关联处置依据
    case_id: Mapped[int | None] = mapped_column(ForeignKey("disposal_cases.id"), nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lifted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    lift_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user: Mapped[User] = relationship(back_populates="restrictions", foreign_keys=[user_id])
