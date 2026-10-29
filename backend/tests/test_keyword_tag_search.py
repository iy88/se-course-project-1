"""自由关键词搜索：商品文本 OR 关联标签主名/活跃别名（FR-02/BR-15）。"""

import pytest

from app.models import Product
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


@pytest.fixture
async def setup(client, db):
    await make_admin(db)
    admin_h = await admin_headers(client)
    seller_h = await user_headers(client, "seller@test.com", "卖方")
    buyer_h = await user_headers(client, "buyer@test.com", "买方")
    return admin_h, seller_h, buyer_h


async def _list_tagged(client, admin_h, seller_h, *, title, category_ids, price_cents=1000):
    resp = await client.post(
        "/api/v1/products",
        headers=seller_h,
        json={
            "title": title,
            "description": "商品描述",
            "price_cents": price_cents,
            "image_keys": [await upload_image(client, seller_h)],
            "tags": [{"category_id": category_id} for category_id in category_ids],
        },
    )
    assert resp.status_code == 200, resp.text
    product_id = resp.json()["id"]
    await approve_product(client, admin_h, product_id)
    return product_id


async def _search_ids(client, headers, **params):
    resp = await client.get("/api/v1/products/search", headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body, {item["id"] for item in body["items"]}


async def test_keyword_matches_tag_primary_and_still_matches_text(client, setup):
    admin_h, seller_h, buyer_h = setup
    tagged = await _list_tagged(
        client, admin_h, seller_h, title="宿舍收纳套装", category_ids=[3]
    )
    text = (await create_listed_product(client, admin_h, seller_h, title="护眼台灯"))["id"]
    unrelated = (await create_listed_product(client, admin_h, seller_h, title="高等数学教材"))["id"]

    # 标题/描述均无关键词，但关联分类主名为“生活用品”。
    body, ids = await _search_ids(client, buyer_h, keyword="生活用品")
    assert body["total"] == 1 and ids == {tagged}

    # 原有标题子串搜索仍生效，且不因标签匹配混入无关商品。
    body, ids = await _search_ids(client, buyer_h, keyword="台灯")
    assert body["total"] == 1 and ids == {text}

    body, ids = await _search_ids(client, buyer_h, keyword="数学")
    assert body["total"] == 1 and ids == {unrelated}


async def test_keyword_matches_active_alias_but_not_removed_alias(client, setup):
    admin_h, seller_h, buyer_h = setup
    resp = await client.post(
        "/api/v1/categories/3/aliases", headers=admin_h, json={"name": "日用小物"}
    )
    assert resp.status_code == 200, resp.text
    tagged = await _list_tagged(
        client, admin_h, seller_h, title="宿舍收纳盒", category_ids=[3]
    )

    body, ids = await _search_ids(client, buyer_h, keyword="日用小物")
    assert body["total"] == 1 and ids == {tagged}

    resp = await client.delete(
        "/api/v1/categories/3/aliases/by-name", headers=admin_h, params={"name": "日用小物"}
    )
    assert resp.status_code == 200, resp.text

    # 已移除别名不再作为标签关键词命中；历史关联本身仍保留。
    body, ids = await _search_ids(client, buyer_h, keyword="日用小物")
    assert body["total"] == 0 and ids == set()
    body, ids = await _search_ids(client, buyer_h, keyword="生活用品")
    assert body["total"] == 1 and ids == {tagged}


async def test_keyword_matches_historical_disabled_category_association(client, setup):
    admin_h, seller_h, buyer_h = setup
    historical = await _list_tagged(
        client, admin_h, seller_h, title="停用前购入的收纳套装", category_ids=[3]
    )
    resp = await client.patch("/api/v1/categories/3", headers=admin_h, json={"status": "disabled"})
    assert resp.status_code == 200, resp.text

    # 停用仅限制新选择；既有标签关联仍按当前主名可检索。
    body, ids = await _search_ids(client, buyer_h, keyword="生活用品")
    assert body["total"] == 1 and ids == {historical}


async def test_keyword_keeps_explicit_multi_tag_and_price_conditions(client, setup):
    admin_h, seller_h, buyer_h = setup
    both = await _list_tagged(
        client, admin_h, seller_h, title="组合优惠套装", category_ids=[1, 2], price_cents=1500
    )
    await _list_tagged(
        client, admin_h, seller_h, title="组合优惠单品", category_ids=[1], price_cents=1500
    )
    await _list_tagged(
        client, admin_h, seller_h, title="组合优惠高端", category_ids=[1, 2], price_cents=5000
    )
    tag_only = await _list_tagged(
        client, admin_h, seller_h, title="组合优惠日用品", category_ids=[3], price_cents=1500
    )

    body, ids = await _search_ids(
        client,
        buyer_h,
        keyword="组合",
        category_ids=[1, 2],
        price_min_cents=1000,
        price_max_cents=2000,
    )
    assert body["total"] == 1 and ids == {both}

    # 关键词通过标签命中也不能绕过显式标签的 AND 条件。
    body, ids = await _search_ids(
        client, buyer_h, keyword="生活用品", category_ids=[1, 2]
    )
    assert body["total"] == 0 and ids == set()
    assert tag_only not in ids


async def test_keyword_listed_only_pagination_and_total_without_duplicates(client, setup, db):
    admin_h, seller_h, buyer_h = setup
    listed = [
        await _list_tagged(
            client, admin_h, seller_h, title=f"宿舍收纳{i}", category_ids=[3]
        )
        for i in range(3)
    ]
    # 主名和多个活跃别名均命中同一关键词，不得使商品或 total 重复。
    for alias in ("生活用品A", "生活用品B"):
        resp = await client.post(
            f"/api/v1/categories/3/aliases", headers=admin_h, json={"name": alias}
        )
        assert resp.status_code == 200, resp.text

    pending = (await publish_product(client, seller_h, title="宿舍收纳待审", category_id=3))["id"]
    in_transaction = await _list_tagged(
        client, admin_h, seller_h, title="宿舍收纳交易中", category_ids=[3]
    )
    in_transaction_row = await db.get(Product, in_transaction)
    in_transaction_row.status = "in_transaction"
    await db.commit()

    delisted = await _list_tagged(
        client, admin_h, seller_h, title="宿舍收纳已下架", category_ids=[3]
    )
    resp = await client.post(f"/api/v1/products/{delisted}/delist", headers=seller_h)
    assert resp.status_code == 200, resp.text

    restricted = await _list_tagged(
        client, admin_h, seller_h, title="宿舍收纳受限", category_ids=[3]
    )
    restricted_row = await db.get(Product, restricted)
    restricted_row.display_restricted = True
    await db.commit()

    await create_listed_product(client, admin_h, seller_h, title="高等数学教材")

    body, first_ids = await _search_ids(
        client, buyer_h, keyword="生活用品", page=1, page_size=2
    )
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert len(first_ids) == 2 and first_ids <= set(listed)

    body, second_ids = await _search_ids(
        client, buyer_h, keyword="生活用品", page=2, page_size=2
    )
    assert body["total"] == 3
    assert len(body["items"]) == 1
    assert first_ids | second_ids == set(listed)
    assert not ({pending, in_transaction, delisted, restricted} & (first_ids | second_ids))
