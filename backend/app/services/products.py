"""商品域服务：快照、可见性、编辑历史、变更通知、搜索条件。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Category, CategoryAlias, Product, ProductEditHistory, ProductImage, ProductTag, Trade, User
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
    result = await db.execute(
        select(ProductImage).where(ProductImage.product_id == product_id).order_by(ProductImage.sort)
    )
    return list(result.scalars())


async def snapshot_content(db: AsyncSession, product: Product) -> dict:
    """按当前持久内容生成审核快照（管理员提交结论时刷新为最新内容，D-46）。"""
    images = await load_product_images(db, product.id)
    tags = await load_product_tags(db, product.id)
    return product_content_dict(product, [i.file_key for i in images], [t.name for t in tags])


async def load_product_tags(db: AsyncSession, product_id: int) -> list[Category]:
    result = await db.execute(
        select(Category)
        .join(ProductTag, ProductTag.category_id == Category.id)
        .where(ProductTag.product_id == product_id)
        .order_by(Category.id)
    )
    return list(result.scalars())


def is_detail_visible(user: User, product: Product) -> bool:
    """公开详情资格（BR-14/15、4.10）：违规撤销公开优先；已下架不向普通第三方开放。"""
    if user.id == product.seller_id:
        return True
    if product.display_restricted:
        return False
    if product.status in (ProductStatus.LISTED.value, ProductStatus.IN_TRANSACTION.value):
        return True
    return False


def is_favorite_valid(product: Product) -> bool:
    """收藏有效资格（BR-16/D-44）：公开可交易或交易中且未撤销公开；不复用历史详情资格。"""
    return (not product.display_restricted) and product.status in (
        ProductStatus.LISTED.value,
        ProductStatus.IN_TRANSACTION.value,
    )


async def has_product_request_history(db: AsyncSession, user_id: int, product_id: int) -> bool:
    """是否曾对该商品发起请求／交易（D-43：结束后仍可看当前详情及之后变更）。"""
    return (
        await db.scalar(
            select(Trade.id)
            .where(Trade.product_id == product_id, Trade.buyer_id == user_id)
            .limit(1)
        )
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
    """商品编辑时通知未结束请求/交易的相关买方（BR-11、4.17/4.18）。"""
    result = await db.execute(
        select(Trade.buyer_id)
        .where(
            Trade.product_id == product.id,
            Trade.status.in_(
                [TradeStatus.PENDING_ACCEPTANCE.value, *[s.value for s in LOCKING_TRADE_STATUSES]]
            ),
        )
        .distinct()
    )
    buyer_ids = [row[0] for row in result.all()]
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
    """D-45：按当前主名/活跃别名严格解析分类名称。

    任一名称未知、为空或指向已移除别名时返回 None（调用方应返回无匹配），
    不得忽略未知项后放宽过滤。主名优先于同名历史别名。
    """
    resolved: list[int] = []
    for raw in names:
        name = (raw or "").strip()
        if not name:
            return None
        category = await db.scalar(
            select(Category).where(Category.name == name, Category.deleted_at.is_(None))
        )
        if category is None:
            alias = await db.scalar(
                select(CategoryAlias).where(
                    CategoryAlias.name == name, CategoryAlias.removed_at.is_(None)
                )
            )
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
    """在售搜索（BR-15）：仅公开可交易且未被撤销公开的商品；多标签须全部匹配。"""
    from sqlalchemy import and_, func

    conditions = [Product.status == ProductStatus.LISTED.value, Product.display_restricted.is_(False)]
    if seller_id is not None:
        conditions.append(Product.seller_id == seller_id)
    if keyword:
        like = f"%{keyword}%"
        # 自由关键词同时匹配商品文本、所关联分类的当前主名及活跃别名。
        # 用 IN 子查询而非联表，避免多标签/多别名命中导致商品与总数重复。
        keyword_tag_ids = (
            select(ProductTag.product_id)
            .join(Category, Category.id == ProductTag.category_id)
            .outerjoin(
                CategoryAlias,
                and_(CategoryAlias.category_id == Category.id, CategoryAlias.removed_at.is_(None)),
            )
            .where((Category.name.like(like)) | (CategoryAlias.name.like(like)))
        )
        conditions.append(
            (Product.title.like(like))
            | (Product.description.like(like))
            | (Product.id.in_(keyword_tag_ids))
        )
    if price_min_cents is not None:
        conditions.append(Product.price_cents >= price_min_cents)
    if price_max_cents is not None:
        conditions.append(Product.price_cents <= price_max_cents)
    if category_ids:
        # 多标签全部匹配：商品关联标签数 ≥ 所选数量
        sub = (
            select(ProductTag.product_id, func.count().label("match_count"))
            .where(ProductTag.category_id.in_(category_ids))
            .group_by(ProductTag.product_id)
            .having(func.count() >= len(category_ids))
            .subquery()
        )
        conditions.append(Product.id.in_(select(sub.c.product_id)))

    total = await db.scalar(select(func.count()).select_from(Product).where(and_(*conditions)))
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.images))
        .where(and_(*conditions))
        .order_by(Product.created_at.desc(), Product.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars()), int(total or 0)
