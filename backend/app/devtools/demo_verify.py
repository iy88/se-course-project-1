"""只读核验持久 demo-seed；不修改业务状态、不打印秘密。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from app.core.config import load_settings, resolve_env_file
from app.devtools.demo_seed import DEFAULT_MANIFEST, _load, _target
from app.devtools.demo_scenarios.checks import validate_catalog
from app.devtools.demo_scenarios.verify import verify


async def _run(settings, manifest: Path, *, verify_api: bool):
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.storage.base import build_storage

    options = {}
    if settings.database_url.startswith('postgresql+asyncpg:'):
        options['connect_args'] = {'server_settings': {'search_path': f'"{settings.database_schema}"'}}
    engine = create_async_engine(settings.database_url, **options)
    if settings.database_url.startswith('sqlite'):
        @event.listens_for(engine.sync_engine, 'connect')
        def _foreign_keys(db_connection, _record):
            cursor = db_connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()
    storage = build_storage(settings)
    # 只读 API 检查复用同一个存储实例；不改配置、不落业务写入。
    import app.storage.base as storage_base

    storage_base._storage = storage
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            data = _load(manifest, _target(settings))
            return await verify(session, storage, data, verify_api=verify_api)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', help='dotenv path; defaults to APP_ENV_FILE or backend/.env.dev')
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST, help='private manifest path')
    parser.add_argument('--skip-api', action='store_true', help='跳过只读 API 可见性检查')
    parser.add_argument('--json', action='store_true', help='输出 JSON 摘要（不含凭据/连接串）')
    args = parser.parse_args(argv)
    try:
        path = args.manifest.expanduser().absolute()
        env_file = resolve_env_file(args.env_file)
        os.environ['APP_ENV_FILE'] = str(env_file)
        from app.core.config import get_settings
        get_settings.cache_clear()
        settings = load_settings(env_file)
        settings.prepare_runtime_paths()
        summary = validate_catalog()
        report = asyncio.run(_run(settings, path, verify_api=not args.skip_api))
        payload = {
            'ok': report.ok(),
            'checks': report.checks,
            'errors': report.errors,
            'counts': report.counts,
            'scenarios': summary.scenarios,
            'mappings': len(summary.mappings),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"demo verify: checks={report.checks} ok={report.ok()} scenarios={summary.scenarios} "
                  f"accounts={report.counts.get('accounts', 0)} products={report.counts.get('products', 0)} "
                  f"trades={report.counts.get('trades', 0)} reports={report.counts.get('reports', 0)} "
                  f"files={report.counts.get('files', 0)}")
            for error in report.errors:
                print(f'demo verify error: {error}', file=sys.stderr)
        return 0 if report.ok() else 1
    except ValueError as exc:
        print(f'demo verify failed: {exc}', file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - 不输出连接串/凭据
        print(f'demo verify failed: {type(exc).__name__}; 请检查迁移、配置及资源访问', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
