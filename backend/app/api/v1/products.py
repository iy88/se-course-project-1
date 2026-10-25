"""商品：发布、重提、编辑、上下架、搜索、详情、编辑历史（FR-02/03/09）。"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, ensure_can_write
from app.models import (
    Category,
    CategoryAlias,
    Product,
    ProductImage,
    ProductTag,
    ProductTagApplication,
    ReviewRecord,
    Trade,
    User,
)
from app.models.enums import CaseType, ProductStatus, ReviewResult, TradeStatus
from app.schemas.product import (
    ProductCardOut,
    ProductCreateIn,
    ProductEditHistoryOut,
    ProductOut,
    ProductSearchOut,
    ProductUpdateIn,
    ReviewRecordOut,
)
from app.services import cases as case_service
from app.services import products as product_service
from app.services import trades as trade_service
from app.services.notifications import notify
from app.storage.base import get_storage

router = APIRouter(prefix="/products", tags=["products"])


def _tag_names(tags: list[Category]) -> list[str]:
    return [t.name for t in tags]


async def _snapshot_content(db: AsyncSession, product: Product) -> dict:
    images = await product_service.load_product_images(db, product.id)
    tags = await product_service.load_product_tags(db, product.id)
    return product_service.product_content_dict(product, [i.file_key for i in images], _tag_names(tags))


async def _out(db: AsyncSession, product: Product, user: User, include_pending_count: bool = False) -> ProductOut:
    storage = get_storage()
    images = await product_service.load_product_images(db, product.id)
    tags = await product_service.load_product_tags(db, product.id)
    pending = 0
    if include_pending_count and user.id == product.seller_id:
        pending = await db.scalar(
            select(func.count())
            .select_from(Trade)
            .where(Trade.product_id == product.id, Trade.status == TradeStatus.PENDING_ACCEPTANCE.value)
        ) or 0
    return ProductOut(
        id=product.id,
        seller_id=product.seller_id,
        title=product.title,
        description=product.description,
        price_cents=product.price_cents,
        status=ProductStatus(product.status),
        display_restricted=product.display_restricted,
        display_restricted_reason=product.display_restricted_reason,
        reject_reason=product.reject_reason if user.id == product.seller_id else None,
        image_keys=[i.file_key for i in images],
        image_urls=[storage.public_url(i.file_key) for i in images],
        tag_ids=[t.id for t in tags],
        tag_names=[t.name for t in tags],
        created_at=product.created_at,
        updated_at=product.updated_at,
        pending_request_count=int(pending),
    )


def _card(product: Product, seller_name: str, image_key: str | None) -> ProductCardOut:
    storage = get_storage()
    return ProductCardOut(
        id=product.id,
        title=product.title,
        price_cents=product.price_cents,
        image_url=storage.public_url(image_key) if image_key else None,
        tag_ids=[t.id for t in product.tags],
        tag_names=[t.name for t in product.tags],
        status=ProductStatus(product.status),
        seller_id=product.seller_id,
        seller_name=seller_name,
        created_at=product.created_at,
    )


async def _validate_image_keys(db: AsyncSession, image_keys: list[str]) -> None:
    storage = get_storage()
    for key in image_keys:
        if not storage.exists(key):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"图片不存在或已失效：{key}")


async def _resolve_tags_for_submit(
    db: AsyncSession, product: Product, tags_in: list
) -> tuple[list[int], list[ProductTagApplication]]:
    """返回(关联已有标签ID列表, 新标签申请列表)。至少一个已有标签或一个新申请（BR-12）。"""
    category_ids: list[int] = []
    applications: list[ProductTagApplication] = []
    for tag_in in tags_in:
        if tag_in.category_id is not None:
            category = await db.get(Category, tag_in.category_id)
            if not category or category.deleted_at is not None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "所选标签不存在")
            if category.id not in category_ids:
                category_ids.append(category.id)
        elif tag_in.new_name:
            name = tag_in.new_name.strip()
            if not name:
                continue
            exists = await db.scalar(select(Category).where(Category.name == name, Category.deleted_at.is_(None)))
            alias = await db.scalar(
                select(CategoryAlias).where(CategoryAlias.name == name, CategoryAlias.removed_at.is_(None))
            )
            if exists:
                if exists.id not in category_ids:
                    category_ids.append(exists.id)
            elif alias:
                if alias.category_id not in category_ids:
                    category_ids.append(alias.category_id)
            else:
                applications.append(ProductTagApplication(product_id=product.id, requested_name=name))
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "标签信息不完整")
    if not category_ids and not applications:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "须至少选择一个已有标签或申请一个新标签")
    return category_ids, applications


@router.post("", response_model=ProductOut)
async def publish_product(body: ProductCreateIn, user: CurrentUser, db: DbSession) -> ProductOut:
    """发布：进入待审核并进入共享待处理池（BR-10、BR-34）。"""
    ensure_can_write(user)
    await _validate_image_keys(db, body.image_keys)
    product = Product(
        seller_id=user.id,
        title=body.title.strip(),
        description=body.description.strip(),
        price_cents=body.price_cents,
        status=ProductStatus.PENDING_REVIEW.value,
    )
    db.add(product)
    await db.flush()
    category_ids, applications = await _resolve_tags_for_submit(db, product, body.tags)
    for cid in category_ids:
        db.add(ProductTag(product_id=product.id, category_id=cid))
    db.add_all(applications)
    for sort, key in enumerate(body.image_keys):
        db.add(ProductImage(product_id=product.id, file_key=key, sort=sort))
    # 当次审核内容快照 + 审核事项进入共享池
    content = await _snapshot_content(db, product)
    case = await case_service.create_case(
        db,
        case_type=CaseType.PRODUCT_REVIEW,
        title=f"商品审核：{product.title}",
        subject_user_id=user.id,
        product_id=product.id,
    )
    db.add(ReviewRecord(product_id=product.id, content_json=content, case_id=case.id))
    await db.commit()
    await db.refresh(product)
    return await _out(db, product, user, include_pending_count=True)


@router.get("/search", response_model=ProductSearchOut)
async def search(
    db: DbSession,
    user: CurrentUser,
    keyword: str | None = Query(default=None, max_length=100),
    category_ids: list[int] | None = Query(default=None),
    price_min_cents: int | None = Query(default=None, ge=0),
    price_max_cents: int | None = Query(default=None, ge=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
) -> ProductSearchOut:
    """在售搜索：关键词/多标签（全部匹配）/价格区间组合（BR-15）。"""
    items, total = await product_service.search_products(
        db,
        keyword=keyword,
        category_ids=category_ids,
        price_min_cents=price_min_cents,
        price_max_cents=price_max_cents,
        page=page,
        page_size=page_size,
    )
    seller_ids = {p.seller_id for p in items}
    names: dict[int, str] = {}
    if seller_ids:
        rows = await db.execute(select(User.id, User.display_name).where(User.id.in_(seller_ids)))
        names = {uid: name for uid, name in rows.all()}
    cards = [_card(p, names.get(p.seller_id, ""), p.images[0].file_key if p.images else None) for p in items]
    return ProductSearchOut(
        items=cards,
        total=total,
        message=None if total else ("无匹配商品" if any([keyword, category_ids, price_min_cents, price_max_cents]) else "暂无在售商品"),
    )


@router.get("/mine", response_model=list[ProductOut])
async def my_products(user: CurrentUser, db: DbSession) -> list[ProductOut]:
    """我的商品：覆盖全部状态及审核原因、待接受请求数（FR-12、4.18）。"""
    result = await db.execute(
        select(Product).where(Product.seller_id == user.id).order_by(Product.created_at.desc())
    )
    products = list(result.scalars())
    return [await _out(db, p, user, include_pending_count=True) for p in products]


@router.get("/{product_id}", response_model=ProductOut)
async def detail(product_id: int, user: CurrentUser, db: DbSession) -> ProductOut:
    product = await db.get(Product, product_id)
    if not product or not product_service.is_detail_visible(user, product):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在或不可见")
    return await _out(db, product, user, include_pending_count=True)


@router.get("/{product_id}/edit-history", response_model=list[ProductEditHistoryOut])
async def edit_history(product_id: int, user: CurrentUser, db: DbSession) -> list[ProductEditHistoryOut]:
    """卖方看本人商品完整历史（4.18）；其他用户无完整历史访问权。"""
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    if product.seller_id != user.id and user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅发布者可查看完整编辑历史")
    from app.models import ProductEditHistory

    result = await db.execute(
        select(ProductEditHistory).where(ProductEditHistory.product_id == product_id).order_by(ProductEditHistory.id)
    )
    return [ProductEditHistoryOut.model_validate(h) for h in result.scalars()]


@router.get("/{product_id}/review-records", response_model=list[ReviewRecordOut])
async def review_records(product_id: int, user: CurrentUser, db: DbSession) -> list[ReviewRecordOut]:
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    if product.seller_id != user.id and user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅发布者可查看审核记录")
    result = await db.execute(
        select(ReviewRecord).where(ReviewRecord.product_id == product_id).order_by(ReviewRecord.id)
    )
    return [ReviewRecordOut.model_validate(r) for r in result.scalars()]


@router.post("/{product_id}/resubmit", response_model=ProductOut)
async def resubmit(
    product_id: int, body: ProductUpdateIn, user: CurrentUser, db: DbSession
) -> ProductOut:
    """TR-03：审核未通过 → 修改后重新提交，形成新的独立审核记录（BR-10）。"""
    ensure_can_write(user)
    product = await db.get(Product, product_id)
    if not product or product.seller_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    if product.status != ProductStatus.REJECTED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅审核未通过的商品可修改重提")
    if body.title is not None:
        product.title = body.title.strip()
    if body.description is not None:
        product.description = body.description.strip()
    if body.price_cents is not None:
        product.price_cents = body.price_cents
    if body.image_keys is not None:
        await _validate_image_keys(db, body.image_keys)
        await db.execute(ProductImage.__table__.delete().where(ProductImage.product_id == product.id))
        for sort, key in enumerate(body.image_keys):
            db.add(ProductImage(product_id=product.id, file_key=key, sort=sort))
    if body.category_ids is not None:
        await db.execute(ProductTag.__table__.delete().where(ProductTag.product_id == product.id))
        for cid in body.category_ids:
            category = await db.get(Category, cid)
            if not category or category.deleted_at is not None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "所选标签不存在")
            db.add(ProductTag(product_id=product.id, category_id=cid))
    tags = await product_service.load_product_tags(db, product.id)
    if not tags:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "重提商品须至少关联一个标签")
    product.status = ProductStatus.PENDING_REVIEW.value
    product.reject_reason = None
    content = await _snapshot_content(db, product)
    case = await case_service.create_case(
        db,
        case_type=CaseType.PRODUCT_REVIEW,
        title=f"商品重提审核：{product.title}",
        subject_user_id=user.id,
        product_id=product.id,
    )
    db.add(ReviewRecord(product_id=product.id, content_json=content, case_id=case.id))
    await db.commit()
    await db.refresh(product)
    return await _out(db, product, user, include_pending_count=True)


@router.patch("/{product_id}", response_model=ProductOut)
async def edit_product(product_id: int, body: ProductUpdateIn, user: CurrentUser, db: DbSession) -> ProductOut:
    """信息微调（BR-11/TR-04）：不二审、不暂停展示、不关闭请求；交易中禁改关键内容。"""
    ensure_can_write(user)
    product = await db.get(Product, product_id)
    if not product or product.seller_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    if product.display_restricted:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "商品因处置停止公开访问，暂不可编辑")
    if product.status == ProductStatus.IN_TRANSACTION.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "商品交易中，禁止修改关键内容")
    if product.status not in (ProductStatus.LISTED.value, ProductStatus.DELISTED.value):
        raise HTTPException(status.HTTP_409_CONFLICT, "当前状态不可编辑；审核未通过请使用修改重提")
    before = await _snapshot_content(db, product)
    changed = False
    if body.title is not None and body.title.strip() != product.title:
        product.title = body.title.strip()
        changed = True
    if body.description is not None and body.description.strip() != product.description:
        product.description = body.description.strip()
        changed = True
    if body.price_cents is not None and body.price_cents != product.price_cents:
        product.price_cents = body.price_cents
        changed = True
    if body.image_keys is not None and body.image_keys != [i.file_key for i in await product_service.load_product_images(db, product.id)]:
        await _validate_image_keys(db, body.image_keys)
        await db.execute(ProductImage.__table__.delete().where(ProductImage.product_id == product.id))
        for sort, key in enumerate(body.image_keys):
            db.add(ProductImage(product_id=product.id, file_key=key, sort=sort))
        changed = True
    if body.category_ids is not None:
        current_ids = {t.id for t in await product_service.load_product_tags(db, product.id)}
        if set(body.category_ids) != current_ids:
            await db.execute(ProductTag.__table__.delete().where(ProductTag.product_id == product.id))
            for cid in set(body.category_ids):
                category = await db.get(Category, cid)
                if not category or category.deleted_at is not None:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "所选标签不存在")
                db.add(ProductTag(product_id=product.id, category_id=cid))
            changed = True
    if not changed:
        return await _out(db, product, user, include_pending_count=True)
    after = await _snapshot_content(db, product)
    await product_service.record_edit_history(db, product, user.id, before, after)
    await product_service.notify_open_request_buyers(
        db,
        product,
        "关注的商品信息已更新",
        f"您关注的商品「{product.title}」信息已被卖方更新，可查看最新内容。",
    )
    await db.commit()
    await db.refresh(product)
    return await _out(db, product, user, include_pending_count=True)


@router.post("/{product_id}/delist", response_model=ProductOut)
async def delist(product_id: int, user: CurrentUser, db: DbSession) -> ProductOut:
    """主动下架（BR-09/14）：无未结束锁单交易；关闭待接受请求并注明原因。"""
    ensure_can_write(user)
    product = await db.get(Product, product_id)
    if not product or product.seller_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    if product.status != ProductStatus.LISTED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅公开可交易的商品可下架")
    locking = await trade_service.get_locking_trade(db, product.id)
    if locking:
        raise HTTPException(status.HTTP_409_CONFLICT, "存在未结束的锁单交易，须先按交易规则结束交易")
    product.status = ProductStatus.DELISTED.value
    product.delisted_at = datetime.now(UTC)
    closed = await trade_service.close_pending_requests_for_product(db, product.id, "商品已下架")
    for trade in closed:
        await notify(
            db,
            [trade.buyer_id],
            "request_closed",
            f"您的购买请求已关闭",
            f"商品「{product.title}」已下架，对应请求已关闭。",
            link_type="trade",
            link_id=trade.id,
        )
    await db.commit()
    await db.refresh(product)
    return await _out(db, product, user, include_pending_count=True)


@router.post("/{product_id}/relist", response_model=ProductOut)
async def relist(product_id: int, user: CurrentUser, db: DbSession) -> ProductOut:
    """重新上架/继续上架（TR-08）：已下架、审核有效且当前账户及商品限制允许。"""
    ensure_can_write(user)
    product = await db.get(Product, product_id)
    if not product or product.seller_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    if product.status != ProductStatus.DELISTED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅已下架商品可重新上架")
    if product.display_restricted:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "商品因处置停止公开访问，暂不可上架")
    latest = await db.scalar(
        select(ReviewRecord).where(ReviewRecord.product_id == product.id).order_by(ReviewRecord.id.desc()).limit(1)
    )
    if not latest or latest.result != ReviewResult.APPROVED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "商品审核无效，须重新提交审核")
    product.status = ProductStatus.LISTED.value
    product.listed_at = datetime.now(UTC)
    product.delisted_at = None
    await db.commit()
    await db.refresh(product)
    return await _out(db, product, user, include_pending_count=True)
