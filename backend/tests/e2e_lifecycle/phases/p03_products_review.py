"""p03 商品发布、审核与维护（US-02、US-09、US-13；SC-02、SC-10）。

真实 HTTP 覆盖：
- 商品矩阵发布 → 共享池待审事项 → 管理员认领 → 审核通过/不通过；
- 待审核（未认领）商品不可见、可撤回；认领后拒绝撤回且状态保持；
- 审核不通过 → 查看原因 → 修改重提 → 独立审核记录（旧结论保留）；
- 撤回审核（认领前）→ 已下架 → 修改后重提 → 再次审核；
- 标签申请三种决策：approve_new（新分类）、map_alias（同义别名）、reject（退回补充）；
- 编辑保留编辑历史并通知未结束请求买方；买方按 D-43 查看请求之后变更；
- 交易中禁止卖方修改关键内容、禁止主动下架；管理员可留据纠正分类；
- 下架关闭待接受请求；重新上架恢复公开；
- 现有演示商品补充真实图片（PATCH image_keys，仍保持 listed 并留下编辑历史）；
- 每件商品真实上传图片（关键商品 2 张），核对 key/url、商品/我的商品回图、签名 URL
  可读取 JPEG、篡改 sig 返回 403；
- D-48 商品 A（旧交易完成后重上架）与商品 B（新交易锁单中）供 p08 验证恢复冲突 409。

对象登记：ctx.products / ctx.trades / ctx.cases / ctx.categories。
"""

from __future__ import annotations

import re

from e2e_support import (
    admin_case_detail,
    admin_claim_case,
    admin_list_cases,
    download_file,
    ensure_account,
    login_account,
    upload_image,
)

PHASE_ID = "p03"

JPEG_MAGIC = b"\xff\xd8\xff"


# ---------------------------------------------------------------------------
# 账户与分类
# ---------------------------------------------------------------------------
def _ensure_accounts(api, ctx) -> None:
    seed = [
        ("admin", "admin@campus.edu", "admin123456", "平台管理员"),
        ("zhang", "zhang@campus.edu", "secret123", "张同学"),
        ("li", "li@campus.edu", "secret123", "李同学"),
        ("wang", "wang@campus.edu", "secret123", "王同学"),
    ]
    for key, email, password, name in seed:
        if key not in ctx.accounts:
            login_account(api, ctx, key, email, password, display_name=name)
    for key, email, name in (
        ("chen", "chen@campus.edu", "陈同学"),
        ("liu", "liu@campus.edu", "刘同学"),
        ("zhao", "zhao@campus.edu", "赵同学"),
        ("qian", "qian@campus.edu", "钱同学"),
        ("wu", "wu@campus.edu", "吴同学"),
        ("sun", "sun@campus.edu", "孙同学"),
    ):
        if key not in ctx.accounts:
            ensure_account(api, ctx, key, email, name)


def _category_index(api, ctx) -> dict[str, int]:
    if "p03_index" not in ctx.categories:
        categories = api.get("/categories", token=ctx.token("admin"), expected=200).json()
        index: dict[str, int] = {}
        for cat in categories:
            index.setdefault(cat["name"], cat["id"])
            for alias in cat.get("aliases") or []:
                index.setdefault(alias, cat["id"])
        ctx.categories["p03_index"] = {"index": index, "count": len(categories)}
    return ctx.categories["p03_index"]["index"]


def _cat(index: dict[str, int], *names: str) -> int:
    for name in names:
        if name in index:
            return index[name]
    raise AssertionError(f"分类不存在：{names}")


def _search(api, token: str, **params) -> dict:
    return api.get("/products/search", token=token, params=params, expected=200).json()


# ---------------------------------------------------------------------------
# 图片上传与读取
# ---------------------------------------------------------------------------
def _upload_images(api, rec, token: str, file_names: list[str], namespace: str = "product") -> list[dict]:
    """真实上传图片并核对 key/url、签名 URL 可读取 JPEG、篡改 sig 403。"""
    payloads: list[dict] = []
    for file_name in file_names:
        payload = upload_image(api, token, file_name, namespace=namespace)
        rec.must(bool(payload.get("key")), f"上传 {file_name} 应返回 key")
        rec.must(bool(payload.get("url")), f"上传 {file_name} 应返回签名 url")
        content = download_file(api, payload["url"])
        rec.must(content.content[:3] == JPEG_MAGIC, f"{file_name} 签名 URL 应读取到 JPEG 字节")
        rec.must(
            "image/jpeg" in (content.headers.get("content-type") or ""),
            f"{file_name} 签名 URL Content-Type 应为 image/jpeg",
        )
        tampered = re.sub(r"sig=[^&]+", "sig=deadbeef00", payload["url"])
        path = tampered.split("/api/v1", 1)[-1] if "/api/v1" in tampered else tampered
        bad = api.get(path)
        rec.must_eq(bad.status_code, 403, f"{file_name} 篡改 sig 应返回 403")
        payloads.append(payload)
    return payloads


def _detail_images_ok(api, rec, ctx, seller: str, detail: dict, expected_count: int) -> None:
    """商品详情与我的商品均返回图片，且签名 URL 可读取 JPEG 字节。"""
    keys = detail.get("image_keys") or []
    urls = detail.get("image_urls") or []
    rec.must_eq(len(keys), expected_count, f"商品 #{detail.get('id')} 详情 image_keys 数量")
    rec.must_eq(len(urls), expected_count, f"商品 #{detail.get('id')} 详情 image_urls 数量")
    for url in urls:
        content = download_file(api, url)
        rec.must(content.content[:3] == JPEG_MAGIC, "商品详情图片签名 URL 应读取到 JPEG 字节")
        rec.must("image/jpeg" in (content.headers.get("content-type") or ""), "商品详情图片 Content-Type 应为 image/jpeg")
    mine = api.get("/products/mine", token=ctx.token(seller), expected=200).json()
    row = next((item for item in mine if item.get("id") == detail.get("id")), None)
    rec.must(row is not None, f"我的商品应包含商品 #{detail.get('id')}")
    rec.must_eq(len(row.get("image_keys") or []), expected_count, "我的商品 image_keys 数量")


def _assert_detail(api, ctx, product_id: int, viewer: str = "admin") -> dict:
    return api.get(f"/products/{product_id}", token=ctx.token(viewer), expected=200).json()


# ---------------------------------------------------------------------------
# 发布 / 审核
# ---------------------------------------------------------------------------
def _publish(
    api,
    rec,
    ctx,
    *,
    seller: str,
    title: str,
    description: str,
    price_cents: int,
    tags: list[dict],
    images: list[str],
) -> tuple[dict, list[dict]]:
    payloads = _upload_images(api, rec, ctx.token(seller), images)
    resp = api.post(
        "/products",
        token=ctx.token(seller),
        json_body={
            "title": title,
            "description": description,
            "price_cents": price_cents,
            "image_keys": [payload["key"] for payload in payloads],
            "tags": tags,
        },
        expected=200,
    )
    product = resp.json()
    rec.must_eq(product.get("status"), "pending_review", "发布后商品应进入待审核")
    rec.must_eq(len(product.get("image_keys") or []), len(images), "发布返回 image_keys 数量")
    return product, payloads


def _pending_case(api, ctx, product_id: int) -> dict | None:
    cases = admin_list_cases(api, ctx, status="pending", case_type="product_review")
    return next((case for case in cases if case.get("product_id") == product_id), None)


def _claim(api, ctx, product_id: int) -> dict:
    case = _pending_case(api, ctx, product_id)
    if case is None:
        raise AssertionError(f"商品 #{product_id} 缺少共享池待审事项")
    admin_claim_case(api, ctx, case["id"])
    return case


def _remember_case(ctx, product_key: str, product_id: int, case_id: int, status: str = "disposed") -> None:
    ctx.remember_case(
        f"review:{product_key}",
        {
            "id": case_id,
            "title": f"商品审核事项：{product_key}",
            "status": status,
            "case_type": "product_review",
            "product_id": product_id,
        },
    )


