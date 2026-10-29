"""[p05] 请求、约定、确认与终止（US-05、US-06）真实 API 生命周期阶段。

覆盖 SC-05（请求/锁单/约定/确认/终止）、SC-06（争议与恢复）、4.15 约定阶段与 D-49，
以及 D-48 旧交易恢复锁单冲突。全部数据通过真实 HTTP 接口创建，商品走真实审核。
共用造数辅助来自本任务 p04 模块（只导入函数，不依赖 p04 已运行）。
"""

from __future__ import annotations

from phases.p04_search_favorites_comments import (
    admin_claim_case,
    admin_list_cases,
    conversation_item,
    detail_text,
    ensure_admin,
    ensure_category,
    merge_trade_detail,
    new_user,
    notifications_matching,
    product_detail,
    publish_listed_product,
    request_trade,
    search_products,
    trade_detail,
    trade_transitions,
)

PHASE_ID = "p05"

AGREEMENT_TEMPLATE = {
    "delivery_time": "2026-11-01 19:00-20:00",
    "delivery_location": "东区宿舍 3 号楼下",
    "delivery_method": "当面交付",
    "amount_cents": 5000,
    "payment_method": "微信转账",
    "payment_timing": "交付时支付",
}


# ---------------------------------------------------------------------------
# 本阶段交易操作辅助
# ---------------------------------------------------------------------------
def accept_trade(api, ctx, trade_key: str, *, expected=200):
    trade = ctx.trades[trade_key]
    seller = ctx.account(trade["seller"])
    resp = api.post(f"/trades/{trade['id']}/accept", token=seller["token"], expected=expected)
    if expected == 200:
        refreshed = trade_detail(api, seller["token"], trade["id"])
        merge_trade_detail(ctx.trades[trade_key], refreshed)
        ctx.update_trade(trade_key, refreshed.get("status", "in_progress"))
    return resp


def propose_agreement(api, ctx, trade_key: str, proposer_key: str, *, overrides: dict | None = None, expected=200):
    trade = ctx.trades[trade_key]
    body = dict(AGREEMENT_TEMPLATE)
    if overrides:
        for key, value in overrides.items():
            if value is None:
                body.pop(key, None)
            else:
                body[key] = value
    return api.post(f"/trades/{trade['id']}/agreements", token=ctx.token(proposer_key), json_body=body, expected=expected)


def confirm_agreement(api, ctx, trade_key: str, agreement_id: int, actor_key: str, *, expected=200):
    trade = ctx.trades[trade_key]
    return api.post(
        f"/trades/{trade['id']}/agreements/{agreement_id}/confirm",
        token=ctx.token(actor_key),
        expected=expected,
    )


def reject_agreement(api, ctx, trade_key: str, agreement_id: int, actor_key: str, *, expected=200):
    trade = ctx.trades[trade_key]
    return api.post(
        f"/trades/{trade['id']}/agreements/{agreement_id}/reject",
        token=ctx.token(actor_key),
        expected=expected,
    )


def submit_confirmation(api, ctx, trade_key: str, actor_key: str, *, note: str | None = None, expected=200):
    trade = ctx.trades[trade_key]
    body: dict = {}
    if note:
        body["note"] = note
    return api.post(f"/trades/{trade['id']}/confirmations", token=ctx.token(actor_key), json_body=body, expected=expected)


def trade_cancel(api, ctx, trade_key: str, actor_key: str, *, reason: str | None = None, expected=200):
    trade = ctx.trades[trade_key]
    body: dict = {}
    if reason:
        body["reason"] = reason
    return api.post(f"/trades/{trade['id']}/cancel", token=ctx.token(actor_key), json_body=body, expected=expected)


def confirm_cancel(api, ctx, trade_key: str, actor_key: str, *, expected=200):
    trade = ctx.trades[trade_key]
    return api.post(f"/trades/{trade['id']}/cancel/confirm", token=ctx.token(actor_key), json_body={}, expected=expected)


def withdraw_cancel(api, ctx, trade_key: str, actor_key: str, *, expected=200):
    trade = ctx.trades[trade_key]
    return api.post(f"/trades/{trade['id']}/cancel/withdraw", token=ctx.token(actor_key), expected=expected)


def create_dispute(api, ctx, trade_key: str, actor_key: str, *, description: str, expected=200):
    trade = ctx.trades[trade_key]
    return api.post(
        f"/trades/{trade['id']}/disputes",
        token=ctx.token(actor_key),
        json_body={"description": description},
        expected=expected,
    )


def resolve_dispute(api, ctx, trade_key: str, actor_key: str, *, expected=200):
    trade = ctx.trades[trade_key]
    return api.post(f"/trades/{trade['id']}/disputes/resolve", token=ctx.token(actor_key), json_body={}, expected=expected)


def refresh_trade(api, ctx, trade_key: str, viewer_key: str | None = None) -> dict:
    trade = ctx.trades[trade_key]
    viewer = viewer_key or trade["buyer"]
    data = trade_detail(api, ctx.token(viewer), trade["id"])
    merge_trade_detail(ctx.trades[trade_key], data)
    ctx.update_trade(trade_key, data.get("status", trade.get("state", "unknown")))
    return data


def refresh_product(api, ctx, product_key: str) -> dict:
    product = ctx.products[product_key]
    data = product_detail(api, ctx.token(product["seller"]), product["id"]).json()
    ctx.products[product_key].update(data)
    ctx.update_product(product_key, state=data.get("status", "unknown"))
    return data


def wait_started_at(api, ctx, trade_key: str, viewer_key: str | None = None) -> str | None:
    return refresh_trade(api, ctx, trade_key, viewer_key).get("confirm_wait_started_at")


def find_pending_case_for_trade(api, ctx, trade_id: int, *, case_type: str = "trade_dispute") -> dict | None:
    cases = admin_list_cases(api, ctx, status="pending", case_type=case_type)
    return next((c for c in cases if c.get("trade_id") == trade_id), None)


def admin_claim_trade_case(api, ctx, trade_key: str, *, case_type: str = "trade_dispute") -> dict:
    trade = ctx.trades[trade_key]
    case = find_pending_case_for_trade(api, ctx, trade["id"], case_type=case_type)
    if case is None:
        raise AssertionError(f"共享池中找不到交易 #{trade['id']} 的 {case_type} 事项")
    admin_claim_case(api, ctx, case["id"])
    ctx.trades[trade_key]["case_id"] = case["id"]
    ctx.remember_case(f"p05_case_{trade_key}", {"id": case["id"], "case_type": case_type, "status": "processing", "title": f"{case_type} #{case['id']}"})
    return case


def admin_adjust(api, ctx, trade_key: str, to_status: str, *, case_id: int | None = None, reason: str = "真实 API 生命周期测试管理调整", expected=200):
    trade = ctx.trades[trade_key]
    body: dict = {"to_status": to_status, "reason": reason}
    if case_id is not None:
        body["case_id"] = case_id
    resp = api.post(f"/admin/trades/{trade['id']}/adjust", token=ctx.token("admin"), json_body=body, expected=expected)
    if expected == 200:
        refreshed = trade_detail(api, ctx.token(trade["buyer"]), trade["id"])
        merge_trade_detail(ctx.trades[trade_key], refreshed)
        ctx.update_trade(trade_key, to_status)
    return resp


def branch_of(api, ctx, trade_key: str) -> dict:
    trade = ctx.trades[trade_key]
    conversation_id = trade.get("conversation_id")
    if conversation_id is None:
        trade = refresh_trade(api, ctx, trade_key)
        conversation_id = trade.get("conversation_id")
    return conversation_item(api, ctx.token(trade["buyer"]), conversation_id)


