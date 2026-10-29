"""共享基础设施：上下文、账户、上传、时间加速与轮询辅助。

阶段模块只依赖本文件与 e2e_client/e2e_recorder，业务动作在各阶段模块内实现，
避免多人同时改同一文件。所有数据均通过真实 HTTP 接口创建；仅"单方确认 7 天超时"
场景允许把数据库中的计时起点前移（否则需要真实等待 7 天），其余状态推进全部走接口。
"""

from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HARNESS_DIR = Path(__file__).resolve().parent
ASSETS_DIR = HARNESS_DIR / "assets"

DEFAULT_PASSWORD = "secret123"


class Ctx:
    """跨阶段共享上下文与数据清单。

    accounts: key -> {key,email,password,display_name,id,role,status,token}
    products: key -> {id,title,seller,status,...}；trades: key -> {id,buyer,seller,product,status,...}
    cases/reports/categories/items: 其他需登记的数据对象
    """

    def __init__(self, run_id: str, db_path: str | None = None):
        self.run_id = run_id
        self.db_path = db_path
        self.accounts: dict[str, dict[str, Any]] = {}
        self.products: dict[str, dict[str, Any]] = {}
        self.trades: dict[str, dict[str, Any]] = {}
        self.cases: dict[str, dict[str, Any]] = {}
        self.reports: dict[str, dict[str, Any]] = {}
        self.categories: dict[str, dict[str, Any]] = {}
        self.items: dict[str, dict[str, Any]] = {}
        self.inventory: list[dict[str, Any]] = []
        self.notes: list[str] = []

    # -- 账户 -------------------------------------------------------------
    def account(self, key: str, *, required: bool = True) -> dict[str, Any] | None:
        acct = self.accounts.get(key)
        if acct is None and required:
            raise AssertionError(f"缺少账户上下文：{key}（请先运行 p01_accounts 或在本阶段创建）")
        return acct

    def token(self, key: str) -> str:
        acct = self.account(key)
        assert acct is not None
        return acct["token"]

    def headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(key)}"}

    def remember_account(self, key: str, data: dict[str, Any]) -> dict[str, Any]:
        self.accounts[key] = data
        self.inventory_add(
            "account",
            key,
            data.get("id"),
            data.get("display_name", key),
            data.get("status", "normal"),
            {"email": data.get("email"), "role": data.get("role", "user"), "password": data.get("password")},
        )
        return data

    # -- 商品 / 交易 -------------------------------------------------------
    def remember_product(self, key: str, product: dict[str, Any], seller: str, state: str | None = None) -> dict[str, Any]:
        item = dict(product)
        item["key"] = key
        item["seller"] = seller
        item["state"] = state or product.get("status", "unknown")
        self.products[key] = item
        self.inventory_add("product", key, item.get("id"), item.get("title", key), item["state"], {"seller": seller})
        return item

    def update_product(self, key: str, **fields) -> None:
        if key in self.products:
            self.products[key].update(fields)
            for row in self.inventory:
                if row["kind"] == "product" and row["key"] == key:
                    row.update({"id": self.products[key].get("id"), "state": fields.get("state", row["state"])})
                    row.setdefault("extra", {}).update({k: v for k, v in fields.items() if k in ("status", "title")})

    def remember_trade(self, key: str, trade: dict[str, Any], buyer: str, seller: str, state: str | None = None) -> dict[str, Any]:
        item = dict(trade)
        item["key"] = key
        item["buyer"] = buyer
        item["seller"] = seller
        item["state"] = state or trade.get("status", "unknown")
        self.trades[key] = item
        self.inventory_add("trade", key, item.get("id"), f"交易#{item.get('id')}", item["state"], {"buyer": buyer, "seller": seller})
        return item

    def update_trade(self, key: str, state: str) -> None:
        if key in self.trades:
            self.trades[key]["state"] = state
            for row in self.inventory:
                if row["kind"] == "trade" and row["key"] == key:
                    row["state"] = state

    # -- 其他对象 ---------------------------------------------------------
    def remember_case(self, key: str, case: dict[str, Any]) -> dict[str, Any]:
        item = dict(case)
        item["key"] = key
        self.cases[key] = item
        self.inventory_add("case", key, item.get("id"), item.get("title", key), item.get("status", "unknown"), {"case_type": item.get("case_type")})
        return item

    def remember_report(self, key: str, report: dict[str, Any]) -> dict[str, Any]:
        item = dict(report)
        item["key"] = key
        self.reports[key] = item
        self.inventory_add("report", key, item.get("id"), item.get("reason", key), item.get("status", "unknown"), {"target_type": item.get("target_type")})
        return item

    def remember_category(self, key: str, category: dict[str, Any]) -> dict[str, Any]:
        item = dict(category)
        item["key"] = key
        self.categories[key] = item
        self.inventory_add("category", key, item.get("id"), item.get("name", key), item.get("status", "enabled"))
        return item

    def remember_item(self, kind: str, key: str, obj_id, label: str, state: str = "", extra: dict | None = None):
        self.items[f"{kind}:{key}"] = {"kind": kind, "key": key, "id": obj_id, "label": label, "state": state, "extra": extra or {}}
        self.inventory_add(kind, key, obj_id, label, state, extra or {})

    # -- 清单 -------------------------------------------------------------
    def inventory_add(self, kind: str, key: str, obj_id, label: str, state: str = "", extra: dict | None = None) -> None:
        self.inventory.append(
            {
                "kind": kind,
                "key": key,
                "id": obj_id,
                "label": label,
                "state": state,
                "extra": extra or {},
            }
        )

    def note(self, text: str) -> None:
        self.notes.append(text)


