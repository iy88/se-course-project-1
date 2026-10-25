"""分类标签：登录用户可选标签/查看；管理员维护（4.16）。"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentAdmin, CurrentUser, DbSession, ensure_can_write
from app.db.session import get_db
from app.models import Category, CategoryAlias
from app.schemas.category import CategoryAliasIn, CategoryCreateIn, CategoryOut, CategoryUpdateIn

router = APIRouter(prefix="/categories", tags=["categories"])


async def get_active_category_or_404(db: AsyncSession, category_id: int) -> Category:
    category = await db.get(Category, category_id)
    if not category or category.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分类不存在")
    return category


@router.get("", response_model=list[CategoryOut])
async def list_categories(db: DbSession, user: CurrentUser) -> list[CategoryOut]:
    """登录用户可查看可选标签（含别名），供筛选与发布使用。"""
    result = await db.execute(
        select(Category)
        .where(Category.deleted_at.is_(None))
        .order_by(Category.id)
    )
    categories = list(result.scalars())
    aliases_result = await db.execute(select(CategoryAlias).where(CategoryAlias.removed_at.is_(None)))
    aliases = list(aliases_result.scalars())
    alias_map: dict[int, list[str]] = {}
    for alias in aliases:
        alias_map.setdefault(alias.category_id, []).append(alias.name)
    return [
        CategoryOut(
            id=c.id,
            name=c.name,
            status=c.status,
            aliases=alias_map.get(c.id, []),
        )
        for c in categories
    ]


@router.post("", response_model=CategoryOut)
async def create_category(body: CategoryCreateIn, admin: CurrentAdmin, db: DbSession) -> CategoryOut:
    """管理员主动创建公共标签（4.16）。"""
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "标签名称不能为空")
    exists = await db.scalar(
        select(Category).where(Category.name == name, Category.deleted_at.is_(None))
    )
    if exists or await db.scalar(select(CategoryAlias).where(CategoryAlias.name == name, CategoryAlias.removed_at.is_(None))):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "同名标签或别名已存在")
    category = Category(name=name, created_by_id=admin.id)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return CategoryOut(id=category.id, name=category.name, status=category.status, aliases=[])


@router.patch("/{category_id}", response_model=CategoryOut)
async def update_category(category_id: int, body: CategoryUpdateIn, admin: CurrentAdmin, db: DbSession) -> CategoryOut:
    """改主名：旧名保留为别名，当前展示新名（4.16）；可停用/启用。"""
    category = await get_active_category_or_404(db, category_id)
    if body.name is not None and body.name.strip() and body.name.strip() != category.name:
        new_name = body.name.strip()
        conflict = await db.scalar(
            select(Category).where(Category.name == new_name, Category.deleted_at.is_(None), Category.id != category.id)
        )
        alias_conflict = await db.scalar(
            select(CategoryAlias).where(CategoryAlias.name == new_name, CategoryAlias.removed_at.is_(None))
        )
        if conflict or alias_conflict:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "目标名称已被使用")
        # 旧主名转为别名
        old_alias = CategoryAlias(
            category_id=category.id, name=category.name, created_by_id=admin.id
        )
        db.add(old_alias)
        category.name = new_name
    if body.status is not None:
        if body.status not in {"active", "disabled"}:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "非法状态")
        category.status = body.status
    await db.commit()
    await db.refresh(category)
    aliases = (
        await db.execute(
            select(CategoryAlias).where(CategoryAlias.category_id == category.id, CategoryAlias.removed_at.is_(None))
        )
    ).scalars().all()
    return CategoryOut(id=category.id, name=category.name, status=category.status, aliases=[a.name for a in aliases])


@router.post("/{category_id}/aliases", response_model=CategoryOut)
async def add_alias(category_id: int, body: CategoryAliasIn, admin: CurrentAdmin, db: DbSession) -> CategoryOut:
    category = await get_active_category_or_404(db, category_id)
    name = body.name.strip()
    if not name or name == category.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "别名不能为空且不能与主名相同")
    exists = await db.scalar(select(CategoryAlias).where(CategoryAlias.name == name, CategoryAlias.removed_at.is_(None)))
    if exists:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "别名已存在")
    db.add(CategoryAlias(category_id=category.id, name=name, created_by_id=admin.id))
    await db.commit()
    aliases = (
        await db.execute(
            select(CategoryAlias).where(CategoryAlias.category_id == category.id, CategoryAlias.removed_at.is_(None))
        )
    ).scalars().all()
    return CategoryOut(id=category.id, name=category.name, status=category.status, aliases=[a.name for a in aliases])


@router.delete("/{category_id}/aliases/{alias_id}", response_model=CategoryOut)
async def remove_alias(category_id: int, alias_id: int, admin: CurrentAdmin, db: DbSession) -> CategoryOut:
    """移除别名不改变归属及历史（4.16）。"""
    await get_active_category_or_404(db, category_id)
    alias = await db.get(CategoryAlias, alias_id)
    if not alias or alias.category_id != category_id or alias.removed_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "别名不存在")
    alias.removed_at = datetime.now(UTC)
    await db.commit()
    category = await db.get(Category, category_id)
    aliases = (
        await db.execute(
            select(CategoryAlias).where(CategoryAlias.category_id == category_id, CategoryAlias.removed_at.is_(None))
        )
    ).scalars().all()
    return CategoryOut(id=category.id, name=category.name, status=category.status, aliases=[a.name for a in aliases])


@router.delete("/{category_id}")
async def delete_category(category_id: int, admin: CurrentAdmin, db: DbSession) -> dict:
    """逻辑删除：仅从未关联商品的标签可删（4.16），关联检查在服务层执行。"""
    from sqlalchemy import func

    from app.models import ProductTag

    category = await get_active_category_or_404(db, category_id)
    used = await db.scalar(select(func.count()).select_from(ProductTag).where(ProductTag.category_id == category_id))
    if used:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该标签已关联商品，仅可停用")
    category.deleted_at = datetime.now(UTC)
    await db.commit()
    return {"detail": "已删除"}
