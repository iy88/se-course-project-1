"""D-51 SQLite 增量升级测试：旧库只追加列且保留数据，新库正常建表。"""

from datetime import UTC, datetime, timedelta

import pytest
from app.db.migrations import upgrade_additive_schema
from app.db.session import Base
from app.models import CompletionConfirmation, Trade
from app.services import moderation
from app.services.trade_timeout import scan_once
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.asyncio


async def test_old_sqlite_schema_adds_wait_columns_without_data_loss(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/old.db")
    try:
        async with engine.begin() as conn:
            # 旧版结构：没有 D-51 两列；已有数据必须保留。
            await conn.execute(
                text(
                    "CREATE TABLE trades ("
                    "id INTEGER PRIMARY KEY, product_id INTEGER, buyer_id INTEGER, seller_id INTEGER, "
                    "status VARCHAR(24), confirm_wait_started_at DATETIME, finished_at DATETIME)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO trades (id, product_id, buyer_id, seller_id, status, "
                    "confirm_wait_started_at, finished_at) VALUES "
                    "(7, 3, 5, 9, 'in_progress', '2026-10-20 08:00:00', NULL)"
                )
            )
            applied = await conn.run_sync(upgrade_additive_schema)
            assert "trades.confirm_wait_paused_at" in applied
            assert "trades.confirm_wait_remaining_seconds" in applied

            columns = await conn.run_sync(
                lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("trades")}
            )
            assert {"confirm_wait_paused_at", "confirm_wait_remaining_seconds"} <= columns
            row = (
                await conn.execute(
                    text(
                        "SELECT id, status, confirm_wait_started_at, finished_at, "
                        "confirm_wait_paused_at, confirm_wait_remaining_seconds FROM trades"
                    )
                )
            ).mappings().one()
            assert row["id"] == 7
            assert row["status"] == "in_progress"
            assert row["confirm_wait_started_at"] == "2026-10-20 08:00:00"
            assert row["finished_at"] is None
            assert row["confirm_wait_paused_at"] is None
            assert row["confirm_wait_remaining_seconds"] is None

            # 可重复执行，不重复加列、不重建表。
            assert await conn.run_sync(upgrade_additive_schema) == []
    finally:
        await engine.dispose()


async def test_legacy_frozen_trade_upgrade_unfreeze_and_scan_preserves_five_days(tmp_path):
    """R1：旧结构库增量升级后，经实际解冻服务续算剩余 5 天，不立即超时。

    旧库场景：单方确认后有效等待 2 天，随后冻结 10 天；升级只补列，
    解冻须以 frozen_at 为暂停点回填，保留当前确认与历史，不得按自然墙钟立即转异常。
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/legacy-frozen.db")
    now = datetime.now(UTC)
    started = (now - timedelta(days=12)).replace(tzinfo=None).isoformat(sep=" ")
    frozen_at = (now - timedelta(days=10)).replace(tzinfo=None).isoformat(sep=" ")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # 模拟 D-51 之前的旧结构：移除两列，保留原有行与确认历史。
            await conn.execute(text('ALTER TABLE trades DROP COLUMN confirm_wait_paused_at'))
            await conn.execute(text('ALTER TABLE trades DROP COLUMN confirm_wait_remaining_seconds'))
            await conn.execute(
                text(
                    "INSERT INTO trades (id, product_id, buyer_id, seller_id, status, "
                    "confirm_wait_started_at, frozen, frozen_at) VALUES "
                    "(7, 3, 5, 9, 'in_progress', :started, 1, :frozen_at)"
                ),
                {"started": started, "frozen_at": frozen_at},
            )
            await conn.execute(
                text(
                    "INSERT INTO completion_confirmations "
                    "(trade_id, confirmer_id, is_current, confirmed_at) VALUES "
                    "(7, 5, 1, :current_at), (7, 5, 0, :history_at)"
                ),
                {
                    "current_at": (now - timedelta(days=12)).isoformat(sep=" "),
                    "history_at": (now - timedelta(days=20)).isoformat(sep=" "),
                },
            )
            applied = await conn.run_sync(upgrade_additive_schema)
            assert {"trades.confirm_wait_paused_at", "trades.confirm_wait_remaining_seconds"} <= set(applied)
            # 可重复升级，不清空旧行或确认历史。
            assert await conn.run_sync(upgrade_additive_schema) == []

        SessionMaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with SessionMaker() as db:
            trade = await db.get(Trade, 7)
            assert trade is not None and trade.frozen is True
            assert trade.confirm_wait_paused_at is None and trade.confirm_wait_remaining_seconds is None
            confirmations_before = list(
                (
                    await db.execute(
                        select(CompletionConfirmation)
                        .where(CompletionConfirmation.trade_id == 7)
                        .order_by(CompletionConfirmation.id)
                    )
                ).scalars()
            )
            assert [c.is_current for c in confirmations_before] == [True, False]

            await moderation.unfreeze_trade(db, trade, "升级后经认领事项解除", admin_id=1)
            await db.commit()

            trade = await db.get(Trade, 7)
            assert trade.frozen is False
            assert trade.confirm_wait_paused_at is None and trade.confirm_wait_remaining_seconds is None
            assert trade.confirm_wait_started_at is not None
            remaining = 7 * 86400 - (
                datetime.now(UTC) - trade.confirm_wait_started_at.replace(tzinfo=UTC)
            ).total_seconds()
            assert 4.9 * 86400 <= remaining <= 5.0 * 86400  # 2 天已有效等待，冻结 10 天不累计
            confirmations_after = list(
                (
                    await db.execute(
                        select(CompletionConfirmation)
                        .where(CompletionConfirmation.trade_id == 7)
                        .order_by(CompletionConfirmation.id)
                    )
                ).scalars()
            )
            assert [c.is_current for c in confirmations_after] == [True, False]

            assert await scan_once(db) == 0
            trade = await db.get(Trade, 7)
            assert trade.status == "in_progress"
    finally:
        await engine.dispose()


async def test_new_database_creates_wait_columns_normally(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/new.db")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            assert await conn.run_sync(upgrade_additive_schema) == []
            columns = await conn.run_sync(
                lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("trades")}
            )
            assert {"confirm_wait_paused_at", "confirm_wait_remaining_seconds"} <= columns
    finally:
        await engine.dispose()
