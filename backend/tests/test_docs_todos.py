"""D-53 用户待办聚合回归：按当前事项状态派生，已读不办结，管理员无个人待办。"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import DisposalCase, User
from app.models.enums import CaseStatus, CaseType
from tests.conftest import (
    admin_headers,
    create_listed_product,
    make_admin,
    publish_product,
    user_headers,
)

pytestmark = pytest.mark.asyncio

AGREEMENT = {
    "delivery_time": "周日下午三点",
    "delivery_location": "图书馆门口",
    "delivery_method": "当面交付",
    "amount_cents": 2000,
    "payment_method": "支付宝",
    "payment_timing": "当面付清",
}


async def _claimed_trade_case(db, trade_id: int, product_id: int, subject_email: str | None = None) -> int:
    """为管理交易写操作建立合法关联事项并认领（R5；不依赖 A 组 guard 自动找事项）。"""
    admin = await db.scalar(select(User).where(User.role == "admin"))
    subject_id = None
    if subject_email:
        subject_id = await db.scalar(select(User.id).where(User.email == subject_email))
    case = DisposalCase(
        case_type=CaseType.TRADE_DISPUTE.value,
        status=CaseStatus.PROCESSING.value,
        claimed_by_id=admin.id,
        claimed_at=datetime.now(UTC),
        trade_id=trade_id,
        product_id=product_id,
        subject_user_id=subject_id,
        title=f"交易处理：#{trade_id}",
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return case.id


@pytest.fixture
async def setup(client, db):
    await make_admin(db)
    admin_h = await admin_headers(client)
    seller_h = await user_headers(client, "tseller@test.com", "待办卖方")
    buyer_h = await user_headers(client, "tbuyer@test.com", "待办买方")
    return admin_h, seller_h, buyer_h


def _todo(items: list[dict], kind: str) -> dict | None:
    return next((i for i in items if i["kind"] == kind), None)


async def _todos(client, headers: dict) -> dict:
    resp = await client.get("/api/v1/notifications/todos", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _start_trade(client, buyer_h, seller_h, product_id: int) -> int:
    resp = await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product_id})
    assert resp.status_code == 200, resp.text
    trade_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trades/{trade_id}/accept", headers=seller_h)
    assert resp.status_code == 200, resp.text
    return trade_id


async def _read_all_notifications(client, headers: dict) -> None:
    items = (await client.get("/api/v1/notifications", headers=headers)).json()["items"]
    for notice in items:
        resp = await client.post(f"/api/v1/notifications/{notice['id']}/read", headers=headers)
        assert resp.status_code == 200, resp.text


async def test_todo_request_agreement_completion_cancel_dispute(client, setup):
    admin_h, seller_h, buyer_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="待办请求商品")

    # 管理员无个人待办
    assert (await _todos(client, admin_h)) == {"total": 0, "items": []}

    resp = await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]})
    trade_id = resp.json()["id"]

    # 待接受请求只出现在卖方，key 稳定且结构符合契约
    first = await _todos(client, seller_h)
    item = _todo(first["items"], "request_pending")
    assert first["total"] == 1 and item is not None
    assert item["key"] == f"request_pending:{trade_id}"
    assert item["link_type"] == "trade" and item["link_id"] == trade_id
    assert item["action"] == "accept_request"
    second = await _todos(client, seller_h)
    assert second["items"][0]["key"] == item["key"]
    assert (await _todos(client, buyer_h))["total"] == 0

    # 接受后请求待办消失，约定待办转到对方
    resp = await client.post(f"/api/v1/trades/{trade_id}/accept", headers=seller_h)
    assert resp.status_code == 200
    assert _todo((await _todos(client, seller_h))["items"], "request_pending") is None
    resp = await client.post(f"/api/v1/trades/{trade_id}/agreements", headers=seller_h, json=AGREEMENT)
    assert resp.status_code == 200, resp.text
    agreement_id = resp.json()["id"]
    item = _todo((await _todos(client, buyer_h))["items"], "agreement_pending")
    assert item and item["link_type"] == "trade" and item["link_id"] == trade_id
    assert _todo((await _todos(client, seller_h))["items"], "agreement_pending") is None

    resp = await client.post(f"/api/v1/trades/{trade_id}/agreements/{agreement_id}/confirm", headers=buyer_h)
    assert resp.status_code == 200
    assert _todo((await _todos(client, buyer_h))["items"], "agreement_pending") is None

    # 有效约定生效后双方都可独立第一确认，不假定对方先确认（R2）
    seller_before = _todo((await _todos(client, seller_h))["items"], "completion_confirm")
    buyer_before = _todo((await _todos(client, buyer_h))["items"], "completion_confirm")
    assert seller_before and buyer_before
    assert seller_before["action"] == buyer_before["action"] == "confirm_completion"

    # 卖方先确认：本人移出，买方仍保留；通知已读不影响
    resp = await client.post(f"/api/v1/trades/{trade_id}/confirmations", headers=seller_h, json={})
    assert resp.status_code == 200, resp.text
    assert _todo((await _todos(client, seller_h))["items"], "completion_confirm") is None
    item = _todo((await _todos(client, buyer_h))["items"], "completion_confirm")
    assert item and item["action"] == "confirm_completion"
    await _read_all_notifications(client, buyer_h)
    still = _todo((await _todos(client, buyer_h))["items"], "completion_confirm")
    assert still and still["key"] == item["key"]  # 通知已读 ≠ 事项办结

    # 双方确认完成后待办自动消失
    resp = await client.post(f"/api/v1/trades/{trade_id}/confirmations", headers=buyer_h, json={})
    assert resp.status_code == 200, resp.text
    assert _todo((await _todos(client, buyer_h))["items"], "completion_confirm") is None
    assert _todo((await _todos(client, seller_h))["items"], "completion_confirm") is None
    assert (await _todos(client, buyer_h))["total"] == 0

    # 取消申请待对方确认；确认终止后移出
    product2 = await create_listed_product(client, admin_h, seller_h, title="待办取消商品")
    trade2 = await _start_trade(client, buyer_h, seller_h, product2["id"])
    resp = await client.post(f"/api/v1/trades/{trade2}/cancel", headers=seller_h, json={"reason": "临时有事"})
    assert resp.status_code == 200, resp.text
    item = _todo((await _todos(client, buyer_h))["items"], "cancel_pending")
    assert item and item["action"] == "confirm_cancel"
    resp = await client.post(f"/api/v1/trades/{trade2}/cancel/confirm", headers=buyer_h, json={})
    assert resp.status_code == 200, resp.text
    assert _todo((await _todos(client, buyer_h))["items"], "cancel_pending") is None

    # 争议解决确认待对方；双方确认恢复后进行中事项消失
    product3 = await create_listed_product(client, admin_h, seller_h, title="待办争议商品")
    trade3 = await _start_trade(client, buyer_h, seller_h, product3["id"])
    resp = await client.post(f"/api/v1/trades/{trade3}/agreements", headers=seller_h, json=AGREEMENT)
    assert resp.status_code == 200, resp.text
    first_agreement = resp.json()["id"]
    resp = await client.post(f"/api/v1/trades/{trade3}/agreements/{first_agreement}/confirm", headers=buyer_h)
    assert resp.status_code == 200, resp.text
    # 单方已确认后提出变更，随后进入争议：争议中不得把提案错误列为可确认约定
    resp = await client.post(f"/api/v1/trades/{trade3}/agreements", headers=seller_h, json=AGREEMENT)
    assert resp.status_code == 200, resp.text
    resp = await client.post(f"/api/v1/trades/{trade3}/disputes", headers=buyer_h, json={"description": "商品与描述不符"})
    assert resp.status_code == 200, resp.text
    assert _todo((await _todos(client, buyer_h))["items"], "agreement_pending") is None
    resp = await client.post(f"/api/v1/trades/{trade3}/disputes/resolve", headers=buyer_h, json={"reason": "协商解决"})
    assert resp.status_code == 200, resp.text
    item = _todo((await _todos(client, seller_h))["items"], "dispute_resolution")
    assert item and item["link_id"] == trade3 and item["action"] == "confirm_dispute_resolution"
    resp = await client.post(f"/api/v1/trades/{trade3}/disputes/resolve", headers=seller_h, json={"reason": "确认"})
    assert resp.status_code == 200, resp.text
    assert _todo((await _todos(client, seller_h))["items"], "dispute_resolution") is None


async def test_todo_inquiry_unanswered_read_and_frozen_trade_suppression(client, setup, db):
    admin_h, seller_h, buyer_h = setup

    # 待审核商品形成管理问询事项
    inquiry_product = await publish_product(client, seller_h, title="待问询审核商品")
    resp = await client.get("/api/v1/admin/cases?status=pending", headers=admin_h)
    inquiry_case = next(c for c in resp.json() if c.get("product_id") == inquiry_product["id"])
    resp = await client.post(f"/api/v1/admin/cases/{inquiry_case['id']}/claim", headers=admin_h)
    assert resp.status_code == 200
    resp = await client.post(
        f"/api/v1/admin/cases/{inquiry_case['id']}/inquiry",
        headers=admin_h,
        json={"content": "请说明商品来源"},
    )
    assert resp.status_code == 200, resp.text

    item = _todo((await _todos(client, seller_h))["items"], "inquiry_pending")
    assert item and item["link_type"] == "case" and item["link_id"] == inquiry_case["id"]
    assert item["action"] == "submit_statement"
    await _read_all_notifications(client, seller_h)
    item_after_read = _todo((await _todos(client, seller_h))["items"], "inquiry_pending")
    assert item_after_read and item_after_read["key"] == item["key"]

    # 已有本人说明后移出；新问询再次出现
    resp = await client.post(
        f"/api/v1/me/cases/{inquiry_case['id']}/statement", headers=seller_h, json={"content": "自用闲置"}
    )
    assert resp.status_code == 200, resp.text
    assert _todo((await _todos(client, seller_h))["items"], "inquiry_pending") is None
    resp = await client.post(
        f"/api/v1/admin/cases/{inquiry_case['id']}/inquiry",
        headers=admin_h,
        json={"content": "请补充购买凭证"},
    )
    assert resp.status_code == 200, resp.text
    again = _todo((await _todos(client, seller_h))["items"], "inquiry_pending")
    assert again and again["key"] == item["key"]

    # 冻结一笔待接受请求：交易动作待办不列出，但管理沟通仍保留
    trade_product = await create_listed_product(client, admin_h, seller_h, title="冻结待办商品")
    resp = await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": trade_product["id"]})
    trade_id = resp.json()["id"]
    assert _todo((await _todos(client, seller_h))["items"], "request_pending") is not None
    trade_case_id = await _claimed_trade_case(db, trade_id, trade_product["id"], "tbuyer@test.com")
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/freeze",
        headers=admin_h,
        json={"reason": "核查中", "case_id": trade_case_id},
    )
    assert resp.status_code == 200
    frozen_items = (await _todos(client, seller_h))["items"]
    assert _todo(frozen_items, "request_pending") is None
    assert _todo(frozen_items, "inquiry_pending") is not None
    # 解冻后当前请求待办重新出现
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_id}/unfreeze",
        headers=admin_h,
        json={"reason": "核查完毕", "case_id": trade_case_id},
    )
    assert resp.status_code == 200
    assert _todo((await _todos(client, seller_h))["items"], "request_pending") is not None
    # 封禁：交易待接受请求按 D-52 关闭，不再列交易待办；管理问询仍保留
    resp = await client.post(f"/api/v1/admin/users/{inquiry_product['seller_id']}/ban", headers=admin_h, json={"reason": "违规"})
    assert resp.status_code == 200
    banned_items = (await _todos(client, seller_h))["items"]
    assert _todo(banned_items, "request_pending") is None
    assert _todo(banned_items, "inquiry_pending") is not None
    resp = await client.post(f"/api/v1/admin/users/{inquiry_product['seller_id']}/unban", headers=admin_h, json={"lift_reason": "复核完毕"})
    assert resp.status_code == 200
    assert _todo((await _todos(client, seller_h))["items"], "request_pending") is None

    # 无归属的其他用户看不到该事项；管理员始终无个人待办
    other_h = await user_headers(client, "tother@test.com", "无关用户")
    assert (await _todos(client, other_h))["total"] == 0
    assert (await _todos(client, admin_h))["total"] == 0


async def test_todo_global_freeze_suppresses_unrelated_and_counterparty(client, setup, db):
    """R3：冻结是用户级交易限制；本人或对方被任一有效冻结命中时均不提供交易写待办。"""
    admin_h, seller_h, buyer_h = setup
    buyer2_h = await user_headers(client, "tbuyer2@test.com", "第二买方")
    buyer3_h = await user_headers(client, "tbuyer3@test.com", "第三买方")

    # 卖方与买方 A 的进行中交易（冻结来源）
    product_a = await create_listed_product(client, admin_h, seller_h, title="全局冻结交易商品")
    trade_a = await _start_trade(client, buyer_h, seller_h, product_a["id"])

    # 冻结前建立两笔与该冻结无关的待接受请求：
    # B：被冻结卖方作为买方请求 buyer2 的商品；C：buyer3 请求 buyer2 的商品。
    product_b = await create_listed_product(client, admin_h, buyer2_h, title="第二买方商品")
    resp = await client.post("/api/v1/trades/requests", headers=seller_h, json={"product_id": product_b["id"]})
    assert resp.status_code == 200, resp.text
    trade_b = resp.json()["id"]
    product_c = await create_listed_product(client, admin_h, buyer2_h, title="第二买方另一商品")
    resp = await client.post("/api/v1/trades/requests", headers=buyer3_h, json={"product_id": product_c["id"]})
    assert resp.status_code == 200, resp.text
    trade_c = resp.json()["id"]

    buyer2_items = (await _todos(client, buyer2_h))["items"]
    assert {i["link_id"] for i in buyer2_items if i["kind"] == "request_pending"} == {trade_b, trade_c}

    case_a = await _claimed_trade_case(db, trade_a, product_a["id"], "tseller@test.com")
    resp = await client.post(
        f"/api/v1/admin/trades/{trade_a}/freeze",
        headers=admin_h,
        json={"reason": "核查交易", "case_id": case_a},
    )
    assert resp.status_code == 200

    # 被冻结的卖方其全部交易写待办不列出
    assert not [i for i in (await _todos(client, seller_h))["items"] if i["link_type"] == "trade"]
    # buyer2 不是冻结交易一方，但其交易对方（卖方）被冻结：仅该笔待办隐藏
    buyer2_frozen = (await _todos(client, buyer2_h))["items"]
    assert [i["link_id"] for i in buyer2_frozen if i["kind"] == "request_pending"] == [trade_c]
    # buyer3 与冻结用户无关，其待办不受影响（buyer3 是买方，本无接受待办）
    assert (await _todos(client, buyer3_h))["total"] == 0

    resp = await client.post(
        f"/api/v1/admin/trades/{trade_a}/unfreeze",
        headers=admin_h,
        json={"reason": "核查完毕", "case_id": case_a},
    )
    assert resp.status_code == 200
    buyer2_after = (await _todos(client, buyer2_h))["items"]
    assert {i["link_id"] for i in buyer2_after if i["kind"] == "request_pending"} == {trade_b, trade_c}
