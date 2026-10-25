"""C-03 商品分类（单级多标签）与别名。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Category(Base):
    """单级标签，无父子层级；停用/逻辑删除保留历史（4.16）。"""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), index=True)  # 主名称
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / disabled
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CategoryAlias(Base):
    """同义别名：主名/别名指向同一分类，不重复计标签（4.16）。"""

    __tablename__ = "category_aliases"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("uq_category_active_name", Category.name, unique=True, sqlite_where=Category.deleted_at.is_(None))
Index("uq_category_alias_name", CategoryAlias.name, unique=True, sqlite_where=CategoryAlias.removed_at.is_(None))
