"""[p07] 评价、举报、认领与封禁（US-07、US-08；SC-07；关联 SC-06-03）。

覆盖范围：
- US-07 评价：完成交易双方互评（每方每笔唯一）、重复/未完成/非参与方拒绝、我的评价
  发表/收到归属、商品页不公开、商品下架后仍可读取本人评价、无修改删除入口、封禁拒绝
  新增评价/举报而读取保留。
- US-07 举报：product/comment/message/user 至少四类目标、证据图 namespace=report 上传
  并由签名 URL 读回、同用户同对象未结在原事项补充、失效对象拒绝、结案后归档语义。
- US-08 治理：共享池认领（唯一认领人）、未认领事项禁止访问、问询→说明→回复、
  结论（无法认定/认定违规并处置）、匿名公开结果与举报人通知、受影响者通知与申辩、
  管理员回复。
- 违规样本：qian「违规账号商品」举报→认定违规→restrict_display+ban_user，最终保持
  banned 且商品 display_restricted 保留；zhao「违规代写商品」撤展→直接封禁→申诉→
  解封（/admin/users/{id}/unban）→ /admin/products/{id}/restore-display，收藏先失效
  再自动恢复有效（D-44/TR-10）。
- 封禁联动（DT-03/D-52/D-51）：其待接受请求按「相关账户被封禁」关闭并归档分支、通知
  双方且解封不重开；其进行中且已单方确认的交易被冻结并暂停等待计时，解封后按剩余
  时间续算。
- 事项状态样本：待处理（未认领）、处理中（已认领且已问询）与已处置并存，封禁事项留痕。

证据边界：本阶段全部业务动作（评价、举报、认领、问询、决策、处置、封禁/解封、
restore-display、交易冻结/解冻）均通过真实运行后端的 HTTP 接口完成；本阶段不直接
读写数据库，也不使用任何时间加速。交易计时暂停/续算由真实服务在封禁/解封链路中完成
（单方确认 7 天超时的时间加速与真实后台扫描验证在 p08）。
"""

from __future__ import annotations

from e2e_support import (
    admin_case_detail,
    admin_claim_case,
    admin_list_cases,
    download_file,
    ensure_account,
    upload_image,
)

PHASE_ID = "p07"

# 种子账号（真实种子库已存在；独立运行时若缺失则尝试注册/登录）
SEED_ACCOUNTS = [
    ("admin", "admin@campus.edu", "admin123456", "平台管理员"),
    ("zhang", "zhang@campus.edu", "secret123", "张同学"),
    ("li", "li@campus.edu", "secret123", "李同学"),
    ("wang", "wang@campus.edu", "secret123", "王同学"),
]
# 本阶段业务账号（按真实注册验证码流程创建；已存在则登录复用）
NEW_ACCOUNTS = [
    ("chen", "chen@campus.edu", "secret123", "陈同学"),
    ("liu", "liu@campus.edu", "secret123", "刘同学"),
    ("zhao", "zhao@campus.edu", "secret123", "赵同学"),
    ("qian", "qian@campus.edu", "secret123", "钱同学"),
    ("fang", "fang@campus.edu", "secret123", "方同学"),
]

AGREEMENT = {
    "delivery_time": "2026-11-01 12:00",
    "delivery_location": "三食堂门口",
    "delivery_method": "当面自提",
    "amount_cents": 5000,
    "payment_method": "微信",
    "payment_timing": "当面支付",
}
LOCKING = ("in_progress", "disputed", "abnormal")


# ---------------------------------------------------------------------------
# 基础辅助
# ---------------------------------------------------------------------------
def _ensure_accounts(api, ctx) -> None:
    for key, email, password, name in SEED_ACCOUNTS + NEW_ACCOUNTS:
        ensure_account(api, ctx, key, email, name, password=password)


def _active_category(api, ctx, preferred: str = "电子产品") -> int:
    """读取真实分类（登录用户可读），优先返回指定主名；缺失时取任一 active 分类。"""
    cats = api.get("/categories", token=ctx.token("chen"), expected=200).json()
    for cat in cats:
        if cat.get("name") == preferred and cat.get("status") == "active":
            return cat["id"]
    for cat in cats:
        if cat.get("status") == "active":
            return cat["id"]
    raise AssertionError("当前没有任何可用分类，无法发布商品")


def _upload_asset(api, ctx, token: str, asset_name: str, namespace: str, key: str) -> dict:
    data = upload_image(api, token, asset_name, namespace=namespace)
    ctx.remember_item(
        "file", key, data["key"], f"{namespace}:{asset_name}", namespace, {"url": data["url"]}
    )
    return data


def _pending_product_case(api, ctx, product_id: int) -> dict:
    cases = admin_list_cases(api, ctx, status="pending", case_type="product_review")
    for case in cases:
        if case.get("product_id") == product_id:
            return case
    raise AssertionError(f"共享池中没有商品 #{product_id} 的待审核事项")


def _approve_product(api, ctx, product_id: int) -> None:
    case = _pending_product_case(api, ctx, product_id)
    admin_claim_case(api, ctx, case["id"])
    api.post(
        f"/admin/products/cases/{case['id']}/review",
        token=ctx.token("admin"),
        json_body={"result": "approved"},
        expected=200,
    )


def _publish_listed(api, ctx, seller: str, product_key: str, title: str, price: int,
                    asset_name: str, category_id: int,
                    description: str = "真实接口构造的阶段样本商品") -> dict:
    """真实上传图片→发布（待审核）→管理员认领并审核通过→在售。"""
    token = ctx.token(seller)
    image = _upload_asset(api, ctx, token, asset_name, "product", f"image_{product_key}")
    product = api.post(
        "/products",
        token=token,
        json_body={
            "title": title,
            "description": description,
            "price_cents": price,
            "image_keys": [image["key"]],
            "tags": [{"category_id": category_id}],
        },
        expected=200,
    ).json()
    _approve_product(api, ctx, product["id"])
    product = api.get(f"/products/{product['id']}", token=token, expected=200).json()
    ctx.remember_product(product_key, product, seller, state=product["status"])
    return product


def _ensure_listed_product(api, ctx, product_key: str, seller: str, title: str, price: int,
                           asset_name: str, category_id: int) -> dict:
    """复用 ctx 中已有商品（真实审核链路创建）；不可用时用真实接口重新构造。"""
    existing = ctx.products.get(product_key)
    if existing and existing.get("id"):
        token = ctx.token(seller)
        resp = api.get(f"/products/{existing['id']}", token=token)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "listed" and not data.get("display_restricted"):
                ctx.remember_product(product_key, data, seller, state="listed")
                return data
            if data.get("status") == "delisted":
                relist = api.post(f"/products/{data['id']}/relist", token=token)
                if relist.status_code == 200 and relist.json().get("status") == "listed":
                    data = relist.json()
                    ctx.remember_product(product_key, data, seller, state="listed")
                    return data
            if data.get("status") == "pending_review":
                _approve_product(api, ctx, data["id"])
                data = api.get(f"/products/{data['id']}", token=token, expected=200).json()
                if data.get("status") == "listed":
                    ctx.remember_product(product_key, data, seller, state="listed")
                    return data
    return _publish_listed(api, ctx, seller, product_key, title, price, asset_name, category_id)


def _trade_or_none(api, ctx, tid: int, viewer: str) -> dict | None:
    resp = api.get(f"/trades/{tid}", token=ctx.token(viewer))
    if resp.status_code == 200:
        return resp.json()
    return None


def _trade(api, ctx, tid: int, viewer: str) -> dict:
    return api.get(f"/trades/{tid}", token=ctx.token(viewer), expected=200).json()


def _create_request(api, ctx, buyer: str, seller: str, product_id: int, trade_key: str,
                    note: str | None = None) -> int:
    body = {"product_id": product_id}
    if note:
        body["note"] = note
    tid = api.post("/trades/requests", token=ctx.token(buyer), json_body=body, expected=200).json()["id"]
    ctx.remember_trade(trade_key, {"id": tid}, buyer, seller, state="pending_acceptance")
    return tid


def _accept(api, ctx, tid: int, seller: str) -> None:
    api.post(f"/trades/{tid}/accept", token=ctx.token(seller), expected=200)


def _agree(api, ctx, tid: int, proposer: str, confirmer: str) -> None:
    aid = api.post(
        f"/trades/{tid}/agreements", token=ctx.token(proposer), json_body=AGREEMENT, expected=200
    ).json()["id"]
    api.post(f"/trades/{tid}/agreements/{aid}/confirm", token=ctx.token(confirmer), expected=200)


def _confirm_completion(api, ctx, tid: int, user: str) -> None:
    api.post(f"/trades/{tid}/confirmations", token=ctx.token(user), json_body={}, expected=200)


def _ensure_completed_trade(api, ctx, trade_key: str, buyer: str, seller: str,
                            product_key: str, product_args: tuple) -> tuple[int, dict]:
    """复用 ctx 中同一 key 的已完成交易；否则在 listed 商品上真实走完交易闭环。"""
    existing = ctx.trades.get(trade_key)
    if existing and existing.get("id"):
        data = _trade_or_none(api, ctx, int(existing["id"]), buyer)
        if data is not None and data.get("status") == "completed":
            ctx.remember_trade(trade_key, {"id": data["id"]}, buyer, seller, state="completed")
            return int(data["id"]), data
    product = _ensure_listed_product(api, ctx, product_key, seller, *product_args)
    tid = _create_request(api, ctx, buyer, seller, product["id"], trade_key)
    _accept(api, ctx, tid, seller)
    _agree(api, ctx, tid, buyer, seller)
    _confirm_completion(api, ctx, tid, buyer)
    _confirm_completion(api, ctx, tid, seller)
    data = _trade(api, ctx, tid, buyer)
    ctx.remember_trade(trade_key, {"id": tid}, buyer, seller, state=data["status"])
    return tid, data


