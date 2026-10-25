"""处置事项（C-13）辅助：创建事项、认领校验、沟通消息留痕。"""

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DisposalCase, DisposalMessage
from app.models.enums import CaseStatus, CaseType, DisposalMessageKind, DisposalMessageRole


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
