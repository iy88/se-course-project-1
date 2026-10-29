"""p02 分类标签与禁发范围维护（US-13、US-02-AC-08；SC-10、SC-02-11/12）。

真实 HTTP 覆盖：
- 读取现有 10 个分类（登录用户可选标签）；
- 管理员主动新建「校园闲置」分类并保留；
- 「运动器材」改名为「运动健身」：旧名自动成为别名，旧名搜索可命中；删除别名后旧名
  搜索/筛选不再命中，分类身份与商品归属不变；
- 自建商品关联「临时分类」并审核通过后停用该分类：已有关联商品保留、有在售商品仍可
  筛选，新发布不可再选该标签；已关联分类仅可停用、未关联分类可逻辑删除；
- 禁发范围：登录用户可独立读取；管理员新增/更新/删除条目后读取为最新内容；
  普通用户写 403、未登录读写 401；
- 标签申请的三种审核决策由 p03 完成，本阶段只准备分类与读取。

对象登记：ctx.categories（seed/admin_created/renamed/deact_cat/deleted_cat）、ctx.items。
"""

from __future__ import annotations

from e2e_support import (
    DEFAULT_PASSWORD,
    admin_claim_case,
    admin_list_cases,
    login_account,
    upload_image,
)

PHASE_ID = "p02"

SEED_CATEGORY_NAMES = [
    "教材书籍",
    "电子产品",
    "生活用品",
    "运动器材",
    "服饰鞋包",
    "宿舍家电",
    "美妆个护",
    "文具用品",
    "乐器",
    "其他闲置",
]


def _login_seed(api, ctx, key: str, email: str, password: str, display: str) -> None:
    if key not in ctx.accounts:
        login_account(api, ctx, key, email, password, display_name=display)


def _ensure_seller(api, ctx) -> None:
    """p02 独立运行时的账户准备（chen 由 p01 注册，缺失则补注册）。"""
    _login_seed(api, ctx, "admin", "admin@campus.edu", "admin123456", "平台管理员")
    _login_seed(api, ctx, "zhang", "zhang@campus.edu", "secret123", "张同学")
    if "chen" not in ctx.accounts:
        from e2e_support import ensure_account

        ensure_account(api, ctx, "chen", "chen@campus.edu", "陈同学")


def _categories(api, ctx) -> list[dict]:
    return api.get("/categories", token=ctx.token("admin"), expected=200).json()


def _category_by_name_or_alias(categories: list[dict], *names: str) -> dict | None:
    by_name = {cat["name"]: cat for cat in categories}
    for name in names:
        if name in by_name:
            return by_name[name]
    for cat in categories:
        aliases = cat.get("aliases") or []
        if any(alias in names for alias in aliases):
            return cat
    return None


def _search(api, token: str, **params) -> dict:
    return api.get("/products/search", token=token, params=params, expected=200).json()


def _pending_review_case(api, ctx, product_id: int) -> dict | None:
    cases = admin_list_cases(api, ctx, status="pending", case_type="product_review")
    return next((case for case in cases if case.get("product_id") == product_id), None)


def _approve_review(api, ctx, rec, product_id: int) -> dict:
    case = _pending_review_case(api, ctx, product_id)
    if case is None:
        raise AssertionError(f"商品 #{product_id} 缺少待处理审核事项")
    admin_claim_case(api, ctx, case["id"])
    resp = api.post(
        f"/admin/products/cases/{case['id']}/review",
        token=ctx.token("admin"),
        json_body={"result": "approved"},
        expected=200,
    )
    rec.must("审核通过" in str((resp.json() or {}).get("detail")), "管理员审核通过提示")
    detail = api.get(f"/products/{product_id}", token=ctx.token("chen"), expected=200).json()
    rec.must_eq(detail.get("status"), "listed", f"商品 #{product_id} 审核通过后应为 listed")
    return detail


