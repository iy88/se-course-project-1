"""商品页评论（C-06/BR-17）：登录用户评论，卖方回复，作者删除本人评论。"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import CurrentUser, DbSession, ensure_can_write
from app.core.config import get_settings
from app.kv.base import get_kv
from app.models import Comment, Product, Report, User
from app.models.enums import ProductStatus, ReportStatus
from app.services import audit as audit_service
from app.services.products import is_detail_visible

router = APIRouter(prefix="/products/{product_id}/comments", tags=["comments"])


class CommentIn(BaseModel):
    content: str = Field(min_length=1)
    reply_to_comment_id: int | None = None


async def _check_product_commentable(db: AsyncSession, product_id: int) -> Product:
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    # 公开可交易或交易中可评论；已下架或撤销公开访问禁止新增（BR-17）
    if product.display_restricted or product.status not in (
        ProductStatus.LISTED.value,
        ProductStatus.IN_TRANSACTION.value,
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "当前商品状态不可评论或回复")
    return product


@router.get("")
async def list_comments(product_id: int, user: CurrentUser, db: DbSession) -> list[dict]:
    product = await db.get(Product, product_id)
    if not product or not is_detail_visible(user, product):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在或不可见")
    result = await db.exec(
        select(Comment).where(col(Comment.product_id) == product_id).order_by(col(Comment.id))
    )
    comments = list(result)
    author_ids = {c.author_id for c in comments} | {c.reply_to_user_id for c in comments if c.reply_to_user_id}
    authors: dict[int, str] = {}
    if author_ids:
        rows = await db.exec(select(col(User.id), col(User.display_name)).where(col(User.id).in_(author_ids)))
        authors = {uid: name for uid, name in rows.all()}
    removed_results: dict[int, str | None] = {}
    removed_ids = [c.id for c in comments if c.deleted_at is not None]
    if removed_ids:
        linked_reports = (await db.exec(
            select(Report)
            .where(
                col(Report.target_type) == "comment",
                col(Report.target_id).in_(removed_ids),
                col(Report.status) == ReportStatus.HANDLED.value,
                col(Report.result_confirmed).is_(True),
                col(Report.public_result).is_not(None),
            )
            .order_by(col(Report.id).desc())
        )).all()
        for linked in linked_reports:
            removed_results.setdefault(linked.target_id, linked.public_result)

    return [
        {
            "id": c.id,
            "author_id": c.author_id,
            "author_name": authors.get(c.author_id, ""),
            "content": c.content if c.deleted_at is None else "该评论已删除",
            "reply_to_comment_id": c.reply_to_comment_id,
            "reply_to_user_id": c.reply_to_user_id,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "deleted": c.deleted_at is not None,
            "report_result": removed_results.get(c.id) if c.deleted_at is not None else None,
        }
        for c in comments
    ]


@router.post("", status_code=201)
async def add_comment(product_id: int, body: CommentIn, user: CurrentUser, db: DbSession) -> dict:
    """登录用户评论公开可交易或交易中的商品（BR-17）。"""
    ensure_can_write(user)
    settings = get_settings()
    content = body.content.strip()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "评论内容不能为空")
    product = await _check_product_commentable(db, product_id)
    kv = get_kv()
    rate_key = f"comment-rate:{user.id}"
    count = await kv.incr_with_ttl(rate_key, settings.comment_rate_limit_seconds)
    if count > settings.comment_rate_limit_count:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "评论过于频繁，请稍后再试")

    reply_to_comment: Comment | None = None
    if body.reply_to_comment_id is not None:
        reply_to_comment = await db.get(Comment, body.reply_to_comment_id)
        if not reply_to_comment or reply_to_comment.product_id != product_id or reply_to_comment.deleted_at:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "回复目标评论不存在")
        # 仅该商品卖方可回复买方评论；不支持买方互相回复（BR-17）
        if user.id != product.seller_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "仅商品卖方可回复评论")
        if reply_to_comment.author_id == product.seller_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "卖方仅可回复买方评论")
    comment = Comment(
        product_id=product_id,
        author_id=user.id,
        content=content,
        reply_to_comment_id=reply_to_comment.id if reply_to_comment else None,
        reply_to_user_id=reply_to_comment.author_id if reply_to_comment else None,
    )
    db.add(comment)
    await db.flush()
    await audit_service.record_event(
        db,
        audit_service.EVENT_COMMENT_CREATE,
        target_type="comment",
        target_id=comment.id,
        after={"product_id": product_id, "reply_to_comment_id": comment.reply_to_comment_id},
    )
    await db.commit()
    return {"id": comment.id, "detail": "已发表"}


@router.delete("/{comment_id}")
async def delete_comment(product_id: int, comment_id: int, user: CurrentUser, db: DbSession) -> dict:
    """作者删除本人评论：逻辑删除保留历史（BR-17/4.18）。"""
    ensure_can_write(user)
    comment = await db.get(Comment, comment_id)
    if not comment or comment.product_id != product_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "评论不存在")
    if comment.author_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅可删除本人评论")
    if comment.deleted_at is None:
        comment.deleted_at = datetime.now(UTC)
        comment.deleted_by_id = user.id
        await audit_service.record_event(
            db,
            audit_service.EVENT_COMMENT_DELETE,
            target_type="comment",
            target_id=comment.id,
            after={"deleted": True, "product_id": product_id},
        )
        await db.commit()
    return {"detail": "已删除"}
