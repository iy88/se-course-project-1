"""Products: publish, resubmit, edit, delist/relist, search, detail, and edit history (FR-02/03/09)."""

from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Header, HTTPException, Query, status
from sqlalchemy.engine import CursorResult
from sqlmodel import col, delete, func, select, update
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api import idempotency as idempotency_service
from app.api.deps import CurrentUser, DbSession, ensure_can_write
from app.api.upload_keys import validate_upload_keys
from app.models import (
    Category,
    CategoryAlias,
    DisposalCase,
    Product,
    ProductImage,
    ProductTag,
    ProductTagApplication,
    Report,
    ReviewRecord,
    Trade,
    User,
)
from app.models.enums import (
    CaseStatus,
    CaseType,
    ProductStatus,
    ReviewResult,
    TradeStatus,
)
from app.schemas.product import (
    DecidedTagApplicationOut,
    PendingTagApplicationOut,
    ProductCardOut,
    ProductCreateIn,
    ProductEditHistoryOut,
    ProductOut,
    ProductSearchOut,
    ProductUpdateIn,
    ReviewRecordOut,
)
from app.services import audit as audit_service
from app.services import cases as case_service
from app.services import permissions, stored_objects
from app.services import products as product_service
from app.services import trades as trade_service
from app.services.notifications import notify
from app.storage.base import StorageError, StorageInvalidKey, get_storage

router = APIRouter(prefix="/products", tags=["products"])


async def _snapshot_content(db: AsyncSession, product: Product) -> dict:
    return await product_service.snapshot_content(db, product)


async def _out(db: AsyncSession, product: Product, user: User, include_pending_count: bool = False) -> ProductOut:
    storage = get_storage()
    images = await product_service.load_product_images(db, product.id)
    tags = await product_service.load_product_tags(db, product.id)
    pending = 0
    if include_pending_count and user.id == product.seller_id:
        pending = (await db.exec(
            select(func.count())
            .select_from(Trade)
            .where(col(Trade.product_id) == product.id, col(Trade.status) == TradeStatus.PENDING_ACCEPTANCE.value)
        )).first() or 0
    can_withdraw_review = False
    can_resubmit = False
    pending_tag_applications: list[PendingTagApplicationOut] = []
    decided_tag_applications: list[DecidedTagApplicationOut] = []
    if user.id == product.seller_id:
        # Tag applications visible only to the seller: pending ones let the frontend enumerate withdrawal IDs (R11); handled ones return results and reasons.
        applications = (
            await db.exec(
                select(ProductTagApplication)
                .where(col(ProductTagApplication.product_id) == product.id)
                .order_by(col(ProductTagApplication.id))
            )
        ).all()
        pending_tag_applications = [
            PendingTagApplicationOut(id=a.id, requested_name=a.requested_name)
            for a in applications
            if a.status == "pending"
        ]
        decided_tag_applications = [
            DecidedTagApplicationOut.model_validate(a) for a in applications if a.status != "pending"
        ]
    if user.id == product.seller_id and not product.display_restricted:
        latest_review = (await db.exec(
            select(ReviewRecord).where(col(ReviewRecord.product_id) == product.id).order_by(col(ReviewRecord.id).desc()).limit(1)
        )).first()
        if product.status == ProductStatus.PENDING_REVIEW.value:
            # Withdrawable before claim; once claimed, only the claiming administrator may handle the old review
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
            # Only a delisted product created by "withdraw review before claim" can be resubmitted; a normally delisted reviewed product is relisted
            can_resubmit = True
    restriction_result = await _restriction_result(db, product)
    return ProductOut(
        id=product.id,
        seller_id=product.seller_id,
        title=product.title,
        description=product.description,
        price_cents=product.price_cents,
        status=ProductStatus(product.status),
        display_restricted=product.display_restricted,
        display_restricted_reason=product.display_restricted_reason,
        restriction_result=restriction_result,
        reject_reason=product.reject_reason if user.id == product.seller_id else None,
        image_keys=[i.file_key for i in images],
        image_urls=[storage.public_url(i.file_key) for i in images],
        tag_ids=[t.id for t in tags],
        tag_names=[t.name for t in tags],
        pending_tag_applications=pending_tag_applications,
        decided_tag_applications=decided_tag_applications,
        created_at=product.created_at,
        updated_at=product.updated_at,
        pending_request_count=int(pending),
        can_withdraw_review=can_withdraw_review,
        can_resubmit=can_resubmit,
    )


