"""IM 与治理关键规则测试（BR-18/32/33/25/26/34）。"""

import pytest

from tests.conftest import create_listed_product, make_admin, user_headers

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def setup(client, db):
    await make_admin(db)
    from tests.conftest import login

    admin_h = {"Authorization": f"Bearer {await login(client, 'admin@test.edu', 'admin123456')}"}
    seller_h = await user_headers(client, "s@t.com", "卖方")
    buyer_h = await user_headers(client, "b@t.com", "买方")
    return admin_h, seller_h, buyer_h


async def _claimed_trade_case(client, admin_h, db, trade_id: int) -> int:
    """R5 合法夹具：创建与交易直接相关的事项并由管理员认领。"""
    from app.models import DisposalCase

    case = DisposalCase(case_type="trade_dispute", title=f"管理交易事项-{trade_id}", trade_id=trade_id)
    db.add(case)
    await db.commit()
    resp = await client.post(f"/api/v1/admin/cases/{case.id}/claim", headers=admin_h)
    assert resp.status_code == 200, resp.text
    return case.id


async def test_trade_branch_and_normal_chat(client, setup):
    """两类 IM 分开：交易分支独立、普通私聊复用（BR-18）。"""
    admin_h, seller_h, buyer_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="IM 商品")
    r = (await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]})).json()
    trade = (await client.get(f"/api/v1/trades/{r['id']}", headers=buyer_h)).json()
    branch_id = trade["conversation_id"]
    # 分支内发消息
    resp = await client.post(f"/api/v1/conversations/{branch_id}/messages", headers=buyer_h, json={"content": "你好，书还在吗"})
    assert resp.status_code == 200
    # 非成员不能访问（BR-18 E1）
    other_h = await user_headers(client, "x@t.com", "路人")
    resp = await client.get(f"/api/v1/conversations/{branch_id}", headers=other_h)
    assert resp.status_code == 403
    # 普通私聊：发起/复用；不能私聊本人
    resp = await client.post("/api/v1/conversations/normal", headers=buyer_h, json={"peer_user_id": 99})
    assert resp.status_code == 404 or resp.status_code == 200
    seller_profile = (await client.get(f"/api/v1/users/{trade['seller']['id']}/profile", headers=buyer_h)).json()
    resp = await client.post("/api/v1/conversations/normal", headers=buyer_h, json={"peer_user_id": seller_profile["id"]})
    assert resp.status_code == 201
    normal_id = resp.json()["id"]
    resp = await client.post("/api/v1/conversations/normal", headers=seller_h, json={"peer_user_id": trade["buyer"]["id"]})
    assert resp.json()["id"] == normal_id  # 同一对用户复用
    me_h = buyer_h
    my_id = trade["buyer"]["id"]
    resp = await client.post("/api/v1/conversations/normal", headers=me_h, json={"peer_user_id": my_id})
    assert resp.status_code == 400
    # 未读按会话独立计算；打开会话推进已读（BR-18）
    await client.post(f"/api/v1/conversations/{normal_id}/messages", headers=seller_h, json={"content": "在的"})
    summary = (await client.get("/api/v1/conversations/unread-summary", headers=buyer_h)).json()
    assert summary["unread"] >= 1
    detail = (await client.get(f"/api/v1/conversations/{normal_id}", headers=buyer_h)).json()
    last_id = detail["messages"][-1]["id"]
    await client.post(f"/api/v1/conversations/{normal_id}/read", headers=buyer_h, json={"last_displayed_message_id": last_id})
    # 交易分支未读不受普通私聊已读影响（US-04-AC-06）
    listing = (await client.get("/api/v1/conversations", headers=buyer_h)).json()
    branch_item = next(c for c in listing if c["id"] == branch_id)
    assert branch_item["unread"] >= 1


