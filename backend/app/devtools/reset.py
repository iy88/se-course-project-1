"""Environment data reset: preview by default; production requires explicit authorization; stop all backend and test processes before running."""
import argparse
import asyncio
import json
import os
import shutil
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import (
    PROD_ENV_FILE,
    ConfigurationError,
    MigrationSettings,
    Settings,
    load_migration_settings,
    load_settings,
    resolve_env_file,
    validate_migration_context,
)
from app.devtools._support import check_inherited_overrides, resolve_dev_env_file
from app.manage import run_migrate


def clear_oss(s: Settings) -> None:
    import alibabacloud_oss_v2 as oss

    from app.storage.oss import OssConfig, _close_result, _create_bucket
    config = OssConfig.from_settings(s)
    for name in (config.media_bucket, config.evidence_bucket):
        print(f'OSS clearing: {name}/{config.key_prefix}', flush=True)
        bucket = _create_bucket(config, name)
        deleted_count = 0
        while True:
            result = bucket.client.list_objects_v2(oss.ListObjectsV2Request(bucket=name, prefix=config.key_prefix, max_keys=1000))
            keys = [item.key for item in (result.contents or [])]
            _close_result(result)
            if not keys:
                break
            for key in keys:
                if not key.startswith(config.key_prefix):
                    raise ValueError('OSS object is outside the prefix range')
            result = bucket.client.delete_multiple_objects(oss.DeleteMultipleObjectsRequest(
                bucket=name,
                delete=oss.Delete(objects=[oss.ObjectIdentifier(key=key) for key in keys], quiet=False),
            ))
            try:
                confirmed = {item.key for item in (result.deleted_objects or [])}
                if confirmed != set(keys):
                    raise ValueError('OSS batch deletion was not fully confirmed; check resources and rerun')
            finally:
                _close_result(result)
            deleted_count += len(keys)
            print(f'OSS clearing: {name}, deleted={deleted_count}', flush=True)
        print(f'OSS cleared: {name}/{config.key_prefix}', flush=True)


def local_target(s: Settings) -> Path:
    if s.storage_local_root is None:
        raise ValueError('STORAGE_LOCAL_ROOT must be configured')
    root = Path(s.storage_local_root).resolve()
    target = root
    target = target.resolve()
    if target != root and root not in target.parents:
        raise ValueError('Local storage target is outside the root directory')
    if target in {Path('/'), Path.home(), Path.cwd(), Path.cwd().parent}:
        raise ValueError('Local storage requires a dedicated data directory')
    return target


def clear_local(s: Settings) -> None:
    target = local_target(s)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    print(f'Local storage cleared: {target}')


