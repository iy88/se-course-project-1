"""交易辅助（请求关闭、锁单校验等）；完整状态机见 api/v1/trades.py。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Trade
from app.models.enums import TradeStatus

LOCKING_STATUSES = [TradeStatus.IN_PROGRESS.value, TradeStatus.DISPUTED.value, TradeStatus.ABNORMAL.value]


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
