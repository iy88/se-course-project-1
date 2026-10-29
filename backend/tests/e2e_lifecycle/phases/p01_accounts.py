"""p01 账户生命周期与访问控制（US-01、SC-01）。

真实 HTTP 覆盖：
- 种子账户 admin/zhang/li/wang 邮箱+密码登录、/auth/me；
- 注册验证码流程：错误验证码被拒、正确验证码创建账户并分配唯一用户 ID；
- 未验证邮箱、持其他邮箱验证码注册均被拒且不创建账户（AC-08/SC-01-11）；
- 重复邮箱注册被拒、原账户保留（AC-02/SC-01-02）；
- 错误密码登录被拒、连续 5 次失败不锁定（AC-03/SC-01-03）；
- 退出登录与未登录访问业务内容 401（AC-03/SC-01-05/08）；
- 忘记密码经绑定邮箱验证重置，用户 ID 不变（AC-04/SC-01-04）；
- 改密校验当前密码、换邮箱新旧双验证+唯一性（AC-05/SC-01-08/09）；
- 改名后历史业务仍归属原用户 ID（AC-06/SC-01-10）；
- qian 封禁：可登录/读公共内容/写拒绝/申诉入口，解除后恢复 normal（AC-07/SC-01-06/07）。

账号矩阵（ctx.accounts）：admin/zhang/li/wang/chen/liu/zhao/qian/wu/sun/emailchg/reset。
"""

from __future__ import annotations

import re

from e2e_support import DEFAULT_PASSWORD, login_account, refresh_me

PHASE_ID = "p01"

SEED_ACCOUNTS = [
    ("admin", "admin@campus.edu", "admin123456", "平台管理员"),
    ("zhang", "zhang@campus.edu", "secret123", "张同学"),
    ("li", "li@campus.edu", "secret123", "李同学"),
    ("wang", "wang@campus.edu", "secret123", "王同学"),
]

NEW_ACCOUNTS = [
    ("liu", "liu@campus.edu", "刘同学"),
    ("zhao", "zhao@campus.edu", "赵同学"),
    ("qian", "qian@campus.edu", "钱同学"),
    ("wu", "wu@campus.edu", "吴同学"),
    ("sun", "sun@campus.edu", "孙同学"),
]

EMAILCHG_OLD = "email.before@campus.edu"
EMAILCHG_NEW = "email.after@campus.edu"
RESET_NEW_PASSWORD = "newpass789"
CHANGE_PW_TEMP = "temppass456"


def _try_login(api, email: str, password: str):
    return api.post("/auth/login", json_body={"email": email, "password": password})


def _login_ok(api, email: str, password: str) -> bool:
    return _try_login(api, email, password).status_code == 200


def _admin_find_users(api, ctx, keyword: str) -> list[dict]:
    resp = api.get(
        "/admin/users",
        token=ctx.token("admin"),
        params={"keyword": keyword, "status": "all"},
        expected=200,
    )
    return resp.json()


def _detail_of(api, path: str, token: str | None = None) -> str:
    resp = api.get(path, token=token) if token else api.get(path)
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001 - 仅用于取 detail 文案
        return ""
    if isinstance(data, dict):
        value = data.get("detail")
        return value if isinstance(value, str) else str(value)
    return ""


def _remember_token(api, ctx, key: str, email: str, password: str, display_name: str, payload: dict) -> dict:
    user = payload.get("user") or {}
    acct = {
        "key": key,
        "email": email,
        "password": password,
        "display_name": display_name,
        "id": user.get("id"),
        "role": user.get("role", "user"),
        "status": user.get("status", "normal"),
        "token": payload["access_token"],
        "user": user,
    }
    return ctx.remember_account(key, acct)


def _register_with_code(api, ctx, key: str, email: str, display_name: str, password: str = DEFAULT_PASSWORD) -> dict:
    """注册并登记 ctx（调用方已保证邮箱未注册）。"""
    code_resp = api.post("/auth/register/send-code", json_body={"email": email}, expected=200)
    code = (code_resp.json() or {}).get("dev_code")
    if not code:
        raise AssertionError(f"开发环境未返回 {email} 的注册验证码")
    resp = api.post(
        "/auth/register",
        json_body={"email": email, "display_name": display_name, "password": password, "code": code},
        expected=200,
    )
    return _remember_token(api, ctx, key, email, password, display_name, resp.json())


