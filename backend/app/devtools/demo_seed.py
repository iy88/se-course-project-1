"""Persistent demonstration data. Run migrations separately before using this command.

The manifest is private and binds a seed to its database and storage target. Existing
business data is never cleared or adopted. Re-running preserves subsequent edits.

Scenario content, object keys, and assertions come from ``app.devtools.demo_scenarios``,
shared by the persistent seed and automated regression tests. Manifest version 2 records
the catalog digest; old versions or catalog changes are rejected explicitly instead of
silently skipping new scenarios when ``complete=true``.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import load_settings, resolve_env_file
from app.core.private_files import require_private
from app.devtools._support import credentials_lock, write_private_json
from app.devtools.demo_scenarios import catalog
from app.devtools.demo_scenarios.builder import build
from app.devtools.demo_scenarios.checks import validate_catalog

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = ROOT / 'var/demo/manifest.json'
MANIFEST_VERSION = 2


def _target(settings) -> str:
    # Never put connection credentials in the manifest or terminal.
    from sqlalchemy.engine import make_url
    database = make_url(settings.database_url).set(password=None).render_as_string(hide_password=True)
    parts = [database, settings.database_schema, settings.storage_backend,
             str(settings.storage_local_root or ''), settings.oss_endpoint,
             settings.oss_media_bucket, settings.oss_evidence_bucket, settings.storage_key_prefix]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()


def _load(path: Path, target: str) -> dict:
    signature = catalog.catalog_signature()
    if path.exists():
        require_private(path)
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('version') != MANIFEST_VERSION:
            raise ValueError('Unsupported manifest version; use a new manifest or migrate per the development docs; old versions are not adopted')
        if data.get('target') != target:
            raise ValueError('Manifest version or resource target does not match')
        if data.get('catalog_signature') != signature:
            raise ValueError('The scenario catalog has changed; the old manifest cannot skip new scenarios; re-seed with a new manifest')
        return data
    tag = secrets.token_hex(8)
    return {
        'version': MANIFEST_VERSION,
        'catalog_version': catalog.CATALOG_VERSION,
        'catalog_signature': signature,
        'target': target,
        'tag': tag,
        'complete': False,
        'accounts': {
            spec.key: {
                'email': f'demo-{spec.key}-{tag}@example.com',
                'password': secrets.token_urlsafe(24),
                'display_name': spec.display_name,
                'role': spec.role,
            }
            for spec in catalog.ACCOUNTS
        },
        'objects': {},
        'object_kinds': {},
        'files': {},
    }


def _object_models():
    from app.models.category import Category, CategoryAlias
    from app.models.governance import (
        DisposalCase,
        Notification,
        Report,
        ReportSupplement,
    )
    from app.models.im import Conversation, Message
    from app.models.product import (
        Comment,
        Favorite,
        Product,
        ProductEditHistory,
        ReviewRecord,
        ProductTagApplication,
    )
    from app.models.stored_object import StoredObject
    from app.models.trade import (
        CompletionConfirmation,
        Trade,
        TradeAgreement,
        TradeReview,
        TradeTransition,
    )
    from app.models.user import AccountRestriction, User

    return {
        'account': User,
        'avatar': User,
        'category': Category,
        'category_alias': CategoryAlias,
        'product': Product,
        'review_record': ReviewRecord,
        'tag_application': ProductTagApplication,
        'edit_history': ProductEditHistory,
        'comment': Comment,
        'favorite': Favorite,
        'trade': Trade,
        'agreement': TradeAgreement,
        'confirmation': CompletionConfirmation,
        'trade_transition': TradeTransition,
        'trade_review': TradeReview,
        'conversation': Conversation,
        'message': Message,
        'report': Report,
        'report_supplement': ReportSupplement,
        'disposal_case': DisposalCase,
        'account_restriction': AccountRestriction,
        'notification': Notification,
        'stored_object': StoredObject,
    }


async def _verify_existing(session, storage, data: dict, *, require_stored_objects: bool) -> None:
    """Validate existing manifest objects; read-only, no adoption or overwrite."""
    from app.core.security import verify_password
    from app.models.stored_object import StoredObject
    from app.models.user import User

    for key, account in data['accounts'].items():
        user = await session.get(User, account.get('id'))
        if user is None or user.email != account['email'] or user.role != account['role']:
            raise ValueError(f'Demo account in the manifest is missing or has changed ({key}); refusing automatic adoption')
        if not verify_password(account['password'], user.password_hash):
            raise ValueError(f'Demo account password in the manifest has changed ({key}); refusing automatic adoption')
    models = _object_models()
    for key, entry in data.get('objects', {}).items():
        if not isinstance(entry, dict) or 'id' not in entry or 'kind' not in entry:
            raise ValueError(f'Manifest object structure is unsupported ({key}); use a new manifest')
        model = models.get(entry['kind'])
        if model is None or await session.get(model, entry['id']) is None:
            raise ValueError(f'Business record in the manifest is incomplete ({key}); check manually')
    for name, entry in data['files'].items():
        if not storage.exists(entry['key']):
            raise ValueError(f'File in the manifest is missing ({name}); check storage manually')
        if require_stored_objects:
            registered = await session.get(StoredObject, entry['key'])
            if registered is None or registered.state != 'committed':
                raise ValueError(f'Object registration in the manifest is incomplete ({name}); check manually')
        if hashlib.sha256(storage.open(entry['key'])).hexdigest() != entry.get('sha256'):
            raise ValueError(f'Registered demo file content does not match ({name}); refusing to overwrite')


async def _seed(settings, manifest: Path, data: dict) -> None:
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import select
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.security import verify_password
    from app.models.user import User
    from app.storage.base import StorageAlreadyExists, build_storage, make_key

    options = {}
    if settings.database_url.startswith('postgresql+asyncpg:'):
        options['connect_args'] = {'server_settings': {'search_path': f'"{settings.database_schema}"'}}
    engine = create_async_engine(settings.database_url, **options)
    if settings.database_url.startswith('sqlite'):
        @event.listens_for(engine.sync_engine, 'connect')
        def _foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()
    storage = build_storage(settings)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    uploads: dict[str, bytes] = {}

    def register_file(name: str, namespace: str, filename: str, asset: str, content: bytes) -> dict:
        entry = data['files'].get(name)
        if entry is None:
            entry = {
                'key': make_key(namespace, filename),
                'asset': asset,
                'namespace': namespace,
                'bucket_role': 'evidence' if namespace == 'report' else 'media',
                'size': len(content),
                'sha256': hashlib.sha256(content).hexdigest(),
            }
            data['files'][name] = entry
        uploads[entry['key']] = content
        return entry

    def upload(item: tuple[str, bytes]) -> None:
        key, content = item
        try:
            storage.save_to_key(key, content)
        except StorageAlreadyExists:
            # A retry can encounter an object uploaded before a lost response.
            pass
        if storage.open(key) != content:
            raise ValueError('Registered demo file content does not match; refusing to overwrite')
    try:
        async with factory() as session:
            if data['complete']:
                await _verify_existing(session, storage, data, require_stored_objects=True)
                return
            found_accounts = [(await session.exec(select(User).where(User.email == account['email']))).first()
                              for account in data['accounts'].values()]
            if any(found_accounts):
                # A previous transaction may have committed but its final manifest write failed.
                if (not data['objects'] or not all(found_accounts) or
                    any(user is None or user.id != account.get('id') or user.role != account['role'] or
                        not verify_password(account['password'], user.password_hash)
                        for user, account in zip(found_accounts, data['accounts'].values()))):
                    raise ValueError('Partial or conflicting accounts detected; refusing adoption; check manually')
                await _verify_existing(session, storage, data, require_stored_objects=True)
                data['complete'] = True
                write_private_json(manifest, data)
                return
            # IDs recorded before a failed commit are advisory only; no existing row is adopted.
            for key, account in data['accounts'].items():
                found = (await session.exec(select(User).where(User.email == account['email']))).first()
                if found is not None:
                    raise ValueError(f'Demo email already exists ({key}); refusing adoption')
            validate_catalog()
            now = datetime.now(UTC)
            await build(session, data=data, settings=settings, ensure_file=register_file, now=now)
            # Journal every key before starting uploads. Commit only after the whole batch verifies.
            write_private_json(manifest, data)
            with ThreadPoolExecutor(max_workers=8) as pool:
                pending_uploads = [pool.submit(upload, item) for item in uploads.items()]
            for pending in pending_uploads:
                pending.result()
            await session.commit()
            data['complete'] = True
            write_private_json(manifest, data)
    finally:
        await engine.dispose()


def verify_manifest(manifest: Path, settings) -> dict:
    """Read-only validation entry point shared by ``demo-verify`` and tests; does not change business state."""
    from app.devtools.demo_scenarios.checks import validate_catalog

    summary = validate_catalog()
    data = _load(manifest, _target(settings))
    if not data.get('complete'):
        raise ValueError('Manifest initialization is not complete')
    return {
        'accounts': len(data['accounts']),
        'objects': len(data['objects']),
        'files': len(data['files']),
        'scenarios': summary.scenarios,
        'catalog_signature': data['catalog_signature'],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', help='dotenv path; defaults to APP_ENV_FILE or backend/.env.dev')
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST, help='private manifest path')
    args = parser.parse_args(argv)
    try:
        path = args.manifest.expanduser().absolute()
        env_file = resolve_env_file(args.env_file)
        # Imports that use get_settings must see the selected file too.
        os.environ['APP_ENV_FILE'] = str(env_file)
        from app.core.config import get_settings
        get_settings.cache_clear()
        settings = load_settings(env_file)
        settings.prepare_runtime_paths()
        validate_catalog()
        with credentials_lock(path):
            data = _load(path, _target(settings))
            write_private_json(path, data)
            asyncio.run(_seed(settings, path, data))
        print(f'demo seed ready; private manifest: {path}')
        print(f"demo scenarios: {len(catalog.SCENARIOS)}; accounts: {len(catalog.ACCOUNTS)}; products: {len(catalog.PRODUCTS)}")
        return 0
    except ValueError as exc:
        print(f'demo seed failed: {exc}', file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI boundary avoids disclosing resource credentials
        print(f'demo seed failed: {type(exc).__name__}; check migrations, configuration, and resource access', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
