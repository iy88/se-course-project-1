"""Alembic 环境：迁移凭据只在本进程读取，并显式 SET ROLE owner。

服务进程不会导入本模块；普通 Settings 也不含迁移 URL。
"""

from __future__ import annotations

import asyncio

import app.models  # noqa: F401 - 注册全部模型到 metadata  # pyright: ignore[reportUnusedImport]
from alembic import context
from app.core.config import (
    load_migration_settings,
    validate_migration_context,
)
from app.db.session import Base
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config

target_metadata = Base.metadata


def _version_table_schema(dialect_name: str) -> str | None:
    return config.attributes["migration_schema"] if dialect_name == "postgresql" else None


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    # Alembic 自己的版本表不属于应用 metadata，避免 autogenerate 生成删除语句。
    return not (type_ == "table" and name == "alembic_version")


def _configure(connection, dialect_name: str) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=False,
        include_schemas=False,
        include_object=_include_object,
        version_table_schema=_version_table_schema(dialect_name),
    )


def run_migrations_offline() -> None:
    settings = load_migration_settings()
    validate_migration_context(settings)
    config.attributes["migration_owner_role"] = settings.migration_owner_role
    config.attributes["migration_app_role"] = settings.app_role
    config.attributes["migration_environment"] = settings.environment
    config.attributes["migration_schema"] = settings.database_schema
    dialect_name = settings.migration_database_url.split("://", 1)[0].split("+", 1)[0]
    context.configure(
        url=settings.migration_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=_version_table_schema(dialect_name),
    )
    with context.begin_transaction():
        context.run_migrations()


def _migration_attributes(settings) -> None:
    config.attributes["migration_owner_role"] = settings.migration_owner_role
    config.attributes["migration_app_role"] = settings.app_role
    config.attributes["migration_environment"] = settings.environment
    config.attributes["migration_schema"] = settings.database_schema


async def run_migrations_online() -> None:
    settings = load_migration_settings()
    validate_migration_context(settings)
    _migration_attributes(settings)

    connectable = create_async_engine(settings.migration_database_url, poolclass=pool.NullPool)
    try:
        async with connectable.connect() as connection:
            dialect_name = connection.dialect.name
            if dialect_name == "postgresql":
                role = settings.migration_owner_role
                # 标识符已由 MigrationSettings 校验；仍使用双引号固定角色名。
                await connection.execute(text(f'SET ROLE "{role}"'))
                await connection.execute(text(f'SET search_path = "{settings.database_schema}"'))
            await connection.run_sync(lambda sync_connection: _run_sync(sync_connection, dialect_name))
            await connection.commit()
    finally:
        await connectable.dispose()


def _run_sync(connection, dialect_name: str) -> None:
    _configure(connection, dialect_name)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
