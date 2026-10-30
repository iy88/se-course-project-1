"""C-03 商品分类（单级多标签）与别名。"""

from datetime import datetime
from typing import Any, cast

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlmodel import Field, col

from app.db.session import Base


class Category(Base, table=True):
    """单级标签，无父子层级；停用/逻辑删除保留历史（4.16）。"""

    __tablename__ = cast(Any, "categories")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    name: str = Field(sa_column=Column(String(64), index=True, nullable=False))  # 主名称
    status: str = Field(default='active', sa_column=Column(String(16), default="active", nullable=False))  # active / disabled
    deleted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    created_by_id: int = Field(sa_column=Column(ForeignKey("users.id"), nullable=False))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    updated_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False))


class CategoryAlias(Base, table=True):
    """同义别名：主名/别名指向同一分类，不重复计标签（4.16）。"""

    __tablename__ = cast(Any, "category_aliases")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    category_id: int = Field(sa_column=Column(ForeignKey("categories.id"), index=True, nullable=False))
    name: str = Field(sa_column=Column(String(64), index=True, nullable=False))
    created_by_id: int = Field(sa_column=Column(ForeignKey("users.id"), nullable=False))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    removed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))


Index(
    "uq_category_active_name",
    col(Category.name),
    unique=True,
    sqlite_where=col(Category.deleted_at).is_(None),
    postgresql_where=col(Category.deleted_at).is_(None),
)
Index(
    "uq_category_alias_name",
    col(CategoryAlias.name),
    unique=True,
    sqlite_where=col(CategoryAlias.removed_at).is_(None),
    postgresql_where=col(CategoryAlias.removed_at).is_(None),
)