async def clear_db_redis(s: Settings, m: MigrationSettings | None) -> None:
    if m is None:
        database = make_url(s.database_url).database
        if database and database != ':memory:':
            for suffix in ('', '-wal', '-shm', '-journal'):
                Path(database + suffix).unlink(missing_ok=True)
        print('SQLite database reset')
    else:
        engine = create_async_engine(m.migration_database_url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f'SET ROLE "{m.migration_owner_role}"'))
                tables = (await conn.execute(text('SELECT tablename FROM pg_tables WHERE schemaname=:s'), {'s': s.database_schema})).scalars().all()
                if tables:
                    quote = engine.dialect.identifier_preparer.quote_identifier
                    names = ', '.join(f'{quote(s.database_schema)}.{quote(t)}' for t in tables)
                    await conn.execute(text(f'DROP TABLE {names}'))
        finally:
            await engine.dispose()
    if s.kv_backend == 'redis':
        from redis.asyncio import Redis
        redis = Redis.from_url(s.redis_url)
        try:
            async for key in redis.scan_iter(match=s.redis_key_prefix + '*', count=500):
                await redis.delete(key)
        finally:
            await redis.aclose()
    else:
        print('Memory KV: stopped service releases data; restart creates an empty store')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--env-file', help='dotenv file; defaults to APP_ENV_FILE or .env.dev')
    parser.add_argument('--allow-production', action='store_true', help='Explicitly allow preview/reset of .env.prod production resources')
    parser.add_argument('--whole-buckets', action='store_true', help='Confirm clearing all current objects in both configured buckets when the OSS prefix is empty')
    parser.add_argument('--confirm', help='Target database name to supply when executing')
    args = parser.parse_args(argv)
    stage = 'configuration'
    try:
        check_inherited_overrides()
        selected = resolve_env_file(args.env_file)
        if selected == PROD_ENV_FILE.resolve() or selected.name == '.env.prod':
            if not args.allow_production:
                raise ValueError('Production reset requires --allow-production')
        else:
            selected = resolve_dev_env_file({'APP_ENV_FILE': str(selected)})
        s = load_settings(selected)
        if s.environment == 'prod' and not args.allow_production:
            raise ValueError('Production reset requires --allow-production')
        if args.allow_production and (s.environment != 'prod' or selected != PROD_ENV_FILE.resolve()):
            raise ValueError('--allow-production is only valid for the backend .env.prod production configuration')
        url = make_url(s.database_url)
        database_name = url.database
        if not database_name:
            raise ValueError('Database URL must include a database name or SQLite file path')
        m = None
        if url.drivername == 'postgresql+asyncpg':
            m = load_migration_settings(selected)
            validate_migration_context(m)
            if s.database_schema in {'public', 'information_schema'}:
                raise ValueError('A dedicated application schema is required')
            print(f'PostgreSQL: {url.host}:{url.port}/{url.database}, schema={s.database_schema}')
        elif url.drivername == 'sqlite+aiosqlite':
            print(f'SQLite: {url.database}')
        else:
            raise ValueError('Database type is not supported')
        if s.kv_backend == 'redis':
            if not s.redis_key_prefix:
                raise ValueError('A non-empty REDIS_KEY_PREFIX is required')
            r = make_url(s.redis_url)
            print(f'Redis: {r.host}:{r.port}/{r.database}, prefix={s.redis_key_prefix}')
        else:
            print('KV: memory (an empty store is used after service restart)')
        if s.storage_backend == 'oss':
            print(f'OSS: {s.oss_media_bucket}, {s.oss_evidence_bucket}, prefix={s.storage_key_prefix or "[entire bucket]"}')
        else:
            target = local_target(s)
            if url.drivername == 'sqlite+aiosqlite' and url.database != ':memory:':
                database = Path(database_name).resolve()
                if database == target or target in database.parents:
                    raise ValueError('SQLite file must be outside the local object cleanup directory')
            print(f'Local storage: {target}')
        confirmation = Path(database_name).name if m is None else database_name
        print(f'Confirmation: {confirmation}')
        if not args.execute:
            print('Preview only; no resources were modified. Stop services before executing, then use --execute --confirm <database name>.')
            return 0
        if s.storage_backend == 'oss' and not s.storage_key_prefix and not args.whole_buckets:
            raise ValueError('The current OSS scope is the entire bucket; add --whole-buckets after confirming that all current objects in both configured buckets may be cleared')
        if args.confirm != confirmation:
            raise ValueError('--confirm must match the target database name')
        print('Starting reset; there is no cross-service transaction, so fix the cause and rerun after a failure.', flush=True)
        stage = 'storage'
        if s.storage_backend == 'oss':
            clear_oss(s)
        else:
            clear_local(s)
        stage = 'database/redis'
        asyncio.run(clear_db_redis(s, m))
        stage = 'migrations'
        previous = os.environ.get('APP_ENV_FILE')
        try:
            os.environ['APP_ENV_FILE'] = str(selected)
            run_migrate('head')
        finally:
            if previous is None:
                os.environ.pop('APP_ENV_FILE', None)
            else:
                os.environ['APP_ENV_FILE'] = previous
        print('Reset complete; initialize the seed or run demo-seed with a new demo manifest. Archive the old manifest first.')
        return 0
    except (ConfigurationError, ValueError) as exc:
        print(str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001 - print only allowlisted diagnostics, never credentials or underlying messages
        from app.storage.oss import _error_details
        print(f'Reset failed, stage={stage}; diagnostics=' + json.dumps(_error_details(exc), ensure_ascii=True))
        print('Check resource state and retry; underlying messages and connection strings were not printed.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
