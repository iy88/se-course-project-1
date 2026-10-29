"""p10 可靠性与权限边界（第 7 章 7.3 可靠性与安全验收；US-05、US-12、US-07 相关边界）。

真实 HTTP 独立造数：并发接受、重复提交、旧状态提交、越权、封禁写拒绝、分页/参数边界、
恶意输入、响应一致性全部通过运行中的真实服务核对；不直接写库、不使用内存传输。

覆盖映射：
- 接近同时接受两条请求（7.3 可靠性 / US-05-AC-02 / SC-05-02 / DT-01）
- 重复点击/刷新/重试只生效一次（7.3 可靠性 / 6.5；US-05、US-07）
- 旧页面提交时状态已变（7.3 可靠性 / BR-27）
- 未登录 401 与越权访问（7.3 安全 / BR-19、BR-22、BR-27、BR-32、BR-34）
- 封禁用户写操作拒绝、处置沟通例外、解封恢复（BR-32 / DT-03）
- 分页与查询参数边界、恶意输入 422（7.3 安全）
- 保存成功后重复读取结果稳定（7.3 可靠性 / 6.5）
- 历史与逻辑删除：既有举报关联保留、失效对象新举报失败（7.3 可靠性 / 4.18）

本阶段自造封禁账户，不改动 qian 等既有样本的最终状态（若 ctx 存在则做前后状态守卫）。
"""

from __future__ import annotations

import threading

from e2e_support import (
    admin_claim_case,
    admin_list_cases,
    asset,
    ensure_account,
    login_account,
    upload_image,
)

PHASE_ID = "p10"
PASSWORD = "secret123"
TAG_NAME = "电子产品"

AGREEMENT_BODY = {
    "delivery_time": "2026-11-02 18:00",
    "delivery_location": "图书馆门口",
    "delivery_method": "当面自提",
    "amount_cents": 8800,
    "payment_method": "支付宝",
    "payment_timing": "当面支付",
}


# ---------------------------------------------------------------------------
# 基础辅助
# ---------------------------------------------------------------------------
def _admin_account(api, ctx):
    acct = ctx.accounts.get("admin")
    if acct and acct.get("token"):
        return acct
    return login_account(api, ctx, "admin", "admin@campus.edu", "admin123456")


def _category_id(api, token: str, name: str = TAG_NAME) -> int:
    for cat in api.get("/categories", token=token, expected=200).json():
        if cat.get("name") == name and cat.get("status") == "active":
            return cat["id"]
    for cat in api.get("/categories", token=token, expected=200).json():
        if cat.get("status") == "active":
            return cat["id"]
    raise AssertionError("没有可用的商品分类标签")


