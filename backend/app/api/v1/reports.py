"""举报（C-12/BR-25）：提交、补充说明、我的举报与我收到的举报。"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DbSession, ensure_can_write
from app.models import Comment, DisposalCase, Message, Product, Report, ReportSupplement, TradeReview, User
from app.models.enums import CaseType, ReportStatus, ReportTargetType
from app.services import cases as case_service

router = APIRouter(prefix="/reports", tags=["reports"])

# 先去空白再校验长度：全空白输入不能作为有效理由/补充内容写入。
_NonBlank500 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
_NonBlank2000 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class ReportCreateIn(BaseModel):
    target_type: str = Field(pattern="^(product|comment|message|review|user)$")
    target_id: int
    reason: _NonBlank500
    detail: str | None = Field(default=None, max_length=2000)
    evidence_keys: list[str] = []


class SupplementIn(BaseModel):
    content: _NonBlank2000
    evidence_keys: list[str] = []


class PublicReportOut(BaseModel):
    """匿名公开结果的白名单字段；不包含对象、举报人、事项及私有理由。"""

    id: int
    target_type: str
    status: str
    public_result: str | None
    closed_at: str | None


async def _target_is_reportable(db, target_type: str, target_id: int) -> bool:
    """按对象实际有效性判断可否新增举报。

    逻辑删除的评论/评价及已撤销公开访问的商品不可作为新举报目标；其他类型
    不做需求未规定的额外失效推断（如下架不等于对象不存在）。
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
        "status": report.status,
        "result_confirmed": report.result_confirmed,
        "public_result": report.public_result if report.result_confirmed else None,
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "closed_at": report.closed_at.isoformat() if report.closed_at else None,
    }
    return data


@router.post("", status_code=201)
async def create_report(body: ReportCreateIn, user: CurrentUser, db: DbSession) -> dict:
    """提交举报：明确对象与原因，证据可选；未结举报在原事项补充（BR-25）。"""
    ensure_can_write(user)
    # 已归档的同一用户+对象举报不可重新提交；先查终态/已关闭记录，兼容历史脏数据多条。
    closed_report_id = await db.scalar(
        select(Report.id)
        .where(
            Report.reporter_id == user.id,
            Report.target_type == body.target_type,
            Report.target_id == body.target_id,
            or_(
                Report.status.in_([ReportStatus.HANDLED.value, ReportStatus.UNFOUNDED.value]),
                Report.closed_at.is_not(None),
            ),
        )
        .order_by(Report.id.desc())
        .limit(1)
    )
    if closed_report_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "您对该对象的举报已处理归档，不能重复提交")
    if not await _target_is_reportable(db, body.target_type, body.target_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "举报对象不存在或已失效，无法提交举报")
    open_report = await db.scalar(
        select(Report).where(
            Report.reporter_id == user.id,
            Report.target_type == body.target_type,
            Report.target_id == body.target_id,
            Report.status.in_([ReportStatus.PENDING.value, ReportStatus.PROCESSING.value]),
        )
    )
    if open_report:
        return {
            "detail": "您对该对象已有未处理完的举报，请在原事项补充说明或证据",
            "existing_report_id": open_report.id,
        }
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
    # 解析被举报内容的责任用户，作为事项沟通对象（问询/申辩）
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
    await db.commit()
    return {"id": report.id, "detail": "举报已提交，进入待处理池"}


@router.post("/{report_id}/supplements")
async def add_supplement(report_id: int, body: SupplementIn, user: CurrentUser, db: DbSession) -> dict:
    """在原举报事项补充说明/证据；结案后归档不再接受（BR-25）。"""
    ensure_can_write(user)
    report = await db.get(Report, report_id)
    if not report or report.reporter_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "举报不存在")
    if report.status not in (ReportStatus.PENDING.value, ReportStatus.PROCESSING.value):
        raise HTTPException(status.HTTP_409_CONFLICT, "该举报事项已处理归档，不再接受补充")
    supplement = ReportSupplement(
        report_id=report.id, author_id=user.id, content=body.content.strip(), evidence_keys=body.evidence_keys
    )
    db.add(supplement)
    await db.commit()
    return {"detail": "补充已提交"}


@router.get("/public", response_model=list[PublicReportOut])
async def public_reports(
    user: CurrentUser,
    db: DbSession,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
) -> list[PublicReportOut]:
    """匿名公开举报结果（BR-25）：仅管理员确认的终态记录，登录用户可读。

    包括封禁用户的公共只读访问；显式白名单输出，绝不返回举报人、对象 ID、
    事项、私有理由或沟通内容。
    """
    result = await db.execute(
        select(Report)
        .where(
            Report.result_confirmed.is_(True),
            Report.status.in_([ReportStatus.HANDLED.value, ReportStatus.UNFOUNDED.value]),
        )
        .order_by(Report.closed_at.desc(), Report.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [
        PublicReportOut(
            id=report.id,
            target_type=report.target_type,
            status=report.status,
            public_result=report.public_result,
            closed_at=report.closed_at.isoformat() if report.closed_at else None,
        )
        for report in result.scalars()
    ]


@router.get("/mine")
async def my_reports(user: CurrentUser, db: DbSession) -> list[dict]:
    result = await db.execute(
        select(Report).where(Report.reporter_id == user.id).order_by(Report.id.desc())
    )
    items = []
    for report in result.scalars():
        data = _report_out(report)
        supplements = (
            await db.execute(select(ReportSupplement).where(ReportSupplement.report_id == report.id).order_by(ReportSupplement.id))
        ).scalars().all()
        data["supplements"] = [
            {"id": s.id, "content": s.content, "created_at": s.created_at.isoformat() if s.created_at else None}
            for s in supplements
        ]
        items.append(data)
    return items


@router.get("/received")
async def reports_about_me(user: CurrentUser, db: DbSession) -> list[dict]:
    """我收到的举报：仅列已实际处置事项，不显示举报人（4.18）。"""
    my_products = (
        await db.execute(select(Product.id).where(Product.seller_id == user.id))
    ).scalars().all()
    my_comments = (
        await db.execute(select(Comment.id).where(Comment.author_id == user.id))
    ).scalars().all()
    my_reviews = (
        await db.execute(select(TradeReview.id).where(TradeReview.reviewer_id == user.id))
    ).scalars().all()
    result = await db.execute(
        select(Report).where(
            Report.status == ReportStatus.HANDLED.value,
            (
                (Report.target_type == "user") & (Report.target_id == user.id)
            ) | (
                (Report.target_type == "product") & (Report.target_id.in_(my_products or [0]))
            ) | (
                (Report.target_type == "comment") & (Report.target_id.in_(my_comments or [0]))
            ) | (
                (Report.target_type == "review") & (Report.target_id.in_(my_reviews or [0]))
            ),
        ).order_by(Report.id.desc())
    )
    items = []
    for report in result.scalars():
        case = await db.scalar(
            select(DisposalCase).where(DisposalCase.report_id == report.id).order_by(DisposalCase.id.desc()).limit(1)
        )
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
