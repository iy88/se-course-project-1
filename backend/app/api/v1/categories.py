"""Category tags: signed-in users view/select tags; administrators maintain them (4.16)."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import CurrentAdmin, CurrentUser, DbSession
from app.models import Category, CategoryAlias
from app.schemas.category import (
    CategoryAliasIn,
    CategoryCreateIn,
    CategoryOut,
    CategoryUpdateIn,
)
from app.services import audit as audit_service

router = APIRouter(prefix="/categories", tags=["categories"])


async def get_active_category_or_404(db: AsyncSession, category_id: int) -> Category:
    category = await db.get(Category, category_id)
    if not category or category.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "分类不存在")
    return category


@router.get("", response_model=list[CategoryOut])
async def list_categories(db: DbSession, user: CurrentUser) -> list[CategoryOut]:
    """Signed-in users can view selectable tags (including aliases) for filtering and publishing."""
    result = await db.exec(
        select(Category)
        .where(col(Category.deleted_at).is_(None))
        .order_by(col(Category.id))
    )
    categories = list(result)
    aliases_result = await db.exec(select(CategoryAlias).where(col(CategoryAlias.removed_at).is_(None)))
    aliases = list(aliases_result)
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
    """Administrators create a public tag explicitly (4.16)."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "标签名称不能为空")
    exists = (await db.exec(
        select(Category).where(col(Category.name) == name, col(Category.deleted_at).is_(None))
    )).first()
    if exists or (await db.exec(select(CategoryAlias).where(col(CategoryAlias.name) == name, col(CategoryAlias.removed_at).is_(None)))).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "同名标签或别名已存在")
    category = Category(name=name, created_by_id=admin.id)
    db.add(category)
    await db.flush()
    await audit_service.record_event(
        db,
        "admin.category_create",
        target_type="category",
        target_id=category.id,
        after={"created": True, "status": category.status},
    )
    await db.commit()
    await db.refresh(category)
    return CategoryOut(id=category.id, name=category.name, status=category.status, aliases=[])


@router.patch("/{category_id}", response_model=CategoryOut)
async def update_category(category_id: int, body: CategoryUpdateIn, admin: CurrentAdmin, db: DbSession) -> CategoryOut:
    """Rename: the old name is retained as an alias and the new name is displayed (4.16); the tag can be disabled/enabled."""
    category = await get_active_category_or_404(db, category_id)
    old_status = category.status
    changed_fields: list[str] = []
    if body.name is not None and body.name.strip() and body.name.strip() != category.name:
        new_name = body.name.strip()
        conflict = (await db.exec(
            select(Category).where(col(Category.name) == new_name, col(Category.deleted_at).is_(None), col(Category.id) != category.id)
        )).first()
        alias_conflict = (await db.exec(
            select(CategoryAlias).where(col(CategoryAlias.name) == new_name, col(CategoryAlias.removed_at).is_(None))
        )).first()
        if conflict or alias_conflict:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "目标名称已被使用")
        # Convert the old primary name into an alias
        old_alias = CategoryAlias(
            category_id=category.id, name=category.name, created_by_id=admin.id
        )
        db.add(old_alias)
        category.name = new_name
        changed_fields.append("name")
    if body.status is not None:
        if body.status not in {"active", "disabled"}:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "非法状态")
        if category.status != body.status:
            category.status = body.status
            changed_fields.append("status")
    if changed_fields:
        await audit_service.record_event(
            db,
            "admin.category_update",
            target_type="category",
            target_id=category.id,
            before={"status": old_status},
            after={"status": category.status, "changed_fields": changed_fields},
        )
    await db.commit()
    await db.refresh(category)
    aliases = (
        await db.exec(
            select(CategoryAlias).where(col(CategoryAlias.category_id) == category.id, col(CategoryAlias.removed_at).is_(None))
        )
    ).all()
    return CategoryOut(id=category.id, name=category.name, status=category.status, aliases=[a.name for a in aliases])


