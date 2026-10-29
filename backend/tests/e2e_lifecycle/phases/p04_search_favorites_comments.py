"""[p04] 检索、详情、收藏与评论（US-03、US-04）真实 API 生命周期阶段。

本模块同时提供 dev-b 三个阶段（p04/p05/p06）共用的真实 API 造数辅助：
账户注册/登录、分类与别名、商品真实发布 + 管理员认领审核、交易请求/接受、通知读取。
p05、p06 只导入这些辅助函数，不依赖 p04 是否已运行——各阶段自行造数，仅共享代码。
"""

from __future__ import annotations

import uuid

from e2e_support import (
    admin_claim_case,
    admin_list_cases,
    ensure_account,
    login_account,
    upload_image,
)

PHASE_ID = "p04"
ADMIN_EMAIL = "admin@campus.edu"
ADMIN_PASSWORD = "admin123456"
DEFAULT_PASSWORD = "secret123"


# ===========================================================================
# 共用造数辅助（p04 / p05 / p06 均可导入）
# ===========================================================================
def ensure_admin(api, ctx) -> dict:
    """登录种子管理员账户（若上下文已有则直接复用）。"""
    if "admin" in ctx.accounts:
        return ctx.accounts["admin"]
    return login_account(api, ctx, "admin", ADMIN_EMAIL, ADMIN_PASSWORD, display_name="平台管理员")


def new_user(api, ctx, key: str, suffix: str, display_name: str | None = None) -> dict:
    """按 devb.<suffix>@campus.edu 真实注册/登录测试账户。"""
    if key in ctx.accounts:
        return ctx.accounts[key]
    return ensure_account(
        api,
        ctx,
        key,
        f"devb.{suffix}@campus.edu",
        display_name or suffix,
        DEFAULT_PASSWORD,
    )


def category_map(api, token: str) -> dict[str, dict]:
    """当前分类主名 -> 分类对象。"""
    resp = api.get("/categories", token=token, expected=200)
    return {c["name"]: c for c in resp.json()}


def ensure_category(api, ctx, admin_token: str, name: str) -> dict:
    """确保存在启用中的分类主名（不存在则由管理员真实创建）。"""
    cats = category_map(api, admin_token)
    cat = cats.get(name)
    if cat is not None and cat.get("status") == "active":
        return cat
    if cat is not None:
        raise AssertionError(f"分类「{name}」已存在但状态为 {cat.get('status')}，无法用于发布")
    resp = api.post("/categories", token=admin_token, json_body={"name": name}, expected=200)
    created = resp.json()
    ctx.remember_category(f"devb_cat_{name}", created)
    return created


def ensure_alias(api, ctx, admin_token: str, category_name: str, alias_name: str) -> dict:
    """在分类下真实添加别名（D-45/4.16；已存在则复用）。"""
    cats = category_map(api, admin_token)
    cat = cats.get(category_name)
    if cat is None:
        raise AssertionError(f"分类「{category_name}」不存在，无法添加别名")
    if alias_name in (cat.get("aliases") or []):
        return cat
    api.post(
        f"/categories/{cat['id']}/aliases",
        token=admin_token,
        json_body={"name": alias_name},
        expected=200,
    )
    ctx.remember_item("category_alias", alias_name, cat["id"], f"{category_name} 的别名 {alias_name}", "active")
    return category_map(api, admin_token)[category_name]


def upload_product_key(api, token: str, file_name: str = "product_textbook.jpg") -> str:
    """真实上传商品图片，返回文件 key（商品 image_keys 只存 key）。"""
    payload = upload_image(api, token, file_name, namespace="product")
    return payload["key"]


def find_review_case(api, ctx, product_id: int) -> dict | None:
    """在共享池中定位该商品的待处理审核事项（未认领、pending）。"""
    cases = admin_list_cases(api, ctx, status="pending", case_type="product_review")
    return next((c for c in cases if c.get("product_id") == product_id), None)


def approve_product(api, ctx, product_id: int, *, seller_token: str, reason: str = "审核通过（真实 API 生命周期测试）") -> dict:
    """管理员真实认领审核事项并审核通过，返回审核后的商品详情（卖方视角）。"""
    admin = ctx.account("admin")
    case = find_review_case(api, ctx, product_id)
    if case is None:
        raise AssertionError(f"共享池中找不到商品 #{product_id} 的待审核事项")
    admin_claim_case(api, ctx, case["id"])
    api.post(
        f"/admin/products/cases/{case['id']}/review",
        token=admin["token"],
        json_body={"result": "approved", "reason": reason},
        expected=200,
    )
    ctx.remember_item("review_case", f"product_{product_id}", case["id"], f"商品审核事项 #{case['id']}", "disposed")
    return api.get(f"/products/{product_id}", token=seller_token, expected=200).json()


def register_product(api, ctx, key: str, seller_key: str, *, title: str, price_cents: int, tag_names: list[str], image: str | None, description: str | None = None) -> dict:
    """真实发布商品（进入待审核）；不自动审核。"""
    seller = ctx.account(seller_key)
    admin = ensure_admin(api, ctx)
    tag_ids = [ensure_category(api, ctx, admin["token"], name)["id"] for name in tag_names]
    image_key = upload_product_key(api, seller["token"], image or "product_textbook.jpg")
    body = {
        "title": title,
        "description": description or f"{title}（真实 API 生命周期测试样本）",
        "price_cents": price_cents,
        "image_keys": [image_key],
        "tags": [{"category_id": cid} for cid in tag_ids],
    }
    resp = api.post("/products", token=seller["token"], json_body=body, expected=200)
    product = resp.json()
    ctx.remember_product(key, product, seller=seller_key, state=product.get("status", "pending_review"))
    return product


def publish_listed_product(
    api,
    ctx,
    key: str,
    seller_key: str,
    *,
    title: str,
    price_cents: int,
    tag_names: list[str],
    image: str | None = None,
    description: str | None = None,
) -> dict:
    """真实发布商品 -> 管理员认领审核通过 -> 公开可交易（listed）。"""
    product = register_product(
        api,
        ctx,
        key,
        seller_key,
        title=title,
        price_cents=price_cents,
        tag_names=tag_names,
        image=image,
        description=description,
    )
    approved = approve_product(api, ctx, product["id"], seller_token=ctx.token(seller_key))
    ctx.products[key].update(approved)
    ctx.update_product(key, state=approved.get("status", "listed"))
    return ctx.products[key]


