"""举报处置冻结回归：交易分支消息举报按关联交易冻结，普通私聊不推断交易（BR-26/33）。"""

import pytest
from app.models import DisposalCase, Notification, Product, Report, Trade
from sqlalchemy import select

from tests.conftest import (
    admin_headers,
    create_listed_product,
    make_admin,
    user_headers,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def setup(client, db):
    await make_admin(db)
    admin_h = await admin_headers(client)
    seller_h = await user_headers(client, "seller-report-freeze@t.com", "卖方")
    buyer_h = await user_headers(client, "buyer-report-freeze@t.com", "买方")
    return admin_h, seller_h, buyer_h


async def _accepted_trade(client, admin_h, seller_h, buyer_h, *, title: str) -> tuple[dict, int, int, int]:
    """发布并审核商品、买方请求、卖方接受；返回商品、交易、交易分支及买方用户。"""
    product = await create_listed_product(client, admin_h, seller_h, title=title)
    resp = await client.post("/api/v1/trades/requests", headers=buyer_h, json={"product_id": product["id"]})
    assert resp.status_code == 200, resp.text
    trade_id = resp.json()["id"]
    resp = await client.post(f"/api/v1/trades/{trade_id}/accept", headers=seller_h)
    assert resp.status_code == 200, resp.text
    detail = (await client.get(f"/api/v1/trades/{trade_id}", headers=buyer_h)).json()
    return product, trade_id, detail["conversation_id"], detail["buyer"]["id"]


async def _send_text(client, conversation_id: int, headers: dict, content: str) -> int:
    resp = await client.post(f"/api/v1/conversations/{conversation_id}/messages", headers=headers, json={"content": content})
    assert resp.status_code == 200, resp.text
    detail = (await client.get(f"/api/v1/conversations/{conversation_id}", headers=headers)).json()
    return detail["messages"][-1]["id"]


async def _submit_report(client, headers: dict, message_id: int, reason: str) -> int:
    resp = await client.post(
        "/api/v1/reports",
        headers=headers,
        json={"target_type": "message", "target_id": message_id, "reason": reason},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _claim_report_case(client, admin_h, report_id: int) -> int:
    reports = (await client.get("/api/v1/admin/reports", headers=admin_h)).json()
    case_id = next(item["case_id"] for item in reports if item["id"] == report_id)
    resp = await client.post(f"/api/v1/admin/cases/{case_id}/claim", headers=admin_h)
    assert resp.status_code == 200, resp.text
    return case_id


async def _decision(client, admin_h, case_id: int, *, reason: str, basis: str) -> None:
    resp = await client.post(
        f"/api/v1/admin/reports/cases/{case_id}/decision",
        headers=admin_h,
        json={
            "outcome": "handled",
            "reason": reason,
            "basis": basis,
            "actions": {"freeze_trade": True},
        },
    )
    assert resp.status_code == 200, resp.text


async def _fresh(db, model, pk):
    db.expunge_all()
    obj = await db.get(model, pk)
    assert obj is not None
    return obj


async def test_report_on_trade_branch_message_freezes_related_trade(client, db, setup):
    """真实举报交易分支消息 → 认领 → 处置冻结：关联交易冻结、结案并通知双方。"""
    admin_h, seller_h, buyer_h = setup
    product, trade_id, branch_id, buyer_id = await _accepted_trade(
        client, admin_h, seller_h, buyer_h, title="举报冻结交易分支消息"
    )
    message_id = await _send_text(client, branch_id, buyer_h, "交易分支内的普通文本消息")

    report_id = await _submit_report(client, seller_h, message_id, "交易分支消息内容违规")
    case_id = await _claim_report_case(client, admin_h, report_id)
    await _decision(client, admin_h, case_id, reason="认定交易分支消息违规", basis=f"举报#{report_id}")

    case = await _fresh(db, DisposalCase, case_id)
    report = await _fresh(db, Report, report_id)
    trade = await _fresh(db, Trade, trade_id)
    product_row = await _fresh(db, Product, product["id"])

    assert case.status == "disposed" and case.disposed_at is not None
    assert report.status == "handled" and report.result_confirmed is True

    # 冻结来源为本案事项，交易状态与商品锁单保留。
    assert trade.frozen is True
    assert trade.frozen_case_id == case_id
    assert trade.status == "in_progress"
    assert product_row.status == "in_transaction"

    # 冻结与处置均通知交易双方。
    db.expunge_all()
    seller_id = trade.seller_id
    notifications = list(
        (
            await db.execute(
                select(Notification).where(Notification.user_id.in_([buyer_id, seller_id]))
            )
        ).scalars()
    )
    frozen_notified = {n.user_id for n in notifications if n.type == "trade_frozen" and n.link_id == trade_id}
    disposed_notified = {
        n.user_id for n in notifications if n.type == "disposal" and n.link_type == "case" and n.link_id == case_id
    }
    assert frozen_notified == {buyer_id, seller_id}
    assert disposed_notified == {buyer_id, seller_id}


async def test_report_on_normal_chat_message_does_not_freeze_pair_trade(client, db, setup):
    """普通私聊消息举报不推断冻结双方交易；无关联交易时不产生冻结副作用。"""
    admin_h, seller_h, buyer_h = setup
    _, trade_id, _, buyer_id = await _accepted_trade(
        client, admin_h, seller_h, buyer_h, title="普通私聊举报不冻结交易"
    )
    resp = await client.post("/api/v1/conversations/normal", headers=seller_h, json={"peer_user_id": buyer_id})
    assert resp.status_code == 201, resp.text
    normal_id = resp.json()["id"]
    message_id = await _send_text(client, normal_id, buyer_h, "普通私聊内的文本消息")

    report_id = await _submit_report(client, seller_h, message_id, "普通私聊消息内容违规")
    case_id = await _claim_report_case(client, admin_h, report_id)
    await _decision(client, admin_h, case_id, reason="认定普通私聊消息违规", basis=f"举报#{report_id}")

    trade = await _fresh(db, Trade, trade_id)
    assert trade.frozen is False
    assert trade.frozen_case_id is None
    assert trade.status == "in_progress"

    db.expunge_all()
    frozen_notifications = list(
        (
            await db.execute(
                select(Notification).where(
                    Notification.user_id.in_([buyer_id, trade.seller_id]),
                    Notification.type == "trade_frozen",
                )
            )
        ).scalars()
    )
    assert frozen_notifications == []
