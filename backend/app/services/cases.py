"""处置事项（C-13）辅助：创建事项、认领校验、沟通消息留痕。"""

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DisposalCase, DisposalMessage, Trade
from app.models.enums import CaseStatus, CaseType, DisposalMessageKind, DisposalMessageRole

# 异常交易/交易争议直接关联交易时，买卖双方均为该事项的沟通参与方（BR-26/33）。
TRADE_PARTICIPANT_CASE_TYPES = (
    CaseType.ABNORMAL_TRADE.value,
    CaseType.TRADE_DISPUTE.value,
)


def has_inquiry(case: DisposalCase) -> bool:
    """是否已由管理员发起问询（问询消息留存于同一沟通单）。"""
    return any(m.kind == DisposalMessageKind.INQUIRY.value for m in case.messages)


async def case_participant_ids(db: AsyncSession, case: DisposalCase) -> list[int]:
    """事项有沟通资格的用户 ID，去重并保持稳定顺序。

    普通审核/举报/封禁仅 subject_user；仅异常交易/交易争议且直接关联 trade_id 时，
    买卖双方均有沟通资格，不把其他事项的关联交易当作扩权依据。
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
    """统一的事项访问/沟通资格判断。"""
    return user_id in await case_participant_ids(db, case)


async def get_entitled_case(db: AsyncSession, case_id: int, user_id: int) -> DisposalCase:
    """按统一资格取事项；不存在 404，无资格 403。"""
    case = await db.get(DisposalCase, case_id)
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "事项不存在")
    if not await case_is_entitled(db, case, user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "无权访问该事项")
    return case


async def case_capabilities(db: AsyncSession, case: DisposalCase, user_id: int) -> dict:
    """由后端真实资格与状态计算说明/申辩能力，接口与详情布尔值共用。"""
    entitled = await case_is_entitled(db, case, user_id)
    return {
        # 说明：须有沟通资格、已问询且仍在处理中（已处置只能申辩）。
        "can_submit_statement": bool(
            entitled and case.status == CaseStatus.PROCESSING.value and has_inquiry(case)
        ),
        # 申辩：须有沟通资格且已形成处置结论。
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
    """事项进入共享待处理池（BR-34），等待管理员主动认领。"""
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
    """BR-34：处理权限限该事项认领人。"""
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