async def test_freeze_blocks_pair_im_not_third_party(client, setup, db):
    """冻结 p、q：两类 IM 禁发、历史可读；p–s 不受影响（US-04-AC-07／BR-33）。"""
    admin_h, seller_h, buyer_h = setup
    third_h = await user_headers(client, "t3@t.com", "第三方")
    product = await create_listed_product(client, admin_h, seller_h, title="冻结 IM 商品")
    r = (await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]})).json()
    await client.post(f"/api/v1/trades/{r['id']}/accept", headers=seller_h)
    trade = (await client.get(f"/api/v1/trades/{r['id']}", headers=seller_h)).json()
    branch_id = trade["conversation_id"]
    # 建立卖方-第三方普通私聊
    normal_st = (await client.post("/api/v1/conversations/normal", headers=seller_h, json={"peer_user_id": trade["buyer"]["id"]}))
    # 管理员冻结该交易（合法相关认领事项上下文）
    case_id = await _claimed_trade_case(client, admin_h, db, r["id"])
    resp = await client.post(
        f"/api/v1/admin/trades/{r['id']}/freeze",
        headers=admin_h,
        json={"reason": "涉嫌违规，暂停处理", "case_id": case_id},
    )
    assert resp.status_code == 200
    # p-q 交易分支禁发、历史可读
    resp = await client.post(f"/api/v1/conversations/{branch_id}/messages", headers=buyer_h, json={"content": "?"})
    assert resp.status_code == 403
    resp = await client.get(f"/api/v1/conversations/{branch_id}", headers=buyer_h)
    assert resp.status_code == 200
    # p-q 普通私聊同样禁发
    normal_id = normal_st.json()["id"]
    resp = await client.post(f"/api/v1/conversations/{normal_id}/messages", headers=buyer_h, json={"content": "?"})
    assert resp.status_code == 403
    # 卖方与第三方私聊不受影响
    normal_st3 = (await client.post("/api/v1/conversations/normal", headers=seller_h, json={"peer_user_id": (await client.get('/api/v1/auth/me', headers=third_h)).json()['id']}))
    resp = await client.post(f"/api/v1/conversations/{normal_st3.json()['id']}/messages", headers=seller_h, json={"content": "正常聊天"})
    assert resp.status_code == 200
    # 解除冻结后恢复发送
    await client.post(
        f"/api/v1/admin/trades/{r['id']}/unfreeze",
        headers=admin_h,
        json={"reason": "核查完毕，无违规", "case_id": case_id},
    )
    resp = await client.post(f"/api/v1/conversations/{branch_id}/messages", headers=buyer_h, json={"content": "恢复沟通"})
    assert resp.status_code == 200


async def test_ban_restrictions_and_appeal(client, setup):
    """封禁：写操作被拒、处置沟通例外、解封恢复展示（BR-32、DT-03、TR-10）。"""
    admin_h, seller_h, buyer_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="封禁联动商品")
    # 买方收藏商品后，卖方被封禁（先取好发布要用的图片 key）
    await client.post(f"/api/v1/favorites/{product['id']}", headers=buyer_h)
    from tests.conftest import upload_image

    image_key = await upload_image(client, seller_h)
    resp = await client.post(f"/api/v1/admin/users/{product['seller_id']}/ban", headers=admin_h, json={"reason": "发布违规内容"})
    assert resp.status_code == 200
    case_id = resp.json()["case_id"]
    # 商品停止公开展示（DT-03）
    resp = await client.get(f"/api/v1/products/{product['id']}", headers=buyer_h)
    assert resp.status_code == 404
    # 封禁卖方写操作被拒
    key = image_key
    resp = await client.post(
        "/api/v1/products",
        headers=seller_h,
        json={
            "title": "新商品",
            "description": "d",
            "price_cents": 100,
            "image_keys": [key],
            "tags": [{"new_name": "x"}],
        },
    )
    assert resp.status_code == 403
    # 处置沟通单例外：提交申辩（BR-32）
    resp = await client.post(f"/api/v1/me/cases/{case_id}/appeal", headers=seller_h, json={"content": "内容合规，申请复核"})
    assert resp.status_code == 200
    # 管理员在事项回复
    resp = await client.post(f"/api/v1/admin/cases/{case_id}/messages", headers=admin_h, json={"content": "收到，维持处置"})
    assert resp.status_code == 200
    # 解封：恢复展示，不自动上架为在售（非在售保持）
    resp = await client.post(f"/api/v1/admin/users/{product['seller_id']}/unban", headers=admin_h, json={"lift_reason": "复核通过"})
    assert resp.status_code == 200
    resp = await client.get(f"/api/v1/products/{product['id']}", headers=buyer_h)
    assert resp.status_code == 200
    assert resp.json()["status"] == "listed"  # 原为在售，恢复展示资格


async def test_report_flow_with_inquiry_and_public_result(client, setup):
    """举报：同对象未结不重复、问询说明、处置告知、匿名公开（BR-25/26）。"""
    admin_h, seller_h, buyer_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="被举报商品")
    # 同对象未结举报在原事项补充
    r1 = (await client.post("/api/v1/reports", headers=buyer_h, json={
        "target_type": "product", "target_id": product["id"], "reason": "疑似全新黄牛转卖",
    })).json()
    r2 = (await client.post("/api/v1/reports", headers=buyer_h, json={
        "target_type": "product", "target_id": product["id"], "reason": "再次举报",
    })).json()
    assert r2.get("existing_report_id") == r1["id"]
    resp = await client.post(f"/api/v1/reports/{r1['id']}/supplements", headers=buyer_h, json={"content": "补充截图说明"})
    assert resp.status_code == 200
    # 管理员认领 + 问询
    resp = await client.get("/api/v1/admin/reports", headers=admin_h)
    case_id = next(r["case_id"] for r in resp.json() if r["id"] == r1["id"])
    await client.post(f"/api/v1/admin/cases/{case_id}/claim", headers=admin_h)
    resp = await client.post(f"/api/v1/admin/cases/{case_id}/inquiry", headers=admin_h, json={"content": "请说明商品来源与使用情况"})
    assert resp.status_code == 200
    # 被举报人从事项提交说明（问询不改变状态）
    resp = await client.post(f"/api/v1/me/cases/{case_id}/statement", headers=seller_h, json={"content": "自用闲置转让"})
    assert resp.status_code == 200
    # 认定违规并处置：停止公开
    resp = await client.post(
        f"/api/v1/admin/reports/cases/{case_id}/decision",
        headers=admin_h,
        json={
            "outcome": "handled",
            "reason": "认定为批量倒卖",
            "public_summary": "经核查认定为违规转卖，已停止相关商品展示",
            "actions": {"remove_content": False, "restrict_display": True, "freeze_trade": False, "ban_user": False},
        },
    )
    assert resp.status_code == 200
    resp = await client.get(f"/api/v1/products/{product['id']}", headers=buyer_h)
    assert resp.status_code == 404
    # 结果已确认并匿名公开：我的举报可见结论
    reports = (await client.get("/api/v1/reports/mine", headers=buyer_h)).json()
    mine = next(r for r in reports if r["id"] == r1["id"])
    assert mine["result_confirmed"] is True and mine["public_result"]
    # 结案后不再接受补充
    resp = await client.post(f"/api/v1/reports/{r1['id']}/supplements", headers=buyer_h, json={"content": "晚了"})
    assert resp.status_code == 409


