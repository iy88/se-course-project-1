"""Product-domain services: snapshots, visibility, edit history, change notifications, and search conditions."""
from typing import cast

from sqlalchemy.orm import QueryableAttribute, selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    Category,
    CategoryAlias,
    Product,
    ProductEditHistory,
    ProductImage,
    ProductTag,
    Trade,
    User,
)
from app.models.enums import LOCKING_TRADE_STATUSES, ProductStatus, TradeStatus
from app.services.notifications import notify

EDITABLE_STATUSES = (ProductStatus.LISTED, ProductStatus.DELISTED, ProductStatus.PENDING_REVIEW)


def product_content_dict(product: Product, image_keys: list[str], tag_names: list[str]) -> dict:
    return {
        "title": product.title,
        "description": product.description,
        "price_cents": product.price_cents,
        "images": image_keys,
        "tags": tag_names,
    }


async def load_product_images(db: AsyncSession, product_id: int) -> list[ProductImage]:
    result = await db.exec(
        select(ProductImage).where(col(ProductImage.product_id) == product_id).order_by(col(ProductImage.sort))
    )
    return list(result)


async def snapshot_content(db: AsyncSession, product: Product) -> dict:
    """Build a review snapshot from current persisted content (refreshed to the latest content when an administrator submits a conclusion, D-46)."""
    images = await load_product_images(db, product.id)
    tags = await load_product_tags(db, product.id)
    return product_content_dict(product, [i.file_key for i in images], [t.name for t in tags])


async def load_product_tags(db: AsyncSession, product_id: int) -> list[Category]:
    result = await db.exec(
        select(Category)
        .join(ProductTag, col(ProductTag.category_id) == col(Category.id))
        .where(col(ProductTag.product_id) == product_id)
        .order_by(col(Category.id))
    )
    return list(result)


def is_detail_visible(user: User, product: Product) -> bool:
    """Public detail eligibility (BR-14/15, 4.10): a display revocation for a violation takes precedence; a delisted product is not exposed to ordinary third parties."""
    if user.id == product.seller_id:
        return True
    if product.display_restricted:
        return False
    return product.status in (ProductStatus.LISTED.value, ProductStatus.IN_TRANSACTION.value)


def is_favorite_valid(product: Product) -> bool:
    """Favorite eligibility (BR-16/D-44): publicly tradable or in a transaction, with display not revoked; does not reuse historical detail eligibility."""
    return (not product.display_restricted) and product.status in (
        ProductStatus.LISTED.value,
        ProductStatus.IN_TRANSACTION.value,
    )


async def has_product_request_history(db: AsyncSession, user_id: int, product_id: int) -> bool:
    """Whether the user ever created a request/trade for this product (D-43: current details and later changes remain visible after it ends)."""
    return (
        (await db.exec(
            select(col(Trade.id))
            .where(col(Trade.product_id) == product_id, col(Trade.buyer_id) == user_id)
            .limit(1)
        )).first()
    ) is not None


async def record_edit_history(
    db: AsyncSession,
    product: Product,
    editor_id: int,
    before: dict,
    after: dict,
    edit_type: str = "edit",
    reason: str | None = None,
) -> ProductEditHistory:
    history = ProductEditHistory(
        product_id=product.id,
        editor_id=editor_id,
        edit_type=edit_type,
        before_json=before,
        after_json=after,
        reason=reason,
    )
    db.add(history)
    await db.flush()
    return history


async def notify_open_request_buyers(db: AsyncSession, product: Product, title: str, content: str) -> None:
    """Notify relevant buyers of unfinished requests/trades when a product is edited (BR-11, 4.17/4.18)."""
    result = await db.exec(
        select(col(Trade.buyer_id))
        .where(
            col(Trade.product_id) == product.id,
            col(Trade.status).in_(
                [TradeStatus.PENDING_ACCEPTANCE.value, *[s.value for s in LOCKING_TRADE_STATUSES]]
            ),
        )
        .distinct()
    )
    buyer_ids = list(result.all())
    if buyer_ids:
        await notify(
            db,
            buyer_ids,
            "product_edited",
            title,
            content,
            link_type="product",
            link_id=product.id,
            payload={"product_id": product.id},
        )


async def resolve_category_names(db: AsyncSession, names: list[str]) -> list[int] | None:
    """D-45: strictly resolve category names against current primary names/active aliases.

    Return None when any name is unknown, empty, or points to a removed alias (the caller
    should return no matches); never ignore unknown entries and loosen the filter. Primary
    names take precedence over historical aliases with the same name.
    """
    resolved: list[int] = []
    for raw in names:
        name = (raw or "").strip()
        if not name:
            return None
        category = (await db.exec(
            select(Category).where(col(Category.name) == name, col(Category.deleted_at).is_(None))
        )).first()
        if category is None:
            alias = (await db.exec(
                select(CategoryAlias).where(
                    col(CategoryAlias.name) == name, col(CategoryAlias.removed_at).is_(None)
                )
            )).first()
            if alias is None:
                return None
            category = await db.get(Category, alias.category_id)
            if category is None or category.deleted_at is not None:
                return None
        if category.id not in resolved:
            resolved.append(category.id)
    return resolved


async def search_products(
    db: AsyncSession,
    *,
    keyword: str | None,
    category_ids: list[int] | None,
    price_min_cents: int | None,
    price_max_cents: int | None,
    page: int,
    page_size: int,
    seller_id: int | None = None,
):
    """Listed-product search (BR-15): only publicly tradable products whose display is not revoked; multiple tags must all match."""
    from sqlmodel import and_, func

    conditions = [col(Product.status) == ProductStatus.LISTED.value, col(Product.display_restricted).is_(False)]
    if seller_id is not None:
        conditions.append(col(Product.seller_id) == seller_id)
    if keyword:
        like = f"%{keyword}%"
        # Free-text keywords match product text and the current primary names/active aliases of linked categories.
        # Use IN subqueries instead of joins so multiple tag/alias hits do not duplicate products or totals.
        keyword_tag_ids = (
            select(col(ProductTag.product_id))
            .join(Category, col(Category.id) == col(ProductTag.category_id))
            .outerjoin(
                CategoryAlias,
                and_(col(CategoryAlias.category_id) == col(Category.id), col(CategoryAlias.removed_at).is_(None)),
            )
            .where((col(Category.name).like(like)) | (col(CategoryAlias.name).like(like)))
        )
        conditions.append(
            (col(Product.title).like(like))
            | (col(Product.description).like(like))
            | (col(Product.id).in_(keyword_tag_ids))
        )
    if price_min_cents is not None:
        conditions.append(col(Product.price_cents) >= price_min_cents)
    if price_max_cents is not None:
        conditions.append(col(Product.price_cents) <= price_max_cents)
    if category_ids:
        # All tags must match: the product's linked tag count is >= the selected count
        sub = (
            select(col(ProductTag.product_id), func.count().label("match_count"))
            .where(col(ProductTag.category_id).in_(category_ids))
            .group_by(col(ProductTag.product_id))
            .having(func.count() >= len(category_ids))
            .subquery()
        )
        conditions.append(col(Product.id).in_(select(sub.c.product_id)))

    total = (await db.exec(select(func.count()).select_from(Product).where(and_(*conditions)))).first()
    result = await db.exec(
        select(Product)
        .options(selectinload(cast(QueryableAttribute[list[ProductImage]], Product.images)))
        .where(and_(*conditions))
        .order_by(col(Product.created_at).desc(), col(Product.id).desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result), int(total or 0)
