"""交易辅助（请求关闭、锁单校验等）；完整状态机见 api/v1/trades.py。"""
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
# 明确可重试的事务级 SQLSTATE：死锁与序列化失败。业务/完整性错误不在此列。
RETRYABLE_TRANSACTION_SQLSTATES = frozenset({"40P01", "40001"})
PENDING_REQUEST_CONSTRAINT = "uq_buyer_pending_request"


def _sqlstate(exc: BaseException) -> str | None:
    """从 SQLAlchemy 包装异常中取出数据库 SQLSTATE（不拼接/输出 SQL 参数）。"""
    orig = exc.orig if isinstance(exc, DBAPIError) else exc
    value = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    return str(value) if value else None


def is_retryable_transaction_error(exc: DBAPIError) -> bool:
    """只把明确的死锁/序列化失败视为可重试；其他数据库错误原样抛出。"""
    return _sqlstate(exc) in RETRYABLE_TRANSACTION_SQLSTATES


def _is_pending_request_unique_conflict(exc: IntegrityError) -> bool:
    """精确识别同买方同商品待接受请求的条件唯一索引冲突。"""
    orig = exc.orig
    sqlstate = _sqlstate(exc)
    message = str(orig)
    if sqlstate == "23505":
        constraint = getattr(orig, "constraint_name", None)
        if constraint:
            return str(constraint) == PENDING_REQUEST_CONSTRAINT
        return PENDING_REQUEST_CONSTRAINT in message
    # SQLite 的完整性错误文本不含条件索引名，只含列；仅匹配本索引唯一的列组合。
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
    """读取同买方对同商品的当前待接受请求（重试一致与并发兜底共用）。"""
    return (await db.exec(
        select(Trade).where(
            col(Trade.product_id) == product_id,
            col(Trade.buyer_id) == buyer_id,
            col(Trade.status) == TradeStatus.PENDING_ACCEPTANCE.value,
        )
    )).first()


async def lock_product_for_update(db: AsyncSession, product_id: int) -> Product | None:
    """在交易写入前按统一顺序锁定商品行。

    PostgreSQL 使用 ``FOR UPDATE`` 串行化同商品交易；SQLite 方言忽略该子句，
    兼容路径先执行无值变化的 UPDATE 获取写锁，再重读状态；唯一索引继续兜底。
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
    """在商品行锁之后锁定目标交易，并刷新可能已过期的会话内状态。

    统一锁序为“商品 → 交易”。``populate_existing`` 保证等待商品锁期间另一事务
    已提交的 trade.status/商品归属不会被 identity map 中的旧对象覆盖。
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
    """用户侧结束/取消路径在写 trade 前先锁商品，再锁并刷新目标交易。

    ``finish_trade`` 会先更新 trade、随后下架商品；若不先取商品锁，会与 accept/
    admin adjust 的“商品 → 交易”顺序形成 trade→product 交叉等待。这里统一为
    同一顺序，避免反向等待；商品不存在时仍允许完成无商品的异常历史交易。
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
    """并发重复请求落在条件唯一索引后，回滚本次写入并返回已存在的请求。

    只处理 ``uq_buyer_pending_request``；其他完整性错误先回滚再原样抛出，
    不把真实的数据缺陷伪装成幂等成功。
    """
    await db.rollback()
    if not _is_pending_request_unique_conflict(exc):
        raise exc
    existing = await find_pending_request(db, product_id, buyer_id)
    if existing is None:
        # 冲突已被识别但找不到可返回的既有请求：保留原始错误，避免伪造结果。
        raise exc
    return existing


async def close_pending_requests_for_product(
    db: AsyncSession,
    product_id: int,
    reason: str,
    exclude_trade_ids: set[int] | None = None,
) -> list[Trade]:
    """商品下架/违规处置下架时关闭待接受请求（BR-02、TR-09），并归档对应分支。"""
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
    """D-52：封禁生效时关闭其作为买方或卖方参与的全部待接受请求。

    保留历史并归档分支；通知双方；已接受交易不在此关闭，按冻结规则处理。
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
    """D-48：进入任何需锁单状态前显式检查同商品另一笔锁单。

    只读查询；冲突时抛 409，调用方尚未修改交易、确认、商品、分支或限制。
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
    """D-48：预检后另一事务抢先提交锁单时，数据库唯一约束是最终裁决。

    必须回滚本次全部写入（状态、确认、商品、分支、通知、转移），再确认同商品
    确有另一笔锁单后映射 409；其他完整性错误原样抛出，避免吞掉真实缺陷。
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