def product_detail(api, token: str, product_id: int, *, expected=200):
    return api.get(f"/products/{product_id}", token=token, expected=expected)


def search_products(api, token: str, params: dict, *, expected=200) -> dict:
    return api.get("/products/search", token=token, params=params, expected=expected).json()


def request_trade(api, ctx, key: str, product_key: str, buyer_key: str, *, note: str | None = None) -> dict:
    """买方真实发起购买请求；重复 pending 时复用已有交易（幂等分支）。"""
    product = ctx.products[product_key]
    seller_key = product["seller"]
    buyer = ctx.account(buyer_key)
    body = {"product_id": product["id"]}
    if note:
        body["note"] = note
    resp = api.post("/trades/requests", token=buyer["token"], json_body=body, expected=200)
    payload = resp.json()
    trade_id = payload["id"]
    detail = api.get(f"/trades/{trade_id}", token=buyer["token"], expected=200).json()
    if key in ctx.trades:
        merge_trade_detail(ctx.trades[key], detail)
        ctx.update_trade(key, detail.get("status", "unknown"))
    else:
        ctx.remember_trade(key, detail, buyer=buyer_key, seller=seller_key, state=detail.get("status"))
    return detail


def merge_trade_detail(trade: dict, data: dict) -> dict:
    """把交易详情合并进 ctx 登记对象，保留 buyer/seller 的账户 key（详情里同名字段是对象）。"""
    for key, value in data.items():
        if key in ("buyer", "seller"):
            continue
        trade[key] = value
    return trade


def trade_detail(api, token: str, trade_id: int, *, expected=200) -> dict:
    return api.get(f"/trades/{trade_id}", token=token, expected=expected).json()


def trade_transitions(api, token: str, trade_id: int, *, expected=200) -> list[dict]:
    return api.get(f"/trades/{trade_id}/transitions", token=token, expected=expected).json()


def conversation_item(api, token: str, conversation_id: int, *, expected=200) -> dict:
    return api.get(f"/conversations/{conversation_id}", token=token, expected=expected).json()


def list_notifications(api, token: str, *, unread_only: bool = False, page: int = 1, page_size: int = 50) -> dict:
    params = {"page": page, "page_size": page_size}
    if unread_only:
        params["unread_only"] = "true"
    return api.get("/notifications", token=token, params=params, expected=200).json()


def notifications_matching(api, token: str, *, type_: str | None = None, link_id: int | None = None, unread_only: bool = False) -> list[dict]:
    """按类型/关联对象过滤本人通知（最多翻 2 页，足够覆盖单阶段事件量）。"""
    found: list[dict] = []
    for page in (1, 2):
        data = list_notifications(api, token, unread_only=unread_only, page=page)
        items = data.get("items") or []
        for item in items:
            if type_ is not None and item.get("type") != type_:
                continue
            if link_id is not None and item.get("link_id") != link_id:
                continue
            found.append(item)
        if len(items) < 50:
            break
    return found


def create_display_restriction(api, ctx, product_id: int, *, reporter_key: str, reason: str) -> dict:
    """真实举报 -> 管理员认领举报事项 -> 决策 restrict_display，形成“撤销公开访问”。"""
    admin = ctx.account("admin")
    reporter = ctx.account(reporter_key)
    resp = api.post(
        "/reports",
        token=reporter["token"],
        json_body={
            "target_type": "product",
            "target_id": product_id,
            "reason": reason,
            "detail": "真实 API 生命周期测试：验证撤销公开访问后的检索/详情/收藏/评论资格",
        },
        expected=201,
    )
    payload = resp.json()
    if "id" not in payload:
        raise AssertionError(f"举报未按预期新建：{payload}")
    report_id = payload["id"]
    reports = api.get("/admin/reports", token=admin["token"], params={"status": "pending"}, expected=200).json()
    report = next((r for r in reports if r.get("id") == report_id), None)
    if report is None or report.get("case_id") is None:
        raise AssertionError(f"举报 #{report_id} 未生成待处理事项")
    case_id = report["case_id"]
    admin_claim_case(api, ctx, case_id)
    api.post(
        f"/admin/reports/cases/{case_id}/decision",
        token=admin["token"],
        json_body={
            "outcome": "handled",
            "reason": reason,
            "public_summary": "测试处置：涉事商品停止公开访问",
            "basis": "真实 API 生命周期测试依据",
            "actions": {"restrict_display": True},
        },
        expected=200,
    )
    ctx.remember_report(
        f"devb_report_product_{product_id}",
        {"id": report_id, "target_type": "product", "target_id": product_id, "reason": reason, "status": "handled", "case_id": case_id},
    )
    ctx.remember_case(
        f"devb_report_case_{product_id}",
        {"id": case_id, "case_type": "report", "status": "disposed", "title": f"举报事项：商品#{product_id}"},
    )
    return {"report_id": report_id, "case_id": case_id}


def restore_display(api, ctx, product_id: int, case_id: int, *, reason: str) -> None:
    """管理员（展示限制来源事项认领人）解除撤销公开访问（TR-10/D-44）。"""
    admin = ctx.account("admin")
    api.post(
        f"/admin/products/{product_id}/restore-display",
        token=admin["token"],
        json_body={"case_id": case_id, "reason": reason},
        expected=200,
    )


def ban_user(api, ctx, user_key: str, *, reason: str) -> dict:
    admin = ctx.account("admin")
    user = ctx.account(user_key)
    resp = api.post(f"/admin/users/{user['id']}/ban", token=admin["token"], json_body={"reason": reason}, expected=200)
    payload = resp.json()
    ctx.remember_case(
        f"devb_ban_case_{user_key}",
        {"id": payload.get("case_id"), "case_type": "account_ban", "status": "disposed", "title": f"封禁事项：{user['display_name']}"},
    )
    return payload


def unban_user(api, ctx, user_key: str, *, reason: str) -> dict:
    admin = ctx.account("admin")
    user = ctx.account(user_key)
    return api.post(
        f"/admin/users/{user['id']}/unban",
        token=admin["token"],
        json_body={"lift_reason": reason},
        expected=200,
    ).json()


