"""Cross-domain business restriction helpers: user-level effects of trade freezes (BR-33, D-50)."""
from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Trade
from app.models.enums import TradeStatus

# Trade statuses still in an active lifecycle that may be administratively frozen (ended trades are unfrozen automatically)
ACTIVE_TRADE_STATUSES = (
    TradeStatus.PENDING_ACCEPTANCE.value,
    TradeStatus.IN_PROGRESS.value,
    TradeStatus.DISPUTED.value,
    TradeStatus.ABNORMAL.value,
)


async def has_active_frozen_trade(db: AsyncSession, user_id: int) -> bool:
    """Whether the account has any active trade freeze (matching either party role).

    D-50: a trade freeze alone, even without an account ban, also blocks publishing new
    products, voluntary delisting, listing, and relisting; unrelated compliant product
    edits are not blocked. Ban write restrictions are enforced first by ensure_can_write.
    """
    result = await db.exec(
        select(col(Trade.id))
        .where(
            col(Trade.frozen).is_(True),
            col(Trade.status).in_(ACTIVE_TRADE_STATUSES),
            or_(col(Trade.buyer_id) == user_id, col(Trade.seller_id) == user_id),
        )
        .limit(1)
    )
    return result.one_or_none() is not None


async def frozen_trade_party_ids(db: AsyncSession) -> set[int]:
    """User IDs of both parties for every actively frozen trade.

    BR-33's "suspend both parties' listing and trade actions" is a user-level
    restriction: a frozen user cannot advance trades in other trades either. To-do
    derivation uses this set to decide whether self/other is restricted.
    """
    result = await db.exec(
        select(col(Trade.buyer_id), col(Trade.seller_id)).where(
            col(Trade.frozen).is_(True),
            col(Trade.status).in_(ACTIVE_TRADE_STATUSES),
        )
    )
    frozen: set[int] = set()
    for buyer_id, seller_id in result.all():
        frozen.add(buyer_id)
        frozen.add(seller_id)
    return frozen
