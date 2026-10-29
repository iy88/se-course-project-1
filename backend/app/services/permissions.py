"""跨域业务限制辅助：交易冻结的用户级影响（BR-33、D-50）。"""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Trade
from app.models.enums import TradeStatus

# 仍处于有效生命周期、可能被管理冻结的交易状态（已结束交易冻结自动解除）
ACTIVE_TRADE_STATUSES = (
    TradeStatus.PENDING_ACCEPTANCE.value,
    TradeStatus.IN_PROGRESS.value,
    TradeStatus.DISPUTED.value,
    TradeStatus.ABNORMAL.value,
)


async def has_active_frozen_trade(db: AsyncSession, user_id: int) -> bool:
    """账户是否存在任一有效交易冻结（双方任一方身份命中）。

    D-50：仅交易冻结且账户未封禁时，也禁止发布新商品、主动下架、上架及重新上架；
    无关商品合规编辑不因此禁止。封禁的禁写限制由 ensure_can_write 优先执行。
    """
    result = await db.execute(
        select(Trade.id)
        .where(
            Trade.frozen.is_(True),
            Trade.status.in_(ACTIVE_TRADE_STATUSES),
            or_(Trade.buyer_id == user_id, Trade.seller_id == user_id),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def frozen_trade_party_ids(db: AsyncSession) -> set[int]:
    """任一有效冻结交易的双方用户 ID。

    BR-33 的“暂停双方上架及交易操作”是用户级限制：被冻结用户在其他交易中
    也不能推进交易。待办派生用此集合判断 self/other 是否受限。
    """
    result = await db.execute(
        select(Trade.buyer_id, Trade.seller_id).where(
            Trade.frozen.is_(True),
            Trade.status.in_(ACTIVE_TRADE_STATUSES),
        )
    )
    frozen: set[int] = set()
    for buyer_id, seller_id in result.all():
        frozen.add(buyer_id)
        frozen.add(seller_id)
    return frozen