# ---------------------------------------------------------------------------
# 账户辅助
# ---------------------------------------------------------------------------
def asset(name: str) -> Path:
    path = ASSETS_DIR / name
    if not path.exists():
        raise AssertionError(f"缺少图片素材：{path}")
    return path


def _login(api, email: str, password: str) -> dict[str, Any] | None:
    resp = api.post("/auth/login", json_body={"email": email, "password": password})
    if resp.status_code == 200:
        return resp.json()
    return None


def login_account(api, ctx: Ctx, key: str, email: str, password: str = DEFAULT_PASSWORD, *, display_name: str | None = None) -> dict[str, Any]:
    data = _login(api, email, password)
    if data is None:
        raise AssertionError(f"账户 {key}（{email}）登录失败，可能不存在或密码不符")
    acct = {
        "key": key,
        "email": email,
        "password": password,
        "display_name": (data.get("user") or {}).get("display_name") or display_name or key,
        "id": (data.get("user") or {}).get("id"),
        "role": (data.get("user") or {}).get("role", "user"),
        "status": (data.get("user") or {}).get("status", "normal"),
        "token": data["access_token"],
        "user": data.get("user"),
    }
    return ctx.remember_account(key, acct)


def register_account(
    api,
    ctx: Ctx,
    key: str,
    email: str,
    display_name: str,
    password: str = DEFAULT_PASSWORD,
) -> dict[str, Any]:
    """通过真实注册验证码流程创建账户；已存在则直接登录复用。"""
    data = _login(api, email, password)
    if data is not None:
        return login_account(api, ctx, key, email, password, display_name=display_name)
    code_resp = api.post("/auth/register/send-code", json_body={"email": email}, expected=200)
    code = (code_resp.json() or {}).get("dev_code")
    if not code:
        raise AssertionError(f"开发环境未返回 {email} 的验证码，无法完成真实注册")
    resp = api.post(
        "/auth/register",
        json_body={"email": email, "display_name": display_name, "password": password, "code": code},
        expected=200,
    )
    payload = resp.json()
    acct = {
        "key": key,
        "email": email,
        "password": password,
        "display_name": display_name,
        "id": (payload.get("user") or {}).get("id"),
        "role": (payload.get("user") or {}).get("role", "user"),
        "status": (payload.get("user") or {}).get("status", "normal"),
        "token": payload["access_token"],
        "user": payload.get("user"),
    }
    return ctx.remember_account(key, acct)


def ensure_account(api, ctx: Ctx, key: str, email: str, display_name: str, password: str = DEFAULT_PASSWORD) -> dict[str, Any]:
    if key in ctx.accounts:
        return ctx.accounts[key]
    return register_account(api, ctx, key, email, display_name, password)


