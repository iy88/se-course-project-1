"""管理事项（C-13/BR-34）：共享池、认领、详情、问询、沟通与结论。"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, StringConstraints
from sqlmodel import and_, col, func, select, update

from app.api.deps import CurrentAdmin, DbSession
from app.models import DisposalCase, Product, Report, User
from app.models.enums import CaseStatus, CaseType, ReportStatus
from app.services import audit as audit_service
from app.services import cases as case_service
from app.services.cases import ensure_claimant

router = APIRouter(prefix="/admin/cases", tags=["admin-cases"])


class ClaimOut(BaseModel):
    id: int
    detail: str


class CaseMessageIn(BaseModel):
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class InquiryIn(BaseModel):
    # 需要本人说明的内容范围；先去空白再校验，全空白不得写入沟通单。
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class DisposeIn(BaseModel):
    conclusion: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=500)
    basis: str | None = Field(default=None, max_length=500)


async def _case_or_404(db, case_id: int) -> DisposalCase:
    case = await db.get(DisposalCase, case_id)
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "事项不存在")
    return case


def _case_item(case: DisposalCase) -> dict:
    return {
        "id": case.id,
        "case_type": case.case_type,
        "status": case.status,
        "title": case.title,
        "claimed_by_id": case.claimed_by_id,
        "subject_user_id": case.subject_user_id,
        "product_id": case.product_id,
        "report_id": case.report_id,
        "trade_id": case.trade_id,
        "conclusion": case.conclusion,
        "conclusion_reason": case.conclusion_reason,
        "basis": case.basis,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "disposed_at": case.disposed_at.isoformat() if case.disposed_at else None,
    }


@router.get("")
async def list_cases(
    admin: CurrentAdmin,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    case_status: str = Query(default="pending", alias="status", pattern="^(pending|processing|disposed|all)$"),
    case_type: str | None = Query(default=None),
    mine: bool = Query(default=False, description="仅列出本人认领的事项"),
) -> dict:
    conditions = []
    if case_status != "all":
        conditions.append(col(DisposalCase.status) == case_status)
    if case_type:
        conditions.append(col(DisposalCase.case_type) == case_type)
    if mine:
        conditions.append(col(DisposalCase.claimed_by_id) == admin.id)
    count_stmt = select(func.count()).select_from(DisposalCase)
    rows_stmt = select(DisposalCase).order_by(col(DisposalCase.id).desc())
    if conditions:
        where_clause = and_(*conditions)
        count_stmt = count_stmt.where(where_clause)
        rows_stmt = rows_stmt.where(where_clause)
    total = (await db.exec(count_stmt)).first() or 0
    result = await db.exec(rows_stmt.offset((page - 1) * page_size).limit(page_size))
    return {"items": [_case_item(c) for c in result], "total": int(total), "page": page, "page_size": page_size}


async def _claim_pending_case(db, case_id: int, admin_id: int, claimed_at) -> bool:
    """以数据库条件更新竞争待处理事项；仅当行仍为 pending 且未认领时成功。

    条件与赋值在同一条 UPDATE 中执行，由数据库判定唯一胜者，不依赖先前读取。
    synchronize_session="evaluate" 同步会话内可能存在的旧对象，避免其后续 flush 覆盖。
    """
    result = await db.exec(
        update(DisposalCase)
        .where(
            col(DisposalCase.id) == case_id,
            col(DisposalCase.status) == CaseStatus.PENDING.value,
            col(DisposalCase.claimed_by_id).is_(None),
        )
        .values(
            status=CaseStatus.PROCESSING.value,
            claimed_by_id=admin_id,
            claimed_at=claimed_at,
        )
        .execution_options(synchronize_session="evaluate")
    )
    return result.rowcount == 1


@router.post("/{case_id}/claim", response_model=ClaimOut)
async def claim_case(case_id: int, admin: CurrentAdmin, db: DbSession) -> ClaimOut:
    """共享池主动认领：同一事项同时仅一名管理员（BR-34）。"""
    admin_id = admin.id
    won = await _claim_pending_case(db, case_id, admin_id, case_service.now_utc())
    if not won:
        # 失败不保留任何写入；先结束事务再区分不存在与被抢先/已处置。
        await db.rollback()
        exists = (await db.exec(select(col(DisposalCase.id)).where(col(DisposalCase.id) == case_id))).first()
        if exists is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "事项不存在")
        raise HTTPException(status.HTTP_409_CONFLICT, "该事项已被认领或已处置")
    # 成功以数据库中的真实 owner 为准，而不是请求参数或内存对象。
    row = (
        await db.exec(
            select(col(DisposalCase.claimed_by_id), col(DisposalCase.status)).where(col(DisposalCase.id) == case_id)
        )
    ).first()
    if row is None or row[0] != admin_id or row[1] != CaseStatus.PROCESSING.value:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "该事项已被认领或已处置")
    # 举报事项认领后同步举报状态为处理中（BR-25/US-07）；与认领同一事务提交。
    claimed_case = await db.get(DisposalCase, case_id)
    report_status = None
    if claimed_case is not None and claimed_case.report_id is not None:
        report = await db.get(Report, claimed_case.report_id)
        if report is not None and report.status == ReportStatus.PENDING.value:
            report.status = ReportStatus.PROCESSING.value
            report_status = report.status
    await audit_service.record_event(
        db,
        audit_service.EVENT_ADMIN_CASE_CLAIM,
        target_type="disposal_case",
        target_id=case_id,
        after={"status": row[1], "claimed_by_id": admin_id, "report_status": report_status},
    )
    await db.commit()
    return ClaimOut(id=case_id, detail="认领成功")


@router.get("/{case_id}")
async def case_detail(case_id: int, admin: CurrentAdmin, db: DbSession) -> dict:
    """事项详情：仅认领人可查看非公开内容与沟通记录（BR-19/34）。"""
    case = await _case_or_404(db, case_id)
    if case.claimed_by_id != admin.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅该事项认领管理员可查看详情")
    data = _case_item(case)
    if case.case_type == CaseType.AVATAR_REVIEW.value:
        from app.storage.base import get_storage
        data['avatar'] = {'key': case.avatar_key, 'url': get_storage().public_url(case.avatar_key) if case.avatar_key else None}

    data["messages"] = [
        {
            "id": m.id,
            "sender_id": m.sender_id,
            "role": m.role,
            "kind": m.kind,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in case.messages
    ]
    # 沟通资格参与方：问询通知对象，展示名称供事项页标注问询对象。
    participant_ids = await case_service.case_participant_ids(db, case)
    participants = []
    if participant_ids:
        users = (await db.exec(
            select(User).where(col(User.id).in_(participant_ids)).order_by(col(User.id))
        )).all()
        by_id = {u.id: u for u in users}
        participants = [
            {"id": pid, "display_name": by_id[pid].display_name if pid in by_id else None}
            for pid in participant_ids
        ]
    data["participants"] = participants

    # 附加上下文
    if case.product_id:
        product = await db.get(Product, case.product_id)
        data["product"] = None
        if product:
            from app.storage.base import get_storage

            product_image_urls = [get_storage().public_url(i.file_key) for i in product.images]
            data["product"] = {
                "id": product.id,
                "title": product.title,
                "description": product.description,
                "price_cents": product.price_cents,
                "status": product.status,
                "display_restricted": product.display_restricted,
                "display_restricted_reason": product.display_restricted_reason,
                "display_restricted_case_id": product.display_restricted_case_id,
                "image_keys": [i.file_key for i in product.images],
                "image_urls": product_image_urls,
                "tag_names": [t.name for t in product.tags],
            }
            from sqlmodel import select as _select

            from app.models import ProductTagApplication

            apps = (await db.exec(_select(ProductTagApplication).where(col(ProductTagApplication.product_id) == product.id))).all()
            data["tag_applications"] = [
                {
                    "id": a.id,
                    "requested_name": a.requested_name,
                    "status": a.status,
                    "decision_reason": a.decision_reason,
                }
                for a in apps
            ]
    if case.report_id:
        from app.models import Report, ReportSupplement

        report = await db.get(Report, case.report_id)
        data["report"] = None
        if report:
            from app.storage.base import get_storage

            storage = get_storage()
            report_evidence_urls = [storage.public_url(key) for key in report.evidence_keys]
            supplements = (await db.exec(
                select(ReportSupplement)
                .where(col(ReportSupplement.report_id) == report.id)
                .order_by(col(ReportSupplement.id))
            )).all()
            data["report"] = {
                "id": report.id,
                "reporter_id": report.reporter_id,
                "target_type": report.target_type,
                "target_id": report.target_id,
                "reason": report.reason,
                "detail": report.detail,
                "evidence_keys": report.evidence_keys,
                "evidence_urls": report_evidence_urls,
                "supplements": [
                    {
                        "id": supplement.id,
                        "content": supplement.content,
                        "created_at": supplement.created_at.isoformat() if supplement.created_at else None,
                        "evidence_urls": [storage.public_url(key) for key in supplement.evidence_keys],
                    }
                    for supplement in supplements
                ],
                "status": report.status,
                "result_confirmed": report.result_confirmed,
            }
            # 举报目标内容（限必要范围展示）
            from app.api.v1.admin.reports import target_snapshot

            data["report_target"] = await target_snapshot(db, report)
    if case.trade_id:
        from app.api.v1.admin.trades import admin_trade_view

        data["trade"] = await admin_trade_view(db, case.trade_id)
    # Only expose the already-authorized case's directly readable branch.
    # No global conversation search or client-entered conversation IDs are needed.
    data["readable_conversation_id"] = None
    if case.case_type == CaseType.REPORT.value:
        target = data.get("report_target")
        if target and target.get("type") == "message" and not target.get("missing"):
            data["readable_conversation_id"] = target.get("conversation_id")
    elif case.case_type in (CaseType.TRADE_DISPUTE.value, CaseType.ABNORMAL_TRADE.value):
        from app.api.v1.admin.case_conversations import _trade_branch_conversation_id

        data["readable_conversation_id"] = await _trade_branch_conversation_id(db, case)
    if case.subject_user_id:
        subject = await db.get(User, case.subject_user_id)
        data["subject_user"] = {"id": subject.id, "display_name": subject.display_name, "email": subject.email} if subject else None
    return data


@router.post("/{case_id}/inquiry")
async def send_inquiry(case_id: int, body: InquiryIn, admin: CurrentAdmin, db: DbSession) -> dict:
    """发起问询：向全部有沟通资格的参与方发送问询通知（BR-26/33）。"""
    case = await _case_or_404(db, case_id)
    # 待处理事项尚未进入认领者的处理上下文，直接按状态拒绝；其余状态先校验认领人，
    # 避免非认领管理员借问询接口探测他人在办/已处置事项。
    if case.status == CaseStatus.PENDING.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅处理中的事项可发起问询")
    await ensure_claimant(case, admin.id)
    # 问询只在认领后的处理中阶段开放；disposed 已归档。
    if case.status == CaseStatus.DISPOSED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "该事项已处置，不能重新发起问询")
    if case.status != CaseStatus.PROCESSING.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅处理中的事项可发起问询")
    recipients = await case_service.case_participant_ids(db, case)
    if not recipients:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该事项无可问询用户")
    await case_service.add_case_message(
        db, case, sender_id=admin.id,
        role=case_service.DisposalMessageRole.ADMIN,
        kind=case_service.DisposalMessageKind.INQUIRY,
        content=body.content.strip(),
    )
    from app.services.notifications import notify

    await notify(
        db, recipients, "inquiry", "管理员向您发起问询",
        f"事项「{case.title}」需要您说明：{body.content.strip()[:100]}。请从本通知进入提交说明。",
        link_type="case", link_id=case.id,
    )
    await audit_service.record_event(
        db,
        audit_service.EVENT_ADMIN_CASE_INQUIRY,
        target_type="disposal_case",
        target_id=case.id,
        after={"status": case.status},
    )
    await db.commit()
    return {"detail": "问询已发送"}


@router.post("/{case_id}/messages")
async def admin_reply(case_id: int, body: CaseMessageIn, admin: CurrentAdmin, db: DbSession) -> dict:
    """管理员在事项沟通单回复结论/说明（BR-32/33）。"""
    case = await _case_or_404(db, case_id)
    await ensure_claimant(case, admin.id)
    await case_service.add_case_message(
        db, case, sender_id=admin.id,
        role=case_service.DisposalMessageRole.ADMIN,
        kind=case_service.DisposalMessageKind.REPLY,
        content=body.content.strip(),
    )
    # 统一按事项资格取接收人并去重，避免同一用户收到多条相同通知。
    recipients = await case_service.case_participant_ids(db, case)
    if recipients:
        from app.services.notifications import notify

        await notify(
            db, recipients, "appeal_result", "事项沟通有新回复",
            f"事项「{case.title}」有管理员回复，请进入查看。",
            link_type="case", link_id=case.id,
        )
    await audit_service.record_event(
        db,
        audit_service.EVENT_ADMIN_CASE_MESSAGE,
        target_type="disposal_case",
        target_id=case.id,
        after={"status": case.status},
    )
    await db.commit()
    return {"detail": "回复已发送"}


@router.post("/{case_id}/dispose")
async def dispose_case(case_id: int, body: DisposeIn, admin: CurrentAdmin, db: DbSession) -> dict:
    """形成处置结论并留依据（BR-26）；具体处置动作由各专项接口执行。"""
    case = await case_service.lock_case_for_update(db, case_id)
    if case is None:
        raise HTTPException(404, '事项不存在')
    await ensure_claimant(case, admin.id)
    if case.status == CaseStatus.DISPOSED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "该事项已处置")
    if case.case_type == CaseType.AVATAR_REVIEW.value:
        raise HTTPException(400, '请使用头像审核结论入口处理该事项')
    await case_service.dispose_case(
        db, case, conclusion=body.conclusion.strip(), reason=body.reason, basis=body.basis
    )
    await audit_service.record_event(
        db,
        audit_service.EVENT_ADMIN_CASE_DISPOSE,
        target_type="disposal_case",
        target_id=case.id,
        before={"status": CaseStatus.PROCESSING.value},
        after={"status": case.status},
    )
    await db.commit()
    return {"detail": "事项已处置"}