@router.post("/{category_id}/aliases", response_model=CategoryOut)
async def add_alias(category_id: int, body: CategoryAliasIn, admin: CurrentAdmin, db: DbSession) -> CategoryOut:
    category = await get_active_category_or_404(db, category_id)
    name = body.name.strip()
    if not name or name == category.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "别名不能为空且不能与主名相同")
    # An alias must not conflict with another category's current primary name (4.16); the same synonymous name may point to only one category.
    principal_conflict = (await db.exec(
        select(Category).where(col(Category.name) == name, col(Category.deleted_at).is_(None))
    )).first()
    if principal_conflict:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "别名与其他分类主名冲突")
    exists = (await db.exec(select(CategoryAlias).where(col(CategoryAlias.name) == name, col(CategoryAlias.removed_at).is_(None)))).first()
    if exists:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "别名已存在")
    alias = CategoryAlias(category_id=category.id, name=name, created_by_id=admin.id)
    db.add(alias)
    await db.flush()
    await audit_service.record_event(
        db,
        "admin.category_alias_add",
        target_type="category_alias",
        target_id=alias.id,
        after={"category_id": category.id},
    )
    await db.commit()
    aliases = (
        await db.exec(
            select(CategoryAlias).where(col(CategoryAlias.category_id) == category.id, col(CategoryAlias.removed_at).is_(None))
        )
    ).all()
    return CategoryOut(id=category.id, name=category.name, status=category.status, aliases=[a.name for a in aliases])


@router.delete("/{category_id}/aliases/by-name")
async def remove_alias_by_name(
    category_id: int, name: str, admin: CurrentAdmin, db: DbSession
) -> dict:
    """Remove an alias by name (the admin list exposes names only)."""
    await get_active_category_or_404(db, category_id)
    alias = (await db.exec(
        select(CategoryAlias).where(
            col(CategoryAlias.category_id) == category_id,
            col(CategoryAlias.name) == name.strip(),
            col(CategoryAlias.removed_at).is_(None),
        )
    )).first()
    if not alias:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "别名不存在")
    alias.removed_at = datetime.now(UTC)
    await audit_service.record_event(
        db,
        "admin.category_alias_remove",
        target_type="category_alias",
        target_id=alias.id,
        after={"category_id": category_id, "removed": True},
    )
    await db.commit()
    return {"detail": "别名已移除"}


@router.delete("/{category_id}/aliases/{alias_id}", response_model=CategoryOut)
async def remove_alias(category_id: int, alias_id: int, admin: CurrentAdmin, db: DbSession) -> CategoryOut:
    """Removing an alias changes neither ownership nor history (4.16)."""
    category = await get_active_category_or_404(db, category_id)
    alias = await db.get(CategoryAlias, alias_id)
    if not alias or alias.category_id != category_id or alias.removed_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "别名不存在")
    alias.removed_at = datetime.now(UTC)
    await audit_service.record_event(
        db,
        "admin.category_alias_remove",
        target_type="category_alias",
        target_id=alias.id,
        after={"category_id": category_id, "removed": True},
    )
    await db.commit()
    aliases = (
        await db.exec(
            select(CategoryAlias).where(col(CategoryAlias.category_id) == category_id, col(CategoryAlias.removed_at).is_(None))
        )
    ).all()
    return CategoryOut(id=category.id, name=category.name, status=category.status, aliases=[a.name for a in aliases])


@router.delete("/{category_id}")
async def delete_category(category_id: int, admin: CurrentAdmin, db: DbSession) -> dict:
    """Soft delete: only a tag never linked to a product may be deleted (4.16); the service layer performs the link check."""
    from sqlmodel import func

    from app.models import ProductTag

    category = await get_active_category_or_404(db, category_id)
    used = (await db.exec(select(func.count()).select_from(ProductTag).where(col(ProductTag.category_id) == category_id))).first()
    if used:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该标签已关联商品，仅可停用")
    old_status = category.status
    category.deleted_at = datetime.now(UTC)
    await audit_service.record_event(
        db,
        "admin.category_delete",
        target_type="category",
        target_id=category.id,
        before={"status": old_status, "deleted": False},
        after={"status": category.status, "deleted": True},
    )
    await db.commit()
    return {"detail": "已删除"}
