"""SQLAlchemy 异步引擎与会话。

引擎/会话工厂延迟到首次使用才读取配置，避免仅导入模块就加载环境文件；
自动化验收通过临时 dotenv 选择独立 schema 或 SQLite 文件。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import get_settings

# 命名约定使循环外键、唯一约束和索引在所有方言下都有确定名称。
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


SQLModel.metadata = MetaData(naming_convention=NAMING_CONVENTION)
Base = SQLModel


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """返回进程级异步引擎（首次访问才读取配置）。"""
    global _engine
    if _engine is None:
        settings = get_settings()
        options: dict[str, Any] = {}
        if settings.database_url.startswith("postgresql+asyncpg:"):
            options["connect_args"] = {"server_settings": {"search_path": f'"{settings.database_schema}"'}}
        _engine = create_async_engine(settings.database_url, echo=False, future=True, **options)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    return _sessionmaker


class _LazyEngine:
    """兼容既有 ``from app.db.session import engine``，但不在导入期建引擎。"""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_engine(), name)


class _LazySessionFactory:
    def __call__(self, **kwargs: Any) -> AsyncSession:
        return get_sessionmaker()(**kwargs)


engine = _LazyEngine()
SessionLocal = _LazySessionFactory()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_sessionmaker()() as session:
        yield session
