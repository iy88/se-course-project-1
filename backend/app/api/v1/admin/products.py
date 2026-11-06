"""管理员商品审核与分类纠正（BR-10/11/13、TR-01—TR-03）。"""

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import and_, col, delete, func, select

from app.core.text import NonBlank500, Text500
from app.api.deps import CurrentAdmin, DbSession
from app.models import (
    AccountRestriction,
    Category,
    CategoryAlias,
    DisposalCase,
    Product,
    ProductTag,
    ProductTagApplication,
    ReviewRecord,
    Trade,
    User,
)
from app.models.enums import (
    AccountStatus,
    CaseStatus,
    CaseType,
    ProductStatus,
    RestrictionStatus,
    ReviewResult,
)
from app.services import audit as audit_service
from app.services import cases as case_service
from app.services import products as product_service
from app.services.cases import ensure_claimant
from app.services.notifications import notify

router = APIRouter(prefix="/admin/products", tags=["admin-products"])


class TagDecisionIn(BaseModel):
    application_id: int
    decision: str = Field(pattern="^(approve_new|map_alias|reject)$")
    category_id: int | None = None  # map_alias 时指向已有分类
    # 拒绝时必须说明原因；商品通过同时拒绝标签时逐申请可见。
    reason: Text500 | None = Field(default=None)


class ReviewDecisionIn(BaseModel):
    result: str = Field(pattern="^(approved|rejected)$")
    # 商品级原因：不通过时必填；通过时可作为逐申请标签拒绝原因的 fallback。
    reason: Text500 | None = Field(default=None)
    tag_decisions: list[TagDecisionIn] = []


class CategoryCorrectionIn(BaseModel):
    category_ids: list[int] = Field(min_length=1)
    reason: NonBlank500


@router.get("")
async def list_products(
    admin: CurrentAdmin,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    product_status: str = Query(
        default="all", alias="status",
        pattern="^(pending_review|rejected|listed|in_transaction|delisted|all)$",
    ),
    category_id: int | None = Query(default=None, ge=1),
    display_restricted: str = Query(default="all", pattern="^(all|yes|no)$"),
    keyword: str | None = Query(default=None, max_length=100),
) -> dict:
    """管理端商品列表：服务端分页、状态/分类/展示限制筛选与关键词检索。

    关键词匹配名称、描述、所关联分类的主名与活跃别名；纯数字关键词同时精确匹配商品 ID。
    """
    conditions = []
    if product_status != "all":
        conditions.append(col(Product.status) == product_status)
    if display_restricted != "all":
        conditions.append(col(Product.display_restricted).is_(display_restricted == "yes"))
    if category_id is not None:
        tagged = select(col(ProductTag.product_id)).where(col(ProductTag.category_id) == category_id)
        conditions.append(col(Product.id).in_(tagged))
    if keyword and keyword.strip():
        stripped = keyword.strip()
        like = f"%{stripped}%"
        keyword_tag_ids = (
            select(col(ProductTag.product_id))
            .join(Category, col(Category.id) == col(ProductTag.category_id))
            .outerjoin(
                CategoryAlias,
                and_(col(CategoryAlias.category_id) == col(Category.id), col(CategoryAlias.removed_at).is_(None)),
            )
            .where((col(Category.name).like(like)) | (col(CategoryAlias.name).like(like)))
        )
        text_match = (
            (col(Product.title).like(like))
            | (col(Product.description).like(like))
            | (col(Product.id).in_(keyword_tag_ids))
        )
        if stripped.isdigit():
            text_match = text_match | (col(Product.id) == int(stripped))
        conditions.append(text_match)

    count_stmt = select(func.count()).select_from(Product)
    rows_stmt = select(Product).order_by(col(Product.id).desc())
    if conditions:
        where_clause = and_(*conditions)
        count_stmt = count_stmt.where(where_clause)
        rows_stmt = rows_stmt.where(where_clause)
    total = (await db.exec(count_stmt)).first() or 0
    rows = (await db.exec(
        rows_stmt.offset((page - 1) * page_size).limit(page_size)
    )).all()
    seller_names = {}
    seller_ids = {product.seller_id for product in rows}
    if seller_ids:
        for seller in (await db.exec(select(User).where(col(User.id).in_(seller_ids)))).all():
            seller_names[seller.id] = seller.display_name
    items = [
        {
            "id": product.id,
            "title": product.title,
            "status": product.status,
            "display_restricted": product.display_restricted,
            "price_cents": product.price_cents,
            "seller_id": product.seller_id,
            "seller_name": seller_names.get(product.seller_id),
            "tag_names": [tag.name for tag in product.tags],
            "created_at": product.created_at.isoformat() if product.created_at else None,
        }
        for product in rows
    ]
    return {"items": items, "total": int(total), "page": page, "page_size": page_size}


