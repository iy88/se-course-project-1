"""D-43/D-44/D-45/D-46/D-50 相关后端回归（docs fab152c 合并基线）。"""

from datetime import UTC, datetime

import pytest
from app.kv.base import get_kv
from app.models import DisposalCase, Product, User
from app.models.enums import CaseStatus, CaseType
from sqlalchemy import func, select

from tests.conftest import (
    admin_headers,
    approve_product,
    create_listed_product,
    make_admin,
    publish_product,
    upload_image,
    user_headers,
)

pytestmark = pytest.mark.asyncio


async def _claimed_case(
    db,
    admin_email: str,
    *,
    case_type: CaseType,
    product_id: int | None = None,
    trade_id: int | None = None,
    subject_email: str | None = None,
    title: str = "事项",
) -> int:
    """建立并认领与目标对象相关的合法事项（R5：管理写操作携带真实依据）。"""
    admin = await db.scalar(select(User).where(User.email == admin_email))
    subject_id = None
    if subject_email:
        subject_id = await db.scalar(select(User.id).where(User.email == subject_email))
    case = DisposalCase(
        case_type=case_type.value,
        status=CaseStatus.PROCESSING.value,
        claimed_by_id=admin.id,
        claimed_at=datetime.now(UTC),
        product_id=product_id,
        trade_id=trade_id,
        subject_user_id=subject_id,
        title=title,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return case.id


@pytest.fixture
async def setup(client, db):
    await make_admin(db)
    admin_h = await admin_headers(client)
    seller_h = await user_headers(client, "seller@docs.com", "卖方")
    buyer_h = await user_headers(client, "buyer@docs.com", "买方")
    return admin_h, seller_h, buyer_h


async def _pending_case_id(client, admin_h, product_id: int) -> int:
    resp = await client.get("/api/v1/admin/cases?status=pending", headers=admin_h)
    return next(c["id"] for c in resp.json() if c.get("product_id") == product_id)


async def _accept_trade(client, buyer_h, seller_h, product_id: int) -> int:
    resp = await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product_id})
    assert resp.status_code == 200, resp.text
    trade_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trades/{trade_id}/accept", headers=seller_h)
    assert resp.status_code == 200, resp.text
    return trade_id


# ---------------- D-47 注册前邮箱验证 ----------------


async def test_register_requires_purpose_and_email_bound_single_use_code(client, db):
    # 错误验证码与未验证邮箱不创建账户
    resp = await client.post("/api/v1/auth/register/send-code", json={"email": "Case@Test.com"})
    assert resp.status_code == 200, resp.text
    code = resp.json()["dev_code"]
    assert code

    wrong = "000000" if code != "000000" else "111111"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "case@test.com", "display_name": "用户", "password": "secret123", "code": wrong},
    )
    assert resp.status_code == 400
    assert await db.scalar(select(func.count()).select_from(User).where(User.email == "case@test.com")) == 0

    # 其他邮箱的验证码不能用于本邮箱（用途/邮箱绑定）
    resp = await client.post("/api/v1/auth/register/send-code", json={"email": "other@test.com"})
    other_code = resp.json()["dev_code"]
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "case@test.com", "display_name": "用户", "password": "secret123", "code": other_code},
    )
    assert resp.status_code == 400
    assert await db.scalar(select(func.count()).select_from(User).where(User.email == "case@test.com")) == 0

    # 其他用途（找回密码）的验证码不能用于注册
    resp = await client.post("/api/v1/auth/forgot-password/send-code", json={"email": "case@test.com"})
    reset_code = resp.json()["dev_code"]
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "case@test.com", "display_name": "用户", "password": "secret123", "code": reset_code},
    )
    assert resp.status_code == 400

    # 大小写不同的同一邮箱可以完成注册，持久化统一小写
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "CASE@test.com", "display_name": "用户", "password": "secret123", "code": code},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["email"] == "case@test.com"
    assert resp.json()["user"]["has_frozen_trade"] is False

    # 验证码一次性：已消费的码不能再用于其他邮箱
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "second@test.com", "display_name": "用户", "password": "secret123", "code": code},
    )
    assert resp.status_code == 400
    assert await db.scalar(select(func.count()).select_from(User).where(User.email == "second@test.com")) == 0

    # 过期等价：验证码不存在时不创建账户
    resp = await client.post("/api/v1/auth/register/send-code", json={"email": "expired@test.com"})
    expired_code = resp.json()["dev_code"]
    await get_kv().delete("vcode:register:expired@test.com")
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "expired@test.com", "display_name": "用户", "password": "secret123", "code": expired_code},
    )
    assert resp.status_code == 400
    assert await db.scalar(select(func.count()).select_from(User).where(User.email == "expired@test.com")) == 0

    # 重复邮箱注册仍返回业务拒绝而不是 500
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "case@test.com", "display_name": "另一用户", "password": "secret123", "code": "123456"},
    )
    assert resp.status_code == 400
    assert await db.scalar(select(func.count()).select_from(User).where(User.email == "case@test.com")) == 1


async def test_register_rejects_blank_display_name(client, db):
    resp = await client.post("/api/v1/auth/register/send-code", json={"email": "blank@test.com"})
    code = resp.json()["dev_code"]
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "blank@test.com", "display_name": "   ", "password": "secret123", "code": code},
    )
    assert resp.status_code == 422
    assert await db.scalar(select(func.count()).select_from(User).where(User.email == "blank@test.com")) == 0