async def _restriction_result(db: AsyncSession, product: Product) -> str | None:
    if not product.display_restricted or not product.display_restricted_case_id:
        return None
    case = await db.get(DisposalCase, product.display_restricted_case_id)
    if case is None or not case.report_id:
        return None
    report = await db.get(Report, case.report_id)
    if report is not None and report.result_confirmed and report.status == "handled":
        return report.public_result
    return None


@router.get("/{product_id}/restriction-result")
async def restriction_result(product_id: int, user: CurrentUser, db: DbSession) -> dict:
    """Anonymous disposal notice for the original route; does not expose restricted product content or private case details."""
    product = await db.get(Product, product_id)
    result = await _restriction_result(db, product) if product else None
    if not result:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "暂无公开处置结果")
    return {"public_result": result}


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


async def _validate_image_keys(db: AsyncSession, image_keys: list[str], owner_id: int) -> None:
    await validate_upload_keys(db, image_keys, owner_id=owner_id, namespace="product")
    try:
        storage = get_storage()
    except StorageError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "文件存储暂不可用") from exc
    for key in image_keys:
        try:
            exists = await run_in_threadpool(storage.exists, key)
        except StorageInvalidKey as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"图片不存在或已失效：{key}") from exc
        except StorageError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "文件存储暂不可用") from exc
        if not exists:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"图片不存在或已失效：{key}")


def _ensure_selectable_category(category: Category) -> None:
    """Disabled tags cannot be chosen for new publications/new links; already-linked historical tags are retained (4.16)."""
    if category.status != "active":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"所选标签已停用：{category.name}")


async def _resolve_tags_for_submit(
    db: AsyncSession, product: Product, tags_in: list
) -> tuple[list[int], list[ProductTagApplication]]:
    """Return (linked existing tag IDs, new tag applications). At least one existing tag or one new application (BR-12)."""
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
            exists = (await db.exec(select(Category).where(col(Category.name) == name, col(Category.deleted_at).is_(None)))).first()
            alias = (await db.exec(
                select(CategoryAlias).where(col(CategoryAlias.name) == name, col(CategoryAlias.removed_at).is_(None))
            )).first()
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
async def publish_product(
    body: ProductCreateIn,
    user: CurrentUser,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ProductOut:
    """Publish: enter pending review and the shared pending pool (BR-10, BR-34); publishing is blocked while frozen (D-50).

    An optional Idempotency-Key shares the transaction with the product, review, audit,
    and event rows; when omitted, behavior is unchanged.
    """
    key = idempotency_service.parse_key(idempotency_key)
    async with idempotency_service.guard(db, user.id, "product.publish", key, body.model_dump()) as idem:
        if idem.replay is not None:
            product_id = int((idem.replay.response or {}).get("product_id", 0))
            product = await db.get(Product, product_id) if product_id else None
            if product is None:
                raise HTTPException(status.HTTP_409_CONFLICT, "幂等结果对应的商品已不存在")
            return await _out(db, product, user, include_pending_count=True)
        ensure_can_write(user)
        if await permissions.has_active_frozen_trade(db, user.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "存在有效交易冻结，暂不能发布商品")
        await _validate_image_keys(db, body.image_keys, user.id)
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
        for sort, key_name in enumerate(body.image_keys):
            db.add(ProductImage(product_id=product.id, file_key=key_name, sort=sort))
        try:
            await stored_objects.mark_committed(
                db, body.image_keys, ref_type="product", ref_id=product.id
            )
        except stored_objects.StoredObjectUnavailable:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "图片已被回收，请重新上传"
            ) from None
        # Snapshot the content under review and put the review case into the shared pool
        content = await _snapshot_content(db, product)
        case = await case_service.create_case(
            db,
            case_type=CaseType.PRODUCT_REVIEW,
            title=f"商品审核：{product.title}",
            subject_user_id=user.id,
            product_id=product.id,
        )
        db.add(ReviewRecord(product_id=product.id, content_json=content, case_id=case.id))
        await audit_service.record_event(
            db,
            audit_service.EVENT_PRODUCT_PUBLISH,
            target_type="product",
            target_id=product.id,
            after={"status": product.status, "price_cents": product.price_cents, "case_id": case.id},
        )
        await db.flush()
        await db.refresh(product)
        result = await _out(db, product, user, include_pending_count=True)
        await idem.complete(status_code=200, response={"product_id": product.id})
        await db.commit()
        return result