class RestoreDisplayIn(BaseModel):
    case_id: int
    reason: NonBlank500


def _clean_reason(value: str | None) -> str | None:
    """去除首尾空白；全空白视为未提供，不写入或用于通过校验。"""
    cleaned = (value or "").strip()
    return cleaned or None


@router.post("/cases/{case_id}/review")
async def review_product(case_id: int, body: ReviewDecisionIn, admin: CurrentAdmin, db: DbSession) -> dict:
    """审核当次内容（TR-01/02）：通过联动展示与标签批准；不通过记录原因并通知。"""
    case = await case_service.lock_case_for_update(db, case_id)
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "事项不存在")
    if case.status == CaseStatus.DISPOSED.value:
        # 撤回/已处置事项不能按旧 id 再审，历史保留
        raise HTTPException(status.HTTP_409_CONFLICT, "该事项已处置")
    await ensure_claimant(case, admin.id)
    if case.case_type != CaseType.PRODUCT_REVIEW.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该事项不是商品审核事项")
    product = await db.get(Product, case.product_id)
    review = (await db.exec(
        select(ReviewRecord).where(col(ReviewRecord.case_id) == case.id).order_by(col(ReviewRecord.id).desc()).limit(1)
    )).first()
    if not product or not review:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "审核事项数据不完整")
    if product.status != ProductStatus.PENDING_REVIEW.value or review.result != ReviewResult.PENDING.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "商品当前不在待审核状态")
    apps = (
        await db.exec(
            select(ProductTagApplication).where(
                col(ProductTagApplication.product_id) == product.id, col(ProductTagApplication.status) == "pending"
            )
        )
    ).all()
    apps_by_id = {app.id: app for app in apps}
    decision_ids = [d.application_id for d in body.tag_decisions]
    # R8/R11：决定只能指向本次待审核商品当前有效的 pending 申请；
    # 撤回、已处理、其他商品/他人的申请 ID 明确拒绝，不得忽略后继续批准。
    if len(decision_ids) != len(set(decision_ids)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "标签申请决定重复")
    for decision in body.tag_decisions:
        if decision.application_id not in apps_by_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"标签申请不属于本次待审核内容或已失效（申请 {decision.application_id}）",
            )
    decisions = {d.application_id: d for d in body.tag_decisions}
    product_reason = _clean_reason(body.reason)

    # 在任何审核/标签写入之前完成原因校验：拒绝标签必须说明原因，
    # 可复用管理员显式提交的商品级原因作为 fallback；不自动生成固定理由。
    if body.result == "approved":
        undecided = [app.id for app in apps if app.id not in decisions]
        if undecided:
            ids = "、".join(str(app_id) for app_id in undecided)
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"商品通过时须对每条待审标签申请作出决定并说明拒绝原因（申请 {ids}）",
            )
        for app in apps:
            decision = decisions[app.id]
            if decision.decision == "reject" and not (_clean_reason(decision.reason) or product_reason):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"拒绝标签申请须说明原因（申请 {app.id}）",
                )
    elif not product_reason:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不通过时须记录拒绝原因")

    # D-46：认领前后卖方均可修改，审核结论以提交结论时的最新内容为准并刷新快照。
    # 校验通过后才写入，避免无效原因留下部分审核/标签变更。
    review.content_json = await product_service.snapshot_content(db, product)
    now = case_service.now_utc()

    if body.result == "approved":
        # 标签随商品通过生效（4.16）
        approved_tag_ids = {t.id for t in await product_service.load_product_tags(db, product.id)}
        for app in apps:
            decision = decisions.get(app.id)
            if decision is None or decision.decision == "reject":
                app.status = "rejected"
                app.decision_reason = _clean_reason(decision.reason) if decision else None
                app.decision_reason = app.decision_reason or product_reason
                app.decided_at = now
                continue
            if decision.decision == "approve_new":
                exists = (await db.exec(
                    select(Category).where(col(Category.name) == app.requested_name, col(Category.deleted_at).is_(None))
                )).first()
                if exists:
                    category = exists
                else:
                    # 新主名不得与现有活跃别名冲突；此类名称应走别名映射。
                    alias_conflict = (await db.exec(
                        select(CategoryAlias).where(
                            col(CategoryAlias.name) == app.requested_name, col(CategoryAlias.removed_at).is_(None)
                        )
                    )).first()
                    if alias_conflict:
                        raise HTTPException(
                            status.HTTP_400_BAD_REQUEST,
                            f"标签名称已是现有分类别名，请使用别名映射（申请 {app.id}）",
                        )
                    category = Category(name=app.requested_name, created_by_id=admin.id)
                    db.add(category)
                    await db.flush()
                app.status = "approved_new"
                app.resolved_category_id = category.id
                app.decision_reason = None
                approved_tag_ids.add(category.id)
            else:  # map_alias：同义名称作为已有分类别名，商品关联原分类
                target = await db.get(Category, decision.category_id)
                if not target or target.deleted_at is not None:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"别名映射目标分类不存在（申请 {app.id}）")
                if target.status != "active":
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"别名映射目标分类已停用（申请 {app.id}）")
                # 别名不得与其他分类主名或活跃别名冲突（4.16）。
                principal_conflict = (await db.exec(
                    select(Category).where(
                        col(Category.name) == app.requested_name,
                        col(Category.deleted_at).is_(None),
                        col(Category.id) != target.id,
                    )
                )).first()
                alias_exists = (await db.exec(
                    select(CategoryAlias).where(
                        col(CategoryAlias.name) == app.requested_name, col(CategoryAlias.removed_at).is_(None)
                    )
                )).first()
                if principal_conflict or (alias_exists and alias_exists.category_id != target.id):
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST, f"标签名称已被其他分类使用（申请 {app.id}）"
                    )
                if not alias_exists and app.requested_name != target.name:
                    db.add(CategoryAlias(category_id=target.id, name=app.requested_name, created_by_id=admin.id))
                app.status = "approved_alias"
                app.resolved_category_id = target.id
                app.decision_reason = None
                approved_tag_ids.add(target.id)
            app.decided_at = now
        if not approved_tag_ids:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "商品通过时须至少关联一个获认可标签（请处理标签申请或保留已有标签）",
            )
        await db.exec(delete(ProductTag).where(col(ProductTag.product_id) == product.id))
        for cid in approved_tag_ids:
            db.add(ProductTag(product_id=product.id, category_id=cid))
        product.status = ProductStatus.LISTED.value
        product.listed_at = now
        product.reject_reason = None
        review.reviewer_id = admin.id
        review.result = ReviewResult.APPROVED.value
        review.reason = None
        review.reviewed_at = now
        await case_service.dispose_case(db, case, conclusion="审核通过", basis="依据当前禁发范围审核通过")
        await notify(
            db, [product.seller_id], "review_result", "商品审核通过",
            f"商品「{product.title}」已通过审核并公开，可被检索与请求。通过仅代表审核结果，不代表成交。",
            link_type="product", link_id=product.id,
        )
        message = "审核通过，商品已公开"
    else:
        reason = product_reason
        for app in apps:
            decision = decisions.get(app.id)
            app.status = "rejected"
            # 逐申请优先使用显式原因；未单独填写时复用管理员显式提交的商品级原因。
            app.decision_reason = (_clean_reason(decision.reason) if decision else None) or reason
            app.decided_at = now
        product.status = ProductStatus.REJECTED.value
        product.reject_reason = reason
        review.reviewer_id = admin.id
        review.result = ReviewResult.REJECTED.value
        review.reason = reason
        review.reviewed_at = now
        await case_service.dispose_case(db, case, conclusion="审核未通过", reason=reason, basis="依据当前禁发范围审核未通过")
        await notify(
            db, [product.seller_id], "review_result", "商品审核未通过",
            f"商品「{product.title}」未通过审核，原因：{reason}。可查看商品并修改后重新提交。",
            link_type="product", link_id=product.id,
        )
        message = "审核未通过，已通知发布者"

    await audit_service.record_event(
        db,
        audit_service.EVENT_ADMIN_PRODUCT_REVIEW,
        target_type="product",
        target_id=product.id,
        after={
            "status": product.status,
            "review_result": review.result,
            "case_id": case.id,
            # 只记录逐申请结果，不把管理员业务说明正文写入审计。
            "tag_applications": [{"application_id": app.id, "status": app.status} for app in apps],
        },
    )
    await db.commit()
    return {"detail": message}


