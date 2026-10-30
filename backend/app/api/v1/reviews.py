"""交易评价（C-11/BR-24）：完成后互评，仅本人按发表/收到查看。"""

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.api.deps import CurrentUser, DbSession, ensure_can_write
from app.models import Trade, TradeReview, User
from app.models.enums import TradeStatus
from app.services import audit as audit_service

router = APIRouter(prefix="/trades", tags=["reviews"])


class ReviewCreateIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    content: str = Field(default="", max_length=1000)


@router.post("/{trade_id}/review", status_code=201)
async def create_review(trade_id: int, body: ReviewCreateIn, user: CurrentUser, db: DbSession) -> dict:
    """已完成交易双方互评，每方每笔一条（BR-24）。"""
    ensure_can_write(user)
    trade = await db.get(Trade, trade_id)
    if not trade or user.id not in (trade.buyer_id, trade.seller_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
    if trade.status != TradeStatus.COMPLETED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅已完成交易可评价")
    existing = (await db.exec(
        select(TradeReview).where(col(TradeReview.trade_id) == trade.id, col(TradeReview.reviewer_id) == user.id)
    )).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "您已评价过本笔交易")
    reviewee_id = trade.seller_id if user.id == trade.buyer_id else trade.buyer_id
    review = TradeReview(
        trade_id=trade.id,
        reviewer_id=user.id,
        reviewee_id=reviewee_id,
        rating=body.rating,
        content=body.content.strip(),
    )
    db.add(review)
    await db.flush()
    await audit_service.record_event(
        db,
        audit_service.EVENT_TRADE_REVIEW_CREATE,
        target_type="trade_review",
        target_id=review.id,
        after={"trade_id": trade.id, "rating": review.rating},
    )
    await db.commit()
    return {"id": review.id, "detail": "评价已提交"}


reviews_router = APIRouter(prefix="/me/reviews", tags=["reviews"])


def _review_out(review: TradeReview, other_name: str, trade_status: str) -> dict:
    return {
        "id": review.id,
        "trade_id": review.trade_id,
        "rating": review.rating,
        "content": review.content,
        "other_party_name": other_name,
        "trade_status": trade_status,
        "created_at": review.created_at.isoformat() if review.created_at else None,
        "deleted": review.deleted_at is not None,
    }


@reviews_router.get("")
async def my_reviews(user: CurrentUser, db: DbSession, type: str = Query(pattern="^(published|received)$", default="published")) -> list[dict]:
    """我的评价：按发表/收到查看，均关联交易（FR-12）。"""
    if type == "published":
        query = select(TradeReview).where(col(TradeReview.reviewer_id) == user.id)
    else:
        query = select(TradeReview).where(col(TradeReview.reviewee_id) == user.id)
    result = await db.exec(query.order_by(col(TradeReview.id).desc()))
    reviews = list(result)
    other_ids = [r.reviewee_id if type == "published" else r.reviewer_id for r in reviews]
    names: dict[int, str] = {}
    if other_ids:
        rows = await db.exec(select(col(User.id), col(User.display_name)).where(col(User.id).in_(set(other_ids))))
        names = {uid: n for uid, n in rows.all()}
    trade_status_map = {}
    trade_ids = {r.trade_id for r in reviews}
    if trade_ids:
        rows = await db.exec(select(col(Trade.id), col(Trade.status)).where(col(Trade.id).in_(trade_ids)))
        trade_status_map = {tid: st for tid, st in rows.all()}
    out = []
    for review in reviews:
        other_id = review.reviewee_id if type == "published" else review.reviewer_id
        item = _review_out(review, names.get(other_id, ""), trade_status_map.get(review.trade_id, ""))
        item["other_party_id"] = other_id
        item["direction"] = type
        out.append(item)
    return out