async def test_single_claimant_rule(client, setup, db):
    """同一事项同时仅一名认领人（BR-34）。"""
    admin_h, seller_h, buyer_h = setup
    from tests.conftest import publish_product

    product = await publish_product(client, seller_h, title="认领唯一商品")  # 新待审事项
    resp = await client.get("/api/v1/admin/cases?status=pending", headers=admin_h)
    case_id = next(c["id"] for c in resp.json() if c["product_id"] == product["id"])
    await client.post(f"/api/v1/admin/cases/{case_id}/claim", headers=admin_h)
    resp = await client.post(f"/api/v1/admin/cases/{case_id}/claim", headers=admin_h)
    assert resp.status_code == 409
    # 第二个管理员不能处理他人认领事项（US-08-AC-01）
    from tests.conftest import admin_headers, make_admin

    await make_admin(db, email="admin2@test.edu")
    admin2_h = await admin_headers(client, email="admin2@test.edu")
    resp = await client.post(f"/api/v1/admin/cases/{case_id}/claim", headers=admin2_h)
    assert resp.status_code == 409
    resp = await client.get(f"/api/v1/admin/cases/{case_id}", headers=admin2_h)
    assert resp.status_code == 403
    # 处理动作同样仅限认领人（BR-34）：问询、处置、商品审核均须 403
    resp = await client.post(
        f"/api/v1/admin/cases/{case_id}/inquiry", headers=admin2_h, json={"content": "请说明来源"}
    )
    assert resp.status_code == 403
    resp = await client.post(
        f"/api/v1/admin/cases/{case_id}/dispose", headers=admin2_h, json={"conclusion": "无问题"}
    )
    assert resp.status_code == 403
    resp = await client.post(
        f"/api/v1/admin/products/cases/{case_id}/review", headers=admin2_h, json={"result": "approved"}
    )
    assert resp.status_code == 403
    # 认领人本人处理不受影响
    resp = await client.post(
        f"/api/v1/admin/cases/{case_id}/dispose", headers=admin_h, json={"conclusion": "无问题"}
    )
    assert resp.status_code == 200


async def test_admin_adjust_and_restore(client, setup, db):
    """管理员有依据调整状态：恢复清空当前确认；直接完成不伪造确认（BR-08）。"""
    admin_h, seller_h, buyer_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="管理调整商品")
    r = (await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]})).json()
    await client.post(f"/api/v1/trades/{r['id']}/accept", headers=seller_h)
    case_id = await _claimed_trade_case(client, admin_h, db, r["id"])
    # 直接调整为已完成
    resp = await client.post(
        f"/api/v1/admin/trades/{r['id']}/adjust",
        headers=admin_h,
        json={"to_status": "completed", "reason": "双方线下已自行交付，按处置依据记录完成", "case_id": case_id},
    )
    assert resp.status_code == 200
    t = (await client.get(f"/api/v1/trades/{r['id']}", headers=seller_h)).json()
    assert t["status"] == "completed"
    # 不伪造用户确认：确认列表为空
    assert t["confirmations"] == []
    # 转移历史留据
    transitions = (await client.get(f"/api/v1/trades/{r['id']}/transitions", headers=seller_h)).json()
    assert any(tr["trigger"] == "admin_adjust_completed" and tr["actor_role"] == "admin" for tr in transitions)


async def test_stats_endpoint(client, setup):
    """统计口径（BR-31）。"""
    admin_h, seller_h, buyer_h = setup
    product = await create_listed_product(client, admin_h, seller_h, title="统计商品")
    resp = await client.get("/api/v1/admin/stats", headers=admin_h)
    assert resp.status_code == 200
    data = resp.json()
    assert data["products"]["listed"] >= 1
    assert data["users"]["total"] >= 3
    # 非管理员被拒
    resp = await client.get("/api/v1/admin/stats", headers=buyer_h)
    assert resp.status_code == 403
