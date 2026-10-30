"""C-12 举报记录、C-13 处置记录（共享池/沟通单）、C-15 站内通知。"""

from datetime import datetime
from typing import Any, cast

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship

from app.db.session import Base
from app.db.types import JSONType
from app.models.enums import (
    CaseStatus,
    ReportStatus,
)


class Report(Base, table=True):
    """C-12：举报提交内容与进度；结果经管理员确认后匿名公开（BR-25/26）。"""

    __tablename__ = cast(Any, "reports")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    reporter_id: int = Field(sa_column=Column(ForeignKey("users.id"), index=True, nullable=False))
    target_type: str = Field(sa_column=Column(String(16), nullable=False))  # product/comment/message/review/user
    target_id: int = Field(sa_column=Column(BigInteger, index=True, nullable=False))
    reason: str = Field(sa_column=Column(String(500), nullable=False))  # 必填原因
    detail: str | None = Field(default=None, sa_column=Column(Text, nullable=True))  # 补充说明（可选）
    evidence_keys: list = Field(default_factory=list, sa_column=Column(JSONType, default=list, nullable=False))  # 截图等证据（可选）
    status: str = Field(default=ReportStatus.PENDING.value, sa_column=Column(String(16), default=ReportStatus.PENDING.value, index=True, nullable=False))
    # 结果经管理员确认后公开；确认前不可见（BR-25）
    result_confirmed: bool = Field(default=False, sa_column=Column(Boolean, default=False, nullable=False))
    public_result: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))
    result_reason: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))
    closed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    updated_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False))


class ReportSupplement(Base, table=True):
    """同一举报事项的补充说明/证据（结案后归档不再接受，BR-25）。"""

    __tablename__ = cast(Any, "report_supplements")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    report_id: int = Field(sa_column=Column(ForeignKey("reports.id"), index=True, nullable=False))
    author_id: int = Field(sa_column=Column(ForeignKey("users.id"), nullable=False))
    content: str = Field(sa_column=Column(Text, nullable=False))
    evidence_keys: list = Field(default_factory=list, sa_column=Column(JSONType, default=list, nullable=False))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))


class DisposalCase(Base, table=True):
    """C-13：管理事项（商品审核/举报/争议/异常/封禁）的认领、结论与依据。"""

    __tablename__ = cast(Any, "disposal_cases")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    case_type: str = Field(sa_column=Column(String(24), index=True, nullable=False))
    status: str = Field(default=CaseStatus.PENDING.value, sa_column=Column(String(16), default=CaseStatus.PENDING.value, index=True, nullable=False))
    claimed_by_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True, index=True))
    claimed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    product_id: int | None = Field(default=None, sa_column=Column(
        ForeignKey("products.id", use_alter=True, name="fk_disposal_cases_product_id_products"), nullable=True, index=True
    ))
    report_id: int | None = Field(default=None, sa_column=Column(ForeignKey("reports.id"), nullable=True, index=True))
    trade_id: int | None = Field(default=None, sa_column=Column(
        ForeignKey("trades.id", use_alter=True, name="fk_disposal_cases_trade_id_trades"), nullable=True, index=True
    ))
    subject_user_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True, index=True))  # 受审核/被举报/受处置用户

    title: str = Field(sa_column=Column(String(200), nullable=False))  # 展示用摘要
    conclusion: str | None = Field(default=None, sa_column=Column(String(200), nullable=True))  # 处置结论
    conclusion_reason: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))
    basis: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))  # 处置/调整依据
    disposed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))

    messages: list["DisposalMessage"] = Relationship(sa_relationship=relationship(
        back_populates="case", order_by="DisposalMessage.id", lazy="selectin"
    ))


class DisposalMessage(Base, table=True):
    """处置通知与沟通单消息：问询/说明/申辩/回复及留痕，独立于买卖双方 IM（BR-32/33）。"""

    __tablename__ = cast(Any, "disposal_messages")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    case_id: int = Field(sa_column=Column(ForeignKey("disposal_cases.id"), index=True, nullable=False))
    sender_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))
    role: str = Field(sa_column=Column(String(16), nullable=False))  # admin / user / system
    kind: str = Field(sa_column=Column(String(16), nullable=False))  # inquiry / statement / appeal / reply / notice
    content: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))

    case: DisposalCase = Relationship(sa_relationship=relationship(back_populates="messages"))


class Notification(Base, table=True):
    """C-15：站内通知；打开具体通知才已读（4.17）。"""

    __tablename__ = cast(Any, "notifications")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    user_id: int = Field(sa_column=Column(ForeignKey("users.id"), index=True, nullable=False))
    type: str = Field(sa_column=Column(String(32), nullable=False))
    title: str = Field(sa_column=Column(String(200), nullable=False))
    content: str = Field(default='', sa_column=Column(String(500), default="", nullable=False))
    # 关联入口（前端据此跳转）：如 product/trade/conversation/case/report
    link_type: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    link_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    payload: dict = Field(default_factory=dict, sa_column=Column(JSONType, default=dict, nullable=False))
    is_read: bool = Field(default=False, sa_column=Column(Boolean, default=False, index=True, nullable=False))
    read_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
