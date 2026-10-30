"""单方确认 7 天未回应超时识别（BR-05、TR-14）：系统转异常并冻结，进入共享池。

D-51：冻结中的交易绝不按自然墙钟累计；解冻后由 trade_wait 续算剩余时间。
SQLite 可能返回 naive datetime，统一按 UTC 解释后再比较。
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

SYSTEM = "system"


async def scan_once(db: AsyncSession | None = None) -> int:
    """扫描全部超时交易并转异常；返回处理笔数。供后台循环与测试使用。"""
    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        days = get_settings().trade_confirm_timeout_days
        threshold = timedelta(days=days)
        now = datetime.now(UTC)
        result = await db.exec(
            select(Trade).where(
                col(Trade.status) == TradeStatus.IN_PROGRESS.value,
                col(Trade.confirm_wait_started_at).is_not(None),
                col(Trade.confirm_wait_paused_at).is_(None),
                col(Trade.frozen).is_(False),
                col(Trade.confirmations).any(col(CompletionConfirmation.is_current).is_(True)),
            )
        )
        trades = []
        for trade in result:
            started = as_utc(trade.confirm_wait_started_at)
            if started is None:
                continue
            if now - started >= threshold:
                trades.append(trade)
        for trade in trades:
            await _to_abnormal(db, trade)
        await db.commit()
        return len(trades)
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