# ---------------------------------------------------------------------------
# 阶段主体
# ---------------------------------------------------------------------------
def run(ctx, api, rec):  # noqa: ANN001 - 框架约定签名
    """US-05 / US-06：请求、锁单、约定、确认、取消、争议、恢复与管理调整。"""
    with rec.step(
        "P05-SETUP",
        us="US-05,US-06",
        sc="SC-05,SC-06",
        desc="真实注册买卖双方/第三方账户，发布并审核通过 14 件测试商品",
        expected="账户与公开可交易商品就绪（真实审核）",
    ):
        ensure_admin(api, ctx)
        new_user(api, ctx, "p05_seller", "p05.seller", "交易卖方")
        new_user(api, ctx, "p05_buyer1", "p05.buyer1", "交易买方一")
        new_user(api, ctx, "p05_buyer2", "p05.buyer2", "交易买方二")
        new_user(api, ctx, "p05_buyer3", "p05.buyer3", "交易买方三")
        new_user(api, ctx, "p05_outsider", "p05.outsider", "交易第三方")
        admin = ctx.account("admin")
        ensure_category(api, ctx, admin["token"], "交易测试品类")
        seeds = [
            ("p05_lock_multi", "交易多请求折叠桌", 12000, "product_lamp.jpg"),
            ("p05_reject", "交易拒绝样本羽毛球拍", 13000, "product_racket.jpg"),
            ("p05_withdraw", "交易撤回样本蓝牙音箱", 14000, "product_second2.jpg"),
            ("p05_own", "交易本人商品样本电煮锅", 15000, "product_lamp.jpg"),
            ("p05_dup", "交易非参与方样本显示器", 16000, "product_camera.jpg"),
            ("p05_agree", "交易首次约定与完成样本", 17000, "product_keyboard.jpg"),
            ("p05_noagree", "交易无约定确认拒绝样本", 18000, "product_notes.jpg"),
            ("p05_cancel_pre_seller", "约定前卖方取消申请样本", 19000, "product_textbook.jpg"),
            ("p05_cancel_after", "约定后双方同意终止样本", 20000, "product_mug.jpg"),
            ("p05_cancel_withdraw", "取消申请撤回样本", 21000, "product_bike.jpg"),
            ("p05_dispute_user", "争议用户双方解决样本", 22000, "product_second.jpg"),
            ("p05_dispute_admin", "争议管理员解决样本", 23000, "product_racket.jpg"),
            ("p05_d48", "D48 旧交易恢复冲突样本", 24000, "product_camera.jpg"),
            ("p05_d49", "约定变更未同意保留样本", 25000, "product_lamp.jpg"),
            ("p05_d49b", "约定变更生效重置确认样本", 25500, "product_keyboard.jpg"),
        ]
        for key, title, price, image in seeds:
            publish_listed_product(
                api, ctx, key, "p05_seller",
                title=title,
                price_cents=price,
                tag_names=["交易测试品类"],
                image=image,
                description=f"{title}（交易生命周期真实 API 测试）",
            )
        rec.must(len([k for k in ctx.products if k.startswith("p05_")]) >= 15, "交易测试商品未全部就绪")

    seller_tok = ctx.token("p05_seller")
    b1 = ctx.token("p05_buyer1")
    b2 = ctx.token("p05_buyer2")
    b3 = ctx.token("p05_buyer3")
    outsider = ctx.token("p05_outsider")

    # ================================================================ US-05-AC-01 请求
    with rec.step(
        "US-05-AC-01a",
        us="US-05",
        sc="SC-05-01",
        desc="买方对公开商品发起购买请求：独立待接受记录 + 交易分支 + 通知卖方，不提前锁单",
        expected="200 待接受；商品仍 listed；分支未归档；卖方收到 request_created 且入口指向同一请求",
    ):
        trade = request_trade(api, ctx, "p05_t_lock_multi", "p05_lock_multi", "p05_buyer1", note="希望周末自提")
        rec.must_eq(trade.get("status"), "pending_acceptance", "请求创建后交易状态")
        rec.must_eq(trade.get("my_role"), "buyer", "买方视角 my_role")
        rec.must_eq(trade.get("request_note"), "希望周末自提", "请求备注")
        rec.must(trade.get("conversation_id") is not None, "有效请求应自动建立交易分支")
        rec.must(not trade.get("conversation_archived"), "待接受分支不应归档")
        product = refresh_product(api, ctx, "p05_lock_multi")
        rec.must_eq(product.get("status"), "listed", "待接受请求不提前锁单，商品仍公开可交易")
        rec.must_eq(product.get("pending_request_count"), 1, "卖方视角待接受请求数")
        branch = branch_of(api, ctx, "p05_t_lock_multi")
        rec.must_eq(branch.get("type"), "trade", "请求对应分支类型")
        rec.must_eq((branch.get("trade") or {}).get("id"), trade["id"], "分支关联同一请求")
        rec.must(any(m.get("kind") == "system" for m in branch.get("messages") or []), "交易分支应有系统消息")
        notes = notifications_matching(api, seller_tok, type_="request_created", link_id=trade["conversation_id"])
        rec.must(len(notes) >= 1, "卖方应收到关联该交易分支的 request_created 通知")
        rec.must_eq((notes[0].get("payload") or {}).get("trade_id"), trade["id"], "通知 payload 关联同一交易")

    with rec.step(
        "US-05-AC-01b",
        us="US-05",
        sc="SC-05-01",
        desc="同一买方重复请求幂等返回既有请求，不重复建交易/分支",
        expected="200 existing=true 且 id 相同；待接受请求数仍为 1",
    ):
        trade = ctx.trades["p05_t_lock_multi"]
        resp = api.post("/trades/requests", token=b1, json_body={"product_id": ctx.products["p05_lock_multi"]["id"]}, expected=200)
        payload = resp.json()
        rec.must_eq(payload.get("existing"), True, "重复请求 existing 标记")
        rec.must_eq(payload.get("id"), trade["id"], "重复请求返回同一交易 id")
        product = refresh_product(api, ctx, "p05_lock_multi")
        rec.must_eq(product.get("pending_request_count"), 1, "重复请求不应新增待接受记录")

    with rec.step(
        "US-05-AC-01c",
        us="US-05",
        sc="SC-05-05",
        desc="同一商品允许多个不同买方的待接受请求（买方二/三各一条）",
        expected="3 条待接受请求，商品仍 listed",
    ):
        request_trade(api, ctx, "p05_t_lock_b2", "p05_lock_multi", "p05_buyer2")
        request_trade(api, ctx, "p05_t_lock_b3", "p05_lock_multi", "p05_buyer3")
        for key in ("p05_t_lock_b2", "p05_t_lock_b3"):
            rec.must_eq(ctx.trades[key].get("status"), "pending_acceptance", f"{key} 应待接受")
        product = refresh_product(api, ctx, "p05_lock_multi")
        rec.must_eq(product.get("pending_request_count"), 3, "卖方视角待接受请求数应为 3")
        rec.must_eq(product.get("status"), "listed", "多请求并存时商品状态")

    with rec.step(
        "US-05-AC-01d",
        us="US-05",
        sc="SC-05-04",
        desc="本人商品不能发起购买请求",
        expected="400 不能购买本人发布的商品",
    ):
        resp = api.post("/trades/requests", token=seller_tok, json_body={"product_id": ctx.products["p05_own"]["id"]}, expected=400)
        rec.must("本人" in detail_text(resp), f"本人商品请求应 400，实际 {detail_text(resp)}")

    with rec.step(
        "US-05-AC-01e",
        us="US-05",
        sc="SC-05-01",
        desc="未登录不能发起购买请求/查看交易",
        expected="401 未登录",
    ):
        resp = api.post("/trades/requests", json_body={"product_id": ctx.products["p05_lock_multi"]["id"]}, expected=401)
        rec.must("未登录" in detail_text(resp), f"未登录请求应 401，实际 {detail_text(resp)}")
        api.get(f"/trades/{ctx.trades['p05_t_lock_multi']['id']}", expected=401)
        api.get("/trades/mine", expected=401)

    with rec.step(
        "US-05-AC-01f",
        us="US-05",
        sc="SC-05-05",
        desc="请求创建不关闭其他待接受请求（接受前互不影响）",
        expected="买方二/三请求仍为待接受",
    ):
        for key in ("p05_t_lock_b2", "p05_t_lock_b3"):
            data = refresh_trade(api, ctx, key)
            rec.must_eq(data.get("status"), "pending_acceptance", f"{key} 在卖方接受前应保持待接受")

    # ================================================================ US-05-AC-02 接受锁单
    with rec.step(
        "US-05-AC-02a",
        us="US-05",
        sc="SC-05-05",
        desc="卖方接受一条请求：锁单、商品交易中、写交易时快照与状态转移",
        expected="200；交易 in_progress + accepted_at；商品 in_transaction；转移 request_accepted；买方通知",
    ):
        trade = ctx.trades["p05_t_lock_multi"]
        resp = api.post(f"/trades/{trade['id']}/accept", token=seller_tok, expected=200)
        rec.must("进行中" in detail_text(resp), f"接受响应文案应提示进行中，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p05_t_lock_multi")
        rec.must_eq(data.get("status"), "in_progress", "接受后交易状态")
        rec.must(data.get("accepted_at") is not None, "接受后 accepted_at 应记录")
        rec.must_eq(data.get("my_role"), "buyer", "买方查看时 my_role")
        snapshot = data.get("product_snapshot") or {}
        rec.must_eq(snapshot.get("title"), ctx.products["p05_lock_multi"]["title"], "交易时商品标题快照")
        rec.must_eq(snapshot.get("price_cents"), 12000, "交易时价格快照")
        rec.must(bool(snapshot.get("images")), "交易时商品图片快照")
        product = refresh_product(api, ctx, "p05_lock_multi")
        rec.must_eq(product.get("status"), "in_transaction", "接受后商品进入交易中")
        transitions = trade_transitions(api, b1, trade["id"])
        accepted = [t for t in transitions if t.get("to_status") == "in_progress"]
        rec.must(accepted, "转移历史应记录进入进行中")
        rec.must_eq(accepted[-1].get("from_status"), "pending_acceptance", "接受转移前状态")
        rec.must_eq(accepted[-1].get("trigger"), "request_accepted", "接受转移 trigger")
        rec.must_eq(accepted[-1].get("actor_role"), "seller", "接受转移 actor_role")
        notes = notifications_matching(api, b1, type_="request_accepted", link_id=trade["conversation_id"])
        rec.must(len(notes) >= 1, "买方应收到 request_accepted 通知")

    with rec.step(
        "US-05-AC-02b",
        us="US-05",
        sc="SC-05-05",
        desc="接受后其余待接受请求自动关闭，原因「商品已被其他用户锁单」，分别通知买方",
        expected="买方二/三请求 closed + close_reason 正确 + 分支归档 + request_closed 通知",
    ):
        for key in ("p05_t_lock_b2", "p05_t_lock_b3"):
            data = refresh_trade(api, ctx, key)
            rec.must_eq(data.get("status"), "closed", f"{key} 应被系统关闭")
            rec.must_eq(data.get("close_reason"), "商品已被其他用户锁单", f"{key} 关闭原因")
            rec.must_eq(data.get("conversation_archived"), True, f"{key} 分支应归档")
            buyer_key = "p05_buyer2" if key == "p05_t_lock_b2" else "p05_buyer3"
            transitions = trade_transitions(api, ctx.token(buyer_key), data["id"])
            rec.must_eq(transitions[-1].get("trigger"), "product_closed", f"{key} 关闭转移 trigger")
            rec.must_eq(transitions[-1].get("actor_role"), "system", f"{key} 关闭转移 actor_role")
            notes = notifications_matching(api, ctx.token(buyer_key), type_="request_closed", link_id=data["id"])
            rec.must(len(notes) >= 1, f"{buyer_key} 应收到 request_closed 通知")
            rec.must("其他用户锁单" in (notes[0].get("content") or ""), f"{buyer_key} 关闭通知应注明其他用户锁单")

    with rec.step(
        "US-05-AC-02c",
        us="US-05",
        sc="SC-05-05",
        desc="已锁单商品不再接受新请求（买家三对新请求被拒）",
        expected="404 商品不存在或当前不可请求",
    ):
        resp = api.post("/trades/requests", token=outsider, json_body={"product_id": ctx.products["p05_lock_multi"]["id"]}, expected=404)
        rec.must("不可请求" in detail_text(resp), f"交易中商品新请求应 404，实际 {detail_text(resp)}")

    with rec.step(
        "US-05-AC-02d",
        us="US-05",
        sc="SC-05-02",
        desc="非该商品卖方不能接受/拒绝请求；非参与方访问交易 404",
        expected="买方自行接受 403；第三方接受/拒绝/查看 404",
    ):
        pending = ctx.trades["p05_t_lock_multi"]
        rec.must_eq(pending.get("status"), "in_progress", "前置交易应为进行中")
        resp = api.post(f"/trades/{pending['id']}/accept", token=b1, expected=403)
        rec.must("卖方" in detail_text(resp), f"买方接受应 403 仅卖方，实际 {detail_text(resp)}")
        resp = api.post(f"/trades/{pending['id']}/accept", token=outsider, expected=404)
        rec.must("交易不存在" in detail_text(resp), f"非参与方接受应 404，实际 {detail_text(resp)}")
        resp = api.post(f"/trades/{pending['id']}/reject", token=outsider, json_body={}, expected=404)
        rec.must("交易不存在" in detail_text(resp), "非参与方拒绝应 404")
        api.get(f"/trades/{pending['id']}", token=outsider, expected=404)
        api.get(f"/trades/{pending['id']}/transitions", token=outsider, expected=404)

    with rec.step(
        "US-05-AC-02e",
        us="US-05",
        sc="SC-05-05",
        desc="重复接受已处理请求返回 409，不重复锁单",
        expected="409 该请求当前不可接受",
    ):
        trade = ctx.trades["p05_t_lock_multi"]
        resp = api.post(f"/trades/{trade['id']}/accept", token=seller_tok, expected=409)
        rec.must("不可接受" in detail_text(resp), f"重复接受应 409，实际 {detail_text(resp)}")
        product = refresh_product(api, ctx, "p05_lock_multi")
        rec.must_eq(product.get("status"), "in_transaction", "重复接受不应改变商品状态")

    # ================================================================ US-05-AC-03 拒绝/撤回
    with rec.step(
        "US-05-AC-03a",
        us="US-05",
        sc="SC-05-06",
        desc="卖方拒绝待接受请求：记录已拒绝与原因、归档分支、通知买方",
        expected="200；rejected + close_reason=自定义原因；分支归档；request_rejected 通知",
    ):
        request_trade(api, ctx, "p05_t_reject", "p05_reject", "p05_buyer1")
        resp = api.post(f"/trades/{ctx.trades['p05_t_reject']['id']}/reject", token=seller_tok, json_body={"reason": "暂时不出售"}, expected=200)
        rec.must("已拒绝" in detail_text(resp), f"拒绝响应文案，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p05_t_reject")
        rec.must_eq(data.get("status"), "rejected", "拒绝后交易状态")
        rec.must_eq(data.get("close_reason"), "暂时不出售", "拒绝原因")
        rec.must_eq(data.get("conversation_archived"), True, "拒绝后分支归档")
        transitions = trade_transitions(api, b1, data["id"])
        rec.must_eq(transitions[-1].get("trigger"), "request_rejected", "拒绝转移 trigger")
        rec.must_eq(transitions[-1].get("reason"), "暂时不出售", "拒绝转移 reason")
        notes = notifications_matching(api, b1, type_="request_rejected", link_id=data["id"])
        rec.must(len(notes) >= 1, "买方应收到 request_rejected 通知")

    with rec.step(
        "US-05-AC-03b",
        us="US-05",
        sc="SC-05-06",
        desc="已拒绝/已处理请求不可重复处理或撤回",
        expected="再拒绝 409；买方撤回 409 卖方已处理",
    ):
        trade = ctx.trades["p05_t_reject"]
        resp = api.post(f"/trades/{trade['id']}/reject", token=seller_tok, json_body={}, expected=409)
        rec.must("不可拒绝" in detail_text(resp), f"重复拒绝应 409，实际 {detail_text(resp)}")
        resp = api.post(f"/trades/{trade['id']}/withdraw", token=b1, expected=409)
        rec.must("已处理" in detail_text(resp), f"已拒绝请求撤回应 409，实际 {detail_text(resp)}")

    with rec.step(
        "US-05-AC-03c",
        us="US-05",
        sc="SC-05-07",
        desc="卖方接受前买方撤回：记已撤回、归档分支、通知卖方；之后不可再接受",
        expected="200 已撤回；withdrawn + close_reason=买方撤回；request_withdrawn 通知；接受 409",
    ):
        request_trade(api, ctx, "p05_t_withdraw", "p05_withdraw", "p05_buyer1")
        resp = api.post(f"/trades/{ctx.trades['p05_t_withdraw']['id']}/withdraw", token=b1, expected=200)
        rec.must("已撤回" in detail_text(resp), f"撤回响应文案，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p05_t_withdraw")
        rec.must_eq(data.get("status"), "withdrawn", "撤回后交易状态")
        rec.must_eq(data.get("close_reason"), "买方撤回", "撤回原因")
        rec.must_eq(data.get("conversation_archived"), True, "撤回后分支归档")
        transitions = trade_transitions(api, b1, data["id"])
        rec.must_eq(transitions[-1].get("trigger"), "request_withdrawn", "撤回转移 trigger")
        notes = notifications_matching(api, seller_tok, type_="request_withdrawn", link_id=data["id"])
        rec.must(len(notes) >= 1, "卖方应收到 request_withdrawn 通知")
        resp = api.post(f"/trades/{data['id']}/accept", token=seller_tok, expected=409)
        rec.must("不可接受" in detail_text(resp), "撤回后接受应 409")

    with rec.step(
        "US-05-AC-03d",
        us="US-05",
        sc="SC-05-07",
        desc="拒绝/撤回后买方可对该商品再次发起新请求（新交易、不复用旧分支）",
        expected="新请求 id 不同、待接受、新分支；商品仍 listed",
    ):
        old_reject_id = ctx.trades["p05_t_reject"]["id"]
        request_trade(api, ctx, "p05_t_reject_again", "p05_reject", "p05_buyer1")
        again = ctx.trades["p05_t_reject_again"]
        rec.must(again["id"] != old_reject_id, "再次请求应创建新交易 id")
        rec.must_eq(again.get("status"), "pending_acceptance", "再次请求状态")
        rec.must(again.get("conversation_id") != ctx.trades["p05_t_reject"].get("conversation_id"), "新请求应使用新分支")
        rec.must_eq(refresh_product(api, ctx, "p05_reject").get("status"), "listed", "拒绝不改变商品公开状态")
        api.post(f"/trades/{again['id']}/withdraw", token=b1, expected=200)
        old_withdraw_id = ctx.trades["p05_t_withdraw"]["id"]
        request_trade(api, ctx, "p05_t_withdraw_again", "p05_withdraw", "p05_buyer1")
        rec.must(ctx.trades["p05_t_withdraw_again"]["id"] != old_withdraw_id, "撤回后再次请求应创建新交易 id")
        api.post(f"/trades/{ctx.trades['p05_t_withdraw_again']['id']}/withdraw", token=b1, expected=200)

    # ================================================================ 非参与方操作拒绝
    with rec.step(
        "US-05-AC-02f",
        us="US-05",
        sc="SC-05-02",
        desc="非参与方对进行中交易的全部写操作被拒绝（404 交易不存在）",
        expected="第三方 accept/reject/withdraw/agreements/confirmations/cancel/disputes/resolve 均 404",
    ):
        request_trade(api, ctx, "p05_t_dup", "p05_dup", "p05_buyer1")
        trade = ctx.trades["p05_t_dup"]
        api.post(f"/trades/{trade['id']}/accept", token=seller_tok, expected=200)
        ctx.update_trade("p05_t_dup", "in_progress")
        attempts = [
            ("post", f"/trades/{trade['id']}/accept", None),
            ("post", f"/trades/{trade['id']}/reject", {}),
            ("post", f"/trades/{trade['id']}/withdraw", None),
            ("post", f"/trades/{trade['id']}/agreements", dict(AGREEMENT_TEMPLATE)),
            ("post", f"/trades/{trade['id']}/confirmations", {}),
            ("post", f"/trades/{trade['id']}/cancel", {}),
            ("post", f"/trades/{trade['id']}/disputes", {"description": "第三方试图发起争议"}),
            ("post", f"/trades/{trade['id']}/disputes/resolve", {}),
        ]
        for method, path, body in attempts:
            if method == "post":
                resp = api.post(path, token=outsider, json_body=body, expected=404)
                rec.must("交易不存在" in detail_text(resp), f"非参与方 {path} 应 404，实际 {detail_text(resp)}")
        rec.must_eq(refresh_trade(api, ctx, "p05_t_dup").get("status"), "in_progress", "非参与方操作后交易状态不变")

    with rec.step(
        "US-05-AC-02g",
        us="US-05",
        sc="SC-05-03",
        desc="非请求发起人不能撤回（卖方撤回 403），接受后买方撤回 409",
        expected="卖方撤回 403 仅请求发起人；接受后买方撤回 409",
    ):
        trade = ctx.trades["p05_t_dup"]
        resp = api.post(f"/trades/{trade['id']}/withdraw", token=seller_tok, expected=403)
        rec.must("发起人" in detail_text(resp), f"卖方撤回应 403，实际 {detail_text(resp)}")
        resp = api.post(f"/trades/{trade['id']}/withdraw", token=b1, expected=409)
        rec.must("已处理" in detail_text(resp), f"接受后撤回应 409，实际 {detail_text(resp)}")
        api.post(f"/trades/{trade['id']}/cancel", token=b1, json_body={}, expected=200)
        rec.must_eq(refresh_trade(api, ctx, "p05_t_dup").get("status"), "terminated", "约定前买方直接取消")

    # ================================================================ US-05-AC-04 首次约定
    with rec.step(
        "US-05-AC-04a",
        us="US-05",
        sc="SC-05-01",
        desc="接受后进入「首次约定待确认」阶段",
        expected="in_progress + agreement_stage=awaiting_agreement + 无有效约定",
    ):
        request_trade(api, ctx, "p05_t_agree", "p05_agree", "p05_buyer1")
        api.post(f"/trades/{ctx.trades['p05_t_agree']['id']}/accept", token=seller_tok, expected=200)
        data = refresh_trade(api, ctx, "p05_t_agree")
        rec.must_eq(data.get("status"), "in_progress", "接受后交易状态")
        rec.must_eq(data.get("agreement_stage"), "awaiting_agreement", "首次约定阶段")
        rec.must_eq(data.get("effective_agreement"), None, "尚无有效约定")
        product = refresh_product(api, ctx, "p05_agree")
        rec.must_eq(product.get("status"), "in_transaction", "约定阶段商品保持交易中")

    with rec.step(
        "US-05-AC-04b",
        us="US-05",
        sc="SC-05-01",
        desc="约定要素完整性校验：缺任一必填要素被 422 拒绝",
        expected="422（schema 必填），不产生提案",
    ):
        trade = ctx.trades["p05_t_agree"]
        resp = api.post(
            f"/trades/{trade['id']}/agreements",
            token=b1,
            json_body={
                "delivery_location": "东区宿舍楼下",
                "delivery_method": "当面交付",
                "amount_cents": 5000,
                "payment_method": "微信",
                "payment_timing": "交付时",
            },
            expected=422,
        )
        rec.must(resp.status_code == 422, "缺 delivery_time 应 422")
        data = refresh_trade(api, ctx, "p05_t_agree")
        rec.must_eq(data.get("pending_agreement"), None, "422 不应产生待确认提案")

    with rec.step(
        "US-05-AC-04c",
        us="US-05",
        sc="SC-05-01",
        desc="提出首次约定：6 要素完整记录、通知对方、进入待确认提案",
        expected="200 提案 id；pending_agreement 6 要素与本方提出一致；对方收到 agreement_proposed",
    ):
        trade = ctx.trades["p05_t_agree"]
        resp = api.post(f"/trades/{trade['id']}/agreements", token=seller_tok, json_body=dict(AGREEMENT_TEMPLATE), expected=200)
        agreement_id = resp.json().get("id")
        rec.must(agreement_id is not None, "提出约定未返回 id")
        ctx.trades["p05_t_agree"]["agreement_1"] = agreement_id
        data = refresh_trade(api, ctx, "p05_t_agree")
        pending = data.get("pending_agreement") or {}
        rec.must_eq(pending.get("id"), agreement_id, "待确认提案 id")
        rec.must_eq(pending.get("round_no"), 1, "首次提案轮次")
        rec.must_eq(pending.get("proposer_id"), ctx.account("p05_seller")["id"], "提案人")
        for field, expected in AGREEMENT_TEMPLATE.items():
            rec.must_eq(pending.get(field), expected, f"提案要素 {field}")
        notes = notifications_matching(api, b1, type_="agreement_proposed", link_id=trade["id"])
        rec.must(len(notes) >= 1, "对方应收到 agreement_proposed 通知")
        rec.must_eq(data.get("agreement_stage"), "awaiting_agreement", "提案未生效前仍待约定")
        rec.must_eq(data.get("effective_agreement"), None, "提案未确认前无有效约定")

    with rec.step(
        "US-05-AC-04d",
        us="US-05",
        sc="SC-05-01",
        desc="已有待确认提案时不能重复提出；提案人不能处理本人提案",
        expected="再提出 409；本人确认 403",
    ):
        trade = ctx.trades["p05_t_agree"]
        resp = api.post(f"/trades/{trade['id']}/agreements", token=b1, json_body=dict(AGREEMENT_TEMPLATE), expected=409)
        rec.must("待确认" in detail_text(resp), f"重复提案应 409，实际 {detail_text(resp)}")
        resp = api.post(f"/trades/{trade['id']}/agreements/{trade['agreement_1']}/confirm", token=seller_tok, expected=403)
        rec.must("本人" in detail_text(resp), f"提案人确认本人提案应 403，实际 {detail_text(resp)}")

    with rec.step(
        "US-05-AC-04e",
        us="US-05",
        sc="SC-05-01",
        desc="拒绝首次提案只结束该提案：锁单保持、可重新提案",
        expected="200 已拒绝；仍 in_progress/awaiting_agreement、无有效约定；历史记录 rejected",
    ):
        trade = ctx.trades["p05_t_agree"]
        resp = api.post(f"/trades/{trade['id']}/agreements/{trade['agreement_1']}/reject", token=b1, expected=200)
        rec.must("已拒绝" in detail_text(resp), f"拒绝提案文案，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p05_t_agree")
        rec.must_eq(data.get("status"), "in_progress", "拒绝提案不结束交易")
        rec.must_eq(data.get("effective_agreement"), None, "拒绝后无有效约定")
        rec.must_eq(data.get("pending_agreement"), None, "拒绝后无待确认提案")
        history = data.get("agreement_history") or []
        rec.must_eq(history[-1].get("status"), "rejected", "提案历史状态")
        notes = notifications_matching(api, seller_tok, type_="agreement_decided", link_id=trade["id"])
        rec.must(len(notes) >= 1, "提出方应收到 agreement_decided 通知")
        resp = api.post(f"/trades/{trade['id']}/agreements/{trade['agreement_1']}/confirm", token=b1, expected=409)
        rec.must("已被处理" in detail_text(resp), f"重复处理已拒绝提案应 409，实际 {detail_text(resp)}")

    with rec.step(
        "US-05-AC-04f",
        us="US-05",
        sc="SC-05-01",
        desc="重新提出约定并由另一方同意后生效（第 2 轮）",
        expected="确认生效；effective_agreement 6 要素与金额（可不同于标价）；阶段转待完成",
    ):
        trade = ctx.trades["p05_t_agree"]
        body = dict(AGREEMENT_TEMPLATE)
        body["amount_cents"] = 8800
        body["delivery_time"] = "2026-11-02 18:30-19:00"
        resp = api.post(f"/trades/{trade['id']}/agreements", token=b1, json_body=body, expected=200)
        agreement_2 = resp.json()["id"]
        ctx.trades["p05_t_agree"]["agreement_2"] = agreement_2
        resp = api.post(f"/trades/{trade['id']}/agreements/{agreement_2}/confirm", token=seller_tok, expected=200)
        rec.must("生效" in detail_text(resp), f"约定确认响应文案，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p05_t_agree")
        effective = data.get("effective_agreement") or {}
        rec.must_eq(effective.get("id"), agreement_2, "有效约定 id")
        for field, expected in body.items():
            rec.must_eq(effective.get(field), expected, f"有效约定要素 {field}")
        rec.must_eq(effective.get("amount_cents"), 8800, "约定金额可不同于商品标价")
        rec.must_eq(refresh_product(api, ctx, "p05_agree").get("price_cents"), 17000, "商品标价不被约定金额改写")
        rec.must_eq(data.get("agreement_stage"), "awaiting_completion", "约定生效后阶段")
        rec.must_eq(data.get("pending_agreement"), None, "生效后无待确认提案")
        statuses = {(a.get("round_no"), a.get("status")) for a in data.get("agreement_history") or []}
        rec.must((1, "rejected") in statuses, "第 1 轮提案历史应保留为 rejected")
        rec.must((2, "confirmed") in statuses, "第 2 轮提案应为 confirmed")
        notes = notifications_matching(api, b1, type_="agreement_decided", link_id=trade["id"])
        rec.must(len(notes) >= 1, "确认后提出方应收到 agreement_decided 通知")

    # ================================================================ US-06 完成确认
    with rec.step(
        "US-06-AC-01a",
        us="US-06",
        sc="SC-05-01",
        desc="无有效约定时提交完成确认被拒绝（先完成约定确认）",
        expected="409 须先确认交易约定",
    ):
        request_trade(api, ctx, "p05_t_noagree", "p05_noagree", "p05_buyer1")
        api.post(f"/trades/{ctx.trades['p05_t_noagree']['id']}/accept", token=seller_tok, expected=200)
        resp = submit_confirmation(api, ctx, "p05_t_noagree", "p05_buyer1", expected=409)
        rec.must("约定" in detail_text(resp), f"无约定确认应 409，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p05_t_noagree")
        rec.must_eq(data.get("confirmations"), [], "被拒绝的确认不应落记录")
        rec.must_eq(data.get("confirm_wait_started_at"), None, "被拒绝的确认不应启动计时")

    with rec.step(
        "US-06-AC-01b",
        us="US-06",
        sc="SC-05-01",
        desc="无约定确认被拒后买方可直接取消（约定前买方可直接终止）",
        expected="200 交易已终止；product 默认下架；分支归档",
    ):
        resp = trade_cancel(api, ctx, "p05_t_noagree", "p05_buyer1", reason="商品暂不需要了")
        rec.must("交易已终止" in detail_text(resp), f"约定前买方直接取消文案，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p05_t_noagree")
        rec.must_eq(data.get("status"), "terminated", "直接取消后交易状态")
        rec.must(data.get("finished_at") is not None, "终止后 finished_at")
        rec.must_eq(data.get("conversation_archived"), True, "终止后分支归档")
        transitions = trade_transitions(api, b1, data["id"])
        rec.must_eq(transitions[-1].get("trigger"), "buyer_cancel", "买方直接取消 transfer")
        rec.must_eq(transitions[-1].get("reason"), "商品暂不需要了", "取消原因留痕")
        rec.must_eq(refresh_product(api, ctx, "p05_noagree").get("status"), "delisted", "终止后商品默认下架")

    with rec.step(
        "US-06-AC-02a",
        us="US-06",
        sc="SC-05-08",
        desc="单方完成确认：记录确认人/时间/说明，开始等待计时，通知另一方（不通知为已完成）",
        expected="200 已记录本人确认；my_confirmed=true/other=false；confirm_wait_started_at 非空；对方 confirm_progress",
    ):
        resp = submit_confirmation(api, ctx, "p05_t_agree", "p05_buyer1", note="已当面交付并微信支付")
        rec.must("等待对方确认" in detail_text(resp), f"单方确认响应文案，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p05_t_agree")
        rec.must_eq(data.get("status"), "in_progress", "单方确认不改变交易状态")
        rec.must_eq(data.get("my_confirmed"), True, "买方 my_confirmed")
        rec.must_eq(data.get("other_party_confirmed"), False, "买方视角对方未确认")
        rec.must(data.get("confirm_wait_started_at") is not None, "单方确认应开始等待计时")
        confirmation = (data.get("confirmations") or [])[0]
        rec.must_eq(confirmation.get("confirmer_id"), ctx.account("p05_buyer1")["id"], "确认记录人")
        rec.must_eq(confirmation.get("note"), "已当面交付并微信支付", "确认说明")
        rec.must(confirmation.get("confirmed_at") is not None, "确认时间")
        rec.must_eq(confirmation.get("is_current"), True, "当前确认标记")
        seller_notes = notifications_matching(api, seller_tok, type_="confirm_progress", link_id=data["id"])
        rec.must(len(seller_notes) >= 1, "待确认方应收到 confirm_progress 通知")
        rec.must_eq(notifications_matching(api, seller_tok, type_="trade_completed", link_id=data["id"]), [], "单方确认不得通知为交易已完成")

    with rec.step(
        "US-06-AC-02b",
        us="US-06",
        sc="SC-05-08",
        desc="本人重复提交完成确认幂等返回既有进度",
        expected="200 existing=true，不新增确认记录",
    ):
        resp = submit_confirmation(api, ctx, "p05_t_agree", "p05_buyer1")
        rec.must_eq(resp.json().get("existing"), True, "重复确认 existing 标记")
        data = refresh_trade(api, ctx, "p05_t_agree")
        rec.must_eq(len(data.get("confirmations") or []), 1, "重复确认不应新增记录")

    with rec.step(
        "US-05-AC-07a",
        us="US-05",
        sc="SC-05-08",
        desc="另一方完成确认：双方记录互不覆盖，交易完成、商品默认下架、解冻留痕",
        expected="200 双方均确认完成；completed + finished_at；两条 is_current 确认；商品 delisted；分支归档",
    ):
        resp = submit_confirmation(api, ctx, "p05_t_agree", "p05_seller", note="已收到货款")
        rec.must("已完成" in detail_text(resp), f"双方确认响应文案，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p05_t_agree")
        rec.must_eq(data.get("status"), "completed", "双确认后交易状态")
        rec.must(data.get("finished_at") is not None, "完成后 finished_at")
        rec.must_eq(data.get("my_confirmed"), True, "完成后本人确认")
        rec.must_eq(data.get("other_party_confirmed"), True, "完成后对方确认")
        confirmations = data.get("confirmations") or []
        rec.must_eq(len(confirmations), 2, "双方确认记录条数")
        confirmer_ids = {c.get("confirmer_id") for c in confirmations}
        rec.must_eq(confirmer_ids, {ctx.account("p05_buyer1")["id"], ctx.account("p05_seller")["id"]}, "双方确认人")
        rec.must(all(c.get("is_current") for c in confirmations), "双方确认均为当前记录")
        rec.must_eq(data.get("conversation_archived"), True, "完成后分支归档")
        rec.must_eq(data.get("confirm_wait_started_at"), None, "完成后结束等待计时")
        rec.must_eq(refresh_product(api, ctx, "p05_agree").get("status"), "delisted", "完成后商品默认下架")
        notes = notifications_matching(api, b1, type_="trade_completed", link_id=data["id"])
        rec.must(len(notes) >= 1, "买方应收到 trade_completed 通知")
        notes = notifications_matching(api, seller_tok, type_="trade_completed", link_id=data["id"])
        rec.must(len(notes) >= 1, "卖方应收到 trade_completed 通知")
        transitions = trade_transitions(api, b1, data["id"])
        rec.must_eq(transitions[-1].get("from_status"), "in_progress", "完成转移前状态")
        rec.must_eq(transitions[-1].get("to_status"), "completed", "完成转移后状态")
        rec.must_eq(transitions[-1].get("trigger"), "both_confirmed", "完成转移 trigger")

    with rec.step(
        "US-06-AC-06a",
        us="US-06",
        sc="SC-05-01",
        desc="完成确认记录仅交易双方可见：双方均可查看确认人/时间/说明历史，第三方与未认领管理员不可访问",
        expected="双方 GET 交易详情均含两条当前确认；第三方 404；管理员无依据 403",
    ):
        trade = ctx.trades["p05_t_agree"]
        buyer_view = trade_detail(api, b1, trade["id"])
        seller_view = trade_detail(api, seller_tok, trade["id"])
        for view, label in ((buyer_view, "买方"), (seller_view, "卖方")):
            confirmations = view.get("confirmations") or []
            rec.must_eq(len(confirmations), 2, f"{label}可见确认记录数")
            rec.must(all(c.get("confirmed_at") for c in confirmations), f"{label}可见确认时间")
            rec.must_eq({c.get("confirmer_id") for c in confirmations}, {ctx.account("p05_buyer1")["id"], ctx.account("p05_seller")["id"]}, f"{label}可见确认人")
        resp = api.get(f"/trades/{trade['id']}", token=outsider, expected=404)
        rec.must("交易不存在" in detail_text(resp), "第三方不可查看交易确认历史")
        resp = api.get(f"/admin/trades/{trade['id']}", token=ctx.token("admin"), expected=403)
        rec.must("认领" in detail_text(resp), "管理员未认领相关事项不可查看私人交易记录")

    with rec.step(
        "US-05-AC-10a",
        us="US-05",
        sc="SC-05-01",
        desc="已完成交易的分支归档后历史可读、发送被拒绝",
        expected="200 历史可读；409 已归档不可发送",
    ):
        data = refresh_trade(api, ctx, "p05_t_agree")
        branch = branch_of(api, ctx, "p05_t_agree")
        rec.must_eq(branch.get("archived"), True, "完成分支归档标记")
        rec.must(len(branch.get("messages") or []) >= 1, "归档分支历史应可读")
        resp = api.post(
            f"/conversations/{data['conversation_id']}/messages",
            token=b1,
            json_body={"content": "完成后还能发消息吗"},
            expected=409,
        )
        rec.must("归档" in detail_text(resp), f"归档分支发送应 409，实际 {detail_text(resp)}")

    with rec.step(
        "US-05-AC-10b",
        us="US-05",
        sc="SC-05-01",
        desc="完成后商品默认下架，卖方明确重新上架后恢复公开可交易",
        expected="delisted -> POST relist 200 listed -> 搜索可见",
    ):
        api.post(f"/products/{ctx.products['p05_agree']['id']}/relist", token=seller_tok, expected=200)
        product = refresh_product(api, ctx, "p05_agree")
        rec.must_eq(product.get("status"), "listed", "重新上架后商品状态")
        data = search_products(api, b1, {"keyword": "交易首次约定与完成样本", "page_size": 50})
        rec.must(ctx.products["p05_agree"]["id"] in {c["id"] for c in data["items"]}, "重新上架后应回到在售搜索")

    with rec.step(
        "US-05-AC-10c",
        us="US-05",
        sc="SC-05-01",
        desc="同一商品再次交易创建新交易与新分支，不复用旧对话",
        expected="新请求 status 待接受、新 conversation_id 不同于已完成分支",
    ):
        request_trade(api, ctx, "p05_t_agree_again", "p05_agree", "p05_buyer2")
        again = ctx.trades["p05_t_agree_again"]
        rec.must(again["id"] != ctx.trades["p05_t_agree"]["id"], "再次交易应为新交易 id")
        rec.must(again.get("conversation_id") != ctx.trades["p05_t_agree"].get("conversation_id"), "再次交易应使用新分支")
        rec.must_eq(again.get("status"), "pending_acceptance", "再次请求状态")
        api.post(f"/trades/{again['id']}/withdraw", token=b2, expected=200)

    with rec.step(
        "US-06-AC-03a",
        us="US-06",
        sc="SC-05-01",
        desc="已完成交易不可由普通用户重复确认/撤销历史",
        expected="重复完成确认 409 仅进行中交易可提交",
    ):
        resp = submit_confirmation(api, ctx, "p05_t_agree", "p05_buyer1", expected=409)
        rec.must("进行中" in detail_text(resp), f"完成后确认应 409，实际 {detail_text(resp)}")

    # ================================================================ US-05-AC-06 取消
    with rec.step(
        "US-05-AC-06a",
        us="US-05",
        sc="SC-05-10",
        desc="约定前卖方申请取消须买方同意：申请后不自动终止，买方确认后终止",
        expected="申请 200 待同意（仍 in_progress）；卖方确认本人申请 400；买方确认后 terminated",
    ):
        request_trade(api, ctx, "p05_t_cancel_pre", "p05_cancel_pre_seller", "p05_buyer1")
        api.post(f"/trades/{ctx.trades['p05_t_cancel_pre']['id']}/accept", token=seller_tok, expected=200)
        resp = trade_cancel(api, ctx, "p05_t_cancel_pre", "p05_seller", reason="临时有事无法交易")
        rec.must("等待对方同意" in detail_text(resp), f"取消申请文案，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p05_t_cancel_pre")
        rec.must_eq(data.get("status"), "in_progress", "取消申请未同意前不自动终止")
        rec.must_eq(data.get("cancel_requested_by"), ctx.account("p05_seller")["id"], "取消申请人")
        notes = notifications_matching(api, b1, type_="cancel_requested", link_id=data["id"])
        rec.must(len(notes) >= 1, "待确认方应收到 cancel_requested 通知")
        resp = confirm_cancel(api, ctx, "p05_t_cancel_pre", "p05_seller", expected=400)
        rec.must("本人" in detail_text(resp), f"确认本人取消申请应 400，实际 {detail_text(resp)}")
        resp = confirm_cancel(api, ctx, "p05_t_cancel_pre", "p05_buyer1")
        rec.must("双方同意" in detail_text(resp), f"同意取消文案，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p05_t_cancel_pre")
        rec.must_eq(data.get("status"), "terminated", "双方同意后交易终止")
        transitions = trade_transitions(api, b1, data["id"])
        rec.must_eq(transitions[-1].get("trigger"), "cancel_agreed", "双方同意取消 trigger")
        rec.must_eq(refresh_product(api, ctx, "p05_cancel_pre_seller").get("status"), "delisted", "终止后商品默认下架")
        notes = notifications_matching(api, b1, type_="trade_terminated", link_id=data["id"])
        rec.must(len(notes) >= 1, "买方应收到 trade_terminated 通知")

    with rec.step(
        "US-05-AC-06b",
        us="US-05",
        sc="SC-05-10",
        desc="约定生效后须双方同意才终止：一方申请后不自动终止，另一方同意后 terminated",
        expected="申请后仍 in_progress；同意后 terminated + 计失败状态",
    ):
        request_trade(api, ctx, "p05_t_cancel_after", "p05_cancel_after", "p05_buyer1")
        api.post(f"/trades/{ctx.trades['p05_t_cancel_after']['id']}/accept", token=seller_tok, expected=200)
        aid = propose_agreement(api, ctx, "p05_t_cancel_after", "p05_buyer1").json()["id"]
        confirm_agreement(api, ctx, "p05_t_cancel_after", aid, "p05_seller")
        resp = trade_cancel(api, ctx, "p05_t_cancel_after", "p05_seller")
        rec.must("等待对方同意" in detail_text(resp), "约定后取消申请需要对方同意")
        data = refresh_trade(api, ctx, "p05_t_cancel_after")
        rec.must_eq(data.get("status"), "in_progress", "约定后取消申请未同意前不终止")
        rec.must_eq(data.get("effective_agreement") is not None, True, "取消申请不清除有效约定")
        confirm_cancel(api, ctx, "p05_t_cancel_after", "p05_buyer1")
        data = refresh_trade(api, ctx, "p05_t_cancel_after")
        rec.must_eq(data.get("status"), "terminated", "约定后双方同意终止")
        rec.must_eq(refresh_product(api, ctx, "p05_cancel_after").get("status"), "delisted", "终止后商品默认下架")

    with rec.step(
        "US-05-AC-06c",
        us="US-05",
        sc="SC-05-10",
        desc="取消申请可撤回；撤回后确认取消返回 409",
        expected="200 已撤回；cancel_requested_by=null；再确认 409 没有待确认申请",
    ):
        request_trade(api, ctx, "p05_t_cancel_withdraw", "p05_cancel_withdraw", "p05_buyer1")
        api.post(f"/trades/{ctx.trades['p05_t_cancel_withdraw']['id']}/accept", token=seller_tok, expected=200)
        aid = propose_agreement(api, ctx, "p05_t_cancel_withdraw", "p05_buyer1").json()["id"]
        confirm_agreement(api, ctx, "p05_t_cancel_withdraw", aid, "p05_seller")
        resp = trade_cancel(api, ctx, "p05_t_cancel_withdraw", "p05_buyer1")
        rec.must("等待对方同意" in detail_text(resp), "买方取消申请")
        resp = withdraw_cancel(api, ctx, "p05_t_cancel_withdraw", "p05_seller", expected=409)
        rec.must("本人" in detail_text(resp), f"非申请人撤回取消应 409，实际 {detail_text(resp)}")
        resp = withdraw_cancel(api, ctx, "p05_t_cancel_withdraw", "p05_buyer1")
        rec.must("已撤回" in detail_text(resp), f"撤回取消申请文案，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p05_t_cancel_withdraw")
        rec.must_eq(data.get("cancel_requested_by"), None, "撤回后取消申请人清空")
        resp = confirm_cancel(api, ctx, "p05_t_cancel_withdraw", "p05_seller", expected=409)
        rec.must("没有" in detail_text(resp), f"无取消申请时确认应 409，实际 {detail_text(resp)}")

    with rec.step(
        "US-05-AC-06d",
        us="US-05",
        sc="SC-05-10",
        desc="约定生效后双方同意取消可终止（取消申请撤回后重新申请并生效）",
        expected="撤回后交易保持进行中；再次申请+同意后 terminated；已终止交易再取消 409",
    ):
        data = refresh_trade(api, ctx, "p05_t_cancel_withdraw")
        rec.must_eq(data.get("status"), "in_progress", "取消撤回后交易保持进行中")
        trade_cancel(api, ctx, "p05_t_cancel_withdraw", "p05_seller")
        confirm_cancel(api, ctx, "p05_t_cancel_withdraw", "p05_buyer1")
        data = refresh_trade(api, ctx, "p05_t_cancel_withdraw")
        rec.must_eq(data.get("status"), "terminated", "双方同意后终止")
        resp = trade_cancel(api, ctx, "p05_t_cancel_withdraw", "p05_buyer1", expected=409)
        rec.must("状态不能取消" in detail_text(resp), f"已终止交易再取消应 409，实际 {detail_text(resp)}")

    # ================================================================ US-05-AC-08 / SC-06 争议
    with rec.step(
        "US-05-AC-08a",
        us="US-05",
        sc="SC-06-01",
        desc="任一方发起争议：进入 disputed、结束原单方确认计时、保持锁单、创建争议事项、通知对方",
        expected="200 case_id；status=disputed；confirm_wait 清空；商品仍 in_transaction；notification trade_dispute",
    ):
        request_trade(api, ctx, "p05_t_dispute_user", "p05_dispute_user", "p05_buyer1")
        api.post(f"/trades/{ctx.trades['p05_t_dispute_user']['id']}/accept", token=seller_tok, expected=200)
        aid = propose_agreement(api, ctx, "p05_t_dispute_user", "p05_buyer1").json()["id"]
        confirm_agreement(api, ctx, "p05_t_dispute_user", aid, "p05_seller")
        submit_confirmation(api, ctx, "p05_t_dispute_user", "p05_buyer1")
        before = refresh_trade(api, ctx, "p05_t_dispute_user")
        rec.must(before.get("confirm_wait_started_at") is not None, "争议前应有单方确认计时")
        resp = create_dispute(api, ctx, "p05_t_dispute_user", "p05_seller", description="交付时间未达成一致，需要核实")
        case_id = resp.json().get("case_id")
        rec.must(case_id is not None, "发起争议应返回 case_id")
        data = refresh_trade(api, ctx, "p05_t_dispute_user")
        rec.must_eq(data.get("status"), "disputed", "发起争议后交易状态")
        rec.must_eq(data.get("confirm_wait_started_at"), None, "进入争议即结束原未回应计时")
        rec.must_eq(data.get("frozen"), False, "争议本身不自动冻结")
        rec.must_eq(refresh_product(api, ctx, "p05_dispute_user").get("status"), "in_transaction", "争议保持商品锁单")
        notes = notifications_matching(api, b1, type_="trade_dispute", link_id=data["id"])
        rec.must(len(notes) >= 1, "对方应收到 trade_dispute 通知")
        transitions = trade_transitions(api, b1, data["id"])
        rec.must_eq(transitions[-1].get("to_status"), "disputed", "争议转移后状态")
        rec.must_eq(transitions[-1].get("trigger"), "dispute_created", "争议转移 trigger")
        rec.must_eq(transitions[-1].get("reason"), "交付时间未达成一致，需要核实", "争议说明留痕")

    with rec.step(
        "US-05-AC-08b",
        us="US-05",
        sc="SC-06-05",
        desc="争议中普通用户不能直接完成确认（须先恢复进行中）",
        expected="409 仅进行中交易可提交完成确认",
    ):
        resp = submit_confirmation(api, ctx, "p05_t_dispute_user", "p05_buyer1", expected=409)
        rec.must("进行中" in detail_text(resp), f"争议中确认应 409，实际 {detail_text(resp)}")

    with rec.step(
        "US-05-AC-08c",
        us="US-05",
        sc="SC-06-01",
        desc="双方确认解决：单方先确认（等待对方），双方确认后恢复进行中、清当前确认、保留有效约定",
        expected="单方 200 等待；双方确认 200 恢复；confirmations 旧记录 is_current=false；wait 为空；约定保留",
    ):
        trade = ctx.trades["p05_t_dispute_user"]
        resp = resolve_dispute(api, ctx, "p05_t_dispute_user", "p05_buyer1")
        rec.must("等待对方" in detail_text(resp), f"单方确认解决文案，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p05_t_dispute_user")
        rec.must_eq(data.get("status"), "disputed", "单方确认解决不改变状态")
        rec.must_eq(data.get("resolution_confirmed_by"), ctx.account("p05_buyer1")["id"], "解决确认人")
        notes = notifications_matching(api, seller_tok, type_="dispute_resolved", link_id=data["id"])
        rec.must(len(notes) >= 1, "对方应收到 dispute_resolved 通知")
        resp = resolve_dispute(api, ctx, "p05_t_dispute_user", "p05_buyer1")
        rec.must_eq(resp.json().get("existing"), True, "重复确认解决幂等")
        resp = resolve_dispute(api, ctx, "p05_t_dispute_user", "p05_seller")
        rec.must("恢复进行中" in detail_text(resp), f"双方确认解决文案，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p05_t_dispute_user")
        rec.must_eq(data.get("status"), "in_progress", "双方确认解决后恢复进行中")
        rec.must_eq(data.get("resolution_confirmed_by"), None, "恢复后清空解决确认人")
        rec.must_eq(data.get("confirm_wait_started_at"), None, "恢复不启动计时")
        rec.must_eq(data.get("agreement_stage"), "awaiting_completion", "有有效约定回待完成阶段")
        rec.must(data.get("effective_agreement") is not None, "恢复保留有效约定")
        old_confirmations = data.get("confirmations") or []
        rec.must(old_confirmations, "历史确认记录应保留")
        rec.must(not any(c.get("is_current") for c in old_confirmations), "恢复时清空当前确认标记")
        rec.must_eq(data.get("my_confirmed"), False, "恢复后 my_confirmed=false")
        rec.must_eq(data.get("other_party_confirmed"), False, "恢复后 other_party_confirmed=false")
        transitions = trade_transitions(api, b1, data["id"])
        rec.must_eq(transitions[-1].get("to_status"), "in_progress", "恢复转移后状态")
        rec.must_eq(transitions[-1].get("trigger"), "dispute_resolved", "恢复转移 trigger")

    with rec.step(
        "US-06-AC-04a",
        us="US-06",
        sc="SC-06-07",
        desc="争议恢复后重新提交完成确认才产生新记录并开始完整计时",
        expected="新确认 is_current=true、历史保留、confirm_wait_started_at 非空",
    ):
        resp = submit_confirmation(api, ctx, "p05_t_dispute_user", "p05_seller", note="争议已解决，重新确认")
        rec.must("等待对方确认" in detail_text(resp), f"恢复后重新确认文案，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p05_t_dispute_user")
        rec.must(data.get("confirm_wait_started_at") is not None, "重新确认应开始新的完整计时")
        confirmations = data.get("confirmations") or []
        rec.must_eq(len(confirmations), 2, "历史确认 + 新确认记录数")
        current = [c for c in confirmations if c.get("is_current")]
        rec.must_eq(len(current), 1, "当前确认仅一条")
        rec.must_eq(current[0].get("confirmer_id"), ctx.account("p05_seller")["id"], "当前确认人")
        rec.must_eq(current[0].get("note"), "争议已解决，重新确认", "重新确认说明")
        submit_confirmation(api, ctx, "p05_t_dispute_user", "p05_buyer1")
        data = refresh_trade(api, ctx, "p05_t_dispute_user")
        rec.must_eq(data.get("status"), "completed", "恢复后双方重新确认完成")

    with rec.step(
        "US-05-AC-08d",
        us="US-05",
        sc="SC-06-01",
        desc="争议期间双方同意取消可终止，不必等待管理员（TR-18）",
        expected="争议中 cancel 申请 + 对方同意 -> terminated",
    ):
        request_trade(api, ctx, "p05_t_dispute_cancel", "p05_reject", "p05_buyer2")
        api.post(f"/trades/{ctx.trades['p05_t_dispute_cancel']['id']}/accept", token=seller_tok, expected=200)
        aid = propose_agreement(api, ctx, "p05_t_dispute_cancel", "p05_buyer2").json()["id"]
        confirm_agreement(api, ctx, "p05_t_dispute_cancel", aid, "p05_seller")
        create_dispute(api, ctx, "p05_t_dispute_cancel", "p05_buyer2", description="争议后协商终止")
        trade_cancel(api, ctx, "p05_t_dispute_cancel", "p05_seller")
        confirm_cancel(api, ctx, "p05_t_dispute_cancel", "p05_buyer2")
        data = refresh_trade(api, ctx, "p05_t_dispute_cancel")
        rec.must_eq(data.get("status"), "terminated", "争议中双方同意取消后终止")
        rec.must_eq(data.get("conversation_archived"), True, "终止后分支归档")
        rec.must_eq(refresh_product(api, ctx, "p05_reject").get("status"), "delisted", "终止后商品默认下架")

    # ================================================================ 管理员解决争议
    with rec.step(
        "US-05-AC-08e",
        us="US-05",
        sc="SC-06-03",
        desc="管理员管理路径：未认领相关事项时不能查看/调整私人交易（403）",
        expected="403 须先认领与本交易相关处置事项",
    ):
        request_trade(api, ctx, "p05_t_dispute_admin", "p05_dispute_admin", "p05_buyer1")
        api.post(f"/trades/{ctx.trades['p05_t_dispute_admin']['id']}/accept", token=seller_tok, expected=200)
        aid = propose_agreement(api, ctx, "p05_t_dispute_admin", "p05_buyer1").json()["id"]
        confirm_agreement(api, ctx, "p05_t_dispute_admin", aid, "p05_seller")
        create_dispute(api, ctx, "p05_t_dispute_admin", "p05_buyer1", description="需要管理员核查交付争议")
        trade = ctx.trades["p05_t_dispute_admin"]
        resp = api.get(f"/admin/trades/{trade['id']}", token=ctx.token("admin"), expected=403)
        rec.must("认领" in detail_text(resp), f"管理员未认领事项查看交易应 403，实际 {detail_text(resp)}")
        resp = api.post(
            f"/admin/trades/{trade['id']}/adjust",
            token=ctx.token("admin"),
            json_body={"to_status": "in_progress", "reason": "无依据调整"},
            expected=403,
        )
        rec.must("认领" in detail_text(resp), f"管理员未认领事项调整交易应 403，实际 {detail_text(resp)}")

    with rec.step(
        "US-05-AC-08f",
        us="US-05",
        sc="SC-06-03",
        desc="认领争议事项的管理员可查看交易并依据调整恢复进行中、通知双方",
        expected="claim 200；admin GET 200；adjust 200 -> in_progress + 转移 admin_restore + trade_adjusted 通知",
    ):
        case = admin_claim_trade_case(api, ctx, "p05_t_dispute_admin")
        trade = ctx.trades["p05_t_dispute_admin"]
        view = api.get(f"/admin/trades/{trade['id']}", token=ctx.token("admin"), params={"case_id": case["id"]}, expected=200).json()
        rec.must_eq(view.get("status"), "disputed", "管理视角交易状态")
        rec.must_eq(view.get("frozen"), False, "争议交易未冻结")
        resp = admin_adjust(api, ctx, "p05_t_dispute_admin", "in_progress", case_id=case["id"], reason="双方已协商一致，管理员核实恢复")
        rec.must("已调整" in detail_text(resp), f"管理调整响应文案，实际 {detail_text(resp)}")
        data = refresh_trade(api, ctx, "p05_t_dispute_admin")
        rec.must_eq(data.get("status"), "in_progress", "管理员恢复后交易状态")
        rec.must_eq(data.get("confirm_wait_started_at"), None, "管理恢复不启动计时")
        rec.must(data.get("effective_agreement") is not None, "管理恢复保留有效约定")
        transitions = trade_transitions(api, b1, data["id"])
        rec.must_eq(transitions[-1].get("trigger"), "admin_restore", "管理恢复转移 trigger")
        rec.must_eq(transitions[-1].get("actor_role"), "admin", "管理恢复 actor_role")
        rec.must_eq(transitions[-1].get("basis_case_id"), case["id"], "管理恢复依据事项")
        notes = notifications_matching(api, b1, type_="trade_adjusted", link_id=data["id"])
        rec.must(len(notes) >= 1, "买方应收到 trade_adjusted 通知")
        notes = notifications_matching(api, seller_tok, type_="trade_adjusted", link_id=data["id"])
        rec.must(len(notes) >= 1, "卖方应收到 trade_adjusted 通知")

    with rec.step(
        "US-05-AC-08g",
        us="US-05",
        sc="SC-06-03",
        desc="管理调整边界：非法目标状态 422、重复调整同状态 409，管理员可直接终止并联动商品",
        expected="422 非法状态；409 已处于目标状态；terminated + 商品下架",
    ):
        trade = ctx.trades["p05_t_dispute_admin"]
        case_id = trade["case_id"]
        resp = api.post(
            f"/admin/trades/{trade['id']}/adjust",
            token=ctx.token("admin"),
            json_body={"to_status": "not_a_status", "reason": "非法目标状态校验", "case_id": case_id},
            expected=422,
        )
        rec.must("非法" in detail_text(resp), f"非法目标状态应 422，实际 {detail_text(resp)}")
        resp = admin_adjust(api, ctx, "p05_t_dispute_admin", "in_progress", case_id=case_id, expected=409)
        rec.must("目标状态" in detail_text(resp), f"重复调整同状态应 409，实际 {detail_text(resp)}")
        admin_adjust(api, ctx, "p05_t_dispute_admin", "terminated", case_id=case_id, reason="管理员依据核查终止交易")
        data = refresh_trade(api, ctx, "p05_t_dispute_admin")
        rec.must_eq(data.get("status"), "terminated", "管理员终止后状态")
        rec.must(data.get("finished_at") is not None, "管理员终止后 finished_at")
        rec.must_eq(refresh_product(api, ctx, "p05_dispute_admin").get("status"), "delisted", "管理员终止后商品默认下架")

    # ================================================================ US-05-AC-11 D-49 约定变更
    with rec.step(
        "US-05-AC-05a",
        us="US-05",
        sc="SC-05-13",
        desc="已有单方确认时提出约定变更但对方不同意：保留原约定、当前确认与计时，取消权阶段不退回",
        expected="effective_agreement 仍为原 id；my_confirmed=true；confirm_wait_started_at 不变；历史保留 rejected 变更",
    ):
        request_trade(api, ctx, "p05_t_d49", "p05_d49", "p05_buyer1")
        api.post(f"/trades/{ctx.trades['p05_t_d49']['id']}/accept", token=seller_tok, expected=200)
        aid_a = propose_agreement(api, ctx, "p05_t_d49", "p05_seller").json()["id"]
        confirm_agreement(api, ctx, "p05_t_d49", aid_a, "p05_buyer1")
        submit_confirmation(api, ctx, "p05_t_d49", "p05_buyer1", note="按原约定已完成")
        before = refresh_trade(api, ctx, "p05_t_d49")
        rec.must(before.get("confirm_wait_started_at") is not None, "变更前应有计时")
        effective_before = (before.get("effective_agreement") or {}).get("id")
        wait_before = before.get("confirm_wait_started_at")
        change = dict(AGREEMENT_TEMPLATE)
        change["delivery_time"] = "2026-11-03 20:00"
        change["amount_cents"] = 9500
        aid_b = api.post(f"/trades/{ctx.trades['p05_t_d49']['id']}/agreements", token=seller_tok, json_body=change, expected=200).json()["id"]
        api.post(f"/trades/{ctx.trades['p05_t_d49']['id']}/agreements/{aid_b}/reject", token=b1, expected=200)
        after = refresh_trade(api, ctx, "p05_t_d49")
        rec.must_eq((after.get("effective_agreement") or {}).get("id"), effective_before, "未同意变更保留原约定")
        rec.must_eq(after.get("my_confirmed"), True, "未同意变更不清空当前确认")
        rec.must_eq(after.get("confirm_wait_started_at"), wait_before, "未同意变更不重置计时")
        rec.must_eq(after.get("agreement_stage"), "awaiting_completion", "未同意变更不退回首次约定前")
        history = after.get("agreement_history") or []
        rec.must_eq(history[-1].get("status"), "rejected", "被拒绝的变更历史保留")
        # 变更未生效不恢复首次约定前买方直接取消权（4.15）：仍须对方同意
        resp = trade_cancel(api, ctx, "p05_t_d49", "p05_buyer1")
        rec.must("等待对方同意" in detail_text(resp), "有有效约定时买方取消须对方同意，不恢复直接取消权")
        withdraw_cancel(api, ctx, "p05_t_d49", "p05_buyer1")
        rec.must_eq(refresh_trade(api, ctx, "p05_t_d49").get("status"), "in_progress", "撤回取消申请后交易仍进行中")
        # 收尾并补充：单方已确认完成后，双方仍可同意取消（BR-06）
        trade_cancel(api, ctx, "p05_t_d49", "p05_seller")
        confirm_cancel(api, ctx, "p05_t_d49", "p05_buyer1")
        ended = refresh_trade(api, ctx, "p05_t_d49")
        rec.must_eq(ended.get("status"), "terminated", "单方已确认后双方同意仍可取消")
        rec.must_eq(refresh_product(api, ctx, "p05_d49").get("status"), "delisted", "取消终止后商品默认下架")

    with rec.step(
        "US-05-AC-11b",
        us="US-05",
        sc="SC-05-13",
        desc="约定变更经对方同意后生效：清空双方当前确认、结束旧计时，保留历史（D-49）",
        expected="新约定生效；旧确认 is_current=false；wait 清空；旧约定 superseded；不自动重新计时",
    ):
        request_trade(api, ctx, "p05_t_d49b", "p05_d49b", "p05_buyer1")
        api.post(f"/trades/{ctx.trades['p05_t_d49b']['id']}/accept", token=seller_tok, expected=200)
        base = dict(AGREEMENT_TEMPLATE)
        aid_a = api.post(f"/trades/{ctx.trades['p05_t_d49b']['id']}/agreements", token=seller_tok, json_body=base, expected=200).json()["id"]
        api.post(f"/trades/{ctx.trades['p05_t_d49b']['id']}/agreements/{aid_a}/confirm", token=b1, expected=200)
        submit_confirmation(api, ctx, "p05_t_d49b", "p05_buyer1", note="原约定下已确认")
        before = refresh_trade(api, ctx, "p05_t_d49b")
        rec.must(before.get("confirm_wait_started_at") is not None, "变更生效前应有旧计时")
        changed = dict(base)
        changed["amount_cents"] = 9900
        changed["payment_timing"] = "交付前支付"
        aid_c = api.post(f"/trades/{ctx.trades['p05_t_d49b']['id']}/agreements", token=seller_tok, json_body=changed, expected=200).json()["id"]
        api.post(f"/trades/{ctx.trades['p05_t_d49b']['id']}/agreements/{aid_c}/confirm", token=b1, expected=200)
        after = refresh_trade(api, ctx, "p05_t_d49b")
        rec.must_eq(after.get("status"), "in_progress", "变更生效不改变交易状态")
        rec.must_eq((after.get("effective_agreement") or {}).get("id"), aid_c, "变更生效后有效约定")
        rec.must_eq((after.get("effective_agreement") or {}).get("amount_cents"), 9900, "新约定金额")
        rec.must_eq(after.get("confirm_wait_started_at"), None, "变更生效结束旧计时")
        rec.must_eq(after.get("confirm_wait_remaining_seconds"), None, "变更生效清空剩余等待秒数")
        rec.must_eq(after.get("my_confirmed"), False, "变更生效清空当前确认（买方）")
        confirmations = after.get("confirmations") or []
        rec.must(confirmations, "历史确认记录应保留")
        rec.must(not any(c.get("is_current") for c in confirmations), "历史确认 is_current 全部清空")
        statuses = {(a.get("id"), a.get("status")) for a in after.get("agreement_history") or []}
        rec.must((aid_a, "superseded") in statuses, "原有效约定标记为 superseded 历史保留")
        rec.must((aid_c, "confirmed") in statuses, "变更约定为 confirmed")
        rec.must_eq(after.get("agreement_stage"), "awaiting_completion", "变更后仍处于待完成阶段（不退回首次约定前）")
        rec.must_eq(after.get("other_party_confirmed"), False, "变更生效清空对方确认")

    with rec.step(
        "US-05-AC-11c",
        us="US-05",
        sc="SC-05-13",
        desc="变更生效后不自动计时，任一方重新确认后才开始完整等待；随后双确认完成",
        expected="重新确认产生新记录且 wait 非空；双确认 completed",
    ):
        resp = submit_confirmation(api, ctx, "p05_t_d49b", "p05_seller", note="按新约定重新确认")
        rec.must("等待对方确认" in detail_text(resp), f"变更后重新确认文案，实际 {detail_text(resp)}")
        after = refresh_trade(api, ctx, "p05_t_d49b")
        rec.must(after.get("confirm_wait_started_at") is not None, "重新确认后开始完整计时")
        current = [c for c in (after.get("confirmations") or []) if c.get("is_current")]
        rec.must_eq(len(current), 1, "变更后新确认记录")
        submit_confirmation(api, ctx, "p05_t_d49b", "p05_buyer1")
        after = refresh_trade(api, ctx, "p05_t_d49b")
        rec.must_eq(after.get("status"), "completed", "变更后双方确认完成")
        rec.must_eq(refresh_product(api, ctx, "p05_d49b").get("status"), "delisted", "完成后商品默认下架")

    rec.skip(
        "US-05-AC-09",
        us="US-05",
        sc="SC-05-09",
        desc="单方确认 7 天未回应的超时转异常（时间加速场景）",
        reason="p08_abnormal_timeout 以 US-14 编号执行同一业务链路，仅作关联证据；本阶段不做数据库时间起点前移，不把该执行回填为本 AC",
    )

    rec.skip(
        "US-06-AC-05",
        us="US-06",
        sc="SC-05-01",
        desc="用户不得自行更正或删除已提交的完成确认（需认领管理员留痕调整）",
        reason="静态路由核对未发现用户端更正/删除确认接口，未做请求被拒绝的执行回归；p08/p07 的管理调整与留痕是另一路径，不据此补齐本 AC",
    )

    # ================================================================ D-48 旧交易恢复冲突
    with rec.step(
        "US-05-AC-08h",
        us="US-05",
        sc="SC-06-01",
        desc="D-48 前置：旧交易在争议中双方同意终止（已结束），商品下架；随后重新上架并产生新锁单交易",
        expected="旧交易 terminated；商品 delisted -> relist listed；新交易 in_progress 锁单",
    ):
        request_trade(api, ctx, "p05_t_d48_old", "p05_d48", "p05_buyer1")
        api.post(f"/trades/{ctx.trades['p05_t_d48_old']['id']}/accept", token=seller_tok, expected=200)
        aid = propose_agreement(api, ctx, "p05_t_d48_old", "p05_buyer1").json()["id"]
        confirm_agreement(api, ctx, "p05_t_d48_old", aid, "p05_seller")
        create_dispute(api, ctx, "p05_t_d48_old", "p05_buyer1", description="旧交易争议后协商终止")
        trade_cancel(api, ctx, "p05_t_d48_old", "p05_seller")
        confirm_cancel(api, ctx, "p05_t_d48_old", "p05_buyer1")
        old = refresh_trade(api, ctx, "p05_t_d48_old")
        rec.must_eq(old.get("status"), "terminated", "旧交易终止")
        rec.must_eq(refresh_product(api, ctx, "p05_d48").get("status"), "delisted", "旧交易终止后商品下架")
        api.post(f"/products/{ctx.products['p05_d48']['id']}/relist", token=seller_tok, expected=200)
        ctx.update_product("p05_d48", state="listed")
        request_trade(api, ctx, "p05_t_d48_new", "p05_d48", "p05_buyer2")
        api.post(f"/trades/{ctx.trades['p05_t_d48_new']['id']}/accept", token=seller_tok, expected=200)
        rec.must_eq(refresh_trade(api, ctx, "p05_t_d48_new").get("status"), "in_progress", "新交易锁单进行中")
        rec.must_eq(refresh_product(api, ctx, "p05_d48").get("status"), "in_transaction", "商品处于新交易锁单")

    with rec.step(
        "US-05-AC-08i",
        us="US-05",
        sc="SC-09-09",
        desc="D-48：恢复已结束旧交易为需锁单状态前校验同商品新锁单，冲突 409 且无副作用",
        expected="409 商品已存在另一笔锁单交易；旧交易保持 terminated、新交易与商品不变、无新增转移",
    ):
        old = ctx.trades["p05_t_d48_old"]
        case = admin_claim_trade_case(api, ctx, "p05_t_d48_old")
        transitions_before = trade_transitions(api, b1, old["id"])
        resp = api.post(
            f"/admin/trades/{old['id']}/adjust",
            token=ctx.token("admin"),
            json_body={"to_status": "in_progress", "reason": "D-48 恢复旧交易", "case_id": case["id"]},
            expected=409,
        )
        rec.must("锁单交易" in detail_text(resp), f"D-48 冲突应 409 锁单冲突，实际 {detail_text(resp)}")
        old_after = refresh_trade(api, ctx, "p05_t_d48_old")
        rec.must_eq(old_after.get("status"), "terminated", "冲突后旧交易状态不变")
        rec.must_eq(old_after.get("finished_at"), old.get("finished_at"), "冲突后旧交易结束时间不变")
        rec.must_eq(len(trade_transitions(api, b1, old["id"])), len(transitions_before), "冲突后不新增状态转移")
        rec.must_eq(refresh_trade(api, ctx, "p05_t_d48_new").get("status"), "in_progress", "新交易保持进行中")
        rec.must_eq(refresh_product(api, ctx, "p05_d48").get("status"), "in_transaction", "商品状态保持交易中")

    with rec.step(
        "US-05-AC-08j",
        us="US-05",
        sc="SC-09-09",
        desc="D-48：新交易结束后再次恢复旧交易成功（清确认/结束计时、分支保持归档）",
        expected="新交易 terminated -> 旧交易可恢复 in_progress；转移 admin_restore；分支仍归档",
    ):
        trade_cancel(api, ctx, "p05_t_d48_new", "p05_buyer2")
        rec.must_eq(refresh_trade(api, ctx, "p05_t_d48_new").get("status"), "terminated", "新交易约定前买方直接取消")
        rec.must_eq(refresh_product(api, ctx, "p05_d48").get("status"), "delisted", "新交易终止后商品下架")
        old = ctx.trades["p05_t_d48_old"]
        case_id = old["case_id"]
        resp = admin_adjust(api, ctx, "p05_t_d48_old", "in_progress", case_id=case_id, reason="新锁单已结束，恢复旧交易")
        rec.must("已调整" in detail_text(resp), "恢复旧交易成功文案")
        old_after = refresh_trade(api, ctx, "p05_t_d48_old")
        rec.must_eq(old_after.get("status"), "in_progress", "旧交易恢复进行中")
        rec.must_eq(old_after.get("finished_at"), None, "恢复后结束时间清空")
        rec.must_eq(old_after.get("confirm_wait_started_at"), None, "恢复不启动计时")
        rec.must_eq(old_after.get("conversation_archived"), True, "恢复不重新打开已归档分支（默认归档）")
        rec.must_eq(refresh_product(api, ctx, "p05_d48").get("status"), "in_transaction", "恢复后商品回到交易中")
        transitions = trade_transitions(api, b1, old["id"])
        rec.must_eq(transitions[-1].get("trigger"), "admin_restore", "恢复旧交易转移 trigger")
        admin_adjust(api, ctx, "p05_t_d48_old", "terminated", case_id=case_id, reason="D-48 场景收尾：管理员终止")
        rec.must_eq(refresh_trade(api, ctx, "p05_t_d48_old").get("status"), "terminated", "收尾终止旧交易")