def _relogin(
    api,
    ctx,
    key: str,
    *,
    email: str | None = None,
    password: str | None = None,
    display_name: str | None = None,
) -> dict:
    """重新登录已登记账户：只更新 token/资料与清单行，不重复登记 inventory。"""
    acct = ctx.accounts[key]
    email = email or acct["email"]
    password = password or acct["password"]
    resp = _try_login(api, email, password)
    if resp.status_code != 200:
        raise AssertionError(f"账户 {key}（{email}）重新登录失败：HTTP {resp.status_code}")
    payload = resp.json()
    user = payload.get("user") or {}
    acct.update(
        {
            "email": email,
            "password": password,
            "token": payload["access_token"],
            "user": user,
            "id": user.get("id", acct.get("id")),
            "role": user.get("role", acct.get("role")),
            "status": user.get("status", acct.get("status")),
        }
    )
    if display_name or user.get("display_name"):
        acct["display_name"] = user.get("display_name") or display_name
    for row in ctx.inventory:
        if row.get("kind") == "account" and row.get("key") == key:
            row.update({"id": acct.get("id"), "label": acct.get("display_name", key), "state": acct.get("status")})
            row.setdefault("extra", {}).update(
                {"email": acct.get("email"), "password": acct.get("password"), "role": acct.get("role")}
            )
            break
    return acct


def _ensure_new_account(
    api, ctx, key: str, email: str, display: str, passwords: tuple[str, ...] = (DEFAULT_PASSWORD,)
) -> dict:
    """已注册则登录复用；否则走真实验证码注册（支持重跑）。"""
    for password in passwords:
        if _login_ok(api, email, password):
            if key in ctx.accounts:
                return _relogin(api, ctx, key, email=email, password=password, display_name=display)
            return login_account(api, ctx, key, email, password, display_name=display)
    return _register_with_code(api, ctx, key, email, display)


def _current_password(api, email: str, passwords: tuple[str, ...]) -> str:
    for password in passwords:
        if _login_ok(api, email, password):
            return password
    raise AssertionError(f"账户 {email} 当前密码不在已知集合内")


