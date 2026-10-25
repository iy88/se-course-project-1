"""商品域关键规则测试（FR-02/03/09）。"""

import pytest

from tests.conftest import (
    admin_headers,
    approve_product,
    create_listed_product,
    make_admin,
    publish_product,
    user_headers,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def setup(client, db):
    admin = await make_admin(db)
    admin_h = await admin_headers(client)
    seller_h = await user_headers(client, "seller@test.com", "卖方")
    buyer_h = await user_headers(client, "buyer@test.com", "买方")
    return admin_h, seller_h, buyer_h


async def test_publish_requires_review_before_public(client, setup):
    admin_h, seller_h, buyer_h = setup
    product = await publish_product(client, seller_h, title="待审核商品")
    # 审核前不出现在在售搜索（TR-01 前置）
    resp = await client.get("/api/v1/products/search?keyword=待审核商品", headers=buyer_h)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    # 审核通过后公开
    await approve_product(client, admin_h, product["id"])
    resp = await client.get("/api/v1/products/search?keyword=待审核商品", headers=buyer_h)
    assert resp.json()["total"] == 1


async def test_reject_shows_reason_and_resubmit(client, setup):
    admin_h, seller_h, buyer_h = setup
    product = await publish_product(client, seller_h, title="会被拒绝的商品")
    resp = await client.get("/api/v1/admin/cases?status=pending", headers=admin_h)
    case = next(c for c in resp.json() if c["product_id"] == product["id"])
    await client.post(f"/api/v1/admin/cases/{case['id']}/claim", headers=admin_h)
    resp = await client.post(
        f"/api/v1/admin/products/cases/{case['id']}/review",
        headers=admin_h,
        json={"result": "rejected", "reason": "图片模糊，无法判断商品状态"},
    )
    assert resp.status_code == 200
    # 卖方可见拒绝原因（US-02-AC-02）
    resp = await client.get(f"/api/v1/products/{product['id']}", headers=seller_h)
    assert resp.json()["status"] == "rejected"
    assert "图片模糊" in resp.json()["reject_reason"]
    # 修改重提形成新的审核记录（TR-03）
    resp = await client.post(
        f"/api/v1/products/{product['id']}/resubmit",
        headers=seller_h,
        json={"title": "会被拒绝的商品-修改版"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending_review"
    resp = await client.get(f"/api/v1/products/{product['id']}/review-records", headers=seller_h)
    assert len(resp.json()) == 2  # 旧结论保留


async def test_search_multi_tag_all_match(client, setup):
    admin_h, seller_h, buyer_h = setup
    from tests.conftest import upload_image

    # 创建双标签商品与单标签商品
    key = await upload_image(client, seller_h)
    resp = await client.get("/api/v1/categories", headers=seller_h)
    cats = resp.json()
    resp = await client.post(
        "/api/v1/products",
        headers=seller_h,
        json={
            "title": "双标签商品",
            "description": "描述",
            "price_cents": 500,
            "image_keys": [key],
            "tags": [{"category_id": cats[0]["id"]}, {"category_id": cats[1]["id"]}],
        },
    )
    assert resp.status_code == 200
    await approve_product(client, admin_h, resp.json()["id"])
    await create_listed_product(client, admin_h, seller_h, title="单标签商品A")
    # 多标签筛选须全部匹配（BR-15）
    resp = await client.get(
        f"/api/v1/products/search?category_ids={cats[0]['id']}&category_ids={cats[1]['id']}", headers=buyer_h
    )
    items = resp.json()["items"]
    assert all("双标签商品" == i["title"] for i in items)
    assert len(items) == 1


async def test_price_range_and_empty_hint(client, setup):
    admin_h, seller_h, buyer_h = setup
    await create_listed_product(client, admin_h, seller_h, title="价格区间商品", price_cents=5000)
    resp = await client.get("/api/v1/products/search?price_min_cents=100000", headers=buyer_h)
    assert resp.json()["total"] == 0
    assert resp.json()["message"] == "无匹配商品"


async def test_edit_keeps_request_and_history(client, setup):
    admin_h, seller_h, buyer_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="微调商品")
    # 微调不二审不关闭请求（TR-04）
    resp = await client.patch(f"/api/v1/products/{product['id']}", headers=seller_h, json={"price_cents": 1200})
    assert resp.status_code == 200
    assert resp.json()["status"] == "listed"
    resp = await client.get(f"/api/v1/products/{product['id']}/edit-history", headers=seller_h)
    assert len(resp.json()) == 1
    assert resp.json()[0]["before_json"]["price_cents"] == 1000
    assert resp.json()[0]["after_json"]["price_cents"] == 1200


async def test_delist_closes_pending_requests(client, setup):
    """下架关闭待接受请求并注明原因（US-02-AC-05）。"""
    admin_h, seller_h, buyer_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="下架联动商品")
    resp = await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]})
    assert resp.status_code == 200
    trade_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/products/{product['id']}/delist", headers=seller_h)
    assert resp.status_code == 200
    resp = await client.get(f"/api/v1/trades/{trade_id}", headers=buyer_h)
    assert resp.json()["status"] == "closed"
    assert resp.json()["close_reason"] == "商品已下架"


