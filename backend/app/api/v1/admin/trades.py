"""管理员交易处置（BR-08/33）：冻结/解冻、有依据调整全部状态。"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentAdmin, DbSession
from app.models import CompletionConfirmation, Product, Trade, TradeAgreement, TradeTransition, User
from app.models.enums import TradeStatus
from app.services import moderation
from app.services import trade_ops

router = APIRouter(prefix="/admin/trades", tags=["admin-trades"])

ALLOWED_ADJUST_TARGETS = {s.value for s in TradeStatus}


async def admin_trade_view(db, trade_id: int) -> dict | None:
    """管理视角交易概要（含约定/确认/转移历史）。"""
    trade = await db.get(Trade, trade_id)
    if not trade:
        return None
    buyer = await db.get(User, trade.buyer_id)
    seller = await db.get(User, trade.seller_id)
    product = await db.get(Product, trade.product_id)
    agreements = (
        await db.execute(select(TradeAgreement).where(TradeAgreement.trade_id == trade.id).order_by(TradeAgreement.id))
    ).scalars().all()
    confirms = (
        await db.execute(
            select(CompletionConfirmation).where(CompletionConfirmation.trade_id == trade.id).order_by(CompletionConfirmation.id)
        )
    ).scalars().all()
    transitions = (
        await db.execute(select(TradeTransition).where(TradeTransition.trade_id == trade.id).order_by(TradeTransition.id))
    ).scalars().all()
    return {
        "id": trade.id,
        "status": trade.status,
        "frozen": trade.frozen,
        "frozen_reason": trade.frozen_reason,
        "buyer": {"id": buyer.id, "display_name": buyer.display_name} if buyer else None,
        "seller": {"id": seller.id, "display_name": seller.display_name} if seller else None,
        "product": {"id": product.id, "title": product.title, "status": product.status} if product else None,
        "product_snapshot": trade.product_snapshot_json,
        "current_agreement_id": trade.current_agreement_id,
        "agreements": [
            {
                "id": a.id,
                "round_no": a.round_no,
                "proposer_id": a.proposer_id,
                "status": a.status,
                "delivery_time": a.delivery_time,
                "delivery_location": a.delivery_location,
                "delivery_method": a.delivery_method,
                "amount_cents": a.amount_cents,
                "payment_method": a.payment_method,
                "payment_timing": a.payment_timing,
            }
            for a in agreements
        ],
        "confirmations": [
            {
                "id": c.id,
                "confirmer_id": c.confirmer_id,
                "note": c.note,
                "is_current": c.is_current,
                "confirmed_at": c.confirmed_at.isoformat() if c.confirmed_at else None,
            }
            for c in confirms
        ],
        "confirm_wait_started_at": trade.confirm_wait_started_at.isoformat() if trade.confirm_wait_started_at else None,
        "transitions": [
            {
                "from_status": t.from_status,
                "to_status": t.to_status,
                "actor_id": t.actor_id,
                "actor_role": t.actor_role,
                "trigger": t.trigger,
                "reason": t.reason,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in transitions
        ],
        "created_at": trade.created_at.isoformat() if trade.created_at else None,
    }


class FreezeIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    case_id: int | None = None


class UnfreezeIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class AdjustIn(BaseModel):
    to_status: str
    reason: str = Field(min_length=1, max_length=500)
    case_id: int | None = None  # 关联处置事项（依据）


@router.get("/{trade_id}")
async def get_trade(trade_id: int, admin: CurrentAdmin, db: DbSession) -> dict:
    """管理视角交易详情（BR-27：按事项必要范围访问）。"""
    view = await admin_trade_view(db, trade_id)
    if not view:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
    return view


@router.post("/{trade_id}/freeze")
async def freeze(trade_id: int, body: FreezeIn, admin: CurrentAdmin, db: DbSession) -> dict:
    trade = await db.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
    await moderation.freeze_trade(db, trade, body.reason.strip(), body.case_id, admin.id)
    await db.commit()
    return {"detail": "交易已冻结"}


@router.post("/{trade_id}/unfreeze")
async def unfreeze(trade_id: int, body: UnfreezeIn, admin: CurrentAdmin, db: DbSession) -> dict:
    """非结束状态的解冻须管理员有依据处理（BR-33）。"""
    trade = await db.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
    if trade.status in (TradeStatus.COMPLETED.value, TradeStatus.TERMINATED.value):
        raise HTTPException(status.HTTP_409_CONFLICT, "已结束交易无冻结标记")
    await moderation.unfreeze_trade(db, trade, body.reason.strip(), admin.id)
    await db.commit()
    return {"detail": "冻结已解除"}


@router.post("/{trade_id}/adjust")
async def adjust_status(trade_id: int, body: AdjustIn, admin: CurrentAdmin, db: DbSession) -> dict:
    """BR-08：认领管理员可有依据调整全部状态（包括直接完成），不伪造双方确认。"""
    if body.to_status not in ALLOWED_ADJUST_TARGETS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "非法目标状态")
    trade = await db.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "交易不存在")
    if trade.status == body.to_status:
        raise HTTPException(status.HTTP_409_CONFLICT, "交易已处于目标状态")
    role = "admin"
    reason = body.reason.strip()
    to_status = TradeStatus(body.to_status)

    if to_status in (TradeStatus.COMPLETED, TradeStatus.TERMINATED):
        # 结束联动：解本笔冻结、归档分支、商品默认下架（BR-33/14）
        await trade_ops.finish_trade(
            db, trade, to_status=to_status, trigger=f"admin_adjust_{body.to_status}",
            actor=admin, actor_role=role, reason=reason, basis_case_id=body.case_id,
        )
    elif to_status == TradeStatus.IN_PROGRESS.value and trade.status in (
        TradeStatus.DISPUTED.value, TradeStatus.ABNORMAL.value
    ):
        # 恢复进行中：清空当前完成确认、保留历史及有效约定；恢复不启动计时（4.15）
        confirms = await db.execute(
            select(CompletionConfirmation).where(
                CompletionConfirmation.trade_id == trade.id, CompletionConfirmation.is_current.is_(True)
            )
        )
        for row in confirms.scalars():
            row.is_current = False
        from_status = trade.status
        trade.status = TradeStatus.IN_PROGRESS.value
        trade.confirm_wait_started_at = None
        trade.resolution_confirmed_by_id = None
        trade.resolution_confirmed_at = None
        await trade_ops.record_transition(
            db, trade, from_status, TradeStatus.IN_PROGRESS.value,
            trigger="admin_restore", actor=admin, actor_role=role, reason=reason, basis_case_id=body.case_id,
        )
    else:
        from_status = trade.status
        trade.status = to_status.value
        if to_status == TradeStatus.PENDING_ACCEPTANCE.value:
            trade.finished_at = None
        await trade_ops.record_transition(
            db, trade, from_status, to_status.value,
            trigger="admin_adjust", actor=admin, actor_role=role, reason=reason, basis_case_id=body.case_id,
        )
        # 接受/进行中联动商品锁单展示
        product = await db.get(Product, trade.product_id)
        if product:
            if to_status == TradeStatus.IN_PROGRESS.value and product.status == ProductStatus.LISTED.value:
                product.status = ProductStatus.IN_TRANSACTION.value
            elif to_status in (TradeStatus.PENDING_ACCEPTANCE.value, TradeStatus.REJECTED.value, TradeStatus.WITHDRAWN.value, TradeStatus.CLOSED.value) and product.status == ProductStatus.IN_TRANSACTION.value:
                product.status = ProductStatus.LISTED.value
    await db.commit()
    return {"detail": f"交易状态已调整为 {body.to_status}，已通知双方并留据"}