def run(ctx, api, rec):  # noqa: ANN001
    # ------------------------------------------------------------------
    # 未登录访问业务内容被拒绝（BR-22、SC-01-05）
    # ------------------------------------------------------------------
    with rec.step(
        "US-01-AC-03",
        us="US-01",
        sc="SC-01-05",
        desc="未登录访客访问商品搜索/分类/禁发范围/本人信息被拒绝",
        expected="401 未登录或登录已过期",
    ) as step:
        for path in ("/products/search", "/categories", "/prohibited-items", "/auth/me"):
            resp = api.get(path)
            api.expect_status(resp, 401, f"未登录访问 {path} 应返回 401")
            rec.must_eq(_detail_of(api, path), "未登录或登录已过期", f"{path} 错误文案")
        step["detail"] = "4 个业务接口未登录访问均返回 401，仅账户入口公开"

    # ------------------------------------------------------------------
    # 种子账户登录（US-01-AC-03、SC-01-01）
    # ------------------------------------------------------------------
    with rec.step(
        "US-01-AC-03",
        us="US-01",
        sc="SC-01-01",
        desc="种子账户 admin/zhang/li/wang 使用邮箱+密码登录并读取 /auth/me",
        expected="登录 200 且返回 access_token 与正常状态账户",
    ) as step:
        for key, email, password, name in SEED_ACCOUNTS:
            acct = login_account(api, ctx, key, email, password, display_name=name)
            rec.must(acct.get("token"), f"{key} 登录未返回 access_token")
            rec.must(acct.get("id"), f"{key} 登录未返回 user.id")
            me = refresh_me(api, ctx, key)
            rec.must_eq(me.get("email"), email, f"{key} /auth/me 邮箱")
            rec.must_eq(me.get("status"), "normal", f"{key} 账户状态")
            rec.must_eq(me.get("role"), "admin" if key == "admin" else "user", f"{key} 角色")
        step["detail"] = "4 个种子账户登录与 /auth/me 均通过"

    # ------------------------------------------------------------------
    # 注册：chen 完整验证码流程（US-01-AC-01、SC-01-01）
    # ------------------------------------------------------------------
    with rec.step(
        "US-01-AC-01",
        us="US-01",
        sc="SC-01-01",
        desc="chen 经真实验证码注册：错码被拒，正确验证码创建账户并分配唯一用户 ID",
        expected="错码 400 验证码错误或已过期；正确 200 并返回 token/user",
    ) as step:
        email = "chen@campus.edu"
        if _login_ok(api, email, DEFAULT_PASSWORD):
            _relogin(api, ctx, "chen", email=email, password=DEFAULT_PASSWORD, display_name="陈同学")
            step["detail"] = "chen 已存在（重跑场景），复用既有账户并核对登录"
        else:
            code_resp = api.post("/auth/register/send-code", json_body={"email": email}, expected=200)
            code = (code_resp.json() or {}).get("dev_code")
            rec.must(bool(code) and bool(re.fullmatch(r"\d{6}", str(code))), "开发环境应返回 6 位注册验证码")
            bad = api.post(
                "/auth/register",
                json_body={
                    "email": email,
                    "display_name": "陈同学",
                    "password": DEFAULT_PASSWORD,
                    "code": "000000",
                },
            )
            api.expect_status(bad, 400, "错误验证码注册应被拒绝")
            rec.must_eq((bad.json() or {}).get("detail"), "验证码错误或已过期", "错误验证码提示")
            resp = api.post(
                "/auth/register",
                json_body={"email": email, "display_name": "陈同学", "password": DEFAULT_PASSWORD, "code": code},
                expected=200,
            )
            payload = resp.json()
            rec.must(bool((payload.get("user") or {}).get("id")), "注册成功应返回唯一用户 ID")
            acct = _remember_token(api, ctx, "chen", email, DEFAULT_PASSWORD, "陈同学", payload)
            rec.must_eq((refresh_me(api, ctx, "chen") or {}).get("email"), email, "注册后 /auth/me 邮箱")
            step["detail"] = "错码 400；正确验证码注册成功并分配用户 ID"
        rec.must(ctx.accounts["chen"].get("id"), "chen 缺少用户 ID")

    # ------------------------------------------------------------------
    # 其余新账户注册：邮箱唯一、用户 ID 互不相同（US-01-AC-01）
    # ------------------------------------------------------------------
    with rec.step(
        "US-01-AC-01",
        us="US-01",
        sc="SC-01-01",
        desc="liu/zhao/qian/wu/sun/emailchg/reset 经真实验证码注册，邮箱与用户 ID 唯一且可登录",
        expected="全部 200；user.id 互不相同；邮箱可用于登录",
    ) as step:
        # emailchg 已切换到新邮箱时按新邮箱登录复用；否则从旧邮箱注册后换邮箱
        if _login_ok(api, EMAILCHG_NEW, DEFAULT_PASSWORD):
            _relogin(api, ctx, "emailchg", email=EMAILCHG_NEW, password=DEFAULT_PASSWORD, display_name="邮箱变更用户")
        elif _login_ok(api, EMAILCHG_OLD, DEFAULT_PASSWORD):
            _relogin(api, ctx, "emailchg", email=EMAILCHG_OLD, password=DEFAULT_PASSWORD, display_name="邮箱变更用户")
        else:
            _register_with_code(api, ctx, "emailchg", EMAILCHG_OLD, "邮箱变更用户")
        for key, email, display in NEW_ACCOUNTS:
            _ensure_new_account(api, ctx, key, email, display)
        # reset 账户：重置后密码为 newpass789，重跑时两套密码都尝试
        _ensure_new_account(
            api, ctx, "reset", "reset@campus.edu", "重置密码用户", passwords=(RESET_NEW_PASSWORD, DEFAULT_PASSWORD)
        )
        ids = {key: acct.get("id") for key, acct in ctx.accounts.items()}
        rec.must(len(set(ids.values())) == len(ids), f"用户 ID 应全平台唯一，实际 {ids}")
        for key, email, _display in NEW_ACCOUNTS:
            rec.must_eq(ctx.accounts[key]["email"], email, f"{key} 邮箱登记")
        rec.must_eq(len(ctx.accounts), len(SEED_ACCOUNTS) + len(NEW_ACCOUNTS) + 3, "ctx.accounts 应登记 12 个账户")
        step["detail"] = "7 个新账户注册成功且 12 个账户用户 ID 唯一"

    # ------------------------------------------------------------------
    # 未验证/错码/跨邮箱注册被拒（US-01-AC-08、SC-01-11）
    # ------------------------------------------------------------------
    with rec.step(
        "US-01-AC-08",
        us="US-01",
        sc="SC-01-11",
        desc="未验证邮箱、错码以及持其他邮箱验证码注册均被拒绝，且不创建账户、不占用邮箱",
        expected="400 验证码错误或已过期；管理端用户列表查不到新账户",
    ) as step:
        unverified_email = "p01.unverified@campus.edu"
        resp = api.post(
            "/auth/register",
            json_body={
                "email": unverified_email,
                "display_name": "未验证用户",
                "password": DEFAULT_PASSWORD,
                "code": "123456",
            },
        )
        api.expect_status(resp, 400, "未验证邮箱直接注册应被拒绝")
        rec.must_eq((resp.json() or {}).get("detail"), "验证码错误或已过期", "未验证注册提示")
        rec.must_eq(_admin_find_users(api, ctx, "p01.unverified"), [], "未验证注册不得创建账户")

        src_email = "p01.cross-src@campus.edu"
        dst_email = "p01.cross-dst@campus.edu"
        code_resp = api.post("/auth/register/send-code", json_body={"email": src_email}, expected=200)
        code = (code_resp.json() or {}).get("dev_code")
        resp = api.post(
            "/auth/register",
            json_body={
                "email": dst_email,
                "display_name": "跨邮箱注册用户",
                "password": DEFAULT_PASSWORD,
                "code": code,
            },
        )
        api.expect_status(resp, 400, "持其他邮箱验证码注册应被拒绝")
        rec.must_eq((resp.json() or {}).get("detail"), "验证码错误或已过期", "跨邮箱注册提示")
        rec.must_eq(_admin_find_users(api, ctx, "p01.cross"), [], "跨邮箱注册不得创建任一账户")
        step["detail"] = "未验证/跨邮箱注册均 400 且未创建账户、未占用邮箱"

    # ------------------------------------------------------------------
    # 重复邮箱注册被拒，原账户保留（US-01-AC-02、SC-01-02）
    # ------------------------------------------------------------------
    with rec.step(
        "US-01-AC-02",
        us="US-01",
        sc="SC-01-02",
        desc="以已注册邮箱 chen@campus.edu 再次注册被拒绝，原账户与记录保留",
        expected="400 该邮箱已被使用；原账户仍可登录且仅一条账户记录",
    ) as step:
        resp = api.post(
            "/auth/register",
            json_body={
                "email": "chen@campus.edu",
                "display_name": "冒名重复注册",
                "password": "another-pass",
                "code": "000000",
            },
        )
        api.expect_status(resp, 400, "重复邮箱注册应被拒绝")
        rec.must_eq((resp.json() or {}).get("detail"), "该邮箱已被使用", "重复邮箱提示")
        me = refresh_me(api, ctx, "chen")
        rec.must_eq(me.get("id"), ctx.accounts["chen"]["id"], "原账户用户 ID 保留")
        rec.must_eq(me.get("display_name"), "陈同学", "原账户显示名保留")
        users = _admin_find_users(api, ctx, "chen@campus.edu")
        rec.must_eq(len(users), 1, "同邮箱不得出现第二条账户记录")
        step["detail"] = "重复注册 400，原账户与唯一性保持"

    # ------------------------------------------------------------------
    # 错误密码与 5 次失败不锁定（US-01-AC-03、SC-01-03）
    # ------------------------------------------------------------------
    with rec.step(
        "US-01-AC-03",
        us="US-01",
        sc="SC-01-03",
        desc="错误密码登录被拒；连续 5 次失败后正确密码仍可登录（首版不设失败阈值）",
        expected="错误 401 邮箱或密码错误；第 6 次正确密码 200 且账户 normal",
    ) as step:
        for index in range(5):
            resp = _try_login(api, "zhang@campus.edu", f"wrong-password-{index}")
            api.expect_status(resp, 401, f"第 {index + 1} 次错误密码登录应返回 401")
            rec.must_eq((resp.json() or {}).get("detail"), "邮箱或密码错误", f"第 {index + 1} 次错误提示")
        acct = _relogin(api, ctx, "zhang", password=DEFAULT_PASSWORD, display_name="张同学")
        me = refresh_me(api, ctx, "zhang")
        rec.must_eq(me.get("id"), acct["id"], "5 次失败后登录用户 ID")
        rec.must_eq(me.get("status"), "normal", "5 次失败后账户仍为 normal（未锁定）")
        step["detail"] = "5 次错误密码均 401；随后正确密码登录成功，账户未被锁定"

    # ------------------------------------------------------------------
    # 退出登录（US-01-AC-03、SC-01-08）
    # ------------------------------------------------------------------
    with rec.step(
        "US-01-AC-03",
        us="US-01",
        sc="SC-01-08",
        desc="主动退出登录接口成功；退出后未携带凭证访问业务内容须重新登录",
        expected="logout 200 已退出登录；无 token 访问 401",
    ) as step:
        token = ctx.token("li")
        resp = api.post("/auth/logout", expected=200)
        rec.must_eq((resp.json() or {}).get("detail"), "已退出登录", "退出登录文案")
        api.expect_status(api.get("/products/search"), 401, "退出后未携带凭证访问应要求重新登录")
        # 服务端 JWT 无状态：旧 token 在有效期内仍可访问（记录候选缺口，不掩盖）
        reuse = api.get("/products/search", token=token)
        if reuse.status_code == 200:
            rec.defect(
                "requirement_gap_candidate",
                {
                    "title": "退出登录未使旧 token 失效（无服务端会话/吊销）",
                    "requirement": "US-01-AC-03 / UC-C01-03：退出后访问业务内容须重新登录",
                    "evidence": "POST /auth/logout 返回 200 但无服务端状态；JWT 有效期内旧 token 仍可访问",
                    "file": "backend/app/api/v1/auth.py:94-97（logout 空实现）、backend/app/core/security.py（仅 exp 校验）",
                },
            )
            ctx.note("logout 为无状态 JWT：接口 200 但旧 token 有效期内仍可访问（候选缺口，已记录缺陷清单）")
        step["detail"] = "logout 200；未携带凭证重新访问 401（旧 token 现状记候选缺口）"

    # ------------------------------------------------------------------
    # 忘记密码重置（US-01-AC-04、SC-01-04）
    # ------------------------------------------------------------------
    with rec.step(
        "US-01-AC-04",
        us="US-01",
        sc="SC-01-04",
        desc="reset 用户经绑定邮箱验证码重置密码：错码被拒，正确码生效且用户 ID 不变",
        expected="错码 400；正确 200；旧密码失效、新密码可登录、用户 ID 不变",
    ) as step:
        reset_email = "reset@campus.edu"
        reset_id = ctx.accounts["reset"]["id"]
        code_resp = api.post("/auth/forgot-password/send-code", json_body={"email": reset_email}, expected=200)
        code = (code_resp.json() or {}).get("dev_code")
        rec.must(bool(code) and bool(re.fullmatch(r"\d{6}", str(code))), "忘记密码验证码应为 6 位数字")
        bad = api.post(
            "/auth/forgot-password/reset",
            json_body={"email": reset_email, "code": "000000", "new_password": RESET_NEW_PASSWORD},
        )
        api.expect_status(bad, 400, "错误验证码重置应被拒绝")
        rec.must_eq((bad.json() or {}).get("detail"), "验证码错误或已过期", "错误验证码重置提示")
        resp = api.post(
            "/auth/forgot-password/reset",
            json_body={"email": reset_email, "code": code, "new_password": RESET_NEW_PASSWORD},
            expected=200,
        )
        payload = resp.json()
        rec.must_eq((payload.get("user") or {}).get("id"), reset_id, "重置后用户 ID 不变")
        api.expect_status(_try_login(api, reset_email, DEFAULT_PASSWORD), 401, "重置后旧密码应失效")
        acct = _relogin(api, ctx, "reset", password=RESET_NEW_PASSWORD, display_name="重置密码用户")
        rec.must_eq(acct["id"], reset_id, "新密码登录用户 ID 不变")
        step["detail"] = "错码 400；正确码重置成功，旧密码失效、新密码可登录、用户 ID 不变"

    # ------------------------------------------------------------------
    # 主动改密（US-01-AC-05、SC-01-08）
    # ------------------------------------------------------------------
    with rec.step(
        "US-01-AC-05",
        us="US-01",
        sc="SC-01-08",
        desc="主动改密须验证当前密码：错误旧密码被拒；正确改密后新密码生效且用户 ID 不变，随后改回",
        expected="错误旧密码 400；正确 200；新密码可登录；用户 ID 不变；最终密码恢复 secret123",
    ) as step:
        wu_email = "wu@campus.edu"
        wu_id = ctx.accounts["wu"]["id"]
        current = _current_password(api, wu_email, (DEFAULT_PASSWORD, CHANGE_PW_TEMP))
        if current != DEFAULT_PASSWORD:
            # 重跑残局：先改回统一密码，保证后续阶段可用
            api.post(
                "/auth/change-password",
                token=ctx.token("wu"),
                json_body={"current_password": current, "new_password": DEFAULT_PASSWORD},
                expected=200,
            )
            _relogin(api, ctx, "wu", password=DEFAULT_PASSWORD, display_name="吴同学")
            current = DEFAULT_PASSWORD
        bad = api.post(
            "/auth/change-password",
            token=ctx.token("wu"),
            json_body={"current_password": "not-the-password", "new_password": CHANGE_PW_TEMP},
        )
        api.expect_status(bad, 400, "错误当前密码改密应被拒绝")
        rec.must_eq((bad.json() or {}).get("detail"), "当前密码不正确", "错误当前密码提示")
        api.post(
            "/auth/change-password",
            token=ctx.token("wu"),
            json_body={"current_password": DEFAULT_PASSWORD, "new_password": CHANGE_PW_TEMP},
            expected=200,
        )
        api.expect_status(_try_login(api, wu_email, DEFAULT_PASSWORD), 401, "改密后旧密码应失效")
        changed = _relogin(api, ctx, "wu", password=CHANGE_PW_TEMP, display_name="吴同学")
        rec.must_eq(changed["id"], wu_id, "改密后用户 ID 不变")
        api.post(
            "/auth/change-password",
            token=ctx.token("wu"),
            json_body={"current_password": CHANGE_PW_TEMP, "new_password": DEFAULT_PASSWORD},
            expected=200,
        )
        back = _relogin(api, ctx, "wu", password=DEFAULT_PASSWORD, display_name="吴同学")
        rec.must_eq(back["id"], wu_id, "改回后用户 ID 不变")
        step["detail"] = "错误旧密码 400；正确改密→新密码登录→改回，全程用户 ID 不变"

    # ------------------------------------------------------------------
    # 换邮箱：新旧双验证 + 唯一性（US-01-AC-05、SC-01-08/09）
    # ------------------------------------------------------------------
    with rec.step(
        "US-01-AC-05",
        us="US-01",
        sc="SC-01-08",
        desc="emailchg 从 email.before 换到 email.after：新旧邮箱双验证，错码被拒，正确后以新邮箱登录且用户 ID 不变",
        expected="错码 400；正确 200；新邮箱可登录、旧邮箱失效、用户 ID 不变",
    ) as step:
        if _login_ok(api, EMAILCHG_NEW, DEFAULT_PASSWORD):
            acct = _relogin(
                api, ctx, "emailchg", email=EMAILCHG_NEW, password=DEFAULT_PASSWORD, display_name="邮箱变更用户"
            )
            rec.must_eq(acct["id"], ctx.accounts["emailchg"]["id"], "换邮箱后用户 ID 不变")
            api.expect_status(_try_login(api, EMAILCHG_OLD, DEFAULT_PASSWORD), 401, "旧邮箱应已失效")
            me = refresh_me(api, ctx, "emailchg")
            rec.must_eq(me.get("email"), EMAILCHG_NEW, "当前绑定邮箱应为新邮箱")
            step["detail"] = "emailchg 已切换到新邮箱（重跑场景），新邮箱登录与用户 ID 核对通过"
        else:
            token = ctx.token("emailchg")
            user_id = ctx.accounts["emailchg"]["id"]
            old_code_resp = api.post(
                "/auth/email/send-code", token=token, json_body={"target": "old"}, expected=200
            )
            old_code = (old_code_resp.json() or {}).get("dev_code")
            new_code_resp = api.post(
                "/auth/email/send-code",
                token=token,
                json_body={"target": "new", "new_email": EMAILCHG_NEW},
                expected=200,
            )
            new_code = (new_code_resp.json() or {}).get("dev_code")
            rec.must(bool(old_code) and bool(new_code), "新旧邮箱均应返回验证码")
            bad = api.post(
                "/auth/email/change",
                token=token,
                json_body={"new_email": EMAILCHG_NEW, "old_code": "000000", "new_code": new_code},
            )
            api.expect_status(bad, 400, "错误旧邮箱验证码换邮箱应被拒绝")
            rec.must_eq((bad.json() or {}).get("detail"), "验证码错误或已过期", "错误验证码换邮箱提示")
            resp = api.post(
                "/auth/email/change",
                token=token,
                json_body={"new_email": EMAILCHG_NEW, "old_code": old_code, "new_code": new_code},
                expected=200,
            )
            data = resp.json()
            rec.must_eq(data.get("id"), user_id, "换邮箱后用户 ID 不变")
            rec.must_eq(data.get("email"), EMAILCHG_NEW, "换邮箱后返回新邮箱")
            api.expect_status(_try_login(api, EMAILCHG_OLD, DEFAULT_PASSWORD), 401, "旧邮箱应失效")
            acct = _relogin(
                api, ctx, "emailchg", email=EMAILCHG_NEW, password=DEFAULT_PASSWORD, display_name="邮箱变更用户"
            )
            rec.must_eq(acct["id"], user_id, "新邮箱登录用户 ID 不变")
            me = refresh_me(api, ctx, "emailchg")
            rec.must_eq(me.get("email"), EMAILCHG_NEW, "当前绑定邮箱")
            step["detail"] = "新旧邮箱各一码验证通过；错码 400；新邮箱登录、旧邮箱失效、用户 ID 不变"

    # ------------------------------------------------------------------
    # 换邮箱唯一性（US-01-AC-02、SC-01-09）
    # ------------------------------------------------------------------
    with rec.step(
        "US-01-AC-02",
        us="US-01",
        sc="SC-01-09",
        desc="换邮箱目标邮箱已被占用（zhang@campus.edu）时被拒绝，保留原邮箱与用户 ID",
        expected="400 新邮箱已被其他账户使用；原邮箱保持不变",
    ) as step:
        token = ctx.token("emailchg")
        resp = api.post(
            "/auth/email/send-code",
            token=token,
            json_body={"target": "new", "new_email": "zhang@campus.edu"},
        )
        api.expect_status(resp, 400, "占用邮箱发码应被拒绝")
        rec.must_eq((resp.json() or {}).get("detail"), "新邮箱已被其他账户使用", "占用邮箱提示")
        submit = api.post(
            "/auth/email/change",
            token=token,
            json_body={"new_email": "zhang@campus.edu", "old_code": "000000", "new_code": "000000"},
        )
        api.expect_status(submit, 400, "占用邮箱提交换邮箱应被拒绝")
        rec.must_eq((submit.json() or {}).get("detail"), "新邮箱已被其他账户使用", "占用邮箱提交提示")
        me = refresh_me(api, ctx, "emailchg")
        rec.must_eq(me.get("email"), EMAILCHG_NEW, "拒绝后保留原邮箱")
        rec.must_eq(me.get("id"), ctx.accounts["emailchg"]["id"], "拒绝后用户 ID 不变")
        step["detail"] = "占用邮箱发码/提交均 400，原邮箱与用户 ID 保留"

    # ------------------------------------------------------------------
    # 改名与历史归属（US-01-AC-06、SC-01-10）
    # ------------------------------------------------------------------
    with rec.step(
        "US-01-AC-06",
        us="US-01",
        sc="SC-01-10",
        desc="zhang 修改显示名称：历史商品仍归属原用户 ID；空白名称被拒；随后恢复原名",
        expected="改名 200；商品 seller_id 不变；空白 422",
    ) as step:
        zhang = ctx.accounts["zhang"]
        original_name = zhang["display_name"]
        mine = api.get("/products/mine", token=zhang["token"], expected=200).json()
        rec.must(len(mine) > 0, "zhang 应有既有商品用于核对历史归属")
        product_id = mine[0]["id"]
        resp = api.patch(
            "/auth/profile",
            token=zhang["token"],
            json_body={"display_name": "张同学（改名核对）"},
            expected=200,
        )
        rec.must_eq((resp.json() or {}).get("display_name"), "张同学（改名核对）", "改名后返回新名称")
        me = refresh_me(api, ctx, "zhang")
        rec.must_eq(me.get("display_name"), "张同学（改名核对）", "改名后 /auth/me 名称")
        rec.must_eq(me.get("id"), zhang["id"], "改名后用户 ID 不变")
        detail = api.get(f"/products/{product_id}", token=zhang["token"], expected=200).json()
        rec.must_eq(detail.get("seller_id"), zhang["id"], "历史商品 seller_id 仍为原用户 ID")
        blank = api.patch("/auth/profile", token=zhang["token"], json_body={"display_name": "   "})
        api.expect_status(blank, 422, "空白显示名称应被拒绝")
        api.patch(
            "/auth/profile", token=zhang["token"], json_body={"display_name": original_name}, expected=200
        )
        rec.must_eq(refresh_me(api, ctx, "zhang").get("display_name"), original_name, "恢复原名")
        step["detail"] = "改名生效且历史商品归属不变；空白名称 422；已恢复原名"

    # ------------------------------------------------------------------
    # 封禁只读与申诉、解除恢复（US-01-AC-07、SC-01-06/07）
    # ------------------------------------------------------------------
    qian = ctx.accounts["qian"]
    qian_products = api.get("/products/mine", token=qian["token"], expected=200).json()
    if qian_products:
        rec.skip(
            "US-01-AC-07",
            us="US-01",
            sc="SC-01-06",
            desc="qian 封禁只读/写拒绝/申诉入口",
            reason="qian 已有业务对象（重跑场景），封禁联动由 p07 覆盖，p01 跳过封禁循环避免破坏数据",
        )
    else:
        with rec.step(
            "US-01-AC-07",
            us="US-01",
            sc="SC-01-06",
            desc="qian 被封禁后仍可登录并只读公共内容，写操作 403，处置沟通申诉入口可用",
            expected="登录 200；读 200；写 403 账户已被封禁；/me/cases 申诉 200",
        ) as step:
            users = _admin_find_users(api, ctx, "qian@campus.edu")
            if users and users[0]["status"] != "banned":
                ban = api.post(
                    f"/admin/users/{qian['id']}/ban",
                    token=ctx.token("admin"),
                    json_body={"reason": "p01 封禁/解封验证：账号存在违规内容待核查"},
                    expected=200,
                )
                ban_case_id = (ban.json() or {}).get("case_id")
                rec.must(bool(ban_case_id), "封禁响应应返回处置事项 case_id")
                ctx.remember_case(
                    "qian_ban",
                    {
                        "id": ban_case_id,
                        "title": "账户封禁：钱同学",
                        "status": "disposed",
                        "case_type": "account_ban",
                    },
                )
            # 封禁可登录
            qian = _relogin(api, ctx, "qian", password=DEFAULT_PASSWORD, display_name="钱同学")
            me = refresh_me(api, ctx, "qian")
            rec.must_eq(me.get("status"), "banned", "qian 状态应为 banned")
            # 只读公共内容
            search = api.get("/products/search", token=qian["token"], expected=200)
            listed = (search.json() or {}).get("items") or []
            rec.must(len(listed) > 0, "封禁用户应可读取公开在售商品")
            api.get("/categories", token=qian["token"], expected=200)
            api.get("/prohibited-items", token=qian["token"], expected=200)
            # 写操作 403
            tag_id = (listed[0].get("tag_ids") or [1])[0]
            write = api.post(
                "/products",
                token=qian["token"],
                json_body={
                    "title": "封禁用户不应能发布",
                    "description": "封禁写入校验",
                    "price_cents": 100,
                    "image_keys": ["product/202610/not-exist.jpg"],
                    "tags": [{"category_id": tag_id}],
                },
            )
            api.expect_status(write, 403, "封禁用户发布商品应被拒绝")
            rec.must_eq(
                (write.json() or {}).get("detail"), "账户已被封禁，当前操作不可用", "封禁写拒绝提示"
            )
            fav = api.post(f"/favorites/{listed[0]['id']}", token=qian["token"])
            api.expect_status(fav, 403, "封禁用户收藏应被拒绝")
            # 申诉入口
            cases = api.get("/me/cases", token=qian["token"], expected=200).json()
            ban_case = next((c for c in cases if c.get("case_type") == "account_ban"), None)
            rec.must(ban_case is not None, "封禁后应出现本人账户封禁事项")
            detail = api.get(f"/me/cases/{ban_case['id']}", token=qian["token"], expected=200).json()
            rec.must_eq(detail.get("status"), "disposed", "封禁事项应已处置并可申诉")
            appeal = api.post(
                f"/me/cases/{ban_case['id']}/appeal",
                token=qian["token"],
                json_body={"content": "p01 验证：对封禁原因提出申辩说明"},
                expected=200,
            )
            rec.must("申辩" in str((appeal.json() or {}).get("detail")), "申诉提交应成功")
            notices = api.get(
                "/notifications", token=qian["token"], params={"page_size": 50}, expected=200
            ).json()
            titles = [n.get("title") for n in notices.get("items", [])]
            rec.must_in("账户已被平台封禁", titles, "封禁处置通知")
            step["detail"] = "封禁后登录/读公共内容 200；发布与收藏 403；申诉成功并收到处置通知"

        with rec.step(
            "US-01-AC-07",
            us="US-01",
            sc="SC-01-07",
            desc="管理员解除 qian 封禁：恢复 normal 与写权限，限制历史保留",
            expected="unban 200；/auth/me status normal；写权限恢复；限制记录保留 lifted 历史",
        ) as step:
            qian = ctx.accounts["qian"]
            resp = api.post(
                f"/admin/users/{qian['id']}/unban",
                token=ctx.token("admin"),
                json_body={"lift_reason": "p01 验证：申诉说明已核实，解除封禁"},
                expected=200,
            )
            rec.must("已解除" in str((resp.json() or {}).get("detail")), "解除封禁提示")
            me = refresh_me(api, ctx, "qian")
            rec.must_eq(me.get("status"), "normal", "解除后 qian 状态 normal")
            search = api.get("/products/search", token=ctx.token("qian"), expected=200).json()
            listed = search.get("items") or []
            rec.must(len(listed) > 0, "解除后应可读取公开商品")
            added = api.post(f"/favorites/{listed[0]['id']}", token=ctx.token("qian"), expected=200)
            rec.must_eq((added.json() or {}).get("detail"), "已收藏", "解除后写操作恢复")
            api.delete(f"/favorites/{listed[0]['id']}", token=ctx.token("qian"), expected=200)
            restrictions = api.get(
                f"/admin/users/{qian['id']}/restrictions", token=ctx.token("admin"), expected=200
            ).json()
            bans = [r for r in restrictions if r.get("type") == "ban"]
            rec.must(len(bans) >= 1, "应保留封禁限制记录")
            rec.must_eq(bans[-1].get("status"), "lifted", "限制记录状态应为 lifted")
            rec.must(bool(bans[-1].get("lifted_at")), "限制记录应保留解除时间")
            notices = api.get(
                "/notifications", token=ctx.token("qian"), params={"page_size": 50}, expected=200
            ).json()
            titles = [n.get("title") for n in notices.get("items", [])]
            rec.must_in("账户封禁已解除", titles, "解封通知")
            step["detail"] = "unban 200；qian 恢复 normal 且写权限恢复；限制记录保留 lifted 历史"

    # ------------------------------------------------------------------
    # 结束登记（报告数据清单）
    # ------------------------------------------------------------------
    for key, acct in ctx.accounts.items():
        acct.setdefault("key", key)
    ctx.note(
        "p01 结束账户状态："
        + "、".join(
            f"{key}={ctx.accounts[key].get('status')}"
            for key in (
                "admin",
                "zhang",
                "li",
                "wang",
                "chen",
                "liu",
                "zhao",
                "qian",
                "wu",
                "sun",
                "emailchg",
                "reset",
            )
        )
    )