def _ensure_single_confirm_trade(api, ctx, trade_key: str, buyer: str, seller: str,
                                 product_factory) -> tuple[int, int]:
    """确保存在“进行中 + 已确认约定 + 仅一方完成确认”的交易，返回 (trade_id, product_id)。

    优先复用 ctx 中同 key 的交易（例如 p05 已构造的封禁联动样本）；不可用时用真实接口新建。
    """
    existing = ctx.trades.get(trade_key)
    if existing and existing.get("id"):
        data = _trade_or_none(api, ctx, int(existing["id"]), buyer)
        if data is not None and data.get("status") in LOCKING:
            if data["status"] != "in_progress":
                return int(data["id"]), int(data["product_id"])
            if data.get("frozen") and not (data.get("my_confirmed") or data.get("other_party_confirmed")):
                ctx.note(f"交易 #{data['id']} 已冻结且无当前确认，p07 另建样本交易用于封禁冻结验证。")
            else:
                if not data.get("frozen") and data.get("agreement_stage") == "awaiting_agreement":
                    pending = data.get("pending_agreement")
                    if pending:
                        confirmer = seller if pending["proposer_id"] == ctx.accounts[buyer]["id"] else buyer
                        api.post(
                            f"/trades/{data['id']}/agreements/{pending['id']}/confirm",
                            token=ctx.token(confirmer), expected=200,
                        )
                    else:
                        _agree(api, ctx, data["id"], buyer, seller)
                    data = _trade(api, ctx, data["id"], buyer)
                if not data.get("frozen") and not (data.get("my_confirmed") or data.get("other_party_confirmed")):
                    _confirm_completion(api, ctx, data["id"], buyer)
                return int(data["id"]), int(data["product_id"])
    product = product_factory()
    tid = _create_request(api, ctx, buyer, seller, product["id"], trade_key)
    _accept(api, ctx, tid, seller)
    _agree(api, ctx, tid, buyer, seller)
    _confirm_completion(api, ctx, tid, buyer)
    ctx.remember_trade(trade_key, {"id": tid}, buyer, seller, state="in_progress")
    return tid, int(product["id"])


def _notifications(api, token: str, *, pages: int = 3, page_size: int = 50) -> list[dict]:
    items: list[dict] = []
    for page in range(1, pages + 1):
        data = api.get(
            "/notifications", token=token, params={"page": page, "page_size": page_size}, expected=200
        ).json()
        items.extend(data.get("items") or [])
        if len(data.get("items") or []) < page_size:
            break
    return items


def _notif(items: list[dict], ntype: str, link_id: int | None = None) -> list[dict]:
    return [n for n in items if n.get("type") == ntype and (link_id is None or n.get("link_id") == link_id)]


def _report_case_id(api, ctx, report_id: int) -> int:
    rows = api.get(
        "/admin/reports", token=ctx.token("admin"), params={"status": "all"}, expected=200
    ).json()
    for row in rows:
        if row.get("id") == report_id:
            case_id = row.get("case_id")
            if case_id:
                return int(case_id)
    cases = admin_list_cases(api, ctx, status="all", case_type="report")
    for case in cases:
        if case.get("report_id") == report_id:
            return int(case["id"])
    raise AssertionError(f"未找到举报 #{report_id} 对应的事项")


def _create_report(api, token: str, target_type: str, target_id: int, reason: str,
                   *, detail: str | None = None, evidence_keys: list[str] | None = None) -> dict:
    body = {"target_type": target_type, "target_id": target_id, "reason": reason}
    if detail:
        body["detail"] = detail
    if evidence_keys:
        body["evidence_keys"] = evidence_keys
    return api.post("/reports", token=token, json_body=body, expected=201).json()


def _remember_report(ctx, key: str, data: dict, state: str) -> dict:
    """登记举报对象并记录当前状态（e2e_support.Ctx.remember_report 不支持 state 关键字）。"""
    payload = dict(data)
    payload["status"] = state
    return ctx.remember_report(key, payload)


def _claim(api, ctx, case_id: int) -> None:
    admin_claim_case(api, ctx, case_id)


def _inquiry(api, ctx, case_id: int, content: str) -> None:
    api.post(f"/admin/cases/{case_id}/inquiry", token=ctx.token("admin"),
             json_body={"content": content}, expected=200)


def _reply(api, ctx, case_id: int, content: str) -> None:
    api.post(f"/admin/cases/{case_id}/messages", token=ctx.token("admin"),
             json_body={"content": content}, expected=200)


def _statement(api, token: str, case_id: int, content: str) -> None:
    api.post(f"/me/cases/{case_id}/statement", token=token,
             json_body={"content": content}, expected=200)


def _my_cases(api, token: str) -> list[dict]:
    return api.get("/me/cases", token=token, expected=200).json()


def _my_case(api, token: str, case_id: int) -> dict:
    return api.get(f"/me/cases/{case_id}", token=token, expected=200).json()



def _dedupe_inventory(ctx) -> None:
    """同一 (kind,key) 多次登记时保留最后一条，避免报告数据清单重复计数。"""
    latest: dict[tuple, int] = {}
    order: list[dict] = []
    for row in ctx.inventory:
        key = (row.get("kind"), row.get("key"))
        if key in latest:
            order[latest[key]] = row
        else:
            latest[key] = len(order)
            order.append(row)
    ctx.inventory[:] = order


def _refresh_report_states(api, ctx) -> None:
    """用管理端只读举报列表刷新举报对象最终状态（保证报告数据清单状态准确）。"""
    resp = api.get("/admin/reports", token=ctx.token("admin"), params={"status": "all"})
    if resp.status_code != 200:
        return
    states = {int(row["id"]): row.get("status", "") for row in resp.json() if row.get("id") is not None}
    for row in ctx.inventory:
        if row.get("kind") == "report" and row.get("id") in states:
            row["state"] = states[row["id"]]
    for item in ctx.reports.values():
        report_id = item.get("id")
        if report_id in states:
            item["status"] = states[report_id]