def refresh_me(api, ctx: Ctx, key: str) -> dict[str, Any]:
    acct = ctx.account(key)
    assert acct is not None
    resp = api.get("/auth/me", token=acct["token"], expected=200)
    acct["user"] = resp.json()
    acct["status"] = (resp.json() or {}).get("status", acct.get("status"))
    return resp.json()


# ---------------------------------------------------------------------------
# 上传
# ---------------------------------------------------------------------------
def upload_image(api, token: str, file_name: str, namespace: str = "product") -> dict[str, Any]:
    path = asset(file_name)
    with path.open("rb") as fh:
        resp = api.post(
            f"/files/upload?namespace={namespace}",
            token=token,
            files={"file": (file_name, fh, "image/jpeg")},
            expected=200,
        )
    payload = resp.json()
    if not payload.get("key") or not payload.get("url"):
        raise AssertionError(f"上传响应缺少 key/url：{payload}")
    return payload


def download_file(api, url: str) -> Any:
    """访问签名 URL（url 为绝对地址或 /api/v1/files/... 路径）。"""
    if url.startswith("http"):
        path = url.split("/api/v1", 1)[1] if "/api/v1" in url else url
        if not path.startswith("/files"):
            # 签名 URL 一般形如 http://host/api/v1/files/xxx?exp=..&sig=..
            path = "/files" + path.split("/files", 1)[1] if "/files" in path else path
    else:
        path = url.split("/api/v1", 1)[-1]
    return api.get(path, expected=200)


# ---------------------------------------------------------------------------
# 数据库时间加速（仅用于单方确认超时场景）
# ---------------------------------------------------------------------------
def db_connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=20)
    conn.execute("PRAGMA busy_timeout = 20000")
    return conn


def backdate_confirm_wait(db_path: str, trade_id: int, *, seconds_ago: int) -> str:
    """把进行中交易的确认等待起点前移指定秒数，模拟时间流逝。

    仅修改计时起点；超时识别、状态转换、冻结、事项与通知全部由真实后端扫描任务完成。
    返回修改后的起点（ISO 字符串）。
    """
    conn = db_connect(db_path)
    try:
        row = conn.execute(
            "SELECT confirm_wait_started_at, confirm_wait_paused_at FROM trades WHERE id = ?", (trade_id,)
        ).fetchone()
        if row is None:
            raise AssertionError(f"数据库中没有交易 #{trade_id}")
        new_start = (datetime.now(UTC) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%d %H:%M:%S.%f")
        conn.execute(
            "UPDATE trades SET confirm_wait_started_at = ?, confirm_wait_paused_at = NULL, "
            "confirm_wait_remaining_seconds = NULL WHERE id = ?",
            (new_start, trade_id),
        )
        conn.commit()
        return new_start
    finally:
        conn.close()


def db_query_one(db_path: str, sql: str, params: tuple = ()) -> tuple | None:
    conn = db_connect(db_path)
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 轮询
# ---------------------------------------------------------------------------
def wait_until(predicate, *, timeout: float = 120.0, interval: float = 2.0, error: str = "等待超时"):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"{error}（最后结果：{last!r}）")


def find_trade(api, token: str, trade_id: int) -> dict[str, Any]:
    resp = api.get(f"/trades/{trade_id}", token=token, expected=200)
    return resp.json()


def wait_trade_status(api, token: str, trade_id: int, statuses, *, timeout: float = 150.0) -> dict[str, Any]:
    allowed = {statuses} if isinstance(statuses, str) else set(statuses)

    def _poll():
        try:
            data = find_trade(api, token, trade_id)
        except AssertionError:
            return None
        return data if data.get("status") in allowed else None

    return wait_until(_poll, timeout=timeout, interval=2.0, error=f"交易 #{trade_id} 未在超时内进入 {allowed}")


# ---------------------------------------------------------------------------
# 管理员共享池
# ---------------------------------------------------------------------------
def admin_list_cases(api, ctx: Ctx, *, status: str = "pending", case_type: str | None = None) -> list[dict]:
    params = {"status": status, "limit": 200}
    if case_type:
        params["case_type"] = case_type
    resp = api.get("/admin/cases", token=ctx.token("admin"), params=params, expected=200)
    return resp.json()


