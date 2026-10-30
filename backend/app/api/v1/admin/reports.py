"""举报管理（C-12/BR-25/26）：核查、结论与处置动作、匿名公开结果。"""

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.api.deps import CurrentAdmin, DbSession
from app.models import (
    Comment,
    DisposalCase,
    Message,
    Product,
    Report,
    Trade,
    TradeReview,
    User,
)
from app.models.enums import CaseStatus, CaseType, ReportStatus
from app.services import audit as audit_service
from app.services import cases as case_service
from app.services import moderation
from app.services.cases import ensure_claimant
from app.services.notifications import notify

router = APIRouter(prefix="/admin/reports", tags=["admin-reports"])


class ReportActionsIn(BaseModel):
    remove_content: bool = False
    restrict_display: bool = False
    freeze_trade: bool = False
    ban_user: bool = False
    ban_reason: str | None = Field(default=None, max_length=500)


class ReportDecisionIn(BaseModel):
    outcome: str = Field(pattern="^(unfounded|handled)$")  # 无法认定/不予处理 或 认定违规并处置
    reason: str = Field(min_length=1, max_length=500)
    public_summary: str | None = Field(default=None, max_length=500)  # 匿名公开的结果说明
    basis: str | None = Field(default=None, max_length=500)
    actions: ReportActionsIn = ReportActionsIn()


async def target_snapshot(db, report: Report) -> dict | None:
    """举报对象内容快照（限认领事项必要范围，BR-19）。"""
    ttype, tid = report.target_type, report.target_id
    if ttype == "product":
        product = await db.get(Product, tid)
        if not product:
            return {"type": ttype, "missing": True}
        return {
            "type": ttype,
            "id": product.id,
            "title": product.title,
            "description": product.description,
            "price_cents": product.price_cents,
            "status": product.status,
            "image_keys": [i.file_key for i in product.images],
            "seller_id": product.seller_id,
        }
    if ttype == "comment":
        comment = await db.get(Comment, tid)
        if not comment:
            return {"type": ttype, "missing": True}
        return {"type": ttype, "id": comment.id, "content": comment.content, "author_id": comment.author_id, "product_id": comment.product_id, "deleted": comment.deleted_at is not None}
    if ttype == "review":
        review = await db.get(TradeReview, tid)
        if not review:
            return {"type": ttype, "missing": True}
        return {"type": ttype, "id": review.id, "rating": review.rating, "content": review.content, "reviewer_id": review.reviewer_id, "trade_id": review.trade_id}
    if ttype == "message":
        from app.models import Message

        message = await db.get(Message, tid)
        if not message:
            return {"type": ttype, "missing": True}
        return {"type": ttype, "id": message.id, "content": message.content, "sender_id": message.sender_id, "conversation_id": message.conversation_id}
    if ttype == "user":
        user = await db.get(User, tid)
        if not user:
            return {"type": ttype, "missing": True}
        return {"type": ttype, "id": user.id, "display_name": user.display_name, "status": user.status}
    return None


async def _report_case(db, case_id: int, admin) -> tuple[DisposalCase, Report]:
    case = await case_service.lock_case_for_update(db, case_id)
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "事项不存在")
    await ensure_claimant(case, admin.id)
    if case.case_type != CaseType.REPORT.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该事项不是举报事项")
    report = await db.get(Report, case.report_id)
    if not report:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "举报数据不完整")
    return case, report


async def resolve_target_user_sync(db, report: Report) -> User | None:
    """被举报内容的责任用户（封禁对象）。"""
    ttype, tid = report.target_type, report.target_id
    if ttype == "user":
        return await db.get(User, tid)
    if ttype == "product":
        product = await db.get(Product, tid)
        return await db.get(User, product.seller_id) if product else None
    if ttype == "comment":
        comment = await db.get(Comment, tid)
        return await db.get(User, comment.author_id) if comment else None
    if ttype == "review":
        review = await db.get(TradeReview, tid)
        return await db.get(User, review.reviewer_id) if review else None
    if ttype == "message":
        from app.models import Message

        message = await db.get(Message, tid)
        return await db.get(User, message.sender_id) if message else None
    return None


