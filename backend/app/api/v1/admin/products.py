"""管理员商品审核与分类纠正（BR-10/11/13、TR-01—TR-03）。"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentAdmin, DbSession
from app.models import DisposalCase, Product, ProductTag, ProductTagApplication, Category, CategoryAlias, ReviewRecord
from app.models.enums import CaseStatus, CaseType, ProductStatus, ReviewResult
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


@router.post("/cases/{case_id}/review")
async def review_product(case_id: int, body: ReviewDecisionIn, admin: CurrentAdmin, db: DbSession) -> dict:
    """审核当次内容（TR-01/02）：通过联动展示与标签批准；不通过记录原因并通知。"""
    case = await db.get(DisposalCase, case_id)
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "事项不存在")
    await ensure_claimant(case, admin.id)
    if case.case_type != CaseType.PRODUCT_REVIEW.value:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该事项不是商品审核事项")
    if case.status == CaseStatus.DISPOSED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "该事项已处置")
    product = await db.get(Product, case.product_id)
    review = await db.scalar(
        select(ReviewRecord).where(ReviewRecord.case_id == case.id).order_by(ReviewRecord.id.desc()).limit(1)
    )
    if not product or not review:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "审核事项数据不完整")
    if product.status != ProductStatus.PENDING_REVIEW.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "商品当前不在待审核状态")

    apps = (
        await db.execute(
            select(ProductTagApplication).where(
                ProductTagApplication.product_id == product.id, ProductTagApplication.status == "pending"
            )
        )
    ).scalars().all()
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
                category = exists or Category(name=app.requested_name, created_by_id=admin.id)
                if not exists:
                    db.add(category)
                    await db.flush()
                app.status = "approved_new"
                app.resolved_category_id = category.id
                approved_tag_ids.add(category.id)
            else:  # map_alias：同义名称作为已有分类别名，商品关联原分类
                target = await db.get(Category, decision.category_id)
                if not target or target.deleted_at is not None:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, f"别名映射目标分类不存在（申请 {app.id}）")
                alias_exists = await db.scalar(
                    select(CategoryAlias).where(CategoryAlias.name == app.requested_name, CategoryAlias.removed_at.is_(None))
                )
                if not alias_exists:
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
        await db.execute(ProductTag.__table__.delete().where(ProductTag.product_id == product.id))
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
    await db.execute(ProductTag.__table__.delete().where(ProductTag.product_id == product.id))
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