def run(ctx, api, rec):  # noqa: ANN001
    _ensure_seller(api, ctx)

    # ------------------------------------------------------------------
    # 读取现有 10 个分类（US-13、SC-10-03）
    # ------------------------------------------------------------------
    with rec.step(
        "US-13-AC-03",
        us="US-13",
        sc="SC-10-03",
        desc="读取现有分类：包含 10 个初始分类，登录用户可按标签筛选发布",
        expected="200 且包含全部初始分类与别名集合",
    ) as step:
        categories = _categories(api, ctx)
        by_name = {cat["name"]: cat for cat in categories}
        missing = [name for name in SEED_CATEGORY_NAMES if name not in by_name]
        rec.must_eq(missing, [], f"现有分类应包含初始 10 个分类，缺少 {missing}")
        ctx.categories["seed"] = {name: by_name[name]["id"] for name in SEED_CATEGORY_NAMES}
        for name in SEED_CATEGORY_NAMES:
            cat = by_name[name]
            ctx.inventory_add("category", f"seed:{name}", cat["id"], name, cat.get("status", "active"))
        normal_cats = api.get("/categories", token=ctx.token("zhang"), expected=200).json()
        rec.must(len(normal_cats) >= 10, "普通登录用户应可读取分类列表")
        step["detail"] = f"读取 {len(categories)} 个分类，初始 10 分类齐全"

    # ------------------------------------------------------------------
    # 管理员新建分类（US-13、SC-10-03）
    # ------------------------------------------------------------------
    with rec.step(
        "US-13-AC-03",
        us="US-13",
        sc="SC-10-03",
        desc="管理员主动新建「校园闲置」公共分类并保留在分类列表",
        expected="新建 200；列表可见；重复名称 400",
    ) as step:
        existing = _category_by_name_or_alias(_categories(api, ctx), "校园闲置")
        if existing is not None:
            cat = existing
            step["detail"] = "「校园闲置」已存在（重跑场景），复用并核对"
        else:
            resp = api.post(
                "/categories", token=ctx.token("admin"), json_body={"name": "校园闲置"}, expected=200
            )
            cat = resp.json()
            rec.must_eq(cat.get("name"), "校园闲置", "新建分类名称")
            rec.must_eq(cat.get("status"), "active", "新建分类状态")
            step["detail"] = "管理员新建「校园闲置」分类成功"
        ctx.remember_category("admin_created", {"id": cat["id"], "name": cat["name"], "status": cat["status"]})
        listed = _category_by_name_or_alias(_categories(api, ctx), "校园闲置")
        rec.must(listed is not None, "分类列表应包含「校园闲置」")
        dup = api.post("/categories", token=ctx.token("admin"), json_body={"name": "校园闲置"})
        api.expect_status(dup, 400, "同名分类重复创建应被拒绝")
        rec.must_eq((dup.json() or {}).get("detail"), "同名标签或别名已存在", "同名分类提示")

    # ------------------------------------------------------------------
    # 改主名保留旧别名，旧名可命中（US-13-AC-03、SC-10-03）
    # ------------------------------------------------------------------
    with rec.step(
        "US-13-AC-03",
        us="US-13",
        sc="SC-10-03",
        desc="「运动器材」改名为「运动健身」：旧名保留为别名，旧名筛选/搜索仍可命中，商品归属不变",
        expected="改名 200；aliases 含旧名；旧名 category_names 搜索命中该分类商品",
    ) as step:
        categories = _categories(api, ctx)
        renamed = _category_by_name_or_alias(categories, "运动健身")
        alias_ready = False
        if renamed is None:
            source = _category_by_name_or_alias(categories, "运动器材")
            rec.must(source is not None, "初始分类应包含「运动器材」")
            resp = api.patch(
                f"/categories/{source['id']}",
                token=ctx.token("admin"),
                json_body={"name": "运动健身"},
                expected=200,
            )
            renamed = resp.json()
            rec.must_eq(renamed.get("name"), "运动健身", "改名后主名")
            rec.must_in("运动器材", renamed.get("aliases") or [], "改名后旧主名应保留为别名")
            step["detail"] = "「运动器材」改名为「运动健身」，旧名保留为别名"
        else:
            alias_ready = "运动器材" in (renamed.get("aliases") or [])
            if not alias_ready:
                resp = api.post(
                    f"/categories/{renamed['id']}/aliases",
                    token=ctx.token("admin"),
                    json_body={"name": "运动器材"},
                    expected=200,
                )
                rec.must_in("运动器材", (resp.json() or {}).get("aliases") or [], "重跑场景补建旧名别名")
                alias_ready = True
            step["detail"] = "「运动健身」已存在（重跑场景），核对旧名别名"
        cat_id = renamed["id"]
        ctx.remember_category(
            "renamed",
            {
                "id": cat_id,
                "name": renamed["name"],
                "status": renamed.get("status", "active"),
                "old_name": "运动器材",
                "new_name": "运动健身",
            },
        )
        # 同一分类身份：更新分类清单中旧名行，避免报告出现同名分类两行
        for row in ctx.inventory:
            if row.get("kind") == "category" and row.get("id") == cat_id and row.get("key") != "renamed":
                row["label"] = renamed["name"]
        # 旧名（别名）作为分类名筛选可命中该分类在售商品
        by_alias = _search(api, ctx.token("zhang"), category_names="运动器材")
        rec.must(by_alias.get("total", 0) >= 1, "旧名作为别名应能筛选出该分类在售商品")
        ctx.categories["renamed"]["search_by_alias_total"] = by_alias.get("total")

    # ------------------------------------------------------------------
    # 删除别名后旧名不再识别，分类身份与商品归属不变（US-13-AC-03、SC-10-04）
    # ------------------------------------------------------------------
    with rec.step(
        "US-13-AC-03",
        us="US-13",
        sc="SC-10-04",
        desc="删除「运动器材」别名后，旧名搜索/筛选按无匹配处理，新主名与商品归属不变",
        expected="删除别名 200；旧名 category_names 搜索 total=0 且 message=无匹配商品；新名仍有商品",
    ) as step:
        renamed = ctx.categories["renamed"]
        categories = _categories(api, ctx)
        current = next(cat for cat in categories if cat["id"] == renamed["id"])
        rec.must_eq(current.get("name"), "运动健身", "分类主名应为新名")
        if "运动器材" in (current.get("aliases") or []):
            resp = api.delete(
                f"/categories/{renamed['id']}/aliases/by-name",
                token=ctx.token("admin"),
                params={"name": "运动器材"},
                expected=200,
            )
            rec.must_eq((resp.json() or {}).get("detail"), "别名已移除", "删除别名提示")
        else:
            ctx.note("「运动器材」别名已移除（重跑场景），直接核对删除后行为")
        by_old = _search(api, ctx.token("zhang"), category_names="运动器材")
        rec.must_eq(by_old.get("total"), 0, "删除别名后旧名筛选应无匹配")
        rec.must_eq(by_old.get("message"), "无匹配商品", "删除别名后旧名搜索提示")
        by_new = _search(api, ctx.token("zhang"), category_names="运动健身")
        rec.must(by_new.get("total", 0) >= 1, "新主名仍应筛选出原分类商品")
        ctx.categories["renamed"]["search_after_alias_removed_total"] = by_old.get("total")
        # 历史商品归属不变：旧别名商品仍在运动健身分类下
        by_id = _search(api, ctx.token("zhang"), category_ids=renamed["id"])
        rec.must(by_id.get("total", 0) >= 1, "分类身份不变，按分类 ID 仍可筛选原商品")
        step["detail"] = "删除别名后旧名筛选 total=0（无匹配商品），新主名与商品归属不变"

    # ------------------------------------------------------------------
    # 停用分类：沿用已关联在售商品（US-13-AC-04、SC-10-03）
    # ------------------------------------------------------------------
    with rec.step(
        "US-13-AC-04",
        us="US-13",
        sc="SC-10-03",
        desc="自建「临时分类」并发布商品审核通过后停用：已有商品保留、在售商品仍可筛选，新发布不可选",
        expected="停用 200 status=disabled；按分类筛选仍命中；新发布 400 所选标签已停用",
    ) as step:
        categories = _categories(api, ctx)
        deact = _category_by_name_or_alias(categories, "临时分类")
        if deact is None:
            deact = api.post(
                "/categories", token=ctx.token("admin"), json_body={"name": "临时分类"}, expected=200
            ).json()
        deact_id = deact["id"]
        ctx.remember_category(
            "deact_cat", {"id": deact_id, "name": "临时分类", "status": deact.get("status", "active")}
        )
        # 自建 1 件商品关联该分类，并走真实审核使其在售
        my_products = api.get("/products/mine", token=ctx.token("chen"), expected=200).json()
        product = next((item for item in my_products if item.get("title") == "临时分类验证商品"), None)
        if product is None:
            image = upload_image(api, ctx.token("chen"), "product_notes.jpg", namespace="product")
            rec.must(bool(image.get("key")) and bool(image.get("url")), "临时商品图片上传应返回 key/url")
            publish = api.post(
                "/products",
                token=ctx.token("chen"),
                json_body={
                    "title": "临时分类验证商品",
                    "description": "用于验证分类停用后已有商品保留、仍可筛选（p02 造数）",
                    "price_cents": 1500,
                    "image_keys": [image["key"]],
                    "tags": [{"category_id": deact_id}],
                },
                expected=200,
            )
            product = publish.json()
            rec.must_eq(product.get("status"), "pending_review", "发布后应待审核")
            product = _approve_review(api, ctx, rec, product["id"])
            ctx.remember_product("p_cat_deact", product, "chen", product.get("status"))
        else:
            rec.must_eq(product.get("status"), "listed", "临时分类验证商品应处于在售状态")
            ctx.remember_product("p_cat_deact", product, "chen", product.get("status"))
        # 停用分类（关联过商品的分类仅可停用，不可删除）
        if product.get("tag_ids") and deact_id in product["tag_ids"]:
            delete_used = api.delete(f"/categories/{deact_id}", token=ctx.token("admin"))
            api.expect_status(delete_used, 400, "已关联商品分类不可删除，仅可停用")
            rec.must_eq(
                (delete_used.json() or {}).get("detail"), "该标签已关联商品，仅可停用", "关联商品分类删除提示"
            )
        disabled = api.patch(
            f"/categories/{deact_id}",
            token=ctx.token("admin"),
            json_body={"status": "disabled"},
            expected=200,
        )
        rec.must_eq((disabled.json() or {}).get("status"), "disabled", "停用后分类状态")
        ctx.categories["deact_cat"].update({"id": deact_id, "name": "临时分类", "status": "disabled"})
        for row in ctx.inventory:
            if row.get("kind") == "category" and row.get("key") == "deact_cat":
                row["state"] = "disabled"
                break
        # 有在售商品：筛选入口保留（按 ID 与名称均可命中）
        by_id = _search(api, ctx.token("zhang"), category_ids=deact_id)
        rec.must(any(item["id"] == product["id"] for item in by_id.get("items", [])), "停用后按分类筛选仍应命中在售商品")
        by_name = _search(api, ctx.token("zhang"), category_names="临时分类")
        rec.must(any(item["id"] == product["id"] for item in by_name.get("items", [])), "停用分类名称筛选仍应命中在售商品")
        # 新发布不可选停用标签
        blocked = api.post(
            "/products",
            token=ctx.token("chen"),
            json_body={
                "title": "停用分类新发布校验",
                "description": "新发布选择停用标签应被拒绝",
                "price_cents": 100,
                "image_keys": [upload_image(api, ctx.token("chen"), "product_notes.jpg")["key"]],
                "tags": [{"category_id": deact_id}],
            },
        )
        api.expect_status(blocked, 400, "新发布选择停用标签应被拒绝")
        rec.must_eq((blocked.json() or {}).get("detail"), "所选标签已停用：临时分类", "停用标签发布提示")
        detail = api.get(f"/products/{product['id']}", token=ctx.token("chen"), expected=200).json()
        rec.must_eq(detail.get("status"), "listed", "停用分类不影响已关联商品在售状态")
        rec.must_in("临时分类", detail.get("tag_names") or [], "已关联商品保留停用前标签")
        step["detail"] = "关联商品审核通过后停用分类；筛选保留、新发布 400；已关联分类删除被拒"

    # ------------------------------------------------------------------
    # 逻辑删除从未关联的分类（US-13-AC-05、SC-10-03）
    # ------------------------------------------------------------------
    with rec.step(
        "US-13-AC-05",
        us="US-13",
        sc="SC-10-03",
        desc="从未关联商品的「未关联分类」可逻辑删除，删除后分类列表与筛选均不再出现",
        expected="删除 200 已删除；列表不含；未知名称筛选无匹配",
    ) as step:
        categories = _categories(api, ctx)
        deleted = _category_by_name_or_alias(categories, "未关联分类")
        if deleted is None:
            deleted = api.post(
                "/categories", token=ctx.token("admin"), json_body={"name": "未关联分类"}, expected=200
            ).json()
        resp = api.delete(f"/categories/{deleted['id']}", token=ctx.token("admin"), expected=200)
        rec.must_eq((resp.json() or {}).get("detail"), "已删除", "逻辑删除提示")
        ctx.remember_category(
            "deleted_cat", {"id": deleted["id"], "name": "未关联分类", "status": "deleted"}
        )
        after = _categories(api, ctx)
        rec.must(all(cat["id"] != deleted["id"] for cat in after), "逻辑删除后分类列表不再出现")
        by_name = _search(api, ctx.token("zhang"), category_names="未关联分类")
        rec.must_eq(by_name.get("total"), 0, "删除后的分类名称筛选应无匹配")
        step["detail"] = "未关联分类逻辑删除成功，列表与筛选均不再出现"

    # ------------------------------------------------------------------
    # 分类维护权限（US-13-AC-03、SC-10-03）
    # ------------------------------------------------------------------
    with rec.step(
        "US-13-AC-03",
        us="US-13",
        sc="SC-10-03",
        desc="分类维护仅管理员可写：普通用户创建/改名/别名/删除 403，未登录写 401",
        expected="普通用户 403 需要平台管理员权限；未登录 401",
    ) as step:
        admin_created = ctx.categories["admin_created"]
        token = ctx.token("zhang")
        create = api.post("/categories", token=token, json_body={"name": "普通用户越权分类"})
        api.expect_status(create, 403, "普通用户创建分类应被拒绝")
        rec.must_eq((create.json() or {}).get("detail"), "需要平台管理员权限", "普通用户创建分类提示")
        rename = api.patch(f"/categories/{admin_created['id']}", token=token, json_body={"name": "越权改名"})
        api.expect_status(rename, 403, "普通用户改名应被拒绝")
        alias = api.post(
            f"/categories/{admin_created['id']}/aliases", token=token, json_body={"name": "越权别名"}
        )
        api.expect_status(alias, 403, "普通用户新增别名应被拒绝")
        delete = api.delete(f"/categories/{admin_created['id']}", token=token)
        api.expect_status(delete, 403, "普通用户删除分类应被拒绝")
        anonymous = api.post("/categories", json_body={"name": "未登录分类"})
        api.expect_status(anonymous, 401, "未登录创建分类应返回 401")
        api.expect_status(api.patch(f"/categories/{admin_created['id']}", json_body={"name": "未登录改名"}), 401, "未登录改名 401")
        api.expect_status(api.delete(f"/categories/{admin_created['id']}"), 401, "未登录删除 401")
        # 越权尝试未生效
        current = next(cat for cat in _categories(api, ctx) if cat["id"] == admin_created["id"])
        rec.must_eq(current.get("name"), "校园闲置", "越权改名不应生效")
        rec.must_eq(current.get("aliases"), [], "越权别名不应生效")
        step["detail"] = "普通用户分类写操作全 403，未登录 401，越权未产生副作用"

    # ------------------------------------------------------------------
    # 禁发范围读取（US-02-AC-08、SC-02-11）
    # ------------------------------------------------------------------
    with rec.step(
        "US-02-AC-08",
        us="US-02",
        sc="SC-02-11",
        desc="普通登录用户在未提交商品前即可独立读取管理员维护的禁发范围",
        expected="200 且包含种子 6 组禁发类别；未登录读取 401",
    ) as step:
        items = api.get("/prohibited-items", token=ctx.token("zhang"), expected=200).json()
        groups = {item.get("group_name") for item in items}
        for expected_group in (
            "法律法规禁止流通的物品",
            "危险品与管制物品",
            "活体动物",
            "药品与医疗器械",
            "账号与虚拟财产",
            "无关服务或推广内容",
        ):
            rec.must_in(expected_group, groups, f"禁发范围应包含「{expected_group}」")
        api.expect_status(api.get("/prohibited-items"), 401, "未登录读取禁发范围应返回 401")
        ctx.items["prohibited:list"] = {
            "kind": "prohibited",
            "key": "list",
            "id": None,
            "label": "禁发范围",
            "state": f"{len(items)} 项",
            "extra": {"ids": [item["id"] for item in items]},
        }
        step["detail"] = f"普通用户读取 {len(items)} 条禁发范围，6 组种子类别齐全；未登录 401"

    # ------------------------------------------------------------------
    # 禁发范围管理员维护（US-02-AC-08、SC-02-12）
    # ------------------------------------------------------------------
    with rec.step(
        "US-02-AC-08",
        us="US-02",
        sc="SC-02-12",
        desc="管理员新增/更新禁发条目后普通用户读取为最新范围；删除临时条目后不再出现",
        expected="新增/更新/删除 200；读取可见最新内容；普通用户写 403",
    ) as step:
        admin_token = ctx.token("admin")
        # 普通用户写拒绝
        deny_create = api.post(
            "/prohibited-items",
            token=ctx.token("zhang"),
            json_body={"group_name": "普通用户组", "content": "普通用户不应能维护", "sort": 0},
        )
        api.expect_status(deny_create, 403, "普通用户新增禁发条目应被拒绝")
        rec.must_eq((deny_create.json() or {}).get("detail"), "需要平台管理员权限", "普通用户禁发写提示")
        # 管理员新增 1 条细目（保留）
        created = api.post(
            "/prohibited-items",
            token=admin_token,
            json_body={
                "group_name": "校园管理补充",
                "content": "p02 新增：伪造校园证件、代刷课等服务（管理员维护样例）",
                "sort": 90,
            },
            expected=200,
        ).json()
        ctx.remember_item(
            "prohibited",
            "created",
            created["id"],
            created.get("content", "新增禁发条目"),
            "active",
            {"group_name": created.get("group_name")},
        )
        # 管理员更新 1 条种子细目（保留最新内容）
        items = api.get("/prohibited-items", token=admin_token, expected=200).json()
        seed_item = items[0]
        updated = api.put(
            f"/prohibited-items/{seed_item['id']}",
            token=admin_token,
            json_body={
                "group_name": seed_item["group_name"],
                "content": seed_item["content"] + "（p02 更新：保留最新维护内容）",
                "sort": seed_item.get("sort", 0),
            },
            expected=200,
        ).json()
        rec.must(updated["content"].endswith("（p02 更新：保留最新维护内容）"), "更新后返回最新内容")
        ctx.remember_item(
            "prohibited",
            "updated_seed",
            seed_item["id"],
            updated["content"],
            "active",
            {"group_name": updated["group_name"]},
        )
        # 普通用户读取最新范围
        latest = api.get("/prohibited-items", token=ctx.token("zhang"), expected=200).json()
        latest_contents = [item["content"] for item in latest]
        rec.must(created["content"] in latest_contents, "普通用户应读到新增条目")
        rec.must(updated["content"] in latest_contents, "普通用户应读到更新后的细目")
        # 新建临时条目后删除，验证删除路径
        temp = api.post(
            "/prohibited-items",
            token=admin_token,
            json_body={"group_name": "临时维护组", "content": "p02 临时条目（随后删除）", "sort": 99},
            expected=200,
        ).json()
        deleted = api.delete(f"/prohibited-items/{temp['id']}", token=admin_token, expected=200)
        rec.must_eq((deleted.json() or {}).get("detail"), "已删除", "删除禁发条目提示")
        ctx.remember_item("prohibited", "temp_deleted", temp["id"], temp["content"], "deleted")
        after = api.get("/prohibited-items", token=ctx.token("zhang"), expected=200).json()
        rec.must(all(item["id"] != temp["id"] for item in after), "删除后的禁发条目不应再出现")
        # 普通用户更新/删除种子条目被拒
        deny_update = api.put(
            f"/prohibited-items/{seed_item['id']}",
            token=ctx.token("zhang"),
            json_body={"group_name": "越权", "content": "越权更新", "sort": 0},
        )
        api.expect_status(deny_update, 403, "普通用户更新禁发条目应被拒绝")
        deny_delete = api.delete(f"/prohibited-items/{seed_item['id']}", token=ctx.token("zhang"))
        api.expect_status(deny_delete, 403, "普通用户删除禁发条目应被拒绝")
        api.expect_status(
            api.post(
                "/prohibited-items",
                json_body={"group_name": "未登录组", "content": "未登录写入", "sort": 0},
            ),
            401,
            "未登录新增禁发条目应返回 401",
        )
        step["detail"] = "新增/更新保留、临时条目删除；普通用户读最新范围、写 403；未登录 401"

    # ------------------------------------------------------------------
    # 阶段说明
    # ------------------------------------------------------------------
    ctx.note(
        "p02 分类状态：校园闲置=enabled、运动健身(旧名 运动器材别名已删)、临时分类=disabled、"
        "未关联分类=deleted；标签申请三种决策（approve_new/map_alias/reject）由 p03 审核覆盖"
    )