async def test_user_out_has_frozen_trade_dynamic(client, setup, db):
    admin_h, seller_h, buyer_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="冻结标记商品")
    trade_id = await _accept_trade(client, buyer_h, seller_h, product["id"])

    resp = await client.get("/api/v1/auth/me", headers=seller_h)
    assert resp.json()["has_frozen_trade"] is False
    trade_case_id = await _claimed_case(
        db, "admin@test.edu", case_type=CaseType.TRADE_DISPUTE,
        product_id=product["id"], trade_id=trade_id, subject_email="buyer@docs.com",
        title="冻结标记交易处理",
    )
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/freeze",
        headers=admin_h,
        json={"reason": "核查订单", "case_id": trade_case_id},
    )
    assert resp.status_code == 200

    resp = await client.get("/api/v1/auth/me", headers=seller_h)
    assert resp.json()["has_frozen_trade"] is True
    resp = await client.post("/api/v1/auth/login", json={"email": "seller@docs.com", "password": "secret123"})
    assert resp.json()["user"]["has_frozen_trade"] is True
    resp = await client.patch("/api/v1/auth/profile", headers=buyer_h, json={"display_name": "新买方名"})
    assert resp.json()["has_frozen_trade"] is True  # 买方也是该冻结交易一方

    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/unfreeze",
        headers=admin_h,
        json={"reason": "核查完毕", "case_id": trade_case_id},
    )
    assert resp.status_code == 200
    resp = await client.get("/api/v1/auth/me", headers=seller_h)
    assert resp.json()["has_frozen_trade"] is False


# ---------------- D-46 待审核编辑、撤回与重提 ----------------


