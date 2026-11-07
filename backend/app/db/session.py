"""SQLAlchemy async engine and sessions.

The engine/session factory is created lazily and reads configuration on first use.
Each process creates its own engine and the lifecycle entry point explicitly calls
``dispose_engine`` on exit; a child process must not reuse the parent's connections.
Pool size, wait time, and PostgreSQL statement/lock timeouts come from the selected
dotenv for the current role.
"""

from __future__ import annotations

import time
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
from app.observability import install_sql_observers

# The naming convention gives cyclic foreign keys, unique constraints, and indexes deterministic names in every dialect.
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


def _engine_options(settings) -> dict[str, Any]:
    options: dict[str, Any] = {"echo": False, "future": True}
    if not settings.database_url.startswith("postgresql+asyncpg:"):
        return options
    pool_size, max_overflow = settings.db_pool
    options.update(
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_pre_ping=settings.db_pre_ping,
        pool_recycle=settings.db_recycle_seconds,
    )
    options["connect_args"] = {
        "server_settings": {
            "search_path": f'"{settings.database_schema}"',
            "application_name": f"campus-{settings.app_role}",
            # Millisecond budgets are enforced by PostgreSQL on this connection.
            # Lock/statement timeouts protect the pool from stuck requests;
            # idle-in-transaction prevents a forgotten transaction holding rows.
            "lock_timeout": str(settings.db_lock_timeout_ms),
            "statement_timeout": str(settings.db_statement_timeout_ms),
            "idle_in_transaction_session_timeout": str(settings.db_idle_in_transaction_timeout_ms),
        }
    }
    return options


def get_engine() -> AsyncEngine:
    """Return the process-level async engine (configuration is read on first access)."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, **_engine_options(settings))
        install_sql_observers(_engine)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)
    return _sessionmaker


async def dispose_engine() -> None:
    """Close this process's pool; idempotent for shutdown and test isolation."""
    global _engine, _sessionmaker
    engine = _engine
    _engine = None
    _sessionmaker = None
    if engine is not None:
        await engine.dispose()
    # Admission cache is keyed by engine identity; never let a disposed test
    # engine's snapshot leak into the next engine/session.
    from app.realtime.admission import clear_admission_cache

    clear_admission_cache()


class _LazyEngine:
    """Keep existing ``from app.db.session import engine`` imports working without creating the engine at import time."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_engine(), name)


class _LazySessionFactory:
    def __call__(self, **kwargs: Any) -> AsyncSession:
        return get_sessionmaker()(**kwargs)


engine = _LazyEngine()
SessionLocal = _LazySessionFactory()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    started = time.perf_counter()
    async with get_sessionmaker()() as session:
        # Keep checkout lazy: unauthenticated WS/HTTP paths must not consume a
        # scarce DB connection. The first SQL statement records an approximate
        # checkout wait; session hold covers the whole dependency scope.
        from app.observability import counters, mark_db_request_start

        mark_db_request_start()
        try:
            yield session
        finally:
            counters.observe("db.session_hold_ms", (time.perf_counter() - started) * 1000)