def _approve(api, ctx, product_id: int, tag_decisions: list[dict] | None = None) -> tuple[dict, int]:
    case = _claim(api, ctx, product_id)
    body: dict = {"result": "approved"}
    if tag_decisions:
        body["tag_decisions"] = tag_decisions
    resp = api.post(
        f"/admin/products/cases/{case['id']}/review",
        token=ctx.token("admin"),
        json_body=body,
        expected=200,
    )
    detail = resp.json()
    if "审核通过" not in str((detail or {}).get("detail")):
        raise AssertionError(f"审核通过文案异常：{detail}")
    return detail, case["id"]


def _reject(api, ctx, product_id: int, reason: str) -> tuple[dict, int]:
    case = _claim(api, ctx, product_id)
    resp = api.post(
        f"/admin/products/cases/{case['id']}/review",
        token=ctx.token("admin"),
        json_body={"result": "rejected", "reason": reason},
        expected=200,
    )
    detail = resp.json()
    if "审核未通过" not in str((detail or {}).get("detail")):
        raise AssertionError(f"审核不通过文案异常：{detail}")
    return detail, case["id"]


def _register_product(ctx, key: str, product: dict, seller: str, state: str) -> dict:
    """登记/更新商品清单（同一 key 只保留一条 inventory 记录）。"""
    fields = {
        "id": product.get("id"),
        "title": product.get("title"),
        "status": product.get("status"),
        "state": state,
        "image_keys": list(product.get("image_keys") or []),
        "image_urls": list(product.get("image_urls") or []),
        "tag_names": list(product.get("tag_names") or []),
        "seller": seller,
    }
    if key in ctx.products:
        ctx.products[key].update(fields)
        for row in ctx.inventory:
            if row.get("kind") == "product" and row.get("key") == key:
                row.update({"id": fields["id"], "label": fields["title"] or row.get("label"), "state": state})
                row.setdefault("extra", {})["seller"] = seller
                break
        return ctx.products[key]
    item = ctx.remember_product(key, product, seller, state)
    item.update(fields)
    return item


def _seller_mine(api, ctx, seller: str, product_id: int) -> dict:
    mine = api.get("/products/mine", token=ctx.token(seller), expected=200).json()
    row = next((item for item in mine if item.get("id") == product_id), None)
    if row is None:
        raise AssertionError(f"{seller} 的我的商品中缺少 #{product_id}")
    return row


def _seed_product_by_title(api, ctx, seller: str, title: str) -> dict | None:
    mine = api.get("/products/mine", token=ctx.token(seller), expected=200).json()
    return next((item for item in mine if item.get("title") == title), None)


# ---------------------------------------------------------------------------
# 简单商品矩阵：发布→审核通过（p04 起消费）
# ---------------------------------------------------------------------------
def _simple_matrix(index: dict[str, int]) -> list[tuple]:
    goods = _cat(index, "电子产品")
    life = _cat(index, "生活用品")
    books = _cat(index, "教材书籍")
    dorm = _cat(index, "宿舍家电")
    sport = _cat(index, "运动器材", "运动健身")
    return [
        ("p_price_edge", "zhang", "线性代数复习笔记", "线性代数复习笔记，含公式总结与例题解析", 10000, [{"category_id": books}], ["product_notes.jpg"]),
        ("p_lock_multi", "zhang", "宿舍折叠桌", "宿舍折叠桌，节省空间，可折叠收纳，桌面完好", 7800, [{"category_id": life}], ["product_lamp.jpg"]),
        ("p_completed", "liu", "宿舍电煮锅", "宿舍小电煮锅，功能正常，已清洁，含说明书", 4600, [{"category_id": dorm}], ["product_lamp.jpg"]),
        ("p_terminated", "zhang", "微单相机（二手）", "二手微单相机，快门数不高，含电池与充电器", 120000, [{"category_id": goods}], ["product_camera.jpg"]),
        ("p_disputed_user", "li", "蓝牙机械键盘", "蓝牙机械键盘，红轴，手感良好，可连接多设备", 15900, [{"category_id": goods}], ["product_second2.jpg"]),
        ("p_disputed_open", "li", "宿舍小冰箱", "宿舍小冰箱，制冷正常，体积小巧", 22000, [{"category_id": dorm}], ["product_lamp.jpg"]),
        ("p_zhao_trade", "zhao", "二手绘图板", "二手绘图板，压感正常，含数据线与笔", 8800, [{"category_id": goods}], ["product_camera.jpg"]),
        ("p_zhao_pending", "zhao", "宿舍置物架", "宿舍置物架，三层可移动，承重良好", 3600, [{"category_id": life}], ["product_lamp.jpg"]),
        ("p_report_cycle", "zhao", "代写作业 论文辅导（违规内容）", "提供代写作业、论文辅导服务，非二手闲置物品", 5000, [{"category_id": _cat(index, "其他闲置")}], ["product_violation.jpg"]),
        ("p_restricted_stays", "qian", "游戏账号租售（违规内容）", "游戏账号租售，虚拟财产交易，非实物闲置", 9000, [{"category_id": _cat(index, "其他闲置")}], ["product_second2.jpg"]),
        ("p_freeze_pause", "wang", "宿舍电热水壶", "宿舍电热水壶，烧水正常，有自动断电保护", 4000, [{"category_id": dorm}], ["product_lamp.jpg"]),
        ("p_abnormal_open", "liu", "桌面收纳柜", "桌面收纳柜，抽屉顺滑，可放文具与杂物", 2000, [{"category_id": life}, {"category_id": goods}], ["product_notes.jpg"]),
        ("p_abnormal_disposed", "zhang", "山地车骑行头盔", "骑行头盔，无磕碰，内衬可拆洗", 6500, [{"category_id": sport}], ["product_racket.jpg"]),
        ("p_pending_requests", "wang", "羽毛球拍一对", "羽毛球拍一对，八成新，拍线完好，适合体育课使用", 6800, [{"category_id": sport}], ["product_racket.jpg"]),
    ]


