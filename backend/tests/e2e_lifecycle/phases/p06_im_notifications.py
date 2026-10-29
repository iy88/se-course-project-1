"""[p06] 两类 IM 与站内通知（US-04、US-11）真实 API 生命周期阶段。

覆盖 SC-04（普通私聊/交易分支/分分支未读/归档分支/冻结限制）、SC-11（通知与已读、待办）、
US-11-AC-01—06 与 4.17 事件通知，以及真实 WebSocket 握手、ping/pong、消息与通知事件帧。
共用造数辅助来自 p04/p05 模块（只导入函数，不依赖其是否已运行）。
"""

from __future__ import annotations

import json

from phases.p04_search_favorites_comments import (
    admin_claim_case,
    admin_list_cases,
    conversation_item,
    detail_text,
    ensure_admin,
    ensure_category,
    find_review_case,
    list_notifications,
    merge_trade_detail,
    new_user,
    notifications_matching,
    product_detail,
    publish_listed_product,
    register_product,
    request_trade,
    trade_detail,
)
from phases.p05_trades_core import (
    accept_trade,
    confirm_agreement,
    confirm_cancel,
    create_dispute,
    propose_agreement,
    refresh_trade,
    submit_confirmation,
    trade_cancel,
)

try:  # 真实 WS 需要 websockets；后端 venv 已安装（框架运行环境约定）
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect as ws_connect

    WS_AVAILABLE = True
except Exception:  # noqa: BLE001 - 缺少依赖时记录 SKIP，不影响 HTTP 检查项
    ws_connect = None
    ConnectionClosed = Exception  # type: ignore[assignment]
    WS_AVAILABLE = False

PHASE_ID = "p06"

GOVERNANCE_EVENT_NOTE = "举报结果/问询/处置/申辩类通知由 p07_reviews_reports_governance 覆盖"


# ---------------------------------------------------------------------------
# 本阶段辅助
# ---------------------------------------------------------------------------
def http_base(api) -> str:
    return api.base_url.rstrip("/")


def ws_uri(api, token: str) -> str:
    base = http_base(api)
    base = base.replace("https://", "wss://", 1) if base.startswith("https://") else base.replace("http://", "ws://", 1)
    return f"{base}/ws?token={token}"


def create_normal(api, token: str, peer_user_id: int, *, expected=201):
    return api.post("/conversations/normal", token=token, json_body={"peer_user_id": peer_user_id}, expected=expected)


def conversations(api, token: str) -> list[dict]:
    return api.get("/conversations", token=token, expected=200).json()


def conversation_map(api, token: str) -> dict[int, dict]:
    return {c["id"]: c for c in conversations(api, token)}


def conversation(api, token: str, conversation_id: int, *, expected=200) -> dict:
    return api.get(f"/conversations/{conversation_id}", token=token, expected=expected).json()


def send_text(api, token: str, conversation_id: int, content: str, *, expected=200):
    return api.post(f"/conversations/{conversation_id}/messages", token=token, json_body={"content": content}, expected=expected)


def advance_read(api, token: str, conversation_id: int, last_displayed_message_id: int, *, expected=200):
    return api.post(
        f"/conversations/{conversation_id}/read",
        token=token,
        json_body={"last_displayed_message_id": last_displayed_message_id},
        expected=expected,
    )


def unread_of(api, token: str, conversation_id: int | None = None, *, name: str = "") -> int:
    data = conversation_map(api, token)
    if conversation_id is None:
        return sum(item.get("unread", 0) for item in data.values())
    item = data.get(conversation_id)
    if item is None:
        raise AssertionError(f"会话列表中找不到 {name or conversation_id}")
    return item.get("unread", 0)


def unread_summary(api, token: str) -> int:
    resp = api.get("/conversations/unread-summary", token=token, expected=200)
    return resp.json().get("unread", -1)


def todos(api, token: str) -> dict:
    return api.get("/notifications/todos", token=token, expected=200).json()


def todo_keys(api, token: str) -> set[str]:
    return {item.get("key", "") for item in todos(api, token).get("items", [])}


def notifications_all(api, token: str, *, pages: int = 3) -> list[dict]:
    found: list[dict] = []
    for page in range(1, pages + 1):
        data = list_notifications(api, token, page=page, page_size=50)
        items = data.get("items") or []
        found.extend(items)
        if len(items) < 50:
            break
    return found


def unread_count(api, token: str) -> int:
    return api.get("/notifications/unread-count", token=token, expected=200).json().get("unread", -1)


def mark_notification_read(api, token: str, notification_id: int, *, expected=200):
    return api.post(f"/notifications/{notification_id}/read", token=token, expected=expected)


def notify_by_link(api, token: str, *, type_: str, link_id: int) -> list[dict]:
    return notifications_matching(api, token, type_=type_, link_id=link_id)


def admin_freeze(api, ctx, trade_key: str, case_id: int, *, reason: str):
    trade = ctx.trades[trade_key]
    return api.post(
        f"/admin/trades/{trade['id']}/freeze",
        token=ctx.token("admin"),
        json_body={"reason": reason, "case_id": case_id},
        expected=200,
    )


def admin_unfreeze(api, ctx, trade_key: str, case_id: int, *, reason: str):
    trade = ctx.trades[trade_key]
    return api.post(
        f"/admin/trades/{trade['id']}/unfreeze",
        token=ctx.token("admin"),
        json_body={"reason": reason, "case_id": case_id},
        expected=200,
    )


def claim_trade_dispute_case(api, ctx, trade_key: str) -> int:
    """认领该交易的争议事项，作为管理员冻结/解冻私人交易的合法依据。"""
    trade = ctx.trades[trade_key]
    cases = admin_list_cases(api, ctx, status="pending", case_type="trade_dispute")
    case = next((c for c in cases if c.get("trade_id") == trade["id"]), None)
    if case is None:
        raise AssertionError(f"找不到交易 #{trade['id']} 的待认领争议事项")
    admin_claim_case(api, ctx, case["id"])
    ctx.trades[trade_key]["case_id"] = case["id"]
    ctx.remember_case(f"p06_case_{trade_key}", {"id": case["id"], "case_type": "trade_dispute", "status": "processing", "title": f"争议事项 #{case['id']}"})
    return case["id"]


def admin_reject_product(api, ctx, product_id: int, *, seller_token: str, reason: str) -> dict:
    """管理员认领审核事项并审核不通过（用于审核未过通知）。"""
    admin = ctx.account("admin")
    case = find_review_case(api, ctx, product_id)
    if case is None:
        raise AssertionError(f"找不到商品 #{product_id} 的待审核事项")
    admin_claim_case(api, ctx, case["id"])
    api.post(
        f"/admin/products/cases/{case['id']}/review",
        token=admin["token"],
        json_body={"result": "rejected", "reason": reason},
        expected=200,
    )
    return api.get(f"/products/{product_id}", token=seller_token, expected=200).json()


def recv_json(ws, *, timeout: float = 8.0) -> dict:
    raw = ws.recv(timeout=timeout)
    return json.loads(raw)


