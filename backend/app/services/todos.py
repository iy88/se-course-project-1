"""User to-do aggregation (D-53, 4.17): each read derives items from existing matters the user is currently eligible for and must handle.

Adds no task types, business records, or permissions; notification read state does not
affect to-do determination. Administrator to-dos come from the shared processing pool,
and personal to-dos are always empty for administrators.
"""
from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    CompletionConfirmation,
    DisposalCase,
    DisposalMessage,
    Trade,
    TradeAgreement,
    User,
)
from app.models.enums import (
    AccountStatus,
    AgreementStatus,
    CaseStatus,
    DisposalMessageKind,
    DisposalMessageRole,
    TradeStatus,
    UserRole,
)
from app.services.permissions import frozen_trade_party_ids

# Own-matter types included in aggregation (stable keys that do not change with notifications or read state)
KIND_REQUEST = "request_pending"
KIND_AGREEMENT = "agreement_pending"
KIND_CANCEL = "cancel_pending"
KIND_COMPLETION = "completion_confirm"
KIND_DISPUTE = "dispute_resolution"
KIND_INQUIRY = "inquiry_pending"

TRADE_TODO_STATUSES = (
    TradeStatus.PENDING_ACCEPTANCE.value,
    TradeStatus.IN_PROGRESS.value,
    TradeStatus.DISPUTED.value,
)


def _item(kind: str, object_id: int, title: str, link_type: str, link_id: int, action: str) -> dict:
    return {
        "key": f"{kind}:{object_id}",
        "kind": kind,
        "title": title,
        "link_type": link_type,
        "link_id": link_id,
        "action": action,
    }


async def build_todos(db: AsyncSession, user: User) -> list[dict]:
    """Return the to-do list for which the current user is eligible to act; read-only, creating or modifying no business records."""
    if user.role == UserRole.ADMIN.value:
        return []

    items: list[dict] = []
    banned = user.status == AccountStatus.BANNED.value

    # Trade to-dos: actions are blocked and the item is omitted while banned or when the
    # user/counterparty has any active trade freeze; BR-33 freezes are user-level trade
    # restrictions and the IM pair scope is not mixed in here.
    if not banned:
        frozen_users = await frozen_trade_party_ids(db)
        trades = list(

                await db.exec(
                    select(Trade).where(
                        or_(col(Trade.buyer_id) == user.id, col(Trade.seller_id) == user.id),
                        col(Trade.status).in_(TRADE_TODO_STATUSES),
                    )
                )

        )
        trade_ids = [trade.id for trade in trades]

        pending_agreements: dict[int, TradeAgreement] = {}
        effective_agreement_ids: set[int] = set()
        confirmers: dict[int, set[int]] = {}
        if trade_ids:
            for agreement in (
                await db.exec(
                    select(TradeAgreement).where(
                        col(TradeAgreement.trade_id).in_(trade_ids),
                        col(TradeAgreement.status) == AgreementStatus.PROPOSED.value,
                    )
                )
            ):
                pending_agreements[agreement.trade_id] = agreement
            for agreement_id in (
                await db.exec(
                    select(col(TradeAgreement.id)).where(
                        col(TradeAgreement.trade_id).in_(trade_ids),
                        col(TradeAgreement.status) == AgreementStatus.CONFIRMED.value,
                    )
                )
            ):
                effective_agreement_ids.add(agreement_id)
            for confirmation in (
                await db.exec(
                    select(CompletionConfirmation).where(
                        col(CompletionConfirmation.trade_id).in_(trade_ids),
                        col(CompletionConfirmation.is_current).is_(True),
                    )
                )
            ):
                confirmers.setdefault(confirmation.trade_id, set()).add(confirmation.confirmer_id)

        for trade in trades:
            other_id = trade.seller_id if trade.buyer_id == user.id else trade.buyer_id
            # The user or this trade's counterparty has an active trade freeze: both parties' trade writes are suspended (BR-33).
            if user.id in frozen_users or other_id in frozen_users:
                continue
            if trade.status == TradeStatus.PENDING_ACCEPTANCE.value:
                if trade.seller_id == user.id:
                    items.append(
                        _item(
                            KIND_REQUEST,
                            trade.id,
                            f"购买请求待接受（交易 #{trade.id}）",
                            "trade",
                            trade.id,
                            "accept_request",
                        )
                    )
                continue

            # Agreement confirmation is actionable only while the trade is in progress; a proposal made during a dispute cannot serve as an actionable agreement confirmation.
            if trade.status == TradeStatus.IN_PROGRESS.value:
                agreement = pending_agreements.get(trade.id)
                if agreement and agreement.proposer_id != user.id:
                    items.append(
                        _item(
                            KIND_AGREEMENT,
                            trade.id,
                            f"交易约定待确认（交易 #{trade.id}）",
                            "trade",
                            trade.id,
                            "confirm_agreement",
                        )
                    )
                # Actionable once an effective agreement exists and the user has not confirmed; the counterparty need not confirm first (BR-04/FR-06).
                if (
                    trade.current_agreement_id
                    and trade.current_agreement_id in effective_agreement_ids
                    and user.id not in confirmers.get(trade.id, set())
                ):
                    items.append(
                        _item(
                            KIND_COMPLETION,
                            trade.id,
                            f"交易完成待确认（交易 #{trade.id}）",
                            "trade",
                            trade.id,
                            "confirm_completion",
                        )
                    )
            if trade.cancel_requested_by_id and trade.cancel_requested_by_id != user.id:
                items.append(
                    _item(
                        KIND_CANCEL,
                        trade.id,
                        f"取消申请待确认（交易 #{trade.id}）",
                        "trade",
                        trade.id,
                        "confirm_cancel",
                    )
                )
            if (
                trade.status == TradeStatus.DISPUTED.value
                and trade.resolution_confirmed_by_id
                and trade.resolution_confirmed_by_id != user.id
            ):
                items.append(
                    _item(
                        KIND_DISPUTE,
                        trade.id,
                        f"争议解决确认待提交（交易 #{trade.id}）",
                        "trade",
                        trade.id,
                        "confirm_dispute_resolution",
                    )
                )

    # Management communication: unanswered inquiries where the user is the person asked; retained even while banned/frozen
    cases = list(

            await db.exec(
                select(DisposalCase).where(
                    col(DisposalCase.subject_user_id) == user.id,
                    col(DisposalCase.status) != CaseStatus.DISPOSED.value,
                )
            )

    )
    for case in cases:
        last_inquiry: DisposalMessage | None = None
        answered = False
        for message in case.messages:
            if message.kind == DisposalMessageKind.INQUIRY.value:
                last_inquiry = message
                answered = False
            elif (
                last_inquiry is not None
                and message.role == DisposalMessageRole.USER.value
                and message.kind == DisposalMessageKind.STATEMENT.value
            ):
                answered = True
        if last_inquiry is not None and not answered:
            items.append(
                _item(
                    KIND_INQUIRY,
                    case.id,
                    f"管理问询待说明：{case.title}",
                    "case",
                    case.id,
                    "submit_statement",
                )
            )

    # Stable order; the key is kind + object id, so repeated reads of the same matter are consistent
    return sorted(items, key=lambda item: (item["kind"], item["link_id"], item["key"]))