async def test_pending_review_edit_before_and_after_claim_uses_latest_content(client, setup, db):
    admin_h, seller_h, _ = setup
    product = await publish_product(client, seller_h, title="初审标题")
    case_id = await _pending_case_id(client, admin_h, product["id"])

    resp = await client.get(f"/api/v1/products/{product['id']}", headers=seller_h)
    assert resp.json()["status"] == "pending_review"
    assert resp.json()["can_withdraw_review"] is True
    assert resp.json()["can_resubmit"] is False

    # 认领前修改：不发起新审核
    resp = await client.patch(f"/api/v1/products/{product['id']}", headers=seller_h, json={"title": "认领前修改"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending_review"
    assert resp.json()["can_withdraw_review"] is True
    records = (await client.get(f"/api/v1/products/{product['id']}/review-records", headers=seller_h)).json()
    assert len(records) == 1

    # 认领后仍可修改，但不能撤回
    resp = await client.post(f"/api/v1/admin/cases/{case_id}/claim", headers=admin_h)
    assert resp.status_code == 200
    resp = await client.get(f"/api/v1/products/{product['id']}", headers=seller_h)
    assert resp.json()["can_withdraw_review"] is False
    resp = await client.patch(
        f"/api/v1/products/{product['id']}", headers=seller_h, json={"description": "认领后修改的最新描述"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending_review"
    records = (await client.get(f"/api/v1/products/{product['id']}/review-records", headers=seller_h)).json()
    assert len(records) == 1

    # 管理员提交结论时快照最新内容
    resp = await client.post(
        f"/api/v1/admin/products/cases/{case_id}/review", headers=admin_h, json={"result": "approved"}
    )
    assert resp.status_code == 200, resp.text
    records = (await client.get(f"/api/v1/products/{product['id']}/review-records", headers=seller_h)).json()
    assert records[-1]["result"] == "approved"
    product_resp = await client.get(f"/api/v1/products/{product['id']}", headers=seller_h)
    assert product_resp.json()["title"] == "认领前修改"
    # 审核记录快照在提交结论时刷新为最新持久内容
    from app.models import ReviewRecord

    review = await db.scalar(
        select(ReviewRecord).where(ReviewRecord.product_id == product["id"]).order_by(ReviewRecord.id.desc())
    )
    assert review.content_json["title"] == "认领前修改"
    assert review.content_json["description"] == "认领后修改的最新描述"


async def test_withdraw_review_only_before_claim_and_resubmit_paths(client, setup):
    admin_h, seller_h, _ = setup
    product = await publish_product(client, seller_h, title="将撤回商品")
    old_case_id = await _pending_case_id(client, admin_h, product["id"])

    resp = await client.post(f"/api/v1/products/{product['id']}/withdraw-review", headers=seller_h)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "delisted"
    assert resp.json()["can_resubmit"] is True
    assert resp.json()["can_withdraw_review"] is False

    records = (await client.get(f"/api/v1/products/{product['id']}/review-records", headers=seller_h)).json()
    assert records[-1]["result"] == "withdrawn"
    # 旧事项不可再认领或按旧审核通过
    resp = await client.post(f"/api/v1/admin/cases/{old_case_id}/claim", headers=admin_h)
    assert resp.status_code == 409
    resp = await client.post(
        f"/api/v1/admin/products/cases/{old_case_id}/review", headers=admin_h, json={"result": "approved"}
    )
    assert resp.status_code in (403, 409)
    resp = await client.get(f"/api/v1/products/{product['id']}", headers=seller_h)
    assert resp.json()["status"] == "delisted"

    # 撤回后的已下架可重提，形成新审核记录与新事项
    resp = await client.post(
        f"/api/v1/products/{product['id']}/resubmit", headers=seller_h, json={"title": "撤回后重提"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending_review"
    records = (await client.get(f"/api/v1/products/{product['id']}/review-records", headers=seller_h)).json()
    assert len(records) == 2 and records[-1]["result"] == "pending"
    new_case_id = await _pending_case_id(client, admin_h, product["id"])
    assert new_case_id != old_case_id

    # 认领后不能撤回，但可继续修改并由认领人审核
    await client.post(f"/api/v1/admin/cases/{new_case_id}/claim", headers=admin_h)
    resp = await client.post(f"/api/v1/products/{product['id']}/withdraw-review", headers=seller_h)
    assert resp.status_code == 409
    resp = await client.post(
        f"/api/v1/admin/products/cases/{new_case_id}/review", headers=admin_h, json={"result": "approved"}
    )
    assert resp.status_code == 200, resp.text

    # 普通已下架且最近审核通过的商品不得走重提，只能重新上架
    resp = await client.post(f"/api/v1/products/{product['id']}/delist", headers=seller_h)
    assert resp.status_code == 200
    resp = await client.get(f"/api/v1/products/{product['id']}", headers=seller_h)
    assert resp.json()["can_resubmit"] is False
    resp = await client.post(f"/api/v1/products/{product['id']}/resubmit", headers=seller_h, json={})
    assert resp.status_code == 409
    resp = await client.post(f"/api/v1/products/{product['id']}/relist", headers=seller_h)
    assert resp.status_code == 200


async def test_pending_tag_application_can_be_withdrawn(client, setup, db):
    _, seller_h, _ = setup
    resp = await client.post(
        "/api/v1/products",
        headers=seller_h,
        json={
            "title": "新标签待审商品",
            "description": "描述",
            "price_cents": 100,
            "image_keys": [await upload_image(client, seller_h)],
            "tags": [{"new_name": "待撤回标签"}],
        },
    )
    assert resp.status_code == 200, resp.text
    product_id = resp.json()["id"]
    # 卖方可从 ProductOut 枚举当前有效待审标签申请（R11），无需直接读库
    detail = (await client.get(f"/api/v1/products/{product_id}", headers=seller_h)).json()
    assert [a["requested_name"] for a in detail["pending_tag_applications"]] == ["待撤回标签"]
    application_id = detail["pending_tag_applications"][0]["id"]
    resp = await client.patch(
        f"/api/v1/products/{product_id}",
        headers=seller_h,
        json={"withdraw_tag_application_ids": [application_id]},
    )
    assert resp.status_code == 200, resp.text
    detail = (await client.get(f"/api/v1/products/{product_id}", headers=seller_h)).json()
    assert detail["pending_tag_applications"] == []
    from app.models import ProductTagApplication

    application = await db.get(ProductTagApplication, application_id)
    await db.refresh(application)
    assert application.status == "withdrawn"


# ---------------- D-45 已移除别名不再参与识别 ----------------


async def test_removed_category_alias_no_longer_resolves(client, setup, db):
    admin_h, seller_h, _ = setup
    resp = await client.post("/api/v1/categories/1/aliases", headers=admin_h, json={"name": "旧别名"})
    assert resp.status_code == 200, resp.text
    resp = await client.delete("/api/v1/categories/1/aliases/by-name", headers=admin_h, params={"name": "旧别名"})
    assert resp.status_code == 200, resp.text
    categories = (await client.get("/api/v1/categories", headers=seller_h)).json()
    assert "旧别名" not in next(c for c in categories if c["id"] == 1)["aliases"]

    resp = await client.post(
        "/api/v1/products",
        headers=seller_h,
        json={
            "title": "别名移除后商品",
            "description": "描述",
            "price_cents": 100,
            "image_keys": [await upload_image(client, seller_h)],
            "tags": [{"new_name": "旧别名"}],
        },
    )
    assert resp.status_code == 200, resp.text
    # 未命中现行主名/别名集合：按新标签申请处理，而不是关联到原分类
    assert resp.json()["tag_ids"] == [] and resp.json()["tag_names"] == []
    from app.models import ProductTagApplication

    application = await db.scalar(
        select(ProductTagApplication).where(ProductTagApplication.product_id == resp.json()["id"])
    )
    assert application is not None and application.requested_name == "旧别名"


# ---------------- D-43 结束后查看权 ----------------


async def test_ended_request_buyer_keeps_current_detail_and_later_edits(client, setup, db):
    admin_h, seller_h, buyer_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="结束后可看商品")
    resp = await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]})
    assert resp.status_code == 200
    resp = await client.post(f"/api/v1/products/{product['id']}/delist", headers=seller_h)
    assert resp.status_code == 200
    # 请求已关闭，卖方仍可编辑当前内容
    resp = await client.patch(f"/api/v1/products/{product['id']}", headers=seller_h, json={"title": "下架后的新标题"})
    assert resp.status_code == 200, resp.text

    resp = await client.get(f"/api/v1/products/{product['id']}", headers=buyer_h)
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "下架后的新标题"
    assert resp.json()["status"] == "delisted"
    resp = await client.get(f"/api/v1/products/{product['id']}/edit-history", headers=buyer_h)
    assert resp.status_code == 200, resp.text
    assert any(h["after_json"]["title"] == "下架后的新标题" for h in resp.json())
    # 结束后不再收到商品编辑通知
    notices = (await client.get("/api/v1/notifications", headers=buyer_h)).json()["items"]
    assert not any(n["type"] == "product_edited" and n["link_id"] == product["id"] for n in notices)

    # 其他用户仍不可见；展示限制不能被历史关系绕开
    stranger_h = await user_headers(client, "stranger@docs.com", "路人")
    resp = await client.get(f"/api/v1/products/{product['id']}", headers=stranger_h)
    assert resp.status_code == 404
    product_row = await db.get(Product, product["id"])
    product_row.display_restricted = True
    await db.commit()
    resp = await client.get(f"/api/v1/products/{product['id']}", headers=buyer_h)
    assert resp.status_code == 404
    product_row.display_restricted = False
    await db.commit()
    resp = await client.get(f"/api/v1/products/{product['id']}", headers=buyer_h)
    assert resp.status_code == 200


# ---------------- D-44 收藏失效与自动恢复 ----------------


async def test_favorite_validity_recovers_without_deleting_relation(client, setup, db):
    admin_h, seller_h, buyer_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="收藏恢复商品")
    resp = await client.post(f"/api/v1/favorites/{product['id']}", headers=buyer_h)
    assert resp.status_code == 200
    favorite_id = resp.json()["favorite_id"]

    resp = await client.get("/api/v1/favorites", headers=buyer_h)
    item = next(i for i in resp.json() if i["product_id"] == product["id"])
    assert item["valid"] is True and item["title"] == "收藏恢复商品"

    # 下架 → 失效且不泄露内容，但收藏关系保留
    resp = await client.post(f"/api/v1/products/{product['id']}/delist", headers=seller_h)
    assert resp.status_code == 200
    resp = await client.get("/api/v1/favorites", headers=buyer_h)
    item = next(i for i in resp.json() if i["product_id"] == product["id"])
    assert item["valid"] is False and item["title"] is None
    assert item["favorite_id"] == favorite_id
    resp = await client.post(f"/api/v1/products/{product['id']}/relist", headers=seller_h)
    assert resp.status_code == 200
    resp = await client.get("/api/v1/favorites", headers=buyer_h)
    item = next(i for i in resp.json() if i["product_id"] == product["id"])
    assert item["valid"] is True and item["title"] == "收藏恢复商品"

    # 展示限制解除后自动恢复；仍受限时保持失效
    row = await db.get(Product, product["id"])
    row.display_restricted = True
    await db.commit()
    resp = await client.get("/api/v1/favorites", headers=buyer_h)
    assert next(i for i in resp.json() if i["product_id"] == product["id"])["valid"] is False
    row.display_restricted = False
    await db.commit()
    resp = await client.get("/api/v1/favorites", headers=buyer_h)
    assert next(i for i in resp.json() if i["product_id"] == product["id"])["valid"] is True


async def test_favorite_in_transaction_valid_but_history_access_is_not_favorite_validity(client, setup):
    admin_h, seller_h, buyer_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="交易中收藏商品")
    await client.post(f"/api/v1/favorites/{product['id']}", headers=buyer_h)
    trade_id = await _accept_trade(client, buyer_h, seller_h, product["id"])

    resp = await client.get("/api/v1/favorites", headers=buyer_h)
    item = next(i for i in resp.json() if i["product_id"] == product["id"])
    assert item["valid"] is True  # 交易中仍有公开详情资格，收藏保持有效（BR-16）

    # 买方在首次约定前直接取消，交易终止、商品默认下架
    resp = await client.post(f"/api/v1/trades/{trade_id}/cancel", headers=buyer_h, json={})
    assert resp.status_code == 200, resp.text
    resp = await client.get(f"/api/v1/products/{product['id']}", headers=buyer_h)
    assert resp.status_code == 200  # D-43 历史资格仍可看详情
    resp = await client.get("/api/v1/favorites", headers=buyer_h)
    item = next(i for i in resp.json() if i["product_id"] == product["id"])
    assert item["valid"] is False  # 历史详情资格不等于收藏有效
    assert item["title"] is None