def _publish(api, token: str, title: str, image_key: str, category_id: int, *, price: int = 8800) -> dict:
    body = {
        "title": title,
        "description": "p10 真实 API 可靠性与权限边界测试商品。",
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


def _review_product(api, ctx, product_id: int, *, approve: bool = True, reason: str | None = None) -> None:
    case = _pending_review_case(api, ctx, product_id)
    admin_claim_case(api, ctx, case["id"])
    body = {"result": "approved" if approve else "rejected"}
    if reason:
        body["reason"] = reason
    api.post(f"/admin/products/cases/{case['id']}/review", token=ctx.token("admin"), json_body=body, expected=200)


def _make_listed(api, ctx, key: str, seller_key: str, token: str, title: str, image_key: str, category_id: int) -> dict:
    product = _publish(api, token, title, image_key, category_id)
    _review_product(api, ctx, product["id"], approve=True)
    ctx.remember_product(key, product, seller=seller_key, state="listed")
    return product


def _request(api, token: str, product_id: int, *, expected=200):
    return api.post("/trades/requests", token=token, json_body={"product_id": product_id}, expected=expected)


def _accept(api, token: str, trade_id: int, *, expected=200):
    return api.post(f"/trades/{trade_id}/accept", token=token, expected=expected)


def _trade(api, token: str, trade_id: int) -> dict:
    return api.get(f"/trades/{trade_id}", token=token, expected=200).json()


def _notifications(api, token: str, *, page_size: int = 50) -> dict:
    return api.get(
        "/notifications", token=token, params={"page": 1, "page_size": page_size}, expected=200
    ).json()


def _find_notification(
    items: list[dict], *, type_: str | None = None, link_id: int | None = None, product_id: int | None = None
) -> list[dict]:
    found = []
    for item in items:
        if type_ is not None and item.get("type") != type_:
            continue
        if link_id is not None and item.get("link_id") != link_id:
            continue
        payload = item.get("payload") or {}
        if product_id is not None and payload.get("product_id") != product_id:
            continue
        found.append(item)
    return found


def _stats(api, ctx) -> dict:
    return api.get("/admin/stats", token=ctx.token("admin"), expected=200).json()


def _expect_status(api, rec, method: str, path: str, status: int | tuple[int, ...], *, token: str | None = None,
                   params: dict | None = None, json_body=None, files: dict | None = None, label: str = ""):
    resp = api.request(method, path, token=token, params=params, json_body=json_body, files=files)
    rec.must_eq(resp.status_code, status if isinstance(status, int) else tuple(status), label or f"{method} {path} 状态码")
    return resp


def _need(*values) -> None:
    if any(value is None for value in values):
        raise AssertionError("前置数据缺失（p10 造数步骤失败），无法继续该检查")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run(ctx, api, rec):  # noqa: ANN001
    admin = _admin_account(api, ctx)

    seller = ensure_account(api, ctx, "c2rel_seller", "c2rel.seller@campus.edu", "任同学", PASSWORD)
    buyer1 = ensure_account(api, ctx, "c2rel_buyer1", "c2rel.buyer1@campus.edu", "侯同学", PASSWORD)
    buyer2 = ensure_account(api, ctx, "c2rel_buyer2", "c2rel.buyer2@campus.edu", "康同学", PASSWORD)
    third = ensure_account(api, ctx, "c2rel_third", "c2rel.third@campus.edu", "苏同学", PASSWORD)
    banme = ensure_account(api, ctx, "c2rel_banme", "c2rel.banme@campus.edu", "封同学", PASSWORD)

    seller_token = seller["token"]
    buyer1_token = buyer1["token"]
    buyer2_token = buyer2["token"]
    third_token = third["token"]
    banme_token = banme["token"]
    image = upload_image(api, seller_token, "product_bike.jpg", namespace="product")
    ctx.remember_item("file", "p10_product_image", image["key"], "p10 商品图", "uploaded", {"url": image["url"]})
    category_id = _category_id(api, seller_token)

    # qian 等既有样本的状态守卫（不得被本阶段破坏）
    qian_before = None
    if "qian" in ctx.accounts:
        qian_before = api.get("/auth/me", token=ctx.token("qian"), expected=200).json()

    # 数据占位
    p_concurrent = p_dup = p_done = p_old = p_ban = None
    t_win = t_lose = t_dup = t_done = t_old1 = t_old2 = None
    report_dup_id = report_case_id = ban_case_id = None
    conv_trade = None

    # ===================================================================
    # 造数：5 件在售商品（真实图片 + 审核）
    # ===================================================================
    with rec.step(
        "P10-SETUP-products",
        us="US-05",
        sc="SC-05-01",
        desc="通过真实上传/发布/管理员审核接口创建可靠性测试商品",
        expected="5 件商品全部审核通过并公开可交易",
    ):
        p_concurrent = _make_listed(
            api, ctx, "p10_product_concurrent", "c2rel_seller", seller_token, "p10 并发锁单测试商品", image["key"], category_id
        )
        p_dup = _make_listed(
            api, ctx, "p10_product_dup", "c2rel_seller", seller_token, "p10 重复提交测试商品", image["key"], category_id
        )
        p_done = _make_listed(
            api, ctx, "p10_product_done", "c2rel_seller", seller_token, "p10 完成交易测试商品", image["key"], category_id
        )
        p_old = _make_listed(
            api, ctx, "p10_product_old", "c2rel_seller", seller_token, "p10 旧状态提交测试商品", image["key"], category_id
        )
        p_ban = _make_listed(
            api, ctx, "p10_product_ban", "c2rel_seller", seller_token, "p10 封禁与举报测试商品", image["key"], category_id
        )
        _need(p_concurrent, p_dup, p_done, p_old, p_ban)
        rec.must_eq(p_concurrent.get("status"), "pending_review", "发布响应初始状态为待审核")
        mine = api.get("/products/mine", token=seller_token, expected=200).json()
        listed_ids = {product["id"] for product in mine if product.get("status") == "listed"}
        for product in (p_concurrent, p_dup, p_done, p_old, p_ban):
            rec.must(product["id"] in listed_ids, f"商品 #{product['id']} 审核通过后应在售")

    # ===================================================================
    # 7.3 可靠性：接近同时接受同一商品的两条请求
    # ===================================================================
    with rec.step(
        "P10-REL-01-concurrent-accept",
        us="US-05",
        sc="SC-05-02",
        desc="两个并发请求同时接受同一商品的两条待接受请求：至多一笔生效，另一个返回 409",
        expected="恰一个 200、一个 409（不出现双 200/500/其他状态）",
    ):
        _need(p_concurrent)
        t_a = _request(api, buyer1_token, p_concurrent["id"], expected=200).json()["id"]
        t_b = _request(api, buyer2_token, p_concurrent["id"], expected=200).json()["id"]
        ctx.remember_trade("p10_t_concurrent_a", {"id": t_a}, buyer="c2rel_buyer1", seller="c2rel_seller", state="pending_acceptance")
        ctx.remember_trade("p10_t_concurrent_b", {"id": t_b}, buyer="c2rel_buyer2", seller="c2rel_seller", state="pending_acceptance")
        results: dict[str, dict] = {}
        barrier = threading.Barrier(2)

        def accept_worker(label: str, trade_id: int) -> None:
            barrier.wait(timeout=15)
            resp = api.post(f"/trades/{trade_id}/accept", token=seller_token)
            results[label] = {"trade_id": trade_id, "status": resp.status_code, "body": resp.text[:300]}

        threads = [
            threading.Thread(target=accept_worker, args=("A", t_a)),
            threading.Thread(target=accept_worker, args=("B", t_b)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=40)
        rec.must_eq(len(results), 2, f"两个并发接受请求都应返回结果，实际 {results}")
        codes = sorted(item["status"] for item in results.values())
        rec.must_eq(codes, [200, 409], f"并发接受应恰一 200 一 409，实际 {results}")
        rec.must(
            all(isinstance(item["status"], int) and item["status"] < 500 for item in results.values()),
            f"并发接受不应出现 5xx：{results}",
        )
        # 记录赢家/输家交易 id 供后续核对
        winner = [item for item in results.values() if item["status"] == 200][0]
        loser = [item for item in results.values() if item["status"] == 409][0]
        t_win = winner["trade_id"]
        t_lose = loser["trade_id"]
        ctx.update_trade("p10_t_concurrent_a", "in_progress" if t_win == t_a else "closed")
        ctx.update_trade("p10_t_concurrent_b", "in_progress" if t_win == t_b else "closed")
        ctx.remember_item(
            "concurrency", "p10_concurrent", [t_a, t_b], "并发接受结果", "one_success",
            {"winner": t_win, "loser": t_lose, "codes": codes},
        )

    with rec.step(
        "P10-REL-02-concurrent-state",
        us="US-05",
        sc="SC-05-02",
        desc="并发结束后：商品恰一笔锁单，其余请求 closed，无重复交易与重复分支",
        expected="商品 in_transaction；同一商品仅 1 笔 in_progress；另一笔 closed 且原因为锁单；请求/交易/分支各 2 条",
    ):
        _need(p_concurrent, t_win, t_lose)
        product = api.get(f"/products/{p_concurrent['id']}", token=seller_token, expected=200).json()
        rec.must_eq(product.get("status"), "in_transaction", "接受后商品状态")
        seller_trades = api.get("/trades/mine", token=seller_token, params={"role": "seller"}, expected=200).json()
        product_trades = [trade for trade in seller_trades if trade.get("product_id") == p_concurrent["id"]]
        rec.must_eq(len(product_trades), 2, f"同一商品应恰有 2 条请求/交易记录，实际 {len(product_trades)}")
        by_id = {trade["id"]: trade for trade in product_trades}
        rec.must(t_win in by_id and t_lose in by_id, "并发交易应都在我的交易中")
        rec.must_eq(by_id[t_win].get("status"), "in_progress", "生效请求状态")
        rec.must_eq(by_id[t_lose].get("status"), "closed", "未生效请求应被关闭")
        rec.must_eq(by_id[t_lose].get("close_reason"), "商品已被其他用户锁单", "未生效请求关闭原因")
        locking = [trade for trade in product_trades if trade.get("status") in ("in_progress", "disputed", "abnormal")]
        rec.must_eq(len(locking), 1, "同一商品同时至多一笔锁单交易")
        winner_detail = _trade(api, seller_token, t_win)
        loser_detail = _trade(api, seller_token, t_lose)
        rec.must(winner_detail.get("conversation_id") is not None, "生效交易应有交易分支")
        rec.must_eq(loser_detail.get("conversation_archived"), True, "被关闭请求分支应归档")
        rec.must(winner_detail.get("conversation_id") != loser_detail.get("conversation_id"), "两笔请求分支独立")
        winner_transitions = api.get(f"/trades/{t_win}/transitions", token=seller_token, expected=200).json()
        loser_transitions = api.get(f"/trades/{t_lose}/transitions", token=seller_token, expected=200).json()
        rec.must("request_accepted" in [row.get("trigger") for row in winner_transitions], "生效交易应有接受转移")
        rec.must("closed" in [row.get("to_status") for row in loser_transitions], "未生效请求应有关闭转移")

    with rec.step(
        "P10-REL-03-concurrent-notify",
        us="US-05",
        sc="SC-05-02",
        desc="并发锁单只产生一次成功通知与一次关闭通知，不重复通知/不重复状态变更",
        expected="赢家 1 条 request_accepted；输家 1 条 request_closed；卖方每个请求 1 条 request_created 且总数 2",
    ):
        _need(t_win, t_lose, p_concurrent)
        winner_info = _trade(api, seller_token, t_win)
        winner_buyer_token = buyer1_token if winner_info.get("buyer", {}).get("id") == buyer1["id"] else buyer2_token
        loser_buyer_token = buyer2_token if winner_buyer_token == buyer1_token else buyer1_token
        winner_notifications = _notifications(api, winner_buyer_token)["items"]
        loser_notifications = _notifications(api, loser_buyer_token)["items"]
        accepted = [
            item for item in winner_notifications
            if item.get("type") == "request_accepted" and (item.get("payload") or {}).get("trade_id") == t_win
        ]
        rec.must_eq(len(accepted), 1, "生效买方应恰收到 1 条 request_accepted 通知（不重复）")
        closed = [
            item for item in loser_notifications
            if item.get("type") == "request_closed" and item.get("link_id") == t_lose
        ]
        rec.must_eq(len(closed), 1, "关闭买方应恰收到 1 条 request_closed 通知（不重复）")
        seller_notifications = _notifications(api, seller_token)["items"]
        created = _find_notification(seller_notifications, type_="request_created", product_id=p_concurrent["id"])
        created_count = sum(
            1 for item in seller_notifications
            if item.get("type") == "request_created" and (item.get("payload") or {}).get("product_id") == p_concurrent["id"]
        )
        rec.must_eq(created_count, 2, "卖方对该商品应恰有 2 条 request_created 通知（每个请求一次）")
        rec.must_eq(len({(item.get("payload") or {}).get("trade_id") for item in created}), 2, "两条请求通知指向不同交易")
        # 并发中不允许出现重复的状态转移记录
        transitions = api.get(f"/trades/{t_win}/transitions", token=seller_token, expected=200).json()
        accept_transitions = [row for row in transitions if row.get("trigger") == "request_accepted"]
        rec.must_eq(len(accept_transitions), 1, "生效交易 request_accepted 转移应恰 1 条")

    # ===================================================================
    # 7.3 可靠性：重复提交只生效一次
    # ===================================================================
    with rec.step(
        "P10-REL-04-duplicate-request",
        us="US-05",
        sc="SC-05-01",
        desc="同一买方对同一商品重复提交购买请求：返回既有请求，不新建交易/分支/通知",
        expected="第二次 200 existing=true 且 id 相同；该买方对该商品仅 1 笔交易；卖方 request_created 仅 1 条",
    ):
        _need(p_dup)
        first = _request(api, buyer1_token, p_dup["id"]).json()
        t_dup = first["id"]
        ctx.remember_trade("p10_t_dup", {"id": t_dup}, buyer="c2rel_buyer1", seller="c2rel_seller", state="pending_acceptance")
        second_resp = _request(api, buyer1_token, p_dup["id"])
        second = second_resp.json()
        rec.must_eq(second.get("id"), t_dup, "重复请求应返回既有请求 id")
        rec.must_eq(second.get("existing"), True, "重复请求应标记 existing")
        mine = api.get("/trades/mine", token=buyer1_token, params={"role": "buyer"}, expected=200).json()
        same_product = [trade for trade in mine if trade.get("product_id") == p_dup["id"]]
        rec.must_eq(len(same_product), 1, "同一买方同一商品仅 1 笔待接受请求")
        seller_notifications = _notifications(api, seller_token)["items"]
        created_count = sum(
            1 for item in seller_notifications
            if item.get("type") == "request_created" and (item.get("payload") or {}).get("product_id") == p_dup["id"]
        )
        rec.must_eq(created_count, 1, "重复请求不应重复通知卖方")

    # ---- 完成交易（用于重复评价与已结束交易操作） ----
    with rec.step(
        "P10-SETUP-completed-trade",
        us="US-05",
        sc="SC-05-08",
        desc="真实接口构造一笔已完成交易（请求→接受→约定→双方完成确认）",
        expected="交易 completed，商品默认下架",
    ):
        _need(p_done)
        t_done = _request(api, buyer1_token, p_done["id"]).json()["id"]
        ctx.remember_trade("p10_t_done", {"id": t_done}, buyer="c2rel_buyer1", seller="c2rel_seller", state="pending_acceptance")
        _accept(api, seller_token, t_done)
        agreement = api.post(
            f"/trades/{t_done}/agreements", token=buyer1_token, json_body=AGREEMENT_BODY, expected=200
        ).json()
        api.post(
            f"/trades/{t_done}/agreements/{agreement['id']}/confirm", token=seller_token, expected=200
        )
        api.post(f"/trades/{t_done}/confirmations", token=buyer1_token, json_body={}, expected=200)
        result = api.post(f"/trades/{t_done}/confirmations", token=seller_token, json_body={}, expected=200).json()
        rec.must("交易已完成" in str(result.get("detail")), "双方确认后交易应完成")
        detail = _trade(api, buyer1_token, t_done)
        rec.must_eq(detail.get("status"), "completed", "交易状态")
        ctx.update_trade("p10_t_done", "completed")
        product = api.get(f"/products/{p_done['id']}", token=seller_token, expected=200).json()
        rec.must_eq(product.get("status"), "delisted", "完成后商品默认下架")
        conv_trade = detail.get("conversation_id")

    with rec.step(
        "P10-REL-05-duplicate-review",
        us="US-07",
        sc="SC-07-01",
        desc="同一交易重复评价被拒绝；未完成交易不可评价",
        expected="首次评价 201；重复评价 409 您已评价过本笔交易；进行中交易评价 409 仅已完成交易可评价",
    ):
        _need(t_done, t_dup)
        first = api.post(
            f"/trades/{t_done}/review", token=buyer1_token, json_body={"rating": 5, "content": "p10 首次评价"}, expected=201
        ).json()
        ctx.remember_item("review", "p10_review", first.get("id"), "p10 首次评价", "published", {"trade_id": t_done})
        resp = _expect_status(
            api, rec, "POST", f"/trades/{t_done}/review", 409, token=buyer1_token,
            json_body={"rating": 4, "content": "p10 重复评价"}, label="重复评价",
        )
        rec.must("已评价过" in str(resp.json().get("detail")), "重复评价应提示已评价过本笔交易")
        resp = _expect_status(
            api, rec, "POST", f"/trades/{t_dup}/review", 409, token=buyer1_token,
            json_body={"rating": 5, "content": "p10 未完成交易评价"}, label="未完成交易评价",
        )
        rec.must("仅已完成交易" in str(resp.json().get("detail")), "未完成交易评价应提示仅已完成交易可评价")
        reviews = api.get("/me/reviews", token=buyer1_token, params={"type": "published"}, expected=200).json()
        same_trade = [row for row in reviews if row.get("trade_id") == t_done]
        rec.must_eq(len(same_trade), 1, "重复评价只应留下 1 条记录")

    # ===================================================================
    # 7.3 可靠性 / 权限：重复举报与事项认领
    # ===================================================================
    with rec.step(
        "P10-REL-06-duplicate-report",
        us="US-07",
        sc="SC-07-10",
        desc="同一用户对同一对象未结举报：在原事项补充，不新建第二条举报/事项",
        expected="第二次 201 返回 existing_report_id=首条 id；我的举报该对象仅 1 条",
    ):
        _need(p_dup)
        first = api.post(
            "/reports",
            token=buyer1_token,
            json_body={"target_type": "product", "target_id": p_dup["id"], "reason": "p10 重复举报测试：描述不符"},
            expected=201,
        ).json()
        report_dup_id = first["id"]
        ctx.remember_report("p10_report_dup", first)
        second_resp = api.post(
            "/reports",
            token=buyer1_token,
            json_body={"target_type": "product", "target_id": p_dup["id"], "reason": "p10 重复举报测试：再次提交"},
            expected=201,
        )
        second = second_resp.json()
        rec.must_eq(second.get("existing_report_id"), report_dup_id, "重复举报应指向既有未结举报")
        mine = api.get("/reports/mine", token=buyer1_token, expected=200).json()
        same_target = [row for row in mine if row.get("target_type") == "product" and row.get("target_id") == p_dup["id"]]
        rec.must_eq(len(same_target), 1, "同对象未结举报不应新建第二条")

    with rec.step(
        "P10-SEC-01-admin-not-claimant",
        us="US-08",
        sc="SC-07-04",
        desc="管理员读取未认领事项详情被拒绝（非认领管理员不得读取非公开记录）",
        expected="未认领事项详情 403；管理员个人待办为空（待办来自共享池）",
    ):
        _need(report_dup_id)
        admin_token = ctx.token("admin")
        reports = api.get("/admin/reports", token=admin_token, params={"status": "pending"}, expected=200).json()
        matched = [row for row in reports if row.get("id") == report_dup_id]
        rec.must_eq(len(matched), 1, "共享池应包含新举报")
        report_case_id = matched[0].get("case_id")
        rec.must(report_case_id, "举报应关联事项")
        ctx.remember_case("p10_report_case", {"id": report_case_id, "case_type": "report", "title": "p10 举报事项", "status": "pending"})
        resp = _expect_status(
            api, rec, "GET", f"/admin/cases/{report_case_id}", 403, token=admin_token, label="非认领管理员读取事项详情"
        )
        rec.must("仅该事项认领管理员" in str(resp.json().get("detail")), "非认领管理员读取应提示仅认领管理员可查看")

    with rec.step(
        "P10-REL-07-duplicate-claim",
        us="US-08",
        sc="SC-07-04",
        desc="管理员重复认领同一事项被拒绝；认领成功后可读取详情",
        expected="首次认领 200；第二次 409 该事项已被认领或已处置；认领后详情 200",
    ):
        _need(report_case_id)
        admin_token = ctx.token("admin")
        admin_claim_case(api, ctx, report_case_id)
        resp = _expect_status(
            api, rec, "POST", f"/admin/cases/{report_case_id}/claim", 409, token=admin_token, json_body=None,
            label="重复认领事项",
        )
        rec.must("已被认领或已处置" in str(resp.json().get("detail")), "重复认领应提示已被认领")
        detail = api.get(f"/admin/cases/{report_case_id}", token=admin_token, expected=200).json()
        rec.must_eq(detail.get("claimed_by_id"), admin["id"], "事项认领人")
        rec.must_eq(detail.get("status"), "processing", "事项认领后状态")

    # ===================================================================
    # 7.3 可靠性：旧页面提交时状态已变
    # ===================================================================
    with rec.step(
        "P10-REL-08-old-state-rejected",
        us="US-05",
        sc="SC-05-04",
        desc="接受一条已被拒绝的旧请求：按当前状态拒绝且无副作用",
        expected="409 该请求当前不可接受；交易仍 rejected、商品仍 listed",
    ):
        _need(p_old)
        t_old1 = _request(api, buyer1_token, p_old["id"]).json()["id"]
        ctx.remember_trade("p10_t_old1", {"id": t_old1}, buyer="c2rel_buyer1", seller="c2rel_seller", state="pending_acceptance")
        api.post(f"/trades/{t_old1}/reject", token=seller_token, json_body={"reason": "p10 旧状态：卖方拒绝"}, expected=200)
        ctx.update_trade("p10_t_old1", "rejected")
        resp = _expect_status(api, rec, "POST", f"/trades/{t_old1}/accept", 409, token=seller_token, label="接受已拒绝请求")
        rec.must("不可接受" in str(resp.json().get("detail")), "接受已拒绝请求应提示不可接受")
        rec.must_eq(_trade(api, seller_token, t_old1).get("status"), "rejected", "旧状态拒绝后交易状态不变")
        product = api.get(f"/products/{p_old['id']}", token=seller_token, expected=200).json()
        rec.must_eq(product.get("status"), "listed", "旧状态拒绝后商品状态不变")

    with rec.step(
        "P10-REL-09-old-state-withdraw",
        us="US-05",
        sc="SC-05-07",
        desc="撤回一条已被接受的请求：按当前状态拒绝且无副作用",
        expected="409 卖方已处理该请求，无法撤回；交易仍 in_progress",
    ):
        _need(p_old)
        second = _request(api, buyer1_token, p_old["id"]).json()
        t_old2 = second["id"]
        ctx.remember_trade("p10_t_old2", {"id": t_old2}, buyer="c2rel_buyer1", seller="c2rel_seller", state="pending_acceptance")
        _accept(api, seller_token, t_old2)
        ctx.update_trade("p10_t_old2", "in_progress")
        resp = _expect_status(api, rec, "POST", f"/trades/{t_old2}/withdraw", 409, token=buyer1_token, label="撤回已接受请求")
        rec.must("已处理" in str(resp.json().get("detail")), "撤回已接受请求应提示卖方已处理")
        rec.must_eq(_trade(api, buyer1_token, t_old2).get("status"), "in_progress", "撤回被拒后交易状态不变")

    with rec.step(
        "P10-REL-10-old-state-confirm",
        us="US-06",
        sc="SC-05-01",
        desc="未有生效约定时提交完成确认：按当前状态拒绝且不写入确认/计时",
        expected="409 须先确认交易约定；交易确认列表为空、等待计时为空",
    ):
        _need(t_old2)
        resp = _expect_status(
            api, rec, "POST", f"/trades/{t_old2}/confirmations", 409, token=buyer1_token, json_body={},
            label="无约定提交完成确认",
        )
        rec.must("须先确认交易约定" in str(resp.json().get("detail")), "无约定完成确认应提示须先确认约定")
        detail = _trade(api, buyer1_token, t_old2)
        rec.must_eq(detail.get("confirmations"), [], "被拒绝的完成确认不应留下记录")
        rec.must_eq(detail.get("confirm_wait_started_at"), None, "被拒绝的完成确认不应开始计时")
        rec.must_eq(detail.get("status"), "in_progress", "交易状态不变")

    with rec.step(
        "P10-REL-11-ended-trade-ops",
        us="US-05",
        sc="SC-05-10",
        desc="对已结束交易执行旧操作：接受/完成确认/取消均被拒绝且无副作用（无新增转移/通知）",
        expected="三个操作均 409；交易仍 completed；状态转移与买卖双方通知数不变",
    ):
        _need(t_done)
        admin_token = ctx.token("admin")
        transitions_before = api.get(f"/trades/{t_done}/transitions", token=buyer1_token, expected=200).json()
        buyer_total_before = _notifications(api, buyer1_token).get("total")
        seller_total_before = _notifications(api, seller_token).get("total")
        resp = _expect_status(api, rec, "POST", f"/trades/{t_done}/confirmations", 409, token=buyer1_token, json_body={}, label="已结束交易完成确认")
        rec.must("仅进行中交易" in str(resp.json().get("detail")), "已结束交易完成确认应提示仅进行中")
        resp = _expect_status(api, rec, "POST", f"/trades/{t_done}/cancel", 409, token=buyer1_token, json_body={}, label="已结束交易取消")
        rec.must("不能取消" in str(resp.json().get("detail")), "已结束交易取消应提示不能取消")
        resp = _expect_status(api, rec, "POST", f"/trades/{t_done}/accept", 409, token=seller_token, label="已结束交易接受")
        rec.must("不可接受" in str(resp.json().get("detail")), "已结束交易接受应提示不可接受")
        rec.must_eq(_trade(api, buyer1_token, t_done).get("status"), "completed", "失败操作后交易状态不变")
        transitions_after = api.get(f"/trades/{t_done}/transitions", token=buyer1_token, expected=200).json()
        rec.must_eq(len(transitions_after), len(transitions_before), "失败操作不应新增状态转移")
        rec.must_eq(_notifications(api, buyer1_token).get("total"), buyer_total_before, "失败操作不应新增买方通知")
        rec.must_eq(_notifications(api, seller_token).get("total"), seller_total_before, "失败操作不应新增卖方通知")

    # ===================================================================
    # 7.3 安全：未登录 401 与越权访问
    # ===================================================================
    with rec.step(
        "P10-SEC-02-unauth-401",
        us="US-01",
        sc="SC-01-08",
        desc="未登录访问业务接口统一 401，不返回业务内容",
        expected="抽查商品/交易/收藏/通知/评价/事项/举报/管理/会话接口均 401",
    ):
        paths = [
            "/products/search",
            "/products/mine",
            "/favorites",
            "/trades/mine",
            "/notifications",
            "/notifications/todos",
            "/me/reviews",
            "/me/cases",
            "/reports/mine",
            "/reports/received",
            "/conversations",
            "/conversations/unread-summary",
            "/categories",
            "/prohibited-items",
            "/admin/stats",
            "/admin/cases",
            "/admin/users",
        ]
        failures = []
        for path in paths:
            resp = api.get(path)
            if resp.status_code != 401:
                failures.append(f"{path} → {resp.status_code}")
            else:
                body = resp.json()
                if "未登录或登录已过期" not in str(body.get("detail")):
                    failures.append(f"{path} 401 文案异常")
        rec.must(not failures, f"未登录访问应统一 401：{failures}")

    with rec.step(
        "P10-SEC-03-cross-trade",
        us="US-12",
        sc="SC-12-03",
        desc="第三方直接访问他人交易链接：404 防枚举且不泄露私人内容",
        expected="404 交易不存在；响应不含商品标题/买卖双方/约定等私人字段",
    ):
        _need(t_done)
        resp = api.get(f"/trades/{t_done}", token=third_token, expected=404)
        body = resp.json()
        rec.must_eq(body.get("detail"), "交易不存在", "他人交易读取文案")
        for key in ("product_title", "buyer", "seller", "effective_agreement", "confirmations"):
            rec.must(key not in body, f"他人交易错误响应不得泄露字段 {key}")
        resp = api.get(f"/trades/{t_done}/transitions", token=third_token, expected=404)
        rec.must_eq(resp.json().get("detail"), "交易不存在", "他人交易状态转移读取文案")

    with rec.step(
        "P10-SEC-04-cross-conversation",
        us="US-04",
        sc="SC-04-05",
        desc="第三方访问他人交易分支会话被拒绝，不泄露消息",
        expected="403 非会话成员无权访问",
    ):
        _need(conv_trade)
        resp = api.get(f"/conversations/{conv_trade}", token=third_token, expected=403)
        rec.must("非会话成员" in str(resp.json().get("detail")), "第三方访问他人会话应提示非会话成员")
        resp = api.post(f"/conversations/{conv_trade}/messages", token=third_token, json_body={"content": "p10 越权消息"}, expected=403)
        rec.must("非会话成员" in str(resp.json().get("detail")), "第三方向他人会话发送应被拒绝")

    with rec.step(
        "P10-SEC-05-cross-favorite",
        us="US-04",
        sc="SC-03-07",
        desc="收藏清单按本人归属：他人不可读取/删除本人收藏，删除他人收藏关系无效果",
        expected="third 清单不含；third 删除他人收藏 404；本人收藏保持",
    ):
        _need(p_ban)
        first = api.post(f"/favorites/{p_ban['id']}", token=banme_token, expected=200).json()
        rec.must(first.get("favorite_id"), "收藏应返回 favorite_id")
        third_favorites = api.get("/favorites", token=third_token, expected=200).json()
        rec.must(
            all(row.get("product_id") != p_ban["id"] for row in third_favorites),
            "他人收藏清单不应包含本人收藏商品",
        )
        resp = _expect_status(api, rec, "DELETE", f"/favorites/{p_ban['id']}", 404, token=third_token, label="他人取消收藏")
        rec.must("未收藏" in str(resp.json().get("detail")), "删除他人收藏关系应提示未收藏")
        banme_favorites = api.get("/favorites", token=banme_token, expected=200).json()
        rec.must(
            any(row.get("product_id") == p_ban["id"] and row.get("valid") is True for row in banme_favorites),
            "本人收藏不因他人操作失效",
        )

    with rec.step(
        "P10-SEC-06-cross-case",
        us="US-12",
        sc="SC-12-03",
        desc="第三方访问/操作他人处置事项被拒绝，不泄露说明与申辩内容",
        expected="他人事项详情/说明均 403",
    ):
        _need(report_case_id)
        resp = api.get(f"/me/cases/{report_case_id}", token=third_token, expected=403)
        rec.must("无权访问" in str(resp.json().get("detail")), "第三方访问他人事项应提示无权访问")
        resp = api.post(
            f"/me/cases/{report_case_id}/statement", token=third_token, json_body={"content": "p10 越权说明"}, expected=403
        )
        rec.must("无权访问" in str(resp.json().get("detail")), "第三方提交他人事项说明应被拒绝")
        resp = _expect_status(api, rec, "POST", f"/me/cases/{report_case_id}/appeal", 403, token=third_token,
                              json_body={"content": "p10 越权申辩"}, label="第三方提交他人事项申辩")
        rec.must("无权访问" in str(resp.json().get("detail")), "第三方提交他人事项申辩应被拒绝")

    with rec.step(
        "P10-SEC-07-admin-private-trade",
        us="US-08",
        sc="SC-07-04",
        desc="管理员未认领相关事项时读取私人交易被拒绝（事项必要范围限制）",
        expected="403 管理员须先认领与本交易相关的处置事项",
    ):
        _need(t_old2)
        admin_token = ctx.token("admin")
        resp = api.get(f"/admin/trades/{t_old2}", token=admin_token, expected=403)
        rec.must(
            "须先认领" in str(resp.json().get("detail")) or "认领" in str(resp.json().get("detail")),
            f"管理员越权读取私人交易应提示须先认领相关事项，实际 {resp.json()}",
        )

    # ===================================================================
    # 7.3 安全：封禁用户写操作拒绝、处置沟通例外、解封恢复
    # ===================================================================
    with rec.step(
        "P10-SEC-08-ban-write",
        us="US-01",
        sc="SC-01-06",
        desc="封禁用户登录仍可用但全部业务写操作被拒绝；本人收藏等只读数据保留",
        expected="写：发布/收藏/交易/IM/评论/举报/评价均 403；读：搜索/收藏/评价/通知/事项 200",
    ):
        _need(p_ban)
        ban_resp = api.post(
            f"/admin/users/{banme['id']}/ban", token=ctx.token("admin"),
            json_body={"reason": "p10 封禁写拒绝测试（自有账户，不涉及既有样本）"}, expected=200,
        ).json()
        ban_case_id = ban_resp.get("case_id")
        rec.must(ban_case_id, "封禁应返回处置沟通事项 id")
        ctx.remember_case("p10_ban_case", {"id": ban_case_id, "case_type": "account_ban", "title": "p10 封禁事项", "status": "disposed"})
        me = api.get("/auth/me", token=banme_token, expected=200).json()
        rec.must_eq(me.get("status"), "banned", "封禁后本人账户状态")
        write_failures = []
        checks = [
            ("POST", "/products", {"title": "p10 封禁用户商品", "description": "封禁用户不应发布成功", "price_cents": 100,
                                   "image_keys": [image["key"]], "tags": [{"category_id": category_id}]}),
            ("POST", f"/favorites/{p_ban['id']}", None),
            ("POST", "/trades/requests", {"product_id": p_ban["id"]}),
            ("POST", "/conversations/normal", {"peer_user_id": seller["id"]}),
            ("POST", f"/products/{p_ban['id']}/comments", {"content": "p10 封禁用户评论"}),
            ("POST", "/reports", {"target_type": "product", "target_id": p_ban["id"], "reason": "p10 封禁用户举报"}),
            ("POST", f"/trades/{t_done}/review", {"rating": 5, "content": "p10 封禁用户评价"}),
        ]
        for method, path, body in checks:
            resp = api.request(method, path, token=banme_token, json_body=body)
            if resp.status_code != 403:
                write_failures.append(f"{method} {path} → {resp.status_code}")
        rec.must(not write_failures, f"封禁用户写操作应全部 403：{write_failures}")
        with asset("product_mug.jpg").open("rb") as handle:
            upload_resp = api.post(
                "/files/upload?namespace=product", token=banme_token,
                files={"file": ("product_mug.jpg", handle, "image/jpeg")},
            )
        rec.must_eq(upload_resp.status_code, 403, "封禁用户上传图片应 403")
        read_failures = []
        for path in ("/products/search", "/favorites", "/me/reviews", "/notifications", "/me/cases", "/auth/me"):
            resp = api.get(path, token=banme_token)
            if resp.status_code != 200:
                read_failures.append(f"{path} → {resp.status_code}")
        rec.must(not read_failures, f"封禁用户只读接口应保持 200：{read_failures}")
        favorites = api.get("/favorites", token=banme_token, expected=200).json()
        rec.must(
            any(row.get("product_id") == p_ban["id"] and row.get("valid") is True for row in favorites),
            "封禁用户仍可读本人收藏且数据保留",
        )
        ctx.remember_item("ban", "p10_ban", banme["id"], "p10 封禁账户", "banned", {"case_id": ban_case_id})

    with rec.step(
        "P10-SEC-09-banned-appeal",
        us="US-08",
        sc="SC-07-06",
        desc="封禁用户仍可走处置沟通：提交申辩、读取管理员回复；管理员可回复已处置事项",
        expected="appeal 200；admin 回复 200；本人事项详情 200 且管理员消息不披露 sender_id",
    ):
        _need(ban_case_id)
        result = api.post(
            f"/me/cases/{ban_case_id}/appeal", token=banme_token,
            json_body={"content": "p10 封禁用户申辩：申请解除封禁。"}, expected=200,
        ).json()
        rec.must("申辩已提交" in str(result.get("detail")), "封禁用户申辩回执")
        api.post(
            f"/admin/cases/{ban_case_id}/messages", token=ctx.token("admin"),
            json_body={"content": "p10 管理员回复：已收到申辩，将核查。"}, expected=200,
        )
        detail = api.get(f"/me/cases/{ban_case_id}", token=banme_token, expected=200).json()
        appeals = [m for m in detail.get("messages") or [] if m.get("kind") == "appeal"]
        replies = [m for m in detail.get("messages") or [] if m.get("kind") == "reply"]
        rec.must(appeals, "本人事项应记录申辩")
        rec.must(replies, "本人事项应记录管理员回复")
        rec.must_eq(replies[0].get("sender_id"), None, "管理员回复不向用户披露 sender_id")
        cases = api.get("/me/cases", token=banme_token, expected=200).json()
        rec.must(any(row.get("id") == ban_case_id for row in cases), "封禁事项应出现在本人事项列表")

    with rec.step(
        "P10-SEC-10-unban-restore",
        us="US-01",
        sc="SC-01-06",
        desc="解除封禁后恢复原权限：可再次写业务；既有样本 qian 等最终状态不被本阶段破坏",
        expected="unban 200；/auth/me normal；写操作恢复 200；qian 状态前后一致",
    ):
        _need(p_ban, p_dup)
        resp = api.post(
            f"/admin/users/{banme['id']}/unban", token=ctx.token("admin"),
            json_body={"lift_reason": "p10 测试解除封禁，恢复原权限"}, expected=200,
        )
        rec.must("已解除" in str(resp.json().get("detail")), "解封回执")
        me = api.get("/auth/me", token=banme_token, expected=200).json()
        rec.must_eq(me.get("status"), "normal", "解封后账户状态")
        restored = api.post(f"/favorites/{p_dup['id']}", token=banme_token, expected=200)
        rec.must_eq(restored.json().get("detail"), "已收藏", "解封后收藏写操作应恢复")
        refreshed = api.get("/auth/me", token=banme_token, expected=200).json()
        rec.must("has_frozen_trade" not in refreshed or refreshed.get("has_frozen_trade") is False, "解封后无交易冻结残留")
        if qian_before is not None:
            qian_after = api.get("/auth/me", token=ctx.token("qian"), expected=200).json()
            rec.must_eq(qian_after.get("status"), qian_before.get("status"), "既有样本 qian 的最终账户状态不应被本阶段改变")
            rec.must_eq(qian_after.get("role"), qian_before.get("role"), "既有样本 qian 的角色不应被改变")

    # ===================================================================
    # 7.3 安全：分页/查询参数边界与恶意输入
    # ===================================================================
    with rec.step(
        "P10-SEC-11-param-boundaries",
        us="US-01",
        sc="SC-01-08",
        desc="分页与查询参数边界：非法页码/过大或过小 limit/非法枚举均 422",
        expected="抽查接口在参数越界或枚举非法时返回 422，不返回 200 或 5xx",
    ):
        cases = [
            ("GET", "/products/search", third_token, {"page": 0}, None),
            ("GET", "/products/search", third_token, {"page_size": 51}, None),
            ("GET", "/products/search", third_token, {"page_size": 0}, None),
            ("GET", "/products/search", third_token, {"page": "abc"}, None),
            ("GET", "/products/search", third_token, {"category_ids": "abc"}, None),
            ("GET", "/notifications", third_token, {"page": 0}, None),
            ("GET", "/notifications", third_token, {"page_size": 51}, None),
            ("GET", "/trades/mine", third_token, {"role": "owner"}, None),
            ("GET", "/me/reviews", third_token, {"type": "all"}, None),
            ("GET", "/admin/cases", ctx.token("admin"), {"status": "open"}, None),
            ("GET", "/admin/reports", ctx.token("admin"), {"status": "bad"}, None),
            ("GET", "/admin/users", ctx.token("admin"), {"status": "bad"}, None),
            ("GET", f"/conversations/{conv_trade}", seller_token, {"limit": 0}, None),
            ("GET", f"/conversations/{conv_trade}", seller_token, {"limit": 101}, None),
        ]
        failures = []
        for method, path, token, params, body in cases:
            resp = api.request(method, path, token=token, params=params, json_body=body)
            if resp.status_code != 422:
                failures.append(f"{method} {path} {params} → {resp.status_code}")
        rec.must(not failures, f"参数边界应返回 422：{failures}")

    with rec.step(
        "P10-SEC-12-malicious-input",
        us="US-02",
        sc="SC-02-01",
        desc="恶意/超长/空白/非法格式输入返回 422，不执行未授权操作或写入数据",
        expected="超长标题/描述、非法价格、空图片、超长评论、空白显示名、非法邮箱、超长举报原因/请求备注均 422；无新增商品/评论",
    ):
        products_before = api.get("/products/mine", token=seller_token, expected=200).json()
        comments_before = api.get(f"/products/{p_ban['id']}/comments", token=seller_token, expected=200).json()
        base_body = {
            "title": "p10 恶意输入测试",
            "description": "p10 恶意输入测试描述",
            "price_cents": 100,
            "image_keys": [image["key"]],
            "tags": [{"category_id": category_id}],
        }
        cases = [
            ("POST", "/products", seller_token, {**base_body, "title": "长" * 121}),
            ("POST", "/products", seller_token, {**base_body, "description": "长" * 5001}),
            ("POST", "/products", seller_token, {**base_body, "price_cents": -1}),
            ("POST", "/products", seller_token, {**base_body, "price_cents": 100_000_001}),
            ("POST", "/products", seller_token, {**base_body, "image_keys": []}),
            ("POST", f"/products/{p_ban['id']}/comments", third_token, {"content": "评" * 2001}),
            ("POST", f"/products/{p_ban['id']}/comments", third_token, {"content": ""}),
            ("PATCH", "/auth/profile", third_token, {"display_name": "   "}),
            ("PATCH", "/auth/profile", third_token, {"display_name": "名" * 65}),
            ("POST", "/auth/register/send-code", None, {"email": "not-an-email"}),
            ("POST", "/reports", third_token, {"target_type": "product", "target_id": p_ban["id"], "reason": "x" * 501}),
            ("POST", "/trades/requests", third_token, {"product_id": p_ban["id"], "note": "x" * 501}),
            ("POST", "/trades/requests", third_token, {"note": "缺少 product_id"}),
        ]
        failures = []
        for method, path, token, body in cases:
            resp = api.request(method, path, token=token, json_body=body)
            if resp.status_code != 422:
                failures.append(f"{method} {path} → {resp.status_code}")
        rec.must(not failures, f"恶意/越界输入应返回 422：{failures}")
        products_after = api.get("/products/mine", token=seller_token, expected=200).json()
        rec.must_eq(
            {product["id"] for product in products_after},
            {product["id"] for product in products_before},
            "非法输入不应创建商品",
        )
        comments_after = api.get(f"/products/{p_ban['id']}/comments", token=seller_token, expected=200).json()
        rec.must_eq(len(comments_after), len(comments_before), "非法评论输入不应写入评论")

    # ===================================================================
    # 7.3 可靠性：保存成功后重复读取结果稳定
    # ===================================================================
    with rec.step(
        "P10-REL-12-response-stability",
        us="US-06",
        sc="SC-05-08",
        desc="保存成功后重复读取结果稳定：交易/商品/通知/统计多次读取一致",
        expected="同一查询连续两次返回完全一致（状态、计数、时间字段稳定）",
    ):
        _need(t_done)
        trade_first = _trade(api, buyer1_token, t_done)
        trade_second = _trade(api, buyer1_token, t_done)
        rec.must_eq(trade_second, trade_first, "交易详情重复读取应完全一致")
        def _stable_products(products: list[dict]) -> list[dict]:
            # 图片地址是 1 小时有效的签名 URL（exp/sig 每次读取会变化），不参与“状态稳定”比较；
            # 商品身份、生命周期、审核、请求计数等业务字段必须逐项一致。
            rows = []
            for product in products:
                row = dict(product)
                row["image_keys"] = list(product.get("image_keys") or [])
                row.pop("image_urls", None)
                rows.append(row)
            return rows

        products_first = _stable_products(api.get("/products/mine", token=seller_token, expected=200).json())
        products_second = _stable_products(api.get("/products/mine", token=seller_token, expected=200).json())
        rec.must_eq(products_second, products_first, "我的商品重复读取应一致（忽略签名 URL 时效参数）")
        unread_first = api.get("/notifications/unread-count", token=buyer1_token, expected=200).json()
        unread_second = api.get("/notifications/unread-count", token=buyer1_token, expected=200).json()
        rec.must_eq(unread_second, unread_first, "未读数重复读取应一致")
        stats_first = _stats(api, ctx)
        stats_second = _stats(api, ctx)
        rec.must_eq(stats_second, stats_first, "管理统计重复读取应一致")
        me_first = api.get("/auth/me", token=banme_token, expected=200).json()
        me_second = api.get("/auth/me", token=banme_token, expected=200).json()
        rec.must_eq(me_second, me_first, "账户状态重复读取应一致（已保存结果不因重试改变）")

    rec.skip(
        "P10-REL-13-response-lost",
        us="US-06",
        sc="SC-05-08",
        desc="后台保存成功但响应丢失：可观察部分的替代验证",
        reason="真实 HTTP 链路无法在 harness 内注入响应丢失；已用重复提交幂等（REL-04/05/06）与保存后重复读取稳定（REL-12）验证可观察部分，故障注入需代理工具",
    )

    # ===================================================================
    # 7.3 可靠性：历史与逻辑删除
    # ===================================================================
    with rec.step(
        "P10-REL-14-logical-delete",
        us="US-12",
        sc="SC-12-03",
        desc="对象逻辑删除不硬删：既有举报关联保留、被删内容不物理删除、失效对象新举报应告知失败",
        expected="评论逻辑删除后仍可读（显示已删除）、原举报仍关联；对已删除评论重新举报应 400 拒绝且不新增",
    ):
        _need(p_ban)
        comment = api.post(
            f"/products/{p_ban['id']}/comments", token=third_token,
            json_body={"content": "p10 将被处置删除的评论内容"}, expected=201,
        ).json()
        comment_id = comment.get("id")
        rec.must(comment_id, "发表评论应返回 id")
        report_comment = api.post(
            "/reports", token=buyer1_token,
            json_body={"target_type": "comment", "target_id": comment_id, "reason": "p10 举报违规评论"},
            expected=201,
        ).json()
        ctx.remember_report("p10_report_comment", report_comment)
        admin_token = ctx.token("admin")
        reports = api.get("/admin/reports", token=admin_token, params={"status": "pending"}, expected=200).json()
        matched = [row for row in reports if row.get("id") == report_comment["id"]]
        rec.must_eq(len(matched), 1, "评论举报应进入共享池")
        comment_case_id = matched[0].get("case_id")
        admin_claim_case(api, ctx, comment_case_id)
        decision = api.post(
            f"/admin/reports/cases/{comment_case_id}/decision", token=admin_token,
            json_body={
                "outcome": "handled",
                "reason": "p10 认定评论违规并移除",
                "public_summary": "评论违规内容已按规则处理。",
                "actions": {"remove_content": True},
            },
            expected=200,
        ).json()
        rec.must("已认定违规" in str(decision.get("detail")), "举报处置结论回执")
        comments = api.get(f"/products/{p_ban['id']}/comments", token=seller_token, expected=200).json()
        deleted_comment = [row for row in comments if row.get("id") == comment_id]
        rec.must_eq(len(deleted_comment), 1, "逻辑删除的评论不应物理消失")
        rec.must_eq(deleted_comment[0].get("deleted"), True, "评论应标记 deleted")
        rec.must_eq(deleted_comment[0].get("content"), "该评论已删除", "已删除评论内容替换为通用文案")
        mine_reports = api.get("/reports/mine", token=buyer1_token, expected=200).json()
        rec.must(
            any(row.get("id") == report_comment["id"] and row.get("target_id") == comment_id for row in mine_reports),
            "既有举报与被删对象的关联应保留",
        )
        # 4.18：失效后才提交举报则告知失败，不新增
        resp = api.post(
            "/reports", token=seller_token,
            json_body={"target_type": "comment", "target_id": comment_id, "reason": "p10 对已删除评论重新举报"},
        )
        if resp.status_code != 400:
            # 先把缺陷候选登记到缺陷清单，再用断言保留 FAIL（缺陷候选保留 FAIL 并交接）
            rec.defect(
                "deleted_target_reportable",
                {
                    "requirement": "4.18 我的业务、编辑历史及举报：失效后才提交举报则告知失败，不新增；7.3 历史与逻辑删除",
                    "repro": "管理员对评论举报 decision handled + remove_content=true 逻辑删除评论后，"
                             "另一用户 POST /api/v1/reports {target_type:comment,target_id:<已删评论>}",
                    "expected": "400 举报对象不存在或已失效，无法提交举报；不新增举报/事项",
                    "actual": f"HTTP {resp.status_code}，{resp.text[:300]}",
                    "code": "backend/app/api/v1/reports.py:28-39 _target_exists（comment/review 未校验 deleted_at）",
                    "sample": {"comment_id": comment_id, "case_id": comment_case_id},
                },
            )
        rec.must_eq(
            resp.status_code,
            400,
            "对已逻辑删除评论重新举报应返回 400 告知失败（4.18）；"
            f"实际 HTTP {resp.status_code}，响应 {resp.text[:300]}。"
            "缺陷候选：reports.py:28-39 _target_exists 对 comment/review 只判存在不判 deleted_at，"
            "已逻辑删除对象仍可被新举报（4.18 要求失效后新举报失败且不新增）",
        )

    # ===================================================================
    # 收尾：既有样本 qian 状态守卫（若在 ctx 中）
    # ===================================================================
    ctx.note(
        "p10 完成：并发接受（恰一成功）、重复提交/评价/举报/认领幂等或拒绝、旧状态提交拒绝且无副作用、"
        "未登录 401、交易/会话/收藏/事项越权拒绝、非认领管理员拒绝、封禁写拒绝与解封恢复、"
        "分页/参数/恶意输入 422、保存后重复读取稳定均用真实接口核对；响应丢失与故障注入记为 SKIP。"
    )