def run(ctx, api, rec):
    _ensure_accounts(api, ctx)
    index = _category_index(api, ctx)

    # ------------------------------------------------------------------
    # 分类标签读取（发布依据）
    # ------------------------------------------------------------------
    with rec.step(
        "US-02-AC-01",
        us="US-02",
        sc="SC-02-01",
        desc="发布前读取登录用户可选分类标签（含 p02 改名后的主名与别名解析）",
        expected="分类列表可读且发布所需标签可解析",
    ) as step:
        categories = api.get("/categories", token=ctx.token("zhang"), expected=200).json()
        rec.must(len(categories) >= 10, "分类标签列表应可读")
        for name in ("教材书籍", "电子产品", "生活用品", "运动器材", "运动健身", "宿舍家电"):
            try:
                _cat(index, name)
            except AssertionError:
                continue
        sport = _cat(index, "运动器材", "运动健身")
        rec.must(sport > 0, "运动类标签应可解析（兼容改名前后名称）")
        step["detail"] = f"读取 {len(categories)} 个分类；运动类标签 id={sport}"

    # ------------------------------------------------------------------
    # 现有演示商品补真实图片（p_seed_textbook / p_seed_bike / p_seed_lamp）
    # ------------------------------------------------------------------
    seed_specs = [
        ("p_seed_textbook", "zhang", "高等数学教材（第七版）", "product_textbook.jpg", "US-02-AC-03", "SC-02-05"),
        ("p_seed_bike", "li", "山地自行车", "product_bike.jpg", "US-02-AC-03", "SC-02-05"),
        ("p_seed_lamp", "wang", "台灯与收纳盒", "product_lamp.jpg", "US-02-AC-03", "SC-02-05"),
    ]
    for key, seller, title, image_name, us, sc in seed_specs:
        with rec.step(
            us,
            us=us,
            sc=sc,
            desc=f"现有演示商品「{title}」由卖方本人 PATCH 补充真实图片并留下编辑历史",
            expected="上传 key/url 可读、PATCH 200 保持 listed、详情与我的商品回图、签名 URL JPEG 可读、篡改 sig 403",
        ) as step:
            product = _seed_product_by_title(api, ctx, seller, title)
            if product is None:
                rec.skip(
                    us,
                    us=us,
                    sc=sc,
                    desc=f"现有演示商品「{title}」补图",
                    reason="开发库中未找到该演示商品（可能已被其他流程改变），跳过既有商品补图",
                )
                continue
            payloads = _upload_images(api, rec, ctx.token(seller), [image_name])
            current_key = (product.get("image_keys") or [None])[0]
            new_keys = [payloads[0]["key"]]
            if current_key and current_key not in new_keys:
                new_keys = [current_key, payloads[0]["key"]]
            patched = api.patch(
                f"/products/{product['id']}",
                token=ctx.token(seller),
                json_body={"image_keys": new_keys},
                expected=200,
            )
            detail = patched.json()
            rec.must_eq(detail.get("status"), "listed", "补图后商品应保持 listed")
            _detail_images_ok(api, rec, ctx, seller, detail, len(new_keys))
            history = api.get(
                f"/products/{product['id']}/edit-history", token=ctx.token(seller), expected=200
            ).json()
            rec.must(len(history) >= 1, "补图应留下编辑历史")
            rec.must_eq(history[-1].get("edit_type"), "edit", "补图编辑历史类型")
            _register_product(ctx, key, detail, seller, detail.get("status"))
            ctx.products[key]["kind"] = "seed"
            if key == "p_seed_textbook":
                # 兼容 PLAN §4 的 p_existing_edit key（同一既有商品）
                ctx.products["p_existing_edit"] = dict(ctx.products[key])
                ctx.products["p_existing_edit"]["key"] = "p_existing_edit"
            step["detail"] = f"「{title}」补图 {len(new_keys)} 张并保持 listed；编辑历史已记录"

    # ------------------------------------------------------------------
    # 待审核未认领商品（p_review_pending）
    # ------------------------------------------------------------------
    with rec.step(
        "US-02-AC-01",
        us="US-02",
        sc="SC-02-01",
        desc="liu 发布「蓝牙音箱（宿舍闲置）」进入待审核与共享池，未审核不可公开访问",
        expected="pending_review；admin pending 审核事项含该商品；非卖方详情 404；搜索不出现",
    ) as step:
        product, payloads = _publish(
            api,
            rec,
            ctx,
            seller="liu",
            title="蓝牙音箱（宿舍闲置）",
            description="宿舍闲置蓝牙音箱，音质良好，配件齐全，功能正常",
            price_cents=8900,
            tags=[{"category_id": _cat(index, "电子产品")}],
            images=["product_second2.jpg"],
        )
        case = _pending_case(api, ctx, product["id"])
        rec.must(case is not None, "发布后应进入共享待处理池（未认领的审核事项）")
        rec.must_eq(case.get("status"), "pending", "审核事项初始状态")
        rec.must_eq(case.get("claimed_by_id"), None, "审核事项初始应未被认领")
        _register_product(ctx, "p_review_pending", product, "liu", "pending_review")
        _remember_case(ctx, "p_review_pending", product["id"], case["id"], "pending")
        other = api.get(f"/products/{product['id']}", token=ctx.token("chen"))
        api.expect_status(other, 404, "待审核商品对其他用户不可见")
        seller_detail = _assert_detail(api, ctx, product["id"], "liu")
        rec.must_eq(seller_detail.get("can_withdraw_review"), True, "未认领待审核商品应可撤回审核")
        by_keyword = _search(api, ctx.token("zhang"), keyword="蓝牙音箱")
        rec.must_eq(by_keyword.get("total"), 0, "待审核商品不应出现在在售搜索")
        step["detail"] = f"商品 #{product['id']} 待审核入共享池（事项 #{case['id']} 未认领），非卖方不可见"

    # ------------------------------------------------------------------
    # 审核不通过 → 修改重提 → 独立审核记录（p_review_rejected）
    # ------------------------------------------------------------------
    with rec.step(
        "US-02-AC-02",
        us="US-02",
        sc="SC-02-02",
        desc="liu 的「二手显示器 24 寸」审核不通过：卖家可见拒绝原因并收到通知，商品不公开",
        expected="rejected 且 reject_reason 可见；买方不可见；通知含原因",
    ) as step:
        product, _payloads = _publish(
            api,
            rec,
            ctx,
            seller="liu",
            title="二手显示器 24 寸",
            description="24 寸 IPS 显示器，无坏点，含电源线",
            price_cents=26000,
            tags=[{"category_id": _cat(index, "电子产品")}],
            images=["product_camera.jpg"],
        )
        _register_product(ctx, "p_review_rejected", product, "liu", "pending_review")
        rejected_reason = "退回补充：请补充接口类型与成色照片后重新提交"
        _api_resp, case_id = _reject(api, ctx, product["id"], rejected_reason)
        _remember_case(ctx, "p_review_rejected", product["id"], case_id)
        detail = _assert_detail(api, ctx, product["id"], "liu")
        rec.must_eq(detail.get("status"), "rejected", "审核不通过后商品状态")
        rec.must_eq(detail.get("reject_reason"), rejected_reason, "拒绝原因应可见")
        rec.must_eq(detail.get("can_resubmit"), True, "审核不通过商品应可修改重提")
        other = api.get(f"/products/{product['id']}", token=ctx.token("chen"))
        api.expect_status(other, 404, "审核未通过商品对其他用户不可见")
        notices = api.get(
            "/notifications", token=ctx.token("liu"), params={"page_size": 50}, expected=200
        ).json()
        review_notices = [
            item for item in notices.get("items", []) if item.get("type") == "review_result"
        ]
        rec.must(len(review_notices) >= 1, "审核不通过应发送站内通知")
        rec.must(
            any(rejected_reason in str(item.get("content")) for item in review_notices),
            "审核未通过通知应附拒绝原因",
        )
        step["detail"] = f"商品 #{product['id']} 审核不通过：原因可见、通知含原因、非公开"
        ctx.products["p_review_rejected"]["reject_reason"] = rejected_reason

    with rec.step(
        "US-02-AC-02",
        us="US-02",
        sc="SC-02-02",
        desc="拒绝后修改重提：形成独立审核记录、旧结论保留；认领后拒绝撤回且状态保持，再次审核不通过",
        expected="重提 pending_review 且新事项；认领后撤回 409；审核记录 2 条且旧结论保留",
    ) as step:
        product = ctx.products["p_review_rejected"]
        resubmit = api.post(
            f"/products/{product['id']}/resubmit",
            token=ctx.token("liu"),
            json_body={
                "title": "二手显示器 24 寸（补充说明）",
                "description": "24 寸 IPS 显示器，无坏点，含电源线与 HDMI 线，接口为 HDMI+DP",
                "price_cents": 25000,
            },
            expected=200,
        )
        pending = resubmit.json()
        rec.must_eq(pending.get("status"), "pending_review", "重提后应重新待审核")
        ctx.update_product("p_review_rejected", state="pending_review", title=pending.get("title"))
        case = _claim(api, ctx, product["id"])
        case_id = case["id"]
        # 认领后拒绝撤回
        withdraw = api.post(f"/products/{product['id']}/withdraw-review", token=ctx.token("liu"))
        api.expect_status(withdraw, 409, "认领后撤回审核应被拒绝")
        rec.must_in(
            "审核事项已被管理员认领或已处置", str((withdraw.json() or {}).get("detail")), "认领后撤回提示"
        )
        still = _assert_detail(api, ctx, product["id"], "liu")
        rec.must_eq(still.get("status"), "pending_review", "撤回被拒后状态保持待审核")
        # 再次审核不通过（退回补充）
        second_reason = "退回补充：请补充显示器接口与成色照片后重提"
        resp = api.post(
            f"/admin/products/cases/{case_id}/review",
            token=ctx.token("admin"),
            json_body={"result": "rejected", "reason": second_reason},
            expected=200,
        )
        rec.must("审核未通过" in str((resp.json() or {}).get("detail")), "第二次审核不通过")
        final = _assert_detail(api, ctx, product["id"], "liu")
        rec.must_eq(final.get("status"), "rejected", "第二次审核后状态")
        rec.must_eq(final.get("reject_reason"), second_reason, "第二次拒绝原因")
        ctx.update_product(
            "p_review_rejected",
            state="rejected",
            title=final.get("title"),
            reject_reason=second_reason,
        )
        # 独立审核记录：旧结论保留
        records = api.get(
            f"/products/{product['id']}/review-records", token=ctx.token("liu"), expected=200
        ).json()
        rec.must_eq(len(records), 2, "拒绝+重提+拒绝应形成 2 条独立审核记录")
        rec.must_eq(records[0].get("result"), "rejected", "第一条审核记录结果")
        rec.must_eq(
            records[0].get("reason"), "退回补充：请补充接口类型与成色照片后重新提交", "旧拒绝原因保留"
        )
        rec.must_eq(records[1].get("result"), "rejected", "第二条审核记录结果")
        rec.must_eq(records[1].get("reason"), second_reason, "新拒绝原因记录")
        buyer_records = api.get(
            f"/products/{product['id']}/review-records", token=ctx.token("chen")
        )
        api.expect_status(buyer_records, 403, "非发布者不可查看审核记录")
        _register_product(ctx, "p_review_rejected", final, "liu", "rejected")
        step["detail"] = (
            f"商品 #{product['id']} 重提形成新审核事项；认领后撤回 409；2 条审核记录旧结论保留，最终 rejected"
        )

    # ------------------------------------------------------------------
    # 商品状态读取：待审核/审核未通过（US-09-AC-01）
    # ------------------------------------------------------------------
    with rec.step(
        "US-09-AC-01",
        us="US-09",
        sc="SC-02-01",
        desc="卖方查看本人待审核与审核未通过商品状态与拒绝原因，公开搜索和详情不展示",
        expected="我的商品分别显示 pending_review/rejected 与拒绝原因；非本人详情 404；搜索无结果",
    ) as step:
        pending_product = ctx.products["p_review_pending"]
        rejected_product = ctx.products["p_review_rejected"]
        mine = api.get("/products/mine", token=ctx.token("liu"), expected=200).json()
        mine_by_id = {item["id"]: item for item in mine}
        rec.must_in(pending_product["id"], mine_by_id, "我的商品应包含待审核商品")
        rec.must_eq(mine_by_id[pending_product["id"]].get("status"), "pending_review", "待审核状态可读")
        rec.must_in(rejected_product["id"], mine_by_id, "我的商品应包含审核未通过商品")
        rec.must_eq(mine_by_id[rejected_product["id"]].get("status"), "rejected", "审核未通过状态可读")
        rec.must(
            bool(mine_by_id[rejected_product["id"]].get("reject_reason")), "审核未通过商品应可读拒绝原因"
        )
        api.expect_status(
            api.get(f"/products/{pending_product['id']}", token=ctx.token("wang")),
            404,
            "待审核商品对他人不可见",
        )
        api.expect_status(
            api.get(f"/products/{rejected_product['id']}", token=ctx.token("wang")),
            404,
            "审核未通过商品对他人不可见",
        )
        rec.must_eq(_search(api, ctx.token("wang"), keyword="二手显示器").get("total"), 0, "审核未通过商品不入搜索")
        step["detail"] = "待审核/审核未通过状态与拒绝原因卖方可见，他人不可见且不入搜索"

    # ------------------------------------------------------------------
    # 撤回标签申请 + 认领前撤回审核 + 修改重提（p_withdraw_resubmit）
    # ------------------------------------------------------------------
    with rec.step(
        "US-02-AC-09",
        us="US-02",
        sc="SC-02-13",
        desc="待审核期间修改/撤回标签申请/认领前撤回商品：撤回后置已下架，修改后可重提",
        expected="标签申请撤回 200；撤回审核 200 且 delisted/can_resubmit；重提 pending_review 形成新事项",
    ) as step:
        books_id = _cat(index, "教材书籍")
        product, payloads = _publish(
            api,
            rec,
            ctx,
            seller="liu",
            title="考研英语真题（近十年）",
            description="近十年考研英语真题，部分有铅笔笔记，适合复习使用",
            price_cents=4500,
            tags=[{"category_id": books_id}, {"new_name": "考研资料备选"}],
            images=["product_second.jpg", "product_notes.jpg"],
        )
        _register_product(ctx, "p_withdraw_resubmit", product, "liu", "pending_review")
        apps = product.get("pending_tag_applications") or []
        rec.must_eq(len(apps), 1, "发布时应生成一条待审标签申请")
        rec.must_eq(apps[0].get("requested_name"), "考研资料备选", "标签申请名称")
        patched = api.patch(
            f"/products/{product['id']}",
            token=ctx.token("liu"),
            json_body={"withdraw_tag_application_ids": [apps[0]["id"]]},
            expected=200,
        )
        rec.must_eq(patched.json().get("pending_tag_applications"), [], "撤回标签申请后不应再有待审申请")
        withdrawn = api.post(
            f"/products/{product['id']}/withdraw-review", token=ctx.token("liu"), expected=200
        ).json()
        rec.must_eq(withdrawn.get("status"), "delisted", "认领前撤回审核后商品应为已下架")
        rec.must_eq(withdrawn.get("can_resubmit"), True, "撤回审核后的已下架商品应可重提")
        records = api.get(
            f"/products/{product['id']}/review-records", token=ctx.token("liu"), expected=200
        ).json()
        rec.must_eq(records[-1].get("result"), "withdrawn", "撤回审核记录结果")
        ctx.update_product("p_withdraw_resubmit", state="delisted", image_keys=[p["key"] for p in payloads])
        step["detail"] = f"标签申请已撤回；审核认领前撤回成功（商品 #{product['id']} 置已下架）"

    with rec.step(
        "US-02-AC-09",
        us="US-02",
        sc="SC-02-15",
        desc="撤回审核后的已下架商品修改重提并再次审核：重新进入待审核，认领后修改以最新内容为准",
        expected="重提 pending_review 新事项；认领后修改不重新排队；审核通过后内容为最新修改版本",
    ) as step:
        product = ctx.products["p_withdraw_resubmit"]
        image_keys = product.get("image_keys") or []
        resubmit = api.post(
            f"/products/{product['id']}/resubmit",
            token=ctx.token("liu"),
            json_body={
                "title": "考研英语真题（近十年·含解析）",
                "description": "近十年考研英语真题，含答案解析册，部分有铅笔笔记",
                "price_cents": 5200,
                "image_keys": image_keys,
            },
            expected=200,
        )
        resubmitted = resubmit.json()
        rec.must_eq(resubmitted.get("status"), "pending_review", "重提后状态应为待审核")
        rec.must_eq(len(resubmitted.get("image_keys") or []), 2, "重提保留 2 张图片")
        case = _claim(api, ctx, product["id"])
        case_id = case["id"]
        # 认领后修改：不重新排队（不新增待审事项）
        edited_title = "考研英语真题（近十年·含解析册）"
        edited = api.patch(
            f"/products/{product['id']}",
            token=ctx.token("liu"),
            json_body={"title": edited_title, "price_cents": 5300},
            expected=200,
        )
        rec.must_eq(edited.json().get("status"), "pending_review", "认领后修改仍保持待审核")
        pending_cases = admin_list_cases(api, ctx, status="pending", case_type="product_review")
        rec.must_eq(
            [case for case in pending_cases if case.get("product_id") == product["id"]],
            [],
            "认领后修改不应重新排队生成新的待审事项",
        )
        review = api.post(
            f"/admin/products/cases/{case_id}/review",
            token=ctx.token("admin"),
            json_body={"result": "approved"},
            expected=200,
        )
        rec.must("审核通过" in str((review.json() or {}).get("detail")), "重提后审核通过")
        final = _assert_detail(api, ctx, product["id"], "liu")
        rec.must_eq(final.get("status"), "listed", "审核通过后公开可交易")
        rec.must_eq(final.get("title"), edited_title, "审核结论以认领后最新内容为准（D-46）")
        rec.must_eq(final.get("price_cents"), 5300, "审核结论价格以最新修改为准")
        rec.must_eq(final.get("tag_names"), ["教材书籍"], "标签保持既有教材书籍")
        _detail_images_ok(api, rec, ctx, "liu", final, 2)
        records = api.get(
            f"/products/{product['id']}/review-records", token=ctx.token("liu"), expected=200
        ).json()
        rec.must_eq(len(records), 2, "撤回+重提应形成 2 条审核记录")
        rec.must_eq(records[0].get("result"), "withdrawn", "第一条为撤回记录")
        rec.must_eq(records[1].get("result"), "approved", "第二条为通过记录")
        _register_product(ctx, "p_withdraw_resubmit", final, "liu", "listed")
        ctx.products["p_withdraw_resubmit"]["image_keys"] = list(final.get("image_keys") or [])
        _remember_case(ctx, "p_withdraw_resubmit", product["id"], case_id)
        step["detail"] = f"商品 #{product['id']} 撤回后重提审核通过，最终内容/价格均为认领后最新修改"

    # ------------------------------------------------------------------
    # 标签申请 approve_new（p_multi_tag）
    # ------------------------------------------------------------------
    with rec.step(
        "US-13-AC-01",
        us="US-13",
        sc="SC-10-01",
        desc="发布商品随附新标签申请「键盘配件」，审核通过时 approve_new 创建并生效新分类",
        expected="审核通过 200；商品标签含新分类；分类列表出现「键盘配件」",
    ) as step:
        goods_id = _cat(index, "电子产品")
        life_id = _cat(index, "生活用品")
        product, _payloads = _publish(
            api,
            rec,
            ctx,
            seller="zhang",
            title="机械键盘清理套装",
            description="键盘清理套装，含拔键器、清洁刷与清洁剂，适合机械键盘日常维护",
            price_cents=3200,
            tags=[
                {"category_id": goods_id},
                {"category_id": life_id},
                {"new_name": "键盘配件"},
            ],
            images=["product_keyboard.jpg", "product_second2.jpg"],
        )
        _register_product(ctx, "p_multi_tag", product, "zhang", "pending_review")
        apps = product.get("pending_tag_applications") or []
        rec.must_eq(len(apps), 1, "应生成一条待审新标签申请")
        rec.must_eq(apps[0].get("requested_name"), "键盘配件", "新标签申请名称")
        app_id = apps[0]["id"]
        case = _pending_case(api, ctx, product["id"])
        admin_claim_case(api, ctx, case["id"])
        case_detail = admin_case_detail(api, ctx, case["id"])
        rec.must(
            any(item.get("id") == app_id for item in case_detail.get("tag_applications") or []),
            "事项详情应展示待审标签申请",
        )
        resp = api.post(
            f"/admin/products/cases/{case['id']}/review",
            token=ctx.token("admin"),
            json_body={"result": "approved", "tag_decisions": [{"application_id": app_id, "decision": "approve_new"}]},
            expected=200,
        )
        rec.must("审核通过" in str((resp.json() or {}).get("detail")), "带标签决策审核通过")
        final = _assert_detail(api, ctx, product["id"], "zhang")
        rec.must_eq(final.get("status"), "listed", "审核通过后 listed")
        rec.must_in("键盘配件", final.get("tag_names") or [], "新标签随商品通过生效")
        rec.must_in("电子产品", final.get("tag_names") or [], "既有标签保留 1")
        rec.must_in("生活用品", final.get("tag_names") or [], "既有标签保留 2")
        categories = api.get("/categories", token=ctx.token("admin"), expected=200).json()
        created = next((cat for cat in categories if cat.get("name") == "键盘配件"), None)
        rec.must(created is not None, "approve_new 应在分类列表创建「键盘配件」")
        ctx.remember_category(
            "tag_new", {"id": created["id"], "name": "键盘配件", "status": created.get("status", "active")}
        )
        ctx.categories["p03_index"]["index"]["键盘配件"] = created["id"]
        _detail_images_ok(api, rec, ctx, "zhang", final, 2)
        _register_product(ctx, "p_multi_tag", final, "zhang", "listed")
        _remember_case(ctx, "p_multi_tag", product["id"], case["id"])
        step["detail"] = f"商品 #{product['id']} 通过时新建分类「键盘配件」并关联；2 张图片可读"

    with rec.step(
        "US-13-AC-07",
        us="US-13",
        sc="SC-03-05",
        desc="多标签商品按全部标签匹配：同时选择电子产品+生活用品仍命中，多选不重复计数",
        expected="category_ids 多选 AND 匹配命中 p_multi_tag；total 不因多标签重复",
    ) as step:
        goods_id = _cat(index, "电子产品")
        life_id = _cat(index, "生活用品")
        result = _search(api, ctx.token("chen"), category_ids=[goods_id, life_id])
        ids = [item["id"] for item in result.get("items", [])]
        rec.must_in(ctx.products["p_multi_tag"]["id"], ids, "多标签全部匹配应命中清理套装")
        rec.must_eq(len(ids), len(set(ids)), "多标签匹配结果不应重复计数")
        step["detail"] = f"多标签 AND 匹配命中清理套装（total={result.get('total')}）"

    # ------------------------------------------------------------------
    # 标签申请 map_alias（p_tag_alias）
    # ------------------------------------------------------------------
    with rec.step(
        "US-13-AC-01",
        us="US-13",
        sc="SC-10-01",
        desc="发布商品申请同义标签「宿舍用品」，审核通过时 map_alias 转为生活用品别名",
        expected="商品关联生活用品；分类别名含宿舍用品；按别名可筛选命中",
    ) as step:
        life_id = _cat(index, "生活用品")
        product, _payloads = _publish(
            api,
            rec,
            ctx,
            seller="liu",
            title="宿舍收纳盒",
            description="宿舍收纳盒，透明可叠放，九成新，可用于桌面整理",
            price_cents=1200,
            tags=[{"category_id": life_id}, {"new_name": "宿舍用品"}],
            images=["product_mug.jpg"],
        )
        _register_product(ctx, "p_tag_alias", product, "liu", "pending_review")
        apps = product.get("pending_tag_applications") or []
        rec.must_eq(len(apps), 1, "应生成一条待审同义标签申请")
        app_id = apps[0]["id"]
        case = _pending_case(api, ctx, product["id"])
        admin_claim_case(api, ctx, case["id"])
        resp = api.post(
            f"/admin/products/cases/{case['id']}/review",
            token=ctx.token("admin"),
            json_body={
                "result": "approved",
                "tag_decisions": [
                    {"application_id": app_id, "decision": "map_alias", "category_id": life_id}
                ],
            },
            expected=200,
        )
        rec.must("审核通过" in str((resp.json() or {}).get("detail")), "别名映射审核通过")
        final = _assert_detail(api, ctx, product["id"], "liu")
        rec.must_eq(final.get("tag_names"), ["生活用品"], "别名映射后商品关联原分类")
        categories = api.get("/categories", token=ctx.token("admin"), expected=200).json()
        life = next(cat for cat in categories if cat["id"] == life_id)
        rec.must_in("宿舍用品", life.get("aliases") or [], "分类别名应包含宿舍用品")
        ctx.categories["p03_index"]["index"]["宿舍用品"] = life_id
        by_alias = _search(api, ctx.token("chen"), category_names="宿舍用品")
        rec.must(
            any(item["id"] == product["id"] for item in by_alias.get("items", [])),
            "按新增别名筛选应命中该商品",
        )
        _register_product(ctx, "p_tag_alias", final, "liu", "listed")
        _remember_case(ctx, "p_tag_alias", product["id"], case["id"])
        step["detail"] = f"商品 #{product['id']} 同义名「宿舍用品」映射为生活用品别名并生效"

    # ------------------------------------------------------------------
    # 标签申请 reject（p_tag_reject）
    # ------------------------------------------------------------------
    with rec.step(
        "US-13-AC-02",
        us="US-13",
        sc="SC-10-02",
        desc="无合适标签的商品审核不通过：标签申请退回补充，分类不新增不公开",
        expected="rejected 且原因含退回补充；分类列表不出现「手工皮具」；按该名筛选无匹配",
    ) as step:
        product, _payloads = _publish(
            api,
            rec,
            ctx,
            seller="liu",
            title="手工皮具材料包",
            description="手工皮具 DIY 材料包，含工具、皮料与说明书",
            price_cents=6800,
            tags=[{"new_name": "手工皮具"}],
            images=["product_notes.jpg"],
        )
        _register_product(ctx, "p_tag_reject", product, "liu", "pending_review")
        apps = product.get("pending_tag_applications") or []
        rec.must_eq(len(apps), 1, "应生成一条待审标签申请")
        reject_reason = "退回补充：请更换或补充标签，当前无合适分类"
        _resp, case_id = _reject(api, ctx, product["id"], reject_reason)
        final = _assert_detail(api, ctx, product["id"], "liu")
        rec.must_eq(final.get("status"), "rejected", "标签退回后商品审核不通过")
        rec.must_eq(final.get("reject_reason"), reject_reason, "退回补充原因可见")
        categories = api.get("/categories", token=ctx.token("admin"), expected=200).json()
        rec.must(
            all(cat.get("name") != "手工皮具" for cat in categories),
            "未通过的标签申请不应创建分类",
        )
        by_name = _search(api, ctx.token("chen"), category_names="手工皮具")
        rec.must_eq(by_name.get("total"), 0, "未通过标签名筛选应无匹配")
        _register_product(ctx, "p_tag_reject", final, "liu", "rejected")
        _remember_case(ctx, "p_tag_reject", product["id"], case_id)
        step["detail"] = f"商品 #{product['id']} 因标签不合适按不通过记录退回补充；新分类未创建"

    # ------------------------------------------------------------------
    # 下架关闭待接受请求 + 重新上架（p_delist_sample / p_delist_req）
    # ------------------------------------------------------------------
    with rec.step(
        "US-02-AC-05",
        us="US-02",
        sc="SC-02-08",
        desc="zhang 的「山地自行车备件」下架时关闭待接受请求并注明商品已下架",
        expected="商品 delisted；请求 closed 且 close_reason=商品已下架",
    ) as step:
        product, _payloads = _publish(
            api,
            rec,
            ctx,
            seller="zhang",
            title="山地自行车备件",
            description="山地自行车备用轮胎与刹车片，适合维修替换",
            price_cents=5600,
            tags=[{"category_id": _cat(index, "运动器材", "运动健身")}],
            images=["product_bike.jpg"],
        )
        _register_product(ctx, "p_delist_req", product, "zhang", "pending_review")
        _resp, case_id = _approve(api, ctx, product["id"])
        current = _assert_detail(api, ctx, product["id"], "zhang")
        rec.must_eq(current.get("status"), "listed", "审核通过后 listed")
        request = api.post(
            "/trades/requests", token=ctx.token("chen"), json_body={"product_id": product["id"]}, expected=200
        ).json()
        ctx.remember_trade(
            "t_closed_bydelist",
            {"id": request["id"], "product_id": product["id"], "title": "下架关闭的待接受请求"},
            "chen",
            "zhang",
            "pending_acceptance",
        )
        delisted = api.post(f"/products/{product['id']}/delist", token=ctx.token("zhang"), expected=200).json()
        rec.must_eq(delisted.get("status"), "delisted", "下架后商品状态")
        trade = api.get(f"/trades/{request['id']}", token=ctx.token("chen"), expected=200).json()
        rec.must_eq(trade.get("status"), "closed", "下架后待接受请求应关闭")
        rec.must_eq(trade.get("close_reason"), "商品已下架", "请求关闭原因")
        ctx.update_trade("t_closed_bydelist", "closed")
        _register_product(ctx, "p_delist_req", delisted, "zhang", "delisted")
        _remember_case(ctx, "p_delist_req", product["id"], case_id)
        step["detail"] = f"商品 #{product['id']} 下架，请求 #{request['id']} 关闭（商品已下架）"

    with rec.step(
        "US-02-AC-06",
        us="US-02",
        sc="SC-02-16",
        desc="zhang 的「校园纪念马克杯」：下架可见性变化、重复下架 409、重新上架恢复公开，最终保持已下架",
        expected="delisted 后搜索/他人详情不可见；relist 200 恢复 listed 且可搜索；再次下架 409 校验",
    ) as step:
        product, _payloads = _publish(
            api,
            rec,
            ctx,
            seller="zhang",
            title="校园纪念马克杯",
            description="校园纪念马克杯，全新未使用，适合收藏",
            price_cents=2500,
            tags=[{"category_id": _cat(index, "生活用品")}],
            images=["product_mug.jpg"],
        )
        _register_product(ctx, "p_delist_sample", product, "zhang", "pending_review")
        _resp, case_id = _approve(api, ctx, product["id"])
        current = _assert_detail(api, ctx, product["id"], "zhang")
        rec.must_eq(current.get("status"), "listed", "审核通过后 listed")
        hit = _search(api, ctx.token("chen"), keyword="校园纪念马克杯")
        rec.must(hit.get("total", 0) >= 1, "在售商品应可被搜索")
        delisted = api.post(f"/products/{product['id']}/delist", token=ctx.token("zhang"), expected=200).json()
        rec.must_eq(delisted.get("status"), "delisted", "下架后状态")
        rec.must_eq(
            _search(api, ctx.token("chen"), keyword="校园纪念马克杯").get("total"), 0, "下架后应退出在售搜索"
        )
        api.expect_status(
            api.get(f"/products/{product['id']}", token=ctx.token("chen")),
            404,
            "已下架商品不向普通第三方开放详情",
        )
        again = api.post(f"/products/{product['id']}/delist", token=ctx.token("zhang"))
        api.expect_status(again, 409, "已下架商品重复下架应被拒绝")
        rec.must_eq((again.json() or {}).get("detail"), "仅公开可交易的商品可下架", "重复下架提示")
        relisted = api.post(f"/products/{product['id']}/relist", token=ctx.token("zhang"), expected=200).json()
        rec.must_eq(relisted.get("status"), "listed", "重新上架后应恢复公开可交易")
        rec.must(
            _search(api, ctx.token("chen"), keyword="校园纪念马克杯").get("total", 0) >= 1,
            "重新上架后应重新出现在搜索",
        )
        final = api.post(f"/products/{product['id']}/delist", token=ctx.token("zhang"), expected=200).json()
        rec.must_eq(final.get("status"), "delisted", "最终保持已下架（无请求）")
        _register_product(ctx, "p_delist_sample", final, "zhang", "delisted")
        _remember_case(ctx, "p_delist_sample", product["id"], case_id)
        step["detail"] = f"商品 #{product['id']} 下架→重新上架→再下架，可见性与 409 均符合预期"

    # ------------------------------------------------------------------
    # 编辑历史与买方访问（p_edit_history）
    # ------------------------------------------------------------------
    with rec.step(
        "US-02-AC-03",
        us="US-02",
        sc="SC-02-05",
        desc="在售商品编辑：不二审、不暂停展示、保留编辑历史，并向未结束请求买方发送变更通知",
        expected="编辑 200 保持 listed；编辑历史含前后内容；买方收到 product_edited 通知",
    ) as step:
        product, _payloads = _publish(
            api,
            rec,
            ctx,
            seller="zhang",
            title="高等数学辅导讲义",
            description="高等数学辅导讲义，含习题解析与典型例题",
            price_cents=3500,
            tags=[{"category_id": _cat(index, "教材书籍")}],
            images=["product_textbook.jpg"],
        )
        _register_product(ctx, "p_edit_history", product, "zhang", "pending_review")
        _resp, case_id = _approve(api, ctx, product["id"])
        current = _assert_detail(api, ctx, product["id"], "zhang")
        rec.must_eq(current.get("status"), "listed", "审核通过后 listed")
        request = api.post(
            "/trades/requests", token=ctx.token("chen"), json_body={"product_id": product["id"]}, expected=200
        ).json()
        ctx.remember_trade(
            "t_pending_edit_history",
            {"id": request["id"], "product_id": product["id"], "title": "编辑通知接收请求"},
            "chen",
            "zhang",
            "pending_acceptance",
        )
        review_records_before = api.get(
            f"/products/{product['id']}/review-records", token=ctx.token("zhang"), expected=200
        ).json()
        edited = api.patch(
            f"/products/{product['id']}",
            token=ctx.token("zhang"),
            json_body={
                "description": "高等数学辅导讲义，含习题解析与典型例题（2026-10 更新：补充适用教材版本）",
                "price_cents": 3300,
            },
            expected=200,
        ).json()
        rec.must_eq(edited.get("status"), "listed", "编辑后商品保持公开可交易")
        rec.must_eq(edited.get("pending_request_count"), 1, "编辑不关闭待接受请求")
        review_records_after = api.get(
            f"/products/{product['id']}/review-records", token=ctx.token("zhang"), expected=200
        ).json()
        rec.must_eq(len(review_records_after), len(review_records_before), "编辑不触发二次审核记录")
        history = api.get(
            f"/products/{product['id']}/edit-history", token=ctx.token("zhang"), expected=200
        ).json()
        rec.must(len(history) >= 1, "卖方应可查看编辑历史")
        latest = history[-1]
        rec.must_eq(latest.get("edit_type"), "edit", "编辑历史类型")
        rec.must_eq(latest.get("editor_id"), ctx.accounts["zhang"]["id"], "编辑历史记录修改人")
        rec.must(3300 in (latest.get("after_json") or {}).values(), "编辑历史应保存修改后内容")
        notices = api.get(
            "/notifications",
            token=ctx.token("chen"),
            params={"page_size": 50},
            expected=200,
        ).json()
        edited_notices = [
            item
            for item in notices.get("items", [])
            if item.get("type") == "product_edited" and item.get("link_id") == product["id"]
        ]
        rec.must(len(edited_notices) >= 1, "未结束请求买方应收到商品编辑通知")
        _register_product(ctx, "p_edit_history", edited, "zhang", "listed")
        _remember_case(ctx, "p_edit_history", product["id"], case_id)
        step["detail"] = f"商品 #{product['id']} 编辑并保留历史，请求未关闭，买方收到编辑通知"

    with rec.step(
        "US-02-AC-03",
        us="US-02",
        sc="SC-02-10",
        desc="编辑历史访问边界：买方（D-43）可看本人请求之后的变更，非参与第三方 403",
        expected="chen 200 且包含编辑记录；wang 403 仅本人请求对应内容及之后变更有访问权",
    ) as step:
        product = ctx.products["p_edit_history"]
        buyer_history = api.get(
            f"/products/{product['id']}/edit-history", token=ctx.token("chen"), expected=200
        ).json()
        rec.must(len(buyer_history) >= 1, "买方应可查看本人请求之后的编辑历史")
        rec.must_eq(buyer_history[-1].get("edit_type"), "edit", "买方可见编辑类型")
        outsider = api.get(f"/products/{product['id']}/edit-history", token=ctx.token("wang"))
        api.expect_status(outsider, 403, "非卖方非买方第三方不可查看完整编辑历史")
        rec.must_eq(
            (outsider.json() or {}).get("detail"),
            "仅本人请求对应内容及之后变更有访问权",
            "第三方编辑历史拒绝提示",
        )
        step["detail"] = f"商品 #{product['id']} 编辑历史：买方可见、第三方 403"

    # ------------------------------------------------------------------
    # 商品矩阵：发布→审核通过（p04 起消费）
    # ------------------------------------------------------------------
    for key, seller, title, description, price, tags, images in _simple_matrix(index):
        with rec.step(
            "US-02-AC-01",
            us="US-02",
            sc="SC-02-01",
            desc=f"发布并审核通过「{title}」：图片真实上传、签名 URL 可读、审核通过后公开",
            expected="发布 pending_review；认领审核通过 listed；图片 key/url 与详情回图可读；篡改 sig 403",
        ) as step:
            product, _payloads = _publish(
                api,
                rec,
                ctx,
                seller=seller,
                title=title,
                description=description,
                price_cents=price,
                tags=tags,
                images=images,
            )
            _register_product(ctx, key, product, seller, "pending_review")
            _resp, case_id = _approve(api, ctx, product["id"])
            final = _assert_detail(api, ctx, product["id"], seller)
            rec.must_eq(final.get("status"), "listed", "审核通过后商品应公开可交易")
            rec.must_eq(len(final.get("tag_names") or []), len(tags), "商品标签数量")
            _detail_images_ok(api, rec, ctx, seller, final, len(images))
            _remember_case(ctx, key, product["id"], case_id)
            _register_product(ctx, key, final, seller, "listed")
            step["detail"] = f"商品 #{product['id']}「{title}」listed，{len(images)} 张图片可读"

    # ------------------------------------------------------------------
    # 交易中商品禁止修改关键内容 + 管理员纠类（p_d48_b）
    # ------------------------------------------------------------------
    with rec.step(
        "US-02-AC-04",
        us="US-02",
        sc="SC-02-06",
        desc="交易中商品禁止卖方修改关键内容与主动下架；管理员有依据纠正分类并通知卖方",
        expected="PATCH 409 交易中禁止修改；下架 409 须先结束交易；纠类 200 且写编辑历史/通知",
    ) as step:
        goods_id = _cat(index, "电子产品")
        life_id = _cat(index, "生活用品")
        product, _payloads = _publish(
            api,
            rec,
            ctx,
            seller="liu",
            title="旧交易恢复冲突商品 B（数位笔）",
            description="数位笔，用于 D-48 恢复冲突验证 B（新交易锁单中）",
            price_cents=5200,
            tags=[{"category_id": goods_id}],
            images=["product_camera.jpg"],
        )
        _register_product(ctx, "p_d48_b", product, "liu", "pending_review")
        _resp, case_id = _approve(api, ctx, product["id"])
        listed = _assert_detail(api, ctx, product["id"], "liu")
        rec.must_eq(listed.get("status"), "listed", "d48_b 审核通过后 listed")
        request = api.post(
            "/trades/requests", token=ctx.token("chen"), json_body={"product_id": product["id"]}, expected=200
        ).json()
        accepted = api.post(f"/trades/{request['id']}/accept", token=ctx.token("liu"), expected=200)
        rec.must("已接受" in str((accepted.json() or {}).get("detail")), "卖方接受请求")
        ctx.remember_trade(
            "t_d48_new",
            {"id": request["id"], "product_id": product["id"], "title": "D-48 新锁单交易"},
            "chen",
            "liu",
            "in_progress",
        )
        locked = _assert_detail(api, ctx, product["id"], "liu")
        rec.must_eq(locked.get("status"), "in_transaction", "接受请求后商品应为交易中")
        blocked = api.patch(
            f"/products/{product['id']}", token=ctx.token("liu"), json_body={"title": "交易中禁止改名"}
        )
        api.expect_status(blocked, 409, "交易中商品禁止修改关键内容")
        rec.must_eq((blocked.json() or {}).get("detail"), "商品交易中，禁止修改关键内容", "交易中禁改提示")
        blocked_delist = api.post(f"/products/{product['id']}/delist", token=ctx.token("liu"))
        api.expect_status(blocked_delist, 409, "存在未结束锁单交易时禁止主动下架")
        rec.must_in(
            (blocked_delist.json() or {}).get("detail"),
            ("存在未结束的锁单交易，须先按交易规则结束交易", "仅公开可交易的商品可下架"),
            "交易中禁下架提示",
        )
        corrected = api.post(
            f"/admin/products/{product['id']}/correct-category",
            token=ctx.token("admin"),
            json_body={"category_ids": [life_id], "reason": "p03 造数：交易中分类纠正留据验证"},
            expected=200,
        )
        rec.must("分类纠正完成" in str((corrected.json() or {}).get("detail")), "管理员纠类成功")
        after = _assert_detail(api, ctx, product["id"], "liu")
        rec.must_eq(after.get("tag_names"), ["生活用品"], "纠类后商品分类更新")
        rec.must_eq(after.get("status"), "in_transaction", "纠类不改变交易中状态")
        ctx.categories["p03_index"]["index"].setdefault("生活用品", life_id)
        history = api.get(
            f"/products/{product['id']}/edit-history", token=ctx.token("liu"), expected=200
        ).json()
        correction = next((row for row in history if row.get("edit_type") == "category_correction"), None)
        rec.must(correction is not None, "纠类应写入编辑历史")
        rec.must_eq(correction.get("reason"), "p03 造数：交易中分类纠正留据验证", "纠类原因留据")
        rec.must_eq(correction.get("editor_id"), ctx.accounts["admin"]["id"], "纠类执行者记录")
        notices = api.get(
            "/notifications", token=ctx.token("liu"), params={"page_size": 50}, expected=200
        ).json()
        rec.must(
            any(
                item.get("title") == "商品分类已被平台纠正" and item.get("link_id") == product["id"]
                for item in notices.get("items", [])
            ),
            "纠类后应通知卖方",
        )
        trade = api.get(f"/trades/{request['id']}", token=ctx.token("chen"), expected=200).json()
        rec.must_eq(trade.get("status"), "in_progress", "纠类不改变交易状态")
        _register_product(ctx, "p_d48_b", after, "liu", "in_transaction")
        _remember_case(ctx, "p_d48_b", product["id"], case_id)
        step["detail"] = (
            f"商品 #{product['id']} 交易中禁改/禁下架均为 409；管理员纠类为生活用品并留历史与通知"
        )

    # ------------------------------------------------------------------
    # 交易中状态与公开性（US-09-AC-02）
    # ------------------------------------------------------------------
    with rec.step(
        "US-09-AC-02",
        us="US-09",
        sc="SC-02-06",
        desc="商品接受请求后转交易中：停止接受新请求，但登录用户仍可查看详情",
        expected="商品 in_transaction；其他用户详情 200；新请求 404",
    ) as step:
        product = ctx.products["p_d48_b"]
        trade = ctx.trades["t_d48_new"]
        detail = _assert_detail(api, ctx, product["id"], "chen")
        rec.must_eq(detail.get("status"), "in_transaction", "商品状态应为交易中")
        other_request = api.post(
            "/trades/requests", token=ctx.token("wang"), json_body={"product_id": product["id"]}
        )
        api.expect_status(other_request, 404, "交易中商品不接受新请求")
        rec.must_eq(
            (other_request.json() or {}).get("detail"), "商品不存在或当前不可请求", "交易中拒绝新请求提示"
        )
        mine = _seller_mine(api, ctx, "liu", product["id"])
        rec.must_eq(mine.get("status"), "in_transaction", "卖方我的商品状态为交易中")
        rec.must_eq(mine.get("pending_request_count"), 0, "交易中商品无待接受请求")
        step["detail"] = f"商品 #{product['id']} 交易中：登录用户详情可见、新请求 404（交易 #{trade['id']}）"

    # ------------------------------------------------------------------
    # D-48 商品 A：旧交易完成 → 默认下架 → 卖方重新上架
    # ------------------------------------------------------------------
    with rec.step(
        "US-09-AC-03",
        us="US-09",
        sc="SC-02-09",
        desc="D-48 商品 A 完成一笔旧交易（请求→接受→约定→双方确认完成）后默认下架，旧交易历史保留",
        expected="交易 completed；商品默认 delisted 且退出在售搜索；交易候选状态与转移历史可读",
    ) as step:
        product, _payloads = _publish(
            api,
            rec,
            ctx,
            seller="liu",
            title="旧交易恢复冲突商品 A（绘图仪）",
            description="绘图仪，用于 D-48 恢复冲突验证 A（旧交易已完成）",
            price_cents=11000,
            tags=[{"category_id": _cat(index, "电子产品")}],
            images=["product_camera.jpg", "product_second.jpg"],
        )
        _register_product(ctx, "p_d48_a", product, "liu", "pending_review")
        _resp, case_id = _approve(api, ctx, product["id"])
        listed = _assert_detail(api, ctx, product["id"], "liu")
        rec.must_eq(listed.get("status"), "listed", "d48_a 审核通过后 listed")
        request = api.post(
            "/trades/requests", token=ctx.token("chen"), json_body={"product_id": product["id"]}, expected=200
        ).json()
        ctx.remember_trade(
            "t_d48_old",
            {"id": request["id"], "product_id": product["id"], "title": "D-48 旧已完成交易"},
            "chen",
            "liu",
            "pending_acceptance",
        )
        api.post(f"/trades/{request['id']}/accept", token=ctx.token("liu"), expected=200)
        ctx.update_trade("t_d48_old", "in_progress")
        agreement = api.post(
            f"/trades/{request['id']}/agreements",
            token=ctx.token("liu"),
            json_body={
                "delivery_time": "2026-11-02 15:00",
                "delivery_location": "图书馆一楼大厅",
                "delivery_method": "当面交付",
                "amount_cents": 11000,
                "payment_method": "微信转账",
                "payment_timing": "当面交付时支付",
            },
            expected=200,
        ).json()
        api.post(
            f"/trades/{request['id']}/agreements/{agreement['id']}/confirm",
            token=ctx.token("chen"),
            expected=200,
        )
        first_confirm = api.post(
            f"/trades/{request['id']}/confirmations", token=ctx.token("liu"), json_body={}, expected=200
        )
        rec.must("已记录本人确认" in str((first_confirm.json() or {}).get("detail")), "单方完成确认记录")
        second_confirm = api.post(
            f"/trades/{request['id']}/confirmations", token=ctx.token("chen"), json_body={}, expected=200
        )
        rec.must("交易已完成" in str((second_confirm.json() or {}).get("detail")), "双方确认后交易完成")
        completed = api.get(f"/trades/{request['id']}", token=ctx.token("liu"), expected=200).json()
        rec.must_eq(completed.get("status"), "completed", "旧交易应已完成")
        ctx.update_trade("t_d48_old", "completed")
        transitions = api.get(
            f"/trades/{request['id']}/transitions", token=ctx.token("liu"), expected=200
        ).json()
        rec.must(any(row.get("to_status") == "completed" for row in transitions), "交易转移历史应记录 completed")
        delisted = _assert_detail(api, ctx, product["id"], "liu")
        rec.must_eq(delisted.get("status"), "delisted", "交易完成后商品默认下架")
        rec.must_eq(
            _search(api, ctx.token("zhang"), keyword="旧交易恢复冲突商品 A").get("total"),
            0,
            "交易完成后默认下架应退出在售搜索",
        )
        _register_product(ctx, "p_d48_a", delisted, "liu", "delisted")
        _remember_case(ctx, "p_d48_a", product["id"], case_id)
        step["detail"] = (
            f"商品 #{product['id']} 旧交易 #{request['id']} 已完成（转移历史可读），商品默认下架（供 p08 D-48 校验）"
        )

    with rec.step(
        "US-09-AC-04",
        us="US-09",
        sc="SC-02-16",
        desc="D-48 商品 A 在停止在售后由卖方重新上架：审核有效且资格允许时恢复公开可交易",
        expected="relist 200 listed；重新出现在售搜索；图片仍可读",
    ) as step:
        product = ctx.products["p_d48_a"]
        relisted = api.post(f"/products/{product['id']}/relist", token=ctx.token("liu"), expected=200).json()
        rec.must_eq(relisted.get("status"), "listed", "卖方明确继续上架后恢复公开可交易")
        now_listed = _assert_detail(api, ctx, product["id"], "liu")
        rec.must_eq(now_listed.get("status"), "listed", "d48_a 最终保留在售（旧交易已完成）")
        rec.must(
            _search(api, ctx.token("chen"), keyword="旧交易恢复冲突商品 A").get("total", 0) >= 1,
            "重新上架后应重新出现在在售搜索",
        )
        _detail_images_ok(api, rec, ctx, "liu", now_listed, 2)
        _register_product(ctx, "p_d48_a", now_listed, "liu", "listed")
        step["detail"] = f"商品 #{product['id']} 重新上架为 listed（旧交易历史保留，供 p08 D-48 校验）"

    # ------------------------------------------------------------------
    # 阶段收尾说明
    # ------------------------------------------------------------------
    rec.skip(
        "US-02-AC-07",
        us="US-02",
        sc="SC-02-17",
        desc="仅交易冻结时禁止发布/下架但允许无关合规编辑",
        reason="冻结由 p07/p08 制造，本阶段不造冻结数据；p08 异常交易观察可作为关联证据，但不回填为本 AC 的直接执行记录",
    )
    ctx.note(
        "p03 商品状态：p_review_pending=pending_review(未认领)、p_review_rejected=rejected、"
        "p_multi_tag/p_price_edge 等=listed、p_delist_sample/p_delist_req=delisted、"
        "p_d48_a=listed(旧交易 completed)、p_d48_b=in_transaction(新交易 in_progress)"
    )
    ctx.note("p03 审核事项：已登记 ctx.cases['review:<key>']，其中 p_review_pending 事项保留 pending 未认领")
