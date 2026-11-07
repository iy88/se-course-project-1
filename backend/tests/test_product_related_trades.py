"""Product filtering and caller-identity scope are exercised through real SQL and HTTP query intersection checks."""
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import get_audit_db, get_current_user
from app.api.v1.trades import router
from app.db.session import Base
from app.models import Product, Trade, User


@pytest.mark.asyncio
async def test_product_filter_preserves_participant_scope_and_all_states(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "requests.db"}')
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            seller, buyer, buyer2, outsider = [User(email=f'{name}@example.com', display_name=name, password_hash='x') for name in ['seller', 'buyer', 'buyer2', 'outsider']]
            db.add_all([seller, buyer, buyer2, outsider])
            await db.commit()
            target, other, third = [Product(seller_id=owner.id, title=title, description='说明', price_cents=100, status='listed') for owner, title in [(seller, '目标'), (seller, '其他'), (outsider, '他人')]]
            db.add_all([target, other, third])
            await db.commit()
            states = ['rejected', 'withdrawn', 'closed', 'in_progress', 'terminated', 'completed']
            records = [Trade(product_id=target.id, seller_id=seller.id, buyer_id=buyer.id, status=state) for state in states]
            pending = Trade(product_id=target.id, seller_id=seller.id, buyer_id=buyer2.id, status='pending_acceptance', request_note='想看实物')
            unrelated = Trade(product_id=other.id, seller_id=seller.id, buyer_id=buyer.id)
            buy_side = Trade(product_id=third.id, seller_id=outsider.id, buyer_id=seller.id)
            db.add_all([*records, pending, unrelated, buy_side])
            await db.commit()
            app = FastAPI()
            app.include_router(router, prefix='/api/v1')
            current = seller
            app.dependency_overrides[get_current_user] = lambda: current
            async def session():
                yield db
            app.dependency_overrides[get_audit_db] = session
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                async def get(**params):
                    response = await client.get('/api/v1/trades/mine', params=params)
                    assert response.status_code == 200, response.text
                    return response.json()
                result = await get(role='seller', product_id=target.id)
                assert {r['id'] for r in result} == {r.id for r in [*records, pending]}
                assert {r['status'] for r in result} == {*states, 'pending_acceptance'}
                assert next(r for r in result if r['id'] == pending.id)['buyer']['display_name'] == 'buyer2'
                assert all(r['product_id'] == target.id for r in result)
                assert [r['id'] for r in result] == sorted([r['id'] for r in result], reverse=True)
                assert await get(role='seller', product_id=third.id) == []
                assert await get(role='all', product_id=9999) == []
                assert {r['id'] for r in await get(role='all')} == {r.id for r in [*records, pending, unrelated, buy_side]}
                assert [r['id'] for r in await get(role='buyer')] == [buy_side.id]
                for bad_id in ['0', '-1', 'abc']:
                    assert (await client.get('/api/v1/trades/mine', params={'product_id': bad_id})).status_code == 422
                current = outsider
                assert await get(role='all', product_id=target.id) == []
                current = buyer2
                assert [r['id'] for r in await get(role='buyer', product_id=target.id)] == [pending.id]
    finally:
        await engine.dispose()
