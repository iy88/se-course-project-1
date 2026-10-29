"""补充真实 API 核验：覆盖主 harness 未单独编号的少量场景分支。

对运行中的开发服务只做只读查询与"预期被拒绝"的负向写操作（不改变业务数据）。
用法：python supplementary_checks.py --base-url http://127.0.0.1:8000 --out supplementary.md
"""

from __future__ import annotations

import argparse
import json
import time

import httpx

RESULTS: list[dict] = []

PUBLIC_LIMIT = 50
PUBLIC_MAX_PAGES = 10


def check(check_id: str, desc: str, fn) -> None:
    try:
        detail = fn()
        RESULTS.append({"check_id": check_id, "desc": desc, "status": "PASS", "detail": detail or ""})
    except AssertionError as exc:
        RESULTS.append({"check_id": check_id, "desc": desc, "status": "FAIL", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        RESULTS.append({"check_id": check_id, "desc": desc, "status": "FAIL", "detail": f"{type(exc).__name__}: {exc}"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", default="supplementary.md")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    api = base + "/api/v1"
    c = httpx.Client(base_url=api, timeout=30)

    def login(email: str, password: str) -> dict:
        r = c.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, f"登录失败 {email}: {r.status_code} {r.text[:200]}"
        data = r.json()
        return {"token": data["access_token"], "user": data["user"], "headers": {"Authorization": f"Bearer {data['access_token']}"}}

    zhang = login("zhang@campus.edu", "secret123")
    li = login("li@campus.edu", "secret123")
    sun = login("sun@campus.edu", "secret123")
    admin = login("admin@campus.edu", "admin123456")
    extra = [zhang, li, sun]
    for email in ("chen@campus.edu", "liu@campus.edu", "wang@campus.edu"):
        try:
            extra.append(login(email, "secret123"))
        except AssertionError:
            pass

    # 基础数据：李同学的在售商品、争议交易、待接受请求、已终止交易
    li_products = c.get("/products/mine", headers=li["headers"]).json()
    li_listed = next((p for p in li_products if p["status"] == "listed"), None)

    def sc_02_03():
        assert li_listed, "缺少李同学在售商品"
        pid = li_listed["id"]
        before = c.get(f"/products/{pid}", headers=li["headers"]).json()
        r = c.patch(f"/products/{pid}", headers=zhang["headers"], json={"description": "非所有者修改尝试"})
        assert r.status_code == 404, f"非所有者修改应 404，实际 {r.status_code} {r.text[:200]}"
        after = c.get(f"/products/{pid}", headers=li["headers"]).json()
        assert before["description"] == after["description"], "商品内容被非所有者修改"
        return f"非所有者 PATCH 商品#{pid} → 404，内容未变化"

    def sc_06_04():
        # 从本人交易中找争议交易
        target = None
        for other in extra:
            for t in c.get("/trades/mine", headers=other["headers"]).json():
                if t["status"] == "disputed":
                    target = (t, other)
                    break
            if target:
                break
        assert target, "开发库中无争议交易样本"
        trade, owner = target
        ok = c.get(f"/trades/{trade['id']}", headers=owner["headers"])
        assert ok.status_code == 200, f"交易参与方读取争议交易应 200，实际 {ok.status_code}"
        deny = c.get(f"/trades/{trade['id']}", headers=sun["headers"])
        assert deny.status_code == 404, f"第三方读取争议交易应 404，实际 {deny.status_code}"
        # 未认领的争议事项详情对管理员拒绝（若有 pending trade_dispute）
        cases = c.get("/admin/cases?status=pending&case_type=trade_dispute", headers=admin["headers"]).json()
        if cases:
            r = c.get(f"/admin/cases/{cases[0]['id']}", headers=admin["headers"])
            assert r.status_code == 403, f"未认领争议事项详情应 403，实际 {r.status_code}"
            return f"争议交易#{trade['id']} 参与方 200／第三方 404；未认领争议事项#{cases[0]['id']} 详情 403"
        return f"争议交易#{trade['id']} 参与方 200／第三方 404（当前无 pending 争议事项）"

    def sc_05_12():
        # 卖方视角的待接受请求：连续读取状态保持，不自动过期
        seller_pending = [t for t in c.get("/trades/mine?role=seller", headers=zhang["headers"]).json() if t["status"] == "pending_acceptance"]
        seller_pending += [t for t in c.get("/trades/mine?role=seller", headers=li["headers"]).json() if t["status"] == "pending_acceptance"]
        assert seller_pending, "缺少待接受请求样本"
        trade = seller_pending[0]
        token = zhang["headers"] if c.get(f"/trades/{trade['id']}", headers=zhang["headers"]).status_code == 200 else li["headers"]
        first = c.get(f"/trades/{trade['id']}", headers=token).json()
        time.sleep(2)
        second = c.get(f"/trades/{trade['id']}", headers=token).json()
        assert first["status"] == second["status"] == "pending_acceptance", "待接受请求状态发生变化"
        return f"待接受请求#{trade['id']} 连续读取保持 pending_acceptance（未自动过期）"

    def sc_06_02():
        # 争议保持：参与方连续读取仍为 disputed（争议本身不自动推进/解除锁单）
        for other in extra:
            for t in c.get("/trades/mine", headers=other["headers"]).json():
                if t["status"] == "disputed":
                    first = c.get(f"/trades/{t['id']}", headers=other["headers"]).json()
                    time.sleep(2)
                    second = c.get(f"/trades/{t['id']}", headers=other["headers"]).json()
                    assert first["status"] == second["status"] == "disputed", "争议状态未保持"
                    return f"争议交易#{t['id']} 连续读取保持 disputed，锁单未自动解除"
        raise AssertionError("缺少争议交易样本")

    def sc_06_08():
        # 已终止交易的重复提交：返回 409 且状态不变
        for user in extra:
            for t in c.get("/trades/mine", headers=user["headers"]).json():
                if t["status"] == "terminated":
                    r = c.post(f"/trades/{t['id']}/cancel", headers=user["headers"], json={})
                    assert r.status_code == 409, f"已终止交易再次取消应 409，实际 {r.status_code} {r.text[:200]}"
                    again = c.get(f"/trades/{t['id']}", headers=user["headers"]).json()
                    assert again["status"] == "terminated", "重复提交改变了已终止交易状态"
                    return f"已终止交易#{t['id']} 重复取消 → 409，状态保持 terminated"
        raise AssertionError("缺少已终止交易样本")

    def us_10_ac_05():
        r = c.get("/admin/stats?from=1990-01-01&to=1990-01-02", headers=admin["headers"])
        assert r.status_code == 200, f"空范围统计应 200，实际 {r.status_code}"
        data = r.json()
        assert data["range"]["completed_trades"] == 0, f"空范围完成交易应为 0，实际 {data['range']['completed_trades']}"
        return "1990-01-01~1990-01-02 完成交易计数为 0（空结果不报错）"

    def us_07_ac_05():
        # BR-25 公开结果：必须由非举报人、非管理员的第三方登录用户读取 /reports/public；
        # 只使用举报人 /reports/mine 不能证明“向所有已登录用户公开”，也不能证明字段白名单。
        # 本检查只做只读 GET，不新增写库动作；确认前不可见依赖开发库现有未确认样本。
        me = c.get("/auth/me", headers=sun["headers"])
        assert me.status_code == 200, f"第三方读取 /auth/me 失败 {me.status_code} {me.text[:200]}"
        viewer_id = int(me.json()["id"])

        # 管理员列表每个状态最多返回前 200 条；按状态分别读取后按 id 去重。
        # 这是本检查的数据边界，不把边界外的举报当成已核对。
        admin_rows: dict[int, dict] = {}
        for report_status in ("handled", "unfounded", "pending", "processing"):
            resp = c.get("/admin/reports", headers=admin["headers"], params={"status": report_status})
            assert resp.status_code == 200, f"管理员读取举报列表（{report_status}）失败 {resp.status_code}"
            page_rows = resp.json()
            assert isinstance(page_rows, list), f"管理员举报列表（{report_status}）应返回 list"
            for row in page_rows:
                admin_rows[int(row["id"])] = row
        rows = list(admin_rows.values())
        confirmed = [
            row for row in rows
            if row.get("result_confirmed") and row.get("status") in ("handled", "unfounded")
        ]
        unconfirmed = [row for row in rows if not row.get("result_confirmed")]
        assert confirmed, "管理员近期举报列表中缺少已确认结果的样本"
        assert unconfirmed, "管理员近期举报列表中缺少未确认样本，无法验证确认前不可见"

        def reporter_id_of(row: dict) -> int | None:
            # 管理员列表的字段契约若未直接给出 reporter_id，则只对候选事项读取一次详情；
            # 该详情也是只读 GET，且仍属于管理员可见范围。
            if row.get("reporter_id") is not None:
                return int(row["reporter_id"])
            case_id = row.get("case_id")
            if not case_id:
                return None
            detail = c.get(f"/admin/cases/{case_id}", headers=admin["headers"])
            if detail.status_code != 200:
                return None
            report = (detail.json() or {}).get("report") or {}
            if report.get("reporter_id") is None:
                return None
            return int(report["reporter_id"])

        # 选“非当前第三方本人提交”的已确认样本；不要求它是管理员列表第一条，
        # 也不要求它出现在公开结果第一页。候选查询设上限，避免异常数据下无限扫描。
        sample = None
        reporter_lookups = 0
        # 与公开结果相同的 closed_at desc,id desc 顺序优先，降低样本落在分页上限之外的误报。
        for row in sorted(
            confirmed,
            key=lambda item: (str(item.get("closed_at") or ""), int(item["id"])),
            reverse=True,
        ):
            if row.get("public_result") is None:
                continue
            if reporter_lookups >= 50:
                break
            reporter_lookups += 1
            reporter_id = reporter_id_of(row)
            if reporter_id is None or reporter_id == viewer_id:
                continue
            sample = row
            break
        assert sample is not None, (
            "在管理员近期已确认举报中未找到 reporter_id 可确认且非当前第三方提交的样本"
            f"（已检查 {reporter_lookups} 条候选，候选查询上限 50）"
        )
        sample_id = int(sample["id"])

        # 匿名拒绝
        anonymous = c.get("/reports/public", params={"offset": 0, "limit": 20})
        assert anonymous.status_code == 401, f"匿名读取公开举报结果应 401，实际 {anonymous.status_code}"

        whitelist = {"id", "target_type", "status", "public_result", "closed_at"}
        private_fields = {
            "target_id", "reporter_id", "subject_id", "subject_user_id", "admin_id", "case_id",
            "reason", "detail", "result_reason", "evidence_keys", "supplements",
            "reporter", "admin", "email", "display_name",
        }
        public_rows: list[dict] = []
        seen_ids: set[int] = set()
        pages = 0
        reached_end = False
        for page in range(PUBLIC_MAX_PAGES):
            public = c.get(
                "/reports/public", headers=sun["headers"],
                params={"offset": page * PUBLIC_LIMIT, "limit": PUBLIC_LIMIT},
            )
            assert public.status_code == 200, (
                f"第三方登录用户读取 /reports/public 第 {page + 1} 页应 200，"
                f"实际 {public.status_code} {public.text[:200]}"
            )
            data = public.json()
            assert isinstance(data, list), f"/reports/public 应返回 list，实际 {type(data).__name__}"
            assert len(data) <= PUBLIC_LIMIT, f"limit={PUBLIC_LIMIT} 返回条数 {len(data)} 超出"
            pages += 1
            for row in data:
                assert set(row) == whitelist, f"公开结果字段应严格为 {sorted(whitelist)}，实际 {sorted(row)}"
                assert not (set(row) & private_fields), f"公开结果包含私有字段 {sorted(set(row) & private_fields)}"
                assert row.get("status") in ("handled", "unfounded"), f"公开结果状态非已处置：{row.get('status')}"
                assert row.get("public_result"), f"公开结果 #{row.get('id')} 的 public_result 为空"
                assert row.get("closed_at"), f"公开结果 #{row.get('id')} 缺少 closed_at"
                row_id = int(row["id"])
                assert row_id not in seen_ids, f"公开结果分页出现重复 id：{row_id}"
                seen_ids.add(row_id)
            keys = [(str(row["closed_at"]), int(row["id"])) for row in data]
            assert keys == sorted(keys, reverse=True), f"公开结果第 {page + 1} 页未按 closed_at desc,id desc 排序"
            public_rows.extend(data)
            if len(data) < PUBLIC_LIMIT:
                reached_end = True
                break

        all_keys = [(str(row["closed_at"]), int(row["id"])) for row in public_rows]
        assert all_keys == sorted(all_keys, reverse=True), "公开结果跨页顺序不是 closed_at desc,id desc"
        scope = "已读到末页" if reached_end else f"达到 {PUBLIC_MAX_PAGES} 页上限"
        assert sample_id in seen_ids, (
            f"已确认举报 #{sample_id} 未出现在公开结果本次读取范围"
            f"（{pages} 页/{len(public_rows)} 条，{scope}）；"
            + ("" if reached_end else "不据此推断上限外数据")
        )
        published = next(row for row in public_rows if int(row["id"]) == sample_id)
        assert published["public_result"] == sample["public_result"], "公开结果与管理员确认内容不一致"
        hidden = sorted({int(row["id"]) for row in unconfirmed} & seen_ids)
        assert not hidden, f"管理员确认前的举报出现在公开结果中：{hidden}"

        # 参数边界只读验证
        for params in ({"limit": 0}, {"limit": 51}, {"offset": -1}):
            bad = c.get("/reports/public", headers=sun["headers"], params=params)
            assert bad.status_code == 422, f"/reports/public 参数 {params} 应 422，实际 {bad.status_code}"

        boundary = "读到末页" if reached_end else f"达到 {PUBLIC_MAX_PAGES} 页上限"
        return (
            f"第三方 #{viewer_id} 读取 {pages} 页/{len(public_rows)} 条公开结果（{boundary}）；"
            f"非本人已确认 #{sample_id} 可见且 public_result 一致；"
            f"{len(unconfirmed)} 条边界内未确认举报均不可见；字段严格为 {sorted(whitelist)}；"
            f"数据边界：管理员各状态前 200 条、公开结果前 {PUBLIC_MAX_PAGES * PUBLIC_LIMIT} 条"
        )

    def us_08_ac_09():
        # 禁发范围：普通用户写拒绝、未登录拒绝、管理员可维护（真实数据存在）
        items = c.get("/prohibited-items", headers=zhang["headers"])
        assert items.status_code == 200
        create = c.post("/prohibited-items", headers=zhang["headers"], json={"group_name": "补充核验", "content": "普通用户无权"})
        assert create.status_code == 403, f"普通用户维护禁发范围应 403，实际 {create.status_code}"
        unauth = c.get("/prohibited-items")
        assert unauth.status_code == 401, f"未登录读取禁发范围应 401，实际 {unauth.status_code}"
        return f"禁发范围条目 {len(items.json())} 条；普通用户写 403、未登录读 401"

    def image_visibility():
        search = c.get("/products/search", headers=zhang["headers"], params={"keyword": "", "page_size": 50}).json()
        sample = next((p for p in search["items"] if p.get("image_url")), None)
        assert sample, "在售商品缺少图片 URL"
        url = sample["image_url"]
        full = base + url
        resp = httpx.get(full, timeout=20)
        assert resp.status_code == 200, f"图片读取失败 {resp.status_code}"
        assert resp.content[:2] == b"\xff\xd8" or resp.content[:8].startswith(b"\x89PNG"), "返回内容不是图片字节"
        tampered = full.replace("sig=", "sig=00")
        bad = httpx.get(tampered, timeout=20)
        assert bad.status_code == 403, f"篡改签名应 403，实际 {bad.status_code}"
        return f"商品#{sample['id']} 图片 {len(resp.content)} 字节可读，篡改签名 403"

    def dev_proxy():
        import http.client

        ok = []
        for port in (5173, 5174):
            conn = http.client.HTTPConnection("localhost", port, timeout=10)
            try:
                conn.request("GET", "/api/health")
                resp = conn.getresponse()
                body = resp.read()
                assert resp.status == 200 and json.loads(body).get("status") == "ok", f"{port} 代理异常 {resp.status}"
            finally:
                conn.close()
            ok.append(str(port))
        return f"{'、'.join(ok)} Vite 同源代理均能访问 /api/health，两前端可读取当前开发库数据"

    check("SUP-SC-02-03", "非商品所有者修改关键内容被拒绝且无副作用", sc_02_03)
    check("SUP-SC-06-04", "争议交易记录访问：参与方可见、第三方不可见、未认领事项管理员拒绝", sc_06_04)
    check("SUP-SC-05-12", "待接受请求状态保持（不自动过期）", sc_05_12)
    check("SUP-SC-06-02", "争议未解决时保持有争议与锁单", sc_06_02)
    check("SUP-SC-06-08", "已终止交易重复提交返回 409 且不改变状态", sc_06_08)
    check("SUP-US-10-AC-05", "统计空时间范围返回 0 不报错", us_10_ac_05)
    check("SUP-BR-25-public-results",
          "已确认举报结果经第三方 /reports/public 可见、未确认不可见且字段白名单", us_07_ac_05)
    check("SUP-US-08-AC-09", "禁发范围普通用户/未登录维护被拒绝", us_08_ac_09)
    check("SUP-IMG-SIGNED-URL", "商品图片经签名 URL 可读、篡改签名被拒绝", image_visibility)
    check("SUP-DEV-PROXY", "移动端 5173／管理端 5174 代理可访问真实 API", dev_proxy)

    lines = ["# 补充真实 API 核验（覆盖少量未单独编号的分支）", ""]
    lines.append("| 检查项 | 说明 | 状态 | 实际 |")
    lines.append("|---|---|---|---|")
    for row in RESULTS:
        detail = (row["detail"] or "").replace("|", "\\|")[:300]
        lines.append(f"| {row['check_id']} | {row['desc']} | {row['status']} | {detail} |")
    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    lines.append("")
    lines.append(f"合计 PASS={passed} FAIL={len(RESULTS) - passed}。均为对运行中开发服务的真实 HTTP 请求；负向写操作均验证被拒绝且未改变数据。")
    text = "\n".join(lines)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    print("\nwritten", args.out)


if __name__ == "__main__":
    main()