async def test_cannot_delist_with_locking_trade(client, setup):
    """锁单交易未结束禁止下架（US-02-AC-04／BR-09）。"""
    admin_h, seller_h, buyer_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="锁单下架商品")
    resp = await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]})
    trade_id = resp.json()["id"]
    await client.post(f"/api/v1/trades/{trade_id}/accept", headers=seller_h)
    resp = await client.post(f"/api/v1/products/{product['id']}/delist", headers=seller_h)
    assert resp.status_code == 409


async def test_favorite_invalid_hint_and_cancel(client, setup):
    """收藏失效提示且可取消，不泄露内容（US-04-AC-02）。"""
    admin_h, seller_h, buyer_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="收藏失效商品")
    resp = await client.post(f"/api/v1/favorites/{product['id']}", headers=buyer_h)
    assert resp.status_code == 200
    # 下架后清单显示失效
    await client.post(f"/api/v1/products/{product['id']}/delist", headers=seller_h)
    resp = await client.get("/api/v1/favorites", headers=buyer_h)
    item = next(i for i in resp.json() if i["product_id"] == product["id"])
    assert item["valid"] is False
    assert item["title"] is None
    # 失效仍可取消收藏
    resp = await client.delete(f"/api/v1/favorites/{product['id']}", headers=buyer_h)
    assert resp.status_code == 200


async def test_comment_rules(client, setup):
    """已下架禁评、仅卖方可回复买方（BR-17）。"""
    admin_h, seller_h, buyer_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="评论规则商品")
    resp = await client.post(
        f"/api/v1/products/{product['id']}/comments", headers=buyer_h, json={"content": "这本书有笔记吗？"}
    )
    assert resp.status_code == 201
    comment_id = resp.json()["id"]
    # 买方不能回复买方
    other_h = await user_headers(client, "other@test.com", "路人")
    resp = await client.post(
        f"/api/v1/products/{product['id']}/comments",
        headers=other_h,
        json={"content": "同问", "reply_to_comment_id": comment_id},
    )
    assert resp.status_code == 403
    # 卖方可回复买方
    resp = await client.post(
        f"/api/v1/products/{product['id']}/comments",
        headers=seller_h,
        json={"content": "有几页笔记，不影响使用", "reply_to_comment_id": comment_id},
    )
    assert resp.status_code == 201
    # 下架后禁止新增
    await client.post(f"/api/v1/products/{product['id']}/delist", headers=seller_h)
    resp = await client.post(f"/api/v1/products/{product['id']}/comments", headers=buyer_h, json={"content": "还在吗"})
    assert resp.status_code == 409