# ---------------- D-50 冻结禁发布/下架/上架 ----------------


async def test_frozen_trade_blocks_publish_delist_relist_but_allows_edit(client, setup, db):
    admin_h, seller_h, buyer_h = setup
    locked = await create_listed_product(client, admin_h, seller_h, title="冻结中交易商品")
    other = await create_listed_product(client, admin_h, seller_h, title="冻结期无关商品")
    delisted = await create_listed_product(client, admin_h, seller_h, title="冻结期待上架商品")
    resp = await client.post(f"/api/v1/products/{delisted['id']}/delist", headers=seller_h)
    assert resp.status_code == 200
    trade_id = await _accept_trade(client, buyer_h, seller_h, locked["id"])
    trade_case_id = await _claimed_case(
        db, "admin@test.edu", case_type=CaseType.TRADE_DISPUTE,
        product_id=locked["id"], trade_id=trade_id, subject_email="buyer@docs.com",
        title="冻结期交易处理",
    )

    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/freeze",
        headers=admin_h,
        json={"reason": "核查中", "case_id": trade_case_id},
    )
    assert resp.status_code == 200

    resp = await client.post(
        "/api/v1/products",
        headers=seller_h,
        json={
            "title": "冻结期新商品",
            "description": "描述",
            "price_cents": 100,
            "image_keys": [await upload_image(client, seller_h)],
            "tags": [{"category_id": 1}],
        },
    )
    assert resp.status_code == 403
    resp = await client.post(f"/api/v1/products/{other['id']}/delist", headers=seller_h)
    assert resp.status_code == 403
    resp = await client.post(f"/api/v1/products/{delisted['id']}/relist", headers=seller_h)
    assert resp.status_code == 403
    # 无关商品合规编辑仍允许；冻结方收藏操作不被无关限制
    resp = await client.patch(f"/api/v1/products/{other['id']}", headers=seller_h, json={"price_cents": 4321})
    assert resp.status_code == 200, resp.text
    resp = await client.post(f"/api/v1/favorites/{other['id']}", headers=buyer_h)
    assert resp.status_code == 200

    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/unfreeze",
        headers=admin_h,
        json={"reason": "核查完毕", "case_id": trade_case_id},
    )
    assert resp.status_code == 200
    resp = await client.post(f"/api/v1/products/{other['id']}/delist", headers=seller_h)
    assert resp.status_code == 200
    resp = await client.post(f"/api/v1/products/{delisted['id']}/relist", headers=seller_h)
    assert resp.status_code == 200


