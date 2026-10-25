"""单方确认 7 天未回应超时识别（BR-05、TR-14）：系统转异常并冻结，进入共享池。"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Trade, TradeTransition
from app.models.enums import CaseType, TradeStatus
from app.services.cases import create_case
from app.services.notifications import notify

SYSTEM = "system"


async def scan_once(db: AsyncSession | None = None) -> int:
    """扫描全部超时交易并转异常；返回处理笔数。供后台循环与测试使用。"""
    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        days = get_settings().trade_confirm_timeout_days
        deadline = datetime.now(UTC) - timedelta(days=days)
        result = await db.execute(
            select(Trade).where(
                Trade.status == TradeStatus.IN_PROGRESS.value,
                Trade.confirm_wait_started_at.is_not(None),
                Trade.confirm_wait_started_at < deadline,
            )
        )
        trades = list(result.scalars())
        for trade in trades:
            await _to_abnormal(db, trade)
        await db.commit()
        return len(trades)
    finally:
        if own_db:
            await db.close()


async def _to_abnormal(db: AsyncSession, trade: Trade) -> None:
    now = datetime.now(UTC)
    trade.status = TradeStatus.ABNORMAL.value
    trade.frozen = True
    trade.frozen_reason = "单方完成确认后超过7天未回应，转异常交易处理"
    trade.frozen_at = now
    trade.confirm_wait_started_at = None
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
