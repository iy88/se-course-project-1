"""商品域服务：快照、可见性、编辑历史、变更通知、搜索条件。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Category, Product, ProductEditHistory, ProductImage, ProductTag, Trade, User
from app.models.enums import LOCKING_TRADE_STATUSES, ProductStatus, TradeStatus
from app.services.notifications import notify

EDITABLE_STATUSES = (ProductStatus.LISTED, ProductStatus.DELISTED)


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


async def load_product_tags(db: AsyncSession, product_id: int) -> list[Category]:
    result = await db.execute(
        select(Category)
        .join(ProductTag, ProductTag.category_id == Category.id)
        .where(ProductTag.product_id == product_id)
        .order_by(Category.id)
    )
    return list(result.scalars())


def is_detail_visible(user: User, product: Product) -> bool:
    """详情可见性（BR-14/15、4.10）：违规撤销公开优先；已下架仅本人历史访问。"""
    if user.id == product.seller_id:
        return True
    if product.display_restricted:
        return False
    if product.status in (ProductStatus.LISTED.value, ProductStatus.IN_TRANSACTION.value):
        return True
    return False


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
        conditions.append((Product.title.like(like)) | (Product.description.like(like)))
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