async def test_ban_write_priority_over_freeze(client, setup, db):
    admin_h, seller_h, buyer_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="封禁优先级商品")
    trade_id = await _accept_trade(client, buyer_h, seller_h, product["id"])
    key = await upload_image(client, seller_h)
    trade_case_id = await _claimed_case(
        db, "admin@test.edu", case_type=CaseType.TRADE_DISPUTE,
        product_id=product["id"], trade_id=trade_id, subject_email="buyer@docs.com",
        title="封禁优先级交易处理",
    )
    await client.post(
        f"/api/v1/admin/trades/{trade_id}/freeze",
        headers=admin_h,
        json={"reason": "核查中", "case_id": trade_case_id},
    )
    resp = await client.post(f"/api/v1/admin/users/{product['seller_id']}/ban", headers=admin_h, json={"reason": "违规"})
    assert resp.status_code == 200
    resp = await client.post(
        "/api/v1/products",
        headers=seller_h,
        json={
            "title": "封禁期新商品",
            "description": "描述",
            "price_cents": 100,
            "image_keys": [key],
            "tags": [{"category_id": 1}],
        },
    )
    assert resp.status_code == 403


# ---------------- R6/D-45 分类名称与停用标签 ----------------


async def test_category_name_filter_strict_and_all_labels_match(client, setup):
    admin_h, seller_h, buyer_h = setup
    resp = await client.post(
        "/api/v1/products",
        headers=seller_h,
        json={
            "title": "双标签商品",
            "description": "描述",
            "price_cents": 100,
            "image_keys": [await upload_image(client, seller_h)],
            "tags": [{"category_id": 1}, {"category_id": 2}],
        },
    )
    assert resp.status_code == 200, resp.text
    both_id = resp.json()["id"]
    await approve_product(client, admin_h, both_id)
    one = await create_listed_product(client, admin_h, seller_h, title="单标签商品")

    # 主名解析：多标签“全部匹配”，category_names 与 category_ids 等价
    resp = await client.get(
        "/api/v1/products/search", headers=buyer_h, params=[("category_names", "教材书籍")]
    )
    assert resp.status_code == 200, resp.text
    assert {i["id"] for i in resp.json()["items"]} == {both_id, one["id"]}

    # 活跃别名解析到同一分类
    resp = await client.post("/api/v1/categories/1/aliases", headers=admin_h, json={"name": "课本"})
    assert resp.status_code == 200, resp.text
    resp = await client.get(
        "/api/v1/products/search", headers=buyer_h, params=[("category_names", "课本")]
    )
    assert {i["id"] for i in resp.json()["items"]} == {both_id, one["id"]}

    # 移除别名后严格无匹配，不得忽略未知名称返回全部
    resp = await client.delete(
        "/api/v1/categories/1/aliases/by-name", headers=admin_h, params={"name": "课本"}
    )
    assert resp.status_code == 200, resp.text
    resp = await client.get(
        "/api/v1/products/search", headers=buyer_h, params=[("category_names", "课本")]
    )
    assert resp.status_code == 200 and resp.json()["total"] == 0 and resp.json()["items"] == []
    assert resp.json()["message"] == "无匹配商品"

    # 任意未知名称同样导致无匹配
    resp = await client.get(
        "/api/v1/products/search", headers=buyer_h, params=[("category_names", "从未存在")]
    )
    assert resp.status_code == 200 and resp.json()["total"] == 0

    # category_ids 多标签全部匹配
    resp = await client.get(
        "/api/v1/products/search",
        headers=buyer_h,
        params=[("category_ids", 1), ("category_ids", 2)],
    )
    assert {i["id"] for i in resp.json()["items"]} == {both_id}

    # ids 与 names 同时给出时合并为“全部标签匹配”，不因名称解析忽略 ids
    resp = await client.get(
        "/api/v1/products/search",
        headers=buyer_h,
        params=[("category_ids", 1), ("category_names", "电子产品")],
    )
    assert {i["id"] for i in resp.json()["items"]} == {both_id}


