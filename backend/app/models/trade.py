"""C-09 交易记录（请求与交易同对象）、约定、状态转移历史、C-10 完成确认、C-11 评价。"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import AgreementStatus, TradeStatus


class Trade(Base):
    """一笔对象承载购买请求与卖方接受后的交易（BR-01；第 3 章 C-09）。"""

    __tablename__ = "trades"
    __table_args__ = (
        # 同一商品同时至多一笔进行中/仍锁单交易（BR-03）
        Index(
            "uq_product_locking_trade",
            "product_id",
            unique=True,
            sqlite_where=text("status IN ('in_progress','disputed','abnormal')"),
        ),
        # 同一买方对同一商品至多一条有效待接受请求（BR-02）
        Index(
            "uq_buyer_pending_request",
            "product_id",
            "buyer_id",
            unique=True,
            sqlite_where=text("status = 'pending_acceptance'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default=TradeStatus.PENDING_ACCEPTANCE.value, index=True)
    request_note: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 请求留言（可选）
    close_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)  # 拒绝/撤回/关闭原因

    product_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 接受时的商品交易时内容（BR-30）

    # 约定阶段：进行中无有效约定=约定待双方确认；有=约定已确认待完成（4.15）
    current_agreement_id: Mapped[int | None] = mapped_column(ForeignKey("trade_agreements.id"), nullable=True)

    # 单方确认进度与 7 天等待计时（BR-05）；争议/恢复时清空
    confirm_wait_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # D-51：冻结时暂停原等待；暂停时刻与剩余秒数单独保存，解冻后按剩余续算
    confirm_wait_paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirm_wait_remaining_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 取消申请（BR-06：约定前卖方取消须买方同意；约定后双方同意）
    cancel_requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 争议解决确认（BR-07：双方均确认解决可恢复；管理员解决限认领事项）
    resolution_confirmed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolution_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 冻结：管理处置导致的进度暂停标记（BR-33），与生命周期状态分开
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    frozen_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frozen_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    frozen_case_id: Mapped[int | None] = mapped_column(ForeignKey("disposal_cases.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 完成/终止时间

    agreements: Mapped[list["TradeAgreement"]] = relationship(
        back_populates="trade", foreign_keys="TradeAgreement.trade_id", order_by="TradeAgreement.id"
    )
    transitions: Mapped[list["TradeTransition"]] = relationship(back_populates="trade", order_by="TradeTransition.id")
    confirmations: Mapped[list["CompletionConfirmation"]] = relationship(back_populates="trade")


class TradeAgreement(Base):
    """交易约定：交付时间/文字地点/方式 + 约定金额/支付方式/支付时点（4.15）。"""

    __tablename__ = "trade_agreements"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"), index=True)
    round_no: Mapped[int] = mapped_column(default=1)  # 首次=1；每次变更递增
    proposer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    delivery_time: Mapped[str] = mapped_column(String(200))
    delivery_location: Mapped[str] = mapped_column(String(200))  # 文字地点
    delivery_method: Mapped[str] = mapped_column(String(200))
    amount_cents: Mapped[int] = mapped_column(BigInteger)  # 约定金额（分），可不同于标价
    payment_method: Mapped[str] = mapped_column(String(100))
    payment_timing: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default=AgreementStatus.PROPOSED.value)
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    trade: Mapped[Trade] = relationship(back_populates="agreements", foreign_keys=[trade_id])


class TradeTransition(Base):
    """状态转移历史：前后状态、主体、时间、触发、原因及依据（BR-08、6.5）。"""

    __tablename__ = "trade_transitions"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # 系统触发为空
    actor_role: Mapped[str] = mapped_column(String(16), default="system")  # buyer/seller/admin/system
    trigger: Mapped[str] = mapped_column(String(64))  # 事件标识
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    basis_case_id: Mapped[int | None] = mapped_column(ForeignKey("disposal_cases.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trade: Mapped[Trade] = relationship(back_populates="transitions")


class CompletionConfirmation(Base):
    """C-10：双方各自一次完成确认（交付+支付统一声明）；当前有效与历史分开（BR-28/29）。"""

    __tablename__ = "completion_confirmations"
    __table_args__ = (
        Index(
            "uq_current_confirm",
            "trade_id",
            "confirmer_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"), index=True)
    confirmer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 可选说明
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trade: Mapped[Trade] = relationship(back_populates="confirmations")


class TradeReview(Base):
    """C-11：已完成交易的双方互评，每方每笔一条；仅本人按发表/收到查看（BR-24）。"""

    __tablename__ = "trade_reviews"
    __table_args__ = (UniqueConstraint("trade_id", "reviewer_id"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"), index=True)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reviewee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    rating: Mapped[int] = mapped_column()  # 1—5
    content: Mapped[str] = mapped_column(Text, default="")
    # 管理员处理违规评价：逻辑删除并留理由（BR-24）
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    delete_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