def admin_claim_case(api, ctx: Ctx, case_id: int) -> dict[str, Any]:
    resp = api.post(f"/admin/cases/{case_id}/claim", token=ctx.token("admin"), json_body={}, expected=200)
    return resp.json()


def admin_case_detail(api, ctx: Ctx, case_id: int) -> dict[str, Any]:
    resp = api.get(f"/admin/cases/{case_id}", token=ctx.token("admin"), expected=200)
    return resp.json()


def admin_stats(api, ctx: Ctx, params: dict | None = None) -> dict[str, Any]:
    resp = api.get("/admin/stats", token=ctx.token("admin"), params=params or {}, expected=200)
    return resp.json()


# ---------------------------------------------------------------------------
# 结束状态复核
# ---------------------------------------------------------------------------
def refresh_inventory(api, ctx: Ctx) -> list[str]:
    """通过只读接口重新读取清单对象的当前状态，返回无法复核的备注列表。"""
    notes: list[str] = []
    admin = ctx.accounts.get("admin")
    any_token = next((a["token"] for a in ctx.accounts.values() if a.get("token")), None)

    for row in ctx.inventory:
        kind = row.get("kind")
        obj_id = row.get("id")
        extra = row.get("extra") or {}
        try:
            if kind == "account":
                acct = ctx.accounts.get(row["key"])
                if not acct:
                    continue
                resp = api.get("/auth/me", token=acct["token"])
                if resp.status_code == 200:
                    me = resp.json()
                    row["state"] = me.get("status", row["state"])
                    row["label"] = me.get("display_name", row["label"])
                    extra["email"] = me.get("email", extra.get("email"))
                else:
                    notes.append(f"账户 {row['key']} 状态复核失败：HTTP {resp.status_code}")
            elif kind == "product":
                seller = ctx.accounts.get(extra.get("seller"))
                if not seller or obj_id is None:
                    continue
                resp = api.get(f"/products/{obj_id}", token=seller["token"])
                if resp.status_code == 200:
                    data = resp.json()
                    row["state"] = data.get("status", row["state"])
                    extra.update(
                        {
                            "display_restricted": data.get("display_restricted"),
                            "tags": data.get("tag_names") or [t.get("name") for t in (data.get("tags") or []) if isinstance(t, dict)],
                            "images": len(data.get("images") or data.get("image_urls") or []),
                        }
                    )
                else:
                    notes.append(f"商品 {row['key']}（#{obj_id}）复核读取失败：HTTP {resp.status_code}")
            elif kind == "trade":
                buyer = ctx.accounts.get(extra.get("buyer")) or ctx.accounts.get(extra.get("seller"))
                if not buyer or obj_id is None:
                    continue
                resp = api.get(f"/trades/{obj_id}", token=buyer["token"])
                if resp.status_code == 200:
                    data = resp.json()
                    row["state"] = data.get("status", row["state"])
                    extra["frozen"] = data.get("frozen")
                else:
                    notes.append(f"交易 {row['key']}（#{obj_id}）复核读取失败：HTTP {resp.status_code}")
            elif kind == "case" and admin:
                resp = api.get("/admin/cases", token=admin["token"], params={"status": "all"})
                if resp.status_code == 200:
                    for case in resp.json():
                        if case.get("id") == obj_id:
                            row["state"] = case.get("status", row["state"])
                            break
            elif kind == "category" and any_token:
                resp = api.get("/categories", token=any_token)
                if resp.status_code == 200:
                    for cat in resp.json():
                        if cat.get("id") == obj_id:
                            row["state"] = "disabled" if cat.get("disabled") or cat.get("status") == "disabled" else "enabled"
                            break
        except AssertionError as exc:
            notes.append(f"{kind} {row.get('key')} 复核异常：{exc}")
        except Exception as exc:  # noqa: BLE001 - 复核不改变测试结论
            notes.append(f"{kind} {row.get('key')} 复核异常：{type(exc).__name__}: {exc}")
    return notes