@router.get("/search", response_model=ProductSearchOut)
async def search(
    db: DbSession,
    user: CurrentUser,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    category_ids: Annotated[list[int] | None, Query()] = None,
    category_names: Annotated[list[str] | None, Query()] = None,
    price_min_cents: Annotated[int | None, Query(ge=0)] = None,
    price_max_cents: Annotated[int | None, Query(ge=0)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> ProductSearchOut:
    """Search listed products by keyword/multiple tags (all must match)/price range (BR-15).

    D-45: explicit category_names resolve against current primary names and active
    aliases; any unknown name produces no matches.
    """
    if category_names:
        resolved_names = await product_service.resolve_category_names(db, category_names)
        if resolved_names is None:
            return ProductSearchOut(items=[], total=0, message="无匹配商品")
        merged_ids = list(dict.fromkeys((category_ids or []) + resolved_names))
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
        rows = await db.exec(select(col(User.id), col(User.display_name)).where(col(User.id).in_(seller_ids)))
        names = {uid: name for uid, name in rows.all()}
    cards = [_card(p, names.get(p.seller_id, ""), p.images[0].file_key if p.images else None) for p in items]
    return ProductSearchOut(
        items=cards,
        total=total,
        message=None if total else ("无匹配商品" if any([keyword, category_ids, category_names, price_min_cents, price_max_cents]) else "暂无在售商品"),
    )


@router.get("/mine", response_model=list[ProductOut])
async def my_products(user: CurrentUser, db: DbSession) -> list[ProductOut]:
    """My products: all statuses plus review reasons and pending-acceptance request counts (FR-12, 4.18)."""
    result = await db.exec(
        select(Product).where(col(Product.seller_id) == user.id).order_by(col(Product.created_at).desc())
    )
    products = list(result)
    return [await _out(db, p, user, include_pending_count=True) for p in products]


@router.get("/{product_id}", response_model=ProductOut)
async def detail(product_id: int, user: CurrentUser, db: DbSession) -> ProductOut:
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在或不可见")
    # Admin product preview: administrators may view details in any status without changing regular-user eligibility (comments etc. still follow the original rules).
    visible = user.role == "admin" or product_service.is_detail_visible(user, product)
    if not visible and not product.display_restricted:
        # D-43: a buyer who once had a request/trade can still see current details and later changes after it ends
        visible = await product_service.has_product_request_history(db, user.id, product.id)
    if not visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在或不可见")
    return await _out(db, product, user, include_pending_count=True)


@router.get("/{product_id}/edit-history", response_model=list[ProductEditHistoryOut])
async def edit_history(product_id: int, user: CurrentUser, db: DbSession) -> list[ProductEditHistoryOut]:
    """Sellers see full history; buyers see the content matching their own request and later changes; administrators are limited to the necessary scope (4.18, D-43)."""
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    from app.models import ProductEditHistory

    result = await db.exec(
        select(ProductEditHistory)
        .where(col(ProductEditHistory.product_id) == product_id)
        .order_by(col(ProductEditHistory.id))
    )
    histories = list(result)
    if product.seller_id != user.id and user.role != "admin":
        first_trade = (await db.exec(
            select(Trade)
            .where(col(Trade.product_id) == product_id, col(Trade.buyer_id) == user.id)
            .order_by(col(Trade.created_at), col(Trade.id))
            .limit(1)
        )).first()
        if first_trade is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "仅本人请求对应内容及之后变更有访问权")
        # After the request ends the buyer can still see later product changes, but not history from before the request (D-43)
        histories = [
            h for h in histories if h.created_at >= first_trade.created_at
        ]
    # Sign image URLs for visible snapshots only after the eligibility and time-range filters.
    editor_ids = {h.editor_id for h in histories}
    names = {}
    if editor_ids:
        rows = await db.exec(select(col(User.id), col(User.display_name)).where(col(User.id).in_(editor_ids)))
        names = dict(rows.all())
    storage = get_storage()
    output = []
    for history in histories:
        item = ProductEditHistoryOut.model_validate(history)
        item.editor_name = names.get(history.editor_id, '')
        item.before_image_urls = [storage.public_url(key) for key in history.before_json.get('images', [])]
        item.after_image_urls = [storage.public_url(key) for key in history.after_json.get('images', [])]
        output.append(item)
    return output


@router.get("/{product_id}/review-records", response_model=list[ReviewRecordOut])
async def review_records(product_id: int, user: CurrentUser, db: DbSession) -> list[ReviewRecordOut]:
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    if product.seller_id != user.id and user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅发布者可查看审核记录")
    result = await db.exec(
        select(ReviewRecord).where(col(ReviewRecord.product_id) == product_id).order_by(col(ReviewRecord.id))
    )
    return [ReviewRecordOut.model_validate(r) for r in result]


async def _dispose_review_case_atomically(db: AsyncSession, case_id: int, *, now: datetime) -> bool:
    """Database race between withdrawal and claiming the same case: only a pending, unclaimed case may be withdrawn.

    The database evaluates the UPDATE conditions and the disposal conclusion in one
    statement; on failure no business write occurs. synchronize_session="evaluate"
    refreshes any stale in-session case object so a later flush cannot overwrite it.
    """
    result = await db.exec(
        update(DisposalCase)
        .where(
            col(DisposalCase.id) == case_id,
            col(DisposalCase.status) == CaseStatus.PENDING.value,
            col(DisposalCase.claimed_by_id).is_(None),
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
    return cast(CursorResult, result).rowcount == 1


@router.post("/{product_id}/withdraw-review", response_model=ProductOut)
async def withdraw_review(product_id: int, user: CurrentUser, db: DbSession) -> ProductOut:
    """D-46/TR-20: the seller withdraws before the review is claimed; the product becomes delisted and the old review case is closed but retained in history."""
    ensure_can_write(user)
    product = await trade_service.lock_product_for_update(db, product_id)
    if not product or product.seller_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    if product.status != ProductStatus.PENDING_REVIEW.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅待审核商品可撤回审核")
    review = (await db.exec(
        select(ReviewRecord)
        .where(col(ReviewRecord.product_id) == product.id, col(ReviewRecord.result) == ReviewResult.PENDING.value)
        .order_by(col(ReviewRecord.id).desc())
        .limit(1)
    )).first()
    if not review:
        raise HTTPException(status.HTTP_409_CONFLICT, "当前没有可撤回的待审核记录")
    now = datetime.now(UTC)
    # Atomically race the claim on the same case before changing the product/review record/applications/messages; any failure rolls back everything.
    if review.case_id and not await _dispose_review_case_atomically(db, review.case_id, now=now):
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "审核事项已被管理员认领或已处置，不能再撤回")
    product.status = ProductStatus.DELISTED.value
    product.delisted_at = now
    product.reject_reason = None
    review.result = ReviewResult.WITHDRAWN.value
    review.reviewed_at = now
    # Also close tag applications from the old review so they cannot be approved by mistake in a later review
    applications = (
        await db.exec(
            select(ProductTagApplication).where(
                col(ProductTagApplication.product_id) == product.id,
                col(ProductTagApplication.status) == "pending",
            )
        )
    ).all()
    for application in applications:
        application.status = "withdrawn"
        application.decided_at = now
    if review.case_id:
        # Re-read the case after the atomic update instead of using stale pre-update ORM state.
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
    await audit_service.record_event(
        db,
        audit_service.EVENT_PRODUCT_WITHDRAW_REVIEW,
        target_type="product",
        target_id=product.id,
        before={"status": ProductStatus.PENDING_REVIEW.value},
        after={"status": product.status, "review_result": review.result},
    )
    await db.commit()
    await db.refresh(product)
    return await _out(db, product, user, include_pending_count=True)


@router.post("/{product_id}/resubmit", response_model=ProductOut)
async def resubmit(
    product_id: int, body: ProductUpdateIn, user: CurrentUser, db: DbSession
) -> ProductOut:
    """TR-03/TR-21: a delisted product rejected in review or withdrawn before claim can be edited and resubmitted, creating a separate review record."""
    ensure_can_write(user)
    product = await trade_service.lock_product_for_update(db, product_id)
    if not product or product.seller_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    latest_review = (await db.exec(
        select(ReviewRecord).where(col(ReviewRecord.product_id) == product.id).order_by(col(ReviewRecord.id).desc()).limit(1)
    )).first()
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
        await _validate_image_keys(db, body.image_keys, user.id)
        await db.exec(delete(ProductImage).where(col(ProductImage.product_id) == product.id))
        for sort, key in enumerate(body.image_keys):
            db.add(ProductImage(product_id=product.id, file_key=key, sort=sort))
        try:
            await stored_objects.mark_committed(
                db, body.image_keys, ref_type="product", ref_id=product.id
            )
        except stored_objects.StoredObjectUnavailable:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "图片已被回收，请重新上传"
            ) from None
    if body.category_ids is not None:
        current_ids = {t.id for t in await product_service.load_product_tags(db, product.id)}
        await db.exec(delete(ProductTag).where(col(ProductTag.product_id) == product.id))
        for cid in body.category_ids:
            category = await db.get(Category, cid)
            if not category or category.deleted_at is not None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "所选标签不存在")
            # Disabled tags already linked historically may remain, but disabled tags cannot be newly selected.
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
    await audit_service.record_event(
        db,
        audit_service.EVENT_PRODUCT_RESUBMIT,
        target_type="product",
        target_id=product.id,
        after={"status": product.status, "price_cents": product.price_cents, "case_id": case.id},
    )
    await db.commit()
    await db.refresh(product)
    return await _out(db, product, user, include_pending_count=True)