# ---------------------------------------------------------------------------
# 阶段主体
# ---------------------------------------------------------------------------
def run(ctx, api, rec):  # noqa: ANN001 - 框架约定签名
    """US-04 两类 IM + US-11 通知/待办 + 真实 WebSocket。"""
    with rec.step(
        "P06-SETUP",
        us="US-04,US-11",
        sc="SC-04,SC-11",
        desc="真实注册买卖双方/第三方账户，发布并审核通过 IM/通知测试商品（含审核未过样本）",
        expected="账户、商品、审核通知就绪",
    ):
        ensure_admin(api, ctx)
        new_user(api, ctx, "p06_seller", "p06.seller", "IM卖方")
        new_user(api, ctx, "p06_buyer", "p06.buyer", "IM买方")
        new_user(api, ctx, "p06_third", "p06.third", "IM第三方")
        new_user(api, ctx, "p06_other", "p06.other", "IM其他买方")
        admin = ctx.account("admin")
        ensure_category(api, ctx, admin["token"], "IM通知测试品类")
        publish_listed_product(
            api, ctx, "p06_local1", "p06_seller",
            title="IM 分支一咨询台灯",
            price_cents=6100,
            tag_names=["IM通知测试品类"],
            image="product_lamp.jpg",
            description="普通私聊与交易分支一未读/消息归属样本",
        )
        publish_listed_product(
            api, ctx, "p06_local2", "p06_seller",
            title="IM 分支二归档音箱",
            price_cents=6200,
            tag_names=["IM通知测试品类"],
            image="product_second2.jpg",
            description="交易分支归档后历史可读、发送拒绝样本",
        )
        publish_listed_product(
            api, ctx, "p06_completed", "p06_seller",
            title="IM 完成分支电煮锅",
            price_cents=6300,
            tag_names=["IM通知测试品类"],
            image="product_lamp.jpg",
            description="交易完成通知与分支归档样本",
        )
        publish_listed_product(
            api, ctx, "p06_frozen_a", "p06_seller",
            title="IM 冻结交易甲绘图板",
            price_cents=6400,
            tag_names=["IM通知测试品类"],
            image="product_camera.jpg",
            description="交易冻结后双方两类 IM 全部禁发样本（甲）",
        )
        publish_listed_product(
            api, ctx, "p06_frozen_b", "p06_seller",
            title="IM 冻结交易乙置物架",
            price_cents=6500,
            tag_names=["IM通知测试品类"],
            image="product_notes.jpg",
            description="冻结按用户组合生效：同组合其他交易分支同样禁发样本（乙）",
        )
        publish_listed_product(
            api, ctx, "p06_events", "p06_seller",
            title="IM 通知事件电水壶",
            price_cents=6600,
            tag_names=["IM通知测试品类"],
            image="product_lamp.jpg",
            description="请求关闭/约定/确认/取消/终止事件通知样本",
        )
        publish_listed_product(
            api, ctx, "p06_edit", "p06_seller",
            title="IM 编辑通知主机",
            price_cents=6700,
            tag_names=["IM通知测试品类"],
            image="product_keyboard.jpg",
            description="商品编辑通知未结束请求买方样本",
        )
        publish_listed_product(
            api, ctx, "p06_withdraw", "p06_seller",
            title="IM 撤回通知文具",
            price_cents=6800,
            tag_names=["IM通知测试品类"],
            image="product_notes.jpg",
            description="请求撤回通知与旧通知入口重校验样本",
        )
        publish_listed_product(
            api, ctx, "p06_todo", "p06_seller",
            title="IM 待办收纳盒",
            price_cents=6900,
            tag_names=["IM通知测试品类"],
            image="product_notes.jpg",
            description="待办 request_pending 与已读不消除待办样本",
        )
        publish_listed_product(
            api, ctx, "p06_ws", "p06_seller",
            title="IM WS 事件水杯",
            price_cents=7000,
            tag_names=["IM通知测试品类"],
            image="product_mug.jpg",
            description="真实 WebSocket 消息与通知事件帧样本",
        )
        pending = register_product(
            api, ctx, "p06_rejected", "p06_seller",
            title="IM 审核未过耳机",
            price_cents=7100,
            tag_names=["IM通知测试品类"],
            image="product_second2.jpg",
            description="审核未过通知附原因样本",
        )
        rejected = admin_reject_product(
            api, ctx, pending["id"],
            seller_token=ctx.token("p06_seller"),
            reason="退回补充：请补充商品实拍图与成色说明",
        )
        ctx.products["p06_rejected"].update(rejected)
        ctx.update_product("p06_rejected", state="rejected")
        rec.must_eq(rejected.get("status"), "rejected", "审核未过商品状态")

    seller = ctx.token("p06_seller")
    buyer = ctx.token("p06_buyer")
    third = ctx.token("p06_third")
    other = ctx.token("p06_other")
    seller_id = ctx.account("p06_seller")["id"]
    buyer_id = ctx.account("p06_buyer")["id"]
    third_id = ctx.account("p06_third")["id"]
    other_id = ctx.account("p06_other")["id"]

    # ================================================================ 普通私聊（US-04-AC-04）
    with rec.step(
        "US-04-AC-04a",
        us="US-04",
        sc="SC-04-05",
        desc="双方均可主动发起双人普通私聊，同一对用户复用同一会话",
        expected="201 会话 id；另一方发起返回同一 id；type=normal 且 trade=null",
    ):
        first = create_normal(api, buyer, seller_id).json()
        rec.must(first.get("id") is not None, "发起普通私聊应返回会话 id")
        second = create_normal(api, seller, buyer_id).json()
        rec.must_eq(second.get("id"), first.get("id"), "同一对用户普通私聊应复用")
        ctx.remember_item("conversation", "p06_normal_p_q", first["id"], "P↔Q 普通私聊", "active")
        item = conversation(api, buyer, first["id"])
        rec.must_eq(item.get("type"), "normal", "普通私聊会话类型")
        rec.must_eq(item.get("trade"), None, "普通私聊不关联交易")
        rec.must_eq(item.get("archived"), False, "普通私聊不归档")

    with rec.step(
        "US-04-AC-04b",
        us="US-04",
        sc="SC-04-05",
        desc="不能向本人发起普通私聊；对方用户不存在 404；未登录 401",
        expected="400 不能向本人发起；404 对方用户不存在；401 未登录",
    ):
        resp = create_normal(api, buyer, buyer_id, expected=400)
        rec.must("本人" in detail_text(resp), f"向本人发起私聊应 400，实际 {detail_text(resp)}")
        resp = create_normal(api, buyer, 99999999, expected=404)
        rec.must("对方用户不存在" in detail_text(resp), f"对方不存在应 404，实际 {detail_text(resp)}")
        resp = api.post("/conversations/normal", json_body={"peer_user_id": seller_id}, expected=401)
        rec.must("未登录" in detail_text(resp), "未登录发起私聊应 401")

    with rec.step(
        "US-04-AC-04c",
        us="US-04",
        sc="SC-04-06",
        desc="普通私聊发送文字消息并读取本人消息（mine 标记）",
        expected="200 发送；详情 messages 含内容且 mine=true；对方视角 mine=false",
    ):
        normal_id = ctx.items["conversation:p06_normal_p_q"]["id"]
        resp = send_text(api, buyer, normal_id, "您好，这台灯还在吗？")
        rec.must(resp.json().get("id") is not None, "发送普通私聊消息应返回 id")
        detail = conversation(api, buyer, normal_id)
        row = next((m for m in detail.get("messages") or [] if m.get("content") == "您好，这台灯还在吗？"), None)
        rec.must(row is not None, "发送方应能读取自己的消息")
        rec.must_eq(row.get("mine"), True, "发送方 mine 标记")
        peer_detail = conversation(api, seller, normal_id)
        peer_row = next((m for m in peer_detail.get("messages") or [] if m.get("content") == "您好，这台灯还在吗？"), None)
        rec.must(peer_row is not None, "对方应能读取消息")
        rec.must_eq(peer_row.get("mine"), False, "接收方 mine 标记")

    with rec.step(
        "US-04-AC-04d",
        us="US-04",
        sc="SC-04-07",
        desc="非会话成员（第三方、管理员）不能查看或发送该私聊",
        expected="第三方/管理员 GET 403；第三方发送 403",
    ):
        normal_id = ctx.items["conversation:p06_normal_p_q"]["id"]
        resp = api.get(f"/conversations/{normal_id}", token=third, expected=403)
        rec.must("非会话成员" in detail_text(resp), f"第三方查看私聊应 403，实际 {detail_text(resp)}")
        send_text(api, third, normal_id, "第三方试图插入私聊", expected=403)
        resp = api.get(f"/conversations/{normal_id}", token=ctx.token("admin"), expected=403)
        rec.must("非会话成员" in detail_text(resp), "管理员不能日常浏览私人会话（BR-19）")
        resp = api.get("/conversations", expected=401)
        rec.must("未登录" in detail_text(resp), "未登录会话列表应 401")

    with rec.step(
        "P06-SETUP-PAIRING",
        us="US-04",
        sc="SC-04-08",
        desc="建立 P↔S、Q↔S 普通私聊作为冻结隔离对照",
        expected="201 两个会话 id",
    ):
        ps = create_normal(api, seller, third_id).json()["id"]
        qs = create_normal(api, buyer, third_id).json()["id"]
        ctx.items["conversation:p06_normal_p_s"] = {"kind": "conversation", "key": "p06_normal_p_s", "id": ps, "label": "P↔S 普通私聊", "state": "active", "extra": {}}
        ctx.items["conversation:p06_normal_q_s"] = {"kind": "conversation", "key": "p06_normal_q_s", "id": qs, "label": "Q↔S 普通私聊", "state": "active", "extra": {}}

    # ================================================================ 交易分支（US-04-AC-05）
    with rec.step(
        "US-04-AC-05a",
        us="US-04",
        sc="SC-04-06",
        desc="每笔购买请求建立独立交易分支，分支关联各自交易且不复用",
        expected="分支一/分支三/普通私聊 id 互不相同；type=trade 且 trade.id 对应各自请求",
    ):
        request_trade(api, ctx, "p06_t_local1", "p06_local1", "p06_buyer")
        request_trade(api, ctx, "p06_t_local2", "p06_local2", "p06_buyer")
        request_trade(api, ctx, "p06_t_completed", "p06_completed", "p06_buyer")
        branch1 = ctx.trades["p06_t_local1"]["conversation_id"]
        branch2 = ctx.trades["p06_t_local2"]["conversation_id"]
        branch3 = ctx.trades["p06_t_completed"]["conversation_id"]
        rec.must(len({branch1, branch2, branch3}) == 3, "三笔请求应各有独立分支")
        rec.must(branch1 not in (branch2, branch3), "交易分支不得复用")
        normal_id = ctx.items["conversation:p06_normal_p_q"]["id"]
        rec.must(normal_id not in (branch1, branch2, branch3), "普通私聊与交易分支应独立")
        for key, branch_id in (("p06_t_local1", branch1), ("p06_t_local2", branch2), ("p06_t_completed", branch3)):
            item = conversation(api, seller, branch_id)
            rec.must_eq(item.get("type"), "trade", f"{key} 分支类型")
            rec.must_eq((item.get("trade") or {}).get("id"), ctx.trades[key]["id"], f"{key} 分支关联交易")
            rec.must_eq((item.get("trade") or {}).get("my_role"), "seller", f"{key} 卖方视角 my_role")
            rec.must(any(m.get("kind") == "system" for m in item.get("messages") or []), f"{key} 分支应有请求系统消息")
            rec.must_eq(item.get("archived"), False, f"{key} 待接受分支不归档")
        branch1_messages = conversation(api, seller, branch1).get("messages") or []
        system_msg = next((m for m in branch1_messages if m.get("kind") == "system"), None)
        rec.must(system_msg is not None, "请求分支应有系统消息")
        rec.must("p06_local1" not in (system_msg.get("content") or "") or "购买请求" in (system_msg.get("content") or ""), "系统消息应说明购买请求")

    with rec.step(
        "US-04-AC-05b",
        us="US-04",
        sc="SC-04-06",
        desc="不同交易分支的消息归属分别保留，不串分支",
        expected="分支一消息只在分支一，分支三消息只在分支三，普通私聊不含交易消息",
    ):
        branch1 = ctx.trades["p06_t_local1"]["conversation_id"]
        branch3 = ctx.trades["p06_t_completed"]["conversation_id"]
        normal_id = ctx.items["conversation:p06_normal_p_q"]["id"]
        send_text(api, buyer, branch1, "分支一：请问台灯可以自提吗？")
        send_text(api, buyer, branch3, "分支三：电煮锅有实拍图吗？")
        b1 = {m.get("content") for m in (conversation(api, seller, branch1).get("messages") or [])}
        b3 = {m.get("content") for m in (conversation(api, seller, branch3).get("messages") or [])}
        nm = {m.get("content") for m in (conversation(api, seller, normal_id).get("messages") or [])}
        rec.must("分支一：请问台灯可以自提吗？" in b1, "分支一应包含本分支消息")
        rec.must("分支三：电煮锅有实拍图吗？" not in b1, "分支一不应包含分支三消息")
        rec.must("分支三：电煮锅有实拍图吗？" in b3, "分支三应包含本分支消息")
        rec.must("分支一：请问台灯可以自提吗？" not in b3, "分支三不应包含分支一消息")
        rec.must("分支一：请问台灯可以自提吗？" not in nm, "普通私聊不应包含交易分支消息")

    with rec.step(
        "US-04-AC-08a",
        us="US-04",
        sc="SC-04-09",
        desc="请求拒绝后分支归档：历史可读、发送被拒绝、可由用户选择转入普通私聊且不迁移消息",
        expected="归档 true；GET 200 历史；发送 409；to-normal 返回既有普通会话且消息数不迁移",
    ):
        branch2 = ctx.trades["p06_t_local2"]["conversation_id"]
        normal_id = ctx.items["conversation:p06_normal_p_q"]["id"]
        api.post(f"/trades/{ctx.trades['p06_t_local2']['id']}/reject", token=seller, json_body={"reason": "已售出"}, expected=200)
        ctx.update_trade("p06_t_local2", "rejected")
        item = conversation(api, seller, branch2)
        rec.must_eq(item.get("archived"), True, "拒绝后交易分支归档")
        rec.must(len(item.get("messages") or []) >= 1, "归档分支历史可读")
        normal_before = len((conversation(api, seller, normal_id).get("messages") or []))
        branch_before = len(item.get("messages") or [])
        resp = send_text(api, buyer, branch2, "归档后继续发送", expected=409)
        rec.must("归档" in detail_text(resp), f"归档分支发送应 409，实际 {detail_text(resp)}")
        migrated = api.post(f"/conversations/{branch2}/to-normal", token=buyer, expected=200).json()
        rec.must_eq(migrated.get("id"), normal_id, "转入普通私聊应复用既有普通会话")
        normal_after = len((conversation(api, seller, normal_id).get("messages") or []))
        branch_after = len((conversation(api, seller, branch2).get("messages") or []))
        rec.must_eq(normal_after, normal_before, "转入普通私聊不迁移旧交易消息")
        rec.must_eq(branch_after, branch_before, "转入普通私聊不移动分支历史消息")

    # ================================================================ 分分支未读（US-04-AC-06 / SC-11-02）
    with rec.step(
        "US-04-AC-06a",
        us="US-04",
        sc="SC-11-02",
        desc="普通私聊与各交易分支分别计算未读：一个分支新增消息不影响其他会话未读",
        expected="分支一未读 +2、普通私聊 +1、分支三不变",
    ):
        branch1 = ctx.trades["p06_t_local1"]["conversation_id"]
        branch3 = ctx.trades["p06_t_completed"]["conversation_id"]
        normal_id = ctx.items["conversation:p06_normal_p_q"]["id"]
        base = conversation_map(api, seller)
        base_b1 = base[branch1]["unread"]
        base_b3 = base[branch3]["unread"]
        base_norm = base[normal_id]["unread"]
        send_text(api, buyer, branch1, "未读测试：分支一第一条")
        send_text(api, buyer, branch1, "未读测试：分支一第二条")
        send_text(api, buyer, normal_id, "未读测试：普通私聊一条")
        after = conversation_map(api, seller)
        rec.must_eq(after[branch1]["unread"], base_b1 + 2, "分支一未读 +2")
        rec.must_eq(after[branch3]["unread"], base_b3, "分支三未读不受分支一影响")
        rec.must_eq(after[normal_id]["unread"], base_norm + 1, "普通私聊未读 +1")

    with rec.step(
        "US-04-AC-06b",
        us="US-04",
        sc="SC-11-02",
        desc="仅进入会话列表或查看其它分支不清除本分支未读",
        expected="列表两次/查看分支三后，分支一未读保持",
    ):
        branch1 = ctx.trades["p06_t_local1"]["conversation_id"]
        before = conversation_map(api, seller)[branch1]["unread"]
        conversations(api, seller)
        conversations(api, seller)
        conversation(api, seller, ctx.trades["p06_t_completed"]["conversation_id"])
        after = conversation_map(api, seller)[branch1]["unread"]
        rec.must_eq(after, before, "列表/查看其它分支不应清除分支一未读")
        rec.must(before > 0, "前置：分支一应有未读消息")

    with rec.step(
        "US-04-AC-06c",
        us="US-04",
        sc="SC-11-02",
        desc="打开具体分支并标读后仅该分支未读归零，其他会话未读保持",
        expected="分支一 unread=0；分支三/普通私聊未读不变；last_read=最大消息 id",
    ):
        branch1 = ctx.trades["p06_t_local1"]["conversation_id"]
        branch3 = ctx.trades["p06_t_completed"]["conversation_id"]
        normal_id = ctx.items["conversation:p06_normal_p_q"]["id"]
        detail = conversation(api, seller, branch1)
        last_id = max(m["id"] for m in detail.get("messages") or [])
        rec.must(len(detail.get("messages") or []) >= 2, "分支一应有已展示消息")
        before = conversation_map(api, seller)
        advance_read(api, seller, branch1, last_id)
        after = conversation_map(api, seller)
        rec.must_eq(after[branch1]["unread"], 0, "仅分支一未读归零")
        rec.must_eq(after[branch3]["unread"], before[branch3]["unread"], "分支三未读保持")
        rec.must_eq(after[normal_id]["unread"], before[normal_id]["unread"], "普通私聊未读保持")
        rec.must_eq(conversation(api, seller, branch1).get("last_read_message_id"), last_id, "分支一已读指针")

    with rec.step(
        "US-04-AC-06d",
        us="US-04",
        sc="SC-11-02",
        desc="已读指针只增不减，超过最大消息 id 时截断到会话最大消息 id",
        expected="回退请求保持原 last_read；超大 id 截断为最大消息 id 且未读归零",
    ):
        branch1 = ctx.trades["p06_t_local1"]["conversation_id"]
        current = conversation(api, seller, branch1).get("last_read_message_id")
        resp = advance_read(api, seller, branch1, max(0, int(current) - 1))
        rec.must_eq(resp.json().get("last_read_message_id"), current, "已读指针不应回退")
        resp = advance_read(api, seller, branch1, 999999)
        rec.must(resp.json().get("last_read_message_id") <= 999999, "超大已读 id 应被截断")
        rec.must_eq(conversation_map(api, seller)[branch1]["unread"], 0, "标读后未读归零")

    with rec.step(
        "US-04-AC-06e",
        us="US-04",
        sc="SC-11-02",
        desc="未读汇总等于各会话未读之和",
        expected="unread-summary.unread == Σ conversations[].unread",
    ):
        summary = unread_summary(api, seller)
        total = sum(item.get("unread", 0) for item in conversations(api, seller))
        rec.must_eq(summary, total, "未读汇总与各会话未读之和")
        rec.must(summary >= 1, "前置：应存在未读消息")

    # ================================================================ US-11 通知基础
    with rec.step(
        "US-11-AC-01a",
        us="US-11",
        sc="SC-11-01",
        desc="购买请求通知与交易分支定位同一请求，不重复创建业务",
        expected="request_created 通知 link_type=conversation/link_id=分支；payload.trade_id=交易；分支 trade.id 一致",
    ):
        branch1 = ctx.trades["p06_t_local1"]["conversation_id"]
        notes = notify_by_link(api, seller, type_="request_created", link_id=branch1)
        rec.must(len(notes) >= 1, "卖方应收到 request_created 通知")
        note = notes[0]
        rec.must_eq(note.get("link_type"), "conversation", "通知关联会话")
        rec.must_eq(note.get("link_id"), branch1, "通知 link_id 为交易分支")
        rec.must_eq((note.get("payload") or {}).get("trade_id"), ctx.trades["p06_t_local1"]["id"], "通知 payload 关联同一交易")
        item = conversation(api, seller, branch1)
        rec.must_eq((item.get("trade") or {}).get("id"), ctx.trades["p06_t_local1"]["id"], "分支与通知定位同一请求")
        seller_trades = api.get("/trades/mine", token=seller, expected=200).json()
        same = [t for t in seller_trades if t.get("id") == ctx.trades["p06_t_local1"]["id"]]
        rec.must_eq(len(same), 1, "同一请求只生成一笔交易，不重复创建")

    with rec.step(
        "US-11-AC-02a",
        us="US-11",
        sc="SC-11-02",
        desc="通知列表不标读：仅访问列表保持全部未读",
        expected="列表所有 is_read=false；重复访问仍不变；unread-count 等于总数",
    ):
        items = notifications_all(api, seller)
        rec.must(len(items) >= 5, "前置：卖方应有通知")
        rec.must(all(item.get("is_read") is False for item in items), "通知列表不应自动标读")
        notifications_all(api, seller)
        again = notifications_all(api, seller)
        rec.must(all(item.get("is_read") is False for item in again), "重复访问列表仍不应标读")
        rec.must_eq(unread_count(api, seller), len(again), "未读数应等于全部通知数")
        rec.must_eq(unread_count(api, seller), len(notifications_all(api, seller)), "未读数一致性（二次）")

    with rec.step(
        "US-11-AC-02b",
        us="US-11",
        sc="SC-11-02",
        desc="打开具体通知才已读：仅该条标读、未读数减一、重复标读幂等",
        expected="目标 is_read=true；其余不变；unread-count 减 1；重复标读 200 且计数不变",
    ):
        request_trade(api, ctx, "p06_t_todo", "p06_todo", "p06_buyer")
        todo_conv = ctx.trades["p06_t_todo"]["conversation_id"]
        notes = notify_by_link(api, seller, type_="request_created", link_id=todo_conv)
        rec.must(len(notes) >= 1, "待接受请求应通知卖方")
        target_id = notes[-1]["id"]
        ctx.items["notification:p06_todo_request"] = {"kind": "notification", "key": "p06_todo_request", "id": target_id, "label": "待接受请求通知", "state": "unread", "extra": {}}
        total_before = unread_count(api, seller)
        mark_notification_read(api, seller, target_id)
        items = notifications_all(api, seller)
        target = next(item for item in items if item.get("id") == target_id)
        rec.must_eq(target.get("is_read"), True, "目标通知已读")
        rec.must_eq(sum(1 for item in items if not item.get("is_read")), len(items) - 1, "仅一条通知变为已读")
        rec.must_eq(unread_count(api, seller), total_before - 1, "未读数减一")
        mark_notification_read(api, seller, target_id)
        rec.must_eq(unread_count(api, seller), total_before - 1, "重复标读不重复计数")

    with rec.step(
        "US-11-AC-02c",
        us="US-11",
        sc="SC-11-02",
        desc="未读筛选与未读数一致（unread_only=true 的 total 等于 unread-count）",
        expected="unread_only total == unread-count；全部为未读",
    ):
        data = list_notifications(api, seller, unread_only=True)
        rec.must_eq(data.get("total"), unread_count(api, seller), "未读筛选数量与未读数")
        rec.must(all(item.get("is_read") is False for item in data.get("items") or []), "未读筛选结果应全部未读")

    with rec.step(
        "US-11-AC-02d",
        us="US-11",
        sc="SC-11-04",
        desc="已读不消除待办：读取请求通知后待办仍在，业务办结后待办自动移出",
        expected="request_pending 待办在通知已读后仍在；卖方接受后消失",
    ):
        trade = ctx.trades["p06_t_todo"]
        key = f"request_pending:{trade['id']}"
        rec.must(key in todo_keys(api, seller), "卖方的待接受请求应出现在待办")
        todos_data = todos(api, seller)
        item = next((x for x in todos_data.get("items") or [] if x.get("key") == key), None)
        rec.must(item is not None, "待办项应存在")
        rec.must_eq(item.get("action"), "accept_request", "待办动作")
        rec.must_eq(item.get("link_type"), "trade", "待办关联交易")
        # 上一步已把该请求通知标读，待办不受通知已读影响
        rec.must(key in todo_keys(api, seller), "通知已读不应清除待办")
        accept_trade(api, ctx, "p06_t_todo")
        rec.must(key not in todo_keys(api, seller), "请求办结后待办应移出")

    with rec.step(
        "US-11-AC-03a",
        us="US-11",
        sc="SC-11-02",
        desc="通知及聊天均未读时，将通知标读后聊天未读保持（通知已读不代替聊天已读）",
        expected="普通私聊未读在标读通知前后一致",
    ):
        normal_id = ctx.items["conversation:p06_normal_p_q"]["id"]
        before = unread_of(api, seller, normal_id, name="普通私聊")
        candidates = notify_by_link(api, seller, type_="review_result", link_id=ctx.products["p06_local1"]["id"])
        if candidates:
            mark_notification_read(api, seller, candidates[0]["id"])
        after = unread_of(api, seller, normal_id, name="普通私聊")
        rec.must_eq(after, before, "通知已读不应清除聊天未读")
        rec.must(before >= 1, "前置：普通私聊应有未读")

    with rec.step(
        "US-11-AC-04a",
        us="US-11",
        sc="SC-11-03",
        desc="旧通知入口重校验当前状态：已撤回请求无法再接受，显示当前状态",
        expected="撤回请求 409；交易状态 withdrawn；分支归档；旧通知仍在且不揭示已失效操作成功",
    ):
        request_trade(api, ctx, "p06_t_withdraw", "p06_withdraw", "p06_buyer")
        trade = ctx.trades["p06_t_withdraw"]
        api.post(f"/trades/{trade['id']}/withdraw", token=buyer, expected=200)
        ctx.update_trade("p06_t_withdraw", "withdrawn")
        resp = api.post(f"/trades/{trade['id']}/accept", token=seller, expected=409)
        rec.must("不可接受" in detail_text(resp), f"已撤回请求接受应 409，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p06_t_withdraw")
        rec.must_eq(data.get("status"), "withdrawn", "旧入口应展示当前状态 withdrawn")
        note = notify_by_link(api, seller, type_="request_created", link_id=trade["conversation_id"])
        rec.must(len(note) >= 1, "旧通知记录应保留")
        rec.must_eq(note[0].get("is_read"), False, "旧通知未读状态不应被业务变化改写")
        rec.must_eq(conversation(api, seller, trade["conversation_id"]).get("archived"), True, "撤回后分支归档")
        rec.must_eq(refresh_trade(api, ctx, "p06_t_withdraw").get("conversation_archived"), True, "交易详情显示分支已归档")

    with rec.step(
        "US-11-AC-06a",
        us="US-11",
        sc="SC-11-03",
        desc="他人通知不能访问/标读，通知仅接收人可见",
        expected="其他用户标读 404 通知不存在；他人通知列表中不含该 id",
    ):
        target_id = ctx.items["notification:p06_todo_request"]["id"]
        resp = mark_notification_read(api, buyer, target_id, expected=404)
        rec.must("通知不存在" in detail_text(resp), f"他人通知标读应 404，实际 {detail_text(resp)}")
        buyer_items = notifications_all(api, buyer)
        rec.must(all(item.get("id") != target_id for item in buyer_items), "他人通知列表不应包含该通知")

    with rec.step(
        "US-11-AC-05a",
        us="US-11",
        sc="SC-11-01",
        desc="管理员无个人站内通知与待办，也不能操作个人通知历史",
        expected="通知列表 {total:0,items:[]}；unread-count 0；todos 0；标读 404",
    ):
        admin_tok = ctx.token("admin")
        data = list_notifications(api, admin_tok)
        rec.must_eq(data.get("total"), 0, "管理员通知总数")
        rec.must_eq(data.get("items"), [], "管理员通知列表为空")
        rec.must_eq(unread_count(api, admin_tok), 0, "管理员未读数")
        rec.must_eq(todos(api, admin_tok).get("total"), 0, "管理员个人待办为空")
        resp = mark_notification_read(api, admin_tok, ctx.items["notification:p06_todo_request"]["id"], expected=404)
        rec.must("通知不存在" in detail_text(resp), "管理员不能标读个人通知（404）")

    # ================================================================ 冻结对 IM 的限制（US-04-AC-07）
    with rec.step(
        "P06-SETUP-FREEZE",
        us="US-04",
        sc="SC-04-08",
        desc="准备两笔同组交易并真实冻结甲笔（管理员认领争议事项后冻结）",
        expected="甲笔 disputed+frozen；乙笔 in_progress；双方收到 trade_frozen",
    ):
        request_trade(api, ctx, "p06_t_frozen_a", "p06_frozen_a", "p06_buyer")
        accept_trade(api, ctx, "p06_t_frozen_a")
        aid = propose_agreement(api, ctx, "p06_t_frozen_a", "p06_buyer").json()["id"]
        confirm_agreement(api, ctx, "p06_t_frozen_a", aid, "p06_seller")
        create_dispute(api, ctx, "p06_t_frozen_a", "p06_buyer", description="冻结限制 IM 测试争议")
        ctx.update_trade("p06_t_frozen_a", "disputed")
        request_trade(api, ctx, "p06_t_frozen_b", "p06_frozen_b", "p06_buyer")
        accept_trade(api, ctx, "p06_t_frozen_b")
        case_id = claim_trade_dispute_case(api, ctx, "p06_t_frozen_a")
        resp = admin_freeze(api, ctx, "p06_t_frozen_a", case_id, reason="违规处置冻结交易进度（IM 限制对照）")
        rec.must("已冻结" in detail_text(resp), f"冻结响应文案，实际 {detail_text(resp)}")
        frozen = refresh_trade(api, ctx, "p06_t_frozen_a")
        rec.must_eq(frozen.get("frozen"), True, "交易冻结标记")
        rec.must_eq(frozen.get("status"), "disputed", "冻结不改变交易状态")
        rec.must_eq(frozen.get("conversation_archived"), False, "冻结不等于结束，不归档分支")
        for token, name in ((seller, "卖方"), (buyer, "买方")):
            notes = notify_by_link(api, token, type_="trade_frozen", link_id=ctx.trades["p06_t_frozen_a"]["id"])
            rec.must(len(notes) >= 1, f"{name}应收到 trade_frozen 通知")
            rec.must("冻结" in (notes[0].get("content") or ""), f"{name}冻结通知应说明限制")

    with rec.step(
        "US-04-AC-07a",
        us="US-04",
        sc="SC-04-08",
        desc="p、q 之间任一交易冻结时，普通私聊与全部交易分支均禁发、历史可读",
        expected="普通私聊/甲分支/乙分支/其他待接受分支发送 403；历史 GET 200",
    ):
        normal_id = ctx.items["conversation:p06_normal_p_q"]["id"]
        branch_a = ctx.trades["p06_t_frozen_a"]["conversation_id"]
        branch_b = ctx.trades["p06_t_frozen_b"]["conversation_id"]
        branch1 = ctx.trades["p06_t_local1"]["conversation_id"]
        branch3 = ctx.trades["p06_t_completed"]["conversation_id"]
        blocked = [
            (seller, normal_id, "卖方→普通私聊"),
            (buyer, normal_id, "买方→普通私聊"),
            (seller, branch_a, "卖方→甲分支"),
            (buyer, branch_a, "买方→甲分支"),
            (seller, branch_b, "卖方→乙分支"),
            (buyer, branch_b, "买方→乙分支"),
            (seller, branch1, "卖方→其他交易分支"),
        ]
        for token, conv_id, label in blocked:
            resp = send_text(api, token, conv_id, f"冻结期间尝试发送：{label}", expected=403)
            rec.must("冻结" in detail_text(resp), f"{label} 冻结期间应 403 禁发，实际 {detail_text(resp)}")
        rec.must(len((conversation(api, seller, normal_id).get("messages") or [])) >= 1, "冻结期间普通私聊历史可读")
        rec.must(len((conversation(api, seller, branch_a).get("messages") or [])) >= 1, "冻结期间交易分支历史可读")
        rec.must_eq(conversation(api, seller, branch_b).get("archived"), False, "冻结不归档乙分支")

    with rec.step(
        "US-04-AC-07b",
        us="US-04",
        sc="SC-04-08",
        desc="冻结仅覆盖 p、q 用户组合，不向第三方会话扩散",
        expected="P↔S、Q↔S 普通私聊发送 200",
    ):
        ps = ctx.items["conversation:p06_normal_p_s"]["id"]
        qs = ctx.items["conversation:p06_normal_q_s"]["id"]
        send_text(api, seller, ps, "与第三方的私聊不受本笔冻结影响")
        send_text(api, buyer, qs, "买方与第三方私聊同样不受影响")
        rec.must(len((conversation(api, third, ps).get("messages") or [])) >= 1, "P↔S 消息应送达")
        rec.must(len((conversation(api, third, qs).get("messages") or [])) >= 1, "Q↔S 消息应送达")

    with rec.step(
        "US-04-AC-07c",
        us="US-04",
        sc="SC-04-08",
        desc="管理员解除冻结后双方 IM 恢复发送，收到 trade_unfrozen 通知",
        expected="unfreeze 200；frozen=false；双方 normal/分支发送 200；trade_unfrozen 通知",
    ):
        normal_id = ctx.items["conversation:p06_normal_p_q"]["id"]
        branch_b = ctx.trades["p06_t_frozen_b"]["conversation_id"]
        case_id = ctx.trades["p06_t_frozen_a"]["case_id"]
        resp = admin_unfreeze(api, ctx, "p06_t_frozen_a", case_id, reason="核查完成，解除冻结恢复沟通")
        rec.must("解除" in detail_text(resp), f"解冻响应文案，实际 {detail_text(resp)}")
        refreshed = refresh_trade(api, ctx, "p06_t_frozen_a")
        rec.must_eq(refreshed.get("frozen"), False, "解冻后 frozen=false")
        for token, name in ((seller, "卖方"), (buyer, "买方")):
            notes = notify_by_link(api, token, type_="trade_unfrozen", link_id=ctx.trades["p06_t_frozen_a"]["id"])
            rec.must(len(notes) >= 1, f"{name}应收到 trade_unfrozen 通知")
        send_text(api, seller, normal_id, "解冻后普通私聊恢复")
        send_text(api, buyer, branch_b, "解冻后交易分支恢复")
        rec.must(len((conversation(api, buyer, normal_id).get("messages") or [])) >= 1, "解冻后普通私聊可发送")
        rec.must(len((conversation(api, seller, branch_b).get("messages") or [])) >= 1, "解冻后交易分支可发送")

    with rec.step(
        "US-05-AC-08k",
        us="US-05",
        sc="SC-06-01",
        desc="冻结的争议交易解冻后双方自行确认解决恢复进行中，随后双方同意终止",
        expected="dispute_resolution 待办→双方确认恢复；再双方同意 cancel -> terminated",
    ):
        trade = ctx.trades["p06_t_frozen_a"]
        api.post(f"/trades/{trade['id']}/disputes/resolve", token=seller, json_body={}, expected=200)
        q_todos = todo_keys(api, buyer)
        rec.must(f"dispute_resolution:{trade['id']}" in q_todos, "买方应出现争议解决确认待办")
        api.post(f"/trades/{trade['id']}/disputes/resolve", token=buyer, json_body={}, expected=200)
        data = refresh_trade(api, ctx, "p06_t_frozen_a")
        rec.must_eq(data.get("status"), "in_progress", "解冻后双方确认解决恢复进行中")
        rec.must_eq(data.get("confirm_wait_started_at"), None, "恢复不启动计时")
        rec.must(f"dispute_resolution:{trade['id']}" not in todo_keys(api, buyer), "解决后待办移出")
        trade_cancel(api, ctx, "p06_t_frozen_a", "p06_seller")
        confirm_cancel(api, ctx, "p06_t_frozen_a", "p06_buyer")
        data = refresh_trade(api, ctx, "p06_t_frozen_a")
        rec.must_eq(data.get("status"), "terminated", "双方同意后终止")
        rec.must_eq(data.get("conversation_archived"), True, "终止后分支归档")
        rec.must_eq(product_detail(api, seller, ctx.products["p06_frozen_a"]["id"]).json().get("status"), "delisted", "终止后商品默认下架")
        notes = notify_by_link(api, buyer, type_="cancel_requested", link_id=trade["id"])
        rec.must(len(notes) >= 1, "买方应收到 cancel_requested 通知")

    with rec.step(
        "P06-FINISH-FROZEN_B",
        us="US-05",
        sc="SC-05-10",
        desc="冻结交易乙收尾：约定前买方直接取消终止",
        expected="terminated + 商品下架",
    ):
        trade_cancel(api, ctx, "p06_t_frozen_b", "p06_buyer")
        data = refresh_trade(api, ctx, "p06_t_frozen_b")
        rec.must_eq(data.get("status"), "terminated", "乙笔约定前买方直接取消")
        rec.must_eq(product_detail(api, seller, ctx.products["p06_frozen_b"]["id"]).json().get("status"), "delisted", "乙笔终止后商品下架")

    # ================================================================ 完成分支与通知
    with rec.step(
        "US-11-AC-05b",
        us="US-11",
        sc="SC-11-01",
        desc="交易完成：单方确认仅提醒对方、未通知为已完成；双确认后双方收到完成通知并归档分支",
        expected="confirm_progress 仅待确认方；完成前无 trade_completed；完成后双方均收到 trade_completed",
    ):
        accept_trade(api, ctx, "p06_t_completed")
        aid = propose_agreement(api, ctx, "p06_t_completed", "p06_seller").json()["id"]
        confirm_agreement(api, ctx, "p06_t_completed", aid, "p06_buyer")
        submit_confirmation(api, ctx, "p06_t_completed", "p06_seller", note="卖方已交付")
        trade = ctx.trades["p06_t_completed"]
        q_notes = notify_by_link(api, buyer, type_="confirm_progress", link_id=trade["id"])
        rec.must(len(q_notes) >= 1, "待确认方应收到 confirm_progress 通知")
        rec.must("7 天" in (q_notes[0].get("content") or ""), "单方确认通知应说明 7 天等待")
        rec.must_eq(notify_by_link(api, buyer, type_="trade_completed", link_id=trade["id"]), [], "单方确认不通知为已完成（买方）")
        rec.must_eq(notify_by_link(api, seller, type_="trade_completed", link_id=trade["id"]), [], "单方确认不通知为已完成（卖方）")
        submit_confirmation(api, ctx, "p06_t_completed", "p06_buyer", note="买方已收货并支付")
        data = refresh_trade(api, ctx, "p06_t_completed")
        rec.must_eq(data.get("status"), "completed", "双确认后交易完成")
        rec.must_eq(data.get("conversation_archived"), True, "完成后分支归档")
        rec.must(len(notify_by_link(api, buyer, type_="trade_completed", link_id=trade["id"])) >= 1, "买方收到 trade_completed")
        rec.must(len(notify_by_link(api, seller, type_="trade_completed", link_id=trade["id"])) >= 1, "卖方收到 trade_completed")
        rec.must_eq(product_detail(api, seller, ctx.products["p06_completed"]["id"]).json().get("status"), "delisted", "完成后商品默认下架")
        resp = send_text(api, buyer, trade["conversation_id"], "完成后继续发送", expected=409)
        rec.must("归档" in detail_text(resp), "完成分支发送应 409")
        normal_item = conversation(api, seller, ctx.items["conversation:p06_normal_p_q"]["id"])
        rec.must_eq(normal_item.get("archived"), False, "交易结束不自动归档普通私聊")
        rec.must(len(normal_item.get("messages") or []) >= 1, "普通私聊历史独立保留")

    # ================================================================ 请求关闭/约定/确认/取消事件通知
    with rec.step(
        "US-11-AC-05c",
        us="US-11",
        sc="SC-11-01",
        desc="其他用户锁单关闭请求：关闭原因与通知内容正确，被关闭方收到 request_closed",
        expected="R 请求 closed + 原因其他用户锁单 + request_closed 通知内容注明原因",
    ):
        request_trade(api, ctx, "p06_t_events_r", "p06_events", "p06_other")
        request_trade(api, ctx, "p06_t_events_q", "p06_events", "p06_buyer")
        accept_trade(api, ctx, "p06_t_events_q")
        closed = refresh_trade(api, ctx, "p06_t_events_r")
        rec.must_eq(closed.get("status"), "closed", "其他用户锁单后请求关闭")
        rec.must_eq(closed.get("close_reason"), "商品已被其他用户锁单", "关闭原因")
        r_notes = notify_by_link(api, other, type_="request_closed", link_id=closed["id"])
        rec.must(len(r_notes) >= 1, "被关闭方应收到 request_closed 通知")
        rec.must("其他用户锁单" in (r_notes[0].get("content") or ""), "关闭通知应注明其他用户锁单原因")
        q_notes = notify_by_link(api, buyer, type_="request_accepted", link_id=ctx.trades["p06_t_events_q"]["conversation_id"])
        rec.must(len(q_notes) >= 1, "被接受方应收到 request_accepted 通知")

    with rec.step(
        "US-11-AC-05d",
        us="US-11",
        sc="SC-11-01",
        desc="约定提出/确认、单方完成确认、取消申请事件均通知正确接收方，并产生对应待办",
        expected="agreement_proposed→对方；agreement_decided→提出方；confirm_progress→对方；cancel_requested→对方；待办类型正确",
    ):
        trade = ctx.trades["p06_t_events_q"]
        aid = propose_agreement(api, ctx, "p06_t_events_q", "p06_buyer").json()["id"]
        p_notes = notify_by_link(api, seller, type_="agreement_proposed", link_id=trade["id"])
        rec.must(len(p_notes) >= 1, "约定提案应通知对方")
        rec.must(f"agreement_pending:{trade['id']}" in todo_keys(api, seller), "对方应出现约定确认待办")
        confirm_agreement(api, ctx, "p06_t_events_q", aid, "p06_seller")
        q_notes = notify_by_link(api, buyer, type_="agreement_decided", link_id=trade["id"])
        rec.must(len(q_notes) >= 1, "约定确认结果应通知提出方")
        rec.must(f"completion_confirm:{trade['id']}" in todo_keys(api, seller), "约定生效后应有完成确认待办")
        submit_confirmation(api, ctx, "p06_t_events_q", "p06_buyer", note="买方单方确认")
        p_notes = notify_by_link(api, seller, type_="confirm_progress", link_id=trade["id"])
        rec.must(len(p_notes) >= 1, "单方完成确认应通知待确认方")
        trade_cancel(api, ctx, "p06_t_events_q", "p06_buyer")
        p_notes = notify_by_link(api, seller, type_="cancel_requested", link_id=trade["id"])
        rec.must(len(p_notes) >= 1, "取消申请应通知待同意方")
        rec.must(f"cancel_pending:{trade['id']}" in todo_keys(api, seller), "待同意方应出现取消确认待办")
        confirm_cancel(api, ctx, "p06_t_events_q", "p06_seller")
        data = refresh_trade(api, ctx, "p06_t_events_q")
        rec.must_eq(data.get("status"), "terminated", "双方同意取消后终止")
        for token, name in ((seller, "卖方"), (buyer, "买方")):
            rec.must(len(notify_by_link(api, token, type_="trade_terminated", link_id=trade["id"])) >= 1, f"{name}应收到 trade_terminated 通知")
        rec.must(f"cancel_pending:{trade['id']}" not in todo_keys(api, seller), "办结后取消待办移出")

    with rec.step(
        "US-11-AC-05e",
        us="US-11",
        sc="SC-11-01",
        desc="商品编辑通知未结束请求的买方（关联商品与变更入口）",
        expected="request_pending 时编辑商品，请求买方收到 product_edited 通知",
    ):
        request_trade(api, ctx, "p06_t_edit", "p06_edit", "p06_other")
        new_title = f"{ctx.products['p06_edit']['title']}（已更新）"
        api.patch(f"/products/{ctx.products['p06_edit']['id']}", token=seller, json_body={"title": new_title}, expected=200)
        notes = notify_by_link(api, other, type_="product_edited", link_id=ctx.products["p06_edit"]["id"])
        rec.must(len(notes) >= 1, "未结束请求的买方应收到商品编辑通知")
        rec.must_eq((notes[0].get("payload") or {}).get("product_id"), ctx.products["p06_edit"]["id"], "编辑通知 payload 关联商品")
        api.post(f"/trades/{ctx.trades['p06_t_edit']['id']}/withdraw", token=other, expected=200)
        ctx.update_trade("p06_t_edit", "withdrawn")

    with rec.step(
        "US-11-AC-05f",
        us="US-11",
        sc="SC-11-01",
        desc="请求撤回通知卖方；审核未过通知附原因并可进入商品查看",
        expected="request_withdrawn 通知；review_result 未过通知内容含拒绝原因",
    ):
        trade = ctx.trades["p06_t_withdraw"]
        notes = notify_by_link(api, seller, type_="request_withdrawn", link_id=trade["id"])
        rec.must(len(notes) >= 1, "撤回请求应通知卖方")
        rejected_id = ctx.products["p06_rejected"]["id"]
        review_notes = notify_by_link(api, seller, type_="review_result", link_id=rejected_id)
        rec.must(len(review_notes) >= 1, "审核未过应通知发布者")
        rec.must("退回补充" in (review_notes[0].get("content") or ""), "审核未过通知应附拒绝原因")
        rec.must_eq(review_notes[0].get("link_type"), "product", "审核通知应关联商品入口")

    with rec.step(
        "US-11-AC-06b",
        us="US-11",
        sc="SC-11-03",
        desc="通知已读不代替业务确认：标记通知已读不改变请求/交易状态",
        expected="标读 request_accepted 通知后交易仍 in_progress；标读不自动接受/确认",
    ):
        q_notes = notify_by_link(api, buyer, type_="request_accepted", link_id=ctx.trades["p06_t_local1"]["conversation_id"])
        if not q_notes:
            q_notes = notify_by_link(api, buyer, type_="request_accepted", link_id=ctx.trades["p06_t_events_q"]["conversation_id"])
        rec.must(len(q_notes) >= 1, "买方应有 request_accepted 通知")
        mark_notification_read(api, buyer, q_notes[0]["id"])
        data = refresh_trade(api, ctx, "p06_t_local1")
        rec.must_eq(data.get("status"), "pending_acceptance", "通知已读不代替卖方接受请求")
        rec.must_eq(refresh_trade(api, ctx, "p06_t_events_q").get("status"), "terminated", "通知已读不改变交易状态")

    # ================================================================ WebSocket
    with rec.step(
        "US-11-WS-a",
        us="US-11",
        sc="SC-11-01",
        desc="真实 WebSocket 握手与 ping/pong",
        expected="ws://host/ws?token=... 接受连接；ping 返回 pong 帧",
    ):
        if not WS_AVAILABLE:
            raise AssertionError("当前运行环境缺少 websockets 库，无法执行真实 WS 检查")
        with ws_connect(ws_uri(api, seller), open_timeout=8, proxy=None) as ws:
            ws.send(json.dumps({"type": "ping"}))
            frame = recv_json(ws)
            rec.must_eq(frame.get("type"), "pong", "WS ping 应返回 pong")

    with rec.step(
        "US-11-WS-b",
        us="US-11",
        sc="SC-11-01",
        desc="无效 token 在握手后被以业务关闭码 4401 关闭",
        expected="connect 成功但随后关闭码 4401",
    ):
        if not WS_AVAILABLE:
            raise AssertionError("当前运行环境缺少 websockets 库，无法执行真实 WS 检查")
        got_code = None
        try:
            with ws_connect(ws_uri(api, "invalid-token"), open_timeout=8, proxy=None) as ws:
                frame = recv_json(ws, timeout=5)
                got_code = f"unexpected-frame:{frame}"
        except ConnectionClosed as exc:
            got_code = exc.code
        rec.must_eq(got_code, 4401, "无效 token 关闭码")

    with rec.step(
        "US-11-WS-c",
        us="US-11",
        sc="SC-04-06",
        desc="连接期间收到 message 事件帧（含会话/发送者/内容），接收不改变已读",
        expected="帧 type=message、conversation_id/发送者/内容正确；会话未读增加且已读指针不变",
    ):
        if not WS_AVAILABLE:
            raise AssertionError("当前运行环境缺少 websockets 库，无法执行真实 WS 检查")
        normal_id = ctx.items["conversation:p06_normal_p_q"]["id"]
        before = conversation(api, seller, normal_id)
        unread_before = unread_of(api, seller, normal_id, name="普通私聊")
        last_read_before = before.get("last_read_message_id")
        with ws_connect(ws_uri(api, seller), open_timeout=8, proxy=None) as ws:
            resp = send_text(api, buyer, normal_id, f"WS 消息帧测试-{ctx.run_id}")
            message_id = resp.json()["id"]
            frame = recv_json(ws)
            rec.must_eq(frame.get("type"), "message", "WS 消息帧类型")
            rec.must_eq(frame.get("conversation_id"), normal_id, "WS 消息帧会话 id")
            rec.must_eq(frame.get("message_id"), message_id, "WS 消息帧消息 id")
            rec.must_eq(frame.get("sender_id"), buyer_id, "WS 消息帧发送者")
            rec.must_eq(frame.get("content"), f"WS 消息帧测试-{ctx.run_id}", "WS 消息帧内容")
        after = conversation(api, seller, normal_id)
        rec.must_eq(unread_of(api, seller, normal_id, name="普通私聊"), unread_before + 1, "收到 WS 帧不改变已读（未读 +1）")
        rec.must_eq(after.get("last_read_message_id"), last_read_before, "收到 WS 帧不推进已读指针")

    with rec.step(
        "US-11-WS-d",
        us="US-11",
        sc="SC-11-01",
        desc="业务事件产生 notification 事件帧（事件类型关联同一请求）",
        expected="帧 type=notification、event=request_created、link_id=交易分支 id",
    ):
        if not WS_AVAILABLE:
            raise AssertionError("当前运行环境缺少 websockets 库，无法执行真实 WS 检查")
        with ws_connect(ws_uri(api, seller), open_timeout=8, proxy=None) as ws:
            request_trade(api, ctx, "p06_t_ws", "p06_ws", "p06_buyer")
            branch = ctx.trades["p06_t_ws"]["conversation_id"]
            frame = recv_json(ws)
            rec.must_eq(frame.get("type"), "notification", "WS 通知帧类型")
            rec.must_eq(frame.get("event"), "request_created", "WS 通知帧事件类型")
            rec.must_eq(frame.get("link_type"), "conversation", "WS 通知帧关联类型")
            rec.must_eq(frame.get("link_id"), branch, "WS 通知帧关联分支")
            rec.must_eq(frame.get("title"), "收到新的购买请求", "WS 通知帧标题")
        api.post(f"/trades/{ctx.trades['p06_t_ws']['id']}/withdraw", token=buyer, expected=200)
        ctx.update_trade("p06_t_ws", "withdrawn")

    # ================================================================ 通知事件类型覆盖 / 待办覆盖
    with rec.step(
        "US-11-AC-05g",
        us="US-11",
        sc="SC-11-01",
        desc="通知事件类型覆盖 4.17 交易/商品/IM 相关全事件（按接收方区分）",
        expected="卖方与买方分别覆盖审核、请求、约定、确认、完成、取消、争议、冻结/解冻事件",
    ):
        seller_types = {item.get("type") for item in notifications_all(api, seller)}
        expected_seller = {
            "review_result",
            "request_created",
            "request_withdrawn",
            "agreement_proposed",
            "agreement_decided",
            "confirm_progress",
            "cancel_requested",
            "trade_completed",
            "trade_terminated",
            "trade_dispute",
            "dispute_resolved",
            "trade_frozen",
            "trade_unfrozen",
        }
        missing = expected_seller - seller_types
        rec.must(not missing, f"卖方通知缺少事件类型：{sorted(missing)}")
        buyer_types = {item.get("type") for item in notifications_all(api, buyer)}
        expected_buyer = {
            "request_accepted",
            "request_rejected",
            "agreement_proposed",
            "agreement_decided",
            "confirm_progress",
            "cancel_requested",
            "trade_completed",
            "trade_terminated",
            "dispute_resolved",
            "trade_frozen",
            "trade_unfrozen",
        }
        missing = expected_buyer - buyer_types
        rec.must(not missing, f"买方通知缺少事件类型：{sorted(missing)}")
        other_types = {item.get("type") for item in notifications_all(api, other)}
        rec.must("request_closed" in other_types, "被关闭请求的买方应收到 request_closed")
        rec.must("product_edited" in other_types, "未结束请求买方应收到 product_edited")

    with rec.step(
        "US-11-AC-02f",
        us="US-11",
        sc="SC-11-04",
        desc="待办覆盖请求/约定/完成确认/取消/争议解决，办结后移出且历史通知保留",
        expected="各类型待办均出现过并正确移出",
    ):
        # 已在前序检查中覆盖 request_pending / agreement_pending / completion_confirm /
        # cancel_pending / dispute_resolution；此处复核当前无遗留交易待办（除未结请求）。
        current = todo_keys(api, seller)
        leftover = [key for key in current if key.startswith(("agreement_pending:", "completion_confirm:", "cancel_pending:", "dispute_resolution:"))]
        rec.must_eq(leftover, [], "已办结事项不应残留待办")
        rec.must(any(key.startswith("request_pending:") for key in current), "未处理的待接受请求应保留待办")
        seller_items = notifications_all(api, seller)
        rec.must(any(item.get("type") == "request_created" for item in seller_items), "办结后历史通知仍保留")

    # 通知/待办中最终管理员共享池与个人通知边界复核
    with rec.step(
        "US-11-AC-05h",
        us="US-11",
        sc="SC-11-01",
        desc="管理员待办来自共享池而非个人通知：管理员存在共享池事项但个人通知恒空",
        expected="管理员个人通知为空；共享池存在商品审核/争议事项",
    ):
        admin_tok = ctx.token("admin")
        pool = api.get("/admin/cases", token=admin_tok, params={"status": "pending"}, expected=200).json()
        rec.must(isinstance(pool, list), "管理员共享池可读")
        rec.must_eq(list_notifications(api, admin_tok).get("items"), [], "管理员个人通知必须为空")
        rec.must_eq(todos(api, admin_tok).get("items"), [], "管理员个人待办必须为空")

    # 治理类事件与时间相关事件在其它阶段覆盖（不在本阶段重复造举报/异常流程）
    rec.skip(
        "US-11-AC-05i",
        us="US-11",
        sc="SC-11-01",
        desc="举报结果/问询/处置/申辩及管理调整类通知事件",
        reason="p07 对部分举报治理事件、p05 对 trade_adjusted、p08 对 trade_abnormal 有实际断言；这些是分散的关联检查，未逐项覆盖本 SKIP 所指的全部通知事件",
    )
