"""环境数据重置：默认预览，生产须显式授权；执行前停止所有后端与测试进程。"""
import argparse
import asyncio
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
        bucket = _create_bucket(config, name)
        while True:
            result = bucket.client.list_objects_v2(oss.ListObjectsV2Request(bucket=name, prefix=config.key_prefix, max_keys=1000))
            keys = [item.key for item in (result.contents or [])]
            _close_result(result)
            if not keys:
                break
            for key in keys:
                if not key.startswith(config.key_prefix):
                    raise ValueError('OSS 对象超出前缀范围')
                _close_result(bucket.delete_object(key))
        print(f'OSS cleared: {name}/{config.key_prefix}', flush=True)


def local_target(s: Settings) -> Path:
    if s.storage_local_root is None:
        raise ValueError('需要配置 STORAGE_LOCAL_ROOT')
    root = Path(s.storage_local_root).resolve()
    target = root
    target = target.resolve()
    if target != root and root not in target.parents:
        raise ValueError('本地存储目标超出根目录')
    if target in {Path('/'), Path.home(), Path.cwd(), Path.cwd().parent}:
        raise ValueError('本地存储需要独立数据目录')
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
    parser.add_argument('--env-file', help='dotenv 文件，默认 APP_ENV_FILE 或 .env.dev')
    parser.add_argument('--allow-production', action='store_true', help='显式允许预览/重置 .env.prod 生产资源')
    parser.add_argument('--whole-buckets', action='store_true', help='确认空 OSS 前缀时清理两个配置桶的全部当前对象')
    parser.add_argument('--confirm', help='执行时填写目标数据库名')
    args = parser.parse_args(argv)
    try:
        check_inherited_overrides()
        selected = resolve_env_file(args.env_file)
        if selected == PROD_ENV_FILE.resolve() or selected.name == '.env.prod':
            if not args.allow_production:
                raise ValueError('生产重置需要 --allow-production')
        else:
            selected = resolve_dev_env_file({'APP_ENV_FILE': str(selected)})
        s = load_settings(selected)
        if s.environment == 'prod' and not args.allow_production:
            raise ValueError('生产重置需要 --allow-production')
        if args.allow_production and (s.environment != 'prod' or selected != PROD_ENV_FILE.resolve()):
            raise ValueError('--allow-production 仅用于后端 .env.prod 生产配置')
        url = make_url(s.database_url)
        database_name = url.database
        if not database_name:
            raise ValueError('数据库 URL 需要包含数据库名或 SQLite 文件路径')
        m = None
        if url.drivername == 'postgresql+asyncpg':
            m = load_migration_settings(selected)
            validate_migration_context(m)
            if s.database_schema in {'public', 'information_schema'}:
                raise ValueError('需要独立应用 schema')
            print(f'PostgreSQL: {url.host}:{url.port}/{url.database}, schema={s.database_schema}')
        elif url.drivername == 'sqlite+aiosqlite':
            print(f'SQLite: {url.database}')
        else:
            raise ValueError('数据库类型不受支持')
        if s.kv_backend == 'redis':
            if not s.redis_key_prefix:
                raise ValueError('需要非空 REDIS_KEY_PREFIX')
            r = make_url(s.redis_url)
            print(f'Redis: {r.host}:{r.port}/{r.database}, prefix={s.redis_key_prefix}')
        else:
            print('KV: memory（服务重启后使用空存储）')
        if s.storage_backend == 'oss':
            print(f'OSS: {s.oss_media_bucket}, {s.oss_evidence_bucket}, prefix={s.storage_key_prefix or "[整个桶]"}')
        else:
            target = local_target(s)
            if url.drivername == 'sqlite+aiosqlite' and url.database != ':memory:':
                database = Path(database_name).resolve()
                if database == target or target in database.parents:
                    raise ValueError('SQLite 文件须放在本地对象清理目录之外')
            print(f'Local storage: {target}')
        confirmation = Path(database_name).name if m is None else database_name
        print(f'Confirmation: {confirmation}')
        if not args.execute:
            print('仅预览，未修改资源。执行前停止服务，再使用 --execute --confirm <数据库名>。')
            return 0
        if s.storage_backend == 'oss' and not s.storage_key_prefix and not args.whole_buckets:
            raise ValueError('当前 OSS 范围为整个桶；确认清空两个配置桶的全部当前对象后添加 --whole-buckets')
        if args.confirm != confirmation:
            raise ValueError('--confirm 必须与目标数据库名一致')
        print('开始重置；跨服务无整体事务，失败后修复原因并重跑。', flush=True)
        if s.storage_backend == 'oss':
            clear_oss(s)
        else:
            clear_local(s)
        asyncio.run(clear_db_redis(s, m))
        previous = os.environ.get('APP_ENV_FILE')
        try:
            os.environ['APP_ENV_FILE'] = str(selected)
            run_migrate('head')
        finally:
            if previous is None:
                os.environ.pop('APP_ENV_FILE', None)
            else:
                os.environ['APP_ENV_FILE'] = previous
        print('重置完成；初始化 seed 或使用新的 demo manifest 运行 demo-seed。旧 manifest 请先归档。')
        return 0
    except (ConfigurationError, ValueError) as exc:
        print(str(exc))
        return 1
    except Exception:  # noqa: BLE001 - 不输出可能包含凭据的底层异常
        print('重置失败，请核对资源状态后重试（底层异常已隐藏）。')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
