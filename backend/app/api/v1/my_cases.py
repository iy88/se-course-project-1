"""用户侧处置沟通（C-13）：问询说明、处置申辩与管理员回复（BR-26/32/33）。"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlmodel import col, select

from app.core.text import NonBlank2000
from app.api.deps import CurrentUser, DbSession
from app.models import DisposalCase, Trade
from app.models.enums import (
    CaseStatus,
    CaseType,
    DisposalMessageKind,
    DisposalMessageRole,
)
from app.services import audit as audit_service
from app.services import cases as case_service

router = APIRouter(prefix="/me/cases", tags=["my-cases"])


class StatementIn(BaseModel):
    content: NonBlank2000


async def _entitled_case(db, case_id: int, user_id: int) -> DisposalCase:
    """统一复用服务的资格判断，避免详情与提交入口口径漂移。"""
    return await case_service.get_entitled_case(db, case_id, user_id)


@router.get("")
async def my_cases(user: CurrentUser, db: DbSession) -> list[dict]:
    """本人事项入口：含受处置事项，以及本人参与的异常交易/争议事项。"""
    my_trades = (
        await db.exec(select(col(Trade.id)).where((col(Trade.buyer_id) == user.id) | (col(Trade.seller_id) == user.id)))
    ).all()
    trade_case_types = [
        CaseType.ABNORMAL_TRADE.value,
        CaseType.TRADE_DISPUTE.value,
    ]
    result = await db.exec(
        select(DisposalCase).where(
            (col(DisposalCase.subject_user_id) == user.id)
            | (
                col(DisposalCase.case_type).in_(trade_case_types)
                & col(DisposalCase.trade_id).in_(my_trades or [0])
            )
        ).order_by(col(DisposalCase.id).desc())
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
        for c in result
    ]


@router.get("/{case_id}")
async def case_detail(case_id: int, user: CurrentUser, db: DbSession) -> dict:
    case = await _entitled_case(db, case_id, user.id)
    capabilities = await case_service.case_capabilities(db, case, user.id)
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
        **capabilities,
        "has_inquiry": case_service.has_inquiry(case),
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
    capabilities = await case_service.case_capabilities(db, case, user.id)
    if not capabilities["can_submit_statement"]:
        if case.status == CaseStatus.DISPOSED.value:
            raise HTTPException(status.HTTP_409_CONFLICT, "该事项已处置，请使用申辩入口")
        if case.status != CaseStatus.PROCESSING.value:
            raise HTTPException(status.HTTP_409_CONFLICT, "该事项尚未进入处理阶段")
        raise HTTPException(status.HTTP_409_CONFLICT, "该事项尚未发起问询")
    message = await case_service.add_case_message(
        db, case, sender_id=user.id, role=DisposalMessageRole.USER,
        kind=DisposalMessageKind.STATEMENT, content=body.content.strip(),
    )
    await audit_service.record_event(
        db,
        "case.statement_submit",
        target_type="disposal_case",
        target_id=case.id,
        after={"kind": DisposalMessageKind.STATEMENT.value, "msg_id": message.id, "status": case.status},
    )
    await db.commit()
    return {"detail": "说明已提交，管理员将回复处理"}


@router.post("/{case_id}/appeal")
async def submit_appeal(case_id: int, body: StatementIn, user: CurrentUser, db: DbSession) -> dict:
    """处置后申辩：不因提交自动撤销处置（BR-26）。"""
    case = await _entitled_case(db, case_id, user.id)
    capabilities = await case_service.case_capabilities(db, case, user.id)
    if not capabilities["can_submit_appeal"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "事项尚未形成实际处置，请使用说明入口")
    message = await case_service.add_case_message(
        db, case, sender_id=user.id, role=DisposalMessageRole.USER,
        kind=DisposalMessageKind.APPEAL, content=body.content.strip(),
    )
    await audit_service.record_event(
        db,
        "case.appeal_submit",
        target_type="disposal_case",
        target_id=case.id,
        after={"kind": DisposalMessageKind.APPEAL.value, "msg_id": message.id, "status": case.status},
    )
    await db.commit()
    return {"detail": "申辩已提交，管理员将回复处理结果"}
