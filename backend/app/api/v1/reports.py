"""Reports (C-12/BR-25): submission, supplements, my reports, and reports about me."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import col, or_, select

from app.core.text import NonBlank2000, NonBlank500, Text2000
from app.api.deps import CurrentUser, DbSession, ensure_can_write
from app.api.upload_keys import validate_upload_keys
from app.models import (
    Comment,
    Conversation,
    DisposalCase,
    Message,
    Product,
    Report,
    ReportSupplement,
    Trade,
    TradeReview,
    User,
)
from app.models.enums import CaseType, ReportStatus, ReportTargetType
from app.services import audit as audit_service
from app.services import cases as case_service
from app.services import stored_objects

router = APIRouter(prefix="/reports", tags=["reports"])

class ReportCreateIn(BaseModel):
    target_type: str = Field(pattern="^(product|comment|message|review|user)$")
    target_id: int
    reason: NonBlank500
    detail: Text2000 | None = Field(default=None)
    evidence_keys: list[str] = []


class SupplementIn(BaseModel):
    content: NonBlank2000
    evidence_keys: list[str] = []


async def _target_is_reportable(db, target_type: str, target_id: int) -> bool:
    """Decide whether a new report is allowed based on the object's actual validity.

    Soft-deleted comments/reviews and products whose public access was revoked cannot
    be new report targets; other types get no extra invalidation inference not required
    by the specification (for example, delisting does not mean the object is absent).
    """
    if target_type == ReportTargetType.PRODUCT.value:
        product = await db.get(Product, target_id)
        return product is not None and not product.display_restricted
    if target_type == ReportTargetType.COMMENT.value:
        comment = await db.get(Comment, target_id)
        return comment is not None and comment.deleted_at is None
    if target_type == ReportTargetType.MESSAGE.value:
        return await db.get(Message, target_id) is not None
    if target_type == ReportTargetType.REVIEW.value:
        review = await db.get(TradeReview, target_id)
        return review is not None and review.deleted_at is None
    if target_type == ReportTargetType.USER.value:
        return await db.get(User, target_id) is not None
    return False


def _report_out(report: Report, include_reporter: bool = False) -> dict:
    data = {
        "id": report.id,
        "target_type": report.target_type,
        "target_id": report.target_id,
        "reason": report.reason,
        "detail": report.detail,
        "status": report.status,
        "result_confirmed": report.result_confirmed,
        "public_result": report.public_result if report.result_confirmed else None,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "closed_at": report.closed_at.isoformat() if report.closed_at else None,
    }
    return data


@router.post("", status_code=201)
async def create_report(body: ReportCreateIn, user: CurrentUser, db: DbSession) -> dict:
    """Submit a report: explicit target and reason, optional evidence; an open report is supplemented in the original case (BR-25)."""
    ensure_can_write(user)
    # An archived report from the same user for the same object cannot be resubmitted; check terminal/closed records first, tolerating multiple legacy dirty rows.
    closed_report_id = (await db.exec(
        select(col(Report.id))
        .where(
            col(Report.reporter_id) == user.id,
            col(Report.target_type) == body.target_type,
            col(Report.target_id) == body.target_id,
            or_(
                col(Report.status).in_([ReportStatus.HANDLED.value, ReportStatus.UNFOUNDED.value]),
                col(Report.closed_at).is_not(None),
            ),
        )
        .order_by(col(Report.id).desc())
        .limit(1)
    )).first()
    if closed_report_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "您对该对象的举报已处理归档，不能重复提交")
    if not await _target_is_reportable(db, body.target_type, body.target_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "举报对象不存在或已失效，无法提交举报")
    open_report = (await db.exec(
        select(Report).where(
            col(Report.reporter_id) == user.id,
            col(Report.target_type) == body.target_type,
            col(Report.target_id) == body.target_id,
            col(Report.status).in_([ReportStatus.PENDING.value, ReportStatus.PROCESSING.value]),
        )
    )).first()
    if open_report:
        return {
            "detail": "您对该对象已有未处理完的举报，请在原事项补充说明或证据",
            "existing_report_id": open_report.id,
        }
    await validate_upload_keys(db, body.evidence_keys, owner_id=user.id, namespace="report")
    report = Report(
        reporter_id=user.id,
        target_type=body.target_type,
        target_id=body.target_id,
        reason=body.reason.strip(),
        detail=(body.detail or "").strip() or None,
        evidence_keys=body.evidence_keys,
    )
    db.add(report)
    await db.flush()
    try:
        await stored_objects.mark_committed(
            db, body.evidence_keys, ref_type="report", ref_id=report.id
        )
    except stored_objects.StoredObjectUnavailable:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "证据已被回收，请重新上传"
        ) from None
    # Resolve the user responsible for the reported content as the case communication subject (inquiry/appeal)
    from app.api.v1.admin.reports import resolve_target_user_sync

    subject_user = await resolve_target_user_sync(db, report)
    target_label = {"product": "商品", "comment": "评论", "message": "消息", "review": "评价", "user": "用户"}[body.target_type]
    await case_service.create_case(
        db,
        case_type=CaseType.REPORT,
        title=f"举报事项：{target_label}#{body.target_id}",
        subject_user_id=subject_user.id if subject_user else None,
        report_id=report.id,
    )
    await audit_service.record_event(
        db,
        audit_service.EVENT_REPORT_CREATE,
        target_type="report",
        target_id=report.id,
        after={"status": report.status, "target_type": report.target_type, "target_id": report.target_id},
    )
    await db.commit()
    return {"id": report.id, "detail": "举报已提交，进入待处理池"}


@router.post("/{report_id}/supplements")
async def add_supplement(report_id: int, body: SupplementIn, user: CurrentUser, db: DbSession) -> dict:
    """Supplement the original report case with detail/evidence; archived cases accept no more supplements (BR-25)."""
    ensure_can_write(user)
    report = await db.get(Report, report_id)
    if not report or report.reporter_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "举报不存在")
    if report.status not in (ReportStatus.PENDING.value, ReportStatus.PROCESSING.value):
        raise HTTPException(status.HTTP_409_CONFLICT, "该举报事项已处理归档，不再接受补充")
    await validate_upload_keys(db, body.evidence_keys, owner_id=user.id, namespace="report")
    supplement = ReportSupplement(
        report_id=report.id, author_id=user.id, content=body.content.strip(), evidence_keys=body.evidence_keys
    )
    db.add(supplement)
    await db.flush()
    try:
        await stored_objects.mark_committed(
            db, body.evidence_keys, ref_type="report_supplement", ref_id=supplement.id
        )
    except stored_objects.StoredObjectUnavailable:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "证据已被回收，请重新上传"
        ) from None
    await audit_service.record_event(
        db,
        audit_service.EVENT_REPORT_SUPPLEMENT,
        target_type="report",
        target_id=report.id,
        after={"supplemented": True},
    )
    await db.commit()
    return {"detail": "补充已提交"}


@router.get("/mine")
async def my_reports(user: CurrentUser, db: DbSession) -> list[dict]:
    result = await db.exec(
        select(Report).where(col(Report.reporter_id) == user.id).order_by(col(Report.id).desc())
    )
    from app.storage.base import get_storage

    storage = get_storage()
    items = []
    for report in result:
        data = _report_out(report)
        data["result_reason"] = report.result_reason if report.result_confirmed else None
        data["target_title"] = None
        data["target_status"] = None
        target_product = None
        if report.target_type == "product":
            target_product = await db.get(Product, report.target_id)
        elif report.target_type == "comment":
            comment = await db.get(Comment, report.target_id)
            if comment is not None and comment.product_id:
                target_product = await db.get(Product, comment.product_id)
        elif report.target_type == "review":
            review = await db.get(TradeReview, report.target_id)
            if review is not None:
                trade = await db.get(Trade, review.trade_id)
                if trade is not None:
                    target_product = await db.get(Product, trade.product_id)
        elif report.target_type == "message":
            message = await db.get(Message, report.target_id)
            if message is not None:
                conversation = await db.get(Conversation, message.conversation_id)
                if conversation is not None and conversation.trade_id is not None:
                    trade = await db.get(Trade, conversation.trade_id)
                    if trade is not None:
                        target_product = await db.get(Product, trade.product_id)
        if target_product is not None:
            data["target_title"] = target_product.title
            data["target_status"] = target_product.status
        data["evidence_urls"] = [storage.public_url(key) for key in report.evidence_keys]
        supplements = (
            await db.exec(select(ReportSupplement).where(col(ReportSupplement.report_id) == report.id).order_by(col(ReportSupplement.id)))
        ).all()
        data["supplements"] = [
            {
                "id": s.id,
                "content": s.content,
                "evidence_urls": [storage.public_url(key) for key in s.evidence_keys],
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in supplements
        ]
        items.append(data)
    return items


@router.get("/received")
async def reports_about_me(user: CurrentUser, db: DbSession) -> list[dict]:
    """Reports about me: only matters actually handled, without revealing the reporter (4.18)."""
    my_products = (
        await db.exec(select(col(Product.id)).where(col(Product.seller_id) == user.id))
    ).all()
    my_comments = (
        await db.exec(select(col(Comment.id)).where(col(Comment.author_id) == user.id))
    ).all()
    my_reviews = (
        await db.exec(select(col(TradeReview.id)).where(col(TradeReview.reviewer_id) == user.id))
    ).all()
    result = await db.exec(
        select(Report).where(
            col(Report.status) == ReportStatus.HANDLED.value,
            (
                (col(Report.target_type) == "user") & (col(Report.target_id) == user.id)
            ) | (
                (col(Report.target_type) == "product") & (col(Report.target_id).in_(my_products or [0]))
            ) | (
                (col(Report.target_type) == "comment") & (col(Report.target_id).in_(my_comments or [0]))
            ) | (
                (col(Report.target_type) == "review") & (col(Report.target_id).in_(my_reviews or [0]))
            ) | (
                (col(Report.target_type) == "message") & (
                    col(Report.target_id).in_(select(col(Message.id)).where(col(Message.sender_id) == user.id))
                )
            ),
        ).order_by(col(Report.id).desc())
    )
    items = []
    for report in result:
        case = (await db.exec(
            select(DisposalCase).where(col(DisposalCase.report_id) == report.id).order_by(col(DisposalCase.id).desc()).limit(1)
        )).first()
        items.append(
            {
                "id": report.id,
                "target_type": report.target_type,
                "target_id": report.target_id,
                "status": report.status,
                "result_confirmed": report.result_confirmed,
                "public_result": report.public_result,
                "case_id": case.id if case else None,
                "disposal_reason": case.conclusion_reason if case else None,
                "created_at": report.created_at.isoformat() if report.created_at else None,
            }
        )
    return items