@router.patch("/{product_id}", response_model=ProductOut)
async def edit_product(product_id: int, body: ProductUpdateIn, user: CurrentUser, db: DbSession) -> ProductOut:
    """Minor information edits (BR-11/TR-04): no second review, no display pause, no closing requests; key content cannot change during a trade."""
    ensure_can_write(user)
    product = await trade_service.lock_product_for_update(db, product_id)
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
        await _validate_image_keys(db, body.image_keys, user.id)
        await db.exec(delete(ProductImage).where(col(ProductImage.product_id) == product.id))
        for sort, key in enumerate(body.image_keys):
            db.add(ProductImage(product_id=product.id, file_key=key, sort=sort))
        try:
            await stored_objects.mark_committed(
                db, body.image_keys, ref_type="product", ref_id=product.id
            )
        except stored_objects.StoredObjectUnavailable:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "图片已被回收，请重新上传"
            ) from None
        changed = True
    if body.category_ids is not None:
        current_ids = {t.id for t in await product_service.load_product_tags(db, product.id)}
        if set(body.category_ids) != current_ids:
            await db.exec(delete(ProductTag).where(col(ProductTag.product_id) == product.id))
            for cid in set(body.category_ids):
                category = await db.get(Category, cid)
                if not category or category.deleted_at is not None:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "所选标签不存在")
                # Only historically linked disabled tags may remain; disabled tags cannot be newly linked.
                if category.status != "active" and cid not in current_ids:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"所选标签已停用：{category.name}")
                db.add(ProductTag(product_id=product.id, category_id=cid))
            changed = True
    if body.withdraw_tag_application_ids:
        if product.status != ProductStatus.PENDING_REVIEW.value:
            raise HTTPException(status.HTTP_409_CONFLICT, "仅待审核期间可撤回标签申请")
        applications = (
            await db.exec(
                select(ProductTagApplication).where(
                    col(ProductTagApplication.product_id) == product.id,
                    col(ProductTagApplication.id).in_(body.withdraw_tag_application_ids),
                    col(ProductTagApplication.status) == "pending",
                )
            )
        ).all()
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
    await audit_service.record_event(
        db,
        audit_service.EVENT_PRODUCT_EDIT,
        target_type="product",
        target_id=product.id,
        before=before,
        after=after,
    )
    await db.commit()
    await db.refresh(product)
    return await _out(db, product, user, include_pending_count=True)