async def test_disabled_category_not_selectable_and_alias_conflicts(client, setup):
    admin_h, seller_h, buyer_h = setup
    historical = await publish_product(client, seller_h, title="停用前商品", category_id=3)
    await approve_product(client, admin_h, historical["id"])

    resp = await client.patch("/api/v1/categories/3", headers=admin_h, json={"status": "disabled"})
    assert resp.status_code == 200, resp.text

    # 停用分类不可被新发布选择，也不得通过旧主名解析为新标签绕过
    resp = await client.post(
        "/api/v1/products",
        headers=seller_h,
        json={
            "title": "选择停用标签",
            "description": "描述",
            "price_cents": 100,
            "image_keys": [await upload_image(client, seller_h)],
            "tags": [{"category_id": 3}],
        },
    )
    assert resp.status_code == 400
    resp = await client.post(
        "/api/v1/products",
        headers=seller_h,
        json={
            "title": "停用标签主名新申请",
            "description": "描述",
            "price_cents": 100,
            "image_keys": [await upload_image(client, seller_h)],
            "tags": [{"new_name": "生活用品"}],
        },
    )
    assert resp.status_code == 400

    # 停用标签的历史关联保留，且按当前名称仍可被检索识别
    detail = (await client.get(f"/api/v1/products/{historical['id']}", headers=seller_h)).json()
    assert "生活用品" in detail["tag_names"]
    resp = await client.get(
        "/api/v1/products/search", headers=buyer_h, params=[("category_names", "生活用品")]
    )
    assert resp.status_code == 200
    assert historical["id"] in {i["id"] for i in resp.json()["items"]}

    # 别名不得与其他分类当前主名冲突
    resp = await client.post("/api/v1/categories/1/aliases", headers=admin_h, json={"name": "电子产品"})
    assert resp.status_code == 400
    resp = await client.post("/api/v1/categories/1/aliases", headers=admin_h, json={"name": "生活用品"})
    assert resp.status_code == 400

    # 活跃别名不得重复；移除后可由其他分类重新使用
    resp = await client.post("/api/v1/categories/1/aliases", headers=admin_h, json={"name": "别名X"})
    assert resp.status_code == 200, resp.text
    resp = await client.post("/api/v1/categories/2/aliases", headers=admin_h, json={"name": "别名X"})
    assert resp.status_code == 400
    resp = await client.delete(
        "/api/v1/categories/1/aliases/by-name", headers=admin_h, params={"name": "别名X"}
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post("/api/v1/categories/2/aliases", headers=admin_h, json={"name": "别名X"})
    assert resp.status_code == 200, resp.text

    # 改主名也不得与其他分类当前主名冲突（含停用未删除分类）
    resp = await client.patch("/api/v1/categories/2", headers=admin_h, json={"name": "生活用品"})
    assert resp.status_code == 400


# ---------------- R8/R11 完整待审标签链 ----------------


async def test_pending_tag_applications_visibility_and_review_rejects_stale(client, setup, db):
    admin_h, seller_h, buyer_h = setup
    resp = await client.post(
        "/api/v1/products",
        headers=seller_h,
        json={
            "title": "待审标签链商品",
            "description": "描述",
            "price_cents": 100,
            "image_keys": [await upload_image(client, seller_h)],
            "tags": [{"new_name": "待审甲"}, {"new_name": "待审乙"}],
        },
    )
    assert resp.status_code == 200, resp.text
    product_id = resp.json()["id"]
    detail = (await client.get(f"/api/v1/products/{product_id}", headers=seller_h)).json()
    pending = {a["requested_name"]: a["id"] for a in detail["pending_tag_applications"]}
    assert set(pending) == {"待审甲", "待审乙"}
    app_a, app_b = pending["待审甲"], pending["待审乙"]

    # 另一商品的标签申请，不得被本商品审核批准
    resp = await client.post(
        "/api/v1/products",
        headers=seller_h,
        json={
            "title": "他人标签商品",
            "description": "描述",
            "price_cents": 100,
            "image_keys": [await upload_image(client, seller_h)],
            "tags": [{"new_name": "他人标签"}],
        },
    )
    other_product_id = resp.json()["id"]
    other_detail = (await client.get(f"/api/v1/products/{other_product_id}", headers=seller_h)).json()
    other_app_id = other_detail["pending_tag_applications"][0]["id"]

    case_id = await _pending_case_id(client, admin_h, product_id)
    resp = await client.post(f"/api/v1/admin/cases/{case_id}/claim", headers=admin_h)
    assert resp.status_code == 200

    # 认领后仍可修改分类并撤回待审标签申请
    resp = await client.patch(
        f"/api/v1/products/{product_id}",
        headers=seller_h,
        json={"category_ids": [2], "withdraw_tag_application_ids": [app_a]},
    )
    assert resp.status_code == 200, resp.text
    assert [a["id"] for a in resp.json()["pending_tag_applications"]] == [app_b]

    # 不得借撤回接口移除其他商品或已撤回的申请
    resp = await client.patch(
        f"/api/v1/products/{product_id}",
        headers=seller_h,
        json={"withdraw_tag_application_ids": [other_app_id]},
    )
    assert resp.status_code == 400
    resp = await client.patch(
        f"/api/v1/products/{product_id}",
        headers=seller_h,
        json={"withdraw_tag_application_ids": [app_a]},
    )
    assert resp.status_code == 400

    # 已撤回/已处理、其他商品及重复决定均明确拒绝，不得忽略或批准旧申请
    resp = await client.post(
        f"/api/v1/admin/products/cases/{case_id}/review",
        headers=admin_h,
        json={"result": "approved", "tag_decisions": [{"application_id": app_a, "decision": "approve_new"}]},
    )
    assert resp.status_code == 400
    resp = await client.post(
        f"/api/v1/admin/products/cases/{case_id}/review",
        headers=admin_h,
        json={"result": "approved", "tag_decisions": [{"application_id": other_app_id, "decision": "approve_new"}]},
    )
    assert resp.status_code == 400
    resp = await client.post(
        f"/api/v1/admin/products/cases/{case_id}/review",
        headers=admin_h,
        json={
            "result": "approved",
            "tag_decisions": [
                {"application_id": app_b, "decision": "approve_new"},
                {"application_id": app_b, "decision": "approve_new"},
            ],
        },
    )
    assert resp.status_code == 400

    # 审核依据提交时最新商品内容，有效 pending 标签可批准
    resp = await client.patch(
        f"/api/v1/products/{product_id}", headers=seller_h, json={"title": "审核时最新标题"}
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/admin/products/cases/{case_id}/review",
        headers=admin_h,
        json={"result": "approved", "tag_decisions": [{"application_id": app_b, "decision": "approve_new"}]},
    )
    assert resp.status_code == 200, resp.text
    detail = (await client.get(f"/api/v1/products/{product_id}", headers=seller_h)).json()
    assert detail["status"] == "listed"
    assert "电子产品" in detail["tag_names"] and "待审乙" in detail["tag_names"]
    assert detail["pending_tag_applications"] == []

    from app.models import ProductTagApplication, ReviewRecord

    app_a_row = await db.get(ProductTagApplication, app_a)
    app_b_row = await db.get(ProductTagApplication, app_b)
    await db.refresh(app_a_row)
    await db.refresh(app_b_row)
    assert app_a_row.status == "withdrawn" and app_b_row.status == "approved_new"
    review = await db.scalar(
        select(ReviewRecord).where(ReviewRecord.product_id == product_id).order_by(ReviewRecord.id.desc())
    )
    assert review.content_json["title"] == "审核时最新标题"

    # 他人查看 ProductOut 不泄露卖方待审申请
    other_pending = ProductTagApplication(product_id=product_id, requested_name="不应外泄申请")
    db.add(other_pending)
    await db.commit()
    buyer_detail = (await client.get(f"/api/v1/products/{product_id}", headers=buyer_h)).json()
    assert buyer_detail["pending_tag_applications"] == []
    seller_detail = (await client.get(f"/api/v1/products/{product_id}", headers=seller_h)).json()
    assert "不应外泄申请" in [a["requested_name"] for a in seller_detail["pending_tag_applications"]]


async def test_frozen_trade_does_not_block_pending_withdraw_or_resubmit(client, setup, db):
    """contracts15：既有待审撤回/重提不因交易冻结新增禁令；封禁仍禁写。"""
    admin_h, seller_h, buyer_h = setup
    other = await create_listed_product(client, admin_h, seller_h, title="冻结期其他商品")
    product = await publish_product(client, seller_h, title="冻结期待审商品")
    trade_id = await _accept_trade(client, buyer_h, seller_h, other["id"])
    trade_case_id = await _claimed_case(
        db, "admin@test.edu", case_type=CaseType.TRADE_DISPUTE,
        product_id=other["id"], trade_id=trade_id, subject_email="buyer@docs.com",
        title="冻结期待审交易",
    )
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/freeze",
        headers=admin_h,
        json={"reason": "核查中", "case_id": trade_case_id},
    )
    assert resp.status_code == 200

    resp = await client.post(f"/api/v1/products/{product['id']}/withdraw-review", headers=seller_h)
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/products/{product['id']}/resubmit", headers=seller_h, json={"title": "冻结期重提"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending_review"

    # 封禁仍优先禁止业务写操作
    resp = await client.post(
        f"/api/v1/admin/users/{product['seller_id']}/ban", headers=admin_h, json={"reason": "违规"}
    )
    assert resp.status_code == 200
    resp = await client.post(f"/api/v1/products/{product['id']}/withdraw-review", headers=seller_h)
    assert resp.status_code == 403