async def _resolve_related_trades(db, report: Report, case: DisposalCase) -> list[Trade]:
    """违规涉及的交易（冻结对象）。"""
    trades: list[Trade] = []
    if case.trade_id:
        trade = await db.get(Trade, case.trade_id)
        if trade:
            trades.append(trade)
    if report.target_type == "product":
        product = await db.get(Product, report.target_id)
        if product:
            locking = (await db.exec(
                select(Trade).where(
                    col(Trade.product_id) == product.id,
                    col(Trade.status).in_(["in_progress", "disputed", "abnormal"]),
                )
            )).first()
            if locking:
                trades.append(locking)
    if report.target_type == "message":
        from app.models import Conversation

        message = await db.get(Message, report.target_id)
        if message:
            conversation = await db.get(Conversation, message.conversation_id)
            if conversation and conversation.trade_id:
                trade = await db.get(Trade, conversation.trade_id)
                if trade:
                    trades.append(trade)
    # 去重
    seen: set[int] = set()
    unique: list[Trade] = []
    for trade in trades:
        if trade.id not in seen:
            seen.add(trade.id)
            unique.append(trade)
    return unique


@router.get("")
async def list_reports(
    admin: CurrentAdmin,
    db: DbSession,
    report_status: str = Query(default="all", alias="status", pattern="^(pending|processing|unfounded|handled|all)$"),
) -> list[dict]:
    query = select(Report).order_by(col(Report.id).desc()).limit(200)
    if report_status != "all":
        query = query.where(col(Report.status) == report_status)
    result = await db.exec(query)
    items = []
    for report in result:
        case = (await db.exec(select(DisposalCase).where(col(DisposalCase.report_id) == report.id).order_by(col(DisposalCase.id).desc()).limit(1))).first()
        items.append(
            {
                "id": report.id,
                "target_type": report.target_type,
                "target_id": report.target_id,
                "reason": report.reason,
                "detail": report.detail,
                "evidence_keys": report.evidence_keys,
                "status": report.status,
                "result_confirmed": report.result_confirmed,
                "public_result": report.public_result,
                "created_at": report.created_at.isoformat() if report.created_at else None,
                "case_id": case.id if case else None,
                "case_status": case.status if case else None,
                "claimed_by_id": case.claimed_by_id if case else None,
            }
        )
    return items


