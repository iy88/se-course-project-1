"""Admin category correction: disabled categories must not be added as new associations (#12 reopened, US-13-AC-04).

Covers:
- adding an unassociated disabled category -> 400 with tags unchanged;
- keeping a product's existing disabled association -> allowed, and active categories may be adjusted at the same time;
- a normal correction using only active categories -> success.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.admin.products import CategoryCorrectionIn, correct_category
from app.db.session import Base
from app.models import Category, Product, ProductTag, User
from app.models.enums import ProductStatus
from app.services.products import load_product_tags


async def _seed(db):
    admin = User(email='admin@example.com', display_name='管理员', password_hash='x', role='admin')
    seller = User(email='seller@example.com', display_name='卖家', password_hash='x')
    db.add_all([admin, seller])
    await db.commit()

    active = Category(name='数码产品', created_by_id=admin.id)
    disabled = Category(name='骑行装备', status='disabled', created_by_id=admin.id)
    other_disabled = Category(name='旧书交流', status='disabled', created_by_id=admin.id)
    db.add_all([active, disabled, other_disabled])
    await db.commit()

    kept = Product(
        seller_id=seller.id,
        title='保留停用关联的商品',
        description='历史遗留停用分类',
        price_cents=100,
        status=ProductStatus.LISTED.value,
    )
    clean = Product(
        seller_id=seller.id,
        title='仅启用分类的商品',
        description='无停用关联',
        price_cents=200,
        status=ProductStatus.LISTED.value,
    )
    db.add_all([kept, clean])
    await db.commit()
    db.add(ProductTag(product_id=kept.id, category_id=disabled.id))
    db.add(ProductTag(product_id=clean.id, category_id=active.id))
    await db.commit()
    return admin, active, disabled, other_disabled, kept, clean


async def _engine(tmp_path, name):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / name}')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest.mark.asyncio
async def test_correct_category_rejects_new_disabled_association(tmp_path):
    engine = await _engine(tmp_path, 'reject.db')
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            admin, active, _disabled, other_disabled, _kept, clean = await _seed(db)
            body = CategoryCorrectionIn(
                category_ids=[active.id, other_disabled.id],
                reason='尝试新增未关联的停用分类',
            )
            with pytest.raises(HTTPException) as exc:
                await correct_category(clean.id, body, admin, db)
            assert exc.value.status_code == 400
            assert other_disabled.name in str(exc.value.detail)
            # Validation fails before tags are replaced, so the original associations stay unchanged.
            tags = await load_product_tags(db, clean.id)
            assert [t.id for t in tags] == [active.id]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_correct_category_keeps_existing_disabled_association(tmp_path):
    engine = await _engine(tmp_path, 'keep.db')
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            admin, active, disabled, _other_disabled, kept, _clean = await _seed(db)
            body = CategoryCorrectionIn(
                category_ids=[disabled.id, active.id],
                reason='保留历史停用分类并补充启用分类',
            )
            result = await correct_category(kept.id, body, admin, db)
            assert result['detail'] == '分类纠正完成并通知卖方'
            tags = await load_product_tags(db, kept.id)
            assert [t.id for t in tags] == [active.id, disabled.id]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_correct_category_allows_active_categories(tmp_path):
    engine = await _engine(tmp_path, 'active.db')
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            admin, active, _disabled, _other_disabled, _kept, clean = await _seed(db)
            body = CategoryCorrectionIn(category_ids=[active.id], reason='仅调整启用分类')
            result = await correct_category(clean.id, body, admin, db)
            assert result['detail'] == '分类纠正完成并通知卖方'
            tags = await load_product_tags(db, clean.id)
            assert [t.id for t in tags] == [active.id]
    finally:
        await engine.dispose()
