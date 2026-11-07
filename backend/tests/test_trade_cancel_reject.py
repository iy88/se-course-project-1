"""Trade cancellation requests: the counterparty may reject, which only ends the request without changing trade state (#17 optional hardening)."""

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.trades import reject_cancel
from app.db.session import Base
from app.models import Notification, Product, Trade, User
from app.models.enums import ProductStatus, TradeStatus


async def _engine(tmp_path, name):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / name}')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def _seed(db):
    applicant = User(email='applicant@example.com', display_name='申请人', password_hash='x')
    counterparty = User(email='counterparty@example.com', display_name='被申请方', password_hash='x')
    db.add_all([applicant, counterparty])
    await db.commit()
    product = Product(
        seller_id=counterparty.id,
        title='测试商品',
        description='用于取消申请拒绝测试',
        price_cents=100,
        status=ProductStatus.IN_TRANSACTION.value,
    )
    db.add(product)
    await db.commit()
    trade = Trade(
        product_id=product.id,
        buyer_id=applicant.id,
        seller_id=counterparty.id,
        status=TradeStatus.IN_PROGRESS.value,
        cancel_requested_by_id=applicant.id,
    )
    db.add(trade)
    await db.commit()
    return applicant, counterparty, trade


@pytest.mark.asyncio
async def test_counterparty_rejects_and_trade_stays_in_progress(tmp_path):
    engine = await _engine(tmp_path, 'reject.db')
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            applicant, counterparty, trade = await _seed(db)
            result = await reject_cancel(trade.id, counterparty, db)
            assert result['detail'] == '已拒绝取消申请，交易继续'

            trade = await db.get(Trade, trade.id)
            assert trade.cancel_requested_by_id is None
            assert trade.cancel_requested_at is None
            assert trade.status == TradeStatus.IN_PROGRESS.value

            notifications = (
                await db.exec(select(Notification).where(col(Notification.user_id) == applicant.id))
            ).all()
            assert len(notifications) == 1
            assert notifications[0].type == 'cancel_rejected'
            assert notifications[0].link_type == 'trade'
            assert notifications[0].link_id == trade.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_applicant_cannot_reject_own_request(tmp_path):
    engine = await _engine(tmp_path, 'applicant.db')
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            applicant, _counterparty, trade = await _seed(db)
            with pytest.raises(HTTPException) as exc:
                await reject_cancel(trade.id, applicant, db)
            assert exc.value.status_code == 400
            trade = await db.get(Trade, trade.id)
            assert trade.cancel_requested_by_id == applicant.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reject_requires_pending_request(tmp_path):
    engine = await _engine(tmp_path, 'pending.db')
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            _applicant, counterparty, trade = await _seed(db)
            trade.cancel_requested_by_id = None
            await db.commit()
            with pytest.raises(HTTPException) as exc:
                await reject_cancel(trade.id, counterparty, db)
            assert exc.value.status_code == 409
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_frozen_trade_cannot_reject_and_keeps_application(tmp_path):
    engine = await _engine(tmp_path, 'frozen.db')
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            applicant, counterparty, trade = await _seed(db)
            trade.frozen = True
            await db.commit()
            with pytest.raises(HTTPException) as exc:
                await reject_cancel(trade.id, counterparty, db)
            assert exc.value.status_code == 403
            trade = await db.get(Trade, trade.id)
            assert trade.cancel_requested_by_id == applicant.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_terminal_trade_cannot_reject(tmp_path):
    engine = await _engine(tmp_path, 'terminal.db')
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            _applicant, counterparty, trade = await _seed(db)
            trade.status = TradeStatus.TERMINATED.value
            await db.commit()
            with pytest.raises(HTTPException) as exc:
                await reject_cancel(trade.id, counterparty, db)
            assert exc.value.status_code == 409
    finally:
        await engine.dispose()
