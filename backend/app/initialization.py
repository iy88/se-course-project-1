"""持久部署初始化：明确创建管理员和可选分类，不执行自动化测试场景。"""
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
from app.db.migrations import upgrade_additive_schema
from app.db.session import Base
from app.models import Category, CategoryAlias, User
from app.services.audit import record_event


class InitialPasswordRequired(ConfigurationError):
    """新管理员尚无密码；CLI应安全提示输入。"""


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
        raise ConfigurationError("管理员邮箱格式无效") from None
    if len(normalized) > 254:
        raise ConfigurationError("管理员邮箱过长")
    return normalized


async def initialize(settings: Settings, *, admin_email: str, password: str | None = None,
                     admin_name: str = "管理员", categories: Sequence[str] = ()) -> InitializationResult:
    """独立事务：已有账户不提权、改密或解除限制；SQLite建表，PG先显式迁移。"""
    email = _email(admin_email)
    name = admin_name.strip()
    if not name or len(name) > 64:
        raise ConfigurationError("管理员显示名称须为1至64个字符")
    names = list(dict.fromkeys(value.strip() for value in categories))
    if any(not value or len(value) > 64 for value in names):
        raise ConfigurationError("分类名称须为1至64个字符")
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
                    raise InitialPasswordRequired("请输入新管理员的初始密码")
                if len(password) < 12 or len(password.encode("utf-8")) > 72:
                    raise ConfigurationError("初始密码须至少12个字符，UTF-8编码不超过72字节")
                admin = User(email=email, display_name=name, password_hash=hash_password(password), role="admin", status="normal")
                db.add(admin)
                await db.flush()
                await record_event(db, "system.admin_initialize", target_type="user", target_id=admin.id,
                                   actor_id=admin.id, actor_role="system", reason_code="explicit_cli", after={"role": "admin"})
            elif admin.role != "admin" or admin.status != "normal":
                raise ConfigurationError("同邮箱账户已存在且不是正常管理员；拒绝提权或解除限制")
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
