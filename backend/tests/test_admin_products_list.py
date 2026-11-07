"""Regression coverage for the admin product list.

Covers: /admin/products server-side pagination and total count; status, display-restriction,
and category (tag) filters; keyword matching against title, description, category primary
name/alias, and exact numeric IDs.
"""

import pytest
from app.api.v1.admin.products import list_products
from app.db.session import Base
from app.models import Category, Product, ProductTag, User
from app.models.enums import ProductStatus
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession


async def _seed(db):
    admin = User(email='admin@example.com', display_name='管理员', password_hash='x', role='admin')
    seller = User(email='s@example.com', display_name='张同学', password_hash='x')
    db.add_all([admin, seller])
    await db.commit()
    book = Category(name='书籍教材', created_by_id=admin.id)
    digital = Category(name='数码产品', created_by_id=admin.id)
    db.add_all([book, digital])
    await db.commit()
    products = [
        Product(seller_id=seller.id, title='高等数学教材', description='线性代数辅导书', price_cents=1500, status=ProductStatus.LISTED.value),
        Product(seller_id=seller.id, title='无线蓝牙耳机', description='二手数码配件', price_cents=9900, status=ProductStatus.IN_TRANSACTION.value),
        Product(seller_id=seller.id, title='台灯', description='宿舍学习用台灯', price_cents=2000, status=ProductStatus.DELISTED.value, display_restricted=True),
        Product(seller_id=seller.id, title='英语真题集', description='考研英语历年真题', price_cents=800, status=ProductStatus.PENDING_REVIEW.value),
    ]
    db.add_all(products)
    await db.commit()
    db.add_all([
        ProductTag(product_id=products[0].id, category_id=book.id),
        ProductTag(product_id=products[1].id, category_id=digital.id),
        ProductTag(product_id=products[3].id, category_id=book.id),
    ])
    await db.commit()
    return admin, products, book


@pytest.mark.asyncio
async def test_admin_product_list_filters_search_pagination(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "products.db"}')
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as db:
            admin, products, book = await _seed(db)

            # Pagination and total: page_size=2, second page
            data = await list_products(admin, db, page=2, page_size=2, product_status='all', category_id=None, display_restricted='all', keyword=None)
            assert data['total'] == 4 and data['page'] == 2
            assert [i['id'] for i in data['items']] == sorted((p.id for p in products), reverse=True)[2:4]

            # Status filter
            data = await list_products(admin, db, page=1, page_size=20, product_status='listed', category_id=None, display_restricted='all', keyword=None)
            assert data['total'] == 1 and data['items'][0]['title'] == '高等数学教材'

            # Display-restriction filter
            data = await list_products(admin, db, page=1, page_size=20, product_status='all', category_id=None, display_restricted='yes', keyword=None)
            assert data['total'] == 1 and data['items'][0]['display_restricted'] is True

            # Category (tag) filter
            data = await list_products(admin, db, page=1, page_size=20, product_status='all', category_id=book.id, display_restricted='all', keyword=None)
            assert data['total'] == 2

            # Keyword: title substring / description substring / category primary name / exact numeric ID
            data = await list_products(admin, db, page=1, page_size=20, product_status='all', category_id=None, display_restricted='all', keyword='教材')
            assert data['total'] == 2
            data = await list_products(admin, db, page=1, page_size=20, product_status='all', category_id=None, display_restricted='all', keyword='考研英语')
            assert data['total'] == 1 and data['items'][0]['title'] == '英语真题集'
            data = await list_products(admin, db, page=1, page_size=20, product_status='all', category_id=None, display_restricted='all', keyword='数码产品')
            assert data['total'] == 1 and data['items'][0]['title'] == '无线蓝牙耳机'
            data = await list_products(admin, db, page=1, page_size=20, product_status='all', category_id=None, display_restricted='all', keyword=str(products[2].id))
            assert data['total'] == 1 and data['items'][0]['id'] == products[2].id
            data = await list_products(admin, db, page=1, page_size=20, product_status='all', category_id=None, display_restricted='all', keyword='999999')
            assert data['total'] == 0

            # Seller name is returned with each item
            data = await list_products(admin, db, page=1, page_size=20, product_status='all', category_id=None, display_restricted='all', keyword=None)
            assert all(i['seller_name'] == '张同学' for i in data['items'])
    finally:
        await engine.dispose()