# ---------------------------------------------------------------------------
# 阶段主流程
# ---------------------------------------------------------------------------
def run(ctx, api, rec):  # noqa: ANN001
    _ensure_accounts(api, ctx)
    admin = ctx.account("admin")
    assert admin is not None
    category_id = _active_category(api, ctx)

    # =====================================================================
    # 1. US-07 评价：完成交易双向评价 → 唯一/拒绝分支 → 我的评价 → 下架可读
    # =====================================================================
    tid_completed, trade_completed = _ensure_completed_trade(
        api, ctx, "t_completed", "chen", "liu", "p_completed",
        ("宿舍电煮锅（阶段评价样本）", 5000, "product_lamp.jpg", category_id),
    )
    p_completed_id = int(trade_completed["product_id"])
    p_inprogress = _ensure_listed_product(
        api, ctx, "p_review_inprogress", "liu", "蓝牙机械键盘（阶段未完成样本）", 8000,
        "product_second2.jpg", category_id,
    )
    existing_inprogress = ctx.trades.get("t_review_inprogress")
    tid_inprogress: int | None = None
    if existing_inprogress and existing_inprogress.get("id"):
        data = _trade_or_none(api, ctx, int(existing_inprogress["id"]), "chen")
        if data is not None and data.get("status") == "in_progress":
            tid_inprogress = int(data["id"])
    if tid_inprogress is None:
        tid_inprogress = _create_request(api, ctx, "chen", "liu", p_inprogress["id"],
                                         "t_review_inprogress", note="阶段未完成交易")
        _accept(api, ctx, tid_inprogress, "liu")
    ctx.remember_trade("t_review_inprogress", {"id": tid_inprogress}, "chen", "liu", state="in_progress")

    with rec.step(
        "US-07-AC-01_双方互评",
        us="US-07", sc="SC-07-01",
        desc="已完成交易双方各提交一条 1—5 分及文字评价",
        expected="买卖双方各 201 保存一条评价（评价人=本人、被评价人=对方）",
    ):
        buyer_review = api.post(
            f"/trades/{tid_completed}/review", token=ctx.token("chen"),
            json_body={"rating": 5, "content": "交付顺利，物超所值"}, expected=201,
        ).json()
        seller_review = api.post(
            f"/trades/{tid_completed}/review", token=ctx.token("liu"),
            json_body={"rating": 4, "content": "守时友好"}, expected=201,
        ).json()
        ctx.remember_item("review", "review_buyer_to_seller", buyer_review.get("id"),
                          f"评价#{buyer_review.get('id')} chen→liu", "published", {"rating": 5})
        ctx.remember_item("review", "review_seller_to_buyer", seller_review.get("id"),
                          f"评价#{seller_review.get('id')} liu→chen", "published", {"rating": 4})
        ctx.items["review_ids"] = {"buyer": buyer_review["id"], "seller": seller_review["id"]}

    with rec.step(
        "US-07-AC-01_唯一评价",
        us="US-07", sc="SC-07-03",
        desc="同一方对同一笔交易重复提交评价",
        expected="409 拒绝，不产生第二条评价",
    ):
        resp = api.post(f"/trades/{tid_completed}/review", token=ctx.token("liu"),
                        json_body={"rating": 1, "content": "重复"}, expected=409)
        rec.must("已评价" in (resp.json().get("detail") or ""), "重复评价提示文案")

    with rec.step(
        "US-07-AC-01_未完成拒绝",
        us="US-07", sc="SC-07-02",
        desc="交易未完成时提交评价",
        expected="409 仅已完成交易可评价",
    ):
        resp = api.post(f"/trades/{tid_inprogress}/review", token=ctx.token("chen"),
                        json_body={"rating": 5}, expected=409)
        rec.must("已完成" in (resp.json().get("detail") or ""), "未完成交易拒绝文案")

    with rec.step(
        "US-07-AC-01_非参与方",
        us="US-07", sc="SC-07-03",
        desc="非交易参与方（无资格代他人评价）提交评价",
        expected="404 交易不存在（防枚举）",
    ):
        api.post(f"/trades/{tid_completed}/review", token=ctx.token("zhang"),
                 json_body={"rating": 5}, expected=404)

    with rec.step(
        "US-07-AC-01_我的评价归属",
        us="US-07", sc="SC-07-01",
        desc="双方在 /me/reviews 按发表/收到查看，关联交易；商品页不公开评价",
        expected="双方 published/received 各含本笔；other_party_name 正确；trade_status=completed；商品详情无评价字段",
    ):
        chen_pub = api.get("/me/reviews", token=ctx.token("chen"), expected=200).json()
        chen_recv = api.get("/me/reviews", token=ctx.token("chen"),
                            params={"type": "received"}, expected=200).json()
        liu_pub = api.get("/me/reviews", token=ctx.token("liu"), expected=200).json()
        liu_recv = api.get("/me/reviews", token=ctx.token("liu"),
                           params={"type": "received"}, expected=200).json()
        mine_pub = next(x for x in chen_pub if x["trade_id"] == tid_completed)
        mine_recv = next(x for x in chen_recv if x["trade_id"] == tid_completed)
        rec.must_eq(mine_pub["direction"], "published", "chen 发表方向")
        rec.must_eq(mine_recv["direction"], "received", "chen 收到方向")
        rec.must_eq(mine_pub["other_party_name"], "刘同学", "发表-对方显示名")
        rec.must_eq(mine_recv["other_party_name"], "刘同学", "收到-对方显示名")
        rec.must_eq(mine_pub["trade_status"], "completed", "评价关联交易状态")
        rec.must_eq(int(mine_pub["rating"]), 5, "发表评分")
        rec.must_eq(mine_pub["content"], "交付顺利，物超所值", "发表文字")
        rec.must(any(x["trade_id"] == tid_completed for x in liu_pub), "liu 发表列表含本笔")
        rec.must(any(x["trade_id"] == tid_completed for x in liu_recv), "liu 收到列表含本笔")
        product_detail = api.get(f"/products/{p_completed_id}", token=ctx.token("chen"), expected=200).json()
        rec.must(not any(k in product_detail for k in ("reviews", "rating", "my_review", "review_list")),
                 "商品详情不应暴露评价内容")

    with rec.step(
        "US-07-AC-01_下架仍可读",
        us="US-07", sc="SC-07-01",
        desc="商品下架不影响本人对既往完成交易评价的读取",
        expected="下架成功；/me/reviews 双方仍返回本笔评价（随后按卖家资格恢复上架保持样本）",
    ):
        product = api.get(f"/products/{p_completed_id}", token=ctx.token("liu"), expected=200).json()
        delisted = False
        if product["status"] == "listed":
            resp = api.post(f"/products/{p_completed_id}/delist", token=ctx.token("liu"), expected=200)
            rec.must_eq(resp.json()["status"], "delisted", "下架后商品状态")
            delisted = True
        chen_pub = api.get("/me/reviews", token=ctx.token("chen"), expected=200).json()
        liu_recv = api.get("/me/reviews", token=ctx.token("liu"),
                           params={"type": "received"}, expected=200).json()
        rec.must(any(x["trade_id"] == tid_completed for x in chen_pub), "下架后买方发表评价仍可读")
        rec.must(any(x["trade_id"] == tid_completed for x in liu_recv), "下架后卖方收到评价仍可读")
        current = api.get(f"/products/{p_completed_id}", token=ctx.token("liu"), expected=200).json()
        if current["status"] == "delisted":
            relisted = api.post(f"/products/{p_completed_id}/relist", token=ctx.token("liu"), expected=200)
            rec.must_eq(relisted.json()["status"], "listed", "恢复上架（保持样本最终在售）")
            ctx.update_product("p_completed", state="listed")

    with rec.step(
        "US-07-AC-02_不可修改删除",
        us="US-07", sc="SC-07-03",
        desc="用户不能自行修改或删除已提交评价（无对应接口）",
        expected="PATCH / DELETE /trades/{id}/review 均为 405 Method Not Allowed",
    ):
        rec.must_eq(api.patch(f"/trades/{tid_completed}/review", token=ctx.token("chen"),
                              json_body={"rating": 1}).status_code, 405, "修改评价入口")
        rec.must_eq(api.delete(f"/trades/{tid_completed}/review", token=ctx.token("chen")).status_code,
                    405, "删除评价入口")

    # qian 的完成交易样本：用于封禁后“拒绝新增评价”验证（读取仍保留）
    tid_qian_review, _ = _ensure_completed_trade(
        api, ctx, "t_qian_review", "qian", "liu", "p_qian_review",
        ("收纳箱（阶段封禁评价样本）", 3000, "product_mug.jpg", category_id),
    )
    with rec.step(
        "US-07-AC-01_封禁前评价基线",
        us="US-07", sc="SC-07-07",
        desc="封禁前 qian 作为已完成交易买方提交评价（封禁后用于拒绝分支对照）",
        expected="201 保存评价",
    ):
        resp = api.post(f"/trades/{tid_qian_review}/review", token=ctx.token("qian"),
                        json_body={"rating": 5, "content": "封禁前评价基线"}, expected=201)
        ctx.remember_item("review", "review_qian_baseline", resp.json().get("id"),
                          f"评价#{resp.json().get('id')} qian→liu", "published", {"rating": 5})

    # =====================================================================
    # 2. 举报基础：四类目标 + 证据图 + 补充说明 + 失效对象
    # =====================================================================
    p_report_target = _ensure_listed_product(
        api, ctx, "p_report_target", "liu", "举报目标样本（阶段）", 6000,
        "product_textbook.jpg", category_id,
    )
    with rec.step(
        "US-07-AC-03_四类举报目标",
        us="US-07", sc="SC-07-04",
        desc="真实接口提交 product/comment/message/user 四类举报目标，证据图 namespace=report 上传并读回",
        expected="四类目标均 201 进入待处理共享池；签名 URL 证据图 200 可读",
    ):
        # product 目标：qian 违规商品（后续处置），先收藏供 D-44 失效→恢复验证
        p_qian_violation = _ensure_listed_product(
            api, ctx, "p_restricted_stays", "qian", "游戏账号租售（阶段违规样本）", 20000,
            "product_second2.jpg", category_id,
        )
        ctx.items["p_qian_violation_id"] = p_qian_violation["id"]
        fav = api.post(f"/favorites/{p_qian_violation['id']}", token=ctx.token("chen"), expected=200).json()
        ctx.remember_item("favorite", "favorite_qian_violation", fav.get("favorite_id"),
                          f"收藏商品#{p_qian_violation['id']}", "active",
                          {"product_id": p_qian_violation["id"]})
        evidence = _upload_asset(api, ctx, ctx.token("chen"), "evidence_listing.jpg", "report",
                                 "evidence_qian_product")
        download = download_file(api, evidence["url"])
        rec.must_eq(download.status_code, 200, "证据图签名 URL 读回")
        rec.must(len(download.content) > 1000, "证据图内容非空")
        report_product = _create_report(
            api, ctx.token("chen"), "product", p_qian_violation["id"], "账号租售属于禁发范围",
            detail="商品标题与描述均涉及游戏账号租售", evidence_keys=[evidence["key"]],
        )
        _remember_report(ctx, "r_qian_product", {"id": report_product["id"], "target_type": "product",
                                               "reason": "账号租售属于禁发范围"}, "pending")
        ctx.items["r_qian_product_id"] = report_product["id"]
        ctx.items["evidence_qian_key"] = evidence["key"]
        ctx.items["evidence_qian_url"] = evidence["url"]
        # comment 目标：fang 在目标商品下的评论（独立账号避免评论频控干扰）
        comment = api.post(f"/products/{p_report_target['id']}/comments", token=ctx.token("fang"),
                           json_body={"content": "阶段样本：不当评论内容"}, expected=201).json()
        ctx.remember_item("comment", "comment_report_target", comment["id"],
                          f"评论#{comment['id']} 商品#{p_report_target['id']}", "active",
                          {"product_id": p_report_target["id"]})
        report_comment = _create_report(api, ctx.token("chen"), "comment", comment["id"], "评论内容不当")
        _remember_report(ctx, "r_comment", {"id": report_comment["id"], "target_type": "comment",
                                          "reason": "评论内容不当"}, "pending")
        ctx.items["r_comment_id"] = report_comment["id"]
        ctx.items["comment_id"] = comment["id"]
        # message 目标：进行中交易分支内真实文本消息
        branch = _trade(api, ctx, tid_inprogress, "chen")
        msg = api.post(f"/conversations/{branch['conversation_id']}/messages",
                       token=ctx.token("chen"), json_body={"content": "阶段样本：交易分支消息"},
                       expected=200).json()
        report_message = _create_report(api, ctx.token("wang"), "message", msg["id"], "交易消息内容不当")
        _remember_report(ctx, "r_message", {"id": report_message["id"], "target_type": "message",
                                          "reason": "交易消息内容不当"}, "pending")
        ctx.items["r_message_id"] = report_message["id"]
        ctx.items["message_id"] = msg["id"]
        # user 目标：对 zhao 的用户举报（后续以无法认定结论收尾）
        report_user = _create_report(api, ctx.token("wang"), "user", ctx.accounts["zhao"]["id"],
                                     "疑似违规用户")
        _remember_report(ctx, "r_user", {"id": report_user["id"], "target_type": "user",
                                       "reason": "疑似违规用户"}, "pending")
        ctx.items["r_user_id"] = report_user["id"]

    with rec.step(
        "US-07-AC-04_未结补充说明",
        us="US-07", sc="SC-07-04",
        desc="同用户同对象仍有未结举报时再次举报，应在原事项补充说明/证据",
        expected="201 返回原举报 existing_report_id；补充说明 200；/reports/mine 可见补充",
    ):
        again = api.post("/reports", token=ctx.token("chen"), json_body={
            "target_type": "product", "target_id": ctx.items["p_qian_violation_id"],
            "reason": "同一对象再次举报"}, expected=201).json()
        rec.must_eq(int(again.get("existing_report_id") or 0), int(ctx.items["r_qian_product_id"]),
                    "重复举报返回原举报 id")
        evidence2 = _upload_asset(api, ctx, ctx.token("chen"), "evidence_chat.jpg", "report",
                                  "evidence_qian_supplement")
        rec.must_eq(download_file(api, evidence2["url"]).status_code, 200, "补充证据图读回")
        api.post(f"/reports/{ctx.items['r_qian_product_id']}/supplements", token=ctx.token("chen"),
                 json_body={"content": "补充：商品描述截图已上传", "evidence_keys": [evidence2["key"]]},
                 expected=200)
        mine = api.get("/reports/mine", token=ctx.token("chen"), expected=200).json()
        row = next(x for x in mine if x["id"] == ctx.items["r_qian_product_id"])
        rec.must(any("补充" in s["content"] for s in row.get("supplements") or []),
                 "原举报含补充说明记录")
        ctx.items["evidence_qian_supplement_key"] = evidence2["key"]

    with rec.step(
        "US-07-AC-06_失效对象拒绝",
        us="US-07", sc="SC-07-11",
        desc="举报不存在的对象（已失效）",
        expected="400 举报对象不存在或已失效，不新建",
    ):
        resp = api.post("/reports", token=ctx.token("chen"),
                        json_body={"target_type": "comment", "target_id": 999999, "reason": "失效对象"},
                        expected=400)
        rec.must("不存在" in (resp.json().get("detail") or ""), "失效对象拒绝文案")

    # =====================================================================
    # 3. 共享池认领与问询→说明→回复（comment 举报，认定违规移除评论）
    # =====================================================================
    case_comment = _report_case_id(api, ctx, ctx.items["r_comment_id"])
    ctx.items["case_comment_id"] = case_comment
    with rec.step(
        "US-08-AC-01_认领唯一性",
        us="US-08", sc="SC-07-10",
        desc="举报进入共享池后：未认领事项详情拒绝、认领成功、重复认领冲突、不存在事项 404",
        expected="未认领 admin 详情 403；首次 claim 200；重复 claim 409；不存在事项 404；认领后详情 processing",
    ):
        unclaimed = api.get(f"/admin/cases/{case_comment}", token=ctx.token("admin"))
        rec.must_eq(unclaimed.status_code, 403, "未认领事项详情拒绝")
        claimed = admin_claim_case(api, ctx, case_comment)
        rec.must_eq(int(claimed["id"]), case_comment, "认领事项 id")
        rec.must_eq(api.post(f"/admin/cases/{case_comment}/claim", token=ctx.token("admin"),
                             json_body={}).status_code, 409, "重复认领冲突")
        rec.must_eq(api.post("/admin/cases/999999/claim", token=ctx.token("admin"),
                             json_body={}).status_code, 404, "不存在事项认领")
        detail = admin_case_detail(api, ctx, case_comment)
        rec.must_eq(detail["status"], "processing", "认领后事项状态")
        rec.must_eq(detail["claimed_by_id"], ctx.accounts["admin"]["id"], "认领人")
        rec.must_eq((detail.get("report") or {}).get("target_type"), "comment", "事项关联举报目标类型")

    with rec.step(
        "US-08-AC-01_越权拒绝",
        us="US-08", sc="SC-07-10",
        desc="普通用户访问管理端事项/认领/处置接口，未登录访问",
        expected="普通用户 403，未登录 401",
    ):
        rec.must_eq(api.get("/admin/cases", token=ctx.token("chen")).status_code, 403, "普通用户读管理事项")
        rec.must_eq(api.post(f"/admin/cases/{case_comment}/claim", token=ctx.token("chen"),
                             json_body={}).status_code, 403, "普通用户认领事项")
        rec.must_eq(api.get("/admin/cases").status_code, 401, "未登录读管理事项")
        rec.must_eq(api.get(f"/admin/cases/{case_comment}").status_code, 401, "未登录读事项详情")

    with rec.step(
        "US-08-AC-05_问询说明回复",
        us="US-08", sc="SC-07-12",
        desc="管理员发起问询→被询问用户经 /me/cases 提交说明→管理员回复",
        expected="问询/说明/回复均 200；问询不改变事项状态、举报状态与账户状态；has_inquiry=true",
    ):
        _inquiry(api, ctx, case_comment, "请说明该评论的发布背景")
        _statement(api, ctx.token("fang"), case_comment, "说明：该评论仅为调侃，无恶意")
        _reply(api, ctx, case_comment, "已收到说明，将结合证据核实")
        detail = admin_case_detail(api, ctx, case_comment)
        kinds = [m["kind"] for m in detail["messages"]]
        rec.must("inquiry" in kinds and "statement" in kinds and "reply" in kinds,
                 f"事项沟通消息类型：{kinds}")
        rec.must_eq(detail["status"], "processing", "问询阶段事项状态保持不变")
        rec.must_eq(detail["report"]["status"], "pending", "问询阶段举报状态保持不变")
        rec.must_eq(api.get("/auth/me", token=ctx.token("fang"), expected=200).json()["status"],
                    "normal", "问询不改变账户状态")
        user_case = _my_case(api, ctx.token("fang"), case_comment)
        rec.must_eq(user_case["has_inquiry"], True, "用户侧事项 has_inquiry")
        rec.must(all(m.get("sender_id") is None for m in user_case["messages"]
                     if m["kind"] in ("inquiry", "reply")), "用户侧不披露管理员 sender_id")

    with rec.step(
        "SC-07-13_内容移除",
        us="US-08", sc="SC-07-13",
        desc="认定评论违规并执行内容移除：仅移除违规评论、通知作者与举报人、匿名公开结果",
        expected="decision handled 200；评论逻辑删除；作者收到处置通知；举报人收到结果通知且 public_result 已确认",
    ):
        decision = api.post(f"/admin/reports/cases/{case_comment}/decision", token=ctx.token("admin"),
                            json_body={
                                "outcome": "handled",
                                "reason": "评论含不当内容",
                                "public_summary": "已认定评论违规并移除",
                                "basis": "BR-17/BR-26",
                                "actions": {"remove_content": True},
                            }, expected=200)
        rec.must("认定违规" in (decision.json().get("detail") or ""), "决策成功文案")
        comments = api.get(f"/products/{p_report_target['id']}/comments",
                           token=ctx.token("fang"), expected=200).json()
        target = next(x for x in comments if x["id"] == ctx.items["comment_id"])
        rec.must_eq(target["deleted"], True, "违规评论逻辑删除")
        rec.must_eq(target["content"], "该评论已删除", "删除后内容占位")
        fang_notifs = _notifications(api, ctx.token("fang"))
        rec.must(bool(_notif(fang_notifs, "disposal", case_comment)), "评论作者收到处置通知")
        chen_notifs = _notifications(api, ctx.token("chen"))
        rec.must(bool(_notif(chen_notifs, "report_result", ctx.items["r_comment_id"])),
                 "举报人收到处理结果通知")
        row = next(x for x in api.get("/reports/mine", token=ctx.token("chen"), expected=200).json()
                   if x["id"] == ctx.items["r_comment_id"])
        rec.must_eq(row["status"], "handled", "举报状态已处置")
        rec.must_eq(row["public_result"], "已认定评论违规并移除", "匿名公开结果")
        rec.must_eq(row["result_confirmed"], True, "结果已确认")
        ctx.remember_case("case_comment", {"id": case_comment, "title": "举报事项：评论",
                                           "case_type": "report", "status": "disposed"})

    # =====================================================================
    # 4. 无实际处置（无法认定）分支 + 不主动告知被举报人
    # =====================================================================
    case_user = _report_case_id(api, ctx, ctx.items["r_user_id"])
    ctx.items["case_user_id"] = case_user
    with rec.step(
        "US-08-AC-03_无法认定",
        us="US-08", sc="SC-07-06",
        desc="证据不足：管理员认领→问询→说明→结论记录无法认定/不予处理",
        expected="unfounded 200；举报状态 unfounded、result_confirmed、public_result 写入；不向被举报人发送处置通知",
    ):
        _claim(api, ctx, case_user)
        _inquiry(api, ctx, case_user, "请说明被举报行为")
        _statement(api, ctx.token("zhao"), case_user, "说明：本人未从事被举报行为")
        _reply(api, ctx, case_user, "已收到说明")
        zhao_before = _notifications(api, ctx.token("zhao"))
        decision = api.post(f"/admin/reports/cases/{case_user}/decision", token=ctx.token("admin"),
                            json_body={
                                "outcome": "unfounded",
                                "reason": "现有证据不足以认定违规",
                                "public_summary": "依据不足，不予处理",
                                "basis": "BR-26",
                            }, expected=200)
        rec.must("不予处理" in (decision.json().get("detail") or ""), "不予处理文案")
        reporter_row = next(x for x in api.get("/reports/mine", token=ctx.token("wang"),
                                               expected=200).json()
                            if x["id"] == ctx.items["r_user_id"])
        rec.must_eq(reporter_row["status"], "unfounded", "举报状态-无法认定")
        rec.must_eq(reporter_row["public_result"], "依据不足，不予处理", "公开结果")
        rec.must(bool(_notif(_notifications(api, ctx.token("wang")), "report_result",
                             ctx.items["r_user_id"])), "举报人收到结果通知")
        zhao_after = _notifications(api, ctx.token("zhao"))
        rec.must_eq(len(_notif(zhao_after, "disposal")), len(_notif(zhao_before, "disposal")),
                    "未实际处置不主动告知被举报人")
        ctx.remember_case("case_user", {"id": case_user, "title": "举报事项：用户",
                                        "case_type": "report", "status": "disposed"})

    # =====================================================================
    # 5. qian：举报认定违规 → 撤展 + 封禁（最终保持 banned）
    # =====================================================================
    case_qian = _report_case_id(api, ctx, ctx.items["r_qian_product_id"])
    ctx.items["case_qian_id"] = case_qian
    with rec.step(
        "SC-07-05_举报不自动处置",
        us="US-08", sc="SC-07-05",
        desc="举报提交后尚未认领/核查，不自动下架或封禁",
        expected="处置前 qian 仍 normal，违规商品仍 listed 且无展示限制",
    ):
        me = api.get("/auth/me", token=ctx.token("qian"), expected=200).json()
        rec.must_eq(me["status"], "normal", "举报未处置前账户状态")
        product = api.get(f"/products/{ctx.items['p_qian_violation_id']}",
                          token=ctx.token("qian"), expected=200).json()
        rec.must_eq(product["display_restricted"], False, "举报未处置前无展示限制")
        rec.must_eq(product["status"], "listed", "举报未处置前生命周期")

    with rec.step(
        "US-08-AC-05b_问询后处置",
        us="US-08", sc="SC-07-07",
        desc="qian 违规商品举报：认领、问询、本人说明、管理员回复、认定违规并 restrict_display+ban_user",
        expected="decision 200；qian banned；商品 display_restricted=true 且 status 不变；举报 handled、公开结果",
    ):
        _claim(api, ctx, case_qian)
        detail = admin_case_detail(api, ctx, case_qian)
        rec.must_eq(detail["report"]["evidence_keys"], [ctx.items["evidence_qian_key"]],
                    "管理员可见举报证据 key")
        _inquiry(api, ctx, case_qian, "请说明账号租售商品的发布情况")
        _statement(api, ctx.token("qian"), case_qian, "说明：帮朋友代发，未获利")
        _reply(api, ctx, case_qian, "已收到说明，结合材料核实")
        decision = api.post(f"/admin/reports/cases/{case_qian}/decision", token=ctx.token("admin"),
                            json_body={
                                "outcome": "handled",
                                "reason": "账号租售属于禁发范围",
                                "public_summary": "已认定违规，暂停相关商品公开访问并封禁账户",
                                "basis": "BR-13/BR-32/TR-09",
                                "actions": {
                                    "restrict_display": True,
                                    "ban_user": True,
                                    "ban_reason": "发布禁发范围内容（账号租售）",
                                },
                            }, expected=200)
        rec.must("认定违规" in (decision.json().get("detail") or ""), "认定违规文案")
        qian_me = api.get("/auth/me", token=ctx.token("qian"), expected=200).json()
        rec.must_eq(qian_me["status"], "banned", "qian 封禁状态")
        product = api.get(f"/products/{ctx.items['p_qian_violation_id']}",
                          token=ctx.token("qian"), expected=200).json()
        rec.must_eq(product["display_restricted"], True, "违规商品展示限制")
        rec.must_eq(product["status"], "listed", "展示限制不改变生命周期状态")
        rec.must_eq(product["display_restricted_reason"] is not None, True, "展示限制原因留痕")
        ctx.update_product("p_restricted_stays", state="listed")
        rec.must(bool(_notif(_notifications(api, ctx.token("chen")), "report_result",
                             ctx.items["r_qian_product_id"])), "举报人收到举报处理结果通知")
        mine = next(x for x in api.get("/reports/mine", token=ctx.token("chen"), expected=200).json()
                    if x["id"] == ctx.items["r_qian_product_id"])
        rec.must_eq(mine["status"], "handled", "举报状态 handled")
        rec.must_eq(mine["public_result"], "已认定违规，暂停相关商品公开访问并封禁账户",
                    "匿名公开结果")
        received = api.get("/reports/received", token=ctx.token("qian"), expected=200).json()
        row = next(x for x in received if x["id"] == ctx.items["r_qian_product_id"])
        rec.must_eq(row["target_type"], "product", "我收到的举报目标类型")
        rec.must_eq(row["status"], "handled", "我收到的举报已处置")
        rec.must("reporter_id" not in row, "不披露举报人身份")
        rec.must_eq(row["disposal_reason"], "账号租售属于禁发范围", "处置原因")
        rec.must(bool(_notif(_notifications(api, ctx.token("qian")), "disposal", case_qian)),
                 "被处置人收到处置通知")
        ctx.remember_case("case_qian", {"id": case_qian, "title": "举报事项：商品",
                                        "case_type": "report", "status": "disposed"})

    with rec.step(
        "US-07-AC-07_封禁拒绝新增",
        us="US-07", sc="SC-07-07",
        desc="封禁用户拒绝新增评价与举报；既往评价读取资格保留",
        expected="qian 评价 403、举报 403；/me/reviews 仍 200 且含封禁前评价",
    ):
        review_resp = api.post(f"/trades/{tid_qian_review}/review", token=ctx.token("qian"),
                               json_body={"rating": 3}, expected=403)
        rec.must("封禁" in (review_resp.json().get("detail") or ""), "封禁评价拒绝文案")
        report_resp = api.post("/reports", token=ctx.token("qian"), json_body={
            "target_type": "product", "target_id": p_report_target["id"], "reason": "封禁期间举报"},
            expected=403)
        rec.must("封禁" in (report_resp.json().get("detail") or ""), "封禁举报拒绝文案")
        reviews = api.get("/me/reviews", token=ctx.token("qian"), expected=200).json()
        rec.must(any(x["trade_id"] == tid_qian_review for x in reviews), "封禁后仍可读取本人评价")

    with rec.step(
        "US-08-AC-05c_处置后申辩",
        us="US-08", sc="SC-07-12",
        desc="qian 从本人事项查看处置详情并提交申辩，管理员回复；申辩不自动撤销处置",
        expected="事项详情可见；appeal 200；管理员回复 200 并通知；qian 仍 banned",
    ):
        user_case = _my_case(api, ctx.token("qian"), case_qian)
        rec.must_eq(user_case["status"], "disposed", "处置后事项状态")
        rec.must_eq(user_case["conclusion"], "认定违规并处置", "处置结论")
        rec.must_eq(user_case["conclusion_reason"], "账号租售属于禁发范围", "处置原因")
        rec.must(any(m["kind"] == "inquiry" for m in user_case["messages"]), "问询与说明留痕")
        api.post(f"/me/cases/{case_qian}/appeal", token=ctx.token("qian"),
                 json_body={"content": "申辩：请求复核并解除封禁"}, expected=200)
        _reply(api, ctx, case_qian, "申辩回复：维持原处置，封禁期间可继续沟通")
        qian_notifs = _notifications(api, ctx.token("qian"))
        rec.must(bool(_notif(qian_notifs, "appeal_result", case_qian)), "申辩回复通知")
        rec.must_eq(api.get("/auth/me", token=ctx.token("qian"), expected=200).json()["status"],
                    "banned", "申辩不自动撤销处置")
        rec.must_eq(api.get(f"/me/cases/{case_qian}", token=ctx.token("chen")).status_code, 403,
                    "举报人不能因举报身份读取对方申辩内容")

    with rec.step(
        "US-07-AC-04b_结案拒绝补充",
        us="US-07", sc="SC-07-04",
        desc="原举报结案归档后拒绝补充说明",
        expected="409 该举报事项已处理归档，不再接受补充",
    ):
        resp = api.post(f"/reports/{ctx.items['r_qian_product_id']}/supplements",
                        token=ctx.token("chen"), json_body={"content": "结案后补充"}, expected=409)
        rec.must("归档" in (resp.json().get("detail") or ""), "结案补充拒绝文案")

    with rec.step(
        "US-07-AC-04c_结案再举报",
        us="US-07", sc="SC-07-04",
        desc="同一对象举报已结案后再次提交举报（4.18：结案后归档，不再接受重新提交）",
        expected="409 拒绝重新提交；原举报保持 handled、原事项保持 disposed，/reports/mine 数量与举报事项数不增加",
    ):
        mine_before = api.get("/reports/mine", token=ctx.token("chen"), expected=200).json()
        cases_before = admin_list_cases(api, ctx, status="all", case_type="report")
        before_report_ids = {int(row["id"]) for row in mine_before}
        before_case_ids = {int(row["id"]) for row in cases_before}
        resp = api.post("/reports", token=ctx.token("chen"), json_body={
            "target_type": "product", "target_id": ctx.items["p_qian_violation_id"],
            "reason": "结案后再次举报"})
        if resp.status_code != 409:
            rec.defect("requirement_gap", {
                "rule": "US-07-AC-04 / 4.18：举报结案后该事项归档，不再接受补充或重新提交",
                "repro": f"POST /reports target_type=product target_id={ctx.items['p_qian_violation_id']} "
                         f"在举报 #{ctx.items['r_qian_product_id']} handled 后调用",
                "expected": "409 拒绝重新提交，不新建举报/事项",
                "actual": f"HTTP {resp.status_code} {resp.text[:300]}",
                "source": "backend/app/api/v1/reports.py:POST /reports",
            })
        rec.must_eq(resp.status_code, 409, "结案后再次举报应被拒绝")
        mine_after = api.get("/reports/mine", token=ctx.token("chen"), expected=200).json()
        rec.must_eq(len(mine_after), len(mine_before), "结案后重报不增加我的举报数量")
        rec.must_eq({int(row["id"]) for row in mine_after} - before_report_ids, set(),
                    "结案后重报不新建举报")
        original = next((row for row in mine_after
                         if int(row["id"]) == int(ctx.items["r_qian_product_id"])), None)
        rec.must(original is not None, "原举报仍可读取")
        rec.must_eq(original["status"], "handled", "原举报状态保持 handled")
        cases_after = admin_list_cases(api, ctx, status="all", case_type="report")
        new_cases = [case for case in cases_after if int(case["id"]) not in before_case_ids]
        rec.must_eq(new_cases, [], "结案后重报不新建举报事项")
        original_case = admin_case_detail(api, ctx, int(ctx.items["case_qian_id"]))
        rec.must_eq(original_case["status"], "disposed", "原举报事项状态保持 disposed")

    # =====================================================================
    # 6. zhao：撤展 → 直接封禁（联动关闭请求/冻结交易）→ 申诉 → 解封 → 恢复展示
    # =====================================================================
    p_zhao_pending = _ensure_listed_product(
        api, ctx, "p_zhao_pending", "zhao", "宿舍置物架（阶段封禁联动样本）", 4000,
        "product_lamp.jpg", category_id,
    )
    tid_ban_pending = _create_request(api, ctx, "chen", "zhao", p_zhao_pending["id"],
                                      "t_ban_pending", note="封禁联动待接受请求")
    ctx.remember_trade("t_ban_pending", {"id": tid_ban_pending}, "chen", "zhao",
                       state="pending_acceptance")

    def _zhao_trade_product() -> dict:
        return _ensure_listed_product(
            api, ctx, "p_zhao_trade", "zhao", "二手绘图板（阶段封禁冻结样本）", 9000,
            "product_camera.jpg", category_id,
        )

    tid_ban_frozen, p_zhao_trade_id = _ensure_single_confirm_trade(
        api, ctx, "t_ban_frozen", "chen", "zhao", _zhao_trade_product
    )
    p_report_cycle = _ensure_listed_product(
        api, ctx, "p_report_cycle", "zhao", "代写作业 论文辅导（阶段违规撤展样本）", 12000,
        "product_violation.jpg", category_id,
    )
    # 先收藏 p_report_cycle，供撤展后失效、恢复展示后自动有效验证
    fav = api.post(f"/favorites/{p_report_cycle['id']}", token=ctx.token("chen"), expected=200).json()
    ctx.remember_item("favorite", "favorite_report_cycle", fav.get("favorite_id"),
                      f"收藏商品#{p_report_cycle['id']}", "active",
                      {"product_id": p_report_cycle["id"]})
    report_cycle = _create_report(api, ctx.token("chen"), "product", p_report_cycle["id"],
                                  "代写作业属于禁发范围")
    _remember_report(ctx, "r_cycle", {"id": report_cycle["id"], "target_type": "product",
                                    "reason": "代写作业属于禁发范围"}, "pending")
    case_cycle = _report_case_id(api, ctx, report_cycle["id"])
    ctx.items["case_cycle_id"] = case_cycle

    with rec.step(
        "SC-07-07_违规撤展",
        us="US-08", sc="SC-07-07",
        desc="zhao 违规商品举报认定违规：仅撤销公开访问（未封禁），收藏立即失效",
        expected="decision 200；product display_restricted=true、status 不变；chen 收藏 valid=false；账户仍 normal",
    ):
        _claim(api, ctx, case_cycle)
        _inquiry(api, ctx, case_cycle, "请说明代写作业辅导服务内容")
        _statement(api, ctx.token("zhao"), case_cycle, "说明：仅转让闲置学习资料")
        _reply(api, ctx, case_cycle, "已核实商品标题与描述")
        api.post(f"/admin/reports/cases/{case_cycle}/decision", token=ctx.token("admin"),
                 json_body={
                     "outcome": "handled",
                     "reason": "代写作业属于禁发范围",
                     "public_summary": "已认定违规并撤销商品公开访问",
                     "basis": "BR-13/TR-09",
                     "actions": {"restrict_display": True},
                 }, expected=200)
        product = api.get(f"/products/{p_report_cycle['id']}", token=ctx.token("zhao"),
                          expected=200).json()
        rec.must_eq(product["display_restricted"], True, "违规商品展示限制")
        rec.must_eq(product["status"], "listed", "展示限制不改变生命周期")
        favs = api.get("/favorites", token=ctx.token("chen"), expected=200).json()
        rec.must_eq(next(f for f in favs if f["product_id"] == p_report_cycle["id"])["valid"], False,
                    "撤展后收藏失效")
        rec.must_eq(api.get("/auth/me", token=ctx.token("zhao"), expected=200).json()["status"],
                    "normal", "仅撤展时不封禁账户")
        ctx.remember_case("case_cycle", {"id": case_cycle, "title": "举报事项：商品",
                                         "case_type": "report", "status": "disposed"})
        ctx.update_product("p_report_cycle", state="listed")

    ban_case_id: int | None = None
    with rec.step(
        "SC-07-07_封禁联动",
        us="US-08", sc="SC-07-07",
        desc="封禁 zhao：关闭其待接受请求（原因相关账户被封禁、通知双方、归档分支）、"
             "冻结其进行中已单方确认交易并暂停计时、其商品停止公开展示",
        expected="ban 200；请求 closed/原因正确/分支归档/双方通知；交易 frozen=true 且 paused 记录；商品 display_restricted",
    ):
        before_frozen = _trade(api, ctx, tid_ban_frozen, "chen")
        rec.must_eq(before_frozen["status"], "in_progress", "封禁前交易状态")
        rec.must_eq(before_frozen["my_confirmed"], True, "封禁前已有单方完成确认")
        rec.must(before_frozen["confirm_wait_started_at"] is not None, "封禁前已开始等待计时")
        ban = api.post(f"/admin/users/{ctx.accounts['zhao']['id']}/ban", token=ctx.token("admin"),
                       json_body={"reason": "发布禁发范围内容（代写作业）"}, expected=200)
        ban_case_id = int(ban.json()["case_id"])
        ctx.items["ban_case_id"] = ban_case_id
        rec.must_eq(api.get("/auth/me", token=ctx.token("zhao"), expected=200).json()["status"],
                    "banned", "zhao 封禁状态")
        closed = _trade(api, ctx, tid_ban_pending, "chen")
        rec.must_eq(closed["status"], "closed", "待接受请求被关闭")
        rec.must_eq(closed["close_reason"], "相关账户被封禁", "请求关闭原因")
        rec.must_eq(closed["conversation_archived"], True, "请求分支归档")
        chen_notifs = _notifications(api, ctx.token("chen"))
        zhao_notifs = _notifications(api, ctx.token("zhao"))
        rec.must(bool(_notif(chen_notifs, "request_closed", tid_ban_pending)), "买方收到请求关闭通知")
        rec.must(bool(_notif(zhao_notifs, "request_closed", tid_ban_pending)), "卖方收到请求关闭通知")
        transitions = api.get(f"/trades/{tid_ban_pending}/transitions", token=ctx.token("chen"),
                              expected=200).json()
        rec.must(any(t["trigger"] == "account_banned" and t["to_status"] == "closed"
                     for t in transitions), "请求关闭状态转移留痕")
        frozen = _trade(api, ctx, tid_ban_frozen, "chen")
        rec.must_eq(frozen["status"], "in_progress", "封禁不结束已接受交易")
        rec.must_eq(frozen["frozen"], True, "封禁冻结交易")
        rec.must_eq(frozen["frozen_reason"] is not None, True, "冻结原因")
        rec.must(frozen["confirm_wait_paused_at"] is not None, "封禁冻结暂停等待计时")
        rec.must(int(frozen["confirm_wait_remaining_seconds"]) > 0, "冻结保存剩余等待秒数")
        rec.must(bool(_notif(_notifications(api, ctx.token("chen")), "trade_frozen", tid_ban_frozen)),
                 "冻结通知买方")
        for key, pid in (("p_zhao_pending", p_zhao_pending["id"]),
                         ("p_zhao_trade", p_zhao_trade_id),
                         ("p_report_cycle", p_report_cycle["id"])):
            data = api.get(f"/products/{pid}", token=ctx.token("zhao"), expected=200).json()
            rec.must_eq(data["display_restricted"], True, f"{key} 封禁后停止公开展示")
        ctx.update_trade("t_ban_pending", state="closed")
        rec.must_eq(api.get(f"/admin/users/{ctx.accounts['zhao']['id']}/restrictions",
                            token=ctx.token("admin"), expected=200).json()[0]["case_id"],
                    ban_case_id, "封禁限制关联封禁事项")

    with rec.step(
        "SC-07-07_封禁写限制",
        us="US-08", sc="SC-07-07",
        desc="封禁账户禁止发布/下架等业务写操作（禁写保读）",
        expected="发布/下架均 403 账户已被封禁；读取本人商品仍 200",
    ):
        image_key = (api.get(f"/products/{p_zhao_pending['id']}", token=ctx.token("zhao"),
                             expected=200).json()["image_keys"] or [""])[0]
        resp = api.post("/products", token=ctx.token("zhao"), json_body={
            "title": "封禁期发布尝试", "description": "不应成功", "price_cents": 100,
            "image_keys": [image_key], "tags": [{"category_id": category_id}]})
        rec.must_eq(resp.status_code, 403, "封禁用户发布")
        rec.must_eq(api.post(f"/products/{p_zhao_pending['id']}/delist",
                             token=ctx.token("zhao")).status_code, 403, "封禁用户下架")
        rec.must_eq(api.get(f"/products/{p_zhao_pending['id']}", token=ctx.token("zhao"),
                            expected=200).status_code, 200, "封禁仍可读取本人商品")

    with rec.step(
        "US-07-AC-07_仅冻结允许",
        us="US-07", sc="SC-07-07",
        desc="仅有交易冻结（账户未封禁）的用户仍按原资格允许新增举报与既往完成交易评价读取",
        expected="chen 存在有效冻结交易；冻结期间提交举报 201；既往完成交易评价入口返回 409 重复（非 403 冻结）",
    ):
        me = api.get("/auth/me", token=ctx.token("chen"), expected=200).json()
        rec.must_eq(me.get("has_frozen_trade"), True, "chen 处于仅冻结状态")
        rec.must_eq(me.get("status"), "normal", "冻结用户账户仍 normal")
        frozen_report = _create_report(api, ctx.token("chen"), "product", p_report_target["id"],
                                       "冻结期间举报（仅冻结不限制）")
        rec.must(int(frozen_report["id"]) > 0, "仅冻结用户仍可提交举报")
        _remember_report(ctx, "r_frozen_allowed", {"id": frozen_report["id"], "target_type": "product",
                                                   "reason": "冻结期间举报（仅冻结不限制）"}, "pending")
        resp = api.post(f"/trades/{tid_completed}/review", token=ctx.token("chen"),
                        json_body={"rating": 1})
        rec.must_eq(resp.status_code, 409, "仅冻结用户评价入口未被冻结阻断（重复评价 409）")

    with rec.step(
        "SC-07-09_封禁中不可单独恢复展示",
        us="US-08", sc="SC-07-09",
        desc="发布者仍封禁时调用 restore-display；非来源事项也不能解除展示限制",
        expected="409 发布者仍处于封禁状态；409 该事项不是当前展示限制的来源依据",
    ):
        resp = api.post(f"/admin/products/{p_report_cycle['id']}/restore-display",
                        token=ctx.token("admin"),
                        json_body={"case_id": case_cycle, "reason": "复核后恢复"})
        rec.must_eq(resp.status_code, 409, "封禁中恢复展示限制")
        rec.must("封禁" in (resp.json().get("detail") or ""), "封禁中恢复展示文案")
        resp = api.post(f"/admin/products/{p_report_cycle['id']}/restore-display",
                        token=ctx.token("admin"),
                        json_body={"case_id": ban_case_id, "reason": "错误来源事项"})
        rec.must_eq(resp.status_code, 409, "非来源事项不能解除展示限制")

    with rec.step(
        "SC-07-09_申诉与解封",
        us="US-08", sc="SC-07-09",
        desc="zhao 从本人事项提交申诉，管理员回复；管理员 /admin/users/{id}/unban 解除封禁",
        expected="appeal 200、回复 200 并通知；unban 200；账户 normal、限制 lifted、解封不重开请求、交易自动解冻并续算",
    ):
        user_case = _my_case(api, ctx.token("zhao"), ban_case_id)
        rec.must_eq(user_case["case_type"], "account_ban", "封禁事项类型")
        rec.must_eq(user_case["status"], "disposed", "封禁事项已处置")
        api.post(f"/me/cases/{ban_case_id}/appeal", token=ctx.token("zhao"),
                 json_body={"content": "申诉：已删除违规内容，请求解除限制"}, expected=200)
        _reply(api, ctx, ban_case_id, "申诉回复：违规内容已撤展，同意解除账户封禁")
        rec.must(bool(_notif(_notifications(api, ctx.token("zhao")), "appeal_result", ban_case_id)),
                 "申诉回复通知")
        history = api.get(f"/admin/users/{ctx.accounts['zhao']['id']}/restrictions",
                          token=ctx.token("admin"), expected=200).json()
        rec.must(any(r["status"] == "active" for r in history), "解封前存在生效限制")
        unban = api.post(f"/admin/users/{ctx.accounts['zhao']['id']}/unban",
                         token=ctx.token("admin"),
                         json_body={"lift_reason": "违规内容已撤展，解除账户封禁"}, expected=200)
        rec.must("已解除" in (unban.json().get("detail") or ""), "解封成功文案")
        rec.must_eq(api.get("/auth/me", token=ctx.token("zhao"), expected=200).json()["status"],
                    "normal", "解封后账户状态")
        history = api.get(f"/admin/users/{ctx.accounts['zhao']['id']}/restrictions",
                          token=ctx.token("admin"), expected=200).json()
        lifted = [r for r in history if r["status"] == "lifted"]
        rec.must(lifted and lifted[-1]["lift_reason"], "限制解除留痕（lifted+原因）")
        rec.must_eq(_trade(api, ctx, tid_ban_pending, "chen")["status"], "closed",
                    "解封不重开已关闭请求")
        resumed = _trade(api, ctx, tid_ban_frozen, "chen")
        rec.must_eq(resumed["frozen"], False, "解封自动解除本笔冻结")
        rec.must_eq(resumed["confirm_wait_paused_at"], None, "解冻清空暂停时刻")
        rec.must(resumed["confirm_wait_remaining_seconds"] is not None, "解冻后等待计时重新计算剩余")
        rec.must(resumed["confirm_wait_started_at"] is not None, "解冻后计时起点重锚")
        transitions = api.get(f"/trades/{tid_ban_frozen}/transitions", token=ctx.token("chen"),
                              expected=200).json()
        rec.must(any(t["trigger"] == "trade_unfrozen" for t in transitions), "解冻状态转移留痕")
        rec.must(bool(_notif(_notifications(api, ctx.token("chen")), "trade_unfrozen", tid_ban_frozen)),
                 "解冻通知双方")
        ctx.update_trade("t_ban_frozen", state="in_progress")

    with rec.step(
        "SC-07-09_恢复展示与收藏",
        us="US-08", sc="SC-07-09",
        desc="解封后仅因该封禁限制展示的商品恢复；违规撤展商品须由原认领管理员 restore-display，"
             "收藏 D-44 先失效后自动恢复有效",
        expected="zhao 被冻结/封禁商品 display_restricted=false；违规商品仍受限；restore-display 200 后"
                 "display_restricted=false、status 不变、收藏 valid=true、编辑历史 display_restore",
    ):
        for key, pid in (("p_zhao_pending", p_zhao_pending["id"]), ("p_zhao_trade", p_zhao_trade_id)):
            data = api.get(f"/products/{pid}", token=ctx.token("zhao"), expected=200).json()
            rec.must_eq(data["display_restricted"], False, f"{key} 解封后恢复展示")
            ctx.update_product(key, state=data["status"])
        cycle = api.get(f"/products/{p_report_cycle['id']}", token=ctx.token("zhao"), expected=200).json()
        rec.must_eq(cycle["display_restricted"], True, "违规撤展商品不随解封恢复")
        favs = api.get("/favorites", token=ctx.token("chen"), expected=200).json()
        rec.must_eq(next(f for f in favs if f["product_id"] == p_report_cycle["id"])["valid"], False,
                    "D-44：恢复展示前收藏仍失效")
        restore = api.post(f"/admin/products/{p_report_cycle['id']}/restore-display",
                           token=ctx.token("admin"),
                           json_body={"case_id": case_cycle, "reason": "申诉通过，解除展示限制"},
                           expected=200)
        rec.must("展示限制已解除" in (restore.json().get("detail") or ""), "恢复展示文案")
        cycle_after = api.get(f"/products/{p_report_cycle['id']}", token=ctx.token("zhao"),
                              expected=200).json()
        rec.must_eq(cycle_after["display_restricted"], False, "恢复展示后无展示限制")
        rec.must_eq(cycle_after["status"], "listed", "恢复展示不改变生命周期")
        favs = api.get("/favorites", token=ctx.token("chen"), expected=200).json()
        rec.must_eq(next(f for f in favs if f["product_id"] == p_report_cycle["id"])["valid"], True,
                    "D-44：恢复展示后收藏自动恢复有效")
        history = api.get(f"/products/{p_report_cycle['id']}/edit-history",
                          token=ctx.token("zhao"), expected=200).json()
        rec.must(any(h["edit_type"] == "display_restore" for h in history), "恢复展示编辑历史留痕")
        ctx.update_product("p_report_cycle", state="listed")

    # =====================================================================
    # 7. 事项状态样本：待处理（未认领）/处理中（已认领+问询）/已处置
    # =====================================================================
    case_inquiry: int | None = None
    with rec.step(
        "US-08-AC-01_事项状态样本",
        us="US-08", sc="SC-07-12",
        desc="共享池保留待处理（未认领）与处理中（已认领且已问询）样本；已处置样本见前序；"
             "管理员列表按状态/类型过滤",
        expected="pending 中有未认领举报事项；processing 中有已认领且已问询事项；disposed 含举报/封禁事项",
    ):
        report_proc = _create_report(api, ctx.token("wang"), "product", p_report_target["id"],
                                     "商品描述与实物不符")
        _remember_report(ctx, "r_processing", {"id": report_proc["id"], "target_type": "product",
                                              "reason": "商品描述与实物不符"}, "processing")
        case_inquiry = _report_case_id(api, ctx, report_proc["id"])
        ctx.items["case_inquiry_id"] = case_inquiry
        _claim(api, ctx, case_inquiry)
        _inquiry(api, ctx, case_inquiry, "请说明商品描述与实物差异")
        _statement(api, ctx.token("liu"), case_inquiry, "说明：商品描述已注明使用痕迹")
        _reply(api, ctx, case_inquiry, "已收到说明，待进一步核查")
        message_case = _report_case_id(api, ctx, ctx.items["r_message_id"])
        pending_cases = admin_list_cases(api, ctx, status="pending", case_type="report")
        rec.must(any(c["id"] == message_case for c in pending_cases), "待处理样本：未认领举报事项")
        processing_cases = admin_list_cases(api, ctx, status="processing", case_type="report")
        rec.must(any(c["id"] == case_inquiry for c in processing_cases), "处理中样本：已认领举报事项")
        disposed_cases = admin_list_cases(api, ctx, status="disposed")
        disposed_ids = {c["id"] for c in disposed_cases}
        rec.must(case_comment in disposed_ids and case_qian in disposed_ids, "已处置样本：举报事项")
        rec.must(any(c["id"] == ban_case_id for c in disposed_cases), "封禁事项已处置留痕")
        inquiry_detail = _my_case(api, ctx.token("liu"), case_inquiry)
        rec.must_eq(inquiry_detail["has_inquiry"], True, "问询中事项 has_inquiry")
        rec.must_eq(inquiry_detail["status"], "processing", "问询中事项仍处理中")
        ctx.remember_case("case_inquiry", {"id": case_inquiry, "title": "举报事项：商品",
                                           "case_type": "report", "status": "processing"})
        ctx.remember_case("case_ban_final", {"id": ban_case_id, "title": "账户封禁：赵同学",
                                             "case_type": "account_ban", "status": "disposed"})

    with rec.step(
        "US-08-AC-04_事项访问控制",
        us="US-08", sc="SC-07-12",
        desc="本人事项访问资格：被询问/受处置本人、交易参与方可读；无关第三方 403",
        expected="liu 可读本人被询问事项；zhang 读同一事项 403；qian 可读本人事项；zhao 本人事项含封禁",
    ):
        rec.must_eq(api.get(f"/me/cases/{case_inquiry}", token=ctx.token("liu"),
                            expected=200).status_code, 200, "受询问人读取本人事项")
        rec.must_eq(api.get(f"/me/cases/{case_inquiry}", token=ctx.token("zhang")).status_code, 403,
                    "无关第三方读取事项")
        rec.must_eq(api.get(f"/me/cases/{case_qian}", token=ctx.token("qian"),
                            expected=200).status_code, 200, "受处置人读取本人事项")
        mine = _my_cases(api, ctx.token("zhao"))
        rec.must(any(c["case_type"] == "account_ban" for c in mine), "本人事项入口含封禁事项")

    # =====================================================================
    # 8. 消息举报目标（共享池待处理样本）与管理端可见性
    # =====================================================================
    with rec.step(
        "US-07-AC-03_消息举报内容",
        us="US-07", sc="SC-07-04",
        desc="message 目标举报保留在共享池，管理员认领后可见被举报消息快照与证据字段",
        expected="未认领时事项待处理；认领后 case 详情 report_target 含消息内容与发送者；不自动处置",
    ):
        case_message = _report_case_id(api, ctx, ctx.items["r_message_id"])
        ctx.items["case_message_id"] = case_message
        pending = admin_list_cases(api, ctx, status="pending", case_type="report")
        rec.must(any(c["id"] == case_message for c in pending), "消息举报进入待处理共享池")
        _claim(api, ctx, case_message)
        detail = admin_case_detail(api, ctx, case_message)
        snapshot = detail.get("report_target") or {}
        rec.must_eq(snapshot.get("type"), "message", "举报目标快照类型")
        rec.must_eq(snapshot.get("content"), "阶段样本：交易分支消息", "举报目标消息内容")
        rec.must_eq(snapshot.get("sender_id"), ctx.accounts["chen"]["id"], "消息责任用户")
        rec.must_eq((detail.get("report") or {}).get("status"), "pending", "举报状态仍待处理")
        ctx.remember_case("case_message", {"id": case_message, "title": "举报事项：消息",
                                           "case_type": "report", "status": "processing"})

    # qian 最终保持封禁、违规商品保持撤展（不解除）
    with rec.step(
        "SC-07-09_qian保持封禁",
        us="US-08", sc="SC-07-09",
        desc="违规样本 qian 最终保持 banned，违规商品 display_restricted 保留（不自动恢复）",
        expected="qian status=banned；商品 display_restricted=true、status=listed；存在生效限制记录",
    ):
        rec.must_eq(api.get("/auth/me", token=ctx.token("qian"), expected=200).json()["status"],
                    "banned", "qian 保持封禁")
        product = api.get(f"/products/{ctx.items['p_qian_violation_id']}",
                          token=ctx.token("qian"), expected=200).json()
        rec.must_eq(product["display_restricted"], True, "qian 违规商品保持撤展")
        rec.must_eq(product["status"], "listed", "撤展商品生命周期保持")
        restrictions = api.get(f"/admin/users/{ctx.accounts['qian']['id']}/restrictions",
                               token=ctx.token("admin"), expected=200).json()
        rec.must(any(r["status"] == "active" and r["type"] == "ban" for r in restrictions),
                 "qian 存在生效封禁限制记录")

    with rec.step(
        "US-08-AC-08_管理员无个人通知",
        us="US-08", sc="SC-07-10",
        desc="管理员不接收个人站内通知（4.17），共享池通过事项列表暴露",
        expected="管理员 /notifications 恒为 total=0",
    ):
        notif = api.get("/notifications", token=ctx.token("admin"), expected=200).json()
        rec.must_eq(notif.get("total"), 0, "管理员站内通知数")
        rec.must_eq(notif.get("items"), [], "管理员站内通知列表")

    _dedupe_inventory(ctx)
    _refresh_report_states(api, ctx)

    ctx.note(
        "p07 证据边界：评价、举报、认领、问询、决策处置、封禁/解封、restore-display、交易冻结/解冻"
        "全部由真实 HTTP 接口与真实后台逻辑完成，本阶段未直接读写数据库、未做时间加速。"
    )
    ctx.note(
        "p07 观察：ReportStatus.PROCESSING 在实现中没有赋值路径——管理员认领举报事项后"
        "事项变为 processing，但举报对象状态仍为 pending，直到 decision 才变为 handled/unfounded；"
        "契约中的 processing 过滤分支真实链路不可达，事项与举报状态不同步，作为风险记录。"
    )
    ctx.note(
        "p07 公开结果核验边界：举报人 /reports/mine 与受处置人 /reports/received 不能证明"
        "“向所有已登录用户公开”；公开结果由 tools/supplementary_checks.py 以第三方只读"
        " GET /reports/public 单独核验（确认前不可见、字段白名单），本阶段不把 /reports/mine 当作公开证据。"
    )