# ---------------- R7/TR-10 展示限制解除 ----------------


async def test_restore_display_requires_source_case_and_preserves_lifecycle(client, setup, db):
    admin_h, seller_h, buyer_h = setup
    await make_admin(db, "admin2@test.edu")
    admin2_h = await admin_headers(client, "admin2@test.edu")
    from app.services import moderation

    product = await create_listed_product(client, admin_h, seller_h, title="展示限制解除商品")
    resp = await client.post(f"/api/v1/favorites/{product['id']}", headers=buyer_h)
    assert resp.status_code == 200
    case_id = await _claimed_case(
        db, "admin@test.edu", case_type=CaseType.REPORT,
        product_id=product["id"], subject_email="seller@docs.com", title="商品展示违规",
    )
    row = await db.get(Product, product["id"])
    await moderation.restrict_product_display(db, row, "违规展示", case_id)
    await db.commit()

    resp = await client.get("/api/v1/favorites", headers=buyer_h)
    assert next(i for i in resp.json() if i["product_id"] == product["id"])["valid"] is False

    # 非认领管理员、不同来源事项均不得解除
    resp = await client.post(
        f"/api/v1/admin/products/{product['id']}/restore-display",
        headers=admin2_h,
        json={"case_id": case_id, "reason": "复核解除"},
    )
    assert resp.status_code == 403
    other_product = await create_listed_product(client, admin_h, seller_h, title="无关商品")
    other_case_id = await _claimed_case(
        db, "admin@test.edu", case_type=CaseType.REPORT,
        product_id=other_product["id"], subject_email="seller@docs.com", title="其他展示事项",
    )
    resp = await client.post(
        f"/api/v1/admin/products/{product['id']}/restore-display",
        headers=admin_h,
        json={"case_id": other_case_id, "reason": "错误事项"},
    )
    assert resp.status_code == 409

    # 仍有效封禁时不得单独解除展示限制
    resp = await client.post(
        f"/api/v1/admin/users/{product['seller_id']}/ban", headers=admin_h, json={"reason": "违规"}
    )
    assert resp.status_code == 200
    resp = await client.post(
        f"/api/v1/admin/products/{product['id']}/restore-display",
        headers=admin_h,
        json={"case_id": case_id, "reason": "封禁中解除"},
    )
    assert resp.status_code == 409
    resp = await client.post(
        f"/api/v1/admin/users/{product['seller_id']}/unban", headers=admin_h, json={"lift_reason": "复核完毕"}
    )
    assert resp.status_code == 200

    # 合法解除：仅恢复展示资格，收藏自动恢复，留执行人/时间/原因与前后限制
    resp = await client.post(
        f"/api/v1/admin/products/{product['id']}/restore-display",
        headers=admin_h,
        json={"case_id": case_id, "reason": "复核后解除展示限制"},
    )
    assert resp.status_code == 200, resp.text
    detail = (await client.get(f"/api/v1/products/{product['id']}", headers=seller_h)).json()
    assert detail["display_restricted"] is False
    assert detail["status"] == "listed"  # 状态未被改动
    resp = await client.get("/api/v1/favorites", headers=buyer_h)
    assert next(i for i in resp.json() if i["product_id"] == product["id"])["valid"] is True

    from app.models import ProductEditHistory

    history = await db.scalar(
        select(ProductEditHistory).where(
            ProductEditHistory.product_id == product["id"],
            ProductEditHistory.edit_type == "display_restore",
        )
    )
    admin = await db.scalar(select(User).where(User.email == "admin@test.edu"))
    assert history and history.editor_id == admin.id
    assert history.reason == "复核后解除展示限制"
    assert history.before_json["display_restricted"] is True
    assert history.after_json["display_restricted"] is False
    notices = (await client.get("/api/v1/notifications", headers=seller_h)).json()["items"]
    assert any(
        n["type"] == "disposal" and n["link_id"] == product["id"] and "公开访问限制已解除" in n["title"]
        for n in notices
    )

    # 交易中商品：展示限制解除不改生命周期、不解冻交易；合格未结束买方获通知且收藏仍有效
    locked_product = await create_listed_product(client, admin_h, seller_h, title="交易中展示限制商品")
    await client.post(f"/api/v1/favorites/{locked_product['id']}", headers=buyer_h)
    trade_id = await _accept_trade(client, buyer_h, seller_h, locked_product["id"])
    trade_case_id = await _claimed_case(
        db, "admin@test.edu", case_type=CaseType.TRADE_DISPUTE,
        product_id=locked_product["id"], trade_id=trade_id, subject_email="buyer@docs.com",
        title="交易中展示限制处理",
    )
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/freeze",
        headers=admin_h,
        json={"reason": "核查中", "case_id": trade_case_id},
    )
    assert resp.status_code == 200
    locked_case_id = await _claimed_case(
        db, "admin@test.edu", case_type=CaseType.REPORT,
        product_id=locked_product["id"], subject_email="seller@docs.com", title="交易中展示违规",
    )
    locked_row = await db.get(Product, locked_product["id"])
    await moderation.restrict_product_display(db, locked_row, "违规展示", locked_case_id)
    await db.commit()
    resp = await client.post(
        f"/api/v1/admin/products/{locked_product['id']}/restore-display",
        headers=admin_h,
        json={"case_id": locked_case_id, "reason": "复核解除"},
    )
    assert resp.status_code == 200, resp.text
    await db.refresh(locked_row)
    from app.models import Trade

    trade_row = await db.get(Trade, trade_id)
    await db.refresh(trade_row)
    assert locked_row.display_restricted is False
    assert locked_row.status == "in_transaction"  # 不把交易中/已下架状态改为在售
    assert trade_row.frozen is True  # 不解除交易冻结
    resp = await client.get("/api/v1/favorites", headers=buyer_h)
    assert next(i for i in resp.json() if i["product_id"] == locked_product["id"])["valid"] is True
    buyer_notices = (await client.get("/api/v1/notifications", headers=buyer_h)).json()["items"]
    assert any(
        n["link_id"] == locked_product["id"] and "公开访问限制已解除" in n["title"]
        for n in buyer_notices
    )
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/unfreeze",
        headers=admin_h,
        json={"reason": "核查完毕", "case_id": trade_case_id},
    )
    assert resp.status_code == 200

    # 已下架商品：解除展示限制后仍为已下架，收藏保持失效
    delisted = await create_listed_product(client, admin_h, seller_h, title="已下架展示限制商品")
    await client.post(f"/api/v1/favorites/{delisted['id']}", headers=buyer_h)
    resp = await client.post(f"/api/v1/products/{delisted['id']}/delist", headers=seller_h)
    assert resp.status_code == 200
    delisted_case_id = await _claimed_case(
        db, "admin@test.edu", case_type=CaseType.REPORT,
        product_id=delisted["id"], subject_email="seller@docs.com", title="已下架展示违规",
    )
    delisted_row = await db.get(Product, delisted["id"])
    await moderation.restrict_product_display(db, delisted_row, "违规展示", delisted_case_id)
    await db.commit()
    resp = await client.post(
        f"/api/v1/admin/products/{delisted['id']}/restore-display",
        headers=admin_h,
        json={"case_id": delisted_case_id, "reason": "复核解除"},
    )
    assert resp.status_code == 200, resp.text
    await db.refresh(delisted_row)
    assert delisted_row.display_restricted is False
    assert delisted_row.status == "delisted"  # 不把已下架变在售
    resp = await client.get("/api/v1/favorites", headers=buyer_h)
    assert next(i for i in resp.json() if i["product_id"] == delisted["id"])["valid"] is False