@router.post("/{product_id}/restore-display")
async def restore_product_display(
    product_id: int, body: RestoreDisplayIn, admin: CurrentAdmin, db: DbSession
) -> dict:
    """D-44/TR-10：认领原展示限制事项的管理员有依据解除公开访问限制。

    只解除该事项来源的展示限制：不改生命周期（不把已下架变在售）、
    不解锁/解冻交易，也不解除仍有效的账户封禁或其他来源限制。
    """
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    if not product.display_restricted:
        raise HTTPException(status.HTTP_409_CONFLICT, "商品当前没有公开访问限制")
    if product.display_restricted_case_id != body.case_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "该事项不是当前展示限制的来源依据")

    case = await db.get(DisposalCase, body.case_id)
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "事项不存在")
    await ensure_claimant(case, admin.id)

    # 事项须与原展示限制对象相关：商品本身、关联交易商品或同一发布者封禁事项。
    related = case.product_id == product.id
    if not related and case.trade_id:
        trade = await db.get(Trade, case.trade_id)
        related = bool(trade and trade.product_id == product.id)
    if not related and case.product_id is None and case.subject_user_id == product.seller_id:
        related = True
    if not related:
        raise HTTPException(status.HTTP_409_CONFLICT, "事项与商品展示限制无关")

    seller = await db.get(User, product.seller_id)
    if not seller:
        raise HTTPException(status.HTTP_409_CONFLICT, "商品发布者不存在")
    active_ban = (await db.exec(
        select(col(AccountRestriction.id)).where(
            col(AccountRestriction.user_id) == seller.id,
            col(AccountRestriction.type) == "ban",
            col(AccountRestriction.status) == RestrictionStatus.ACTIVE.value,
        )
    )).first()
    if seller.status == AccountStatus.BANNED.value or active_ban is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "发布者仍处于封禁状态，不能单独解除展示限制")

    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "须记录解除展示限制的原因")
    before = {
        "display_restricted": True,
        "display_restricted_reason": product.display_restricted_reason,
        "display_restricted_case_id": product.display_restricted_case_id,
        "status": product.status,
    }
    product.display_restricted = False
    product.display_restricted_reason = None
    product.display_restricted_at = None
    product.display_restricted_case_id = None
    after = {
        "display_restricted": False,
        "display_restricted_reason": None,
        "display_restricted_case_id": None,
        "status": product.status,
    }
    # 复用商品编辑历史留痕：执行人、时间、原因及前后限制，不新增 schema。
    await product_service.record_edit_history(
        db, product, admin.id, before, after, edit_type="display_restore", reason=reason
    )
    await case_service.add_case_message(
        db,
        case,
        sender_id=admin.id,
        role=case_service.DisposalMessageRole.SYSTEM,
        kind=case_service.DisposalMessageKind.NOTICE,
        content=(
            f"管理员解除商品「{product.title}」的公开访问限制。原因：{reason}。"
            f"生命周期状态保持 {product.status}，交易锁单/冻结不变。"
        ),
    )
    await notify(
        db,
        [seller.id],
        "disposal",
        "商品公开访问限制已解除",
        (f"商品「{product.title}」的公开访问限制已由管理员解除，原因：{reason}。"
         "商品原生命周期状态、交易锁单及冻结不变。"),
        link_type="product",
        link_id=product.id,
    )
    await product_service.notify_open_request_buyers(
        db,
        product,
        "关注的商品公开访问限制已解除",
        f"您关注的商品「{product.title}」公开访问限制已解除，可按商品当前状态查看。",
    )
    await audit_service.record_event(
        db,
        audit_service.EVENT_ADMIN_PRODUCT_RESTORE_DISPLAY,
        target_type="product",
        target_id=product.id,
        before={"display_restricted": True},
        after={"display_restricted": False, "status": product.status, "case_id": case.id},
    )
    await db.commit()
    return {"detail": "展示限制已解除；生命周期与交易限制保持不变"}


