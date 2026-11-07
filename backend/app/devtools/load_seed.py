"""Bulk persistent load fixtures; real DB/storage, no HTTP or test mocks.

Run reset separately (preview + explicit confirmation) before replacing a dataset.
The private manifest journals object keys before upload and DB IDs before commit.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import secrets
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import event, insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings, load_settings, resolve_env_file
from app.core.private_files import require_private
from app.core.security import hash_password, verify_password
from app.devtools._support import credentials_lock, write_private_json
from app.devtools.demo_seed import _target
from app.devtools.demo_scenarios.catalog import PRODUCTS
from app.models import User, Category, Product, ProductImage, ProductTag, ReviewRecord, Conversation, Message
from app.models.stored_object import StoredObject
from app.storage.base import StorageAlreadyExists, build_storage

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = ROOT / 'var/load/manifest.json'
ASSETS = Path(__file__).parent / 'demo_scenarios/assets'
VERSION = 2
LOAD_IMAGES = (
    ('keyboard', '键盘', 'product_keyboard_pending'),
    ('textbook', '教材', 'product_textbook'),
    ('lamp', '台灯', 'product_lamp_pending'),
    ('bike', '自行车', 'product_folding_bike'),
    ('camera', '相机', 'product_camera_rejected'),
    ('mug', '水杯', 'product_mug'),
    ('monitor', '显示器', 'product_monitor_resubmitted'),
    ('racket', '球拍', 'product_racket'),
)


def asset_for(data: dict, index: int) -> dict:
    return data['image_assets'][index % len(data['image_assets'])]


def category_index(index: int, users: int) -> int:
    return (index // users + index % users) % 5


def new_manifest(settings, users: int, products: int) -> dict:
    tag = secrets.token_hex(8)
    assets = []
    product_assets = {product.key: product.asset for product in PRODUCTS}
    for name, keyword, product_key in LOAD_IMAGES:
        image = (ASSETS / product_assets[product_key]).read_bytes()
        assets.append(dict(name=name, keyword=keyword, base64=base64.b64encode(image).decode(),
                           sha256=hashlib.sha256(image).hexdigest(), size_bytes=len(image)))
    return dict(version=VERSION, target=_target(settings), tag=tag, complete=False,
                users=users, products=products, password=secrets.token_urlsafe(24),
                image_base64=assets[0]['base64'], image_sha256=assets[0]['sha256'],
                image_assets=assets, search_terms=[asset['keyword'] for asset in assets],
                accounts=[], product_ids=[], category_ids=[], conversation_ids=[])


def image_key(data: dict, index: int) -> str:
    return f'product/load_{data["tag"]}/{index:08d}.jpg'


async def verify(session, storage, data: dict, *, all_files: bool) -> None:
    if len(data['accounts']) != data['users'] or len(data['product_ids']) != data['products']:
        raise ValueError('manifest IDs incomplete; reset and use a new manifest')
    for account in data['accounts']:
        user = await session.get(User, account['id'])
        if not user or user.email != account['email'] or not verify_password(data['password'], user.password_hash):
            raise ValueError('seed account missing or modified; refusing to adopt')
    # Chunked selects avoid SQLite variable limits and keep validation linear.
    for offset in range(0, data['products'], 500):
        ids = data['product_ids'][offset:offset + 500]
        rows = (await session.exec(select(Product.id).where(col(Product.id).in_(ids)))).all()
        images = (await session.exec(select(ProductImage).where(col(ProductImage.product_id).in_(ids)))).all()
        if len(rows) != len(ids) or len(images) != len(ids):
            raise ValueError('seed products/images missing; reset and use a new manifest')
        expected = {image_key(data, i): pid for i, pid in enumerate(ids, start=offset)}
        if any(expected.get(i.file_key) != i.product_id for i in images):
            raise ValueError('seed image references modified')
        objects = (await session.exec(select(StoredObject).where(col(StoredObject.key).in_(list(expected))))).all()
        if len(objects) != len(ids) or any(o.state != 'committed' or o.ref_id != expected[o.key] for o in objects):
            raise ValueError('seed object registrations incomplete')
    for cid in data['conversation_ids']:
        if await session.get(Conversation, cid) is None:
            raise ValueError('seed conversation missing')
    indices = range(data['products']) if all_files else sorted({0, data['products'] // 2, data['products'] - 1})
    def check(i):
        if hashlib.sha256(storage.open(image_key(data, i))).hexdigest() != asset_for(data, i)['sha256']:
            raise ValueError('seed image missing or corrupted')
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(check, indices))


async def seed(settings, path: Path, data: dict, workers: int, *, verify_only: bool = False) -> None:
    options = {}
    if settings.database_url.startswith('postgresql+asyncpg:'):
        options['connect_args'] = {'server_settings': {'search_path': f'"{settings.database_schema}"'}}
    engine = create_async_engine(settings.database_url, **options)
    if settings.database_url.startswith('sqlite'):
        @event.listens_for(engine.sync_engine, 'connect')
        def fk(connection, _record):
            connection.execute('PRAGMA foreign_keys=ON')
    storage = build_storage(settings)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            existing = (await session.exec(select(User).where(User.email == f'load-{data["tag"]}-0@example.com'))).first()
            if existing or data['complete'] or verify_only:
                await verify(session, storage, data, all_files=verify_only)
                if not verify_only:
                    data['complete'] = True
                    write_private_json(path, data)
                return
            images_bytes = [base64.b64decode(a['base64']) for a in data['image_assets']]
            # Keys are deterministic and journaled via tag/count before any remote write.
            def upload(i):
                key = image_key(data, i)
                image = images_bytes[i % len(images_bytes)]
                try:
                    storage.save_to_key(key, image)
                except StorageAlreadyExists:
                    if storage.open(key) != image:
                        raise ValueError('existing seed object differs; refusing to overwrite')
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for done, _ in enumerate(pool.map(upload, range(data['products'])), 1):
                    if done % 500 == 0 or done == data['products']:
                        print(f'load images: {done}/{data["products"]}', flush=True)
            # Shared fixture password/hash only accelerates setup. Rust still logs in via HTTP.
            password_hash = hash_password(data['password'])
            accounts = [User(email=f'load-{data["tag"]}-{i}@example.com', password_hash=password_hash,
                             display_name=f'压测用户{i:03d}') for i in range(data['users'])]
            session.add_all(accounts)
            await session.flush()
            data['accounts'] = [dict(id=u.id, email=u.email) for u in accounts]
            categories = [Category(name=f'压测{data["tag"]}-{name}', created_by_id=accounts[0].id)
                          for name in ('数码', '教材', '生活', '运动', '其他')]
            session.add_all(categories)
            await session.flush()
            data['category_ids'] = [c.id for c in categories]
            now = datetime.now(UTC)
            data['product_ids'] = []
            for offset in range(0, data['products'], 500):
                products = [Product(seller_id=accounts[i % data['users']].id,
                                    title=f'{asset_for(data, i)["keyword"]} {("九成新", "闲置", "毕业转让")[i % 3]} {i:06d}',
                                    description=(f'{asset_for(data, i)["keyword"]}，{("自提", "校内面交", "图书馆门口交接")[i % 3]}。' * (2 + i % 23)),
                                    price_cents=100 + (i * 137) % 100000, status='listed',
                                    created_at=now - timedelta(minutes=i), listed_at=now - timedelta(minutes=i))
                            for i in range(offset, min(offset + 500, data['products']))]
                session.add_all(products)
                await session.flush()
                data['product_ids'].extend(p.id for p in products)
                images, tags, objects, reviews = [], [], [], []
                for i, p in enumerate(products, start=offset):
                    key = image_key(data, i)
                    asset = asset_for(data, i)
                    category = categories[category_index(i, data['users'])]
                    images.append(dict(product_id=p.id, file_key=key, sort=0))
                    tags.append(dict(product_id=p.id, category_id=category.id))
                    objects.append(dict(key=key, namespace='product', bucket_role='media', owner_id=p.seller_id,
                                        content_type='image/jpeg', size_bytes=asset['size_bytes'], state='committed',
                                        ref_type='product', ref_id=p.id, committed_at=now,
                                        object_metadata={'sha256': asset['sha256']}))
                    from app.services.products import product_content_dict
                    reviews.append(dict(product_id=p.id, result='approved', reviewed_at=now,
                                        content_json=product_content_dict(p, [key], [category.name])))
                for model, rows in ((ProductImage, images), (ProductTag, tags), (StoredObject, objects), (ReviewRecord, reviews)):
                    await session.execute(insert(model), rows)
            data['conversation_ids'] = []
            # One outgoing ring conversation per user; all 100 can send and receive concurrently.
            for i, user in enumerate(accounts):
                low, high = sorted((user.id, accounts[(i + 1) % len(accounts)].id))
                c = Conversation(type='normal', user_low_id=low, user_high_id=high)
                session.add(c)
                await session.flush()
                data['conversation_ids'].append(c.id)
                await session.execute(insert(Message), [dict(conversation_id=c.id, sender_id=user.id,
                    kind='text', content=f'压测历史消息 {j:03d}') for j in range(20)])
            # Recovery from commit-response loss: IDs are persisted before the DB commit.
            write_private_json(path, data)
            await session.commit()
            data['complete'] = True
            write_private_json(path, data)
            print(f'load DB ready: {len(accounts)} users, {data["products"]} products', flush=True)
    finally:
        await engine.dispose()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', default='.env.dev')
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--users', type=int, default=100)
    parser.add_argument('--products', type=int, default=10000)
    parser.add_argument('--upload-workers', type=int, default=16)
    parser.add_argument('--verify-only', action='store_true', help='check all DB references and all stored image bytes')
    args = parser.parse_args(argv)
    try:
        if not 3 <= args.users <= 10000 or not args.users <= args.products <= 1000000 or not 1 <= args.upload_workers <= 64:
            raise ValueError('require 3 <= users <= 10000, users <= products <= 1000000, 1 <= workers <= 64')
        selected = resolve_env_file(args.env_file)
        if selected.name == '.env.prod':
            raise ValueError('load-seed only permits dev/test resources')
        settings = load_settings(selected)
        if settings.environment not in {'dev', 'test'}:
            raise ValueError('load-seed only permits dev/test resources')
        os.environ['APP_ENV_FILE'] = str(selected)
        get_settings.cache_clear()
        settings.prepare_runtime_paths()
        path = args.manifest.expanduser().absolute()
        with credentials_lock(path):
            if path.exists():
                require_private(path)
                data = json.loads(path.read_text())
                if (data.get('version'), data.get('target'), data.get('users'), data.get('products')) != (VERSION, _target(settings), args.users, args.products):
                    raise ValueError('manifest version/target/scale mismatch; use a new manifest')
            elif args.verify_only:
                raise ValueError('manifest does not exist')
            else:
                data = new_manifest(settings, args.users, args.products)
                write_private_json(path, data)
            asyncio.run(seed(settings, path, data, args.upload_workers, verify_only=args.verify_only))
        print(f'load {"verified" if args.verify_only else "seed ready"}; private manifest: {path}')
        return 0
    except ValueError as exc:
        print(f'load seed failed: {exc}', file=sys.stderr)
        return 1
    except Exception as exc:
        print(f'load seed failed: {type(exc).__name__}; check configuration/migrations/resources', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
