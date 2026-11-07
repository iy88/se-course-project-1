"""Trade helpers (request closing, lock validation, etc.); the full state machine lives in api/v1/trades.py."""
from typing import NoReturn

from fastapi import HTTPException, status
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlmodel import col, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Product, Trade
from app.models.enums import TradeStatus
from app.services.notifications import notify

LOCKING_STATUSES = [TradeStatus.IN_PROGRESS.value, TradeStatus.DISPUTED.value, TradeStatus.ABNORMAL.value]
BANNED_PENDING_REASON = "相关账户被封禁"
CLOSED_BY_LOCK = "商品已被其他用户锁单"
DISPLAY_REVOKED_REASON = "商品公开访问已撤销"
LOCK_CONFLICT_DETAIL = "商品已存在另一笔锁单交易，请先按该笔交易的适用规则处理后再恢复"
# Explicitly retryable transaction-level SQLSTATEs: deadlock and serialization failure. Business/integrity errors are not included.
RETRYABLE_TRANSACTION_SQLSTATES = frozenset({"40P01", "40001"})
PENDING_REQUEST_CONSTRAINT = "uq_buyer_pending_request"


def _sqlstate(exc: BaseException) -> str | None:
    """Extract the database SQLSTATE from a wrapped SQLAlchemy exception (does not concatenate/print SQL parameters)."""
    orig = exc.orig if isinstance(exc, DBAPIError) else exc
    value = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return str(value) if value else None


def is_retryable_transaction_error(exc: DBAPIError) -> bool:
    """Treat only explicit deadlock/serialization failures as retryable; other database errors propagate unchanged."""
    return _sqlstate(exc) in RETRYABLE_TRANSACTION_SQLSTATES


def _is_pending_request_unique_conflict(exc: IntegrityError) -> bool:
    """Identify exactly the conditional unique-index conflict for a pending-acceptance request from the same buyer for the same product."""
    orig = exc.orig
    sqlstate = _sqlstate(exc)
    message = str(orig)
    if sqlstate == "23505":
        constraint = getattr(orig, "constraint_name", None)
        if constraint:
            return str(constraint) == PENDING_REQUEST_CONSTRAINT
        return PENDING_REQUEST_CONSTRAINT in message
    # SQLite integrity-error text lacks the conditional index name and only lists columns; match only the column combination unique to this index.
    lowered = message.lower()
    if PENDING_REQUEST_CONSTRAINT in lowered:
        return True
    return (
        "unique constraint failed" in lowered
        and "trades.product_id" in lowered
        and "trades.buyer_id" in lowered
    )


async def find_pending_request(
    db: AsyncSession, product_id: int, buyer_id: int
) -> Trade | None:
    """Read the current pending-acceptance request from the same buyer for the same product (shared by retry consistency and concurrency fallback)."""
    return (await db.exec(
        select(Trade).where(
            col(Trade.product_id) == product_id,
            col(Trade.buyer_id) == buyer_id,
            col(Trade.status) == TradeStatus.PENDING_ACCEPTANCE.value,
        )
    )).first()


