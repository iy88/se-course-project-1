"""p09 统计、本人业务与待办（US-10／US-11／US-12／US-13；SC-08／SC-11／SC-12）。

真实 HTTP 独立造数（不依赖其他阶段先运行）：
- 账户：优先复用 ctx 中同名账户（登录即可）；缺失时走真实注册验证码流程。若目标账户已封禁
  或存在有效交易冻结，改用本阶段回退账户，避免改动 qian 等既有样本的最终状态。
- 商品：真实上传图片 → 发布 → 管理员认领共享池事项 → 审核通过/不通过 → 下架/锁单。
- 交易：请求 → 接受 → 约定确认 → 完成确认 → 完成；另造终止、争议、拒绝、撤回、锁单关闭。
- 收藏、评价、举报（含证据图）、问询/说明/申辩、管理员核查结论全部走真实接口。
统计口径用“动作前后两次 GET /admin/stats 的计数差值”核对查询时点口径，不直接写库。
US-13 仅在 p02 已在本运行登记分类对象时复读核对，否则 SKIP（分类维护已由 p02 覆盖）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from e2e_support import (
    admin_claim_case,
    admin_list_cases,
    admin_stats,
    ensure_account,
    login_account,
    upload_image,
)

PHASE_ID = "p09"
PASSWORD = "secret123"
TAG_NAME = "电子产品"

# 统计响应中不得出现的资金/流水口径字段（BR-31、SC-08-06）
FORBIDDEN_MONEY_KEYS = (
    "amount",
    "revenue",
    "income",
    "payment",
    "money",
    "price",
    "cents",
    "流水",
    "资金",
    "成交额",
    "收入",
    "financial",
)

AGREEMENT_BODY = {
    "delivery_time": "2026-11-01 18:00",
    "delivery_location": "三食堂门口",
    "delivery_method": "当面自提",
    "amount_cents": 6600,
    "payment_method": "微信",
    "payment_timing": "当面支付",
}

PRODUCT_STATUSES = ("pending_review", "rejected", "listed", "in_transaction", "delisted")
TRADE_STATUSES = (
    "pending_acceptance",
    "rejected",
    "withdrawn",
    "closed",
    "in_progress",
    "disputed",
    "abnormal",
    "terminated",
    "completed",
)


# ---------------------------------------------------------------------------
# 账户与基础设施
# ---------------------------------------------------------------------------
def _admin_account(api, ctx):
    acct = ctx.accounts.get("admin")
    if acct and acct.get("token"):
        return acct
    return login_account(api, ctx, "admin", "admin@campus.edu", "admin123456")


def _actor(api, ctx, key: str, email: str, display_name: str):
    """返回 (账户, ctx 中使用的 key)。账户被封禁或存在有效交易冻结时使用本阶段回退账户。"""
    acct = ensure_account(api, ctx, key, email, display_name, PASSWORD)
    me = api.get("/auth/me", token=acct["token"], expected=200).json()
    if me.get("status") == "normal" and not me.get("has_frozen_trade"):
        return acct, key
    fallback_key = f"{key}_c2"
    fallback = ensure_account(api, ctx, fallback_key, f"c2.{key}@campus.edu", display_name, PASSWORD)
    ctx.note(
        f"p09：账户 {key} 当前 status={me.get('status')} has_frozen_trade={me.get('has_frozen_trade')}，"
        f"改用回退账户 {fallback_key} 造数"
    )
    return fallback, fallback_key


def _category_id(api, token: str, name: str = TAG_NAME) -> int:
    cats = api.get("/categories", token=token, expected=200).json()
    for cat in cats:
        if cat.get("name") == name and cat.get("status") == "active":
            return cat["id"]
    for cat in cats:
        if cat.get("status") == "active":
            return cat["id"]
    raise AssertionError("没有可用的商品分类标签，无法发布商品")


# ---------------------------------------------------------------------------
# 商品辅助
# ---------------------------------------------------------------------------
def _publish(api, token: str, title: str, image_key: str, category_id: int, *, price: int = 6600) -> dict:
    body = {
        "title": title,
        "description": "p09 真实 API 生命周期测试商品：用于统计口径、本人业务入口与待办核对。",
        "price_cents": price,
        "image_keys": [image_key],
        "tags": [{"category_id": category_id}],
    }
    return api.post("/products", token=token, json_body=body, expected=200).json()


def _pending_review_case(api, ctx, product_id: int) -> dict:
    for case in admin_list_cases(api, ctx, status="pending", case_type="product_review"):
        if case.get("product_id") == product_id:
            return case
    raise AssertionError(f"共享池中没有商品 #{product_id} 的待审核事项")


def _review_product(api, ctx, product_id: int, *, approve: bool, reason: str | None = None) -> dict:
    case = _pending_review_case(api, ctx, product_id)
    admin_claim_case(api, ctx, case["id"])
    body = {"result": "approved" if approve else "rejected"}
    if reason:
        body["reason"] = reason
    return api.post(
        f"/admin/products/cases/{case['id']}/review", token=ctx.token("admin"), json_body=body, expected=200
    ).json()


# ---------------------------------------------------------------------------
# 交易辅助
# ---------------------------------------------------------------------------
def _request(api, token: str, product_id: int) -> dict:
    return api.post("/trades/requests", token=token, json_body={"product_id": product_id}, expected=200).json()


def _accept(api, token: str, trade_id: int) -> dict:
    return api.post(f"/trades/{trade_id}/accept", token=token, expected=200).json()


def _reject(api, token: str, trade_id: int) -> dict:
    return api.post(
        f"/trades/{trade_id}/reject", token=token, json_body={"reason": "p09 卖方拒绝"}, expected=200
    ).json()


def _withdraw(api, token: str, trade_id: int) -> dict:
    return api.post(f"/trades/{trade_id}/withdraw", token=token, expected=200).json()


def _propose_agreement(api, token: str, trade_id: int) -> dict:
    return api.post(f"/trades/{trade_id}/agreements", token=token, json_body=AGREEMENT_BODY, expected=200).json()


def _confirm_agreement(api, token: str, trade_id: int, agreement_id: int) -> dict:
    return api.post(
        f"/trades/{trade_id}/agreements/{agreement_id}/confirm", token=token, expected=200
    ).json()


def _propose_cancel(api, token: str, trade_id: int) -> dict:
    return api.post(
        f"/trades/{trade_id}/cancel", token=token, json_body={"reason": "p09 发起取消申请"}, expected=200
    ).json()


def _confirm_completion(api, token: str, trade_id: int) -> dict:
    return api.post(f"/trades/{trade_id}/confirmations", token=token, json_body={}, expected=200).json()


def _dispute(api, token: str, trade_id: int) -> dict:
    return api.post(
        f"/trades/{trade_id}/disputes",
        token=token,
        json_body={"description": "p09 争议测试：交付方式与约定不一致"},
        expected=200,
    ).json()


def _trade(api, token: str, trade_id: int) -> dict:
    return api.get(f"/trades/{trade_id}", token=token, expected=200).json()


# ---------------------------------------------------------------------------
# 统计辅助
# ---------------------------------------------------------------------------
def _stats(api, ctx, params: dict | None = None) -> dict:
    return admin_stats(api, ctx, params=params)


def _dig(payload: dict, dotted: str):
    current = payload
    for part in dotted.split("."):
        current = current[part]
    return current


def _delta(api, ctx, rec, prev: dict, expected: dict[str, int], label: str) -> dict:
    """读取当前统计，与 prev 比较指定计数路径的变化量，返回当前统计作为新的 prev。"""
    current = _stats(api, ctx)
    failures = []
    for path, change in expected.items():
        actual = _dig(current, path) - _dig(prev, path)
        if actual != change:
            failures.append(f"{path} 变化 {actual:+d}（期望 {change:+d}）")
    rec.must(not failures, f"{label} 后统计计数不符：{'；'.join(failures)}")
    return current


def _find_forbidden_keys(node, path: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            lowered = str(key).lower()
            if any(token in lowered for token in FORBIDDEN_MONEY_KEYS):
                hits.append(f"{path}.{key}")
            hits.extend(_find_forbidden_keys(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            hits.extend(_find_forbidden_keys(value, f"{path}[{index}]"))
    return hits


# ---------------------------------------------------------------------------
# 通知 / 待办辅助
# ---------------------------------------------------------------------------
def _notifications(api, token: str, *, unread_only: bool = False, page: int = 1, page_size: int = 50) -> dict:
    return api.get(
        "/notifications",
        token=token,
        params={"unread_only": unread_only, "page": page, "page_size": page_size},
        expected=200,
    ).json()


def _find_notification(
    items: list[dict], *, type_: str | None = None, link_id: int | None = None, trade_id: int | None = None
) -> list[dict]:
    found = []
    for item in items:
        if type_ is not None and item.get("type") != type_:
            continue
        if link_id is not None and item.get("link_id") != link_id:
            continue
        payload = item.get("payload") or {}
        if trade_id is not None and payload.get("trade_id") != trade_id:
            continue
        found.append(item)
    return found


def _todos(api, token: str) -> dict:
    return api.get("/notifications/todos", token=token, expected=200).json()


def _find_todo(todos: dict, kind: str, link_id: int) -> dict | None:
    for item in todos.get("items") or []:
        if item.get("kind") == kind and item.get("link_id") == link_id:
            return item
    return None


def _need(*values) -> None:
    if any(value is None for value in values):
        raise AssertionError("前置数据缺失（p09 造数步骤失败），无法继续该检查")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run(ctx, api, rec):
    _admin_account(api, ctx)

    main, main_key = _actor(api, ctx, "chen", "chen@campus.edu", "陈同学")
    peer, peer_key = _actor(api, ctx, "liu", "liu@campus.edu", "刘同学")
    third, third_key = _actor(api, ctx, "wang", "wang@campus.edu", "王同学")

    main_token = main["token"]
    peer_token = peer["token"]
    third_token = third["token"]
    main_id = main["id"]

    # 真实图片上传（商品图；举报证据图另传 report 命名空间）
    product_image = upload_image(api, main_token, "product_textbook.jpg", namespace="product")
    product_image2 = upload_image(api, main_token, "product_second.jpg", namespace="product")
    evidence_image = upload_image(api, peer_token, "evidence_chat.jpg", namespace="report")
    ctx.remember_item(
        "file", "p09_product_image", product_image["key"], "p09 商品图", "uploaded", {"url": product_image["url"]}
    )
    ctx.remember_item(
        "file", "p09_evidence_image", evidence_image["key"], "p09 举报证据图", "uploaded", {"url": evidence_image["url"]}
    )
    image_key = product_image["key"]
    image_key2 = product_image2["key"]
    category_id = _category_id(api, main_token)

    # 数据占位：造数步骤失败时后续检查以 FAIL 形式暴露，而不是阶段崩溃
    p_pending = p_rejected = p_listed = p_delisted = None
    p_claimed = p_pending_req = None
    p_peer_mixed = p_peer_term = p_peer_done = p_peer_dispute = p_peer_closed = None
    p_third_fav = None
    t_v = t_u = t_q = t_r = t_s = t_t_main = t_t_third = t_p_rejected = t_p_withdrawn = t_agree = None
    report_of_main = None
    report_case_id = None
    review_main = None
    review_peer = None

    # ===================================================================
    # US-10 管理统计：权限、查询时点指标、范围与全部、失败口径、无资金口径
    # ===================================================================
    with rec.step(
        "P09-US10-AC-01-403",
        us="US-10",
        sc="SC-08-03",
        desc="普通校园用户访问管理统计入口被拒绝",
        expected="403 需要平台管理员权限",
    ):
        resp = api.get("/admin/stats", token=main_token, expected=403)
        rec.must_eq(resp.json().get("detail"), "需要平台管理员权限", "普通用户统计拒绝文案")

    with rec.step(
        "P09-US10-AC-01-401",
        us="US-10",
        sc="SC-08-03",
        desc="未登录访问管理统计入口返回 401",
        expected="401 未登录或登录已过期",
    ):
        resp = api.get("/admin/stats", expected=401)
        rec.must_eq(resp.json().get("detail"), "未登录或登录已过期", "未登录统计 401 文案")

    with rec.step(
        "P09-US10-AC-02-schema",
        us="US-10",
        sc="SC-08-01",
        desc="管理员查询时点指标：用户/商品各状态/待处理事项/交易各状态字段齐全且为计数",
        expected="结构完整、计数为非负整数、range 未选择时为空",
    ):
        stats = _stats(api, ctx)
        for path in (
            "users.total",
            "users.banned",
            *[f"products.{status}" for status in PRODUCT_STATUSES],
            "products.display_restricted",
            "pending.review_cases",
            "pending.report_cases",
            "pending.all_cases",
            *[f"trades.{status}" for status in TRADE_STATUSES],
            "trades.frozen_current",
        ):
            value = _dig(stats, path)
            rec.must(isinstance(value, int) and value >= 0, f"统计字段 {path} 应为非负整数，实际 {value!r}")
        rec.must_eq(stats["range"]["from"], None, "未选范围时 range.from")
        rec.must_eq(stats["range"]["to"], None, "未选范围时 range.to")

    with rec.step(
        "P09-US10-AC-02-users",
        us="US-10",
        sc="SC-08-01",
        desc="用户总数包含封禁用户并单列封禁数：与管理员用户列表逐项对账",
        expected="users.total 与列表条数一致；users.banned 与列表 banned 数一致（列表未超上限时）",
    ):
        stats = _stats(api, ctx)
        users = api.get(
            "/admin/users", token=ctx.token("admin"), params={"status": "all"}, expected=200
        ).json()
        banned_in_list = [user for user in users if user.get("status") == "banned"]
        rec.must_eq(stats["users"]["banned"], len(banned_in_list), "users.banned 与管理员列表封禁数")
        if stats["users"]["total"] <= 200:
            rec.must_eq(stats["users"]["total"], len(users), "users.total 与管理员列表条数")
            rec.must(
                {user["id"] for user in banned_in_list} <= {user["id"] for user in users},
                "封禁用户应被计入用户列表（总数含封禁用户）",
            )
        else:
            rec.must_eq(len(users), 200, "用户总数超过 200 时管理员列表应返回上限 200 条")
            rec.must(stats["users"]["total"] >= len(users), "users.total 应不小于列表条数")
        ctx.remember_item(
            "stats", "p09_stats_users", stats["users"].get("total"), "用户统计基线", "captured", dict(stats["users"])
        )

    with rec.step(
        "P09-US10-AC-03-default",
        us="US-10",
        sc="SC-08-02",
        desc="未选择时间范围时不套用默认范围：completed_trades 为空，同时点状态计数照常返回",
        expected="range.completed_trades is None；trades.completed 为查询时点计数",
    ):
        stats = _stats(api, ctx)
        rec.must_eq(stats["range"]["completed_trades"], None, "未选范围 completed_trades")
        rec.must(isinstance(stats["trades"]["completed"], int), "查询时点 completed 状态计数应为整数")

    with rec.step(
        "P09-US10-06-money",
        us="US-10",
        sc="SC-08-06",
        desc="统计不输出真实付款金额、流水或成交收入字段",
        expected="响应（含嵌套）不含 amount/revenue/payment/price/cents 等资金口径字段",
    ):
        hits = _find_forbidden_keys(_stats(api, ctx))
        rec.must(not hits, f"统计响应出现资金/流水口径字段：{hits[:8]}")

    # ---- 商品状态计数：发布/审核/下架逐动作核对 ----
    with rec.step(
        "P09-US10-AC-02-product-pending",
        us="US-10",
        sc="SC-08-01",
        desc="发布商品进入待审核：待审核商品数与待处理审核事项数同时 +1",
        expected="products.pending_review +1；pending.review_cases +1；pending.all_cases +1",
    ):
        prev = _stats(api, ctx)
        p_pending = _publish(api, main_token, "p09 待审核笔记本（本人商品）", image_key, category_id)
        ctx.remember_product("p09_main_pending", p_pending, seller=main_key, state="pending_review")
        rec.must_eq(p_pending.get("status"), "pending_review", "新发布商品状态")
        _delta(
            api, ctx, rec, prev,
            {"products.pending_review": 1, "pending.review_cases": 1, "pending.all_cases": 1},
            "发布待审商品",
        )

    with rec.step(
        "P09-US10-AC-02-product-approved",
        us="US-10",
        sc="SC-08-01",
        desc="审核通过：待审核商品数回落、在售商品数 +1、待处理审核事项 -1",
        expected="发布后 pending_review+1；通过后 pending_review-1、listed+1、review_cases-1",
    ):
        prev = _stats(api, ctx)
        p_listed = _publish(api, main_token, "p09 在售教材（本人商品，举报目标）", image_key, category_id, price=5200)
        prev = _delta(
            api, ctx, rec, prev,
            {"products.pending_review": 1, "pending.review_cases": 1, "pending.all_cases": 1},
            "发布待审商品",
        )
        _review_product(api, ctx, p_listed["id"], approve=True)
        ctx.remember_product("p09_main_listed", p_listed, seller=main_key, state="listed")
        _delta(
            api, ctx, rec, prev,
            {"products.pending_review": -1, "products.listed": 1, "pending.review_cases": -1, "pending.all_cases": -1},
            "审核通过",
        )

    with rec.step(
        "P09-US10-AC-02-product-rejected",
        us="US-10",
        sc="SC-08-01",
        desc="审核不通过：不通过商品数 +1、待审核商品数回落、待处理审核事项结清",
        expected="rejected +1；pending_review -1；review_cases -1",
    ):
        prev = _stats(api, ctx)
        p_rejected = _publish(api, main_token, "p09 退回补充商品（本人商品，含拒绝原因）", image_key2, category_id)
        prev = _delta(
            api, ctx, rec, prev,
            {"products.pending_review": 1, "pending.review_cases": 1, "pending.all_cases": 1},
            "发布待审商品",
        )
        _review_product(api, ctx, p_rejected["id"], approve=False, reason="退回补充：请更换或补充标签")
        ctx.remember_product("p09_main_rejected", p_rejected, seller=main_key, state="rejected")
        _delta(
            api, ctx, rec, prev,
            {"products.pending_review": -1, "products.rejected": 1, "pending.review_cases": -1, "pending.all_cases": -1},
            "审核不通过",
        )

    with rec.step(
        "P09-US10-AC-02-product-delisted",
        us="US-10",
        sc="SC-08-01",
        desc="下架：在售商品数 -1、已下架商品数 +1",
        expected="listed -1；delisted +1",
    ):
        prev = _stats(api, ctx)
        p_delisted = _publish(api, main_token, "p09 待下架商品（本人商品）", image_key, category_id)
        prev = _delta(
            api, ctx, rec, prev,
            {"products.pending_review": 1, "pending.review_cases": 1, "pending.all_cases": 1},
            "发布待审商品",
        )
        _review_product(api, ctx, p_delisted["id"], approve=True)
        prev = _delta(
            api, ctx, rec, prev,
            {"products.pending_review": -1, "products.listed": 1, "pending.review_cases": -1, "pending.all_cases": -1},
            "审核通过",
        )
        api.post(f"/products/{p_delisted['id']}/delist", token=main_token, expected=200)
        ctx.remember_product("p09_main_delisted", p_delisted, seller=main_key, state="delisted")
        _delta(api, ctx, rec, prev, {"products.listed": -1, "products.delisted": 1}, "主动下架")

    # ---- 其余商品批量造数（交易/本人业务/待办前置） ----
    with rec.step(
        "P09-SETUP-products",
        us="US-12",
        sc="SC-12-01",
        desc="通过真实发布+审核接口批量创建本人业务与待办所需的在售商品",
        expected="8 件商品全部发布并审核通过，状态 listed",
    ):
        prev = _stats(api, ctx)

        def make_listed(key: str, seller_key: str, token: str, title: str, img: str) -> dict:
            product = _publish(api, token, title, img, category_id)
            _review_product(api, ctx, product["id"], approve=True)
            ctx.remember_product(key, product, seller=seller_key, state="listed")
            return product

        p_claimed = make_listed("p09_main_claimed", main_key, main_token, "p09 本人卖方交易中商品", image_key)
        p_pending_req = make_listed(
            "p09_main_pending_req", main_key, main_token, "p09 本人卖方待接受请求商品", image_key2
        )
        p_peer_mixed = make_listed(
            "p09_peer_mixed", peer_key, peer_token, "p09 对方商品（拒绝/撤回/编辑历史）", image_key
        )
        p_peer_term = make_listed("p09_peer_term", peer_key, peer_token, "p09 对方商品（终止交易）", image_key2)
        p_peer_done = make_listed("p09_peer_done", peer_key, peer_token, "p09 对方商品（完成交易）", image_key)
        p_peer_dispute = make_listed(
            "p09_peer_dispute", peer_key, peer_token, "p09 对方商品（争议交易）", image_key2
        )
        p_peer_closed = make_listed(
            "p09_peer_closed", peer_key, peer_token, "p09 对方商品（锁单关闭请求）", image_key
        )
        p_third_fav = make_listed("p09_third_fav", third_key, third_token, "p09 第三方商品（收藏失效）", image_key)
        rec.must(
            all(
                p is not None
                for p in (
                    p_claimed, p_pending_req, p_peer_mixed, p_peer_term,
                    p_peer_done, p_peer_dispute, p_peer_closed, p_third_fav,
                )
            ),
            "批量商品创建结果",
        )
        _delta(
            api, ctx, rec, prev,
            {"products.pending_review": 0, "products.listed": 8, "pending.review_cases": 0, "pending.all_cases": 0},
            "批量发布并审核通过 8 件商品",
        )

    # ===================================================================
    # US-11 待办：卖方待接受请求、通知已读不办结、办结后移出
    # ===================================================================
    with rec.step(
        "P09-US10-AC-02-trade-request",
        us="US-10",
        sc="SC-08-01",
        desc="发起购买请求不锁单：待接受交易数 +1（商品仍在售）",
        expected="trades.pending_acceptance +1；products.listed 不变",
    ):
        _need(p_claimed)
        prev = _stats(api, ctx)
        t_v = _request(api, peer_token, p_claimed["id"])["id"]
        ctx.remember_trade("p09_t_v", {"id": t_v}, buyer=peer_key, seller=main_key, state="pending_acceptance")
        _delta(api, ctx, rec, prev, {"trades.pending_acceptance": 1, "products.listed": 0}, "买方发起请求")

    with rec.step(
        "P09-US11-AC-01-05",
        us="US-11",
        sc="SC-11-01",
        desc="卖方待接受请求出现在待办；站内通知与交易分支定位同一请求且不重复生成请求",
        expected="todos 含 request_pending（link_type=trade, action=accept_request）；通知指向同一交易分支；该商品仅 1 条待接受请求、1 条 request_created",
    ):
        _need(t_v, p_claimed)
        todos = _todos(api, main_token)
        item = _find_todo(todos, "request_pending", t_v)
        rec.must(item is not None, f"卖方待办缺少 request_pending:交易#{t_v}；实际 {todos.get('items')}")
        rec.must_eq(item.get("link_type"), "trade", "待办 link_type")
        rec.must_eq(item.get("link_id"), t_v, "待办 link_id")
        rec.must_eq(item.get("action"), "accept_request", "待办 action")
        detail = _trade(api, main_token, t_v)
        rec.must_eq(detail.get("status"), "pending_acceptance", "交易当前状态")
        conv_id = detail.get("conversation_id")
        rec.must(conv_id is not None, "交易应自动创建交易分支会话")
        notifications = _notifications(api, main_token)["items"]
        matched = _find_notification(notifications, type_="request_created", trade_id=t_v)
        rec.must_eq(len(matched), 1, "卖方 request_created 通知条数（不重复）")
        rec.must_eq(matched[0].get("link_type"), "conversation", "request_created 通知 link_type")
        rec.must_eq(matched[0].get("link_id"), conv_id, "request_created 通知与交易分支定位同一请求")
        conv = api.get(f"/conversations/{conv_id}", token=main_token, expected=200).json()
        rec.must_eq(conv.get("type"), "trade", "会话类型")
        rec.must_eq((conv.get("trade") or {}).get("id"), t_v, "会话绑定的交易")
        mine = api.get("/trades/mine", token=main_token, expected=200).json()
        pending_on_product = [
            trade for trade in mine
            if trade.get("product_id") == p_claimed["id"] and trade.get("status") == "pending_acceptance"
        ]
        rec.must_eq(len(pending_on_product), 1, "同一商品同一买方仅一条待接受请求")
        ctx.remember_item("todo", "p09_todo_request", item.get("key"), item.get("title", ""), "open", {"trade_id": t_v})

    with rec.step(
        "P09-US11-AC-02-read",
        us="US-11",
        sc="SC-11-02",
        desc="访问通知列表不标读；打开具体通知仅该通知已读且不消除未办结待办",
        expected="列表前后未读数不变；单条标记后未读数 -1、待办仍存在；聊天未读不被通知已读替代",
    ):
        _need(t_v)
        before = api.get("/notifications/unread-count", token=main_token, expected=200).json()["unread"]
        api.get("/notifications", token=main_token, params={"page_size": 50}, expected=200)
        after_list = api.get("/notifications/unread-count", token=main_token, expected=200).json()["unread"]
        rec.must_eq(after_list, before, "仅访问通知列表后的未读数（列表不标读）")
        chat_before = api.get("/conversations/unread-summary", token=main_token, expected=200).json()["unread"]
        items = _notifications(api, main_token)["items"]
        target = _find_notification(items, type_="request_created", trade_id=t_v)[0]
        rec.must_eq(target.get("is_read"), False, "request_created 通知初始未读")
        api.post(f"/notifications/{target['id']}/read", token=main_token, expected=200)
        after_read = api.get("/notifications/unread-count", token=main_token, expected=200).json()["unread"]
        rec.must_eq(after_read, before - 1, "打开一条通知后未读数应减 1")
        chat_after = api.get("/conversations/unread-summary", token=main_token, expected=200).json()["unread"]
        rec.must_eq(chat_after, chat_before, "通知已读不应改变聊天未读数")
        refreshed = _notifications(api, main_token)["items"]
        marked = next(item for item in refreshed if item["id"] == target["id"])
        rec.must_eq(marked.get("is_read"), True, "目标通知标记已读")
        rec.must(_find_todo(_todos(api, main_token), "request_pending", t_v) is not None, "通知已读后待办仍应存在")

    with rec.step(
        "P09-US11-AC-02-finish",
        us="US-11",
        sc="SC-11-04",
        desc="完成对应业务后待办自动移出；旧入口再次接受被拒绝且无副作用",
        expected="接受请求 → 待办 request_pending 移出；交易 in_progress、商品 in_transaction；再次接受 409",
    ):
        _need(t_v, p_claimed)
        prev = _stats(api, ctx)
        _accept(api, main_token, t_v)
        ctx.update_trade("p09_t_v", "in_progress")
        ctx.update_product("p09_main_claimed", state="in_transaction")
        _delta(
            api, ctx, rec, prev,
            {"trades.pending_acceptance": -1, "trades.in_progress": 1, "products.listed": -1, "products.in_transaction": 1},
            "接受请求锁单",
        )
        rec.must(_find_todo(_todos(api, main_token), "request_pending", t_v) is None, "办结后 request_pending 待办应移出")
        rec.must_eq(_trade(api, main_token, t_v).get("status"), "in_progress", "被接受请求的状态")
        resp = api.post(f"/trades/{t_v}/accept", token=main_token, expected=409)
        rec.must("不可接受" in str(resp.json().get("detail")), "旧入口二次接受应提示不可接受")
        rec.must_eq(_trade(api, main_token, t_v).get("status"), "in_progress", "二次接受无副作用")

    # 约定待确认 / 完成确认待办改在“买方身份”交易上验证（见下方 US-12 越权检查之后），
    # 卖方身份交易 p09_t_v 保持 in_progress（首次约定待确认）作为本人业务状态样本。

    # ===================================================================
    # US-10 交易计数：终止（计失败）、争议；US-11 取消申请待办
    # ===================================================================
    with rec.step(
        "P09-US10-AC-06-terminated",
        us="US-10",
        sc="SC-08-05",
        desc="已终止计失败交易：终止计数 +1，且拒绝/撤回/锁单关闭计数不被并入失败口径",
        expected="in_progress -1、terminated +1、商品 in_transaction -1/delisted +1；rejected/withdrawn/closed 不变",
    ):
        _need(p_peer_term)
        prev = _stats(api, ctx)
        t_q = _request(api, main_token, p_peer_term["id"])["id"]
        ctx.remember_trade("p09_t_q", {"id": t_q}, buyer=main_key, seller=peer_key, state="pending_acceptance")
        prev = _delta(api, ctx, rec, prev, {"trades.pending_acceptance": 1}, "买方发起请求")
        _accept(api, peer_token, t_q)
        ctx.update_trade("p09_t_q", "in_progress")
        ctx.update_product("p09_peer_term", state="in_transaction")
        prev = _delta(
            api, ctx, rec, prev,
            {"trades.pending_acceptance": -1, "trades.in_progress": 1, "products.listed": -1, "products.in_transaction": 1},
            "卖方接受请求",
        )
        cancel = _propose_cancel(api, peer_token, t_q)
        rec.must("等待对方同意" in str(cancel.get("detail")), "首次约定前卖方取消应等待买方同意")
        cancel_todo = _find_todo(_todos(api, main_token), "cancel_pending", t_q)
        rec.must(cancel_todo is not None, f"取消申请待办缺失：交易#{t_q}")
        rec.must_eq(cancel_todo.get("action"), "confirm_cancel", "取消申请待办 action")
        api.post(f"/trades/{t_q}/cancel", token=main_token, json_body={}, expected=200)
        ctx.update_trade("p09_t_q", "terminated")
        ctx.update_product("p09_peer_term", state="delisted")
        _delta(
            api, ctx, rec, prev,
            {
                "trades.in_progress": -1,
                "trades.terminated": 1,
                "trades.rejected": 0,
                "trades.withdrawn": 0,
                "trades.closed": 0,
                "products.in_transaction": -1,
                "products.delisted": 1,
            },
            "双方同意取消（终止计失败）",
        )
        rec.must(_find_todo(_todos(api, main_token), "cancel_pending", t_q) is None, "取消办结后 cancel_pending 待办应移出")
        rec.must_eq(_trade(api, main_token, t_q).get("status"), "terminated", "取消生效后交易状态")

    with rec.step(
        "P09-US12-AC-02-readonly-ended",
        us="US-12",
        sc="SC-12-01",
        desc="结束交易只读：终止交易仍可被本人读取，历史与原因保留",
        expected="200；status=terminated；transitions 保留",
    ):
        _need(t_q)
        rec.must_eq(_trade(api, main_token, t_q).get("status"), "terminated", "终止交易读取状态")
        transitions = api.get(f"/trades/{t_q}/transitions", token=main_token, expected=200).json()
        rec.must(len(transitions) >= 3, f"终止交易状态转移历史应保留，实际 {len(transitions)} 条")
        rec.must("terminated" in [row.get("to_status") for row in transitions], "状态转移历史包含 terminated")

    with rec.step(
        "P09-US10-AC-02-disputed",
        us="US-10",
        sc="SC-08-01",
        desc="有争议交易数 +1：进行中交易进入争议后保持锁单",
        expected="in_progress -1；disputed +1；商品仍 in_transaction",
    ):
        _need(p_peer_dispute)
        prev = _stats(api, ctx)
        t_s = _request(api, main_token, p_peer_dispute["id"])["id"]
        ctx.remember_trade("p09_t_s", {"id": t_s}, buyer=main_key, seller=peer_key, state="pending_acceptance")
        prev = _delta(api, ctx, rec, prev, {"trades.pending_acceptance": 1}, "买方发起请求")
        _accept(api, peer_token, t_s)
        ctx.update_trade("p09_t_s", "in_progress")
        ctx.update_product("p09_peer_dispute", state="in_transaction")
        prev = _delta(
            api, ctx, rec, prev,
            {"trades.pending_acceptance": -1, "trades.in_progress": 1, "products.listed": -1, "products.in_transaction": 1},
            "卖方接受请求",
        )
        dispute = _dispute(api, main_token, t_s)
        rec.must(dispute.get("case_id"), "发起争议应创建争议事项")
        ctx.remember_case(
            "p09_dispute_case",
            {"id": dispute["case_id"], "case_type": "trade_dispute", "title": f"交易争议：交易#{t_s}", "status": "pending"},
        )
        ctx.update_trade("p09_t_s", "disputed")
        _delta(
            api, ctx, rec, prev,
            {"trades.in_progress": -1, "trades.disputed": 1, "products.in_transaction": 0},
            "发起争议",
        )

    # ===================================================================
    # US-10 完成交易与时间范围口径
    # ===================================================================
    with rec.step(
        "P09-US10-AC-04-completed-range",
        us="US-10",
        sc="SC-08-02",
        desc="完成交易按结果确认时间计入范围：完成数/范围内完成数同步 +1；单方确认不改变交易状态计数",
        expected="in_progress -1、completed +1；全部范围 completed_trades +1；今日范围 >=1",
    ):
        _need(p_peer_done)
        today = datetime.now(UTC).date().isoformat()
        open_params = {"from": "1970-01-01", "to": today}
        prev = _stats(api, ctx)
        open_before = _stats(api, ctx, params=open_params)
        t_r = _request(api, main_token, p_peer_done["id"])["id"]
        ctx.remember_trade("p09_t_r", {"id": t_r}, buyer=main_key, seller=peer_key, state="pending_acceptance")
        prev = _delta(api, ctx, rec, prev, {"trades.pending_acceptance": 1}, "买方发起请求")
        _accept(api, peer_token, t_r)
        ctx.update_trade("p09_t_r", "in_progress")
        ctx.update_product("p09_peer_done", state="in_transaction")
        prev = _delta(
            api, ctx, rec, prev,
            {"trades.pending_acceptance": -1, "trades.in_progress": 1, "products.listed": -1, "products.in_transaction": 1},
            "卖方接受请求",
        )
        agreement = _propose_agreement(api, main_token, t_r)
        _confirm_agreement(api, peer_token, t_r, agreement["id"])
        _confirm_completion(api, main_token, t_r)
        prev = _delta(api, ctx, rec, prev, {"trades.in_progress": 0, "trades.completed": 0}, "单方提交完成确认（不改变状态计数）")
        result = _confirm_completion(api, peer_token, t_r)
        rec.must("交易已完成" in str(result.get("detail")), "双方确认后交易应完成")
        ctx.update_trade("p09_t_r", "completed")
        ctx.update_product("p09_peer_done", state="delisted")
        _delta(
            api, ctx, rec, prev,
            {"trades.in_progress": -1, "trades.completed": 1, "products.in_transaction": -1, "products.delisted": 1},
            "双方完成确认",
        )
        open_after = _stats(api, ctx, params=open_params)
        rec.must_eq(
            open_after["range"]["completed_trades"] - open_before["range"]["completed_trades"],
            1,
            "全部范围（1970-01-01 至今）完成交易数应随本次完成 +1",
        )
        rec.must_eq(open_after["range"]["from"], "1970-01-01", "范围参数 from 原样返回")
        rec.must_eq(open_after["range"]["to"], today, "范围参数 to 原样返回")
        today_stats = _stats(api, ctx, params={"from": today, "to": today})
        rec.must(
            isinstance(today_stats["range"]["completed_trades"], int) and today_stats["range"]["completed_trades"] >= 1,
            f"今日范围应至少包含本次完成交易，实际 {today_stats['range']['completed_trades']!r}",
        )
        detail = _trade(api, main_token, t_r)
        rec.must_eq(detail.get("status"), "completed", "完成交易状态")
        rec.must(detail.get("finished_at") is not None, "完成交易应有结果确认时间 finished_at")

    with rec.step(
        "P09-US10-AC-04-empty-range",
        us="US-10",
        sc="SC-08-04",
        desc="所选范围无数据返回零计数且不报错，不推断缺失原因",
        expected="completed_trades == 0；HTTP 200；无错误文案推断",
    ):
        empty = _stats(api, ctx, params={"from": "2000-01-01", "to": "2000-01-02"})
        rec.must_eq(empty["range"]["completed_trades"], 0, "空范围完成交易数")
        rec.must_eq(empty["range"]["from"], "2000-01-01", "空范围 from")
        rec.must_eq(empty["range"]["to"], "2000-01-02", "空范围 to")
        rec.must("message" not in empty and "detail" not in empty, "空范围不应返回错误文案推断缺失原因")

    # ===================================================================
    # US-10 拒绝/撤回/锁单关闭不计失败
    # ===================================================================
    with rec.step(
        "P09-US10-AC-06-not-failed",
        us="US-10",
        sc="SC-08-05",
        desc="拒绝、撤回、锁单关闭分别计数且不计入已终止失败数",
        expected="rejected/withdrawn/closed 各 +1，terminated 不变",
    ):
        _need(p_peer_mixed, p_peer_closed)
        prev = _stats(api, ctx)
        t_p_rejected = _request(api, main_token, p_peer_mixed["id"])["id"]
        ctx.remember_trade(
            "p09_t_p_rejected", {"id": t_p_rejected}, buyer=main_key, seller=peer_key, state="pending_acceptance"
        )
        prev = _delta(api, ctx, rec, prev, {"trades.pending_acceptance": 1}, "买方发起请求")
        _reject(api, peer_token, t_p_rejected)
        ctx.update_trade("p09_t_p_rejected", "rejected")
        prev = _delta(
            api, ctx, rec, prev,
            {"trades.pending_acceptance": -1, "trades.rejected": 1, "trades.terminated": 0},
            "卖方拒绝请求",
        )
        t_p_withdrawn = _request(api, main_token, p_peer_mixed["id"])["id"]
        ctx.remember_trade(
            "p09_t_p_withdrawn", {"id": t_p_withdrawn}, buyer=main_key, seller=peer_key, state="pending_acceptance"
        )
        prev = _delta(api, ctx, rec, prev, {"trades.pending_acceptance": 1}, "买方再次发起请求")
        _withdraw(api, main_token, t_p_withdrawn)
        ctx.update_trade("p09_t_p_withdrawn", "withdrawn")
        prev = _delta(
            api, ctx, rec, prev,
            {"trades.pending_acceptance": -1, "trades.withdrawn": 1, "trades.terminated": 0},
            "买方撤回请求",
        )
        t_t_main = _request(api, main_token, p_peer_closed["id"])["id"]
        ctx.remember_trade("p09_t_t_main", {"id": t_t_main}, buyer=main_key, seller=peer_key, state="pending_acceptance")
        prev = _delta(api, ctx, rec, prev, {"trades.pending_acceptance": 1}, "第一买方发起请求")
        t_t_third = _request(api, third_token, p_peer_closed["id"])["id"]
        ctx.remember_trade("p09_t_t_third", {"id": t_t_third}, buyer=third_key, seller=peer_key, state="pending_acceptance")
        prev = _delta(api, ctx, rec, prev, {"trades.pending_acceptance": 1}, "第二买方发起请求")
        _accept(api, peer_token, t_t_third)
        ctx.update_trade("p09_t_t_third", "in_progress")
        ctx.update_trade("p09_t_t_main", "closed")
        ctx.update_product("p09_peer_closed", state="in_transaction")
        _delta(
            api, ctx, rec, prev,
            {
                "trades.pending_acceptance": -2,
                "trades.in_progress": 1,
                "trades.closed": 1,
                "trades.terminated": 0,
                "trades.rejected": 0,
                "trades.withdrawn": 0,
                "products.listed": -1,
                "products.in_transaction": 1,
            },
            "锁单关闭其余请求",
        )

    # ===================================================================
    # US-11 旧通知入口重校验
    # ===================================================================
    with rec.step(
        "P09-US11-AC-04-old-entry",
        us="US-11",
        sc="SC-11-03",
        desc="从旧通知进入已拒绝/已关闭/已完成事项：显示当前状态并拒绝失效操作",
        expected="旧通知与交易当前状态一致；撤回已拒绝/已关闭请求、确认已完成交易均被拒绝且无副作用",
    ):
        _need(t_p_rejected, t_t_main, t_r)
        notifications = _notifications(api, main_token)["items"]
        rejected_notice = _find_notification(notifications, type_="request_rejected", link_id=t_p_rejected)
        rec.must_eq(len(rejected_notice), 1, "买方应有 1 条 request_rejected 通知")
        closed_notice = _find_notification(notifications, type_="request_closed", link_id=t_t_main)
        rec.must_eq(len(closed_notice), 1, "被锁单关闭的买方应有 1 条 request_closed 通知")
        rec.must_eq(_trade(api, main_token, t_p_rejected).get("status"), "rejected", "旧拒绝通知所指交易当前状态")
        resp = api.post(f"/trades/{t_p_rejected}/withdraw", token=main_token, expected=409)
        rec.must("已处理" in str(resp.json().get("detail")), "撤回已拒绝请求应提示卖方已处理")
        rec.must_eq(_trade(api, main_token, t_p_rejected).get("status"), "rejected", "撤回失效操作无副作用")
        rec.must_eq(_trade(api, main_token, t_t_main).get("status"), "closed", "旧关闭通知所指交易当前状态")
        resp = api.post(f"/trades/{t_t_main}/withdraw", token=main_token, expected=409)
        rec.must("已处理" in str(resp.json().get("detail")), "撤回已关闭请求应被拒绝")
        resp = api.post(f"/trades/{t_r}/confirmations", token=main_token, json_body={}, expected=409)
        rec.must("仅进行中交易" in str(resp.json().get("detail")), "已完成交易再次提交确认应被拒绝")

    # ===================================================================
    # US-11 / US-10 保留待接受请求样本（须在“我的商品待接受请求计数”之前造数）
    # ===================================================================
    with rec.step(
        "P09-US10-AC-02-pending-left",
        us="US-10",
        sc="SC-08-01",
        desc="保留一条待接受请求样本：待接受交易数 +1，卖方待办保持",
        expected="pending_acceptance +1；待办 request_pending 存在",
    ):
        _need(p_pending_req)
        prev = _stats(api, ctx)
        t_u = _request(api, third_token, p_pending_req["id"])["id"]
        ctx.remember_trade("p09_t_u", {"id": t_u}, buyer=third_key, seller=main_key, state="pending_acceptance")
        _delta(api, ctx, rec, prev, {"trades.pending_acceptance": 1, "products.listed": 0}, "第三方发起请求")
        rec.must(_find_todo(_todos(api, main_token), "request_pending", t_u) is not None, "保留的待接受请求应有待办")

    # ===================================================================
    # US-12 我的商品：全状态、审核原因、关联请求
    # ===================================================================
    with rec.step(
        "P09-US12-AC-01-products",
        us="US-12",
        sc="SC-12-01",
        desc="我的商品覆盖全部生命周期状态，含审核原因与待接受请求数，且仅含本人商品",
        expected="pending_review/rejected/listed/in_transaction/delisted 均出现；拒绝原因可见；待接受请求计数正确",
    ):
        _need(p_pending, p_rejected, p_listed, p_delisted, p_claimed, p_pending_req)
        mine = api.get("/products/mine", token=main_token, expected=200).json()
        by_id = {product["id"]: product for product in mine}
        rec.must(all(product.get("seller_id") == main_id for product in mine), "我的商品应全部归属本人")
        expected_states = {
            p_pending["id"]: "pending_review",
            p_rejected["id"]: "rejected",
            p_listed["id"]: "listed",
            p_delisted["id"]: "delisted",
            p_claimed["id"]: "in_transaction",
            p_pending_req["id"]: "listed",
        }
        for product_id, status in expected_states.items():
            rec.must(product_id in by_id, f"我的商品缺少商品 #{product_id}")
            rec.must_eq(by_id[product_id].get("status"), status, f"商品 #{product_id} 状态")
        statuses = {product.get("status") for product in mine}
        for status in PRODUCT_STATUSES:
            rec.must(status in statuses, f"我的商品状态集合缺少 {status}（实际 {sorted(statuses)}）")
        rejected = by_id[p_rejected["id"]]
        rec.must(rejected.get("reject_reason"), "审核未通过商品应展示拒绝原因")
        rec.must("退回补充" in str(rejected.get("reject_reason")), "拒绝原因应保留退回补充说明")
        rec.must_eq(rejected.get("can_resubmit"), True, "审核未通过商品应可修改重提")
        rec.must_eq(by_id[p_pending["id"]].get("can_withdraw_review"), True, "未认领待审核商品应可撤回审核")
        rec.must_eq(by_id[p_pending_req["id"]].get("pending_request_count"), 1, "待接受请求计数")

    with rec.step(
        "P09-US12-AC-01-review-records",
        us="US-12",
        sc="SC-12-01",
        desc="本人商品可查看审核记录（结论、原因、时间），审核原因与我的商品一致",
        expected="review-records 200；含 rejected 记录及退回补充原因",
    ):
        _need(p_rejected)
        records = api.get(f"/products/{p_rejected['id']}/review-records", token=main_token, expected=200).json()
        rejected_records = [row for row in records if row.get("result") == "rejected"]
        rec.must(rejected_records, f"审核记录应包含 rejected 结论，实际 {records}")
        rec.must(
            any("退回补充" in str(row.get("reason")) for row in rejected_records),
            "审核记录应保留退回补充原因",
        )
        rec.must(all(row.get("reviewed_at") for row in rejected_records), "审核记录应含审核时间")

    # ===================================================================
    # US-12 我的交易：买卖双身份全状态
    # ===================================================================
    with rec.step(
        "P09-US12-AC-02-trades",
        us="US-12",
        sc="SC-12-01",
        desc="我的交易覆盖买卖两种身份的全部请求与交易状态，结束记录只读保留",
        expected="已知交易全部出现且状态正确；my_role 双身份；role 过滤结果自洽",
    ):
        _need(t_v, t_u, t_q, t_r, t_s, t_t_main, t_p_rejected, t_p_withdrawn)
        mine = api.get("/trades/mine", token=main_token, expected=200).json()
        by_id = {trade["id"]: trade for trade in mine}
        expected = {
            t_v: ("in_progress", "seller"),
            t_u: ("pending_acceptance", "seller"),
            t_q: ("terminated", "buyer"),
            t_r: ("completed", "buyer"),
            t_s: ("disputed", "buyer"),
            t_t_main: ("closed", "buyer"),
            t_p_rejected: ("rejected", "buyer"),
            t_p_withdrawn: ("withdrawn", "buyer"),
        }
        for trade_id, (status, role) in expected.items():
            rec.must(trade_id in by_id, f"我的交易缺少交易 #{trade_id}")
            rec.must_eq(by_id[trade_id].get("status"), status, f"交易 #{trade_id} 状态")
            rec.must_eq(by_id[trade_id].get("my_role"), role, f"交易 #{trade_id} 本人角色")
        seen_statuses = {trade.get("status") for trade in mine}
        for status in ("pending_acceptance", "in_progress", "completed", "terminated", "disputed", "closed", "rejected", "withdrawn"):
            rec.must(status in seen_statuses, f"我的交易状态集合缺少 {status}（实际 {sorted(seen_statuses)}）")
        buyer_only = api.get("/trades/mine", token=main_token, params={"role": "buyer"}, expected=200).json()
        seller_only = api.get("/trades/mine", token=main_token, params={"role": "seller"}, expected=200).json()
        rec.must(all(trade.get("my_role") == "buyer" for trade in buyer_only), "role=buyer 过滤结果应全为买方角色")
        rec.must(all(trade.get("my_role") == "seller" for trade in seller_only), "role=seller 过滤结果应全为卖方角色")
        rec.must_eq(len(buyer_only) + len(seller_only), len(mine), "买卖身份过滤结果数应等于全部交易数")
        rec.must_eq(
            {trade["id"] for trade in buyer_only} | {trade["id"] for trade in seller_only},
            {trade["id"] for trade in mine},
            "买卖身份过滤并集应等于全部交易",
        )
        completed = by_id[t_r]
        rec.must(completed.get("finished_at") is not None, "完成交易保留结果确认时间")
        rec.must_eq(completed.get("my_reviewed"), False, "评价前 my_reviewed 为 False（随后补评价）")

    # ===================================================================
    # US-12 收藏：本人清单、失效提示、越权不可见
    # ===================================================================
    with rec.step(
        "P09-US12-AC-03-favorites",
        us="US-12",
        sc="SC-12-01",
        desc="收藏按本人归属：有效项显示商品信息，失效项仅通用提示不泄露内容；他人清单不含本人收藏",
        expected="有效 1 条（title 非空）、失效 1 条（valid=false、title/status 为 null）；third 清单不含这两个收藏",
    ):
        _need(p_peer_mixed, p_third_fav)
        first = api.post(f"/favorites/{p_peer_mixed['id']}", token=main_token, expected=200).json()
        second = api.post(f"/favorites/{p_peer_mixed['id']}", token=main_token, expected=200).json()
        rec.must_eq(second.get("favorite_id"), first.get("favorite_id"), "重复收藏应幂等返回既有收藏 id")
        api.post(f"/favorites/{p_third_fav['id']}", token=main_token, expected=200)
        prev = _stats(api, ctx)
        api.post(f"/products/{p_third_fav['id']}/delist", token=third_token, expected=200)
        ctx.update_product("p09_third_fav", state="delisted")
        _delta(api, ctx, rec, prev, {"products.listed": -1, "products.delisted": 1}, "第三方下架被收藏商品")
        favorites = api.get("/favorites", token=main_token, expected=200).json()
        peer_favorites = [row for row in favorites if row.get("product_id") == p_peer_mixed["id"]]
        invalid_favorites = [row for row in favorites if row.get("product_id") == p_third_fav["id"]]
        rec.must_eq(len(peer_favorites), 1, "有效收藏应恰一条")
        rec.must_eq(peer_favorites[0].get("valid"), True, "在售商品收藏有效")
        rec.must(peer_favorites[0].get("title"), "有效收藏应显示标题")
        rec.must_eq(len(invalid_favorites), 1, "失效收藏应恰一条")
        rec.must_eq(invalid_favorites[0].get("valid"), False, "已下架商品收藏失效")
        rec.must_eq(invalid_favorites[0].get("title"), None, "失效收藏不泄露标题")
        rec.must_eq(invalid_favorites[0].get("status"), None, "失效收藏不泄露商品状态")
        third_favorites = api.get("/favorites", token=third_token, expected=200).json()
        third_product_ids = {row.get("product_id") for row in third_favorites}
        rec.must(p_peer_mixed["id"] not in third_product_ids, "他人收藏清单不含本人收藏商品")
        rec.must(p_third_fav["id"] not in third_product_ids, "他人收藏清单不含本人收藏（失效项）")
        resp = api.delete(f"/favorites/{p_peer_mixed['id']}", token=third_token, expected=404)
        rec.must("未收藏" in str(resp.json().get("detail")), "他人取消收藏应提示未收藏")
        still = api.get("/favorites", token=main_token, expected=200).json()
        rec.must(
            any(row.get("product_id") == p_peer_mixed["id"] and row.get("valid") is True for row in still),
            "他人取消收藏不得影响本人收藏",
        )

    # ===================================================================
    # US-12 双向评价
    # ===================================================================
    with rec.step(
        "P09-US12-AC-03-reviews",
        us="US-12",
        sc="SC-12-01",
        desc="我的评价按我发表/我收到分别查询，关联原交易；商品下架不影响本人读取，他人清单不含本人评价",
        expected="published 含本人评价（rating=5、trade_status=completed）；received 含对方评价（rating=4）；third 清单不含",
    ):
        _need(t_r)
        review_main = api.post(
            f"/trades/{t_r}/review",
            token=main_token,
            json_body={"rating": 5, "content": "p09 本人发表评价：交易顺利"},
            expected=201,
        ).json()
        review_peer = api.post(
            f"/trades/{t_r}/review",
            token=peer_token,
            json_body={"rating": 4, "content": "p09 对方评价：交付准时"},
            expected=201,
        ).json()
        ctx.remember_item("review", "p09_review_published", review_main["id"], "p09 本人发表评价", "published", {"trade_id": t_r})
        ctx.remember_item("review", "p09_review_received", review_peer["id"], "p09 本人收到评价", "received", {"trade_id": t_r})
        published = api.get("/me/reviews", token=main_token, params={"type": "published"}, expected=200).json()
        received = api.get("/me/reviews", token=main_token, params={"type": "received"}, expected=200).json()
        pub = [row for row in published if row.get("id") == review_main["id"]]
        rcv = [row for row in received if row.get("id") == review_peer["id"]]
        rec.must_eq(len(pub), 1, "我发表评价应出现在 published 清单")
        rec.must_eq(pub[0].get("trade_id"), t_r, "发表评价关联原交易")
        rec.must_eq(pub[0].get("rating"), 5, "发表评价评分")
        rec.must_eq(pub[0].get("trade_status"), "completed", "发表评价对应交易状态")
        rec.must_eq(pub[0].get("direction"), "published", "发表评价方向")
        rec.must_eq(len(rcv), 1, "我收到评价应出现在 received 清单")
        rec.must_eq(rcv[0].get("trade_id"), t_r, "收到评价关联原交易")
        rec.must_eq(rcv[0].get("rating"), 4, "收到评价评分")
        rec.must_eq(
            rcv[0].get("other_party_name"),
            peer.get("display_name") or (peer.get("user") or {}).get("display_name"),
            "收到评价的对方名称",
        )
        rec.must_eq(rcv[0].get("deleted"), False, "收到评价未被删除")
        third_published = api.get("/me/reviews", token=third_token, params={"type": "published"}, expected=200).json()
        rec.must(
            all(row.get("id") != review_main["id"] for row in third_published),
            "他人 published 清单不应包含本人评价",
        )
        product_after = api.get(f"/products/{p_peer_done['id']}", token=main_token, expected=200).json()
        rec.must_eq(product_after.get("status"), "delisted", "完成后商品默认下架")
        rec.must(
            any(row.get("id") == review_peer["id"] for row in received),
            "商品下架后本人仍可读取收到的评价",
        )

    # ===================================================================
    # US-10 / US-12 举报：我的举报、我收到的举报（仅已处置）
    # ===================================================================
    with rec.step(
        "P09-US10-AC-02-report-pending",
        us="US-10",
        sc="SC-08-01",
        desc="新增举报进入共享池：待处理举报事项数 +1",
        expected="pending.report_cases +1；pending.all_cases +1",
    ):
        _need(p_listed)
        prev = _stats(api, ctx)
        report_of_main = api.post(
            "/reports",
            token=peer_token,
            json_body={
                "target_type": "product",
                "target_id": p_listed["id"],
                "reason": "p09 举报：商品描述与实物不符",
                "detail": "p09 真实举报测试，用于验证我收到的举报仅已处置可见。",
                "evidence_keys": [evidence_image["key"]],
            },
            expected=201,
        ).json()
        ctx.remember_report("p09_report_received", report_of_main)
        _delta(api, ctx, rec, prev, {"pending.report_cases": 1, "pending.all_cases": 1}, "提交举报")
        prev = _stats(api, ctx)
        own_report = api.post(
            "/reports",
            token=main_token,
            json_body={
                "target_type": "product",
                "target_id": p_peer_mixed["id"],
                "reason": "p09 我的举报：描述含推广内容",
            },
            expected=201,
        ).json()
        ctx.remember_report("p09_report_mine", own_report)
        _delta(api, ctx, rec, prev, {"pending.report_cases": 1, "pending.all_cases": 1}, "提交本人举报")
        rec.must(own_report.get("id") and report_of_main.get("id"), "举报创建应返回 id")

    with rec.step(
        "P09-US12-AC-04-received-before",
        us="US-12",
        sc="SC-12-02",
        desc="未处置的收到举报不在“我收到的举报”中额外披露",
        expected="received 清单不含该举报",
    ):
        _need(report_of_main)
        received = api.get("/reports/received", token=main_token, expected=200).json()
        rec.must(
            all(row.get("id") != report_of_main["id"] for row in received),
            "未处置举报不应出现在我收到的举报清单",
        )

    with rec.step(
        "P09-US12-AC-04-mine",
        us="US-12",
        sc="SC-12-02",
        desc="我的举报独立可查，含目标、原因、处理进度与补充说明列表",
        expected="reports/mine 含本人举报；status 为 pending/processing；supplements 为列表",
    ):
        _need(p_peer_mixed)
        mine_reports = api.get("/reports/mine", token=main_token, expected=200).json()
        matched = [
            row for row in mine_reports
            if row.get("target_id") == p_peer_mixed["id"] and row.get("target_type") == "product"
        ]
        rec.must(matched, "我的举报清单应包含本人对目标商品的举报")
        rec.must_in(matched[0].get("status"), ("pending", "processing"), "我的举报处理进度")
        rec.must(isinstance(matched[0].get("supplements"), list), "我的举报应含补充说明列表")
        rec.must_eq(matched[0].get("reason"), "p09 我的举报：描述含推广内容", "我的举报原因原文")

    # ---- 管理员认领举报事项 → 问询 → 回复 → 核查结论 ----
    with rec.step(
        "P09-US12-AC-04-claimed",
        us="US-12",
        sc="SC-12-02",
        desc="管理员认领举报事项并发起问询/回复；处置前不可申辩",
        expected="认领/问询/回复均 200；处置前 appeal 409",
    ):
        _need(report_of_main)
        admin_token = ctx.token("admin")
        reports = api.get("/admin/reports", token=admin_token, params={"status": "pending"}, expected=200).json()
        matched = [row for row in reports if row.get("id") == report_of_main["id"]]
        rec.must_eq(len(matched), 1, "共享池应包含新举报")
        report_case_id = matched[0].get("case_id")
        rec.must(report_case_id, "举报应关联处置事项")
        ctx.remember_case(
            "p09_report_case",
            {"id": report_case_id, "case_type": "report", "title": f"举报事项：商品#{p_listed['id']}", "status": "processing"},
        )
        admin_claim_case(api, ctx, report_case_id)
        api.post(
            f"/admin/cases/{report_case_id}/inquiry",
            token=admin_token,
            json_body={"content": "请说明该商品描述与实际交付是否一致，并提交说明。"},
            expected=200,
        )
        api.post(
            f"/admin/cases/{report_case_id}/messages",
            token=admin_token,
            json_body={"content": "已收到说明，正在核查，请稍候。"},
            expected=200,
        )
        resp = api.post(
            f"/me/cases/{report_case_id}/appeal",
            token=main_token,
            json_body={"content": "p09 处置前误用申辩入口"},
            expected=409,
        )
        rec.must("尚未形成实际处置" in str(resp.json().get("detail")), "处置前申辩应提示尚未形成实际处置")

    with rec.step(
        "P09-US11-AC-05-inquiry",
        us="US-11",
        sc="SC-11-01",
        desc="管理员问询产生问询待办；本人提交说明后待办移出并留下说明记录",
        expected="todos 含 inquiry_pending（action=submit_statement）；说明提交后移出；事项消息含问询与说明",
    ):
        _need(report_case_id)
        item = _find_todo(_todos(api, main_token), "inquiry_pending", report_case_id)
        rec.must(item is not None, f"问询待办缺失：事项#{report_case_id}")
        rec.must_eq(item.get("action"), "submit_statement", "问询待办 action")
        rec.must_eq(item.get("link_type"), "case", "问询待办 link_type")
        detail = api.get(f"/me/cases/{report_case_id}", token=main_token, expected=200).json()
        rec.must_eq(detail.get("has_inquiry"), True, "事项详情 has_inquiry")
        rec.must_eq(detail.get("status"), "processing", "问询阶段事项状态")
        inquiry_messages = [m for m in detail.get("messages") or [] if m.get("kind") == "inquiry"]
        rec.must(inquiry_messages, "事项消息应含管理员问询")
        rec.must_eq(inquiry_messages[0].get("sender_id"), None, "用户视角不披露管理员 sender_id")
        result = api.post(
            f"/me/cases/{report_case_id}/statement",
            token=main_token,
            json_body={"content": "p09 本人说明：商品描述与实际一致，附交付说明。"},
            expected=200,
        ).json()
        rec.must("说明已提交" in str(result.get("detail")), "说明提交回执")
        rec.must(_find_todo(_todos(api, main_token), "inquiry_pending", report_case_id) is None, "说明提交后问询待办应移出")
        after = api.get(f"/me/cases/{report_case_id}", token=main_token, expected=200).json()
        statements = [m for m in after.get("messages") or [] if m.get("kind") == "statement"]
        rec.must_eq(len(statements), 1, "应记录 1 条本人说明")
        rec.must_eq(statements[0].get("mine"), True, "本人说明 mine=True")
        rec.must_eq(statements[0].get("sender_id"), main_id, "本人说明 sender_id 为本人")
        replies = [m for m in after.get("messages") or [] if m.get("kind") == "reply"]
        rec.must(replies, "事项应含管理员回复")
        rec.must_eq(replies[0].get("sender_id"), None, "管理员回复不披露 sender_id")

    with rec.step(
        "P09-US10-AC-02-report-disposed",
        us="US-10",
        sc="SC-08-01",
        desc="管理员形成举报核查结论：待处理举报事项数回落",
        expected="decision 200；pending.report_cases -1；pending.all_cases -1",
    ):
        _need(report_case_id)
        admin_token = ctx.token("admin")
        prev = _stats(api, ctx)
        api.post(
            f"/admin/reports/cases/{report_case_id}/decision",
            token=admin_token,
            json_body={
                "outcome": "handled",
                "reason": "p09 核查：认定描述不实，已记录处置",
                "public_summary": "经核查，该举报认定成立，已按平台规则记录处置。",
                "actions": {},
            },
            expected=200,
        )
        _delta(api, ctx, rec, prev, {"pending.report_cases": -1, "pending.all_cases": -1}, "举报处置归档")

    with rec.step(
        "P09-US12-AC-04-received-after",
        us="US-12",
        sc="SC-12-02",
        desc="已实际处置的收到举报进入列表，隐去举报人身份并带处置原因与公开结论",
        expected="received 含该举报；case_id/disposal_reason/public_result 有值；无举报人字段",
    ):
        _need(report_of_main, report_case_id)
        received = api.get("/reports/received", token=main_token, expected=200).json()
        matched = [row for row in received if row.get("id") == report_of_main["id"]]
        rec.must_eq(len(matched), 1, "已处置举报应出现在我收到的举报")
        row = matched[0]
        rec.must_eq(row.get("status"), "handled", "收到举报的处理状态")
        rec.must_eq(row.get("result_confirmed"), True, "处置结论已确认")
        rec.must_eq(row.get("case_id"), report_case_id, "收到举报关联处置事项")
        rec.must(row.get("public_result"), "公开结论应非空")
        rec.must(row.get("disposal_reason"), "处置原因应非空（已处置才给）")
        rec.must(
            not any("reporter" in str(key) for key in row),
            f"我收到的举报不得显示举报人身份，实际字段 {sorted(row)}",
        )

    # ===================================================================
    # US-12 我的事项：说明与申辩入口
    # ===================================================================
    with rec.step(
        "P09-US12-AC-05-appeal",
        us="US-12",
        sc="SC-12-02",
        desc="处置后说明入口关闭、申辩入口开放并留存申辩记录；举报人不能读取对方申辩",
        expected="处置后 statement 409、appeal 200、详情含本人申辩；举报人访问事项 403",
    ):
        _need(report_case_id)
        resp = api.post(
            f"/me/cases/{report_case_id}/statement",
            token=main_token,
            json_body={"content": "处置后误用说明入口"},
            expected=409,
        )
        rec.must("已处置" in str(resp.json().get("detail")), "处置后说明入口应提示已处置")
        result = api.post(
            f"/me/cases/{report_case_id}/appeal",
            token=main_token,
            json_body={"content": "p09 本人申辩：对核查结论申请复核。"},
            expected=200,
        ).json()
        rec.must("申辩已提交" in str(result.get("detail")), "申辩提交回执")
        detail = api.get(f"/me/cases/{report_case_id}", token=main_token, expected=200).json()
        appeals = [m for m in detail.get("messages") or [] if m.get("kind") == "appeal"]
        rec.must_eq(len(appeals), 1, "应记录 1 条本人申辩")
        rec.must_eq(appeals[0].get("mine"), True, "本人申辩 mine=True")
        rec.must_eq(detail.get("status"), "disposed", "申辩后事项保持已处置（不自动撤销处置）")
        # 举报人不因身份获得对方申辩内容
        resp = api.get(f"/me/cases/{report_case_id}", token=peer_token, expected=403)
        rec.must("无权访问" in str(resp.json().get("detail")), "举报人读取对方申辩应被拒绝")

    with rec.step(
        "P09-US12-AC-05-my-cases",
        us="US-12",
        sc="SC-12-02",
        desc="我的事项覆盖受处置事项与本人交易的争议事项，含结论；局外人与他人事项被拒绝",
        expected="me/cases 含举报事项和交易争议事项；已处置结论可读；局外人访问/说明被拒绝",
    ):
        _need(report_case_id, t_s)
        cases = api.get("/me/cases", token=main_token, expected=200).json()
        case_ids = {row["id"] for row in cases}
        rec.must(report_case_id in case_ids, f"我的事项缺少举报事项 #{report_case_id}")
        report_case = next(row for row in cases if row["id"] == report_case_id)
        rec.must_eq(report_case.get("status"), "disposed", "我的举报事项状态")
        rec.must_eq(report_case.get("case_type"), "report", "我的举报事项类型")
        rec.must(report_case.get("conclusion"), "已处置事项应展示结论")
        rec.must(report_case.get("conclusion_reason"), "已处置事项应展示结论原因")
        dispute_cases = [row for row in cases if row.get("case_type") == "trade_dispute"]
        rec.must(dispute_cases, "争议交易参与方应在我的事项中看到争议事项")
        resp = api.get(f"/me/cases/{report_case_id}", token=third_token, expected=403)
        rec.must("无权访问" in str(resp.json().get("detail")), "局外人访问他人事项应提示无权访问")
        resp = api.post(
            f"/me/cases/{report_case_id}/statement",
            token=third_token,
            json_body={"content": "p09 局外人越权说明"},
            expected=403,
        )
        rec.must("无权访问" in str(resp.json().get("detail")), "局外人提交说明应被拒绝")

    # ===================================================================
    # US-12 编辑历史：买方历史访问、第三方拒绝、不向已结束请求发变更通知
    # ===================================================================
    with rec.step(
        "P09-US12-AC-07-edit-history",
        us="US-12",
        sc="SC-12-04",
        desc="请求已结束后买方仍可查看该商品后续编辑历史；普通第三方无权限；已结束请求不产生商品变更通知",
        expected="本人 edit-history 200 且含后续编辑；third 403；本人通知无该商品 product_edited",
    ):
        _need(p_peer_mixed)
        api.patch(
            f"/products/{p_peer_mixed['id']}",
            token=peer_token,
            json_body={"description": "p09 请求结束后的商品描述编辑（买方历史可见）。"},
            expected=200,
        )
        histories = api.get(f"/products/{p_peer_mixed['id']}/edit-history", token=main_token, expected=200).json()
        rec.must(histories, "买方历史入口应可读取请求对应内容及之后变更")
        rec.must(
            any("p09 请求结束后的商品描述编辑" in str(row.get("after_json")) for row in histories),
            "编辑历史应包含请求结束后的变更内容",
        )
        rec.must(all(row.get("created_at") for row in histories), "编辑历史应含时间")
        detail = api.get(f"/products/{p_peer_mixed['id']}", token=main_token, expected=200).json()
        rec.must_eq(detail.get("status"), "listed", "编辑后商品仍应在售")
        resp = api.get(f"/products/{p_peer_mixed['id']}/edit-history", token=third_token, expected=403)
        rec.must("仅本人请求" in str(resp.json().get("detail")), "普通第三方读取编辑历史应被拒绝")
        notifications = _notifications(api, main_token)["items"]
        edited_notices = _find_notification(notifications, type_="product_edited", link_id=p_peer_mixed["id"])
        rec.must_eq(len(edited_notices), 0, "已结束请求（拒绝/撤回）不应收到该商品的编辑通知")

    # ===================================================================
    # US-12 他人链接越权（不泄露）
    # ===================================================================
    with rec.step(
        "P09-US12-AC-06-cross-user",
        us="US-12",
        sc="SC-12-03",
        desc="他人业务链接不泄露：非本人不可见商品返回不可见；他人交易返回 404 且不泄露内容",
        expected="third 读取本人待审/未通过商品 404；读取本人交易 404 且不泄露商品/对方信息",
    ):
        _need(p_pending, p_rejected, t_r)
        for product_id in (p_pending["id"], p_rejected["id"]):
            resp = api.get(f"/products/{product_id}", token=third_token, expected=404)
            rec.must("不可见" in str(resp.json().get("detail")), "他人不可见商品应返回不可见提示")
        resp = api.get(f"/trades/{t_r}", token=third_token, expected=404)
        body = resp.json()
        rec.must_eq(body.get("detail"), "交易不存在", "他人交易读取用同文案防枚举")
        rec.must("product_title" not in body, "他人交易错误响应不泄露商品标题")

    # ---- 买方身份：约定待确认 / 完成确认待办（US-11-AC-02/05、D-53、4.17） ----
    with rec.step(
        "P09-US11-AC-05-agreement",
        us="US-11",
        sc="SC-11-01",
        desc="买方（待确认方）收到对方约定提案后出现 agreement_pending 待办；局外人无该待办",
        expected="todos 含 agreement_pending（action=confirm_agreement, link_type=trade）；third 无该待办",
    ):
        _need(p_peer_mixed)
        prev = _stats(api, ctx)
        t_agree = _request(api, main_token, p_peer_mixed["id"])["id"]
        ctx.remember_trade("p09_t_agree", {"id": t_agree}, buyer=main_key, seller=peer_key, state="pending_acceptance")
        prev = _delta(api, ctx, rec, prev, {"trades.pending_acceptance": 1}, "买方发起请求")
        _accept(api, peer_token, t_agree)
        ctx.update_trade("p09_t_agree", "in_progress")
        ctx.update_product("p09_peer_mixed", state="in_transaction")
        _delta(
            api, ctx, rec, prev,
            {"trades.pending_acceptance": -1, "trades.in_progress": 1, "products.listed": -1, "products.in_transaction": 1},
            "卖方接受请求",
        )
        agreement = _propose_agreement(api, peer_token, t_agree)  # 卖方提出约定，买方待确认
        item = _find_todo(_todos(api, main_token), "agreement_pending", t_agree)
        rec.must(item is not None, f"买方待确认约定待办缺失：交易#{t_agree}")
        rec.must_eq(item.get("action"), "confirm_agreement", "约定待办 action")
        rec.must_eq(item.get("link_type"), "trade", "约定待办 link_type")
        rec.must(
            _find_todo(_todos(api, third_token), "agreement_pending", t_agree) is None,
            "局外人不应获得该约定待办",
        )
        ctx.remember_item(
            "agreement", "p09_agreement", agreement.get("id"), f"交易#{t_agree} 约定", "proposed", {"trade_id": t_agree}
        )

    with rec.step(
        "P09-US11-AC-05-completion",
        us="US-11",
        sc="SC-11-01",
        desc="约定确认后买方出现完成确认待办；本人提交完成确认后待办移出，单方确认只提醒对方",
        expected="agreement_pending 移出、completion_confirm 出现；提交后移出、卖方收到 confirm_progress",
    ):
        _need(t_agree)
        agreements = _trade(api, main_token, t_agree).get("agreement_history") or []
        pending_agreement = [row for row in agreements if row.get("status") == "proposed"]
        rec.must_eq(len(pending_agreement), 1, "当前待确认约定提案数")
        _confirm_agreement(api, main_token, t_agree, pending_agreement[0]["id"])
        todos = _todos(api, main_token)
        rec.must(_find_todo(todos, "agreement_pending", t_agree) is None, "约定确认后 agreement_pending 应移出")
        completion_todo = _find_todo(todos, "completion_confirm", t_agree)
        rec.must(completion_todo is not None, f"约定确认后应出现 completion_confirm 待办：交易#{t_agree}")
        rec.must_eq(completion_todo.get("action"), "confirm_completion", "完成确认待办 action")
        _confirm_completion(api, main_token, t_agree)
        rec.must(_find_todo(_todos(api, main_token), "completion_confirm", t_agree) is None, "提交完成确认后待办应移出")
        detail = _trade(api, main_token, t_agree)
        rec.must_eq(detail.get("my_role"), "buyer", "本笔交易本人角色应为买方")
        rec.must_eq(detail.get("my_confirmed"), True, "本人完成确认标记")
        rec.must_eq(detail.get("other_party_confirmed"), False, "对方完成确认标记")
        rec.must(detail.get("confirm_wait_started_at") is not None, "单方确认后应开始 7 天等待计时")
        peer_notifications = _notifications(api, peer_token)["items"]
        progress = _find_notification(peer_notifications, type_="confirm_progress", link_id=t_agree)
        rec.must_eq(len(progress), 1, "卖方应收到 1 条 confirm_progress 通知")
        ctx.note("p09：交易 t_agree（本人买方）保留单方完成确认与 7 天等待（真实计时未加速），最终状态仍为 in_progress")

    # ===================================================================
    # US-11 管理员：无个人待办、共享池可读
    # ===================================================================
    with rec.step(
        "P09-US11-AC-05-admin",
        us="US-11",
        sc="SC-11-01",
        desc="管理员无个人站内通知/待办，待办从共享处理池读取",
        expected="todos.total=0；notifications.total=0；unread-count=0；共享池可读且含待处理举报事项",
    ):
        admin_token = ctx.token("admin")
        todos = _todos(api, admin_token)
        rec.must_eq(todos.get("total"), 0, "管理员个人待办数")
        rec.must_eq(todos.get("items"), [], "管理员个人待办明细应为空")
        notifications = _notifications(api, admin_token)
        rec.must_eq(notifications.get("total"), 0, "管理员站内通知数")
        unread = api.get("/notifications/unread-count", token=admin_token, expected=200).json()
        rec.must_eq(unread.get("unread"), 0, "管理员未读通知数")
        pool = admin_list_cases(api, ctx, status="pending", case_type="report")
        rec.must(isinstance(pool, list), "共享池待处理举报事项应为列表")
        rec.must(
            any(case.get("case_type") == "report" for case in pool),
            "共享池应可读取待处理举报事项（本人举报尚未处置）",
        )
        admin_items = _notifications(api, admin_token).get("items") or []
        rec.must_eq(admin_items, [], "管理员不接收个人站内通知")

    # ===================================================================
    # US-13 从管理端复读分类/别名/停用与检索一致（p02 已覆盖则不重复消耗）
    # ===================================================================
    renamed = ctx.categories.get("renamed")
    deactivated = ctx.categories.get("deact_cat")
    deleted = ctx.categories.get("deleted_cat")
    if not (renamed or deactivated or deleted):
        rec.skip(
            "P09-US13-AC-03-readback",
            us="US-13",
            sc="SC-10",
            desc="从管理端复读分类改名/别名/停用/删除与检索一致",
            reason="本次运行未执行 p02（ctx 无分类维护对象）；分类维护已由 p02 覆盖，p09 不重复消耗数据",
        )
    else:
        with rec.step(
            "P09-US13-AC-03-readback",
            us="US-13",
            sc="SC-10",
            desc="管理端复读分类：新主名/别名/停用/删除与商品检索口径一致",
            expected="改名后新主名可检索、旧名不再作为别名命中；停用分类保留于分类列表；逻辑删除分类不再返回",
        ):
            admin_token = ctx.token("admin")
            categories = api.get("/categories", token=admin_token, expected=200).json()
            by_id = {cat["id"]: cat for cat in categories}

            def _search_ids(params: dict) -> list[int]:
                payload = api.get("/products/search", token=admin_token, params=params, expected=200).json()
                return sorted(item["id"] for item in payload.get("items") or [])

            if renamed:
                target = by_id.get(renamed.get("id"))
                rec.must(target is not None, "改名后的分类应仍在分类列表")
                rec.must_eq(target.get("name"), renamed.get("name"), "分类当前主名")
                # D-45：当前主名与全部活跃别名都指向同一分类，检索结果应与分类 ID 检索一致
                by_id_ids = _search_ids({"category_ids": target.get("id")})
                labels = [target.get("name"), *(target.get("aliases") or [])]
                for label in filter(None, labels):
                    name_ids = _search_ids({"category_names": label})
                    rec.must_eq(name_ids, by_id_ids, f"分类名/别名「{label}」与分类 ID 检索结果一致")
                # 旧主名当前已既非主名也非活跃别名时按无匹配处理，不得回退到历史名称
                if "运动器材" not in labels:
                    old_alias_search = api.get(
                        "/products/search", token=admin_token, params={"category_names": "运动器材"}, expected=200
                    ).json()
                    rec.must_eq(old_alias_search.get("total"), 0, "已移除旧别名不应再命中商品")
            if deactivated:
                target = by_id.get(deactivated.get("id"))
                rec.must(target is not None, "停用分类应保留在分类读接口中（筛选入口保留）")
                rec.must_in(target.get("status"), ("active", "disabled"), "停用分类状态为合法枚举")
                rec.must_eq(
                    _search_ids({"category_names": target.get("name")}),
                    _search_ids({"category_ids": target.get("id")}),
                    "停用分类名称与分类 ID 检索口径一致（已关联商品保留）",
                )
            if deleted:
                rec.must(deleted.get("id") not in by_id, "逻辑删除的分类不再出现在分类列表")

    ctx.note(
        "p09 完成：US-10 统计（权限/时点指标/范围与全部/失败口径/无资金口径）、US-12 本人业务、"
        "US-11 待办（请求/约定/完成确认/取消/问询）与通知已读分离均用真实接口核对；"
        "US-13 仅在 p02 对象存在时复读，否则 SKIP。交易 p09_t_agree（本人买方）保留单方完成确认与 7 天等待。"
    )