@router.post("/{product_id}/correct-category")
async def correct_category(product_id: int, body: CategoryCorrectionIn, admin: CurrentAdmin, db: DbSession) -> dict:
    """管理员有依据纠正分类（BR-11）：留前后内容、原因、操作人与时间，通知卖方。"""
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    before = await product_service.load_product_tags(db, product.id)
    retained_ids = {tag.id for tag in before}
    categories = []
    for cid in sorted(set(body.category_ids)):
        category = await db.get(Category, cid)
        if not category or category.deleted_at is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"分类不存在：{cid}")
        # 停用分类只可作为“保留原关联”出现在纠正结果中，不能用作新增关联（4.16、US-13-AC-04）。
        if category.status != "active" and category.id not in retained_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"所选标签已停用：{category.name}")
        categories.append(category)
    before_names = [t.name for t in before]
    await db.exec(delete(ProductTag).where(col(ProductTag.product_id) == product.id))
    for category in categories:
        db.add(ProductTag(product_id=product.id, category_id=category.id))
    after_names = [c.name for c in categories]
    await product_service.record_edit_history(
        db, product, admin.id,
        {"tags": before_names}, {"tags": after_names},
        edit_type="category_correction", reason=body.reason.strip(),
    )
    await product_service.notify_open_request_buyers(
        db, product, "商品分类已被平台纠正",
        f"商品「{product.title}」分类由平台管理员纠正：{'、'.join(after_names)}。",
    )
    await notify(
        db, [product.seller_id], "product_edited", "商品分类已被平台纠正",
        f"商品「{product.title}」分类被管理员纠正为：{'、'.join(after_names)}。原因：{body.reason.strip()}",
        link_type="product", link_id=product.id,
    )
    await audit_service.record_event(
        db,
        audit_service.EVENT_ADMIN_PRODUCT_CATEGORY_CORRECT,
        target_type="product",
        target_id=product.id,
        before={"tags": before_names},
        after={"tags": after_names},
    )
    await db.commit()
    return {"detail": "分类纠正完成并通知卖方"}
