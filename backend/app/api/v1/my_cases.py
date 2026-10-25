"""用户侧处置沟通（C-13）：问询说明、处置申辩与管理员回复（BR-26/32/33）。"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import DisposalCase, Trade
from app.models.enums import CaseStatus, DisposalMessageKind, DisposalMessageRole
from app.services import cases as case_service

router = APIRouter(prefix="/me/cases", tags=["my-cases"])


class StatementIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


async def _entitled_case(db, case_id: int, user_id: int) -> DisposalCase:
    """事项访问资格：受处置/被询问本人，或争议/异常交易的参与方（BR-26）。"""
    case = await db.get(DisposalCase, case_id)
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "事项不存在")
    if case.subject_user_id == user_id:
        return case
    if case.trade_id:
        trade = await db.get(Trade, case.trade_id)
        if trade and user_id in (trade.buyer_id, trade.seller_id):
            return case
    raise HTTPException(status.HTTP_403_FORBIDDEN, "无权访问该事项")


@router.get("")
async def my_cases(user: CurrentUser, db: DbSession) -> list[dict]:
    """本人事项入口：含受处置事项与交易争议/异常事项。"""
    my_trades = (
        await db.execute(select(Trade.id).where((Trade.buyer_id == user.id) | (Trade.seller_id == user.id)))
    ).scalars().all()
    result = await db.execute(
        select(DisposalCase).where(
            (DisposalCase.subject_user_id == user.id) | (DisposalCase.trade_id.in_(my_trades or [0]))
        ).order_by(DisposalCase.id.desc())
    )
    return [
        {
            "id": c.id,
            "case_type": c.case_type,
            "status": c.status,
            "title": c.title,
            "conclusion": c.conclusion,
            "conclusion_reason": c.conclusion_reason if c.status == CaseStatus.DISPOSED.value else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "disposed_at": c.disposed_at.isoformat() if c.disposed_at else None,
        }
        for c in result.scalars()
    ]


@router.get("/{case_id}")
async def case_detail(case_id: int, user: CurrentUser, db: DbSession) -> dict:
    case = await _entitled_case(db, case_id, user.id)
    has_inquiry = any(m.kind == DisposalMessageKind.INQUIRY.value for m in case.messages)
    return {
        "id": case.id,
        "case_type": case.case_type,
        "status": case.status,
        "title": case.title,
        "trade_id": case.trade_id,
        "conclusion": case.conclusion,
        "conclusion_reason": case.conclusion_reason if case.status == CaseStatus.DISPOSED.value else None,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "disposed_at": case.disposed_at.isoformat() if case.disposed_at else None,
        "has_inquiry": has_inquiry,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "kind": m.kind,
                "content": m.content,
                "sender_id": m.sender_id if m.sender_id == user.id else None,  # 不披露管理员身份细节
                "mine": m.sender_id == user.id,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in case.messages
        ],
    }


@router.post("/{case_id}/statement")
async def submit_statement(case_id: int, body: StatementIn, user: CurrentUser, db: DbSession) -> dict:
    """问询阶段说明：从问询通知进入提交；问询不改变状态（BR-26）。"""
    case = await _entitled_case(db, case_id, user.id)
    if case.subject_user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅被询问用户可提交说明")
    if case.status == CaseStatus.DISPOSED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "该事项已处置，请使用申辩入口")
    has_inquiry = any(m.kind == DisposalMessageKind.INQUIRY.value for m in case.messages)
    if not has_inquiry:
        raise HTTPException(status.HTTP_409_CONFLICT, "该事项尚未发起问询")
    await case_service.add_case_message(
        db, case, sender_id=user.id, role=DisposalMessageRole.USER,
        kind=DisposalMessageKind.STATEMENT, content=body.content.strip(),
    )
    await db.commit()
    return {"detail": "说明已提交，管理员将回复处理"}


@router.post("/{case_id}/appeal")
async def submit_appeal(case_id: int, body: StatementIn, user: CurrentUser, db: DbSession) -> dict:
    """处置后申辩：不因提交自动撤销处置（BR-26）。"""
    case = await _entitled_case(db, case_id, user.id)
    if case.subject_user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅受处置用户可提交申辩")
    if case.status != CaseStatus.DISPOSED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "事项尚未形成实际处置，请使用说明入口")
    await case_service.add_case_message(
        db, case, sender_id=user.id, role=DisposalMessageRole.USER,
        kind=DisposalMessageKind.APPEAL, content=body.content.strip(),
    )
    await db.commit()
    return {"detail": "申辩已提交，管理员将回复处理结果"}
