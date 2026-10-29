"""C-12 举报记录、C-13 处置记录（共享池/沟通单）、C-15 站内通知。"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import (
    CaseStatus,
    ReportStatus,
)


class Report(Base):
    """C-12：举报提交内容与进度；结果经管理员确认后匿名公开（BR-25/26）。"""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(16))  # product/comment/message/review/user
    target_id: Mapped[int] = mapped_column(BigInteger, index=True)
    reason: Mapped[str] = mapped_column(String(500))  # 必填原因
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # 补充说明（可选）
    evidence_keys: Mapped[list] = mapped_column(JSON, default=list)  # 截图等证据（可选）
    status: Mapped[str] = mapped_column(String(16), default=ReportStatus.PENDING.value, index=True)
    # 结果经管理员确认后公开；确认前不可见（BR-25）
    result_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    public_result: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ReportSupplement(Base):
    """同一举报事项的补充说明/证据（结案后归档不再接受，BR-25）。"""

    __tablename__ = "report_supplements"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text)
    evidence_keys: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DisposalCase(Base):
    """C-13：管理事项（商品审核/举报/争议/异常/封禁）的认领、结论与依据。"""

    __tablename__ = "disposal_cases"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    case_type: Mapped[str] = mapped_column(String(24), index=True)
    status: Mapped[str] = mapped_column(String(16), default=CaseStatus.PENDING.value, index=True)
    claimed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    report_id: Mapped[int | None] = mapped_column(ForeignKey("reports.id"), nullable=True, index=True)
    trade_id: Mapped[int | None] = mapped_column(ForeignKey("trades.id"), nullable=True, index=True)
    subject_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)  # 受审核/被举报/受处置用户

    title: Mapped[str] = mapped_column(String(200))  # 展示用摘要
    conclusion: Mapped[str | None] = mapped_column(String(200), nullable=True)  # 处置结论
    conclusion_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    basis: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 处置/调整依据
    disposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    messages: Mapped[list["DisposalMessage"]] = relationship(
        back_populates="case", order_by="DisposalMessage.id", lazy="selectin"
    )


class DisposalMessage(Base):
    """处置通知与沟通单消息：问询/说明/申辩/回复及留痕，独立于买卖双方 IM（BR-32/33）。"""

    __tablename__ = "disposal_messages"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("disposal_cases.id"), index=True)
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(16))  # admin / user / system
    kind: Mapped[str] = mapped_column(String(16))  # inquiry / statement / appeal / reply / notice
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    case: Mapped[DisposalCase] = relationship(back_populates="messages")


class Notification(Base):
    """C-15：站内通知；打开具体通知才已读（4.17）。"""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(String(500), default="")
    # 关联入口（前端据此跳转）：如 product/trade/conversation/case/report
    link_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    link_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