@router.post("/cases/{case_id}/decision")
async def decide_report(case_id: int, body: ReportDecisionIn, admin: CurrentAdmin, db: DbSession) -> dict:
    """举报核查结论（BR-26/DT-05）：不予处理不告知被举报人；实际处置告知受影响者。"""
    case, report = await _report_case(db, case_id, admin)
    if case.status == CaseStatus.DISPOSED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "该事项已处置")

    if body.outcome == "unfounded":
        report.status = ReportStatus.UNFOUNDED.value
        report.result_confirmed = True
        report.public_result = body.public_summary or "依据不足，不予处理"
        report.result_reason = body.reason
        report.closed_at = case_service.now_utc()
        await case_service.add_case_message(
            db, case, sender_id=admin.id, role=case_service.DisposalMessageRole.ADMIN,
            kind=case_service.DisposalMessageKind.REPLY,
            content=f"核查结论：无法认定/不予处理。原因：{body.reason}",
        )
        await case_service.dispose_case(db, case, conclusion="不予处理", reason=body.reason, basis=body.basis)
        await notify(
            db, [report.reporter_id], "report_result", "您的举报已处理",
            f"处理结论：{report.public_result}。结果已匿名公开；不披露他人私人信息。",
            link_type="report", link_id=report.id,
        )
        await audit_service.record_event(
            db,
            audit_service.EVENT_ADMIN_REPORT_DECISION,
            target_type="report",
            target_id=report.id,
            reason_code="unfounded",
            after={"status": report.status, "case_id": case.id},
        )
        await db.commit()
        return {"detail": "已记录不予处理并通知举报人"}

    # 认定违规并处置
    actions = body.actions
    report.status = ReportStatus.HANDLED.value
    report.result_confirmed = True
    report.public_result = body.public_summary or "已认定违规并处理"
    report.result_reason = body.reason
    report.closed_at = case_service.now_utc()

    target_user = await resolve_target_user_sync(db, report)
    related_trades = await _resolve_related_trades(db, report, case)
    affected_users: set[int] = set()
    removal_note = ""

    if actions.remove_content:
        if report.target_type == "comment":
            comment = await db.get(Comment, report.target_id)
            if comment and comment.deleted_at is None:
                comment.deleted_at = case_service.now_utc()
                comment.deleted_by_id = admin.id
                comment.delete_reason = body.reason
                affected_users.add(comment.author_id)
                removal_note = "违规评论已移除"
        elif report.target_type == "review":
            review = await db.get(TradeReview, report.target_id)
            if review and review.deleted_at is None:
                review.deleted_at = case_service.now_utc()
                review.deleted_by_id = admin.id
                review.delete_reason = body.reason
                affected_users.add(review.reviewer_id)
                removal_note = "违规评价已移除"
        else:
            removal_note = "内容处置已记录"

    if actions.restrict_display and report.target_type == "product":
        product = await db.get(Product, report.target_id)
        if product:
            await moderation.restrict_product_display(db, product, f"违规处置：{body.reason}", case.id)
            affected_users.add(product.seller_id)
            removal_note = (removal_note + "；" if removal_note else "") + "涉事商品已停止公开访问"

    if actions.freeze_trade:
        for trade in related_trades:
            await moderation.freeze_trade(db, trade, f"违规处置：{body.reason}", case.id, admin.id)
            affected_users.update({trade.buyer_id, trade.seller_id})
        if related_trades:
            removal_note = (removal_note + "；" if removal_note else "") + "涉事交易已冻结"

    if actions.ban_user:
        if target_user is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "未能定位封禁对象用户")
        ban_reason = actions.ban_reason or body.reason
        await moderation.ban_user(
            db, target_user, reason=f"违规处置：{ban_reason}", basis=f"举报#{report.id}", case_id=case.id, admin_id=admin.id
        )
        affected_users.add(target_user.id)
        removal_note = (removal_note + "；" if removal_note else "") + "违规账户已封禁"

    await case_service.add_case_message(
        db, case, sender_id=admin.id, role=case_service.DisposalMessageRole.ADMIN,
        kind=case_service.DisposalMessageKind.REPLY,
        content=f"核查结论：认定违规并处置。原因：{body.reason}。处置：{removal_note or '记录在案'}",
    )
    await case_service.dispose_case(db, case, conclusion="认定违规并处置", reason=body.reason, basis=body.basis or f"举报#{report.id}")

    # 受影响者告知（隐去举报人身份）；举报人获结果通知
    if affected_users:
        await notify(
            db, sorted(affected_users), "disposal", "平台处置通知",
            f"您的相关内容/账户被处置：{removal_note or '记录在案'}。原因：{body.reason}。可从处置通知进入提交申辩。",
            link_type="case", link_id=case.id,
        )
    await notify(
        db, [report.reporter_id], "report_result", "您的举报已处理",
        f"处理结论：{report.public_result}。结果已匿名公开。",
        link_type="report", link_id=report.id,
    )
    await audit_service.record_event(
        db,
        audit_service.EVENT_ADMIN_REPORT_DECISION,
        target_type="report",
        target_id=report.id,
        reason_code="handled",
        after={
            "status": report.status,
            "case_id": case.id,
            "removed": actions.remove_content,
            "restricted": actions.restrict_display,
            "froze": actions.freeze_trade,
            "banned": actions.ban_user,
        },
    )
    await db.commit()
    return {"detail": f"已认定违规并处置：{removal_note or '记录在案'}"}
