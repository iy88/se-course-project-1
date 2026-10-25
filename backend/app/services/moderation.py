"""管理处置动作：封禁/解除及联动（DT-03、BR-32/33、TR-09/10）。"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccountRestriction, Product, Trade, User
from app.models.enums import (
    AccountStatus,
    DisposalMessageKind,
    DisposalMessageRole,
    ProductStatus,
    RestrictionStatus,
    TradeStatus,
)
from app.services import cases as case_service
from app.services import conversations as conversation_service
from app.services import trades as trade_service
from app.services.notifications import notify


def now_utc() -> datetime:
    return datetime.now(UTC)


async def freeze_trade(db: AsyncSession, trade: Trade, reason: str, case_id: int | None, admin_id: int | None) -> None:
    """冻结整个交易进度（BR-33）：暂停双方操作，已结束交易不再冻结。"""
    if trade.status in (TradeStatus.COMPLETED.value, TradeStatus.TERMINATED.value) or trade.frozen:
        return
    trade.frozen = True
    trade.frozen_reason = reason
    trade.frozen_at = now_utc()
    trade.frozen_by_id = admin_id
    trade.frozen_case_id = case_id
    await trade_service._record_transition(
        db, trade, trade.status, trade.status, "trade_frozen", reason=reason
    )
    await notify(
        db, [trade.buyer_id, trade.seller_id], "trade_frozen", f"交易#{trade.id}已被冻结",
        f"原因：{reason}。冻结期间双方交易操作与双方间 IM 暂停，可通过处置沟通与管理员说明。",
        link_type="trade", link_id=trade.id,
    )


async def unfreeze_trade(db: AsyncSession, trade: Trade, reason: str, admin_id: int) -> None:
    """有依据解除冻结：其他有效限制保留（BR-33）。"""
    if not trade.frozen:
        return
    from app.models import TradeTransition

    trade.frozen = False
    db.add(
        TradeTransition(
            trade_id=trade.id,
            from_status=trade.status,
            to_status=trade.status,
            actor_id=admin_id,
            actor_role="admin",
            trigger="trade_unfrozen",
            reason=reason,
        )
    )
    await notify(
        db, [trade.buyer_id, trade.seller_id], "trade_unfrozen", f"交易#{trade.id}冻结已解除",
        f"原因：{reason}。其他有效限制（如有）继续适用。",
        link_type="trade", link_id=trade.id,
    )


async def restrict_product_display(db: AsyncSession, product: Product, reason: str, case_id: int | None) -> None:
    """违规撤销公开访问（TR-09）：展示限制与生命周期分开；关闭待接受请求并注明原因。"""
    if product.display_restricted:
        return
    product.display_restricted = True
    product.display_restricted_reason = reason
    product.display_restricted_at = now_utc()
    product.display_restricted_case_id = case_id
    closed = await trade_service.close_pending_requests_for_product(
        db, product.id, "商品因违规处置停止公开"
    )
    for trade in closed:
        await notify(
            db, [trade.buyer_id], "request_closed", "您的购买请求已关闭",
            f"商品「{product.title}」因平台处置停止公开，对应请求已关闭。",
            link_type="trade", link_id=trade.id,
        )


async def ban_user(
    db: AsyncSession,
    user: User,
    *,
    reason: str,
    basis: str | None,
    case_id: int | None,
    admin_id: int,
) -> AccountRestriction:
    """封禁（BR-32/DT-03）：禁写保读；冻结其进行中交易；其商品停止公开展示。"""
    if user.status == AccountStatus.BANNED.value:
        existing = await db.scalar(
            select(AccountRestriction).where(
                AccountRestriction.user_id == user.id, AccountRestriction.status == RestrictionStatus.ACTIVE.value
            )
        )
        if existing:
            return existing
    restriction = AccountRestriction(
        user_id=user.id,
        type="ban",
        status=RestrictionStatus.ACTIVE.value,
        reason=reason,
        basis=basis,
        case_id=case_id,
        created_by_id=admin_id,
    )
    db.add(restriction)
    user.status = AccountStatus.BANNED.value
    # DT-03：封禁任一交易方 → 冻结整个交易进度
    result = await db.execute(
        select(Trade).where(
            ((Trade.buyer_id == user.id) | (Trade.seller_id == user.id)),
            Trade.status.in_(trade_service.LOCKING_STATUSES),
        )
    )
    for trade in result.scalars():
        await freeze_trade(db, trade, f"交易方账户被平台封禁：{reason}", case_id, admin_id)
    # DT-03：封禁账户的商品 → 停止公开展示
    products = await db.execute(
        select(Product).where(Product.seller_id == user.id, Product.status == ProductStatus.LISTED.value)
    )
    for product in products.scalars():
        await restrict_product_display(db, product, f"发布者账户被平台封禁：{reason}", case_id)
    await db.flush()
    if case_id:
        from app.models import DisposalCase

        case = await db.get(DisposalCase, case_id)
        if case:
            await case_service.add_case_message(
                db, case, sender_id=None, role=DisposalMessageRole.SYSTEM,
                kind=DisposalMessageKind.NOTICE,
                content=f"账户已被封禁。原因：{reason}",
            )
    await notify(
        db, [user.id], "disposal", "账户已被平台封禁",
        f"原因：{reason}。封禁期间禁止发布、交易、评论等写操作，可浏览原有公开内容并通过处置沟通提交申辩。",
        link_type="case", link_id=case_id,
    )
    return restriction


async def unban_user(
    db: AsyncSession,
    user: User,
    *,
    lift_reason: str,
    case_id: int | None,
    admin_id: int,
) -> int:
    """解除封禁（TR-10）：恢复原权限及因处置停止的展示；原非在售商品不自动变为在售。"""
    result = await db.execute(
        select(AccountRestriction).where(
            AccountRestriction.user_id == user.id, AccountRestriction.status == RestrictionStatus.ACTIVE.value
        )
    )
    restrictions = list(result.scalars())
    if not restrictions:
        return 0
    now = now_utc()
    for restriction in restrictions:
        restriction.status = RestrictionStatus.LIFTED.value
        restriction.lifted_at = now
        restriction.lifted_by_id = admin_id
        restriction.lift_reason = lift_reason
    user.status = AccountStatus.NORMAL.value
    lifted_case_ids = {r.case_id for r in restrictions if r.case_id}
    # 仅恢复因本次解除的封禁而停止展示的商品（只解除限制标记，不改生命周期状态）
    products = await db.execute(
        select(Product).where(
            Product.seller_id == user.id,
            Product.display_restricted.is_(True),
            Product.display_restricted_case_id.in_(lifted_case_ids or {0}),
        )
    )
    for product in products.scalars():
        product.display_restricted = False
    # 解除因该账户封禁而冻结的交易
    trades = await db.execute(
        select(Trade).where(
            ((Trade.buyer_id == user.id) | (Trade.seller_id == user.id)),
            Trade.frozen.is_(True),
            Trade.frozen_case_id.in_(lifted_case_ids or {0}),
        )
    )
    for trade in trades.scalars():
        await unfreeze_trade(db, trade, f"账户封禁解除：{lift_reason}", admin_id)
    if case_id:
        from app.models import DisposalCase

        case = await db.get(DisposalCase, case_id)
        if case:
            await case_service.add_case_message(
                db, case, sender_id=None, role=DisposalMessageRole.SYSTEM,
                kind=DisposalMessageKind.NOTICE,
                content=f"账户封禁已解除。原因：{lift_reason}",
            )
    await notify(
        db, [user.id], "disposal", "账户封禁已解除",
        f"原因：{lift_reason}。原权限已恢复；原非在售商品不自动上架。",
        link_type="case", link_id=case_id,
    )
    await db.flush()
    return len(restrictions)