async def lock_product_for_update(db: AsyncSession, product_id: int) -> Product | None:
    """Lock the product row in the unified order before a trade write.

    PostgreSQL uses ``FOR UPDATE`` to serialize trades on the same product; the SQLite
    dialect ignores that clause, so the compatibility path first runs a no-op UPDATE to
    acquire the write lock, then re-reads state; the unique index remains the backstop.
    """
    if db.get_bind().dialect.name == 'sqlite':
        await db.exec(update(Product).where(col(Product.id) == product_id).values(id=product_id))
    result = await db.exec(
        select(Product)
        .where(col(Product.id) == product_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.one_or_none()


async def lock_trade_for_update(db: AsyncSession, trade_id: int) -> Trade | None:
    """Lock the target trade after the product row lock and refresh potentially stale in-session state.

    The unified lock order is "product → trade". ``populate_existing`` ensures a
    trade.status/product ownership committed by another transaction while waiting for
    the product lock is not overwritten by a stale identity-map object.
    """
    result = await db.exec(
        select(Trade)
        .where(col(Trade.id) == trade_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.one_or_none()


async def lock_product_then_trade(
    db: AsyncSession, trade_id: int, product_id: int
) -> Trade | None:
    """User-side finish/cancel paths lock the product before writing the trade, then lock and refresh the target trade.

    ``finish_trade`` updates the trade and then delists the product; without taking the
    product lock first, the "product → trade" order used by accept/admin adjust would
    create a trade→product cross-wait. This helper keeps the same order to avoid reverse
    waiting; a missing product still allows finishing an abnormal historical trade
    without a product.
    """
    await lock_product_for_update(db, product_id)
    return await lock_trade_for_update(db, trade_id)


async def resolve_duplicate_pending_request(
    db: AsyncSession,
    exc: IntegrityError,
    *,
    product_id: int,
    buyer_id: int,
) -> Trade:
    """After a concurrent duplicate request hits the conditional unique index, roll back this write and return the existing request.

    Handles only ``uq_buyer_pending_request``; other integrity errors are rolled back
    and re-raised unchanged, never disguising a real data defect as idempotent success.
    """
    await db.rollback()
    if not _is_pending_request_unique_conflict(exc):
        raise exc
    existing = await find_pending_request(db, product_id, buyer_id)
    if existing is None:
        # The conflict was identified but no existing request can be returned: preserve the original error instead of fabricating a result.
        raise exc
    return existing


async def close_pending_requests_for_product(
    db: AsyncSession,
    product_id: int,
    reason: str,
    exclude_trade_ids: set[int] | None = None,
) -> list[Trade]:
    """Close pending-acceptance requests when a product is delisted/removed by disposal (BR-02, TR-09), and archive the corresponding branches."""
    exclude = exclude_trade_ids or set()
    from app.services import conversations as conversation_service

    result = await db.exec(
        select(Trade).where(col(Trade.product_id) == product_id, col(Trade.status) == TradeStatus.PENDING_ACCEPTANCE.value)
    )
    closed: list[Trade] = []
    for trade in result:
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
    """D-52: when a ban takes effect, close all pending-acceptance requests where the user is buyer or seller.

    Retain history and archive branches; notify both parties; accepted trades are not
    closed here and follow the freeze rules.
    """
    from app.services import conversations as conversation_service

    result = await db.exec(
        select(Trade).where(
            col(Trade.status) == TradeStatus.PENDING_ACCEPTANCE.value,
            (col(Trade.buyer_id) == user_id) | (col(Trade.seller_id) == user_id),
        )
    )
    closed = list(result)
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
    result = await db.exec(
        select(Trade).where(col(Trade.product_id) == product_id, col(Trade.status).in_(LOCKING_STATUSES))
    )
    return result.one_or_none()


async def ensure_no_locking_conflict(db: AsyncSession, trade: Trade, target_status: str) -> None:
    """D-48: explicitly check for another locking trade on the same product before entering any locking status.

    Read-only query; on conflict it raises 409 before the caller modifies the trade,
    confirmations, product, branch, or restrictions.
    """
    if target_status not in LOCKING_STATUSES:
        return
    other_id = (await db.exec(
        select(col(Trade.id))
        .where(
            col(Trade.product_id) == trade.product_id,
            col(Trade.status).in_(LOCKING_STATUSES),
            col(Trade.id) != trade.id,
        )
        .limit(1)
    )).first()
    if other_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, LOCK_CONFLICT_DETAIL)


async def resolve_lock_integrity_error(
    db: AsyncSession,
    exc: IntegrityError,
    *,
    product_id: int,
) -> NoReturn:
    """D-48: when another transaction commits a lock first after the precheck, the database unique constraint is the final arbiter.

    All writes from this attempt (state, confirmations, product, branch, notifications,
    transitions) must be rolled back; after confirming another lock exists on the same
    product, map to 409. Other integrity errors propagate unchanged so real defects are not swallowed.
    """
    await db.rollback()
    other_id = (await db.exec(
        select(col(Trade.id))
        .where(col(Trade.product_id) == product_id, col(Trade.status).in_(LOCKING_STATUSES))
        .limit(1)
    )).first()
    if other_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, LOCK_CONFLICT_DETAIL) from exc
    raise exc
