"""后端管理命令。

用法（默认读取 backend/.env.dev，独立迁移命令才读取迁移凭据）::

    python -m app.manage migrate
    python -m app.manage serve
    python -m app.manage seed --admin-email <administrator email>
    python -m app.manage demo-seed --env-file .env.dev

持久初始化使用 seed 子命令；自动化身份 seed 属于验收套件（``python -m tests.acceptance_real.seed``），
不再由应用管理命令提供；应用模块不反向依赖 tests。
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import re
import sys
import traceback
from argparse import Namespace

from app.core.config import (
    BACKEND_ROOT,
    ConfigurationError,
    load_migration_settings,
    load_settings,
    validate_migration_context,
)

_REVISION = re.compile(r"^[A-Za-z0-9_]+$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.manage", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    migrate = sub.add_parser("migrate", help="apply versioned PostgreSQL migrations")
    migrate.add_argument("--revision", default="head", help="target revision (default: head)")

    sub.add_parser("serve", help="run the API server using API_HOST/API_PORT from the selected dotenv")
    seed = sub.add_parser("seed", help="persist initial administrator and optional reference categories")
    seed.add_argument("--admin-email", default=None, help="administrator email; prompted if omitted")
    seed.add_argument("--admin-name", default="管理员", help="display name for a new administrator")
    seed.add_argument("--category", action="append", default=[], help="optional initial category; repeatable")
    demo = sub.add_parser("demo-seed", help="persist demonstration accounts and business scenarios in the selected environment")
    demo.add_argument("--env-file", default=None, help="dotenv file (default: APP_ENV_FILE or .env.dev)")
    demo.add_argument("--manifest", default=None, help="private demo manifest path")
    return parser


def run_migrate(revision: str) -> int:
    if not _REVISION.match(revision):
        raise ConfigurationError("invalid migration revision")
    settings = load_settings()
    if settings.database_url.startswith("sqlite+"):
        if revision != "head":
            raise ConfigurationError("SQLite本地初始化只支持head；PostgreSQL使用版本化迁移")
        from sqlalchemy.ext.asyncio import create_async_engine

        import app.models  # noqa: F401 - register metadata
        from app.db.migrations import upgrade_additive_schema
        from app.db.session import Base

        async def migrate_local() -> None:
            settings.prepare_runtime_paths()
            engine = create_async_engine(settings.database_url)
            try:
                async with engine.begin() as connection:
                    await connection.run_sync(Base.metadata.create_all)
                    await connection.run_sync(upgrade_additive_schema)
            finally:
                await engine.dispose()

        asyncio.run(migrate_local())
        print("SQLite schema initialized; existing data preserved.")
        return 0
    migration = load_migration_settings()
    validate_migration_context(migration)
    # 延迟导入，普通服务/测试不会加载 Alembic 或迁移配置。
    from alembic import command
    from alembic.config import Config

    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(config, revision)
    return 0


def run_serve() -> int:
    settings = load_settings()
    settings.validate_for_runtime()
    import uvicorn

    uvicorn.run("app.main:app", host=settings.api_host, port=settings.api_port, log_level="info")
    return 0


def run_seed(admin_email: str | None, admin_name: str, categories: list[str]) -> int:
    from app.initialization import InitialPasswordRequired, initialize

    settings = load_settings()
    email = admin_email or input("Administrator email: ").strip()
    try:
        result = asyncio.run(initialize(settings, admin_email=email, admin_name=admin_name, categories=categories))
    except InitialPasswordRequired:
        if not sys.stdin.isatty():
            raise ConfigurationError("新管理员需要交互终端输入密码；不接受命令行明文密码") from None
        password = getpass.getpass("New administrator password: ")
        if password != getpass.getpass("Confirm administrator password: "):
            raise ConfigurationError("两次密码不一致")
        result = asyncio.run(initialize(settings, admin_email=email, password=password, admin_name=admin_name, categories=categories))
    print(f"Initialization: admin_id={result.admin_id} admin_created={result.admin_created} "
          f"categories_created={result.categories_created} categories_existing={result.categories_existing}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args: Namespace = _parser().parse_args(argv)
    try:
        if args.command == "migrate":
            return run_migrate(args.revision)
        if args.command == "serve":
            return run_serve()
        if args.command == "seed":
            return run_seed(args.admin_email, args.admin_name, args.category)
        if args.command == "demo-seed":
            from app.devtools.demo_seed import main as run_demo_seed

            demo_args = []
            if args.env_file is not None:
                demo_args.extend(["--env-file", args.env_file])
            if args.manifest is not None:
                demo_args.extend(["--manifest", args.manifest])
            return run_demo_seed(demo_args)
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - CLI 输出完整异常以便定位管理命令故障
        traceback.print_exc()
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
