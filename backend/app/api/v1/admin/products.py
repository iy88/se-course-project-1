"""管理员商品审核与分类纠正（BR-10/11/13、TR-01—TR-03）。"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

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
from app.services import cases as case_service
from app.services import products as product_service
from app.services.cases import ensure_claimant
from app.services.notifications import notify

router = APIRouter(prefix="/admin/products", tags=["admin-products"])


class TagDecisionIn(BaseModel):
    application_id: int
    decision: str = Field(pattern="^(approve_new|map_alias|reject)$")
    category_id: int | None = None  # map_alias 时指向已有分类


class ReviewDecisionIn(BaseModel):
    result: str = Field(pattern="^(approved|rejected)$")
    reason: str | None = Field(default=None, max_length=500)  # 不通过原因（含退回补充）
    tag_decisions: list[TagDecisionIn] = []


class CategoryCorrectionIn(BaseModel):
    category_ids: list[int] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


class RestoreDisplayIn(BaseModel):
    case_id: int
    reason: str = Field(min_length=1, max_length=500)


@router.post("/cases/{case_id}/review")
async def review_product(case_id: int, body: ReviewDecisionIn, admin: CurrentAdmin, db: DbSession) -> dict:
    """审核当次内容（TR-01/02）：通过联动展示与标签批准；不通过记录原因并通知。"""
    case = await db.get(DisposalCase, case_id)
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "事项不存在")
    if case.status == CaseStatus.DISPOSED.value:
        # 撤回/已处置事项不能按旧 id 再审，历史保留
        raise HTTPException(status.HTTP_409_CONFLICT, "该事项已处置")
    await ensure_claimant(case, admin.id)
    if case.case_type != CaseType.PRODUCT_REVIEW.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该事项不是商品审核事项")
    product = await db.get(Product, case.product_id)
    review = await db.scalar(
        select(ReviewRecord).where(ReviewRecord.case_id == case.id).order_by(ReviewRecord.id.desc()).limit(1)
    )
    if not product or not review:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "审核事项数据不完整")
    if product.status != ProductStatus.PENDING_REVIEW.value or review.result != ReviewResult.PENDING.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "商品当前不在待审核状态")
    # D-46：认领前后卖方均可修改，审核结论以提交结论时的最新内容为准并刷新快照
    review.content_json = await product_service.snapshot_content(db, product)

    apps = (
        await db.execute(
            select(ProductTagApplication).where(
                ProductTagApplication.product_id == product.id, ProductTagApplication.status == "pending"
            )
        )
    ).scalars().all()
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

    if body.result == "approved":
        # 标签随商品通过生效（4.16）
        approved_tag_ids = {t.id for t in await product_service.load_product_tags(db, product.id)}
        for app in apps:
            decision = decisions.get(app.id)
            if decision is None or decision.decision == "reject":
                app.status = "rejected"
                app.decided_at = case_service.now_utc()
                continue
            if decision.decision == "approve_new":
                exists = await db.scalar(
                    select(Category).where(Category.name == app.requested_name, Category.deleted_at.is_(None))
                )
                if exists:
                    category = exists
                else:
                    # 新主名不得与现有活跃别名冲突；此类名称应走别名映射。
                    alias_conflict = await db.scalar(
                        select(CategoryAlias).where(
                            CategoryAlias.name == app.requested_name, CategoryAlias.removed_at.is_(None)
                        )
                    )
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
                approved_tag_ids.add(category.id)
            else:  # map_alias：同义名称作为已有分类别名，商品关联原分类
                target = await db.get(Category, decision.category_id)
                if not target or target.deleted_at is not None:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"别名映射目标分类不存在（申请 {app.id}）")
                if target.status != "active":
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"别名映射目标分类已停用（申请 {app.id}）")
                # 别名不得与其他分类主名或活跃别名冲突（4.16）。
                principal_conflict = await db.scalar(
                    select(Category).where(
                        Category.name == app.requested_name,
                        Category.deleted_at.is_(None),
                        Category.id != target.id,
                    )
                )
                alias_exists = await db.scalar(
                    select(CategoryAlias).where(
                        CategoryAlias.name == app.requested_name, CategoryAlias.removed_at.is_(None)
                    )
                )
                if principal_conflict or (alias_exists and alias_exists.category_id != target.id):
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST, f"标签名称已被其他分类使用（申请 {app.id}）"
                    )
                if not alias_exists and app.requested_name != target.name:
                    db.add(CategoryAlias(category_id=target.id, name=app.requested_name, created_by_id=admin.id))
                app.status = "approved_alias"
                app.resolved_category_id = target.id
                approved_tag_ids.add(target.id)
            app.decided_at = case_service.now_utc()
        if not approved_tag_ids:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "商品通过时须至少关联一个获认可标签（请处理标签申请或保留已有标签）",
            )
        await db.execute(delete(ProductTag).where(ProductTag.product_id == product.id))
        for cid in approved_tag_ids:
            db.add(ProductTag(product_id=product.id, category_id=cid))
        product.status = ProductStatus.LISTED.value
        product.listed_at = case_service.now_utc()
        product.reject_reason = None
        review.reviewer_id = admin.id
        review.result = ReviewResult.APPROVED.value
        review.reason = None
        review.reviewed_at = case_service.now_utc()
        await case_service.dispose_case(db, case, conclusion="审核通过", basis="依据当前禁发范围审核通过")
        await notify(
            db, [product.seller_id], "review_result", "商品审核通过",
            f"商品「{product.title}」已通过审核并公开，可被检索与请求。通过仅代表审核结果，不代表成交。",
            link_type="product", link_id=product.id,
        )
        message = "审核通过，商品已公开"
    else:
        reason = (body.reason or "").strip()
        if not reason:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不通过时须记录拒绝原因")
        for app in apps:
            app.status = "rejected"
            app.decided_at = case_service.now_utc()
        product.status = ProductStatus.REJECTED.value
        product.reject_reason = reason
        review.reviewer_id = admin.id
        review.result = ReviewResult.REJECTED.value
        review.reason = reason
        review.reviewed_at = case_service.now_utc()
        await case_service.dispose_case(db, case, conclusion="审核未通过", reason=reason, basis="依据当前禁发范围审核未通过")
        await notify(
            db, [product.seller_id], "review_result", "商品审核未通过",
            f"商品「{product.title}」未通过审核，原因：{reason}。可查看商品并修改后重新提交。",
            link_type="product", link_id=product.id,
        )
        message = "审核未通过，已通知发布者"

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
    active_ban = await db.scalar(
        select(AccountRestriction.id).where(
            AccountRestriction.user_id == seller.id,
            AccountRestriction.type == "ban",
            AccountRestriction.status == RestrictionStatus.ACTIVE.value,
        )
    )
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
        f"商品「{product.title}」的公开访问限制已由管理员解除，原因：{reason}。"
        "商品原生命周期状态、交易锁单及冻结不变。",
        link_type="product",
        link_id=product.id,
    )
    await product_service.notify_open_request_buyers(
        db,
        product,
        "关注的商品公开访问限制已解除",
        f"您关注的商品「{product.title}」公开访问限制已解除，可按商品当前状态查看。",
    )
    await db.commit()
    return {"detail": "展示限制已解除；生命周期与交易限制保持不变"}


@router.post("/{product_id}/correct-category")
async def correct_category(product_id: int, body: CategoryCorrectionIn, admin: CurrentAdmin, db: DbSession) -> dict:
    """管理员有依据纠正分类（BR-11）：留前后内容、原因、操作人与时间，通知卖方。"""
    product = await db.get(Product, product_id)
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    categories = []
    for cid in set(body.category_ids):
        category = await db.get(Category, cid)
        if not category or category.deleted_at is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"分类不存在：{cid}")
        categories.append(category)
    before = await product_service.load_product_tags(db, product.id)
    before_names = [t.name for t in before]
    await db.execute(delete(ProductTag).where(ProductTag.product_id == product.id))
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
    await db.commit()
    return {"detail": "分类纠正完成并通知卖方"}
