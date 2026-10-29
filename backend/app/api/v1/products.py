"""商品：发布、重提、编辑、上下架、搜索、详情、编辑历史（FR-02/03/09）。"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, ensure_can_write
from app.models import (
    Category,
    CategoryAlias,
    DisposalCase,
    Product,
    ProductImage,
    ProductTag,
    ProductTagApplication,
    ReviewRecord,
    Trade,
    User,
)
from app.models.enums import CaseStatus, CaseType, ProductStatus, ReviewResult, TradeStatus
from app.schemas.product import (
    PendingTagApplicationOut,
    ProductCardOut,
    ProductCreateIn,
    ProductEditHistoryOut,
    ProductOut,
    ProductSearchOut,
    ProductUpdateIn,
    ReviewRecordOut,
)
from app.services import cases as case_service
from app.services import permissions
from app.services import products as product_service
from app.services import trades as trade_service
from app.services.notifications import notify
from app.storage.base import get_storage

router = APIRouter(prefix="/products", tags=["products"])


async def _snapshot_content(db: AsyncSession, product: Product) -> dict:
    return await product_service.snapshot_content(db, product)


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
    can_withdraw_review = False
    can_resubmit = False
    pending_tag_applications: list[PendingTagApplicationOut] = []
    if user.id == product.seller_id:
        # 仅本人可见当前仍有效的待审标签申请，供前端枚举撤回 ID（R11）；其他查看者恒为空。
        pending_apps = (
            await db.execute(
                select(ProductTagApplication)
                .where(
                    ProductTagApplication.product_id == product.id,
                    ProductTagApplication.status == "pending",
                )
                .order_by(ProductTagApplication.id)
            )
        ).scalars().all()
        pending_tag_applications = [
            PendingTagApplicationOut(id=a.id, requested_name=a.requested_name) for a in pending_apps
        ]
    if user.id == product.seller_id and not product.display_restricted:
        latest_review = await db.scalar(
            select(ReviewRecord).where(ReviewRecord.product_id == product.id).order_by(ReviewRecord.id.desc()).limit(1)
        )
        if product.status == ProductStatus.PENDING_REVIEW.value:
            # 认领前可撤回；认领后旧审核只能由认领管理员处理
            can_withdraw_review = bool(latest_review and latest_review.result == ReviewResult.PENDING.value)
            if can_withdraw_review and latest_review and latest_review.case_id:
                review_case = await db.get(DisposalCase, latest_review.case_id)
                can_withdraw_review = bool(review_case and review_case.claimed_by_id is None)
        elif product.status == ProductStatus.REJECTED.value:
            can_resubmit = True
        elif (
            product.status == ProductStatus.DELISTED.value
            and latest_review
            and latest_review.result == ReviewResult.WITHDRAWN.value
        ):
            # 仅“认领前撤回审核”形成的已下架可重提，普通已下架已审商品走重新上架
            can_resubmit = True
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
        pending_tag_applications=pending_tag_applications,
        created_at=product.created_at,
        updated_at=product.updated_at,
        pending_request_count=int(pending),
        can_withdraw_review=can_withdraw_review,
        can_resubmit=can_resubmit,
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


def _ensure_selectable_category(category: Category) -> None:
    """停用标签不可被新发布/新关联选择；已关联的历史标签保留（4.16）。"""
    if category.status != "active":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"所选标签已停用：{category.name}")


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
            _ensure_selectable_category(category)
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
                _ensure_selectable_category(exists)
                if exists.id not in category_ids:
                    category_ids.append(exists.id)
            elif alias:
                alias_category = await db.get(Category, alias.category_id)
                if not alias_category or alias_category.deleted_at is not None:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "所选标签不存在")
                _ensure_selectable_category(alias_category)
                if alias_category.id not in category_ids:
                    category_ids.append(alias_category.id)
            else:
                applications.append(ProductTagApplication(product_id=product.id, requested_name=name))
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "标签信息不完整")
    if not category_ids and not applications:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "须至少选择一个已有标签或申请一个新标签")
    return category_ids, applications


@router.post("", response_model=ProductOut)
async def publish_product(body: ProductCreateIn, user: CurrentUser, db: DbSession) -> ProductOut:
    """发布：进入待审核并进入共享待处理池（BR-10、BR-34）；冻结禁发（D-50）。"""
    ensure_can_write(user)
    if await permissions.has_active_frozen_trade(db, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "存在有效交易冻结，暂不能发布商品")
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
    category_names: list[str] | None = Query(default=None),
    price_min_cents: int | None = Query(default=None, ge=0),
    price_max_cents: int | None = Query(default=None, ge=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
) -> ProductSearchOut:
    """在售搜索：关键词/多标签（全部匹配）/价格区间组合（BR-15）。

    D-45：显式 category_names 按当前主名及活跃别名解析；任一未知名称返回无匹配。
    """
    if category_names:
        resolved_names = await product_service.resolve_category_names(db, category_names)
        if resolved_names is None:
            return ProductSearchOut(items=[], total=0, message="无匹配商品")
        merged_ids = list(dict.fromkeys([*(category_ids or []), *resolved_names]))
        category_ids = merged_ids or None
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
        message=None if total else ("无匹配商品" if any([keyword, category_ids, category_names, price_min_cents, price_max_cents]) else "暂无在售商品"),
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
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在或不可见")
    visible = product_service.is_detail_visible(user, product)
    if not visible and not product.display_restricted:
        # D-43：本人曾有请求／交易的买方，结束后仍可看当前详情及之后变更
        visible = await product_service.has_product_request_history(db, user.id, product.id)
    if not visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在或不可见")
    return await _out(db, product, user, include_pending_count=True)


@router.get("/{product_id}/edit-history", response_model=list[ProductEditHistoryOut])
async def edit_history(product_id: int, user: CurrentUser, db: DbSession) -> list[ProductEditHistoryOut]:
    """卖方看完整历史；买方看本人请求对应内容及之后变更；管理员限必要范围（4.18、D-43）。"""
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    from app.models import ProductEditHistory

    result = await db.execute(
        select(ProductEditHistory)
        .where(ProductEditHistory.product_id == product_id)
        .order_by(ProductEditHistory.id)
    )
    histories = list(result.scalars())
    if product.seller_id != user.id and user.role != "admin":
        first_trade = await db.scalar(
            select(Trade)
            .where(Trade.product_id == product_id, Trade.buyer_id == user.id)
            .order_by(Trade.created_at, Trade.id)
            .limit(1)
        )
        if first_trade is None or first_trade.created_at is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "仅本人请求对应内容及之后变更有访问权")
        # 请求结束后仍可查看该商品后续变更，但不开放请求前历史（D-43）
        histories = [
            h for h in histories if h.created_at is not None and h.created_at >= first_trade.created_at
        ]
    return [ProductEditHistoryOut.model_validate(h) for h in histories]


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


async def _dispose_review_case_atomically(db: AsyncSession, case_id: int, *, now: datetime) -> bool:
    """撤回与认领对同一事项的数据库条件竞争：仅 pending 且未认领的事项可被撤回。

    UPDATE 的条件与处置结论在同一条语句中由数据库判定；失败时不产生任何业务写入。
    synchronize_session="evaluate" 同步会话内可能存在的旧事项对象，避免其后续 flush 覆盖。
    """
    result = await db.execute(
        update(DisposalCase)
        .where(
            DisposalCase.id == case_id,
            DisposalCase.status == CaseStatus.PENDING.value,
            DisposalCase.claimed_by_id.is_(None),
        )
        .values(
            status=CaseStatus.DISPOSED.value,
            conclusion="卖方撤回审核",
            conclusion_reason="卖方在审核认领前撤回",
            basis="D-46",
            disposed_at=now,
        )
        .execution_options(synchronize_session="evaluate")
    )
    return result.rowcount == 1


@router.post("/{product_id}/withdraw-review", response_model=ProductOut)
async def withdraw_review(product_id: int, user: CurrentUser, db: DbSession) -> ProductOut:
    """D-46/TR-20：卖方在审核认领前撤回，商品置为已下架，旧审核事项失效但保留历史。"""
    ensure_can_write(user)
    product = await db.get(Product, product_id)
    if not product or product.seller_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    if product.status != ProductStatus.PENDING_REVIEW.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅待审核商品可撤回审核")
    review = await db.scalar(
        select(ReviewRecord)
        .where(ReviewRecord.product_id == product.id, ReviewRecord.result == ReviewResult.PENDING.value)
        .order_by(ReviewRecord.id.desc())
        .limit(1)
    )
    if not review:
        raise HTTPException(status.HTTP_409_CONFLICT, "当前没有可撤回的待审核记录")
    now = datetime.now(UTC)
    # 在修改商品/审核记录/申请/消息之前先与认领原子竞争同一事项；失败即整体回滚。
    if review.case_id and not await _dispose_review_case_atomically(db, review.case_id, now=now):
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "审核事项已被管理员认领或已处置，不能再撤回")
    product.status = ProductStatus.DELISTED.value
    product.delisted_at = now
    product.reject_reason = None
    review.result = ReviewResult.WITHDRAWN.value
    review.reviewed_at = now
    # 旧审核的标签申请一并结束，避免在后续新审核中被误批准
    applications = (
        await db.execute(
            select(ProductTagApplication).where(
                ProductTagApplication.product_id == product.id,
                ProductTagApplication.status == "pending",
            )
        )
    ).scalars().all()
    for application in applications:
        application.status = "withdrawn"
        application.decided_at = now
    if review.case_id:
        # 原子更新后重新读取事项，避免使用更新前的旧 ORM 状态。
        review_case = await db.get(DisposalCase, review.case_id, populate_existing=True)
        if review_case and review_case.status == CaseStatus.DISPOSED.value:
            await case_service.add_case_message(
                db,
                review_case,
                sender_id=user.id,
                role=case_service.DisposalMessageRole.SYSTEM,
                kind=case_service.DisposalMessageKind.NOTICE,
                content="卖方在审核认领前撤回商品，本次审核事项结束，商品置为已下架。",
            )
    await db.commit()
    await db.refresh(product)
    return await _out(db, product, user, include_pending_count=True)


@router.post("/{product_id}/resubmit", response_model=ProductOut)
async def resubmit(
    product_id: int, body: ProductUpdateIn, user: CurrentUser, db: DbSession
) -> ProductOut:
    """TR-03/TR-21：审核拒绝或认领前撤回后的已下架商品可修改后重提，形成独立审核记录。"""
    ensure_can_write(user)
    product = await db.get(Product, product_id)
    if not product or product.seller_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    latest_review = await db.scalar(
        select(ReviewRecord).where(ReviewRecord.product_id == product.id).order_by(ReviewRecord.id.desc()).limit(1)
    )
    can_resubmit = product.status == ProductStatus.REJECTED.value or (
        product.status == ProductStatus.DELISTED.value
        and latest_review is not None
        and latest_review.result == ReviewResult.WITHDRAWN.value
    )
    if not can_resubmit:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "仅审核未通过或认领前撤回审核的商品可修改重提；普通已下架商品请重新上架",
        )
    if product.display_restricted:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "商品因处置停止公开访问，暂不可重提")
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
        current_ids = {t.id for t in await product_service.load_product_tags(db, product.id)}
        await db.execute(ProductTag.__table__.delete().where(ProductTag.product_id == product.id))
        for cid in body.category_ids:
            category = await db.get(Category, cid)
            if not category or category.deleted_at is not None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "所选标签不存在")
            # 历史已关联的停用标签可继续保留，但不得新选择停用标签。
            if category.status != "active" and cid not in current_ids:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"所选标签已停用：{category.name}")
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
    if product.status not in (
        ProductStatus.LISTED.value,
        ProductStatus.DELISTED.value,
        ProductStatus.PENDING_REVIEW.value,
    ):
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
                # 只允许保留历史已有关联的停用标签，不能新关联停用标签。
                if category.status != "active" and cid not in current_ids:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"所选标签已停用：{category.name}")
                db.add(ProductTag(product_id=product.id, category_id=cid))
            changed = True
    if body.withdraw_tag_application_ids:
        if product.status != ProductStatus.PENDING_REVIEW.value:
            raise HTTPException(status.HTTP_409_CONFLICT, "仅待审核期间可撤回标签申请")
        applications = (
            await db.execute(
                select(ProductTagApplication).where(
                    ProductTagApplication.product_id == product.id,
                    ProductTagApplication.id.in_(body.withdraw_tag_application_ids),
                    ProductTagApplication.status == "pending",
                )
            )
        ).scalars().all()
        if len(applications) != len(set(body.withdraw_tag_application_ids)):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "存在不可撤回的标签申请")
        for application in applications:
            application.status = "withdrawn"
            application.decided_at = datetime.now(UTC)
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
    """主动下架（BR-09/14）：无未结束锁单交易；关闭待接受请求并注明原因；冻结禁下架（D-50）。"""
    ensure_can_write(user)
    if await permissions.has_active_frozen_trade(db, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "存在有效交易冻结，暂不能主动下架商品")
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
    """重新上架/继续上架（TR-08）：已下架、审核有效且当前账户及商品限制允许；冻结禁上架（D-50）。"""
    ensure_can_write(user)
    if await permissions.has_active_frozen_trade(db, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "存在有效交易冻结，暂不能上架或重新上架商品")
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
