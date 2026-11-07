"""Disposal-case (C-13) helpers: case creation, claim validation, and communication-message records."""

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import DisposalCase, DisposalMessage, Trade
from app.models.enums import (
    CaseStatus,
    CaseType,
    DisposalMessageKind,
    DisposalMessageRole,
)

# When an abnormal trade/trade dispute is directly linked to a trade, both buyer and seller are communication participants in the case (BR-26/33).
TRADE_PARTICIPANT_CASE_TYPES = (
    CaseType.ABNORMAL_TRADE.value,
    CaseType.TRADE_DISPUTE.value,
)


def has_inquiry(case: DisposalCase) -> bool:
    """Whether an administrator has already started an inquiry (inquiry messages are retained in the same communication case)."""
    return any(m.kind == DisposalMessageKind.INQUIRY.value for m in case.messages)


async def case_participant_ids(db: AsyncSession, case: DisposalCase) -> list[int]:
    """User IDs eligible to communicate on the case, deduplicated and kept in stable order.

    Ordinary review/report/ban cases include only subject_user; only an abnormal
    trade/trade dispute directly linked by trade_id includes both buyer and seller,
    and a linked trade from another case never serves as a basis for broader access.
    """
    ids: list[int] = []
    if case.subject_user_id is not None:
        ids.append(case.subject_user_id)
    if case.case_type in TRADE_PARTICIPANT_CASE_TYPES and case.trade_id is not None:
        trade = await db.get(Trade, case.trade_id)
        if trade:
            ids.extend([trade.buyer_id, trade.seller_id])
    return list(dict.fromkeys(ids))


async def case_is_entitled(db: AsyncSession, case: DisposalCase, user_id: int) -> bool:
    """Unified eligibility check for case access/communication."""
    return user_id in await case_participant_ids(db, case)


async def get_entitled_case(db: AsyncSession, case_id: int, user_id: int) -> DisposalCase:
    """Load a case under the unified eligibility rules; nonexistent yields 404 and ineligible yields 403."""
    case = await db.get(DisposalCase, case_id)
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "事项不存在")
    if not await case_is_entitled(db, case, user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权访问该事项")
    return case


async def case_capabilities(db: AsyncSession, case: DisposalCase, user_id: int) -> dict:
    """Compute statement/appeal capability from real backend eligibility and state, shared by the API and detail booleans."""
    entitled = await case_is_entitled(db, case, user_id)
    return {
        # Statement: requires communication eligibility, an existing inquiry, and processing status (a disposed case only allows an appeal).
        "can_submit_statement": bool(
            entitled and case.status == CaseStatus.PROCESSING.value and has_inquiry(case)
        ),
        # Appeal: requires communication eligibility and an existing disposal conclusion.
        "can_submit_appeal": bool(entitled and case.status == CaseStatus.DISPOSED.value),
    }


async def create_case(
    db: AsyncSession,
    *,
    case_type: CaseType,
    title: str,
    subject_user_id: int | None = None,
    product_id: int | None = None,
    report_id: int | None = None,
    trade_id: int | None = None,
) -> DisposalCase:
    """The case enters the shared pending pool (BR-34), awaiting an administrator to claim it voluntarily."""
    case = DisposalCase(
        case_type=case_type.value,
        title=title,
        subject_user_id=subject_user_id,
        product_id=product_id,
        report_id=report_id,
        trade_id=trade_id,
    )
    db.add(case)
    await db.flush()
    return case


async def ensure_claimant(case: DisposalCase, admin_id: int) -> None:
    """BR-34: handling permission is limited to the case claimant."""
    if case.claimed_by_id != admin_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅该事项认领管理员可处理")


async def add_case_message(
    db: AsyncSession,
    case: DisposalCase,
    *,
    sender_id: int | None,
    role: DisposalMessageRole,
    kind: DisposalMessageKind,
    content: str,
) -> DisposalMessage:
    msg = DisposalMessage(case_id=case.id, sender_id=sender_id, role=role.value, kind=kind.value, content=content)
    db.add(msg)
    await db.flush()
    return msg


def now_utc() -> datetime:
    return datetime.now(UTC)


async def dispose_case(
    db: AsyncSession,
    case: DisposalCase,
    *,
    conclusion: str,
    reason: str | None = None,
    basis: str | None = None,
) -> DisposalCase:
    case.status = CaseStatus.DISPOSED.value
    case.conclusion = conclusion
    case.conclusion_reason = reason
    case.basis = basis
    case.disposed_at = now_utc()
    await db.flush()
    return case


async def lock_case_for_update(db: AsyncSession, case_id: int) -> DisposalCase | None:
    """Lock in product→case order before a write and refresh state read before the lock wait."""
    from sqlmodel import col, select, update

    from app.services.trades import lock_product_for_update
    existing = await db.get(DisposalCase, case_id)
    if existing is None:
        return None
    if existing.product_id is not None:
        await lock_product_for_update(db, existing.product_id)
    if db.get_bind().dialect.name == 'sqlite':
        await db.exec(update(DisposalCase).where(col(DisposalCase.id) == case_id).values(id=case_id))
    return (await db.exec(select(DisposalCase).where(col(DisposalCase.id) == case_id)
        .with_for_update().execution_options(populate_existing=True))).one_or_none()
