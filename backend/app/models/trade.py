"""C-09 交易记录（请求与交易同对象）、约定、状态转移历史、C-10 完成确认、C-11 评价。"""

from datetime import datetime
from typing import Any, cast

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
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
from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship

from app.db.session import Base
from app.db.types import JSONType
from app.models.enums import AgreementStatus, TradeStatus


class Trade(Base, table=True):
    """一笔对象承载购买请求与卖方接受后的交易（BR-01；第 3 章 C-09）。"""

    __tablename__ = cast(Any, "trades")
    __table_args__ = (
        # 同一商品同时至多一笔进行中/仍锁单交易（BR-03）
        Index(
            "uq_product_locking_trade",
            "product_id",
            unique=True,
            sqlite_where=text("status IN ('in_progress','disputed','abnormal')"),
            postgresql_where=text("status IN ('in_progress','disputed','abnormal')"),
        ),
        # 同一买方对同一商品至多一条有效待接受请求（BR-02）
        Index(
            "uq_buyer_pending_request",
            "product_id",
            "buyer_id",
            unique=True,
            sqlite_where=text("status = 'pending_acceptance'"),
            postgresql_where=text("status = 'pending_acceptance'"),
        ),
    )

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    product_id: int = Field(sa_column=Column(ForeignKey("products.id"), index=True, nullable=False))
    buyer_id: int = Field(sa_column=Column(ForeignKey("users.id"), index=True, nullable=False))
    seller_id: int = Field(sa_column=Column(ForeignKey("users.id"), index=True, nullable=False))
    status: str = Field(default=TradeStatus.PENDING_ACCEPTANCE.value, sa_column=Column(String(24), default=TradeStatus.PENDING_ACCEPTANCE.value, index=True, nullable=False))
    request_note: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))  # 请求留言（可选）
    close_reason: str | None = Field(default=None, sa_column=Column(String(200), nullable=True))  # 拒绝/撤回/关闭原因

    product_snapshot_json: dict | None = Field(default=None, sa_column=Column(JSONType, nullable=True))  # 接受时的商品交易时内容（BR-30）

    # 约定阶段：进行中无有效约定=约定待双方确认；有=约定已确认待完成（4.15）
    current_agreement_id: int | None = Field(default=None, sa_column=Column(
        ForeignKey("trade_agreements.id", use_alter=True, name="fk_trades_current_agreement_id_trade_agreements"),
        nullable=True,
    ))

    # 单方确认进度与 7 天等待计时（BR-05）；争议/恢复时清空
    confirm_wait_started_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    # D-51：冻结时暂停原等待；暂停时刻与剩余秒数单独保存，解冻后按剩余续算
    confirm_wait_paused_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    confirm_wait_remaining_seconds: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))

    # 取消申请（BR-06：约定前卖方取消须买方同意；约定后双方同意）
    cancel_requested_by_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))
    cancel_requested_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    # 争议解决确认（BR-07：双方均确认解决可恢复；管理员解决限认领事项）
    resolution_confirmed_by_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))
    resolution_confirmed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    # 冻结：管理处置导致的进度暂停标记（BR-33），与生命周期状态分开
    frozen: bool = Field(default=False, sa_column=Column(Boolean, default=False, nullable=False))
    frozen_reason: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))
    frozen_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    frozen_by_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))
    frozen_case_id: int | None = Field(default=None, sa_column=Column(
        ForeignKey("disposal_cases.id", use_alter=True, name="fk_trades_frozen_case_id_disposal_cases"), nullable=True
    ))

    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    accepted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    finished_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))  # 完成/终止时间

    agreements: list["TradeAgreement"] = Relationship(sa_relationship=relationship(
        back_populates="trade", foreign_keys="TradeAgreement.trade_id", order_by="TradeAgreement.id"
    ))
    transitions: list["TradeTransition"] = Relationship(sa_relationship=relationship(back_populates="trade", order_by="TradeTransition.id"))
    confirmations: list["CompletionConfirmation"] = Relationship(sa_relationship=relationship(back_populates="trade"))


