"""SQLite/local regression for the persistent demo-seed: real records, resource validation, and idempotency."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.private_files import require_private
from app.core.security import verify_password
from app.db.session import Base
from app.devtools.demo_scenarios import catalog
from app.devtools.demo_scenarios.verify import verify
from app.models import User
from app.models.product import Product


def _write_env(tmp_path: Path) -> tuple[Path, str, Path, Path]:
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
    return env_file, f'sqlite+aiosqlite:///{db_path}', storage, manifest


def _create_schema(url: str, *, existing: bool = True) -> None:
    async def run():
        engine = create_async_engine(url)
        @event.listens_for(engine.sync_engine, 'connect')
        def foreign_keys(conn, _):
            conn.execute('PRAGMA foreign_keys=ON')
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        if existing:
            async with AsyncSession(engine) as session:
                session.add(User(email='existing@example.org', password_hash='original-hash', display_name='Existing'))
                await session.commit()
        await engine.dispose()
    asyncio.run(run())


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith(('APP_ENV_', 'DATABASE_', 'STORAGE_', 'OSS_', 'JWT_', 'FILE_URL_'))}


def _run(env_file: Path, manifest: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, '-X', 'utf8', '-m', 'app.manage', 'demo-seed',
         '--env-file', str(env_file), '--manifest', str(manifest)],
        cwd=Path(__file__).resolve().parents[1], env=_clean_env(),
        capture_output=True, text=True, encoding='utf-8', check=False,
    )


def _load_manifest(manifest: Path) -> dict:
    return json.loads(manifest.read_text(encoding='utf-8'))


def _id(data: dict, key: str) -> int:
    return int(data['objects'][key]['id'])


def _session(url: str) -> tuple:
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def test_demo_seed_sqlite_local(tmp_path):
    env_file, url, storage_root, manifest = _write_env(tmp_path)
    _create_schema(url)
    assert not manifest.exists()

    first = _run(env_file, manifest)
    assert first.returncode == 0, first.stderr
    data = _load_manifest(manifest)
    assert data['complete'] and data['catalog_signature'] == catalog.catalog_signature()
    assert data['scenarios'] == [scenario.key for scenario in catalog.SCENARIOS]
    assert set(data['object_kinds']) == set(data['objects'])
    require_private(manifest)
    final_keys = {entry['key'] for entry in data['files'].values()}
    assert {p.relative_to(storage_root).as_posix() for p in storage_root.rglob('*') if p.is_file()} == final_keys
    assert len(data['accounts']) == len(catalog.ACCOUNTS)

    async def inspect_and_verify():
        from app.storage.base import LocalStorage
        import app.storage.base as storage_base
        storage = LocalStorage(storage_root)
        storage_base._storage = storage
        engine, factory = _session(url)
        try:
            async with factory() as session:
                violations = (await session.exec(__import__('sqlalchemy').text('PRAGMA foreign_key_check'))).all()
                assert not violations
                existing = (await session.exec(select(User).where(User.email == 'existing@example.org'))).one()
                assert (existing.display_name, existing.password_hash) == ('Existing', 'original-hash')
                for account in data['accounts'].values():
                    user = await session.get(User, account['id'])
                    assert user.email == account['email'] and user.role == account['role']
                for key in ('admin', 'seller'):
                    account = data['accounts'][key]
                    user = await session.get(User, account['id'])
                    assert verify_password(account['password'], user.password_hash)
                report = await verify(session, storage, data, verify_api=False)
                assert report.ok(), report.errors[:10]
                counts = {}
                for table in Base.metadata.sorted_tables:
                    counts[table.name] = (await session.exec(
                        __import__('sqlalchemy').text(f'SELECT count(*) FROM "{table.name}"')
                    )).one()[0]
                return counts
        finally:
            await engine.dispose()
    counts = asyncio.run(inspect_and_verify())

    async def inspect_counts():
        from sqlalchemy import text
        engine, factory = _session(url)
        try:
            async with factory() as session:
                result = {}
                for table in Base.metadata.sorted_tables:
                    result[table.name] = (await session.exec(text(f'SELECT count(*) FROM "{table.name}"'))).one()[0]
                return result
        finally:
            await engine.dispose()

    # Re-run idempotency: manual edits must be preserved, and the manifest and counts stay unchanged.
    async def edit_seeded_data():
        engine, factory = _session(url)
        try:
            async with factory() as session:
                user = await session.get(User, data['accounts']['seller']['id'])
                product = await session.get(Product, _id(data, 'product_bike'))
                user.display_name = 'Edited seller'
                product.title = 'Edited listing'
                await session.commit()
        finally:
            await engine.dispose()
    asyncio.run(edit_seeded_data())
    before = manifest.read_bytes()
    second = _run(env_file, manifest)
    assert second.returncode == 0, second.stderr
    assert manifest.read_bytes() == before
    assert asyncio.run(inspect_counts()) == counts

    async def assert_edits_preserved():
        engine, factory = _session(url)
        try:
            async with factory() as session:
                user = await session.get(User, data['accounts']['seller']['id'])
                product = await session.get(Product, _id(data, 'product_bike'))
                assert (user.display_name, product.title) == ('Edited seller', 'Edited listing')
        finally:
            await engine.dispose()
    asyncio.run(assert_edits_preserved())

    # Old versions, catalog changes, and target changes must all be rejected explicitly, without writing a new target.
    stale_version = dict(data)
    stale_version['version'] = 1
    manifest.write_bytes(json.dumps(stale_version, ensure_ascii=False).encode())
    refused = _run(env_file, manifest)
    assert refused.returncode != 0 and 'version' in refused.stderr
    stale_signature = dict(data)
    stale_signature['catalog_signature'] = '0' * 64
    manifest.write_bytes(json.dumps(stale_signature, ensure_ascii=False).encode())
    refused = _run(env_file, manifest)
    assert refused.returncode != 0 and 'catalog' in refused.stderr
    manifest.write_bytes(before)

    other_storage = tmp_path / 'other-storage'
    env_file.write_text(env_file.read_text().replace(str(storage_root), str(other_storage)))
    refused = _run(env_file, manifest)
    assert refused.returncode != 0
    assert manifest.read_bytes() == before
    assert not other_storage.exists() or not any(other_storage.rglob('*'))