@router.post("/{product_id}/delist", response_model=ProductOut)
async def delist(product_id: int, user: CurrentUser, db: DbSession) -> ProductOut:
    """Delist voluntarily (BR-09/14): no unfinished locking trade; close pending-acceptance requests with a reason; delisting is blocked while frozen (D-50)."""
    ensure_can_write(user)
    if await permissions.has_active_frozen_trade(db, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "存在有效交易冻结，暂不能主动下架商品")
    product = await trade_service.lock_product_for_update(db, product_id)
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
            "您的购买请求已关闭",
            f"商品「{product.title}」已下架，对应请求已关闭。",
            link_type="trade",
            link_id=trade.id,
        )
    await audit_service.record_event(
        db,
        audit_service.EVENT_PRODUCT_DELIST,
        target_type="product",
        target_id=product.id,
        before={"status": ProductStatus.LISTED.value},
        after={"status": product.status},
    )
    await db.commit()
    await db.refresh(product)
    return await _out(db, product, user, include_pending_count=True)


@router.post("/{product_id}/relist", response_model=ProductOut)
async def relist(product_id: int, user: CurrentUser, db: DbSession) -> ProductOut:
    """Relist/continue listing (TR-08): the product is delisted, its review is valid, and current account/product restrictions allow it; listing is blocked while frozen (D-50)."""
    ensure_can_write(user)
    if await permissions.has_active_frozen_trade(db, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "存在有效交易冻结，暂不能上架或重新上架商品")
    product = await trade_service.lock_product_for_update(db, product_id)
    if not product or product.seller_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    if product.status != ProductStatus.DELISTED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "仅已下架商品可重新上架")
    if product.display_restricted:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "商品因处置停止公开访问，暂不可上架")
    latest = (await db.exec(
        select(ReviewRecord).where(col(ReviewRecord.product_id) == product.id).order_by(col(ReviewRecord.id).desc()).limit(1)
    )).first()
    if not latest or latest.result != ReviewResult.APPROVED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "商品审核无效，须重新提交审核")
    product.status = ProductStatus.LISTED.value
    product.listed_at = datetime.now(UTC)
    product.delisted_at = None
    await audit_service.record_event(
        db,
        audit_service.EVENT_PRODUCT_RELIST,
        target_type="product",
        target_id=product.id,
        before={"status": ProductStatus.DELISTED.value},
        after={"status": product.status},
    )
    await db.commit()
    await db.refresh(product)
    return await _out(db, product, user, include_pending_count=True)