class TradeAgreement(Base, table=True):
    """交易约定：交付时间/文字地点/方式 + 约定金额/支付方式/支付时点（4.15）。"""

    __tablename__ = cast(Any, "trade_agreements")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    trade_id: int = Field(sa_column=Column(
        ForeignKey("trades.id", use_alter=True, name="fk_trade_agreements_trade_id_trades"), index=True
    , nullable=False))
    round_no: int = Field(default=1, sa_column=Column(Integer, default=1, nullable=False))  # 首次=1；每次变更递增
    proposer_id: int = Field(sa_column=Column(ForeignKey("users.id"), nullable=False))
    delivery_time: str = Field(sa_column=Column(String(200), nullable=False))
    delivery_location: str = Field(sa_column=Column(String(200), nullable=False))  # 文字地点
    delivery_method: str = Field(sa_column=Column(String(200), nullable=False))
    amount_cents: int = Field(sa_column=Column(BigInteger, nullable=False))  # 约定金额（分），可不同于标价
    payment_method: str = Field(sa_column=Column(String(100), nullable=False))
    payment_timing: str = Field(sa_column=Column(String(200), nullable=False))
    status: str = Field(default=AgreementStatus.PROPOSED.value, sa_column=Column(String(16), default=AgreementStatus.PROPOSED.value, nullable=False))
    proposed_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    decided_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    trade: Trade = Relationship(sa_relationship=relationship(back_populates="agreements", foreign_keys="TradeAgreement.trade_id"))


class TradeTransition(Base, table=True):
    """状态转移历史：前后状态、主体、时间、触发、原因及依据（BR-08、6.5）。"""

    __tablename__ = cast(Any, "trade_transitions")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    trade_id: int = Field(sa_column=Column(ForeignKey("trades.id"), index=True, nullable=False))
    from_status: str | None = Field(default=None, sa_column=Column(String(24), nullable=True))
    to_status: str = Field(sa_column=Column(String(24), nullable=False))
    actor_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))  # 系统触发为空
    actor_role: str = Field(default='system', sa_column=Column(String(16), default="system", nullable=False))  # buyer/seller/admin/system
    trigger: str = Field(sa_column=Column(String(64), nullable=False))  # 事件标识
    reason: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))
    basis_case_id: int | None = Field(default=None, sa_column=Column(ForeignKey("disposal_cases.id"), nullable=True))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))

    trade: Trade = Relationship(sa_relationship=relationship(back_populates="transitions"))


class CompletionConfirmation(Base, table=True):
    """C-10：双方各自一次完成确认（交付+支付统一声明）；当前有效与历史分开（BR-28/29）。"""

    __tablename__ = cast(Any, "completion_confirmations")
    __table_args__ = (
        Index(
            "uq_current_confirm",
            "trade_id",
            "confirmer_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
            # PostgreSQL boolean 不能复用 SQLite 的 = 1 表达式。
            postgresql_where=text("is_current"),
        ),
    )

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    trade_id: int = Field(sa_column=Column(ForeignKey("trades.id"), index=True, nullable=False))
    confirmer_id: int = Field(sa_column=Column(ForeignKey("users.id"), nullable=False))
    note: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))  # 可选说明
    is_current: bool = Field(default=True, sa_column=Column(Boolean, default=True, nullable=False))
    confirmed_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))

    trade: Trade = Relationship(sa_relationship=relationship(back_populates="confirmations"))


class TradeReview(Base, table=True):
    """C-11：已完成交易的双方互评，每方每笔一条；仅本人按发表/收到查看（BR-24）。"""

    __tablename__ = cast(Any, "trade_reviews")
    __table_args__ = (UniqueConstraint("trade_id", "reviewer_id"),)

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    trade_id: int = Field(sa_column=Column(ForeignKey("trades.id"), index=True, nullable=False))
    reviewer_id: int = Field(sa_column=Column(ForeignKey("users.id"), index=True, nullable=False))
    reviewee_id: int = Field(sa_column=Column(ForeignKey("users.id"), index=True, nullable=False))
    rating: int = Field(sa_column=Column(Integer, nullable=False))  # 1—5
    content: str = Field(default='', sa_column=Column(Text, default="", nullable=False))
    # 管理员处理违规评价：逻辑删除并留理由（BR-24）
    deleted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    deleted_by_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))
    delete_reason: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
