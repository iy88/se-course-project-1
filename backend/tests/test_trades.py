"""交易状态机关键规则测试（FR-05/06/09；BR-01—09、4.15）。"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Trade
from tests.conftest import create_listed_product, make_admin, user_headers

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def setup(client, db):
    await make_admin(db)
    admin_h = await admin_headers_local(client)
    seller_h = await user_headers(client, "seller@t.com", "卖方")
    buyer1_h = await user_headers(client, "buyer1@t.com", "买方一")
    buyer2_h = await user_headers(client, "buyer2@t.com", "买方二")
    return admin_h, seller_h, buyer1_h, buyer2_h


async def admin_headers_local(client):
    from tests.conftest import login

    return {"Authorization": f"Bearer {await login(client, 'admin@test.edu', 'admin123456')}"}


async def test_request_lifecycle(client, setup):
    """请求→接受锁单→其余关闭（DT-01）；撤回与拒绝分支。"""
    admin_h, seller_h, buyer1_h, buyer2_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="多请求商品")
    # 两个买方分别请求
    r1 = (await client.post("/api/v1/trades/requests", headers=buyer1_h, json={"product_id": product["id"]})).json()
    r2 = (await client.post("/api/v1/trades/requests", headers=buyer2_h, json={"product_id": product["id"]})).json()
    # 同一买方重复请求返回已有结果（BR-02）
    r1_dup = (await client.post("/api/v1/trades/requests", headers=buyer1_h, json={"product_id": product["id"]})).json()
    assert r1_dup["id"] == r1["id"] and r1_dup.get("existing") is True
    # 不能购买本人商品（BR-02）
    resp = await client.post("/api/v1/trades/requests", headers=seller_h, json={"product_id": product["id"]})
    assert resp.status_code == 400
    # 接受 r1：锁单 + r2 关闭
    await client.post(f"/api/v1/trades/{r1['id']}/accept", headers=seller_h)
    t1 = (await client.get(f"/api/v1/trades/{r1['id']}", headers=seller_h)).json()
    t2 = (await client.get(f"/api/v1/trades/{r2['id']}", headers=buyer2_h)).json()
    assert t1["status"] == "in_progress"
    assert t2["status"] == "closed" and t2["close_reason"] == "商品已被其他用户锁单"
    # 商品交易中，退出搜索（BR-15）
    resp = await client.get("/api/v1/products/search?keyword=多请求商品", headers=buyer1_h)
    assert resp.json()["total"] == 0
    # 交易中禁止修改关键内容（BR-11）
    resp = await client.patch(f"/api/v1/products/{product['id']}", headers=seller_h, json={"price_cents": 1})
    assert resp.status_code == 409


async def test_withdraw_and_reject(client, setup):
    admin_h, seller_h, buyer1_h, _ = setup
    product = await create_listed_product(client, admin_h, seller_h, title="撤回拒绝商品")
    r = (await client.post("/api/v1/trades/requests", headers=buyer1_h, json={"product_id": product["id"]})).json()
    # 非发起人不能撤回
    resp = await client.post(f"/api/v1/trades/{r['id']}/withdraw", headers=seller_h)
    assert resp.status_code == 403
    await client.post(f"/api/v1/trades/{r['id']}/withdraw", headers=buyer1_h)
    t = (await client.get(f"/api/v1/trades/{r['id']}", headers=buyer1_h)).json()
    assert t["status"] == "withdrawn"
    # 撤回后可再发新请求；卖方拒绝
    r2 = (await client.post("/api/v1/trades/requests", headers=buyer1_h, json={"product_id": product["id"]})).json()
    await client.post(f"/api/v1/trades/{r2['id']}/reject", headers=seller_h, json={"reason": "已线下出掉"})
    t2 = (await client.get(f"/api/v1/trades/{r2['id']}", headers=buyer1_h)).json()
    assert t2["status"] == "rejected"


AGREEMENT = {
    "delivery_time": "周六上午十点",
    "delivery_location": "东门快递站旁",
    "delivery_method": "当面交付",
    "amount_cents": 1000,
    "payment_method": "微信转账",
    "payment_timing": "当面付清",
}


async def test_agreement_flow(client, setup):
    """约定提出/拒绝保持待约定/同意生效/变更须同意（4.15）。"""
    admin_h, seller_h, buyer1_h, _ = setup
    product = await create_listed_product(client, admin_h, seller_h, title="约定流程商品")
    r = (await client.post("/api/v1/trades/requests", headers=buyer1_h, json={"product_id": product["id"]})).json()
    await client.post(f"/api/v1/trades/{r['id']}/accept", headers=seller_h)
    # 提案人不能自己确认
    resp = await client.post(f"/api/v1/trades/{r['id']}/agreements", headers=buyer1_h, json=AGREEMENT)
    assert resp.status_code == 200
    a1 = resp.json()["id"]
    resp = await client.post(f"/api/v1/trades/{r['id']}/agreements/{a1}/confirm", headers=buyer1_h)
    assert resp.status_code == 403
    # 卖方拒绝：只结束提案，保持待约定与锁单
    await client.post(f"/api/v1/trades/{r['id']}/agreements/{a1}/reject", headers=seller_h)
    t = (await client.get(f"/api/v1/trades/{r['id']}", headers=seller_h)).json()
    assert t["agreement_stage"] == "awaiting_agreement" and t["status"] == "in_progress"
    # 第二轮提案并同意
    resp = await client.post(f"/api/v1/trades/{r['id']}/agreements", headers=seller_h, json=AGREEMENT)
    a2 = resp.json()["id"]
    await client.post(f"/api/v1/trades/{r['id']}/agreements/{a2}/confirm", headers=buyer1_h)
    t = (await client.get(f"/api/v1/trades/{r['id']}", headers=seller_h)).json()
    assert t["agreement_stage"] == "awaiting_completion"
    assert t["effective_agreement"]["id"] == a2
    # 变更未同意前保留原约定
    resp = await client.post(
        f"/api/v1/trades/{r['id']}/agreements",
        headers=seller_h,
        json={**AGREEMENT, "amount_cents": 800},
    )
    a3 = resp.json()["id"]
    await client.post(f"/api/v1/trades/{r['id']}/agreements/{a3}/reject", headers=buyer1_h)
    t = (await client.get(f"/api/v1/trades/{r['id']}", headers=seller_h)).json()
    assert t["effective_agreement"]["id"] == a2
    assert t["effective_agreement"]["amount_cents"] == 1000
    assert len([a for a in t["agreement_history"]]) == 3


async def test_completion_requires_agreement(client, setup):
    """普通完成不能跳过约定（UC-C05 验收）。"""
    admin_h, seller_h, buyer1_h, _ = setup
    product = await create_listed_product(client, admin_h, seller_h, title="跳过约定商品")
    r = (await client.post("/api/v1/trades/requests", headers=buyer1_h, json={"product_id": product["id"]})).json()
    await client.post(f"/api/v1/trades/{r['id']}/accept", headers=seller_h)
    resp = await client.post(f"/api/v1/trades/{r['id']}/confirmations", headers=buyer1_h, json={})
    assert resp.status_code == 409


async def test_full_completion_flow(client, setup):
    """双确认完成：商品默认下架，分支归档，可评价（TR-15）。"""
    admin_h, seller_h, buyer1_h, _ = setup
    product = await create_listed_product(client, admin_h, seller_h, title="正常完成商品")
    r = (await client.post("/api/v1/trades/requests", headers=buyer1_h, json={"product_id": product["id"]})).json()
    await client.post(f"/api/v1/trades/{r['id']}/accept", headers=seller_h)
    a = (await client.post(f"/api/v1/trades/{r['id']}/agreements", headers=buyer1_h, json=AGREEMENT)).json()
    await client.post(f"/api/v1/trades/{r['id']}/agreements/{a['id']}/confirm", headers=seller_h)
    # 单方确认只记进度
    resp = await client.post(f"/api/v1/trades/{r['id']}/confirmations", headers=buyer1_h, json={"note": "已当面付清"})
    assert "等待" in resp.json()["detail"]
    t = (await client.get(f"/api/v1/trades/{r['id']}", headers=seller_h)).json()
    assert t["status"] == "in_progress" and t["confirm_wait_started_at"]
    # 重复提交幂等
    resp = await client.post(f"/api/v1/trades/{r['id']}/confirmations", headers=buyer1_h, json={})
    assert resp.json().get("existing") is True
    # 双确认完成
    resp = await client.post(f"/api/v1/trades/{r['id']}/confirmations", headers=seller_h, json={})
    assert "已完成" in resp.json()["detail"]
    t = (await client.get(f"/api/v1/trades/{r['id']}", headers=seller_h)).json()
    assert t["status"] == "completed" and t["conversation_archived"] is True
    p = (await client.get(f"/api/v1/products/{product['id']}", headers=seller_h)).json()
    assert p["status"] == "delisted"
    # 完成后互评（BR-24）
    resp = await client.post(f"/api/v1/trades/{r['id']}/review", headers=buyer1_h, json={"rating": 5, "content": "很靠谱"})
    assert resp.status_code == 201
    resp = await client.post(f"/api/v1/trades/{r['id']}/review", headers=buyer1_h, json={"rating": 1})
    assert resp.status_code == 409  # 每方每笔一条
    # 卖方重新上架形成后续新交易（TR-08）
    resp = await client.post(f"/api/v1/products/{product['id']}/relist", headers=seller_h)
    assert resp.status_code == 200
    assert resp.json()["status"] == "listed"
    r2 = (await client.post("/api/v1/trades/requests", headers=buyer1_h, json={"product_id": product["id"]})).json()
    assert r2["id"] != r["id"]


async def test_cancel_stages(client, setup):
    """约定前买方直接取消；约定后双方同意（BR-06）。"""
    admin_h, seller_h, buyer1_h, _ = setup
    product = await create_listed_product(client, admin_h, seller_h, title="取消阶段商品")
    r = (await client.post("/api/v1/trades/requests", headers=buyer1_h, json={"product_id": product["id"]})).json()
    await client.post(f"/api/v1/trades/{r['id']}/accept", headers=seller_h)
    # 约定前卖方取消须买方同意；买方直接取消
    resp = await client.post(f"/api/v1/trades/{r['id']}/cancel", headers=seller_h, json={})
    assert "等待对方同意" in resp.json()["detail"]
    resp = await client.post(f"/api/v1/trades/{r['id']}/cancel/confirm", headers=buyer1_h, json={})
    assert resp.status_code == 200
    t = (await client.get(f"/api/v1/trades/{r['id']}", headers=seller_h)).json()
    assert t["status"] == "terminated"
    # 约定后须双方同意
    await client.post(f"/api/v1/products/{product['id']}/relist", headers=seller_h)
    r2 = (await client.post("/api/v1/trades/requests", headers=buyer1_h, json={"product_id": product["id"]})).json()
    await client.post(f"/api/v1/trades/{r2['id']}/accept", headers=seller_h)
    a = (await client.post(f"/api/v1/trades/{r2['id']}/agreements", headers=buyer1_h, json=AGREEMENT)).json()
    await client.post(f"/api/v1/trades/{r2['id']}/agreements/{a['id']}/confirm", headers=seller_h)
    resp = await client.post(f"/api/v1/trades/{r2['id']}/cancel", headers=buyer1_h, json={})
    assert "等待对方同意" in resp.json()["detail"]  # 约定后买方不再有直接取消权
    await client.post(f"/api/v1/trades/{r2['id']}/cancel/confirm", headers=seller_h, json={})
    t2 = (await client.get(f"/api/v1/trades/{r2['id']}", headers=seller_h)).json()
    assert t2["status"] == "terminated"


async def test_dispute_flow(client, setup):
    """争议：进入争议结束计时；解决恢复清空当前确认（TR-16/19、BR-07）。"""
    admin_h, seller_h, buyer1_h, _ = setup
    product = await create_listed_product(client, admin_h, seller_h, title="争议流程商品")
    r = (await client.post("/api/v1/trades/requests", headers=buyer1_h, json={"product_id": product["id"]})).json()
    await client.post(f"/api/v1/trades/{r['id']}/accept", headers=seller_h)
    a = (await client.post(f"/api/v1/trades/{r['id']}/agreements", headers=buyer1_h, json=AGREEMENT)).json()
    await client.post(f"/api/v1/trades/{r['id']}/agreements/{a['id']}/confirm", headers=seller_h)
    await client.post(f"/api/v1/trades/{r['id']}/confirmations", headers=buyer1_h, json={})
    # 对方发起争议：结束计时、保持锁单
    resp = await client.post(f"/api/v1/trades/{r['id']}/disputes", headers=seller_h, json={"description": "买方失联"})
    assert resp.status_code == 200
    t = (await client.get(f"/api/v1/trades/{r['id']}", headers=seller_h)).json()
    assert t["status"] == "disputed" and t["confirm_wait_started_at"] is None
    # 争议中不能直接提交完成确认（4.10）
    resp = await client.post(f"/api/v1/trades/{r['id']}/confirmations", headers=seller_h, json={})
    assert resp.status_code == 409
    # 双方确认解决：恢复进行中、清空当前确认
    await client.post(f"/api/v1/trades/{r['id']}/disputes/resolve", headers=seller_h, json={})
    resp = await client.post(f"/api/v1/trades/{r['id']}/disputes/resolve", headers=buyer1_h, json={})
    assert "恢复进行中" in resp.json()["detail"]
    t = (await client.get(f"/api/v1/trades/{r['id']}", headers=seller_h)).json()
    assert t["status"] == "in_progress"
    assert t["my_confirmed"] is False and t["other_party_confirmed"] is False
    assert t["confirm_wait_started_at"] is None  # 恢复不启动计时
    assert t["effective_agreement"]["id"] == a["id"]  # 有效约定保留


async def test_timeout_to_abnormal(client, setup, db):
    """单方确认 7 天未回应转异常并冻结（TR-14）。"""
    from app.services.trade_timeout import scan_once

    admin_h, seller_h, buyer1_h, _ = setup
    product = await create_listed_product(client, admin_h, seller_h, title="超时异常商品")
    r = (await client.post("/api/v1/trades/requests", headers=buyer1_h, json={"product_id": product["id"]})).json()
    await client.post(f"/api/v1/trades/{r['id']}/accept", headers=seller_h)
    a = (await client.post(f"/api/v1/trades/{r['id']}/agreements", headers=buyer1_h, json=AGREEMENT)).json()
    await client.post(f"/api/v1/trades/{r['id']}/agreements/{a['id']}/confirm", headers=seller_h)
    await client.post(f"/api/v1/trades/{r['id']}/confirmations", headers=buyer1_h, json={})
    # 人为将等待起点拨回 8 天前
    trade = await db.get(Trade, r["id"])
    trade.confirm_wait_started_at = datetime.now(UTC) - timedelta(days=8)
    await db.commit()
    count = await scan_once(db)
    assert count == 1
    t = (await client.get(f"/api/v1/trades/{r['id']}", headers=seller_h)).json()
    assert t["status"] == "abnormal" and t["frozen"] is True
    # 异常（冻结）期间双方不得推进（BR-33）：状态与冻结校验均拒绝
    resp = await client.post(f"/api/v1/trades/{r['id']}/confirmations", headers=seller_h, json={})
    assert resp.status_code in (403, 409)
    resp = await client.post(f"/api/v1/trades/{r['id']}/cancel", headers=seller_h, json={})
    assert resp.status_code in (403, 409)
