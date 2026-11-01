"""Exercise the persistent demo seed against a disposable real database and storage."""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.api.v1.admin.cases import claim_case
from app.api.v1.admin.products import ReviewDecisionIn, review_product
from app.api.v1.trades import trade_detail
from app.core.private_files import require_private
from app.core.security import verify_password
from app.db.session import Base
from app.models import User
from app.models.product import Product, ProductImage
from app.models.stored_object import StoredObject
from app.models.trade import Trade
from app.services import trade_timeout
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.mark.parametrize('response_lost', [False, True])
def test_demo_seed_sqlite_local(tmp_path, response_lost):
    db_path = tmp_path / 'demo.db'
    storage = tmp_path / 'storage'
    manifest = tmp_path / 'manifest.json'
    env_file = tmp_path / 'demo.env'
    env_file.write_text(f'''APP_NAME=DemoTest
ENVIRONMENT=test
DATABASE_URL=sqlite+aiosqlite:///{db_path}
DATABASE_SCHEMA=app
DB_AUTO_CREATE=false
AUDIT_TRUSTED_PROXIES=none
STORAGE_LOCAL_ROOT={storage}
JWT_SECRET=abcdefghijklmnopqrstuvwxyz1234567890
JWT_ALGORITHM=HS256
FILE_URL_SECRET=anotherabcdefghijklmnopqrstuvwxyz1234567890
SMTP_SECURITY=ssl
SMTP_HOST=mail.example.org
SMTP_USERNAME=testuser
SMTP_PASSWORD=testingpassword
SMTP_FROM_EMAIL=test@example.org
SMTP_FROM_NAME=Demo
''')
    url = f'sqlite+aiosqlite:///{db_path}'

    async def inspect_setup():
        engine = create_async_engine(url)
        @event.listens_for(engine.sync_engine, 'connect')
        def foreign_keys(conn, _):
            conn.execute('PRAGMA foreign_keys=ON')
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine) as session:
            session.add(User(email='existing@example.org', password_hash='original-hash', display_name='Existing'))
            await session.commit()
        await engine.dispose()
    asyncio.run(inspect_setup())

    def run():
        # Isolate the selected target from any shell configuration and never read .env.dev.
        environment = {k: v for k, v in os.environ.items() if not k.startswith(('APP_ENV_', 'DATABASE_', 'STORAGE_', 'OSS_', 'JWT_', 'FILE_URL_'))}
        return subprocess.run([sys.executable, '-X', 'utf8', '-m', 'app.manage', 'demo-seed', '--env-file', str(env_file), '--manifest', str(manifest)],
                              cwd=Path(__file__).resolve().parents[1], env=environment, capture_output=True, text=True, encoding='utf-8', check=False)

    # Fail after the first file is persisted but before the DB transaction commits.
    fault_code = """
import sys
import app.storage.base as storage_base
from app.devtools.demo_seed import main
original_build = storage_base.build_storage
class FailingStorage:
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.calls = 0
    def __getattr__(self, name):
        return getattr(self.wrapped, name)
    def save_to_key(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 2:
            if RESPONSE_LOST:
                self.wrapped.save_to_key(*args, **kwargs)
            raise RuntimeError('injected storage failure')
        return self.wrapped.save_to_key(*args, **kwargs)
storage_base.build_storage = lambda settings: FailingStorage(original_build(settings))
raise SystemExit(main(sys.argv[1:]))
"""
    fault_code = fault_code.replace('RESPONSE_LOST', str(response_lost))
    failed = subprocess.run(
        [sys.executable, '-X', 'utf8', '-c', fault_code, '--env-file', str(env_file), '--manifest', str(manifest)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, encoding='utf-8', check=False,
    )
    assert failed.returncode != 0 and 'RuntimeError' in failed.stderr
    partial = json.loads(manifest.read_text(encoding='utf-8'))
    assert not partial['complete'] and len(partial['files']) == 2
    partial_keys = {entry['key'] for entry in partial['files'].values()}
    existing_keys = {p.relative_to(storage).as_posix() for p in storage.rglob('*') if p.is_file()}
    assert len(existing_keys) == (2 if response_lost else 1)
    assert existing_keys <= partial_keys
    partial_contents = {key: (storage / key).read_bytes() for key in existing_keys}

    async def assert_rolled_back():
        engine = create_async_engine(url)
        try:
            async with AsyncSession(engine) as session:
                users = (await session.exec(select(User))).all()
                assert len(users) == 1 and users[0].email == 'existing@example.org'
                assert not (await session.exec(select(Product))).all()
                assert not (await session.exec(select(StoredObject))).all()
        finally:
            await engine.dispose()
    asyncio.run(assert_rolled_back())

    first = run()
    assert first.returncode == 0, first.stderr
    data = json.loads(manifest.read_text(encoding='utf-8'))
    assert data['complete']
    require_private(manifest)
    final_keys = {entry['key'] for entry in data['files'].values()}
    assert partial_keys <= final_keys
    assert {p.relative_to(storage).as_posix() for p in storage.rglob('*') if p.is_file()} == final_keys
    assert all((storage / key).read_bytes() == content for key, content in partial_contents.items())
    assert data['accounts'] and data['objects'] and data['files']

    async def inspect():
        engine = create_async_engine(url)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                violations = (await session.exec(text('PRAGMA foreign_key_check'))).all()
                assert not violations
                existing = (await session.exec(select(User).where(User.email == 'existing@example.org'))).one()
                assert (existing.display_name, existing.password_hash) == ('Existing', 'original-hash')
                for account in data['accounts'].values():
                    user = await session.get(User, account['id'])
                    assert user.email == account['email'] and user.role == account['role']
                    assert verify_password(account['password'], user.password_hash)
                for entry in data['files'].values():
                    key = entry['key']
                    path = (storage / key).resolve()
                    assert path.is_relative_to(storage.resolve()) and path.is_file() and path.stat().st_size > 0
                    obj = await session.get(StoredObject, key)
                    assert obj is not None and obj.state == 'committed' and obj.size_bytes == path.stat().st_size
                images = (await session.exec(select(ProductImage))).all()
                assert images
                for image in images:
                    assert await session.get(Product, image.product_id) is not None
                trades = (await session.exec(select(Trade))).all()
                assert {'pending_acceptance', 'in_progress', 'completed', 'disputed'} <= {t.status for t in trades}
                for trade in trades:
                    buyer = await session.get(User, trade.buyer_id)
                    detail = await trade_detail(trade.id, buyer, session)
                    assert detail['id'] == trade.id and detail['buyer']['id'] == buyer.id
                    assert detail['product_title'] and detail['seller']['id'] == trade.seller_id
                counts = {}
                for table in Base.metadata.sorted_tables:
                    counts[table.name] = (await session.exec(text(f'SELECT count(*) FROM "{table.name}"'))).one()[0]
                return counts
        finally:
            await engine.dispose()
    counts = asyncio.run(inspect())
    async def edit_seeded_data():
        engine = create_async_engine(url)
        try:
            async with AsyncSession(engine) as session:
                user = await session.get(User, data['accounts']['seller']['id'])
                product = await session.get(Product, data['objects']['product_listed'])
                user.display_name = 'Edited seller'
                product.title = 'Edited listing'
                await session.commit()
        finally:
            await engine.dispose()
    asyncio.run(edit_seeded_data())
    before = manifest.read_bytes()
    second = run()
    assert second.returncode == 0, second.stderr
    assert manifest.read_bytes() == before
    assert asyncio.run(inspect()) == counts

    async def assert_edits_preserved():
        engine = create_async_engine(url)
        try:
            async with AsyncSession(engine) as session:
                user = await session.get(User, data['accounts']['seller']['id'])
                product = await session.get(Product, data['objects']['product_listed'])
                assert user.display_name == 'Edited seller'
                assert product.title == 'Edited listing'
        finally:
            await engine.dispose()
    asyncio.run(assert_edits_preserved())

    async def exercise_workflows():
        engine = create_async_engine(url)
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                admin = await session.get(User, data['accounts']['admin']['id'])
                case_id = data['objects']['case_product_review']
                await claim_case(case_id, admin, session)
                await review_product(case_id, ReviewDecisionIn(result='rejected', reason='演示审核'), admin, session)
                product = await session.get(Product, data['objects']['product_pending'])
                await session.refresh(product)
                assert product.status == 'rejected'
                frozen = await session.get(Trade, data['objects']['trade_frozen'])
                assert frozen.frozen and frozen.status == 'disputed'
                assert (await session.get(User, data['accounts']['banned']['id'])).status == 'banned'
                old_get_settings = trade_timeout.get_settings
                trade_timeout.get_settings = lambda: SimpleNamespace(trade_confirm_timeout_days=7)
                try:
                    assert await trade_timeout.scan_once(session, trade_ids=(data['objects']['trade_timeout'],)) == 1
                finally:
                    trade_timeout.get_settings = old_get_settings
                timeout = await session.get(Trade, data['objects']['trade_timeout'])
                await session.refresh(timeout)
                assert timeout.status == 'abnormal' and timeout.frozen
        finally:
            await engine.dispose()
    asyncio.run(exercise_workflows())

    # A manifest bound to another storage target must fail without changing either target.
    env_file.write_text(env_file.read_text().replace(str(storage), str(tmp_path / 'other-storage')))
    refused = run()
    assert refused.returncode != 0
    assert manifest.read_bytes() == before
    assert not (tmp_path / 'other-storage').exists() or not any((tmp_path / 'other-storage').rglob('*'))
