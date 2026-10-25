"""交易状态机核心操作：转移留痕、结束联动（商品下架/分支归档/本笔解冻）、通知。"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, Trade, TradeTransition, User
from app.models.enums import ENDED_TRADE_STATUSES, ProductStatus, TradeStatus
from app.services import conversations as conversation_service
from app.services import products as product_service
from app.services.notifications import notify


def now_utc() -> datetime:
    return datetime.now(UTC)


async def record_transition(
    db: AsyncSession,
    trade: Trade,
    from_status: str,
    to_status: str,
    *,
    trigger: str,
    actor: User | None = None,
    actor_role: str = "system",
    reason: str | None = None,
    basis_case_id: int | None = None,
) -> None:
    db.add(
        TradeTransition(
            trade_id=trade.id,
            from_status=from_status,
            to_status=to_status,
            actor_id=actor.id if actor else None,
            actor_role=actor_role,
            trigger=trigger,
            reason=reason,
            basis_case_id=basis_case_id,
        )
    )


async def product_snapshot(db: AsyncSession, product: Product) -> dict:
    """交易时内容快照（BR-30）。"""
    images = await product_service.load_product_images(db, product.id)
    tags = await product_service.load_product_tags(db, product.id)
    return {
        "product_id": product.id,
        "title": product.title,
        "description": product.description,
        "price_cents": product.price_cents,
        "images": [i.file_key for i in images],
        "tags": [t.name for t in tags],
        "captured_at": now_utc().isoformat(),
    }


async def finish_trade(
    db: AsyncSession,
    trade: Trade,
    *,
    to_status: TradeStatus,
    trigger: str,
    actor: User | None = None,
    actor_role: str = "system",
    reason: str | None = None,
    basis_case_id: int | None = None,
    title: str = "",
) -> Trade:
    """交易结束统一联动：状态、本笔解冻、分支归档、商品默认下架（TR-15/17/18、BR-14/33）。"""
    from_status = trade.status
    trade.status = to_status.value
    trade.finished_at = now_utc()
    trade.confirm_wait_started_at = None
    trade.cancel_requested_by_id = None
    trade.cancel_requested_at = None
    # 已完成/已终止自动解除本笔冻结，其他冻结/封禁保留（BR-33）
    if trade.frozen:
        trade.frozen = False
    await record_transition(
        db, trade, from_status, to_status.value,
        trigger=trigger, actor=actor, actor_role=actor_role, reason=reason, basis_case_id=basis_case_id,
    )
    await conversation_service.archive_trade_branch(db, trade.id)
    product = await db.get(Product, trade.product_id)
    if product and product.status == ProductStatus.IN_TRANSACTION.value:
        product.status = ProductStatus.DELISTED.value
        product.delisted_at = now_utc()
    label = "已完成" if to_status == TradeStatus.COMPLETED else "已终止"
    scope = f"（{title}）" if title else ""
    await notify(
        db,
        [trade.buyer_id, trade.seller_id],
        "trade_completed" if to_status == TradeStatus.COMPLETED else "trade_terminated",
        f"交易#{trade.id}{label}",
        (
            f"交易#{trade.id}{scope}已{label}。"
            + ("可从我的交易进入评价。" if to_status == TradeStatus.COMPLETED else "")
            + "商品默认已下架，卖方可按资格选择继续上架。"
        ),
        link_type="trade",
        link_id=trade.id,
    )
    return trade