def detail_text(resp) -> str:
    """读取错误响应的 detail 文本（兼容 Pydantic 422 数组形态）。"""
    try:
        payload = resp.json()
    except Exception:  # noqa: BLE001 - 极少数非 JSON
        return resp.text
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, str):
        return detail
    return str(detail)


# ===========================================================================
# 阶段主体
# ===========================================================================
def _comment(api, token: str, product_id: int, content: str, *, reply_to: int | None = None, expected=201):
    body: dict = {"content": content}
    if reply_to is not None:
        body["reply_to_comment_id"] = reply_to
    return api.post(f"/products/{product_id}/comments", token=token, json_body=body, expected=expected)


def run(ctx, api, rec):
    """US-03 检索/详情可见性 + US-04 收藏/评论（真实 HTTP，独立造数）。"""
    stamp = uuid.uuid4().hex[:6]
    with rec.step(
        "P04-SETUP",
        us="US-03,US-04",
        sc="SC-03,SC-04",
        desc="真实注册测试账户、创建分类/别名、发布并审核通过全部测试商品",
        expected="账户/分类/商品全部就绪且走真实审核",
    ):
        ensure_admin(api, ctx)
        new_user(api, ctx, "p04_seller", "p04.seller", "检索卖方")
        new_user(api, ctx, "p04_buyer", "p04.buyer", "检索买方")
        new_user(api, ctx, "p04_buyer2", "p04.buyer2", "检索买方二")
        new_user(api, ctx, "p04_third", "p04.third", "检索第三方")
        new_user(api, ctx, "p04_commenter", "p04.commenter", "评论用户")
        # 频控用户按运行标识使用唯一邮箱，避免同一服务实例重复运行时残留 60 秒频控计数
        new_user(api, ctx, "p04_rate", f"p04.rate.{stamp}", "评论频控用户")
        new_user(api, ctx, "p04_banned", "p04.banned", "收藏封禁用户")
        admin = ctx.account("admin")
        ensure_category(api, ctx, admin["token"], "检索测试教材")
        ensure_category(api, ctx, admin["token"], "检索测试电子")
        ensure_alias(api, ctx, admin["token"], "检索测试教材", "检索旧称教材")
        publish_listed_product(
            api, ctx, "p04_multi", "p04_seller",
            title="检索多条件机械键盘套装",
            price_cents=15000,
            tag_names=["检索测试教材", "检索测试电子"],
            image="product_keyboard.jpg",
            description="多标签全部匹配检索样本，关键词：组合检索",
        )
        publish_listed_product(
            api, ctx, "p04_control", "p04_seller",
            title="检索多条件单标签控制组",
            price_cents=15000,
            tag_names=["检索测试教材"],
            image="product_notes.jpg",
            description="仅一个标签的对照组，用于验证多标签全部匹配",
        )
        publish_listed_product(
            api, ctx, "p04_price", "p04_seller",
            title="检索价格端点复习笔记",
            price_cents=10000,
            tag_names=["检索测试教材"],
            image="product_notes.jpg",
            description="价格端点 10000 分（100 元）样本",
        )
        publish_listed_product(
            api, ctx, "p04_kw", "p04_seller",
            title="检索关键词望远镜",
            price_cents=8800,
            tag_names=["检索测试教材"],
            image="product_camera.jpg",
            description="描述关键词样本：天文观测器材说明",
        )
        publish_listed_product(
            api, ctx, "p04_trade", "p04_seller",
            title="交易中可见性台灯",
            price_cents=6600,
            tag_names=["检索测试教材"],
            image="product_lamp.jpg",
            description="进入交易中后退出在售搜索、详情仍可见的样本",
        )
        publish_listed_product(
            api, ctx, "p04_delist", "p04_seller",
            title="下架不可见水杯",
            price_cents=3300,
            tag_names=["检索测试教材"],
            image="product_mug.jpg",
            description="主动下架后不提供公开详情的样本",
        )
        publish_listed_product(
            api, ctx, "p04_restrict", "p04_seller",
            title="撤销公开收纳盒",
            price_cents=4400,
            tag_names=["检索测试教材"],
            image="product_notes.jpg",
            description="管理处置撤销公开访问（展示限制）样本",
        )
        publish_listed_product(
            api, ctx, "p04_comment", "p04_seller",
            title="评论测试折叠桌",
            price_cents=5500,
            tag_names=["检索测试教材"],
            image="product_lamp.jpg",
            description="评论与卖方回复、删除、频控样本",
        )
        rec.must(len(ctx.products) >= 8, "测试商品未全部创建完成")

    seller_tok = ctx.token("p04_seller")
    buyer_tok = ctx.token("p04_buyer")
    buyer2_tok = ctx.token("p04_buyer2")
    third_tok = ctx.token("p04_third")
    cat_a_id = ensure_category(api, ctx, ctx.token("admin"), "检索测试教材")["id"]
    cat_b_id = ensure_category(api, ctx, ctx.token("admin"), "检索测试电子")["id"]
    p_multi = ctx.products["p04_multi"]["id"]
    p_control = ctx.products["p04_control"]["id"]
    p_price = ctx.products["p04_price"]["id"]
    p_kw = ctx.products["p04_kw"]["id"]
    p_trade = ctx.products["p04_trade"]["id"]
    p_delist = ctx.products["p04_delist"]["id"]
    p_restrict = ctx.products["p04_restrict"]["id"]
    p_comment = ctx.products["p04_comment"]["id"]

    # ---------------------------------------------------------------- US-03-AC-01
    with rec.step(
        "US-03-AC-01a",
        us="US-03",
        sc="SC-03-01",
        desc="关键词 + 多标签（全部匹配）+ 价格区间组合检索",
        expected="同时满足全部条件的商品命中，单标签对照组不命中",
    ):
        data = search_products(
            api, buyer_tok,
            {"keyword": "检索多条件", "category_ids": [cat_a_id, cat_b_id], "price_min_cents": 10000, "price_max_cents": 20000, "page_size": 50},
        )
        ids = {c["id"] for c in data["items"]}
        rec.must(p_multi in ids, f"多标签全部匹配的商品 #{p_multi} 应命中，实际 items={sorted(ids)}")
        rec.must(p_control not in ids, f"仅单标签的对照组 #{p_control} 不应命中多标签全部匹配")

    with rec.step(
        "US-03-AC-01b",
        us="US-03",
        sc="SC-03-01",
        desc="价格区间包含端点（price_min=price_max=10000 命中）、端点外不命中",
        expected="端点商品命中；9999/10001 区间排除",
    ):
        hit = search_products(api, buyer_tok, {"keyword": "检索价格端点", "price_min_cents": 10000, "price_max_cents": 10000, "page_size": 50})
        hit_ids = {c["id"] for c in hit["items"]}
        rec.must(p_price in hit_ids, f"价格端点商品 #{p_price} 应命中，实际 {sorted(hit_ids)}")
        low = search_products(api, buyer_tok, {"keyword": "检索价格端点", "price_max_cents": 9999, "page_size": 50})
        rec.must(p_price not in {c["id"] for c in low["items"]}, "price_max=9999 不应命中 10000 分商品")
        high = search_products(api, buyer_tok, {"keyword": "检索价格端点", "price_min_cents": 10001, "page_size": 50})
        rec.must(p_price not in {c["id"] for c in high["items"]}, "price_min=10001 不应命中 10000 分商品")

    with rec.step(
        "US-03-AC-01c",
        us="US-03",
        sc="SC-03-01",
        desc="关键词匹配商品描述与关联分类主名",
        expected="关键词出现在描述/分类主名时同样命中",
    ):
        by_desc = search_products(api, buyer_tok, {"keyword": "天文观测", "page_size": 50})
        rec.must(p_kw in {c["id"] for c in by_desc["items"]}, f"描述关键词应命中商品 #{p_kw}")
        by_cat = search_products(api, buyer_tok, {"keyword": "检索测试电子", "page_size": 50})
        rec.must(p_multi in {c["id"] for c in by_cat["items"]}, f"关键词匹配分类主名时应命中带该标签的商品 #{p_multi}")

    with rec.step(
        "US-03-AC-01d",
        us="US-03",
        sc="SC-03-01",
        desc="关键词与标签条件同时生效（AND）",
        expected="标签不符时即使关键词命中也不返回",
    ):
        mismatch = search_products(api, buyer_tok, {"keyword": "检索关键词", "category_ids": [cat_b_id], "page_size": 50})
        rec.must(p_kw not in {c["id"] for c in mismatch["items"]}, "商品仅带教材标签，按电子标签过滤不应命中")
        match = search_products(
            api, buyer_tok,
            {"keyword": "检索关键词", "category_ids": [cat_a_id], "price_min_cents": 8800, "price_max_cents": 8800, "page_size": 50},
        )
        rec.must(p_kw in {c["id"] for c in match["items"]}, "关键词/标签/价格同时满足时应命中")

    # ---------------------------------------------------------------- US-03-AC-02
    with rec.step(
        "US-03-AC-02a",
        us="US-03",
        sc="SC-03-01",
        desc="分类主名筛选命中该分类商品",
        expected="category_names=主名 返回该标签商品",
    ):
        data = search_products(api, buyer_tok, {"category_names": ["检索测试教材"], "page_size": 50})
        ids = {c["id"] for c in data["items"]}
        rec.must(p_control in ids, f"主名筛选应命中商品 #{p_control}")
        rec.must(p_multi in ids, f"主名筛选应命中双标签商品 #{p_multi}")

    with rec.step(
        "US-03-AC-02b",
        us="US-03",
        sc="SC-03-01",
        desc="分类别名解析：别名与主名定位同一分类、结果一致",
        expected="别名筛选结果与主名一致（D-45/4.16）",
    ):
        main = search_products(api, buyer_tok, {"category_names": ["检索测试教材"], "page_size": 50})
        alias = search_products(api, buyer_tok, {"category_names": ["检索旧称教材"], "page_size": 50})
        rec.must_eq(
            {c["id"] for c in alias["items"]},
            {c["id"] for c in main["items"]},
            "别名与主名筛选结果",
        )
        rec.must_eq(alias.get("total"), main.get("total"), "别名与主名 total")

    with rec.step(
        "US-03-AC-02c",
        us="US-03",
        sc="SC-10-01",
        desc="主名与别名同时选择不重复计标签（单标签商品仍匹配全部所选）",
        expected="同一分类的主名+别名解析为同一 id，单标签商品仍命中（别名不重复计）",
    ):
        data = search_products(api, buyer_tok, {"category_names": ["检索测试教材", "检索旧称教材"], "page_size": 50})
        ids = {c["id"] for c in data["items"]}
        rec.must(p_control in ids, f"单标签商品 #{p_control} 在主名+别名同时选择时仍应命中（别名不重复计标签）")

    with rec.step(
        "US-03-AC-02d",
        us="US-03",
        sc="SC-10-01",
        desc="未知分类名严格无匹配，不忽略未知项放宽过滤",
        expected="category_names 含未知名称 -> 空结果 + 无匹配商品提示（D-45）",
    ):
        data = search_products(api, buyer_tok, {"category_names": ["不存在的分类xyz"], "page_size": 50})
        rec.must_eq(data.get("items"), [], "未知分类名结果列表")
        rec.must_eq(data.get("total"), 0, "未知分类名 total")
        rec.must_eq(data.get("message"), "无匹配商品", "未知分类名提示")
        mixed = search_products(api, buyer_tok, {"category_names": ["检索测试教材", "不存在的分类xyz"], "page_size": 50})
        rec.must_eq(mixed.get("total"), 0, "主名+未知名混合时严格无匹配")

    # ---------------------------------------------------------------- US-03-AC-03
    with rec.step(
        "US-03-AC-03a",
        us="US-03",
        sc="SC-03-02",
        desc="无匹配商品时返回空列表与「无匹配商品」提示",
        expected="200 + items=[]/total=0/message=无匹配商品（不是错误）",
    ):
        data = search_products(api, buyer_tok, {"keyword": f"不存在的关键词-{stamp}", "page_size": 50})
        rec.must_eq(data.get("items"), [], "空结果列表")
        rec.must_eq(data.get("total"), 0, "空结果 total")
        rec.must_eq(data.get("message"), "无匹配商品", "空结果提示")

    with rec.step(
        "US-03-AC-03b",
        us="US-03",
        sc="SC-03-02",
        desc="无筛选条件时返回结构合法的在售列表",
        expected="200 列表结构合法",
    ):
        data = search_products(api, buyer_tok, {"page_size": 50})
        rec.must(data.get("total", 0) >= 1, "当前库内应至少存在本阶段创建的在售商品")
        rec.must(isinstance(data.get("items"), list), "搜索 items 应为列表")

    # ---------------------------------------------------------------- 未登录
    with rec.step(
        "US-03-AC-06a",
        us="US-03",
        sc="SC-03-03",
        desc="未登录检索/查看列表/查看详情均被拒绝",
        expected="401 未登录或登录已过期，不返回业务内容",
    ):
        for path in ("/products/search", f"/products/{p_multi}", f"/products/{p_multi}/comments", "/favorites", "/categories"):
            resp = api.get(path, expected=401)
            rec.must(("未登录" in detail_text(resp)), f"{path} 未登录应提示未登录，实际 {detail_text(resp)}")

    with rec.step(
        "US-03-AC-06b",
        us="US-03",
        sc="SC-03-03",
        desc="未登录发表评论被拒绝",
        expected="401",
    ):
        resp = api.post(f"/products/{p_comment}/comments", json_body={"content": "未登录评论"}, expected=401)
        rec.must("未登录" in detail_text(resp), "未登录评论应返回未登录提示")

    # ---------------------------------------------------------------- US-04-AC-01 收藏基础
    with rec.step(
        "US-04-AC-01a",
        us="US-04",
        sc="SC-03-01",
        desc="登录用户收藏公开商品并查看本人清单",
        expected="200 收藏成功；清单可见商品标题/价格/状态且 valid=true",
    ):
        resp = api.post(f"/favorites/{p_kw}", token=buyer_tok, expected=200)
        fav_id = resp.json().get("favorite_id")
        rec.must(fav_id is not None, f"收藏响应缺少 favorite_id：{resp.text[:300]}")
        ctx.remember_item("favorite", "p04_kw", fav_id, f"收藏商品#{p_kw}", "active")
        favorites = api.get("/favorites", token=buyer_tok, expected=200).json()
        item = next((f for f in favorites if f.get("product_id") == p_kw), None)
        rec.must(item is not None, "本人收藏清单应包含刚收藏的商品")
        rec.must_eq(item.get("valid"), True, "收藏有效标记")
        rec.must_eq(item.get("title"), ctx.products["p04_kw"]["title"], "收藏标题")
        rec.must_eq(item.get("status"), "listed", "收藏商品状态")

    with rec.step(
        "US-04-AC-01b",
        us="US-04",
        sc="SC-03-01",
        desc="重复收藏同一商品幂等返回既有收藏 id",
        expected="200 同一 favorite_id，不产生重复记录",
    ):
        first = api.post(f"/favorites/{p_kw}", token=buyer_tok, expected=200).json()
        second = api.post(f"/favorites/{p_kw}", token=buyer_tok, expected=200).json()
        rec.must_eq(second.get("favorite_id"), first.get("favorite_id"), "重复收藏 favorite_id")
        favorites = api.get("/favorites", token=buyer_tok, expected=200).json()
        rec.must_eq(len([f for f in favorites if f.get("product_id") == p_kw]), 1, "收藏记录条数")

    with rec.step(
        "US-04-AC-01c",
        us="US-04",
        sc="SC-03-06",
        desc="收藏清单仅本人可见，其他用户清单不包含该收藏",
        expected="他人清单没有该商品收藏",
    ):
        others = api.get("/favorites", token=buyer2_tok, expected=200).json()
        rec.must_eq([f for f in others if f.get("product_id") == p_kw], [], "他人收藏清单不应包含本人收藏")

    with rec.step(
        "US-04-AC-01d",
        us="US-04",
        sc="SC-03-04",
        desc="商品进入交易中后已有收藏保持有效（收藏记录保留且 valid=true）",
        expected="交易中商品在本人收藏清单 valid=true 且状态为 in_transaction",
    ):
        api.post(f"/favorites/{p_trade}", token=buyer_tok, expected=200)
        trade = request_trade(api, ctx, "p04_trade_trade", "p04_trade", "p04_buyer")
        rec.must_eq(trade.get("status"), "pending_acceptance", "请求创建后交易状态")
        api.post(f"/trades/{trade['id']}/accept", token=seller_tok, expected=200)
        accepted = trade_detail(api, buyer_tok, trade["id"])
        rec.must_eq(accepted.get("status"), "in_progress", "接受后交易状态")
        ctx.update_trade("p04_trade_trade", "in_progress")
        favorites = api.get("/favorites", token=buyer_tok, expected=200).json()
        item = next((f for f in favorites if f.get("product_id") == p_trade), None)
        rec.must(item is not None, "交易中商品的既有收藏应保留")
        rec.must_eq(item.get("valid"), True, "交易中收藏有效标记")
        rec.must_eq(item.get("status"), "in_transaction", "收藏商品当前状态")

    with rec.step(
        "US-04-AC-01e",
        us="US-04",
        sc="SC-03-04",
        desc="交易中商品不接受新收藏（已有收藏保持有效，退出售卖资格）",
        expected="POST /favorites/{交易中商品} -> 404 商品不存在或不可收藏",
    ):
        resp = api.post(f"/favorites/{p_trade}", token=buyer2_tok, expected=404)
        rec.must("不可收藏" in detail_text(resp), f"交易中商品新收藏应被拒绝，实际 {detail_text(resp)}")

    # ---------------------------------------------------------------- US-04-AC-02 取消收藏
    with rec.step(
        "US-04-AC-02a",
        us="US-04",
        sc="SC-03-07",
        desc="取消本人收藏后清单移除，重复取消返回 404",
        expected="取消成功；再取消 404 未收藏该商品",
    ):
        api.delete(f"/favorites/{p_kw}", token=buyer_tok, expected=200)
        favorites = api.get("/favorites", token=buyer_tok, expected=200).json()
        rec.must_eq([f for f in favorites if f.get("product_id") == p_kw], [], "取消收藏后清单")
        resp = api.delete(f"/favorites/{p_kw}", token=buyer_tok, expected=404)
        rec.must("未收藏" in detail_text(resp), f"重复取消收藏提示应包含未收藏，实际 {detail_text(resp)}")

    # ---------------------------------------------------------------- US-04-AC-03 评论
    with rec.step(
        "US-04-AC-03a",
        us="US-04",
        sc="SC-04-01",
        desc="登录用户对公开商品发表评论并公开展示",
        expected="201 发表；评论列表含作者/内容/deleted=false",
    ):
        resp = _comment(api, ctx.token("p04_commenter"), p_comment, "请问这个折叠桌承重多少？")
        comment_id = resp.json().get("id")
        rec.must(comment_id is not None, "发表评论未返回 id")
        ctx.remember_item("comment", "p04_first", comment_id, "第一条评论", "published")
        comments = api.get(f"/products/{p_comment}/comments", token=buyer_tok, expected=200).json()
        row = next((c for c in comments if c.get("id") == comment_id), None)
        rec.must(row is not None, "评论列表应包含新评论")
        rec.must_eq(row.get("content"), "请问这个折叠桌承重多少？", "评论内容")
        rec.must_eq(row.get("deleted"), False, "评论删除标记")
        rec.must_eq(row.get("author_id"), ctx.account("p04_commenter")["id"], "评论作者 id")

    with rec.step(
        "US-04-AC-03b",
        us="US-04",
        sc="SC-04-02",
        desc="卖方回复买方评论（reply_to 被正确记录）",
        expected="201 回复；列表展示 reply_to_comment_id 与 reply_to_user_id",
    ):
        first = ctx.items["comment:p04_first"]["id"]
        resp = _comment(api, seller_tok, p_comment, "承重约 20 公斤，可放心使用。", reply_to=first)
        reply_id = resp.json().get("id")
        comments = api.get(f"/products/{p_comment}/comments", token=buyer_tok, expected=200).json()
        row = next((c for c in comments if c.get("id") == reply_id), None)
        rec.must(row is not None, "卖方回复应出现在评论列表")
        rec.must_eq(row.get("reply_to_comment_id"), first, "回复目标评论 id")
        rec.must_eq(row.get("reply_to_user_id"), ctx.account("p04_commenter")["id"], "被回复用户 id")

    with rec.step(
        "US-04-AC-03c",
        us="US-04",
        sc="SC-04-02",
        desc="不支持买方之间互相回复：非卖方回复评论被拒绝",
        expected="403 仅商品卖方可回复评论",
    ):
        resp = _comment(api, buyer2_tok, p_comment, "我也想知道承重。", reply_to=ctx.items["comment:p04_first"]["id"], expected=403)
        rec.must("卖方" in detail_text(resp), f"非卖回复应提示仅卖方，实际 {detail_text(resp)}")

    with rec.step(
        "US-04-AC-03d",
        us="US-04",
        sc="SC-04-02",
        desc="卖方回复本人评论被拒绝（卖方仅可回复买方评论）",
        expected="400 卖方仅可回复买方评论",
    ):
        seller_comment = _comment(api, seller_tok, p_comment, "卖方自身补充说明评论。").json()["id"]
        resp = _comment(api, seller_tok, p_comment, "回复自己的评论", reply_to=seller_comment, expected=400)
        rec.must("买方评论" in detail_text(resp), f"卖方回复本人评论应提示仅可回复买方，实际 {detail_text(resp)}")

    with rec.step(
        "US-04-AC-03e",
        us="US-04",
        sc="SC-04-04",
        desc="作者删除本人评论：逻辑删除保留占位、他人删除被拒绝",
        expected="作者 200 删除且列表显示「该评论已删除」；他人 403",
    ):
        victim = _comment(api, ctx.token("p04_commenter"), p_comment, "重复提问：是否可折叠？").json()["id"]
        resp = api.delete(f"/products/{p_comment}/comments/{victim}", token=buyer2_tok, expected=403)
        rec.must("本人" in detail_text(resp), f"非作者删除应提示仅本人，实际 {detail_text(resp)}")
        api.delete(f"/products/{p_comment}/comments/{victim}", token=ctx.token("p04_commenter"), expected=200)
        comments = api.get(f"/products/{p_comment}/comments", token=buyer_tok, expected=200).json()
        row = next(c for c in comments if c.get("id") == victim)
        rec.must_eq(row.get("deleted"), True, "删除后 deleted 标记")
        rec.must_eq(row.get("content"), "该评论已删除", "删除后内容占位")
        api.delete(f"/products/{p_comment}/comments/{victim}", token=ctx.token("p04_commenter"), expected=200)
        resp = api.delete(f"/products/{p_comment}/comments/99999999", token=seller_tok, expected=404)
        rec.must("评论不存在" in detail_text(resp), "删除不存在评论应 404 评论不存在")

    with rec.step(
        "US-04-AC-03f",
        us="US-04",
        sc="SC-04-01",
        desc="评论内容长度限制：空白 400、超 500 字 400、超 schema 2000 字 422",
        expected="空白/501 字 400；2001 字 422；空串 422",
    ):
        resp = _comment(api, ctx.token("p04_commenter"), p_comment, "   ", expected=400)
        rec.must("不能为空" in detail_text(resp), f"空白评论应 400 不能为空，实际 {detail_text(resp)}")
        resp = _comment(api, ctx.token("p04_commenter"), p_comment, "评" * 501, expected=400)
        rec.must("500" in detail_text(resp), f"501 字评论应 400 最长 500 字，实际 {detail_text(resp)}")
        _comment(api, ctx.token("p04_commenter"), p_comment, "评" * 2001, expected=422)
        _comment(api, ctx.token("p04_commenter"), p_comment, "", expected=422)

    with rec.step(
        "US-04-AC-03g",
        us="US-04",
        sc="SC-04-01",
        desc="评论发表频率限制：60 秒内第 4 条返回 429",
        expected="前 3 条 201，第 4 条 429 评论过于频繁",
    ):
        rate_tok = ctx.token("p04_rate")
        ids = []
        for i in range(3):
            ids.append(_comment(api, rate_tok, p_comment, f"频控测试第 {i + 1} 条评论").json()["id"])
        resp = _comment(api, rate_tok, p_comment, "频控测试第 4 条评论", expected=429)
        rec.must("频繁" in detail_text(resp), f"第 4 条评论应 429 评论过于频繁，实际 {detail_text(resp)}")
        rec.must(len(ids) == 3, "前三条评论应全部发表成功")

    with rec.step(
        "US-04-AC-03h",
        us="US-04",
        sc="SC-04-01",
        desc="回复目标不存在时返回 404；评论不存在商品返回 404",
        expected="404 回复目标评论不存在 / 商品不存在",
    ):
        # 回复目标校验在频控计数之后（CAND-13）：使用频控额度未耗尽的用户避免 429 掩盖 404。
        resp = _comment(api, buyer2_tok, p_comment, "回复不存在的评论", reply_to=99999999, expected=404)
        rec.must("回复目标" in detail_text(resp), f"回复不存在评论应 404 回复目标评论不存在，实际 {detail_text(resp)}")
        resp = _comment(api, ctx.token("p04_commenter"), 99999999, "评论不存在商品", expected=404)
        rec.must("商品不存在" in detail_text(resp), f"评论不存在商品应 404，实际 {detail_text(resp)}")

    # ---------------------------------------------------------------- US-03-AC-04 交易中
    with rec.step(
        "US-03-AC-04a",
        us="US-03",
        sc="SC-03-04",
        desc="交易中商品退出在售搜索",
        expected="搜索不返回 in_transaction 商品",
    ):
        data = search_products(api, buyer_tok, {"keyword": "交易中可见性", "page_size": 50})
        rec.must(p_trade not in {c["id"] for c in data["items"]}, "交易中商品不应进入在售搜索")
        broad = search_products(api, buyer_tok, {"keyword": "检索", "page_size": 50})
        rec.must(p_trade not in {c["id"] for c in broad["items"]}, "宽泛检索也不应返回交易中商品")

    with rec.step(
        "US-03-AC-04b",
        us="US-03",
        sc="SC-03-04",
        desc="交易中商品登录用户仍可按展示资格查看详情与评论",
        expected="第三方详情 200 且状态 in_transaction；评论列表 200",
    ):
        detail = product_detail(api, third_tok, p_trade).json()
        rec.must_eq(detail.get("status"), "in_transaction", "交易中商品详情状态")
        comments = api.get(f"/products/{p_trade}/comments", token=third_tok, expected=200)
        rec.must(isinstance(comments.json(), list), "交易中商品评论列表应可读")

    with rec.step(
        "US-04-AC-03i",
        us="US-04",
        sc="SC-04-01",
        desc="交易中商品仍允许新增评论（BR-17/BR-14）",
        expected="201 发表成功",
    ):
        resp = _comment(api, third_tok, p_trade, "交易中也能咨询，请问可以自提吗？")
        rec.must(resp.json().get("id") is not None, "交易中商品评论应成功")

    # ---------------------------------------------------------------- US-03-AC-05 下架
    with rec.step(
        "US-03-AC-05a",
        us="US-03",
        sc="SC-03-04",
        desc="商品下架后不提供公开详情（他人 404、本人 200）",
        expected="第三方 404 商品不存在或不可见；卖方本人可见 status=delisted",
    ):
        api.post(f"/favorites/{p_delist}", token=buyer_tok, expected=200)
        api.post(f"/products/{p_delist}/delist", token=seller_tok, expected=200)
        ctx.update_product("p04_delist", state="delisted")
        resp = product_detail(api, third_tok, p_delist, expected=404)
        rec.must("不可见" in detail_text(resp), f"下架商品对他人应 404，实际 {detail_text(resp)}")
        own = product_detail(api, seller_tok, p_delist).json()
        rec.must_eq(own.get("status"), "delisted", "下架商品本人视角状态")
        comments = api.get(f"/products/{p_delist}/comments", token=third_tok, expected=404)
        rec.must("不可见" in detail_text(comments), "下架商品评论列表应对他人不可见")

    with rec.step(
        "US-03-AC-05b",
        us="US-03",
        sc="SC-03-04",
        desc="下架商品退出在售搜索",
        expected="搜索不返回已下架商品",
    ):
        data = search_products(api, buyer_tok, {"keyword": "下架不可见", "page_size": 50})
        rec.must(p_delist not in {c["id"] for c in data["items"]}, "已下架商品不应进入在售搜索")

    with rec.step(
        "US-04-AC-03j",
        us="US-04",
        sc="SC-04-03",
        desc="已下架商品禁止新增评论与回复",
        expected="409 当前商品状态不可评论或回复",
    ):
        resp = _comment(api, third_tok, p_delist, "下架后还能评论吗？", expected=409)
        rec.must("不可评论" in detail_text(resp), f"下架商品评论应 409，实际 {detail_text(resp)}")

    # ---------------------------------------------------------------- 撤销公开访问
    with rec.step(
        "P04-SETUP-RESTRICT",
        us="US-03",
        sc="SC-03-05",
        desc="真实举报 + 管理员认领举报事项 + 处置撤销公开访问（restrict_display）",
        expected="商品 status 仍 listed 但 display_restricted=true",
    ):
        api.post(f"/favorites/{p_restrict}", token=buyer_tok, expected=200)
        info = create_display_restriction(
            api, ctx, p_restrict,
            reporter_key="p04_buyer2",
            reason="测试商品含违规内容（真实生命周期测试）",
        )
        ctx.items["p04_restrict_case"] = {
            "kind": "case",
            "key": "p04_restrict_case",
            "id": info["case_id"],
            "label": "撤销公开访问依据事项",
            "state": "disposed",
            "extra": {},
        }
        detail = product_detail(api, seller_tok, p_restrict).json()
        rec.must_eq(detail.get("status"), "listed", "撤销公开访问不改变生命周期状态")
        rec.must_eq(detail.get("display_restricted"), True, "撤销公开访问标记")
        ctx.update_product("p04_restrict", state="listed(display_restricted)")

    with rec.step(
        "US-03-AC-05c",
        us="US-03",
        sc="SC-03-05",
        desc="撤销公开访问后公开详情与搜索均不提供入口，本人仍可见",
        expected="第三方 404；搜索不包含；本人 200 且 display_restricted=true",
    ):
        resp = product_detail(api, third_tok, p_restrict, expected=404)
        rec.must("不可见" in detail_text(resp), f"撤销公开商品对他人应 404，实际 {detail_text(resp)}")
        data = search_products(api, buyer_tok, {"keyword": "撤销公开", "page_size": 50})
        rec.must(p_restrict not in {c["id"] for c in data["items"]}, "撤销公开商品不应进入在售搜索")
        own = product_detail(api, seller_tok, p_restrict).json()
        rec.must_eq(own.get("display_restricted"), True, "本人视角 display_restricted")
        comments = api.get(f"/products/{p_restrict}/comments", token=third_tok, expected=404)
        rec.must("不可见" in detail_text(comments), "撤销公开商品评论列表应对他人不可见")

    with rec.step(
        "US-04-AC-03k",
        us="US-04",
        sc="SC-04-03",
        desc="撤销公开访问后禁止新增评论与回复",
        expected="409 当前商品状态不可评论或回复",
    ):
        resp = _comment(api, third_tok, p_restrict, "撤销公开后评论应被拒绝", expected=409)
        rec.must("不可评论" in detail_text(resp), f"撤销公开商品评论应 409，实际 {detail_text(resp)}")

    # ---------------------------------------------------------------- US-04-AC-02b/09 失效收藏
    with rec.step(
        "US-04-AC-02b",
        us="US-04",
        sc="SC-03-05",
        desc="下架/撤销公开后收藏仅显示失效提示，不泄露内容且可取消",
        expected="valid=false 且标题/价格/图片/状态为 null；下架收藏可与取消",
    ):
        for product_id, key in ((p_delist, "p04_delist"), (p_restrict, "p04_restrict")):
            favorites = api.get("/favorites", token=buyer_tok, expected=200).json()
            item = next((f for f in favorites if f.get("product_id") == product_id), None)
            rec.must(item is not None, f"{key} 收藏记录应保留（不硬删除）")
            rec.must_eq(item.get("valid"), False, f"{key} 收藏失效标记")
            rec.must_eq(item.get("title"), None, f"{key} 失效收藏不泄露标题")
            rec.must_eq(item.get("price_cents"), None, f"{key} 失效收藏不泄露价格")
            rec.must_eq(item.get("image_url"), None, f"{key} 失效收藏不泄露图片")
            rec.must_eq(item.get("status"), None, f"{key} 失效收藏不泄露状态")
            rec.must_eq(item.get("seller_name"), "", f"{key} 失效收藏不泄露卖方")
        api.delete(f"/favorites/{p_delist}", token=buyer_tok, expected=200)
        favorites = api.get("/favorites", token=buyer_tok, expected=200).json()
        rec.must_eq([f for f in favorites if f.get("product_id") == p_delist], [], "取消失效收藏后清单")

    with rec.step(
        "US-04-AC-09a",
        us="US-04",
        sc="SC-03-09",
        desc="管理处置解除（恢复展示）后原收藏自动恢复有效，无须重新收藏",
        expected="restore-display 后收藏 valid=true 且商品重新可搜索可见",
    ):
        restore_display(api, ctx, p_restrict, ctx.items["p04_restrict_case"]["id"], reason="测试解除：合规复核通过")
        ctx.update_product("p04_restrict", state="listed")
        favorites = api.get("/favorites", token=buyer_tok, expected=200).json()
        item = next((f for f in favorites if f.get("product_id") == p_restrict), None)
        rec.must(item is not None, "收藏关系应保留")
        rec.must_eq(item.get("valid"), True, "恢复展示后收藏自动恢复有效")
        rec.must_eq(item.get("title"), ctx.products["p04_restrict"]["title"], "恢复后收藏标题")
        detail = product_detail(api, third_tok, p_restrict).json()
        rec.must_eq(detail.get("display_restricted"), False, "解除后 display_restricted=false")
        data = search_products(api, buyer_tok, {"keyword": "撤销公开", "page_size": 50})
        rec.must(p_restrict in {c["id"] for c in data["items"]}, "解除后商品应重新进入在售搜索")

    with rec.step(
        "US-04-AC-09b",
        us="US-04",
        sc="SC-03-09",
        desc="仍有其他限制（已下架）的收藏保持失效，不泄露内容",
        expected="下架商品收藏取消后不再出现，且保持搜索不可见",
    ):
        favorites = api.get("/favorites", token=buyer_tok, expected=200).json()
        rec.must_eq([f for f in favorites if f.get("product_id") == p_delist], [], "已下架收藏取消后不再出现")
        data = search_products(api, buyer_tok, {"keyword": "下架不可见", "page_size": 50})
        rec.must(p_delist not in {c["id"] for c in data["items"]}, "下架商品保持不可见")

    # ---------------------------------------------------------------- 封禁只读
    with rec.step(
        "US-04-AC-01f",
        us="US-04",
        sc="SC-03-08",
        desc="账户封禁后收藏只读：可查看本人清单，禁止收藏与取消收藏",
        expected="GET /favorites 200；POST/DELETE /favorites 403；解封后恢复",
    ):
        api.post(f"/favorites/{p_comment}", token=ctx.token("p04_banned"), expected=200)
        ban_user(api, ctx, "p04_banned", reason="封禁只读收藏测试")
        me = api.get("/auth/me", token=ctx.token("p04_banned"), expected=200).json()
        rec.must_eq(me.get("status"), "banned", "封禁后账户状态")
        favorites = api.get("/favorites", token=ctx.token("p04_banned"), expected=200).json()
        rec.must(len(favorites) >= 1, "封禁账户应可查看本人收藏清单")
        resp = api.post(f"/favorites/{p_kw}", token=ctx.token("p04_banned"), expected=403)
        rec.must("封禁" in detail_text(resp), f"封禁账户收藏应 403，实际 {detail_text(resp)}")
        resp = api.delete(f"/favorites/{p_comment}", token=ctx.token("p04_banned"), expected=403)
        rec.must("封禁" in detail_text(resp), f"封禁账户取消收藏应 403，实际 {detail_text(resp)}")
        unban_user(api, ctx, "p04_banned", reason="解除封禁只读测试")
        me = api.get("/auth/me", token=ctx.token("p04_banned"), expected=200).json()
        rec.must_eq(me.get("status"), "normal", "解封后账户状态")
        api.delete(f"/favorites/{p_comment}", token=ctx.token("p04_banned"), expected=200)
