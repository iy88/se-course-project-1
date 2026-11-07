"""Detect timeouts when a unilateral confirmation gets no response for 7 days (BR-05, TR-14): the system turns the trade abnormal, freezes it, and moves it to the shared pool.

D-51: frozen trades never accrue by wall-clock time; after unfreezing, trade_wait
resumes the remaining time. SQLite may return naive datetimes, so interpret them
consistently as UTC before comparing.
"""
from datetime import UTC, datetime, timedelta

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import CompletionConfirmation, Trade, TradeTransition
from app.models.enums import CaseType, TradeStatus
from app.services import audit as audit_service
from app.services.cases import create_case
from app.services.notifications import notify
from app.services.trade_wait import as_utc, clear_wait_state
from app.services.trades import lock_product_then_trade

SYSTEM = "system"


async def scan_once(db: AsyncSession | None = None, *, trade_ids: tuple[int, ...] | None = None) -> int:
    """Scan all timed-out trades and turn them abnormal; return the number processed. Used by the background loop and tests."""
    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        days = get_settings().trade_confirm_timeout_days
        threshold = timedelta(days=days)
        now = datetime.now(UTC)
        # Collect candidate IDs only; re-check each trade after locking in product→trade order instead of using the scan snapshot.
        statement = select(Trade.product_id, Trade.id).where(
            col(Trade.status) == TradeStatus.IN_PROGRESS.value,
            col(Trade.confirm_wait_started_at).is_not(None),
        ).order_by(col(Trade.product_id), col(Trade.id))
        if trade_ids is not None:
            statement = statement.where(col(Trade.id).in_(trade_ids))
        result = await db.exec(statement)
        candidates = list(result)
        await db.commit()
        processed = 0
        for product_id, trade_id in candidates:
            trade = await lock_product_then_trade(db, trade_id, product_id)
            if trade is not None:
                started = as_utc(trade.confirm_wait_started_at)
                confirmed = (await db.exec(select(CompletionConfirmation.confirmer_id).where(
                    col(CompletionConfirmation.trade_id) == trade_id,
                    col(CompletionConfirmation.is_current).is_(True),
                ))).all()
                if (trade.status == TradeStatus.IN_PROGRESS.value and not trade.frozen
                        and trade.confirm_wait_paused_at is None and started is not None
                        and now - started >= threshold and len(set(confirmed)) == 1):
                    await _to_abnormal(db, trade)
                    processed += 1
            # Release locks per trade; multiple scanners and manual writes follow the same order.
            await db.commit()
        return processed
    finally:
        if own_db:
            await db.close()


async def _to_abnormal(db: AsyncSession, trade: Trade) -> None:
    from app.services.trade_wait import now_utc

    now = now_utc()
    trade.status = TradeStatus.ABNORMAL.value
    trade.frozen = True
    trade.frozen_reason = "单方完成确认后超过7天未回应，转异常交易处理"
    trade.frozen_at = now
    clear_wait_state(trade)
    db.add(
        TradeTransition(
            trade_id=trade.id,
            from_status=TradeStatus.IN_PROGRESS.value,
            to_status=TradeStatus.ABNORMAL.value,
            actor_role=SYSTEM,
            trigger="confirm_timeout",
            reason="单方完成确认后7天未回应",
        )
    )
    await create_case(
        db,
        case_type=CaseType.ABNORMAL_TRADE,
        title=f"异常交易：交易#{trade.id}单方确认超时",
        trade_id=trade.id,
    )
    await notify(
        db,
        [trade.buyer_id, trade.seller_id],
        "trade_abnormal",
        f"交易#{trade.id}已转异常交易处理",
        "单方确认后7天未回应，交易已冻结并转交管理员处理，您可从通知进入管理沟通。",
        link_type="trade",
        link_id=trade.id,
    )
    await audit_service.record_event(
        db,
        audit_service.EVENT_SYSTEM_TRADE_TIMEOUT,
        target_type="trade",
        target_id=trade.id,
        actor_id=None,
        actor_role="system",
        request_id=None,
        reason_code="confirm_timeout",
        before={"status": TradeStatus.IN_PROGRESS.value},
        after={"status": trade.status, "frozen": True},
    )
