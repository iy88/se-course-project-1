"""Persistent deployment initialization: explicitly creates an administrator and optional categories; no automated test scenarios."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from email_validator import EmailNotValidError, validate_email
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import ConfigurationError, Settings
from app.core.security import hash_password
from app.core.text import TextLimit
from app.db.migrations import upgrade_additive_schema
from app.db.session import Base
from app.models import Category, CategoryAlias, User
from app.services.audit import record_event


class InitialPasswordRequired(ConfigurationError):
    """The new administrator has no password; the CLI should prompt for it securely."""


@dataclass(frozen=True)
class InitializationResult:
    admin_id: int
    admin_created: bool
    categories_created: int
    categories_existing: int


def _email(value: str) -> str:
    try:
        normalized = validate_email(value.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise ConfigurationError("Invalid administrator email address") from None
    if len(normalized) > 254:
        raise ConfigurationError("Administrator email address is too long")
    return normalized


async def initialize(settings: Settings, *, admin_email: str, password: str | None = None,
                     admin_name: str = "管理员", categories: Sequence[str] = ()) -> InitializationResult:
    """Standalone transaction: existing accounts are not elevated, re-passworded, or unrestricted; SQLite creates tables, PostgreSQL is migrated explicitly first."""
    email = _email(admin_email)
    try:
        rule = TextLimit(64, required=True)
        name = rule.validate(admin_name)
        names = list(dict.fromkeys(rule.validate(value) for value in categories))
    except ValueError as exc:
        raise ConfigurationError(f"Invalid administrator display name or category name: {exc}") from None
    settings.prepare_runtime_paths()
    options: dict[str, Any] = {}
    if settings.database_url.startswith("postgresql+asyncpg:"):
        options["connect_args"] = {"server_settings": {"search_path": f'"{settings.database_schema}"'}}
    engine = create_async_engine(settings.database_url, **options)
    try:
        if engine.dialect.name == "sqlite":
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
                await connection.run_sync(upgrade_additive_schema)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db, db.begin():
            admin = (await db.exec(select(User).where(col(User.email) == email))).first()
            created = admin is None
            if admin is None:
                if password is None:
                    raise InitialPasswordRequired("Enter the initial password for the new administrator")
                if len(password) < 12 or len(password.encode("utf-8")) > 72:
                    raise ConfigurationError("The initial password must be at least 12 characters and at most 72 bytes in UTF-8")
                admin = User(email=email, display_name=name, password_hash=hash_password(password), role="admin", status="normal")
                db.add(admin)
                await db.flush()
                await record_event(db, "system.admin_initialize", target_type="user", target_id=admin.id,
                                   actor_id=admin.id, actor_role="system", reason_code="explicit_cli", after={"role": "admin"})
            elif admin.role != "admin" or admin.status != "normal":
                raise ConfigurationError("An account with this email already exists and is not a normal administrator; refusing to elevate it or lift restrictions")
            count_new = count_existing = 0
            for category_name in names:
                existing = (await db.exec(select(Category).where(col(Category.name) == category_name, col(Category.deleted_at).is_(None)))).first()
                alias = (await db.exec(select(CategoryAlias).where(col(CategoryAlias.name) == category_name, col(CategoryAlias.removed_at).is_(None)))).first()
                if existing is not None or alias is not None:
                    count_existing += 1
                    continue
                category = Category(name=category_name, status="active", created_by_id=admin.id)
                db.add(category)
                await db.flush()
                await record_event(db, "system.category_initialize", target_type="category", target_id=category.id,
                                   actor_id=admin.id, actor_role="system", reason_code="explicit_cli", after={"status": "active"})
                count_new += 1
            result = InitializationResult(admin.id, created, count_new, count_existing)
        return result
    finally:
        await engine.dispose()
