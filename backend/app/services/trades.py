"""交易辅助（请求关闭、锁单校验等）；完整状态机见 api/v1/trades.py。"""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Trade
from app.models.enums import TradeStatus
from app.services.notifications import notify

LOCKING_STATUSES = [TradeStatus.IN_PROGRESS.value, TradeStatus.DISPUTED.value, TradeStatus.ABNORMAL.value]
BANNED_PENDING_REASON = "相关账户被封禁"
CLOSED_BY_LOCK = "商品已被其他用户锁单"
DISPLAY_REVOKED_REASON = "商品公开访问已撤销"
LOCK_CONFLICT_DETAIL = "商品已存在另一笔锁单交易，请先按该笔交易的适用规则处理后再恢复"


async def close_pending_requests_for_product(
    db: AsyncSession,
    product_id: int,
    reason: str,
    exclude_trade_ids: set[int] | None = None,
) -> list[Trade]:
    """商品下架/违规处置下架时关闭待接受请求（BR-02、TR-09），并归档对应分支。"""
    exclude = exclude_trade_ids or set()
    from app.services import conversations as conversation_service

    result = await db.execute(
        select(Trade).where(Trade.product_id == product_id, Trade.status == TradeStatus.PENDING_ACCEPTANCE.value)
    )
    closed: list[Trade] = []
    for trade in result.scalars():
        if trade.id in exclude:
            continue
        closed.append(trade)
    for trade in closed:
        from_status = trade.status
        trade.status = TradeStatus.CLOSED.value
        trade.close_reason = reason
        await _record_transition(db, trade, from_status, TradeStatus.CLOSED.value, "product_closed", reason)
        await conversation_service.archive_trade_branch(db, trade.id)
    await db.flush()
    return closed


async def close_pending_requests_for_user(
    db: AsyncSession,
    user_id: int,
    *,
    reason: str = BANNED_PENDING_REASON,
) -> list[Trade]:
    """D-52：封禁生效时关闭其作为买方或卖方参与的全部待接受请求。

    保留历史并归档分支；通知双方；已接受交易不在此关闭，按冻结规则处理。
    """
    from app.services import conversations as conversation_service

    result = await db.execute(
        select(Trade).where(
            Trade.status == TradeStatus.PENDING_ACCEPTANCE.value,
            (Trade.buyer_id == user_id) | (Trade.seller_id == user_id),
        )
    )
    closed = list(result.scalars())
    for trade in closed:
        from_status = trade.status
        trade.status = TradeStatus.CLOSED.value
        trade.close_reason = reason
        await _record_transition(db, trade, from_status, TradeStatus.CLOSED.value, "account_banned", reason)
        await conversation_service.archive_trade_branch(db, trade.id)
        await notify(
            db,
            [trade.buyer_id, trade.seller_id],
            "request_closed",
            "购买请求已关闭",
            f"交易请求 #{trade.id} 已关闭，原因：{reason}。历史记录保留，解除限制后不会重新打开该请求。",
            link_type="trade",
            link_id=trade.id,
            payload={"reason": reason, "closed_by": "account_ban"},
        )
    await db.flush()
    return closed


async def _record_transition(
    db: AsyncSession,
    trade: Trade,
    from_status: str,
    to_status: str,
    trigger: str,
    reason: str | None = None,
) -> None:
    from app.models import TradeTransition

    db.add(
        TradeTransition(
            trade_id=trade.id,
            from_status=from_status,
            to_status=to_status,
            actor_role="system",
            trigger=trigger,
            reason=reason,
        )
    )


async def get_locking_trade(db: AsyncSession, product_id: int) -> Trade | None:
    result = await db.execute(
        select(Trade).where(Trade.product_id == product_id, Trade.status.in_(LOCKING_STATUSES))
    )
    return result.scalar_one_or_none()


async def ensure_no_locking_conflict(db: AsyncSession, trade: Trade, target_status: str) -> None:
    """D-48：进入任何需锁单状态前显式检查同商品另一笔锁单。

    只读查询；冲突时抛 409，调用方尚未修改交易、确认、商品、分支或限制。
    """
    if target_status not in LOCKING_STATUSES:
        return
    other_id = await db.scalar(
        select(Trade.id)
        .where(
            Trade.product_id == trade.product_id,
            Trade.status.in_(LOCKING_STATUSES),
            Trade.id != trade.id,
        )
        .limit(1)
    )
    if other_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, LOCK_CONFLICT_DETAIL)


async def resolve_lock_integrity_error(
    db: AsyncSession,
    exc: IntegrityError,
    *,
    product_id: int,
) -> None:
    """D-48：预检后另一事务抢先提交锁单时，数据库唯一约束是最终裁决。

    必须回滚本次全部写入（状态、确认、商品、分支、通知、转移），再确认同商品
    确有另一笔锁单后映射 409；其他完整性错误原样抛出，避免吞掉真实缺陷。
    """
    await db.rollback()
    other_id = await db.scalar(
        select(Trade.id)
        .where(Trade.product_id == product_id, Trade.status.in_(LOCKING_STATUSES))
        .limit(1)
    )
    if other_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, LOCK_CONFLICT_DETAIL) from exc
    raise exc
