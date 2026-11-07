"""Edit-history supplemental display fields keep the original buyer/seller eligibility, and signing does not bypass the time filter."""
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1 import products
from app.db.session import Base
from app.models import Product, ProductEditHistory, Trade, User


@pytest.mark.asyncio
async def test_history_fields_and_buyer_scope(tmp_path, monkeypatch):
    storage = Mock()
    storage.public_url.side_effect = lambda key: f'/signed/{key}'
    monkeypatch.setattr(products, 'get_storage', lambda: storage)
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "history.db"}')
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            seller, buyer, outsider = [User(email=f'{role}@example.com', display_name=role, password_hash='x') for role in ['seller', 'buyer', 'outsider']]
            db.add_all([seller, buyer, outsider])
            await db.commit()
            product = Product(seller_id=seller.id, title='商品', description='说明', price_cents=3000, status='delisted')
            db.add(product)
            await db.commit()
            start = datetime(2026, 1, 1)
            trade = Trade(product_id=product.id, buyer_id=buyer.id, seller_id=seller.id, status='completed', created_at=start)
            old = ProductEditHistory(product_id=product.id, editor_id=seller.id, before_json={'images': ['old-before.jpg']}, after_json={'images': ['old-after.jpg']}, created_at=start-timedelta(days=1))
            new = ProductEditHistory(product_id=product.id, editor_id=seller.id, before_json={'title': '旧标题', 'images': ['before.jpg'], 'price_cents': 3000}, after_json={'title': '新标题', 'images': ['after.jpg'], 'price_cents': 2500}, created_at=start+timedelta(days=1))
            db.add_all([trade, old, new])
            await db.commit()
            result = await products.edit_history(product.id, buyer, db)
            assert [r.id for r in result] == [new.id]
            assert result[0].editor_name == 'seller'
            assert result[0].before_image_urls == ['/signed/before.jpg']
            assert result[0].after_image_urls == ['/signed/after.jpg']
            assert result[0].before_json['price_cents'] == 3000
            assert result[0].after_json['price_cents'] == 2500
            assert [c.args[0] for c in storage.public_url.call_args_list] == ['before.jpg', 'after.jpg']
            storage.reset_mock()
            with pytest.raises(HTTPException) as exc:
                await products.edit_history(product.id, outsider, db)
            assert exc.value.status_code == 403
            storage.public_url.assert_not_called()
            full = await products.edit_history(product.id, seller, db)
            assert [r.id for r in full] == [old.id, new.id]
            with pytest.raises(HTTPException) as exc:
                await products.edit_history(9999, buyer, db)
            assert exc.value.status_code == 404
    finally:
        await engine.dispose()
