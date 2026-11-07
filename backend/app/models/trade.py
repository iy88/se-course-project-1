"""C-09 trade records (request and trade are the same object), agreements, state-transition history, C-10 completion confirmations, C-11 reviews."""

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
    """One object carries the purchase request and, after seller acceptance, the trade (BR-01; Chapter 3 C-09)."""

    __tablename__ = cast(Any, "trades")
    __table_args__ = (
        # At most one in-progress/still-locking trade per product at a time (BR-03)
        Index(
            "uq_product_locking_trade",
            "product_id",
            unique=True,
            sqlite_where=text("status IN ('in_progress','disputed','abnormal')"),
            postgresql_where=text("status IN ('in_progress','disputed','abnormal')"),
        ),
        # At most one active pending-acceptance request per buyer per product (BR-02)
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
    request_note: str | None = Field(default=None, sa_column=Column(Text, nullable=True))  # request note (optional)
    close_reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True))  # rejection/withdrawal/close reason

    product_snapshot_json: dict | None = Field(default=None, sa_column=Column(JSONType, nullable=True))  # product content at the time of acceptance (BR-30)

    # Agreement stage: in progress with no active agreement = agreement awaiting both parties; with one = agreement confirmed, awaiting completion (4.15)
    current_agreement_id: int | None = Field(default=None, sa_column=Column(
        ForeignKey("trade_agreements.id", use_alter=True, name="fk_trades_current_agreement_id_trade_agreements"),
        nullable=True,
    ))

    # Unilateral confirmation progress and the 7-day wait timer (BR-05); cleared on dispute/recovery
    confirm_wait_started_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    # D-51: freezing pauses the existing wait; the pause instant and remaining seconds are stored separately and resumed from the remainder after unfreezing
    confirm_wait_paused_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    confirm_wait_remaining_seconds: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))

    # Cancellation request (BR-06: before an agreement the seller needs buyer consent; after an agreement both parties must agree)
    cancel_requested_by_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))
    cancel_requested_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    # Dispute-resolution confirmation (BR-07: recovery when both parties confirm resolution; administrator resolution is limited to claimed cases)
    resolution_confirmed_by_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))
    resolution_confirmed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    # Frozen: progress-pause flag caused by administrative action (BR-33), kept separate from the lifecycle status
    frozen: bool = Field(default=False, sa_column=Column(Boolean, default=False, nullable=False))
    frozen_reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    frozen_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    frozen_by_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))
    frozen_case_id: int | None = Field(default=None, sa_column=Column(
        ForeignKey("disposal_cases.id", use_alter=True, name="fk_trades_frozen_case_id_disposal_cases"), nullable=True
    ))

    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    accepted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    finished_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))  # completion/termination time

    agreements: list["TradeAgreement"] = Relationship(sa_relationship=relationship(
        back_populates="trade", foreign_keys="TradeAgreement.trade_id", order_by="TradeAgreement.id"
    ))
    transitions: list["TradeTransition"] = Relationship(sa_relationship=relationship(back_populates="trade", order_by="TradeTransition.id"))
    confirmations: list["CompletionConfirmation"] = Relationship(sa_relationship=relationship(back_populates="trade"))


class TradeAgreement(Base, table=True):
    """Trade agreement: delivery time/text location/method plus agreed amount/payment method/payment timing (4.15)."""

    __tablename__ = cast(Any, "trade_agreements")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    trade_id: int = Field(sa_column=Column(
        ForeignKey("trades.id", use_alter=True, name="fk_trade_agreements_trade_id_trades"), index=True
    , nullable=False))
    round_no: int = Field(default=1, sa_column=Column(Integer, default=1, nullable=False))  # first round = 1; incremented on every change
    proposer_id: int = Field(sa_column=Column(ForeignKey("users.id"), nullable=False))
    delivery_time: str = Field(sa_column=Column(Text, nullable=False))
    delivery_location: str = Field(sa_column=Column(Text, nullable=False))  # text location
    delivery_method: str = Field(sa_column=Column(Text, nullable=False))
    amount_cents: int = Field(sa_column=Column(BigInteger, nullable=False))  # agreed amount (cents), may differ from the list price
    payment_method: str = Field(sa_column=Column(Text, nullable=False))
    payment_timing: str = Field(sa_column=Column(Text, nullable=False))
    status: str = Field(default=AgreementStatus.PROPOSED.value, sa_column=Column(String(16), default=AgreementStatus.PROPOSED.value, nullable=False))
    proposed_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    decided_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    trade: Trade = Relationship(sa_relationship=relationship(back_populates="agreements", foreign_keys="TradeAgreement.trade_id"))


class TradeTransition(Base, table=True):
    """State-transition history: from/to status, actor, time, trigger, reason, and basis (BR-08, 6.5)."""

    __tablename__ = cast(Any, "trade_transitions")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    trade_id: int = Field(sa_column=Column(ForeignKey("trades.id"), index=True, nullable=False))
    from_status: str | None = Field(default=None, sa_column=Column(String(24), nullable=True))
    to_status: str = Field(sa_column=Column(String(24), nullable=False))
    actor_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))  # null for system-triggered transitions
    actor_role: str = Field(default='system', sa_column=Column(String(16), default="system", nullable=False))  # buyer/seller/admin/system
    trigger: str = Field(sa_column=Column(String(64), nullable=False))  # event identifier
    reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    basis_case_id: int | None = Field(default=None, sa_column=Column(ForeignKey("disposal_cases.id"), nullable=True))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))

    trade: Trade = Relationship(sa_relationship=relationship(back_populates="transitions"))


class CompletionConfirmation(Base, table=True):
    """C-10: each party confirms completion once (delivery + payment declared together); current and historical entries are separate (BR-28/29)."""

    __tablename__ = cast(Any, "completion_confirmations")
    __table_args__ = (
        Index(
            "uq_current_confirm",
            "trade_id",
            "confirmer_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
            # PostgreSQL booleans cannot reuse the SQLite = 1 expression.
            postgresql_where=text("is_current"),
        ),
    )

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    trade_id: int = Field(sa_column=Column(ForeignKey("trades.id"), index=True, nullable=False))
    confirmer_id: int = Field(sa_column=Column(ForeignKey("users.id"), nullable=False))
    note: str | None = Field(default=None, sa_column=Column(Text, nullable=True))  # optional note
    is_current: bool = Field(default=True, sa_column=Column(Boolean, default=True, nullable=False))
    confirmed_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))

    trade: Trade = Relationship(sa_relationship=relationship(back_populates="confirmations"))


class TradeReview(Base, table=True):
    """C-11: mutual reviews for a completed trade, one per party per trade; users see their own written/received reviews (BR-24)."""

    __tablename__ = cast(Any, "trade_reviews")
    __table_args__ = (UniqueConstraint("trade_id", "reviewer_id"),)

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    trade_id: int = Field(sa_column=Column(ForeignKey("trades.id"), index=True, nullable=False))
    reviewer_id: int = Field(sa_column=Column(ForeignKey("users.id"), index=True, nullable=False))
    reviewee_id: int = Field(sa_column=Column(ForeignKey("users.id"), index=True, nullable=False))
    rating: int = Field(sa_column=Column(Integer, nullable=False))  # 1—5
    content: str = Field(default='', sa_column=Column(Text, default="", nullable=False))
    # Administrator handling of violating reviews: soft delete with a reason (BR-24)
    deleted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    deleted_by_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))
    delete_reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
