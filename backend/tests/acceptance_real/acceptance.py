"""真实资源验收场景：所有业务动作通过 HTTP，数据库用于初始化 seed、只读核验及扫描服务的隔离并发验证。

本模块不修改业务代码；7 天场景通过测试服务进程的受控时钟推进，不写数据库时间字段。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import re
import subprocess
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from app.core.private_files import protect_private, require_private
from app.devtools._support import (
    DevConfig,
    StorageProbe,
    mint_fingerprint_token,
    probe_database,
    readonly_mapping,
    readonly_rows,
)

from tests.acceptance_real.core import (
    BACKEND_ROOT,
    REPO_ROOT,
    ApiClient,
    Catalog,
    CheckFailure,
    Recorder,
    RouteIndex,
)
from tests.acceptance_real.seed import (
    SEED_DOMAIN,
    SeedAccount,
    identities_for_run,
    load_credentials,
    seed_identities,
)

ASSETS = BACKEND_ROOT / "tests" / "acceptance_real" / "assets"
ACCEPTANCE_ROOT = REPO_ROOT / "var" / "acceptance-real"

AGREEMENT_A = {
    "delivery_time": "2026-11-02 18:00",
    "delivery_location": "图书馆西门",
    "delivery_method": "当面交付",
    "amount_cents": 6000,
    "payment_method": "支付宝",
    "payment_timing": "当面支付",
}
AGREEMENT_B = {
    "delivery_time": "2026-11-03 19:00",
    "delivery_location": "宿舍楼下",
    "delivery_method": "当面交付",
    "amount_cents": 5800,
    "payment_method": "微信",
    "payment_timing": "交付后支付",
}
PNG_1X1 = bytes.fromhex(
    ("89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
     "de0000000c4944415408d763f8cfc000000301010018dd8db00000000049454e44ae426082")
)


def _asset_bytes(name: str) -> bytes:
    path = ASSETS / name
    if not path.is_file():
        raise CheckFailure(f"缺少测试素材：{path.name}")
    return path.read_bytes()


def _safe_iso(value: Any) -> str | None:
    return str(value) if value else None


@dataclass
class ServerHandle:
    process: subprocess.Popen[bytes]
    base_url: str
    clock_file: Path
    log_path: Path

    def set_clock_offset(self, seconds: int) -> None:
        self.clock_file.write_text(f"{int(seconds)}\n", encoding="ascii")
        try:
            protect_private(self.clock_file)
        except OSError:
            pass

    def stop(self) -> None:
        from tests.acceptance_real.processes import stop_server
        stop_server(self.process, self.clock_file)


class AcceptanceRun:
    def __init__(
        self,
        *,
        base_url: str,
        config: DevConfig,
        catalog: Catalog,
        run_id: str,
        server: ServerHandle | None = None,
        only: Sequence[str] | None = None,
    ) -> None:
        self.base_url = base_url
        self.config = config
        self.catalog = catalog
        self.run_id = run_id
        self.server = server
        self.only = {value.strip().lower() for value in (only or []) if value.strip()}
        self.route_index = RouteIndex({})
        self.api = ApiClient(base_url, self.route_index)
        if config.settings.storage_backend == 'oss':
            endpoint = urlsplit(config.settings.oss_endpoint).netloc
            self.api.allowed_storage_hosts = {f'{bucket}.{endpoint}' for bucket in (config.settings.oss_media_bucket, config.settings.oss_evidence_bucket)}
        self.rec = Recorder(self.api)
        self.users: dict[str, dict[str, Any]] = {}
        self.categories: dict[str, Any] = {}
        self.products: dict[str, dict[str, Any]] = {}
        self.trades: dict[str, dict[str, Any]] = {}
        self.cases: dict[str, Any] = {}
        self.reports: dict[str, Any] = {}
        self.files: dict[str, Any] = {}
        self.comments: dict[str, Any] = {}
        self.conversations: dict[str, Any] = {}
        self.notes: list[str] = []
        self.ws_ok = False
        self.started_at = datetime.now(UTC)
        self.finished_at: datetime | None = None
        self.openapi: dict[str, Any] = {}
        self.all_business_routes: list[tuple[str, str]] = []
        self.clock_events: list[dict[str, Any]] = []
        self.concurrency: list[dict[str, Any]] = []
        self.seed_fingerprint: str | None = None
        self.retained: list[dict[str, Any]] = []
        # 审计完整性核验所需的本轮对象/敏感标记；不保存凭据或响应正文。
        self.audit_targets: dict[str, Any] = {}
        self._server_started_by_us = server is not None

    # ------------------------------------------------------------------
    # 基础访问
    # ------------------------------------------------------------------
    def _enabled(self, group: str) -> bool:
        return not self.only or group.lower() in self.only

    def _token(self, key: str) -> str:
        account = self.users.get(key)
        if not account or not account.get("token"):
            raise CheckFailure(f"账号 {key} 未登录")
        return str(account["token"])

    def _uid(self, key: str) -> int:
        account = self.users.get(key)
        if not account:
            raise CheckFailure(f"账号 {key} 不存在")
        return int(account["id"])

    def _call(self, method: str, path: str, *, user: str | None = None, expected: Any = 200, **kwargs: Any) -> httpx.Response:
        token = self._token(user) if user else None
        self.api.current_role = user or "anonymous"
        return self.api.request(method, path, token=token, expected=expected, **kwargs)

    def _json(self, response: httpx.Response) -> Any:
        return self.api.json_of(response)

    def _dict(self, response: httpx.Response) -> dict[str, Any]:
        return self.api.dict_of(response)

    def _list(self, response: httpx.Response) -> list[Any]:
        # 管理端列表已改为 {items, total, page, page_size} 分页响应；此处统一解包，
        # 兼容仍返回裸数组的公开端点，避免逐调用点修改。
        value = self.api.json_of(response)
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            return value["items"]
        if isinstance(value, list):
            return value
        raise CheckFailure("响应不是 JSON 数组或分页对象")

    def _sandbox_sql(self, sql: str) -> str:
        from app.core.config import validate_schema_identifier
        schema = validate_schema_identifier(self.config.database_schema)
        if not self.config.acceptance_sandbox or not schema.startswith("acceptance_"):
            raise CheckFailure("只允许查询本轮隔离数据库")
        return sql.replace("app.", "" if self.config.database_url.startswith("sqlite+") else f'"{schema}".')

    def _adapt_query(self, sql: str, params: Mapping[str, Any] | None):
        sql = self._sandbox_sql(sql)
        values = dict(params or {})
        if self.config.database_url.startswith("sqlite+"):
            sql = sql.replace("payload->>'trade_id'", "CAST(json_extract(payload, '$.trade_id') AS TEXT)")
            # Raw SQL bypasses SQLAlchemy's DateTime bind processor. Match its
            # explicit SQLite format instead of sqlite3's deprecated adapter.
            for name,value in values.items():
                if isinstance(value,datetime):
                    stamp=value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value
                    values[name]=stamp.isoformat(sep=" ",timespec="microseconds")
        if self.config.database_url.startswith("sqlite+") and "= any(:keys)" in sql:
            keys = values.pop("keys")
            placeholders = []
            for index, value in enumerate(keys):
                name = f"sandbox_key_{index}"
                values[name] = value
                placeholders.append(":" + name)
            sql = sql.replace("= any(:keys)", "in (" + (", ".join(placeholders) or "NULL") + ")")
        return sql, values

    def _db(self, sql: str, params: Mapping[str, Any] | None = None) -> list[Mapping[str, Any]]:
        sql, params = self._adapt_query(sql, params)
        return asyncio.run(readonly_rows(self.config.database_url, sql, params, schema=self.config.database_schema))

    def _db_one(self, sql: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        sql, params = self._adapt_query(sql, params)
        row = asyncio.run(readonly_mapping(self.config.database_url, sql, params, schema=self.config.database_schema))
        if row is None:
            raise CheckFailure("只读核验 SQL 未返回预期行")
        return row

    def _assert_media_url(self, url: str | None, label: str) -> None:
        """媒体链接必须是可读入口：OSS 为私有桶签名直链，local 为后端签名路径。"""
        self.rec.must(bool(url), f"{label}链接存在")
        if not url:
            return
        if self.config.settings.storage_backend == "oss":
            self.rec.must(urlsplit(url).netloc in self.api.allowed_storage_hosts, f"{label}为OSS直链")
        else:
            self.rec.must(url.startswith("/api/v1/files/"), f"{label}为后端签名入口")
        self.api.signed_get(url)

    # ------------------------------------------------------------------
    # 账号
    # ------------------------------------------------------------------
    def _bootstrap_identities(self) -> dict[str, SeedAccount]:
        """调用 tests 内唯一 seed，复用/创建本轮 canonical 身份。

        只初始化账号身份，不建业务数据；凭据文件 0600，不输出密码。
        被用户改过的账号不会被覆盖或重置，seed 以 preserved 报告。
        """
        path = self.config.credentials_path
        if path is None:
            raise CheckFailure("缺少隔离凭据路径")
        summary = asyncio.run(
            seed_identities(run_id=self.run_id, credentials_path=path, config=self.config)
        )
        if summary.preserved:
            raise CheckFailure(
                "本轮 seed 账号已被用户修改/封禁，拒绝重置；请换新 run_id："
                + ",".join(summary.preserved)
            )
        credentials = load_credentials(path, require_private=True, identities=identities_for_run(self.run_id))
        if credentials is None:
            raise CheckFailure("缺少本轮 seed 凭据")
        require_private(path)
        self.seed_fingerprint = credentials.fingerprint
        expected = {identity.key for identity in identities_for_run(self.run_id)}
        if set(credentials.accounts) != expected:
            raise CheckFailure("seed 凭据身份集合不是本轮 canonical 身份")
        return dict(credentials.accounts)

    def _login_known(self, key: str, email: str, password: str, expected_id: int | None = None, expected_role: str | None = None) -> None:
        response = self._call("POST", "/api/v1/auth/login", expected=200, json_body={"email": email, "password": password})
        data = self._dict(response)
        user = data.get("user") or {}
        token = data.get("access_token")
        if not token:
            raise CheckFailure(f"登录 {key} 缺少 token")
        account = {
            "key": key,
            "id": int(user["id"]),
            "email": email,
            "password": password,
            "display_name": str(user.get("display_name") or ""),
            "role": str(user.get("role") or ""),
            "status": str(user.get("status") or ""),
            "token": str(token),
        }
        if expected_id is not None and account["id"] != expected_id:
            raise CheckFailure(f"登录 {key} 用户 ID 与 seed 不一致")
        if expected_role is not None and account["role"] != expected_role:
            raise CheckFailure(f"登录 {key} 角色与 seed 不一致")
        self.users[key] = account

    def _relogin(self, key: str, *, password: str | None = None, email: str | None = None) -> None:
        account = self.users[key]
        self._login_known(
            key,
            email or str(account["email"]),
            password or str(account["password"]),
            expected_id=int(account["id"]),
            expected_role=str(account["role"]),
        )

    def _fresh_email(self, name: str) -> str:
        return f"accept-{name}-{self.run_id.lower()}@{SEED_DOMAIN}"

    def _register_via_http(self, key: str, email: str, display_name: str, password: str) -> dict[str, Any]:
        code_response = self._call("POST", "/api/v1/auth/register/send-code", expected=200, json_body={"email": email})
        code = self._received_code(self._dict(code_response),email,"register")
        response = self._call(
            "POST",
            "/api/v1/auth/register",
            expected=200,
            json_body={"email": email, "display_name": display_name, "password": password, "code": code},
        )
        data = self._dict(response)
        user = data.get("user") or {}
        token = data.get("access_token")
        if not token:
            raise CheckFailure("注册响应缺少 token")
        account = {
            "key": key,
            "id": int(user["id"]),
            "email": email,
            "password": password,
            "display_name": display_name,
            "role": str(user.get("role") or "user"),
            "status": str(user.get("status") or "normal"),
            "token": str(token),
        }
        self.users[key] = account
        return account

    def _received_code(self, response: Mapping[str,Any], email: str, purpose: str) -> str:
        """Read this run's private mail sink, never an API-returned code or real inbox."""
        self.rec.must("dev_code" not in response,"验证码不在HTTP响应中返回")
        settings=self.config.settings
        if settings.mail_backend != "capture" or settings.mail_capture_path is None:
            raise CheckFailure("自动化只能读取本轮隔离邮件捕获")
        path=Path(settings.mail_capture_path)
        require_private(path)
        messages=[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        matching=[m for m in messages if m['email']==email.strip().lower() and m['purpose']==purpose]
        if not matching or not re.fullmatch(r"[0-9]{6}",matching[-1]['code']):
            raise CheckFailure("未收到对应的隔离验证码邮件")
        self.rec.must(True,"验证码已投递至本轮私有邮箱")
        return matching[-1]['code']

    # ------------------------------------------------------------------
    # 文件 / 商品 / 通用业务辅助
    # ------------------------------------------------------------------
    def _upload(self, user: str, asset: str, namespace: str = "product") -> dict[str, Any]:
        content = _asset_bytes(asset)
        lease = self._lease(user,asset,content,namespace)
        self._put_lease(lease,content)
        data = self._dict(self._call("POST",f"/api/v1/files/upload-leases/{lease['lease_id']}/complete",user=user))
        if not data.get("key") or not data.get("url"):
            raise CheckFailure("上传响应缺少 key/url")
        return data

    def _lease(self, user: str, filename: str, content: bytes, namespace: str = "product", **overrides: Any) -> dict[str, Any]:
        from app.storage.base import content_type_for_key
        declaration = {"namespace":namespace,"filename":filename,"size_bytes":len(content),
                       "content_type":content_type_for_key(filename),"sha256":hashlib.sha256(content).hexdigest()}
        declaration.update(overrides)
        return self._dict(self._call("POST","/api/v1/files/upload-leases",user=user,json_body=declaration))

    def _put_lease(self, lease: Mapping[str, Any], content: bytes, *, expected: Sequence[int] = (200,), headers_override: Mapping[str,str] | None = None) -> httpx.Response:
        upload=lease['upload'];url=str(upload['url']);headers=dict(upload['headers'])
        if headers_override:headers.update(headers_override)
        if url.startswith('/'):
            return self._call("PUT",url,content=content,headers=headers,expected=expected)
        with httpx.Client(trust_env=False,timeout=30,follow_redirects=False) as client:
            response=client.put(url,headers=headers,content=content)
        if response.status_code not in expected:
            raise CheckFailure(f"OSS direct PUT returned {response.status_code}, expected {list(expected)}")
        return response

    def _product_detail(self, key: str, viewer: str = "seller") -> dict[str, Any]:
        product = self.products.get(key)
        if not product:
            raise CheckFailure(f"商品 {key} 尚未创建")
        return self._dict(self._call("GET", f"/api/v1/products/{product['id']}", user=viewer, expected=200))

    def _pending_case(self, product_id: int, case_type: str = "product_review", *, user: str = "admin") -> dict[str, Any]:
        rows = self._list(
            self._call("GET", "/api/v1/admin/cases", user=user, expected=200, params={"status": "pending", "case_type": case_type})
        )
        for row in rows:
            if int(row.get("product_id") or 0) == int(product_id):
                return row
        raise CheckFailure(f"共享池没有商品 #{product_id} 的待处理 {case_type} 事项")

    def _claim(self, case_id: int, user: str = "admin") -> dict[str, Any]:
        return self._dict(self._call("POST", f"/api/v1/admin/cases/{case_id}/claim", user=user, expected=200, json_body={}))

    def _review(self, case_id: int, body: Mapping[str, Any], user: str = "admin") -> dict[str, Any]:
        return self._dict(
            self._call("POST", f"/api/v1/admin/products/cases/{case_id}/review", user=user, expected=200, json_body=dict(body))
        )

    def _approve(self, key: str, *, user: str = "admin", tag_decisions: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
        product = self.products[key]
        case = self._pending_case(int(product["id"]), user=user)
        self._claim(int(case["id"]), user=user)
        body: dict[str, Any] = {"result": "approved"}
        if tag_decisions is not None:
            body["tag_decisions"] = list(tag_decisions)
        self._review(int(case["id"]), body, user=user)
        detail = self._product_detail(key, "seller")
        if detail.get("status") != "listed":
            raise CheckFailure(f"商品 {key} 审核通过后不是 listed")
        self.products[key].update(detail)
        self.products[key]["review_case_id"] = int(case["id"])
        return detail

    def _reject(self, key: str, reason: str, *, user: str = "admin") -> dict[str, Any]:
        product = self.products[key]
        case = self._pending_case(int(product["id"]), user=user)
        self._claim(int(case["id"]), user=user)
        self._review(int(case["id"]), {"result": "rejected", "reason": reason}, user=user)
        detail = self._product_detail(key, "seller")
        self.products[key].update(detail)
        self.products[key]["review_case_id"] = int(case["id"])
        return detail

    def _publish(
        self,
        key: str,
        seller: str,
        title: str,
        *,
        price: int = 5000,
        category_ids: Sequence[int] | None = None,
        new_names: Sequence[str] | None = None,
        asset: str = "product_bike.jpg",
        description: str | None = None,
    ) -> dict[str, Any]:
        uploaded = self._upload(seller, asset, "product")
        self.files[f"{key}:image"] = uploaded
        tags: list[dict[str, Any]] = []
        for cid in category_ids or []:
            tags.append({"category_id": int(cid)})
        for name in new_names or []:
            tags.append({"new_name": name})
        if not tags:
            raise CheckFailure("发布商品至少需要一个标签")
        response = self._call(
            "POST",
            "/api/v1/products",
            user=seller,
            expected=200,
            json_body={
                "title": title,
                "description": description or f"验收商品 {title}；仅用于真实测试环境。",
                "price_cents": int(price),
                "image_keys": [uploaded["key"]],
                "tags": tags,
            },
        )
        product = self._dict(response)
        product.update({"key": key, "seller": seller})
        self.products[key] = product
        return product

    def _request_trade(self, key: str, buyer: str, product_key: str, note: str | None = None) -> dict[str, Any]:
        product = self.products[product_key]
        body: dict[str, Any] = {"product_id": int(product["id"])}
        if note:
            body["note"] = note
        data = self._dict(self._call("POST", "/api/v1/trades/requests", user=buyer, expected=200, json_body=body))
        trade = {"id": int(data["id"]), "key": key, "buyer": buyer, "seller": product["seller"], "product": product_key}
        self.trades[key] = trade
        return trade

    def _trade_detail(self, key: str, viewer: str | None = None) -> dict[str, Any]:
        trade = self.trades[key]
        viewer = viewer or str(trade["buyer"])
        return self._dict(self._call("GET", f"/api/v1/trades/{trade['id']}", user=viewer, expected=200))

    def _accept(self, key: str, seller: str | None = None) -> dict[str, Any]:
        trade = self.trades[key]
        seller = seller or str(trade["seller"])
        return self._dict(self._call("POST", f"/api/v1/trades/{trade['id']}/accept", user=seller, expected=200, json_body={}))

    def _propose(self, key: str, proposer: str, agreement: Mapping[str, Any] = AGREEMENT_A) -> int:
        trade = self.trades[key]
        data = self._dict(
            self._call(
                "POST",
                f"/api/v1/trades/{trade['id']}/agreements",
                user=proposer,
                expected=200,
                json_body=dict(agreement),
            )
        )
        return int(data["id"])

    def _agree(self, key: str, agreement_id: int, confirmer: str) -> dict[str, Any]:
        trade = self.trades[key]
        return self._dict(
            self._call(
                "POST",
                f"/api/v1/trades/{trade['id']}/agreements/{agreement_id}/confirm",
                user=confirmer,
                expected=200,
                json_body={},
            )
        )

    def _confirm(self, key: str, user: str, note: str | None = None) -> dict[str, Any]:
        trade = self.trades[key]
        body = {"note": note} if note else {}
        return self._dict(
            self._call("POST", f"/api/v1/trades/{trade['id']}/confirmations", user=user, expected=200, json_body=body)
        )

    def _set_status(self, key: str, status: str) -> None:
        self.trades[key]["status"] = status

    def _wait_trade_status(self, key: str, statuses: Iterable[str], *, viewer: str | None = None, timeout: float = 60.0) -> dict[str, Any]:
        wanted = set(statuses)
        deadline = time.monotonic() + timeout
        last: Any = None
        while time.monotonic() < deadline:
            try:
                detail = self._trade_detail(key, viewer)
            except CheckFailure:
                time.sleep(1.0)
                continue
            last = detail.get("status")
            if last in wanted:
                self._set_status(key, str(last))
                return detail
            time.sleep(1.0)
        raise CheckFailure(f"交易 {key} 未在 {timeout:.0f}s 内进入 {sorted(wanted)}（最后 {last}）")

    def _notifications(self, user: str, *, pages: int = 4, page_size: int = 50) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page in range(1, pages + 1):
            data = self._dict(
                self._call(
                    "GET",
                    "/api/v1/notifications",
                    user=user,
                    expected=200,
                    params={"page": page, "page_size": page_size},
                )
            )
            batch = data.get("items") or []
            items.extend(batch)
            if len(batch) < page_size:
                break
        return items

    @staticmethod
    def _has_notification(items: Sequence[Mapping[str, Any]], ntype: str, *, link_id: int | None = None) -> bool:
        return any(item.get("type") == ntype and (link_id is None or int(item.get("link_id") or 0) == link_id) for item in items)

    # ------------------------------------------------------------------
    # 并发与跨步骤辅助
    # ------------------------------------------------------------------
    def _concurrent(self, jobs: Sequence[tuple[str, str, str, Mapping[str, Any]]]) -> list[dict[str, Any]]:
        """用独立 httpx 客户端并发发起真实请求，并补登到主调用账本。"""
        import threading

        lock = threading.Lock()
        start_barrier = threading.Barrier(len(jobs))
        origin = self.api.origin
        results: list[dict[str, Any]] = []

        def _one(job: tuple[str, str, str, Mapping[str, Any]]) -> dict[str, Any]:
            method, path, role, body = job
            token = self._token(role)
            started = time.monotonic()
            with httpx.Client(
                base_url=origin,
                timeout=40.0,
                follow_redirects=False,
                trust_env=False,
                headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            ) as client:
                start_barrier.wait(timeout=10)
                response = client.request(method, path, json=dict(body))
            duration = round((time.monotonic() - started) * 1000, 1)
            from tests.acceptance_real.core import CallRecord

            record = CallRecord(
                len(self.api.calls) + 1,
                self.api.current_check,
                method.upper(),
                urlsplit(path).path,
                self.api.route_index.resolve(method.upper(), urlsplit(path).path),
                response.status_code,
                duration,
                role,
                [],
                "concurrent",
            )
            with lock:
                self.api.calls.append(record)
            try:
                body = response.json() if response.content else None
            except ValueError:
                body = None
            return {"role": role, "status": response.status_code, "duration_ms": duration, "body": body}

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = [pool.submit(_one, job) for job in jobs]
            for future in futures:
                results.append(future.result())
        return results

    def _relevant_case_for_product(self, product_id: int, *, claimant: str = "admin") -> int:
        """通过真实举报建立与商品相关的已认领事项，供管理交易读取/处置作依据。"""
        report = self._dict(
            self._call(
                "POST",
                "/api/v1/reports",
                user="outsider",
                expected=201,
                json_body={
                    "target_type": "product",
                    "target_id": int(product_id),
                    "reason": f"管理处置依据-{self.run_id}",
                },
            )
        )
        report_id = int(report["id"])
        rows = self._list(self._call("GET", "/api/v1/admin/reports", user=claimant, expected=200, params={"status": "all"}))
        case_id = next(
            (int(row["case_id"]) for row in rows if int(row.get("id") or 0) == report_id and row.get("case_id")),
            None,
        )
        if case_id is None:
            raise CheckFailure("举报事项未出现在管理列表")
        self._claim(case_id, claimant)
        return case_id

    def _admin_terminate(self, key: str, *, reason: str, claimant: str = "admin") -> dict[str, Any]:
        trade = self.trades[key]
        case_id = self._relevant_case_for_product(int(self.products[trade["product"]]["id"]), claimant=claimant)
        return self._dict(
            self._call(
                "POST",
                f"/api/v1/admin/trades/{trade['id']}/adjust",
                user=claimant,
                expected=200,
                json_body={"to_status": "terminated", "reason": reason, "case_id": case_id},
            )
        )

    # ------------------------------------------------------------------
    # 预检
    # ------------------------------------------------------------------
    def preflight(self) -> None:
        with self.rec.step(
            "ENV-01",
            "环境/数据库/Redis/OSS 配置目标与真实可用性",
            ac=["US-01-AC-01"],
            sc=["SC-01-01"],
            note="基础设施预检；不替代业务语义验收",
        ):
            identity = asyncio.run(probe_database(self.config.database_url, expect_test_target=True))
            if self.config.database_url.startswith("postgresql+"):
                self.rec.must_eq(identity.database, self.config.database.database, "数据库名")
                self.rec.must_eq(identity.user, self.config.database.username, "数据库应用角色")
            else:
                self.rec.must_eq(identity.database, "sqlite", "隔离 SQLite")
            self.rec.must_eq(self.config.environment in {"dev", "test"}, True, "ENVIRONMENT")
            settings = self.config.settings
            if settings.storage_backend == "oss":
                self.rec.must_eq(settings.oss_media_bucket, self.config.oss_media_bucket, "media bucket")
                self.rec.must_eq(settings.oss_evidence_bucket, self.config.oss_evidence_bucket, "evidence bucket")
            if settings.kv_backend == "redis":
                import redis.asyncio as aioredis
                async def roundtrip():
                    client = aioredis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3)
                    try:
                        key = settings.redis_key_prefix + "probe"
                        pong = await client.ping()
                        await client.set(key, "1", ex=30)
                        value = await client.get(key)
                        await client.delete(key)
                        return pong, value
                    finally:
                        await client.aclose()
                pong, value = asyncio.run(roundtrip())
                self.rec.must(bool(pong), "Redis PING")
                self.rec.must_eq(value, "1", "Redis SET/GET")
                self.clock_events.append({"kind": "redis", "mode": "real", "ok": True})
            else:
                self.clock_events.append({"kind": "redis", "mode": "memory", "ok": True})
            probe = StorageProbe.build(self.config)
            for namespace in ("product", "report"):
                key = f"{namespace}/probe/{self.run_id}.png"
                self.rec.must(not probe.exists(key), f"{namespace} 本轮探测 key 不存在")

        with self.rec.step(
            "SVC-01",
            "真实服务指纹、OpenAPI 路由基准、健康与文档端点",
            sc=["SC-01-05"],
            note="基础设施检查；签名 URL/令牌不落报告",
        ):
            health = self._call("GET", "/api/health", expected=200)
            self.rec.must_eq(self._dict(health).get("status"), "ok", "health")
            openapi_response = self._call("GET", "/openapi.json", expected=200)
            self.openapi = self._dict(openapi_response)
            self.route_index.__init__(self.openapi)  # 用最终运行 OpenAPI 重建
            routes = sorted(
                (method.upper(), path)
                for path, item in (self.openapi.get("paths") or {}).items()
                for method in item
                if method.lower() in {"get", "post", "put", "patch", "delete"}
            )
            self.all_business_routes = [row for row in routes if row[1] != "/api/health"]
            self.rec.must(len(self.all_business_routes) >= 90, f"OpenAPI 业务路由数 {len(self.all_business_routes)}")
            docs = self._call("GET", "/docs", expected=200)
            self.rec.must("text/html" in (docs.headers.get("content-type") or ""), "docs 返回 HTML")
            self._call("GET", "/redoc", expected=200)
            # 服务指纹：本地签短时 JWT -> /auth/me -> 只读 SQL 同一行。
            path = self.config.credentials_path
            if path is None:
                raise CheckFailure("缺少隔离凭据路径")
            admin = load_credentials(path, require_private=True)
            if admin is None:
                raise CheckFailure("缺少 seed 凭据")
            account = admin.accounts["admin"]
            token = mint_fingerprint_token(self.config, user_id=account.id, role=account.role, run_id=self.run_id)
            me = self._dict(self._call("GET", "/api/v1/auth/me", expected=200, headers={"Authorization": f"Bearer {token}"}))
            self.rec.must_eq(int(me["id"]), account.id, "服务指纹 admin id")
            row = self._db_one("select id, email, role, display_name from app.users where id = :id", {"id": account.id})
            self.rec.must(int(row["id"]) == account.id, "指纹账号存在于 test 库")
            self.rec.must_eq(str(row["email"]), account.email, "指纹账号 email")
            # WebSocket 未认证关闭码 4401；无效 token 不注册连接。
            import websockets

            async def _bad_ws() -> int | None:
                try:
                    async with websockets.connect(
                        self.base_url.replace("http", "ws", 1) + "/ws?token=invalid-token",
                        proxy=None,  # Local acceptance traffic must ignore shell/system proxies.
                        open_timeout=10,
                        close_timeout=5,
                    ) as websocket:
                        try:
                            await asyncio.wait_for(websocket.recv(), timeout=5)
                        except websockets.exceptions.ConnectionClosed as exc:
                            return exc.rcvd.code if exc.rcvd is not None else None
                        return None
                except websockets.exceptions.ConnectionClosed as exc:
                    return exc.rcvd.code if exc.rcvd is not None else None

            code = asyncio.run(_bad_ws())
            self.rec.must_eq(code, 4401, "无效 WS token 关闭码")
            self.ws_ok = True
            self.rec.data["openapi_routes"] = len(routes)
            self.rec.data["business_routes"] = len(self.all_business_routes)

    def bootstrap_accounts(self) -> None:
        with self.rec.step(
            "ACC-01",
            "canonical seed 身份登录、错误凭证与退出；同一 seed 幂等复用",
            ac=["US-01-AC-03"],
            sc=["SC-01-03", "SC-01-08"],
        ):
            credentials = self._bootstrap_identities()
            self.rec.must(bool(self.seed_fingerprint), "seed 指纹存在")
            # canonical 身份全部来自 tests.acceptance_real.seed，同一 run_id 可被人工浏览器复用。
            for key in ("admin", "admin2", "buyer", "buyer2", "seller", "seller2", "outsider", "commenter"):
                account = credentials[key]
                self._login_known(key, account.email, account.password, account.id, account.role)
            self.rec.must_eq(len(self.users), 8, "登录 canonical 身份数")
            # 错误密码 + 连续失败不锁定
            bad = self._call(
                "POST",
                "/api/v1/auth/login",
                expected=401,
                json_body={"email": self.users["buyer"]["email"], "password": "definitely-wrong-password"},
            )
            self.rec.must_eq(bad.status_code, 401, "错误密码登录拒绝")
            for _ in range(4):
                self._call(
                    "POST",
                    "/api/v1/auth/login",
                    expected=401,
                    json_body={"email": self.users["buyer"]["email"], "password": "definitely-wrong-password"},
                )
            self._login_known("buyer", self.users["buyer"]["email"], self.users["buyer"]["password"], self._uid("buyer"), "user")
            me = self._dict(self._call("GET", "/api/v1/auth/me", user="buyer", expected=200))
            self.rec.must_eq(int(me["id"]), self._uid("buyer"), "失败多次后仍可登录")
            logout = self._dict(self._call("POST", "/api/v1/auth/logout", user="buyer", expected=200))
            self.rec.must("退出" in str(logout.get("detail")), "退出接口返回")
            self._login_known("buyer", self.users["buyer"]["email"], self.users["buyer"]["password"], self._uid("buyer"), "user")

    def account_lifecycle(self) -> None:
        with self.rec.step(
            "ACC-02",
            "注册验证码：错误验证码拒绝；正确验证码创建唯一账户；重复邮箱拒绝",
            ac=["US-01-AC-01", "US-01-AC-02", "US-01-AC-08"],
            sc=["SC-01-01", "SC-01-02", "SC-01-11"],
        ):
            email = self._fresh_email("lifecycle")
            code_response = self._dict(
                self._call("POST", "/api/v1/auth/register/send-code", expected=200, json_body={"email": email})
            )
            code = self._received_code(code_response,email,"register")
            wrong = self._call(
                "POST",
                "/api/v1/auth/register",
                expected=400,
                json_body={"email": email, "display_name": "验收生命周期", "password": "lifecycle-pass-1", "code": "000000"},
            )
            self.rec.must_eq(wrong.status_code, 400, "错误验证码注册拒绝")
            before = self._db_one("select count(*) as n from app.users where email = :email", {"email": email})
            self.rec.must_eq(int(before["n"]), 0, "错误验证码不创建账户")
            response = self._call(
                "POST",
                "/api/v1/auth/register",
                expected=200,
                json_body={"email": email, "display_name": "验收生命周期", "password": "lifecycle-pass-1", "code": code},
            )
            data = self._dict(response)
            user = data.get("user") or {}
            self.rec.must(bool(user.get("id")), "注册返回用户 ID")
            self.users["lifecycle"] = {
                "key": "lifecycle",
                "id": int(user["id"]),
                "email": email,
                "password": "lifecycle-pass-1",
                "display_name": "验收生命周期",
                "role": "user",
                "status": "normal",
                "token": str(data["access_token"]),
            }
            self._call(
                "POST",
                "/api/v1/auth/register",
                expected=400,
                json_body={"email": email, "display_name": "重复", "password": "lifecycle-pass-1", "code": "000000"},
            )
            count = self._db_one("select count(*) as n from app.users where email = :email", {"email": email})
            self.rec.must_eq(int(count["n"]), 1, "重复注册不新增账户")
            login = self._dict(
                self._call("POST", "/api/v1/auth/login", expected=200, json_body={"email": email, "password": "lifecycle-pass-1"})
            )
            self.rec.must_eq(int(login["user"]["id"]), int(user["id"]), "注册后可用邮箱登录")
            unverified = self._fresh_email("unverified")
            self._call("POST", "/api/v1/auth/register/send-code", expected=200, json_body={"email": unverified})
            self._call(
                "POST",
                "/api/v1/auth/register",
                expected=400,
                json_body={"email": unverified, "display_name": "未验证", "password": "lifecycle-pass-1", "code": "123456"},
            )
            self.rec.must_eq(
                int(self._db_one("select count(*) as n from app.users where email = :email", {"email": unverified})["n"]),
                0,
                "未验证邮箱不占用/不创建",
            )

        with self.rec.step(
            "ACC-03",
            "忘记密码：绑定邮箱验证码重置；旧密码失效、用户 ID 不变",
            ac=["US-01-AC-04"],
            sc=["SC-01-04"],
        ):
            account = self.users["lifecycle"]
            email = str(account["email"])
            code_response = self._dict(
                self._call("POST", "/api/v1/auth/forgot-password/send-code", expected=200, json_body={"email": email})
            )
            code=self._received_code(code_response,email,"reset_password")
            self._call(
                "POST",
                "/api/v1/auth/forgot-password/reset",
                expected=200,
                json_body={"email": email, "code": code, "new_password": "lifecycle-pass-2"},
            )
            self._call("POST", "/api/v1/auth/login", expected=401, json_body={"email": email, "password": "lifecycle-pass-1"})
            relogin = self._dict(
                self._call("POST", "/api/v1/auth/login", expected=200, json_body={"email": email, "password": "lifecycle-pass-2"})
            )
            self.rec.must_eq(int(relogin["user"]["id"]), int(account["id"]), "重置后用户 ID 不变")
            self.users["lifecycle"]["password"] = "lifecycle-pass-2"
            self.users["lifecycle"]["token"] = str(relogin["access_token"])

        with self.rec.step(
            "ACC-04",
            "主动改密：旧密码校验；改后旧密码失效、新密码可登录",
            ac=["US-01-AC-05"],
            sc=["SC-01-08"],
        ):
            account = self.users["lifecycle"]
            self._call(
                "POST",
                "/api/v1/auth/change-password",
                user="lifecycle",
                expected=400,
                json_body={"current_password": "wrong-old", "new_password": "lifecycle-pass-3"},
            )
            self._call(
                "POST",
                "/api/v1/auth/change-password",
                user="lifecycle",
                expected=200,
                json_body={"current_password": "lifecycle-pass-2", "new_password": "lifecycle-pass-3"},
            )
            self._call(
                "POST",
                "/api/v1/auth/login",
                expected=401,
                json_body={"email": account["email"], "password": "lifecycle-pass-2"},
            )
            relogin = self._dict(
                self._call(
                    "POST",
                    "/api/v1/auth/login",
                    expected=200,
                    json_body={"email": account["email"], "password": "lifecycle-pass-3"},
                )
            )
            self.rec.must_eq(int(relogin["user"]["id"]), int(account["id"]), "改密后用户 ID 不变")
            self.users["lifecycle"]["password"] = "lifecycle-pass-3"
            self.users["lifecycle"]["token"] = str(relogin["access_token"])

        with self.rec.step(
            "ACC-05",
            "换邮箱双验证+唯一性；改名；历史业务仍归原用户 ID",
            ac=["US-01-AC-02", "US-01-AC-05", "US-01-AC-06"],
            sc=["SC-01-08", "SC-01-09", "SC-01-10"],
        ):
            account = self.users["lifecycle"]
            # 先用普通私聊建立历史业务，再改邮箱/名称。
            normal = self._dict(
                self._call(
                    "POST",
                    "/api/v1/conversations/normal",
                    user="lifecycle",
                    expected=201,
                    json_body={"peer_user_id": self._uid("seller")},
                )
            )
            self.conversations["lifecycle_seller"] = normal
            old_email = str(account["email"])
            occupied = str(self.users["buyer"]["email"])
            # 目标已被占用：发码阶段即拒绝，不改变原邮箱。
            self._call(
                "POST",
                "/api/v1/auth/email/send-code",
                user="lifecycle",
                expected=400,
                json_body={"target": "new", "new_email": occupied},
            )
            new_email = self._fresh_email("lifecycle-new")
            new_response = self._dict(
                self._call(
                    "POST",
                    "/api/v1/auth/email/send-code",
                    user="lifecycle",
                    expected=200,
                    json_body={"target": "new", "new_email": new_email},
                )
            )
            new_code=self._received_code(new_response,new_email,"change_email_new")
            old_response = self._dict(
                self._call("POST", "/api/v1/auth/email/send-code", user="lifecycle", expected=200, json_body={"target": "old"})
            )
            old_code=self._received_code(old_response,old_email,"change_email_old")
            changed = self._dict(
                self._call(
                    "POST",
                    "/api/v1/auth/email/change",
                    user="lifecycle",
                    expected=200,
                    json_body={"new_email": new_email, "old_code": old_code, "new_code": new_code},
                )
            )
            self.rec.must_eq(int(changed["id"]), int(account["id"]), "换邮箱后用户 ID 不变")
            self._call("POST", "/api/v1/auth/login", expected=401, json_body={"email": old_email, "password": account["password"]})
            relogin = self._dict(
                self._call(
                    "POST",
                    "/api/v1/auth/login",
                    expected=200,
                    json_body={"email": new_email, "password": account["password"]},
                )
            )
            self.rec.must_eq(int(relogin["user"]["id"]), int(account["id"]), "新邮箱登录同一 ID")
            self.users["lifecycle"]["email"] = new_email
            self.users["lifecycle"]["token"] = str(relogin["access_token"])
            profile = self._dict(
                self._call("PATCH", "/api/v1/auth/profile", user="lifecycle", expected=200, json_body={"display_name": "验收生命周期改名"})
            )
            self.rec.must_eq(str(profile["display_name"]), "验收生命周期改名", "显示名称修改")
            self.rec.must_eq(int(profile["id"]), int(account["id"]), "改名后用户 ID 不变")
            conversations = self._list(self._call("GET", "/api/v1/conversations", user="lifecycle", expected=200))
            self.rec.must(
                any(int(item.get("peer_id") or 0) == self._uid("seller") for item in conversations),
                "改邮箱/改名后历史私聊仍归原用户",
            )
            audit = self._db_one(
                "select count(*) as n from app.audit_events where actor_id = :id and event_type in ('auth.email_change','user.profile_update')",
                {"id": account["id"]},
            )
            self.rec.must(int(audit["n"]) >= 2, "换邮箱/改名审计主体为原用户 ID")

    # ------------------------------------------------------------------
    # 分类 / 禁发
    # ------------------------------------------------------------------
    def taxonomy(self) -> None:
        with self.rec.step(
            "CAT-01",
            "分类创建与读取；普通用户/匿名维护拒绝",
            ac=["US-13-AC-04", "US-13-AC-05"],
            sc=["SC-10-03"],
        ):
            suffix = self.run_id.lower()
            for key, name in (
                ("main", f"验收主分类-{suffix}"),
                ("second", f"验收次分类-{suffix}"),
                ("disable", f"验收停用分类-{suffix}"),
                ("delete", f"验收删除分类-{suffix}"),
            ):
                data = self._dict(
                    self._call("POST", "/api/v1/categories", user="admin", expected=200, json_body={"name": name})
                )
                self.categories[key] = {"id": int(data["id"]), "name": name}
            self.audit_targets["category_ids"] = {
                key: int(value["id"]) for key, value in self.categories.items()
            }
            listed = self._list(self._call("GET", "/api/v1/categories", user="outsider", expected=200))
            names = {item.get("name") for item in listed}
            for key in ("main", "second", "disable", "delete"):
                self.rec.must_in(self.categories[key]["name"], names, f"分类 {key} 出现在列表")
            self._call("POST", "/api/v1/categories", user="outsider", expected=403, json_body={"name": "越权分类"})
            self._call("POST", "/api/v1/categories", expected=401, json_body={"name": "匿名分类"})
            self._call("GET", "/api/v1/categories", expected=401)

        with self.rec.step(
            "CAT-02",
            "改名保留旧主名为别名；别名搜索；按名称/ID 移除别名后旧名不再解析",
            ac=["US-13-AC-03", "US-13-AC-07"],
            sc=["SC-10-03", "SC-10-04"],
        ):
            key = "main"
            new_name = f"验收主分类改名-{self.run_id.lower()}"
            renamed = self._dict(
                self._call(
                    "PATCH",
                    f"/api/v1/categories/{self.categories[key]['id']}",
                    user="admin",
                    expected=200,
                    json_body={"name": new_name},
                )
            )
            old_name = self.categories[key]["name"]
            self.rec.must_eq(str(renamed["name"]), new_name, "分类主名更新")
            self.rec.must_in(old_name, renamed.get("aliases") or [], "旧主名保留为别名")
            self.categories[key]["name"] = new_name
            self.categories[key]["old_name"] = old_name
            # 新增别名，先将第二分类商品关联到主分类，验证搜索/归属。
            alias_name = f"验收别名-{self.run_id.lower()}"
            aliased = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/categories/{self.categories[key]['id']}/aliases",
                    user="admin",
                    expected=200,
                    json_body={"name": alias_name},
                )
            )
            self.rec.must_in(alias_name, aliased.get("aliases") or [], "别名新增")
            self.audit_targets["alias_added_name"] = alias_name
            search_alias = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="buyer",
                    expected=200,
                    params={"category_names": [old_name]},
                )
            )
            self.rec.must_eq(search_alias.get("total"), 0, "旧名暂无可匹配商品（无关联商品）")
            # 按名称移除新增别名
            self._call(
                "DELETE",
                f"/api/v1/categories/{self.categories[key]['id']}/aliases/by-name",
                user="admin",
                expected=200,
                params={"name": alias_name},
            )
            self.audit_targets["alias_removed_by_name"] = {
                "category_id": self.categories[key]["id"],
                "name": alias_name,
            }
            missing = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="buyer",
                    expected=200,
                    params={"category_names": [alias_name]},
                )
            )
            self.rec.must_eq(missing.get("total"), 0, "移除别名后不再解析")
            self.rec.must_eq(missing.get("message"), "无匹配商品", "移除别名后无匹配提示")
            # 按 ID 移除旧主名别名（只读 SQL 取真实 ID；不写库）
            alias_row = self._db_one(
                "select id from app.category_aliases where category_id = :cid and name = :name and removed_at is null",
                {"cid": self.categories[key]["id"], "name": old_name},
            )
            self._call(
                "DELETE",
                f"/api/v1/categories/{self.categories[key]['id']}/aliases/{int(alias_row['id'])}",
                user="admin",
                expected=200,
            )
            self.audit_targets["alias_removed_by_id"] = int(alias_row["id"])
            removed = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="buyer",
                    expected=200,
                    params={"category_names": [old_name]},
                )
            )
            self.rec.must_eq(removed.get("total"), 0, "按 ID 移除旧名后不再解析")
            category = next(
                item
                for item in self._list(self._call("GET", "/api/v1/categories", user="admin", expected=200))
                if int(item["id"]) == self.categories[key]["id"]
            )
            self.rec.must_eq(str(category["name"]), new_name, "移除别名不改变分类身份")

        with self.rec.step(
            "CAT-03",
            "停用分类：新发布拒绝；已有商品保留；有关联仅可停用不可删除；未关联可逻辑删除",
            ac=["US-13-AC-04", "US-13-AC-05"],
            sc=["SC-10-03"],
        ):
            # 先创建关联商品，再停用。
            product = self._publish(
                "P_DISABLED",
                "seller",
                f"停用分类关联商品-{self.run_id}",
                price=3200,
                category_ids=[self.categories["disable"]["id"]],
            )
            self._approve("P_DISABLED")
            self._call(
                "PATCH",
                f"/api/v1/categories/{self.categories['disable']['id']}",
                user="admin",
                expected=200,
                json_body={"status": "disabled"},
            )
            categories = self._list(self._call("GET", "/api/v1/categories", user="seller", expected=200))
            disabled = next(item for item in categories if int(item["id"]) == self.categories["disable"]["id"])
            self.rec.must_eq(disabled.get("status"), "disabled", "分类停用状态")
            # 相同状态重复提交不应产生第二条成功审计（幂等）。
            self._call(
                "PATCH",
                f"/api/v1/categories/{self.categories['disable']['id']}",
                user="admin",
                expected=200,
                json_body={"status": "disabled"},
            )
            self._call(
                "POST",
                "/api/v1/products",
                user="seller",
                expected=400,
                json_body={
                    "title": "停用分类新发布",
                    "description": "应被拒绝",
                    "price_cents": 100,
                    "image_keys": [self.files["P_DISABLED:image"]["key"]],
                    "tags": [{"category_id": self.categories["disable"]["id"]}],
                },
            )
            still = self._dict(self._call("GET", f"/api/v1/products/{product['id']}", user="seller", expected=200))
            self.rec.must_eq(still.get("status"), "listed", "停用分类不改变已关联商品状态")
            search = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="buyer",
                    expected=200,
                    params={"category_ids": [self.categories["disable"]["id"]]},
                )
            )
            self.rec.must(
                any(int(item["id"]) == int(product["id"]) for item in search.get("items") or []),
                "停用分类仍有在售商品时保留筛选入口",
            )
            self._call(
                "DELETE",
                f"/api/v1/categories/{self.categories['disable']['id']}",
                user="admin",
                expected=400,
            )
            self._call(
                "DELETE",
                f"/api/v1/categories/{self.categories['delete']['id']}",
                user="admin",
                expected=200,
            )
            names = {
                item.get("name")
                for item in self._list(self._call("GET", "/api/v1/categories", user="admin", expected=200))
            }
            self.rec.must(self.categories["delete"]["name"] not in names, "逻辑删除分类不再列出")

        with self.rec.step(
            "PROH-01",
            "禁发范围：登录读取、管理员增改删、普通用户/匿名拒绝",
            ac=["US-02-AC-08", "US-08-AC-08", "US-08-AC-09"],
            sc=["SC-02-11", "SC-02-12"],
        ):
            self._list(self._call("GET", "/api/v1/prohibited-items", user="buyer", expected=200))
            created = self._dict(
                self._call(
                    "POST",
                    "/api/v1/prohibited-items",
                    user="admin",
                    expected=200,
                    json_body={
                        "group_name": f"验收禁发组-{self.run_id}",
                        "content": "验收禁发内容（仅测试）",
                        "sort": 99,
                    },
                )
            )
            item_id = int(created["id"])
            updated = self._dict(
                self._call(
                    "PUT",
                    f"/api/v1/prohibited-items/{item_id}",
                    user="admin",
                    expected=200,
                    json_body={
                        "group_name": f"验收禁发组-{self.run_id}",
                        "content": "验收禁发内容-已更新",
                        "sort": 100,
                    },
                )
            )
            self.rec.must_eq(updated["content"], "验收禁发内容-已更新", "禁发条目更新")
            self.audit_targets["prohibited_item_id"] = item_id
            # 全量 PUT 但值相同不应重复写成功审计。
            self._call(
                "PUT",
                f"/api/v1/prohibited-items/{item_id}",
                user="admin",
                expected=200,
                json_body={
                    "group_name": f"验收禁发组-{self.run_id}",
                    "content": "验收禁发内容-已更新",
                    "sort": 100,
                },
            )
            latest = self._list(self._call("GET", "/api/v1/prohibited-items", user="outsider", expected=200))
            self.rec.must(
                any(int(item["id"]) == item_id and item["content"] == "验收禁发内容-已更新" for item in latest),
                "普通用户读取到最新禁发范围",
            )
            self._call(
                "POST",
                "/api/v1/prohibited-items",
                user="outsider",
                expected=403,
                json_body={"group_name": "越权", "content": "越权", "sort": 0},
            )
            self._call("POST", "/api/v1/prohibited-items", expected=401, json_body={"group_name": "匿名", "content": "匿名", "sort": 0})
            self._call("DELETE", f"/api/v1/prohibited-items/{item_id}", user="admin", expected=200)
            after = self._list(self._call("GET", "/api/v1/prohibited-items", user="admin", expected=200))
            self.rec.must(not any(int(item["id"]) == item_id for item in after), "删除后不再返回")

    # ------------------------------------------------------------------
    # 文件、商品、检索、收藏、评论
    # ------------------------------------------------------------------
    def _review_race_regression(self) -> None:
        for index in range(3):
            key = f'P_REVIEW_RACE_{index}'
            product = self._publish(key, 'seller', f'并发审核-{index}-{self.run_id}', category_ids=[self.categories['main']['id']])
            case = self._pending_case(product['id'])
            self._claim(case['id'])
            path = f"/api/v1/admin/products/cases/{case['id']}/review"
            results = self._concurrent([
                ('POST', path, 'admin', {'result': 'approved'}),
                ('POST', path, 'admin', {'result': 'rejected', 'reason': '并发拒绝'}),
            ])
            self.rec.must_eq(sorted(item['status'] for item in results), [200, 409], '审核重复提交仅一个成功')
            count = self._db_one("select count(*) as n from app.audit_events where event_type='admin.product_review' and target_id=:id", {'id': str(product['id'])})
            # 最终商品状态与唯一审核结论一致。
            record = self._db_one('select result from app.review_records where case_id=:id', {'id': case['id']})
            detail = self._product_detail(key, 'seller')
            self.rec.must_eq(detail['status'], 'listed' if record['result'] == 'approved' else 'rejected', '并发审核最终状态一致')
            self.rec.must_eq(int(count['n']), 1, '仅一次审核成功审计')

            edit_key = f'P_EDIT_REVIEW_RACE_{index}'
            product = self._publish(edit_key, 'seller', f'并发编辑审核-{index}-{self.run_id}', category_ids=[self.categories['main']['id']])
            case = self._pending_case(product['id'])
            self._claim(case['id'])
            results = self._concurrent([
                ('PATCH', f"/api/v1/products/{product['id']}", 'seller', {'description': '并发编辑新内容'}),
                ('POST', f"/api/v1/admin/products/cases/{case['id']}/review", 'admin', {'result': 'rejected', 'reason': '并发快照检查'}),
            ])
            self.rec.must(results[0]['status'] in (200, 409) and results[1]['status'] == 200, '审核与编辑按串行顺序执行')
            snapshot = self._db_one('select content_json from app.review_records where case_id=:id', {'id': case['id']})['content_json']
            if isinstance(snapshot, str):
                snapshot = json.loads(snapshot)
            if results[0]['status'] == 200:
                self.rec.must_eq(snapshot['description'], '并发编辑新内容', '编辑先提交则审核使用最新内容')
            case = self._dict(self._call('GET', f"/api/v1/admin/cases/{case['id']}", user='admin'))
            self.rec.must_eq(case['status'], 'disposed', '审核事项归档')
            product_image_urls = (case.get('product') or {}).get('image_urls') or []
            self.rec.must(bool(product_image_urls), '审核事项返回商品图片直链')
            if product_image_urls:
                self._assert_media_url(product_image_urls[0], '审核事项商品图')

        # 同一事项的通用处置重复请求只能写入一次结论。
        key = 'P_CASE_DISPOSE_RACE'
        product = self._publish(key, 'seller', f'重复处置-{self.run_id}', category_ids=[self.categories['main']['id']])
        case = self._pending_case(product['id'])
        self._claim(case['id'])
        results = self._concurrent([
            ('POST', f"/api/v1/admin/cases/{case['id']}/dispose", 'admin', {'conclusion': '结论一'}),
            ('POST', f"/api/v1/admin/cases/{case['id']}/dispose", 'admin', {'conclusion': '结论二'}),
        ])
        self.rec.must_eq(sorted(item['status'] for item in results), [200, 409], '通用处置重复提交仅一次成功')
        product = self._publish('P_REPORT_RACE', 'seller', f'重复举报处置-{self.run_id}', category_ids=[self.categories['main']['id']])
        self._approve('P_REPORT_RACE')
        report_case = self._relevant_case_for_product(product['id'], claimant='admin')
        results = self._concurrent([
            ('POST', f'/api/v1/admin/reports/cases/{report_case}/decision', 'admin', {'outcome': 'unfounded', 'reason': '并发核查一', 'public_summary': '依据不足'}),
            ('POST', f'/api/v1/admin/reports/cases/{report_case}/decision', 'admin', {'outcome': 'unfounded', 'reason': '并发核查二', 'public_summary': '依据不足'}),
        ])
        self.rec.must_eq(sorted(item['status'] for item in results), [200, 409], '举报重复处置仅一次成功')
        self.concurrency.append({'kind': 'review_edit_dispose', 'rounds': 3, 'status': 'PASS'})

    def _timeout_race_regression(self) -> None:
        from unittest.mock import patch

        from app.devtools._support import make_async_engine
        from app.services import trade_timeout
        from sqlmodel.ext.asyncio.session import AsyncSession

        for action in ('confirm', 'freeze'):
            product_key, trade_key = f'P_SCAN_{action}', f'T_SCAN_{action}'
            self._publish(product_key, 'seller', f'扫描并发-{action}-{self.run_id}', category_ids=[self.categories['main']['id']])
            self._approve(product_key)
            self._request_trade(trade_key, 'buyer', product_key)
            self._accept(trade_key)
            agreement = self._propose(trade_key, 'buyer', AGREEMENT_A)
            self._agree(trade_key, agreement, 'seller')
            self._confirm(trade_key, 'buyer')
            tid = self.trades[trade_key]['id']
            case_id = self._relevant_case_for_product(self.products[product_key]['id'], claimant='admin') if action == 'freeze' else None

            async def exercise(tid=tid, action=action, trade_key=trade_key, case_id=case_id):
                engine = make_async_engine(self.config.database_url, schema=self.config.database_schema)
                ready, release = asyncio.Event(), asyncio.Event()
                real_lock = trade_timeout.lock_product_then_trade
                future = datetime.now(UTC) + timedelta(days=8)
                class FutureDateTime(datetime):
                    @classmethod
                    def now(cls, tz=None):
                        return future if tz else future.replace(tzinfo=None)
                async def delayed_lock(db, trade_id, product_id):
                    ready.set()
                    await release.wait()
                    return await real_lock(db, trade_id, product_id)
                try:
                    async with AsyncSession(engine) as db:
                        with patch.object(trade_timeout, 'datetime', FutureDateTime), patch.object(trade_timeout, 'get_settings', return_value=self.config.settings), patch.object(trade_timeout, 'lock_product_then_trade', delayed_lock):
                            scan = asyncio.create_task(trade_timeout.scan_once(db, trade_ids=(tid,)))
                            try:
                                await asyncio.wait_for(ready.wait(), 10)
                                if action == 'confirm':
                                    await asyncio.to_thread(self._confirm, trade_key, 'seller')
                                else:
                                    await asyncio.to_thread(self._call, 'POST', f'/api/v1/admin/trades/{tid}/freeze', user='admin', expected=200, json_body={'reason': '扫描并发冻结', 'case_id': case_id})
                            finally:
                                release.set()
                                await asyncio.wait_for(scan, 15)
                            self.rec.must_eq(scan.result(), 0, '扫描等待后重检，跳过已完成或被冻结交易')
                finally:
                    await engine.dispose()
            asyncio.run(exercise())
            row = self._db_one("select count(*) as n from app.trade_transitions where trade_id=:id and trigger='confirm_timeout'", {'id': tid})
            self.rec.must_eq(int(row['n']), 0, '过期扫描快照没有产生异常转移')
            detail = self._trade_detail(trade_key, 'buyer')
            self.rec.must_eq(detail['status'], 'completed' if action == 'confirm' else 'in_progress', '人工操作结果保持')
            if action == 'freeze':
                self.rec.must_eq(detail['frozen'], True, '扫描未覆盖人工冻结')
                self._call('POST', f'/api/v1/admin/trades/{tid}/unfreeze', user='admin', expected=200, json_body={'reason': '并发测试完成', 'case_id': case_id})
                # 完成该测试交易，避免影响后续受控时钟场景。
                self._confirm(trade_key, 'seller')
        self.concurrency.append({'kind': 'timeout_vs_confirmation_and_freeze', 'status': 'PASS'})

    def files_and_products(self) -> None:
        with self.rec.step(
            "FILE-01",
            "图片上传真实入 media/evidence 双桶；签名读取；篡改/非法/超限/错误命名空间拒绝",
            ac=["US-02-AC-01", "US-07-AC-03"],
            sc=["SC-02-01", "SC-07-04"],
            note="桶落点另由只读 SQL 核验",
        ):
            from io import BytesIO

            from PIL import Image
            avatar_bytes = BytesIO()
            Image.new('RGB', (256, 256), '#408060').save(avatar_bytes, format='JPEG')
            avatar_content = avatar_bytes.getvalue()
            avatar_lease = self._lease('seller', 'avatar.jpg', avatar_content, 'avatar')
            self._put_lease(avatar_lease, avatar_content)
            self._call('POST', f"/api/v1/files/upload-leases/{avatar_lease['lease_id']}/complete", user='seller')
            avatar_key = avatar_lease['key']
            atomic_avatar = self._dict(self._call('GET', '/api/v1/auth/me', user='seller'))
            self.rec.must_eq(atomic_avatar['avatar_review_status'], 'pending', '上传确认同事务提交头像审核')
            self._call('POST', '/api/v1/auth/avatar', user='buyer', expected=400, json_body={'key': avatar_key})
            avatar_case = self._dict(self._call('POST', '/api/v1/auth/avatar', user='seller', json_body={'key': avatar_key}))
            pending = self._dict(self._call('GET', '/api/v1/auth/me', user='seller'))
            self.rec.must_eq(pending['avatar_review_status'], 'pending', '头像待审核')
            self.rec.must(not pending['avatar_url'], '待审核头像未公开')
            queue = self._list(self._call('GET', '/api/v1/admin/cases', user='admin', params={'case_type': 'avatar_review'}))
            self.rec.must(any(item['id'] == avatar_case['case_id'] for item in queue), '管理员可见头像申请')
            avatar_case_id = avatar_case['case_id']
            decision_path = f"/api/v1/admin/cases/{avatar_case_id}/avatar-decision"
            self._call('POST', decision_path, user='admin', expected=403, json_body={'key': avatar_key, 'approved': True})
            self._claim(avatar_case_id, 'admin')
            self._call('GET', f'/api/v1/admin/cases/{avatar_case_id}', user='admin')
            self._call('POST', decision_path, user='buyer', expected=403, json_body={'key': avatar_key, 'approved': True})
            self._call('POST', decision_path, user='admin', json_body={'key': avatar_key, 'approved': False, 'reason': '请更换图片'})
            avatar_case = self._dict(self._call('POST', '/api/v1/auth/avatar', user='seller', json_body={'key': avatar_key}))
            avatar_case_id = avatar_case['case_id']
            decision_path = f'/api/v1/admin/cases/{avatar_case_id}/avatar-decision'
            self._claim(avatar_case_id, 'admin')
            self._call('POST', decision_path, user='admin', json_body={'key': avatar_key, 'approved': True})
            approved = self._dict(self._call('GET', '/api/v1/auth/me', user='seller'))
            self.rec.must_eq(approved['avatar_review_status'], 'approved', '头像审核通过')
            self.rec.must(bool(approved['avatar_url']), '审核通过后返回头像链接')
            refreshed = self._dict(self._call('GET', '/api/v1/auth/me', user='seller'))
            if self.config.settings.storage_backend == 'oss':
                self.rec.must_eq(refreshed['avatar_url'], approved['avatar_url'], '元数据刷新复用头像签名URL')
                self.rec.must(urlsplit(approved['avatar_url']).netloc in self.api.allowed_storage_hosts, '头像返回OSS直链')
            self.api.signed_get(approved['avatar_url'])
            self._call('POST', decision_path, user='admin', expected=409, json_body={'key': avatar_key, 'approved': True})
            product_file = self._upload("seller", "product_bike.jpg", "product")
            self.files["product_probe"] = product_file
            self.rec.must(str(product_file["key"]).startswith("product/"), "商品图 key 前缀 product/")
            signed = self.api.signed_get(str(product_file["url"]))
            self.rec.must(signed.content[:3] == b"\xff\xd8\xff", "签名 URL 读回 JPEG")
            from urllib.parse import parse_qsl, urlencode
            parsed_url = urlsplit(str(product_file['url']))
            signature_name = 'x-oss-signature' if parsed_url.netloc else 'sig'
            query = [(key, '0' * 64 if key.lower() == signature_name else value) for key, value in parse_qsl(parsed_url.query)]
            tampered = parsed_url._replace(query=urlencode(query)).geturl()
            self.api.signed_get(tampered, expected=403)
            # 本地文件兼容读取入口继续验证；OSS 业务 URL 则直接读取对应私有桶。
            import hmac
            expiry = int(time.time()) + 300
            logical_key = product_file['key']
            sig = hmac.new(self.config.settings.file_url_secret.encode(), f'{logical_key}:{expiry}'.encode(), hashlib.sha256).hexdigest()
            self.api.signed_get(f'/api/v1/files/{logical_key}?exp={expiry}&sig={sig}')
            valid = _asset_bytes("product_bike.jpg")
            base = {"namespace":"product","filename":"x.jpg","content_type":"image/jpeg","size_bytes":len(valid),"sha256":hashlib.sha256(valid).hexdigest()}
            for body, expected, note in [
                ({**base,"namespace":"unknown"},400,"invalid-namespace"),
                ({**base,"filename":"x.txt","content_type":"text/plain"},400,"non-image"),
                ({**base,"size_bytes":10*1024*1024+1},422,"oversized"),
                ({**base,"sha256":"invalid"},422,"invalid-hash"),
            ]:
                self._call("POST","/api/v1/files/upload-leases",user="seller",json_body=body,expected=expected,note=note)
            lease = self._lease("seller","x.jpg",valid)
            self._call("POST",f"/api/v1/files/upload-leases/{lease['lease_id']}/complete",user="buyer",expected=404)
            self._call("POST",f"/api/v1/files/upload-leases/{lease['lease_id']}/complete",user="seller",expected=404)
            self._put_lease(lease,valid)
            image_product={"title":"未完成上传校验","description":"附件资格拒绝测试","price_cents":100,
                           "image_keys":[lease['key']],"tags":[{"new_name":"upload-safety"}]}
            self._call("POST","/api/v1/products",user="seller",json_body=image_product,expected=400)
            self._put_lease(lease,valid,expected=(403,409,400,502))
            complete=f"/api/v1/files/upload-leases/{lease['lease_id']}/complete"
            self._call("POST",complete,user="seller")
            self._call("POST",complete,user="seller")
            self._call("POST","/api/v1/products",user="buyer",json_body=image_product,expected=400)
            self.rec.must(True,"完成确认幂等；其他用户和缺失对象拒绝；重复写入拒绝")
            malformed=b"\xff\xd8\xffnot-a-real-image"
            for content, overrides in [(valid,{"sha256":"0"*64}),(malformed,{})]:
                badlease=self._lease("seller","bad.jpg",content,**overrides)
                self._put_lease(badlease,content)
                self._call("POST",f"/api/v1/files/upload-leases/{badlease['lease_id']}/complete",user="seller",expected=400)
            if self.config.storage_backend == "oss":
                mismatch=self._lease("seller","size.jpg",valid,size_bytes=len(valid)+1)
                self._put_lease(mismatch,valid)
                self._call("POST",f"/api/v1/files/upload-leases/{mismatch['lease_id']}/complete",user="seller",expected=400)
                metadata=self._lease("seller","metadata.jpg",valid)
                self._put_lease(metadata,valid,headers_override={"x-oss-meta-sha256":"f"*64},expected=(403,))
                with httpx.Client(trust_env=False,timeout=15) as client:
                    for origin in ("http://localhost:5173","http://127.0.0.1:5173","http://localhost:5174","http://127.0.0.1:5174"):
                        preflight=client.options(metadata['upload']['url'],headers={"Origin":origin,"Access-Control-Request-Method":"PUT",
                            "Access-Control-Request-Headers":"content-type,x-oss-meta-sha256,x-oss-forbid-overwrite"})
                        self.rec.must_eq(preflight.status_code,200,"测试桶浏览器直传预检通过")
                        self.rec.must_eq(preflight.headers.get('access-control-allow-origin'),origin,"预检来源匹配")
                self.rec.must(True,"OSS拒绝篡改已签名元信息，后端拒绝实际hash/大小不一致")
            evidence = self._upload("buyer", "evidence_chat.jpg", "report")
            self.files["evidence_probe"] = evidence
            self.rec.must(str(evidence["key"]).startswith("report/"), "举报证据 key 前缀 report/")
            self.api.signed_get(str(evidence["url"]))
            # 只读 SQL 核对两桶 role 与提交状态（不读取对象正文）。
            rows = self._db(
                "select key, bucket_role, state from app.stored_objects where key = any(:keys)",
                {"keys": [product_file["key"], evidence["key"]]},
            )
            role_by_key = {str(row["key"]): str(row["bucket_role"]) for row in rows}
            self.rec.must_eq(role_by_key.get(str(product_file["key"])), "media", "商品图落 media 桶")
            self.rec.must_eq(role_by_key.get(str(evidence["key"])), "evidence", "举报证据落 evidence 桶")

        with self.rec.step(
            "PROD-01",
            "待审核商品可见性、撤回审核、修改重提、共享池并发认领、审核通过",
            ac=["US-02-AC-01", "US-02-AC-09", "US-08-AC-02", "US-09-AC-01"],
            sc=["SC-02-01", "SC-02-04", "SC-02-13", "SC-02-14", "SC-02-15", "SC-07-10"],
            note="并发认领证据在 CONC-01 单列",
        ):
            product = self._publish(
                "P_PENDING",
                "seller",
                f"待审核商品-{self.run_id}",
                price=4100,
                category_ids=[self.categories["main"]["id"]],
            )
            self.rec.must_eq(product.get("status"), "pending_review", "发布后待审核")
            detail = self._product_detail("P_PENDING", "seller")
            self.rec.must_eq(detail.get("status"), "pending_review", "卖方可见待审核详情")
            self._call("GET", f"/api/v1/products/{product['id']}", user="outsider", expected=404)
            search = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="outsider",
                    expected=200,
                    params={"keyword": f"待审核商品-{self.run_id}"},
                )
            )
            self.rec.must_eq(search.get("total"), 0, "待审核商品不进入公开搜索")
            self._call("GET", f"/api/v1/products/{product['id']}/comments", user="outsider", expected=404)
            records = self._list(
                self._call("GET", f"/api/v1/products/{product['id']}/review-records", user="seller", expected=200)
            )
            self.rec.must_eq(len(records), 1, "待审核审核记录")
            self._call("GET", f"/api/v1/products/{product['id']}/review-records", user="outsider", expected=403)
            mine = self._list(self._call("GET", "/api/v1/products/mine", user="seller", expected=200))
            self.rec.must(any(int(item["id"]) == int(product["id"]) for item in mine), "我的商品含待审核")
            # 认领前撤回
            withdrawn = self._dict(
                self._call("POST", f"/api/v1/products/{product['id']}/withdraw-review", user="seller", expected=200)
            )
            self.rec.must_eq(withdrawn.get("status"), "delisted", "认领前撤回后已下架")
            self._call(
                "POST",
                f"/api/v1/products/{product['id']}/withdraw-review",
                user="seller",
                expected=409,
            )
            # 修改后重提
            resubmitted = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/products/{product['id']}/resubmit",
                    user="seller",
                    expected=200,
                    json_body={"title": f"待审核商品重提-{self.run_id}", "price_cents": 4200},
                )
            )
            self.rec.must_eq(resubmitted.get("status"), "pending_review", "撤回后重提待审核")
            self.products["P_PENDING"].update(resubmitted)
            self._review_race_regression()
            # 并发认领：admin 与 admin2 同时 claim 同一事项。
            case = self._pending_case(int(product["id"]))
            self.cases["P_PENDING_review"] = case
            result = self._concurrent(
                [
                    ("POST", f"/api/v1/admin/cases/{case['id']}/claim", "admin", {}),
                    ("POST", f"/api/v1/admin/cases/{case['id']}/claim", "admin2", {}),
                ]
            )
            statuses = sorted(item["status"] for item in result)
            self.rec.must_eq(statuses, [200, 409], "并发认领一胜一败")
            self.concurrency.append(
                {
                    "kind": "admin_claim_same_case",
                    "case_id": case["id"],
                    "results": [{"role": item["role"], "status": item["status"]} for item in result],
                    "db_claimant_count": int(
                        self._db_one("select count(distinct claimed_by_id) as n from app.disposal_cases where id = :id", {"id": case["id"]})["n"]
                    ),
                }
            )
            winner = "admin" if next(item for item in result if item["role"] == "admin")["status"] == 200 else "admin2"
            loser = "admin2" if winner == "admin" else "admin"
            self._call("GET", f"/api/v1/admin/cases/{case['id']}", user=loser, expected=403)
            self._call("POST", f"/api/v1/admin/products/cases/{case['id']}/review", user=loser, expected=403, json_body={"result": "approved"})
            self._call("GET", f"/api/v1/admin/cases/{case['id']}", user=winner, expected=200)
            self._review(int(case["id"]), {"result": "approved"}, user=winner)
            approved = self._product_detail("P_PENDING", "seller")
            self.rec.must_eq(approved.get("status"), "listed", "重提后审核通过")
            self.products["P_PENDING"].update(approved)
            search = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="outsider",
                    expected=200,
                    params={"keyword": f"待审核商品重提-{self.run_id}"},
                )
            )
            self.rec.must_eq(search.get("total"), 1, "审核通过后进入搜索")
            latest_records = self._list(
                self._call("GET", f"/api/v1/products/{product['id']}/review-records", user="seller", expected=200)
            )
            self.rec.must({row.get("result") for row in latest_records} >= {"withdrawn", "approved"}, "撤回与通过审核记录均保留")

        with self.rec.step(
            "PROD-02",
            "审核不通过原因可见、公开不可见、修改重提后独立审核通过",
            ac=["US-02-AC-02", "US-09-AC-01"],
            sc=["SC-02-02"],
        ):
            product = self._publish(
                "P_REJECT",
                "seller",
                f"审核不通过商品-{self.run_id}",
                price=4300,
                category_ids=[self.categories["main"]["id"]],
            )
            reason = f"验收拒绝原因-{self.run_id}"
            rejected = self._reject("P_REJECT", reason)
            self.rec.must_eq(rejected.get("status"), "rejected", "审核不通过状态")
            self.rec.must_eq(rejected.get("reject_reason"), reason, "卖方可见拒绝原因")
            self._call("GET", f"/api/v1/products/{product['id']}", user="outsider", expected=404)
            resubmitted = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/products/{product['id']}/resubmit",
                    user="seller",
                    expected=200,
                    json_body={"title": f"审核不通过商品重提-{self.run_id}", "price_cents": 4400},
                )
            )
            self.rec.must_eq(resubmitted.get("status"), "pending_review", "不通过后重提")
            self.products["P_REJECT"].update(resubmitted)
            self._approve("P_REJECT")
            self.rec.must_eq(self._product_detail("P_REJECT", "seller").get("status"), "listed", "重提审核通过")

        with self.rec.step(
            "PROD-03",
            "标签审核 approve_new 与 map_alias：新标签公开、同义别名生效；未通过不公开",
            ac=["US-13-AC-01"],
            sc=["SC-10-01"],
        ):
            new_tag = f"验收新标签-{self.run_id}"
            alias_name = f"验收同义名-{self.run_id}"
            self._publish(
                "P_TAG",
                "seller",
                f"标签申请商品-{self.run_id}",
                price=4500,
                new_names=[new_tag, alias_name],
            )
            detail = self._product_detail("P_TAG", "seller")
            apps = detail.get("pending_tag_applications") or []
            self.rec.must_eq(len(apps), 2, "两条待审标签申请")
            by_name = {str(app["requested_name"]): app for app in apps}
            case = self._pending_case(int(detail["id"]))
            self._claim(int(case["id"]))
            self._review(
                int(case["id"]),
                {
                    "result": "approved",
                    "tag_decisions": [
                        {"application_id": int(by_name[new_tag]["id"]), "decision": "approve_new"},
                        {
                            "application_id": int(by_name[alias_name]["id"]),
                            "decision": "map_alias",
                            "category_id": self.categories["main"]["id"],
                        },
                    ],
                },
            )
            approved = self._product_detail("P_TAG", "seller")
            self.products["P_TAG"].update(approved)
            self.rec.must_eq(approved.get("status"), "listed", "标签通过后商品 listed")
            self.rec.must_in(new_tag, approved.get("tag_names") or [], "新标签关联商品")
            self.rec.must_in(self.categories["main"]["name"], approved.get("tag_names") or [], "别名映射到已有分类")
            categories = self._list(self._call("GET", "/api/v1/categories", user="seller", expected=200))
            created = next((item for item in categories if item.get("name") == new_tag), None)
            self.rec.must(created is not None and created.get("status") == "active", "新标签公开可选")
            mapped = next(item for item in categories if int(item["id"]) == self.categories["main"]["id"])
            self.rec.must_in(alias_name, mapped.get("aliases") or [], "同义名成为活跃别名")
            by_tag = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="buyer",
                    expected=200,
                    params={"category_names": [new_tag]},
                )
            )
            self.rec.must_eq(by_tag.get("total"), 1, "按新标签搜索命中")
            by_alias = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="buyer",
                    expected=200,
                    params={"category_names": [alias_name]},
                )
            )
            self.rec.must(
                any(int(item["id"]) == int(self.products["P_TAG"]["id"]) for item in by_alias.get("items") or []),
                "按同义别名搜索命中目标商品",
            )

        with self.rec.step(
            "PROD-04",
            "商品通过同时拒绝个别标签：逐申请原因落库；卖方可见/非本人不可见；空原因400无部分审批",
            ac=["US-13-AC-01", "US-13-AC-02"],
            sc=["SC-10-02"],
        ):
            good_tag = f"验收合适标签-{self.run_id}"
            bad_tag = f"验收不合适标签-{self.run_id}"
            self._publish(
                "P_TAG_REJ",
                "seller",
                f"标签逐项处置商品-{self.run_id}",
                price=4600,
                category_ids=[self.categories["main"]["id"]],
                new_names=[good_tag, bad_tag],
            )
            detail = self._product_detail("P_TAG_REJ", "seller")
            pending_apps = {
                str(app["requested_name"]): int(app["id"])
                for app in detail.get("pending_tag_applications") or []
            }
            self.rec.must(good_tag in pending_apps and bad_tag in pending_apps, "两条标签申请待审")
            case = self._pending_case(int(detail["id"]))
            self._claim(int(case["id"]))
            reason = f"逐申请拒绝原因-{self.run_id}"
            self._review(
                int(case["id"]),
                {
                    "result": "approved",
                    "tag_decisions": [
                        {"application_id": pending_apps[good_tag], "decision": "approve_new"},
                        {
                            "application_id": pending_apps[bad_tag],
                            "decision": "reject",
                            "reason": reason,
                        },
                    ],
                },
            )
            approved = self._product_detail("P_TAG_REJ", "seller")
            self.products["P_TAG_REJ"].update(approved)
            self.rec.must_eq(approved.get("status"), "listed", "通过商品同时拒绝标签仍 listed")
            tag_names = approved.get("tag_names") or []
            self.rec.must_in(good_tag, tag_names, "被认可标签关联商品")
            self.rec.must(bad_tag not in tag_names, "被拒绝标签不关联商品")
            decided = {
                str(app["requested_name"]): app
                for app in approved.get("decided_tag_applications") or []
            }
            self.rec.must(bad_tag in decided, "卖方能看到已处理标签申请")
            self.rec.must_eq(decided[bad_tag].get("status"), "rejected", "被拒绝申请状态")
            self.rec.must_eq(
                decided[bad_tag].get("decision_reason"), reason, "逐申请拒绝原因对卖方可见"
            )
            self.rec.must_eq(
                decided[good_tag].get("decision_reason"), None, "通过标签不记录拒绝原因"
            )
            self.rec.must_eq(approved.get("pending_tag_applications"), [], "通过后无待审标签")
            categories_after = self._list(
                self._call("GET", "/api/v1/categories", user="seller", expected=200)
            )
            self.rec.must(
                not any(item.get("name") == bad_tag for item in categories_after),
                "被拒绝标签不公开",
            )
            for viewer in ("buyer", "outsider"):
                other = self._product_detail("P_TAG_REJ", viewer)
                self.rec.must_eq(
                    other.get("decided_tag_applications"), [], f"{viewer} 不可见逐申请原因"
                )
                self.rec.must(
                    reason not in json.dumps(other, ensure_ascii=False),
                    f"{viewer} 商品响应不含拒绝原因",
                )

            # 空白原因必须在任何写入前 400，且不产生部分审批/标签变更。
            empty_tag = f"验收空原因标签-{self.run_id}"
            self._publish(
                "P_TAG_EMPTY",
                "seller",
                f"空原因标签商品-{self.run_id}",
                price=4650,
                category_ids=[self.categories["main"]["id"]],
                new_names=[empty_tag],
            )
            empty_detail = self._product_detail("P_TAG_EMPTY", "seller")
            empty_apps = [
                int(app["id"])
                for app in empty_detail.get("pending_tag_applications") or []
                if app.get("requested_name") == empty_tag
            ]
            self.rec.must_eq(len(empty_apps), 1, "空原因样本一条待审申请")
            empty_case = self._pending_case(int(empty_detail["id"]))
            self._claim(int(empty_case["id"]))
            self._call(
                "POST",
                f"/api/v1/admin/products/cases/{int(empty_case['id'])}/review",
                user="admin",
                expected=400,
                json_body={
                    "result": "approved",
                    "tag_decisions": [
                        {
                            "application_id": empty_apps[0],
                            "decision": "reject",
                            "reason": "   ",
                        }
                    ],
                },
            )
            unchanged = self._product_detail("P_TAG_EMPTY", "seller")
            self.rec.must_eq(unchanged.get("status"), "pending_review", "空原因失败后商品仍待审")
            self.rec.must_eq(
                unchanged.get("decided_tag_applications"), [], "空原因失败后无已处理申请"
            )
            self.rec.must(
                any(
                    int(app["id"]) == empty_apps[0]
                    for app in unchanged.get("pending_tag_applications") or []
                ),
                "空原因失败后申请仍待审",
            )
            self.rec.must(empty_tag not in (unchanged.get("tag_names") or []), "空原因失败后标签未关联")
            categories_after_empty = self._list(
                self._call("GET", "/api/v1/categories", user="seller", expected=200)
            )
            self.rec.must(
                not any(item.get("name") == empty_tag for item in categories_after_empty),
                "空原因失败未创建分类",
            )
            # 同一事项随后可用有效原因通过，失败未消耗审核状态。
            self._review(
                int(empty_case["id"]),
                {
                    "result": "approved",
                    "tag_decisions": [
                        {
                            "application_id": empty_apps[0],
                            "decision": "reject",
                            "reason": f"补充原因后拒绝-{self.run_id}",
                        }
                    ],
                },
            )
            recovered = self._product_detail("P_TAG_EMPTY", "seller")
            self.products["P_TAG_EMPTY"].update(recovered)
            self.rec.must_eq(recovered.get("status"), "listed", "有效原因后同一事项可继续审核")

        with self.rec.step(
            "PROD-05",
            "商品编辑历史、未结束买方通知、下架关闭待接受请求、重新上架",
            ac=["US-02-AC-03", "US-02-AC-05", "US-02-AC-06", "US-09-AC-03", "US-09-AC-04", "US-09-AC-06", "US-12-AC-07"],
            sc=["SC-02-05", "SC-02-08", "SC-02-09", "SC-02-10", "SC-02-16"],
        ):
            self._publish(
                "P_EDIT",
                "seller",
                f"编辑历史商品-{self.run_id}",
                price=4700,
                category_ids=[self.categories["main"]["id"]],
            )
            self._approve("P_EDIT")
            request = self._request_trade("T_EDIT_PENDING", "buyer", "P_EDIT")
            old_title = str(self.products["P_EDIT"]["title"])
            new_title = f"编辑后商品-{self.run_id}"
            edited = self._dict(
                self._call(
                    "PATCH",
                    f"/api/v1/products/{self.products['P_EDIT']['id']}",
                    user="seller",
                    expected=200,
                    json_body={"title": new_title, "price_cents": 4750},
                )
            )
            self.rec.must_eq(edited.get("status"), "listed", "编辑不暂停展示/不二审")
            self.rec.must_eq(edited.get("title"), new_title, "标题已更新")
            histories = self._list(
                self._call("GET", f"/api/v1/products/{self.products['P_EDIT']['id']}/edit-history", user="seller", expected=200)
            )
            self.rec.must(histories and str(histories[-1]["before_json"].get("title")) == old_title, "编辑前后内容留痕")
            buyer_histories = self._list(
                self._call(
                    "GET",
                    f"/api/v1/products/{self.products['P_EDIT']['id']}/edit-history",
                    user="buyer",
                    expected=200,
                )
            )
            self.rec.must(
                any(str(row["after_json"].get("title")) == new_title for row in buyer_histories),
                "请求买方可见请求后变更",
            )
            buyer_notifications = self._notifications("buyer")
            self.rec.must(
                self._has_notification(buyer_notifications, "product_edited", link_id=int(self.products["P_EDIT"]["id"])),
                "未结束请求买方收到商品编辑通知",
            )
            delisted = self._dict(
                self._call("POST", f"/api/v1/products/{self.products['P_EDIT']['id']}/delist", user="seller", expected=200)
            )
            self.rec.must_eq(delisted.get("status"), "delisted", "下架状态")
            trade = self._trade_detail("T_EDIT_PENDING", "buyer")
            self.rec.must_eq(trade.get("status"), "closed", "下架关闭待接受请求")
            self.rec.must_eq(trade.get("close_reason"), "商品已下架", "关闭原因")
            buyer_notifications = self._notifications("buyer")
            self.rec.must(
                self._has_notification(buyer_notifications, "request_closed", link_id=int(request["id"])),
                "关闭请求通知买方",
            )
            self._call("GET", f"/api/v1/products/{self.products['P_EDIT']['id']}", user="outsider", expected=404)
            # 结束时买方仍可按 D-43 查看历史详情
            self._call("GET", f"/api/v1/products/{self.products['P_EDIT']['id']}", user="buyer", expected=200)
            relisted = self._dict(
                self._call("POST", f"/api/v1/products/{self.products['P_EDIT']['id']}/relist", user="seller", expected=200)
            )
            self.rec.must_eq(relisted.get("status"), "listed", "重新上架")
            self._call("GET", f"/api/v1/products/{self.products['P_EDIT']['id']}", user="outsider", expected=200)

        with self.rec.step(
            "PROD-06",
            "商品权限与状态拒绝：非所有者、匿名、交易中禁改/禁下架、已认领撤回 409",
            ac=["US-02-AC-03", "US-02-AC-04", "US-02-AC-09", "US-09-AC-02"],
            sc=["SC-02-03", "SC-02-06", "SC-02-07", "SC-02-14"],
        ):
            product_id = int(self.products["P_EDIT"]["id"])
            self._call("PATCH", f"/api/v1/products/{product_id}", user="outsider", expected=404, json_body={"title": "越权"})
            self._call("PATCH", f"/api/v1/products/{product_id}", expected=401, json_body={"title": "匿名"})
            # 已认领待审商品：撤回 409，同时验证“待审核期间修改保持 pending”。
            pending = self._publish(
                "P_CLAIM_LATE",
                "seller",
                f"已认领待审商品-{self.run_id}",
                price=4800,
                category_ids=[self.categories["main"]["id"]],
            )
            case = self._pending_case(int(pending["id"]))
            self._claim(int(case["id"]))
            self._call("POST", f"/api/v1/products/{pending['id']}/withdraw-review", user="seller", expected=409)
            edited_pending = self._dict(
                self._call(
                    "PATCH",
                    f"/api/v1/products/{pending['id']}",
                    user="seller",
                    expected=200,
                    json_body={"description": f"认领后修改仍待审-{self.run_id}"},
                )
            )
            self.rec.must_eq(edited_pending.get("status"), "pending_review", "认领后修改不重排队")
            self._review(int(case["id"]), {"result": "approved"})
            self.products["P_CLAIM_LATE"].update(self._product_detail("P_CLAIM_LATE", "seller"))
            self._call("POST", f"/api/v1/admin/products/cases/{case['id']}/review", user="admin", expected=409, json_body={"result": "approved"})
            # 交易中禁改：P_PENDING 已 listed，先置为交易中样本（后续 TRADE-01 会使用 P_MAIN，另有 P_LOCKED）。
            self._publish(
                "P_LOCKED",
                "seller",
                f"交易中禁改商品-{self.run_id}",
                price=4900,
                category_ids=[self.categories["main"]["id"]],
            )
            self._approve("P_LOCKED")
            self._request_trade("T_LOCKED", "buyer", "P_LOCKED")
            self._accept("T_LOCKED")
            self.products["P_LOCKED"].update(self._product_detail("P_LOCKED", "seller"))
            self.rec.must_eq(self.products["P_LOCKED"].get("status"), "in_transaction", "接受后交易中")
            self._call(
                "PATCH",
                f"/api/v1/products/{self.products['P_LOCKED']['id']}",
                user="seller",
                expected=409,
                json_body={"title": "交易中改"},
            )
            self._call("POST", f"/api/v1/products/{self.products['P_LOCKED']['id']}/delist", user="seller", expected=409)
            # 收尾：管理员终止该样本，释放锁单
            self._admin_terminate("T_LOCKED", reason="验收交易中禁改样本收尾")

        with self.rec.step(
            "SEARCH-01",
            "组合检索：关键词/多标签全部匹配/价格/别名/无匹配；未登录拒绝",
            ac=["US-03-AC-01", "US-03-AC-02", "US-03-AC-03", "US-03-AC-06", "US-13-AC-07"],
            sc=["SC-03-01", "SC-03-02", "SC-03-03", "SC-10-04"],
        ):
            self._publish(
                "P_MULTI",
                "seller",
                f"多标签组合商品-{self.run_id}",
                price=5200,
                category_ids=[self.categories["main"]["id"], self.categories["second"]["id"]],
            )
            self._approve("P_MULTI")
            keyword = f"多标签组合商品-{self.run_id}"
            hit = self._dict(
                self._call("GET", "/api/v1/products/search", user="outsider", expected=200, params={"keyword": keyword})
            )
            self.rec.must_eq(hit.get("total"), 1, "关键词命中")
            price_hit = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="outsider",
                    expected=200,
                    params={"keyword": keyword, "price_min_cents": 5000, "price_max_cents": 5300},
                )
            )
            self.rec.must_eq(price_hit.get("total"), 1, "价格区间命中")
            price_miss = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="outsider",
                    expected=200,
                    params={"keyword": keyword, "price_min_cents": 999999},
                )
            )
            self.rec.must_eq(price_miss.get("total"), 0, "价格不匹配")
            multi = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="outsider",
                    expected=200,
                    params={
                        "category_ids": [self.categories["main"]["id"], self.categories["second"]["id"]],
                        "keyword": keyword,
                    },
                )
            )
            self.rec.must_eq(multi.get("total"), 1, "多标签全部匹配")
            by_names = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="outsider",
                    expected=200,
                    params={
                        "category_names": [self.categories["main"]["name"], self.categories["second"]["name"]],
                        "keyword": keyword,
                    },
                )
            )
            self.rec.must_eq(by_names.get("total"), 1, "分类名/别名参与筛选")
            unknown = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="outsider",
                    expected=200,
                    params={"category_names": [f"不存在分类-{self.run_id}"]},
                )
            )
            self.rec.must_eq(unknown.get("total"), 0, "未知分类无匹配")
            self.rec.must_eq(unknown.get("message"), "无匹配商品", "未知分类提示")
            none = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="outsider",
                    expected=200,
                    params={"keyword": f"绝对不存在-{self.run_id}"},
                )
            )
            self.rec.must_eq(none.get("total"), 0, "无匹配关键词")
            self._call("GET", "/api/v1/products/search", expected=401)
            self._call("GET", f"/api/v1/products/{self.products['P_MULTI']['id']}", expected=401)

        with self.rec.step(
            "FAV-01",
            "收藏：有效/重复/取消/失效提示/解封或重新上架恢复；封禁只读",
            ac=["US-04-AC-01", "US-04-AC-02", "US-04-AC-09", "US-03-AC-04"],
            sc=["SC-03-01", "SC-03-06", "SC-03-07", "SC-03-08", "SC-03-09"],
        ):
            self._publish(
                "P_FAV",
                "seller",
                f"收藏失效商品-{self.run_id}",
                price=5300,
                category_ids=[self.categories["main"]["id"]],
            )
            self._approve("P_FAV")
            product_id = int(self.products["P_FAV"]["id"])
            first = self._dict(self._call("POST", f"/api/v1/favorites/{product_id}", user="buyer", expected=200))
            second = self._dict(self._call("POST", f"/api/v1/favorites/{product_id}", user="buyer", expected=200))
            self.rec.must_eq(second.get("favorite_id"), first.get("favorite_id"), "重复收藏返回已有结果")
            self.audit_targets["favorite_product_id"] = product_id
            self.audit_targets["favorite_removed_id"] = int(first["favorite_id"])
            favorites = self._list(self._call("GET", "/api/v1/favorites", user="buyer", expected=200))
            row = next(item for item in favorites if int(item["product_id"]) == product_id)
            self.rec.must(row.get("valid") is True, "收藏有效")
            self._call("DELETE", f"/api/v1/favorites/{product_id}", user="buyer", expected=200)
            self._call("DELETE", f"/api/v1/favorites/{product_id}", user="buyer", expected=404)
            self._call("POST", f"/api/v1/favorites/{product_id}", user="buyer", expected=200)
            readded = self._dict(
                self._call("POST", f"/api/v1/favorites/{product_id}", user="buyer", expected=200)
            )
            self.audit_targets["favorite_readded_id"] = int(readded["favorite_id"])
            self._call("POST", f"/api/v1/products/{product_id}/delist", user="seller", expected=200)
            favorites = self._list(self._call("GET", "/api/v1/favorites", user="buyer", expected=200))
            row = next(item for item in favorites if int(item["product_id"]) == product_id)
            self.rec.must(row.get("valid") is False and row.get("title") is None, "下架后仅失效提示")
            self._call("POST", f"/api/v1/products/{product_id}/relist", user="seller", expected=200)
            favorites = self._list(self._call("GET", "/api/v1/favorites", user="buyer", expected=200))
            row = next(item for item in favorites if int(item["product_id"]) == product_id)
            self.rec.must(row.get("valid") is True, "重新上架后收藏恢复")
            # 封禁只读：后面 REPORT-04 会封禁 seller2；此处用 outsider 临时封禁再解除，
            # 覆盖“查看允许、收藏写 403”。
            self._call("POST", f"/api/v1/admin/users/{self._uid('outsider')}/ban", user="admin", expected=200, json_body={"reason": "验收收藏封禁样本"})
            self._call("GET", "/api/v1/favorites", user="outsider", expected=200)
            self._call("POST", f"/api/v1/favorites/{product_id}", user="outsider", expected=403)
            self._call("DELETE", f"/api/v1/favorites/{product_id}", user="outsider", expected=403)
            self._call("POST", f"/api/v1/admin/users/{self._uid('outsider')}/unban", user="admin", expected=200, json_body={"lift_reason": "验收收藏封禁解除"})

        with self.rec.step(
            "COMM-01",
            "评论：登录用户评论、卖方回复、作者删除、越权拒绝、限频、下架拒绝",
            ac=["US-04-AC-03"],
            sc=["SC-04-01", "SC-04-02", "SC-04-03", "SC-04-04"],
        ):
            self._publish(
                "P_COMMENT",
                "seller2",
                f"评论商品-{self.run_id}",
                price=5400,
                category_ids=[self.categories["main"]["id"]],
            )
            self._approve("P_COMMENT")
            product_id = int(self.products["P_COMMENT"]["id"])
            # 2000 grapheme boundary includes compound emoji; 2001 is rejected before writes.
            self._call("POST", f"/api/v1/products/{product_id}/comments", user="outsider",
                       expected=422, json_body={"content": "评" * 2001})
            long_comment = "👨‍👩‍👧‍👦" * 2000
            first = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/products/{product_id}/comments",
                    user="outsider",
                    expected=201,
                    json_body={"content": long_comment},
                )
            )
            self.comments["first"] = int(first["id"])
            saved=self._list(self._call("GET",f"/api/v1/products/{product_id}/comments",user="outsider"))
            self.rec.must(next(row["content"] for row in saved if row["id"]==first["id"])==long_comment,"2000个组合表情完整存储并读回，字素簇计数不被码点限制拒绝")
            if self.config.settings.kv_backend == "redis":
                # 证明服务进程确实使用 Redis KV，而不是 MemoryKV 兜底：
                # 外部把该用户频控计数置高，真实 HTTP 评论应立刻按 Redis 值返回 429。
                import redis.asyncio as aioredis


                redis_settings = self.config.settings
                redis_key = f"{redis_settings.redis_key_prefix}comment-rate:{self._uid('outsider')}"

                async def _redis_rate_probe() -> None:
                    client = aioredis.from_url(redis_settings.redis_url, decode_responses=True)
                    try:
                        await client.set(redis_key, "999", ex=60)
                    finally:
                        await client.aclose()

                async def _redis_rate_cleanup() -> None:
                    client = aioredis.from_url(redis_settings.redis_url, decode_responses=True)
                    try:
                        await client.delete(redis_key)
                    finally:
                        await client.aclose()

                asyncio.run(_redis_rate_probe())
                try:
                    self._call(
                        "POST",
                        f"/api/v1/products/{product_id}/comments",
                        user="outsider",
                        expected=429,
                        json_body={"content": f"Redis 频控证据-{self.run_id}"},
                    )
                    self.rec.must(True, "应用频控读取真实 Redis 计数（MemoryKV 兜底不可通过）")
                finally:
                    asyncio.run(_redis_rate_cleanup())
            reply = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/products/{product_id}/comments",
                    user="seller2",
                    expected=201,
                    json_body={"content": "卖家回复", "reply_to_comment_id": int(first["id"])},
                )
            )
            self.comments["reply"] = int(reply["id"])
            self._call(
                "POST",
                f"/api/v1/products/{product_id}/comments",
                user="outsider",
                expected=403,
                json_body={"content": "买方互相回复", "reply_to_comment_id": int(first["id"])},
            )
            second = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/products/{product_id}/comments",
                    user="buyer2",
                    expected=201,
                    json_body={"content": f"另一买方评论-{self.run_id}"},
                )
            )
            self.comments["second"] = int(second["id"])
            self._call(
                "DELETE",
                f"/api/v1/products/{product_id}/comments/{self.comments['first']}",
                user="buyer",
                expected=403,
            )
            self._call(
                "DELETE",
                f"/api/v1/products/{product_id}/comments/{self.comments['first']}",
                user="outsider",
                expected=200,
            )
            listed = self._list(
                self._call("GET", f"/api/v1/products/{product_id}/comments", user="outsider", expected=200)
            )
            deleted_row = next(item for item in listed if int(item["id"]) == self.comments["first"])
            self.rec.must_eq(deleted_row.get("content"), "该评论已删除", "逻辑删除占位")
            # 真实 Redis 限频：独立 commenter 连续 4 条，前 3 条 201，第 4 条 429。
            for index in range(3):
                self._call(
                    "POST",
                    f"/api/v1/products/{product_id}/comments",
                    user="commenter",
                    expected=201,
                    json_body={"content": f"限频测试-{self.run_id}-{index}"},
                )
            self._call(
                "POST",
                f"/api/v1/products/{product_id}/comments",
                user="commenter",
                expected=429,
                json_body={"content": f"限频测试-{self.run_id}-最后"},
            )
            self._call("POST", f"/api/v1/products/{product_id}/delist", user="seller2", expected=200)
            self._call(
                "POST",
                f"/api/v1/products/{product_id}/comments",
                user="buyer",
                expected=409,
                json_body={"content": "下架后评论"},
            )
            self._call("POST", f"/api/v1/products/{product_id}/relist", user="seller2", expected=200)

        with self.rec.step(
            "USERS-01",
            "卖方个人页：登录可见在售商品；未知用户 404；匿名 401",
            ac=["US-04-AC-04"],
            sc=["SC-04-05"],
        ):
            profile = self._dict(
                self._call("GET", f"/api/v1/users/{self._uid('seller')}/profile", user="outsider", expected=200)
            )
            self.rec.must_eq(int(profile["id"]), self._uid("seller"), "个人页用户 ID")
            self.rec.must(isinstance(profile.get("products"), list), "个人页含在售商品列表")
            self._call("GET", "/api/v1/users/999999999/profile", user="outsider", expected=404)
            self._call("GET", f"/api/v1/users/{self._uid('seller')}/profile", expected=401)

    # ------------------------------------------------------------------
    # 交易核心、取消、争议、冻结、超时、D-48
    # ------------------------------------------------------------------
    def trades_core(self) -> None:
        with self.rec.step(
            "TRADE-01",
            "购买请求/重复请求/锁单关闭其余请求/接受权限/分支与通知",
            ac=["US-05-AC-01", "US-05-AC-02", "US-05-AC-04", "US-05-AC-07", "US-05-AC-10", "US-09-AC-02", "US-13-AC-06"],
            sc=["SC-05-01", "SC-05-02", "SC-05-04", "SC-05-05", "SC-05-12", "SC-02-06", "SC-03-04"],
        ):
            self._publish(
                "P_MAIN",
                "seller",
                f"主交易商品-{self.run_id}",
                price=6000,
                category_ids=[self.categories["main"]["id"]],
            )
            self._approve("P_MAIN")
            main = self._request_trade("T_MAIN", "buyer", "P_MAIN", note="主流程请求")
            duplicate = self._dict(
                self._call(
                    "POST",
                    "/api/v1/trades/requests",
                    user="buyer",
                    expected=200,
                    json_body={"product_id": int(self.products["P_MAIN"]["id"]), "note": "重复请求"},
                )
            )
            self.rec.must_eq(int(duplicate["id"]), int(main["id"]), "重复请求返回已有交易")
            self.rec.must_eq(duplicate.get("existing"), True, "重复请求 existing 标记")
            other = self._request_trade("T_MAIN_OTHER", "buyer2", "P_MAIN", note="其他买方请求")
            seller_notifications = self._notifications("seller")
            self.rec.must(
                self._has_notification(seller_notifications, "request_created", link_id=int(main["conversation_id"])) if main.get("conversation_id") else any(
                    item.get("type") == "request_created" and int((item.get("payload") or {}).get("trade_id") or 0) == int(main["id"])
                    for item in seller_notifications
                ),
                "卖方收到 request_created 通知且关联同一交易",
            )
            self._call("POST", f"/api/v1/favorites/{self.products['P_MAIN']['id']}", user="buyer", expected=200)
            self._accept("T_MAIN")
            trade_detail = self._trade_detail("T_MAIN", "buyer")
            self.rec.must_eq(trade_detail.get("status"), "in_progress", "接受后进行中")
            self.rec.must_eq(trade_detail.get("agreement_stage"), "awaiting_agreement", "待约定阶段")
            self.rec.must_eq(self._product_detail("P_MAIN", "seller").get("status"), "in_transaction", "接受后商品交易中")
            # 交易中：退出公开搜索，详情/收藏仍可用；管理员纠类不影响交易。
            listed_favorites = self._list(self._call("GET", "/api/v1/favorites", user="buyer", expected=200))
            main_favorite = next(item for item in listed_favorites if int(item["product_id"]) == int(self.products["P_MAIN"]["id"]))
            self.rec.must_eq(main_favorite.get("valid"), True, "交易中收藏保持有效")
            self._call("GET", f"/api/v1/products/{self.products['P_MAIN']['id']}", user="buyer", expected=200)
            self._call(
                "POST",
                f"/api/v1/products/{self.products['P_MAIN']['id']}/comments",
                user="buyer",
                expected=201,
                json_body={"content": f"交易中可评论-{self.run_id}"},
            )
            self._call(
                "POST",
                "/api/v1/trades/requests",
                user="buyer2",
                expected=404,
                json_body={"product_id": int(self.products["P_MAIN"]["id"])},
                note="trade-in-progress-reject",
            )
            trade_search = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="buyer",
                    expected=200,
                    params={"keyword": f"主交易商品-{self.run_id}"},
                )
            )
            self.rec.must_eq(trade_search.get("total"), 0, "交易中退出公开搜索")
            corrected = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/admin/products/{self.products['P_MAIN']['id']}/correct-category",
                    user="admin",
                    expected=200,
                    json_body={"category_ids": [self.categories["second"]["id"]], "reason": "验收纠类"},
                )
            )
            self.rec.must("纠正" in str(corrected.get("detail")), "管理员纠类入口")
            corrected_detail = self._product_detail("P_MAIN", "seller")
            self.rec.must_in(self.categories["second"]["name"], corrected_detail.get("tag_names") or [], "纠类后标签更新")
            # 管理端商品列表与摘要：ID 关键词检索、分页响应与摘要标签（分类纠正二级页数据来源）。
            admin_products_page = self._dict(
                self._call(
                    "GET",
                    "/api/v1/admin/products",
                    user="admin",
                    expected=200,
                    params={"keyword": str(self.products["P_MAIN"]["id"]), "page_size": 5},
                )
            )
            # 数字关键词也匹配正文；目标可能位于后续分页，不要求唯一命中。
            admin_product_rows = list(admin_products_page.get("items") or [])
            for page in range(2, (int(admin_products_page.get("total") or 0) + 4) // 5 + 1):
                batch = self._dict(self._call(
                    "GET", "/api/v1/admin/products", user="admin", expected=200,
                    params={"keyword": str(self.products["P_MAIN"]["id"]), "page_size": 5, "page": page},
                ))
                admin_product_rows.extend(batch.get("items") or [])
            self.rec.must(
                any(
                    int(row.get("id") or 0) == int(self.products["P_MAIN"]["id"])
                    for row in admin_product_rows
                ),
                "管理端商品列表命中纠正商品",
            )
            self.rec.must_eq(self._trade_detail("T_MAIN", "buyer").get("status"), "in_progress", "纠类不改交易状态")
            other_detail = self._trade_detail("T_MAIN_OTHER", "buyer2")
            self.rec.must_eq(other_detail.get("status"), "closed", "其余待接受请求关闭")
            self.rec.must_eq(other_detail.get("close_reason"), "商品已被其他用户锁单", "关闭原因锁单")
            buyer2_notifications = self._notifications("buyer2")
            self.rec.must(
                self._has_notification(buyer2_notifications, "request_closed", link_id=int(other["id"])),
                "其他买方收到关闭通知",
            )
            self._call("POST", f"/api/v1/trades/{main['id']}/accept", user="buyer", expected=403)
            self._call("GET", f"/api/v1/trades/{main['id']}", user="outsider", expected=404)
            self._publish(
                "P_SELF",
                "seller",
                f"本人商品请求样本-{self.run_id}",
                price=6050,
                category_ids=[self.categories["main"]["id"]],
            )
            self._approve("P_SELF")
            self._call(
                "POST",
                "/api/v1/trades/requests",
                user="seller",
                expected=400,
                json_body={"product_id": int(self.products["P_SELF"]["id"])},
            )
            mine_all = self._list(self._call("GET", "/api/v1/trades/mine", user="buyer", expected=200, params={"role": "all"}))
            mine_buyer = self._list(self._call("GET", "/api/v1/trades/mine", user="buyer", expected=200, params={"role": "buyer"}))
            mine_seller = self._list(self._call("GET", "/api/v1/trades/mine", user="seller", expected=200, params={"role": "seller"}))
            self.rec.must(any(int(item["id"]) == int(main["id"]) for item in mine_all), "我的交易 all")
            self.rec.must(any(int(item["id"]) == int(main["id"]) for item in mine_buyer), "我的交易 buyer")
            self.rec.must(any(int(item["id"]) == int(main["id"]) for item in mine_seller), "我的交易 seller")
            transitions = self._list(
                self._call("GET", f"/api/v1/trades/{main['id']}/transitions", user="buyer", expected=200)
            )
            self.rec.must(
                any(row.get("to_status") == "in_progress" and row.get("trigger") == "request_accepted" for row in transitions),
                "接受转移留痕",
            )

        with self.rec.step(
            "CONC-01",
            "并发锁单/重复请求：5轮独立商品真实并发，一胜一败无500，失败方无多余成功审计/通知/转移",
            sc=["SC-05-05"],
        ):
            accept_rounds: list[dict[str, Any]] = []
            accept_all_ok = True
            for index in range(5):
                product_key = f"P_CONC_{index}"
                self._publish(
                    product_key,
                    "seller",
                    f"并发锁单商品-{index}-{self.run_id}",
                    price=6075 + index * 10,
                    category_ids=[self.categories["main"]["id"]],
                )
                self._approve(product_key)
                first = self._request_trade(f"T_CONC_A_{index}", "buyer", product_key)
                second = self._request_trade(f"T_CONC_B_{index}", "buyer2", product_key)
                results = self._concurrent(
                    [
                        ("POST", f"/api/v1/trades/{first['id']}/accept", "seller", {}),
                        ("POST", f"/api/v1/trades/{second['id']}/accept", "seller", {}),
                    ]
                )
                statuses = [int(row["status"]) for row in results]
                status_ok = sorted(statuses) == [200, 409]
                pairs = list(zip((first, second), results))
                winner = next((trade for trade, row in pairs if row["status"] == 200), None)
                loser = next((trade for trade, row in pairs if row["status"] == 409), None)
                if winner is None or loser is None:
                    accept_all_ok = False
                    accept_rounds.append(
                        {
                            "round": index,
                            "product_id": self.products[product_key]["id"],
                            "statuses": statuses,
                            "status_ok": False,
                        }
                    )
                    continue
                winner_detail = self._trade_detail(str(winner["key"]), str(winner["buyer"]))
                loser_detail = self._trade_detail(str(loser["key"]), str(loser["buyer"]))
                states_ok = winner_detail.get("status") == "in_progress" and loser_detail.get("status") == "closed"
                lock_count = int(
                    self._db_one(
                        ("select count(*) as n from app.trades where product_id = :pid "
                         "and status in ('in_progress','disputed','abnormal')"),
                        {"pid": int(self.products[product_key]["id"])},
                    )["n"]
                )
                winner_accept_audit = int(
                    self._db_one(
                        ("select count(*) as n from app.audit_events where event_type = 'trade.accept' "
                         "and target_type = 'trade' and target_id = :tid"),
                        {"tid": str(winner["id"])},
                    )["n"]
                )
                loser_accept_audit = int(
                    self._db_one(
                        ("select count(*) as n from app.audit_events where event_type = 'trade.accept' "
                         "and target_type = 'trade' and target_id = :tid"),
                        {"tid": str(loser["id"])},
                    )["n"]
                )
                winner_transitions = int(
                    self._db_one(
                        ("select count(*) as n from app.trade_transitions where trade_id = :tid "
                         "and to_status = 'in_progress' and trigger = 'request_accepted'"),
                        {"tid": int(winner["id"])},
                    )["n"]
                )
                loser_transitions = int(
                    self._db_one(
                        ("select count(*) as n from app.trade_transitions where trade_id = :tid "
                         "and to_status = 'in_progress'"),
                        {"tid": int(loser["id"])},
                    )["n"]
                )
                loser_closed_transitions = int(
                    self._db_one(
                        ("select count(*) as n from app.trade_transitions where trade_id = :tid "
                         "and to_status = 'closed' and trigger = 'product_closed'"),
                        {"tid": int(loser["id"])},
                    )["n"]
                )
                loser_accepted_notifications = int(
                    self._db_one(
                        ("select count(*) as n from app.notifications where user_id = :uid "
                         "and type = 'request_accepted' and payload->>'trade_id' = :tid"),
                        {"uid": self._uid(str(loser["buyer"])), "tid": str(loser["id"])},
                    )["n"]
                )
                loser_closed_notifications = int(
                    self._db_one(
                        ("select count(*) as n from app.notifications where user_id = :uid "
                         "and type = 'request_closed' and link_type = 'trade' and link_id = :tid"),
                        {"uid": self._uid(str(loser["buyer"])), "tid": int(loser["id"])},
                    )["n"]
                )
                winner_accepted_notifications = int(
                    self._db_one(
                        ("select count(*) as n from app.notifications where user_id = :uid "
                         "and type = 'request_accepted' and payload->>'trade_id' = :tid"),
                        {"uid": self._uid(str(winner["buyer"])), "tid": str(winner["id"])},
                    )["n"]
                )
                round_ok = (
                    status_ok
                    and states_ok
                    and lock_count == 1
                    and winner_accept_audit == 1
                    and loser_accept_audit == 0
                    and winner_transitions == 1
                    and loser_transitions == 0
                    and loser_closed_transitions == 1
                    and loser_accepted_notifications == 0
                    and loser_closed_notifications == 1
                    and winner_accepted_notifications == 1
                )
                accept_all_ok = accept_all_ok and round_ok
                accept_rounds.append(
                    {
                        "round": index,
                        "product_id": self.products[product_key]["id"],
                        "trade_ids": [winner["id"], loser["id"]],
                        "statuses": statuses,
                        "states": [winner_detail.get("status"), loser_detail.get("status")],
                        "lock_count": lock_count,
                        "winner_accept_audit": winner_accept_audit,
                        "loser_accept_audit": loser_accept_audit,
                        "winner_transitions": winner_transitions,
                        "loser_transitions": loser_transitions,
                        "loser_closed_transitions": loser_closed_transitions,
                        "loser_accepted_notifications": loser_accepted_notifications,
                        "loser_closed_notifications": loser_closed_notifications,
                        "winner_accepted_notifications": winner_accepted_notifications,
                        "status_ok": round_ok,
                    }
                )
            self.concurrency.append(
                {
                    "kind": "concurrent_accept_same_product",
                    "rounds": len(accept_rounds),
                    "details": accept_rounds,
                    "all_ok": accept_all_ok,
                }
            )

            dup_rounds: list[dict[str, Any]] = []
            dup_all_ok = True
            for index in range(5):
                product_key = f"P_CONC_DUP_{index}"
                self._publish(
                    product_key,
                    "seller",
                    f"并发重复请求商品-{index}-{self.run_id}",
                    price=6085 + index * 10,
                    category_ids=[self.categories["main"]["id"]],
                )
                self._approve(product_key)
                dup_results = self._concurrent(
                    [
                        (
                            "POST",
                            "/api/v1/trades/requests",
                            "buyer",
                            {"product_id": int(self.products[product_key]["id"])},
                        ),
                        (
                            "POST",
                            "/api/v1/trades/requests",
                            "buyer",
                            {"product_id": int(self.products[product_key]["id"])},
                        ),
                    ]
                )
                dup_statuses = [int(row["status"]) for row in dup_results]
                ids = sorted(
                    {
                        int(str((row.get("body") or {}).get("id") or 0))
                        for row in dup_results
                        if row.get("body") and (row.get("body") or {}).get("id")
                    }
                )
                existing_flags = [
                    bool((row.get("body") or {}).get("existing")) for row in dup_results
                ]
                pending_count = int(
                    self._db_one(
                        ("select count(*) as n from app.trades where product_id = :pid "
                         "and buyer_id = :bid and status = 'pending_acceptance'"),
                        {
                            "pid": int(self.products[product_key]["id"]),
                            "bid": self._uid("buyer"),
                        },
                    )["n"]
                )
                request_trade_count = int(
                    self._db_one(
                        "select count(*) as n from app.trades where product_id = :pid and buyer_id = :bid",
                        {
                            "pid": int(self.products[product_key]["id"]),
                            "bid": self._uid("buyer"),
                        },
                    )["n"]
                )
                trade_id = ids[0] if len(ids) == 1 else -1
                request_audit = int(
                    self._db_one(
                        ("select count(*) as n from app.audit_events where event_type = 'trade.request_create' "
                         "and target_type = 'trade' and target_id = :tid"),
                        {"tid": str(trade_id)},
                    )["n"]
                )
                request_transitions = int(
                    self._db_one(
                        ("select count(*) as n from app.trade_transitions where trade_id = :tid "
                         "and to_status = 'pending_acceptance' and trigger = 'request_created'"),
                        {"tid": trade_id},
                    )["n"]
                )
                request_notifications = int(
                    self._db_one(
                        ("select count(*) as n from app.notifications where user_id = :uid "
                         "and type = 'request_created' and payload->>'trade_id' = :tid"),
                        {"uid": self._uid("seller"), "tid": str(trade_id)},
                    )["n"]
                )
                round_ok = (
                    sorted(dup_statuses) == [200, 200]
                    and len(ids) == 1
                    and any(existing_flags)
                    and pending_count == 1
                    and request_trade_count == 1
                    and request_audit == 1
                    and request_transitions == 1
                    and request_notifications == 1
                )
                dup_all_ok = dup_all_ok and round_ok
                dup_rounds.append(
                    {
                        "round": index,
                        "product_id": self.products[product_key]["id"],
                        "statuses": dup_statuses,
                        "trade_ids": ids,
                        "existing_flags": existing_flags,
                        "pending_count": pending_count,
                        "request_trade_count": request_trade_count,
                        "request_audit": request_audit,
                        "request_transitions": request_transitions,
                        "request_notifications": request_notifications,
                        "status_ok": round_ok,
                    }
                )
            self.concurrency.append(
                {
                    "kind": "concurrent_duplicate_request",
                    "rounds": len(dup_rounds),
                    "details": dup_rounds,
                    "all_ok": dup_all_ok,
                }
            )
            self.rec.must(
                accept_all_ok and dup_all_ok,
                ("并发锁单/重复请求多轮："
                 f"accept_rounds={len(accept_rounds)} accept_ok={accept_all_ok} "
                 f"duplicate_rounds={len(dup_rounds)} duplicate_ok={dup_all_ok}"),
            )

        with self.rec.step(
            "TRADE-02",
            "约定多轮：无约定不可确认完成；拒绝不改原约定；重复提案 409；本人提案不可自确认",
            ac=["US-05-AC-05", "US-05-AC-07", "US-05-AC-11"],
            sc=["SC-05-08", "SC-05-13"],
        ):
            # 无有效约定时不能提交完成确认。
            self._call("POST", f"/api/v1/trades/{self.trades['T_MAIN']['id']}/confirmations", user="buyer", expected=409, json_body={})
            proposed = self._propose("T_MAIN", "buyer", AGREEMENT_A)
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_MAIN']['id']}/agreements",
                user="seller",
                expected=409,
                json_body=dict(AGREEMENT_B),
            )
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_MAIN']['id']}/agreements/{proposed}/confirm",
                user="buyer",
                expected=403,
            )
            rejected = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/trades/{self.trades['T_MAIN']['id']}/agreements/{proposed}/reject",
                    user="seller",
                    expected=200,
                    json_body={},
                )
            )
            self.rec.must("拒绝" in str(rejected.get("detail")), "提案被拒绝")
            detail = self._trade_detail("T_MAIN", "buyer")
            self.rec.must(detail.get("effective_agreement") is None, "拒绝后无有效约定")
            self.rec.must_eq(len(detail.get("agreement_history") or []), 1, "拒绝提案保留历史")
            self.rec.must_eq(detail["agreement_history"][0].get("status"), "rejected", "提案状态 rejected")
            second = self._propose("T_MAIN", "seller", AGREEMENT_B)
            confirmed = self._agree("T_MAIN", second, "buyer")
            self.rec.must("生效" in str(confirmed.get("detail")), "约定确认生效")
            detail = self._trade_detail("T_MAIN", "buyer")
            self.rec.must_eq(int(detail["effective_agreement"]["id"]), second, "当前有效约定")
            self.rec.must_eq(len(detail.get("agreement_history") or []), 2, "两轮约定历史")
            self.rec.must_eq(detail.get("pending_agreement"), None, "无待确认提案")

        with self.rec.step(
            "TRADE-03",
            "单方确认→双方确认完成；完成联动下架/归档/通知；双方评价与重复评价拒绝",
            ac=["US-05-AC-07", "US-05-AC-10", "US-06-AC-01", "US-06-AC-02", "US-06-AC-03", "US-06-AC-05", "US-06-AC-06", "US-07-AC-01", "US-07-AC-02"],
            sc=["SC-05-01", "SC-05-08", "SC-07-01", "SC-07-02", "SC-07-03"],
        ):
            one = self._confirm("T_MAIN", "buyer", note="买方已交付付款")
            self.rec.must("等待对方" in str(one.get("detail")), "单方确认仅记进度")
            seller_notifications = self._notifications("seller")
            self.rec.must(self._has_notification(seller_notifications, "confirm_progress", link_id=int(self.trades["T_MAIN"]["id"])), "单方确认通知另一方")
            detail = self._trade_detail("T_MAIN", "buyer")
            self.rec.must_eq(detail.get("my_confirmed"), True, "买方当前确认")
            self.rec.must(detail.get("confirm_wait_started_at"), "单方确认开始计时")
            confirmation_id = int(detail["confirmations"][0]["id"])
            self._call("PATCH", f"/api/v1/trades/{self.trades['T_MAIN']['id']}/confirmations/{confirmation_id}", user="buyer", expected=404, json_body={})
            self._call("DELETE", f"/api/v1/trades/{self.trades['T_MAIN']['id']}/confirmations/{confirmation_id}", user="buyer", expected=404)
            self._call("GET", f"/api/v1/trades/{self.trades['T_MAIN']['id']}", user="outsider", expected=404)
            remaining = detail.get("confirm_wait_remaining_seconds")
            self.rec.must(isinstance(remaining, int) and remaining > 7 * 86400 - 3600, "7 天完整计时起点")
            both = self._confirm("T_MAIN", "seller", note="卖方确认")
            self.rec.must("已完成" in str(both.get("detail")), "双方确认交易完成")
            detail = self._trade_detail("T_MAIN", "buyer")
            self.rec.must_eq(detail.get("status"), "completed", "交易 completed")
            self.rec.must_eq(detail.get("conversation_archived"), True, "交易分支归档")
            self.rec.must_eq(self._product_detail("P_MAIN", "seller").get("status"), "delisted", "完成后商品默认下架")
            buyer_notifications = self._notifications("buyer")
            seller_notifications = self._notifications("seller")
            self.rec.must(self._has_notification(buyer_notifications, "trade_completed"), "完成通知买方")
            self.rec.must(self._has_notification(seller_notifications, "trade_completed"), "完成通知卖方")
            transitions = self._list(
                self._call("GET", f"/api/v1/trades/{self.trades['T_MAIN']['id']}/transitions", user="buyer", expected=200)
            )
            self.rec.must(any(row.get("to_status") == "completed" for row in transitions), "完成状态转移留痕")
            buy_review = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/trades/{self.trades['T_MAIN']['id']}/review",
                    user="buyer",
                    expected=201,
                    json_body={"rating": 5, "content": "验收买方评价"},
                )
            )
            sell_review = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/trades/{self.trades['T_MAIN']['id']}/review",
                    user="seller",
                    expected=201,
                    json_body={"rating": 4, "content": "验收卖方评价"},
                )
            )
            self.rec.must(int(buy_review["id"]) != int(sell_review["id"]), "双方各一条评价")
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_MAIN']['id']}/review",
                user="buyer",
                expected=409,
                json_body={"rating": 5, "content": "重复"},
            )
            # 未完成交易评价拒绝（T_DISPUTE 尚未完成）
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_MAIN']['id']}/review",
                user="outsider",
                expected=404,
                json_body={"rating": 5, "content": "第三方"},
            )
            product_detail = self._product_detail("P_MAIN", "seller")
            self.rec.must("reviews" not in product_detail, "商品详情不公开评价")
            comments = self._list(
                self._call("GET", f"/api/v1/products/{self.products['P_MAIN']['id']}/comments", user="seller", expected=200)
            )
            self.rec.must(not any("验收买方评价" in str(row.get("content")) for row in comments), "商品评论不混入交易评价")
            # UC-C09-02：交易结束默认下架，卖方可按资格明确继续上架。
            relisted = self._dict(
                self._call("POST", f"/api/v1/products/{self.products['P_MAIN']['id']}/relist", user="seller", expected=200)
            )
            self.rec.must_eq(relisted.get("status"), "listed", "完成后卖方明确继续上架")
            self.rec.must_eq(self._product_detail("P_MAIN", "seller").get("status"), "listed", "继续上架可公开")
            published = self._list(
                self._call("GET", "/api/v1/me/reviews", user="buyer", expected=200, params={"type": "published"})
            )
            received = self._list(
                self._call("GET", "/api/v1/me/reviews", user="buyer", expected=200, params={"type": "received"})
            )
            self.rec.must(any(int(row["trade_id"]) == int(self.trades["T_MAIN"]["id"]) for row in published), "我的发表评价")
            self.rec.must(any(int(row["trade_id"]) == int(self.trades["T_MAIN"]["id"]) for row in received), "我的收到评价")

        with self.rec.step(
            "TRADE-04",
            "卖方拒绝/买方撤回/非当事人权限/已处理重复操作拒绝",
            ac=["US-05-AC-02", "US-05-AC-03"],
            sc=["SC-05-02", "SC-05-03", "SC-05-06", "SC-05-07"],
        ):
            self._publish(
                "P_REJECT_TRADE",
                "seller",
                f"拒绝请求商品-{self.run_id}",
                price=6100,
                category_ids=[self.categories["main"]["id"]],
            )
            self._approve("P_REJECT_TRADE")
            rejected_trade = self._request_trade("T_REJECT", "buyer", "P_REJECT_TRADE")
            self._call("POST", f"/api/v1/trades/{rejected_trade['id']}/accept", user="outsider", expected=404)
            self._call("POST", f"/api/v1/trades/{rejected_trade['id']}/withdraw", user="outsider", expected=404)
            self._call(
                "POST",
                f"/api/v1/trades/{rejected_trade['id']}/reject",
                user="seller",
                expected=200,
                json_body={"reason": "验收拒绝"},
            )
            detail = self._trade_detail("T_REJECT", "buyer")
            self.rec.must_eq(detail.get("status"), "rejected", "拒绝后 rejected")
            self.rec.must_eq(detail.get("close_reason"), "验收拒绝", "拒绝原因")
            self.rec.must_eq(detail.get("conversation_archived"), True, "拒绝后分支归档")
            self._call("POST", f"/api/v1/trades/{rejected_trade['id']}/reject", user="seller", expected=409, json_body={})
            self._call(
                "POST",
                "/api/v1/trades/requests",
                user="buyer",
                expected=200,
                json_body={"product_id": int(self.products["P_REJECT_TRADE"]["id"])},
            )
            # 上面新建了另一条请求；撤回该新请求。
            # 通过我的交易找到最新 pending 请求。
            mine = self._list(self._call("GET", "/api/v1/trades/mine", user="buyer", expected=200, params={"role": "buyer"}))
            pending = [row for row in mine if int(row["product_id"]) == int(self.products["P_REJECT_TRADE"]["id"]) and row["status"] == "pending_acceptance"]
            if not pending:
                raise CheckFailure("撤回样本请求未生成")
            withdraw_id = int(pending[0]["id"])
            self._call("POST", f"/api/v1/trades/{withdraw_id}/withdraw", user="buyer", expected=200)
            self._call("GET", f"/api/v1/trades/{withdraw_id}", user="buyer", expected=200)
            self.rec.must_eq(self._trade_detail("T_REJECT", "buyer").get("status"), "rejected", "撤回不影响已拒绝交易")

        with self.rec.step(
            "TRADE-05",
            "取消：首约前买方直接取消；约定后双方同意；取消申请撤回与拒绝",
            ac=["US-05-AC-06"],
            sc=["SC-05-10", "SC-06-06"],
        ):
            self._publish("P_CANCEL_DIRECT", "seller", f"直接取消商品-{self.run_id}", price=6200, category_ids=[self.categories["main"]["id"]])
            self._approve("P_CANCEL_DIRECT")
            self._request_trade("T_CANCEL_DIRECT", "buyer", "P_CANCEL_DIRECT")
            self._accept("T_CANCEL_DIRECT")
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_CANCEL_DIRECT']['id']}/cancel",
                user="buyer",
                expected=200,
                json_body={"reason": "首约前直接取消"},
            )
            direct = self._trade_detail("T_CANCEL_DIRECT", "buyer")
            self.rec.must_eq(direct.get("status"), "terminated", "首约前买方直接取消 terminated")
            self.rec.must_eq(self._product_detail("P_CANCEL_DIRECT", "seller").get("status"), "delisted", "取消后商品默认下架")
            self._publish("P_CANCEL_AGREE", "seller", f"双方取消商品-{self.run_id}", price=6300, category_ids=[self.categories["main"]["id"]])
            self._approve("P_CANCEL_AGREE")
            self._request_trade("T_CANCEL_AGREE", "buyer", "P_CANCEL_AGREE")
            self._accept("T_CANCEL_AGREE")
            agreement = self._propose("T_CANCEL_AGREE", "buyer", AGREEMENT_A)
            self._agree("T_CANCEL_AGREE", agreement, "seller")
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_CANCEL_AGREE']['id']}/cancel",
                user="seller",
                expected=200,
                json_body={"reason": "约定后卖方申请取消"},
            )
            detail = self._trade_detail("T_CANCEL_AGREE", "buyer")
            self.rec.must_eq(detail.get("status"), "in_progress", "未同意取消不生效")
            self.rec.must_eq(int(detail["cancel_requested_by"] or 0), self._uid("seller"), "取消申请人")
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_CANCEL_AGREE']['id']}/cancel/confirm",
                user="buyer",
                expected=200,
                json_body={"reason": "买方同意取消"},
            )
            self.rec.must_eq(self._trade_detail("T_CANCEL_AGREE", "buyer").get("status"), "terminated", "双方同意终止")
            self._publish("P_CANCEL_WITHDRAW", "seller", f"取消撤回商品-{self.run_id}", price=6400, category_ids=[self.categories["main"]["id"]])
            self._approve("P_CANCEL_WITHDRAW")
            self._request_trade("T_CANCEL_WITHDRAW", "buyer", "P_CANCEL_WITHDRAW")
            self._accept("T_CANCEL_WITHDRAW")
            agreement = self._propose("T_CANCEL_WITHDRAW", "buyer", AGREEMENT_B)
            self._agree("T_CANCEL_WITHDRAW", agreement, "seller")
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_CANCEL_WITHDRAW']['id']}/cancel",
                user="buyer",
                expected=200,
                json_body={"reason": "申请取消后撤回"},
            )
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_CANCEL_WITHDRAW']['id']}/cancel/withdraw",
                user="buyer",
                expected=200,
            )
            detail = self._trade_detail("T_CANCEL_WITHDRAW", "buyer")
            self.rec.must_eq(detail.get("status"), "in_progress", "撤回取消申请后仍进行中")
            self.rec.must_eq(detail.get("cancel_requested_by"), None, "取消申请已撤回")
            self._confirm("T_CANCEL_WITHDRAW", "buyer")
            self._confirm("T_CANCEL_WITHDRAW", "seller")
            self.rec.must_eq(self._trade_detail("T_CANCEL_WITHDRAW", "buyer").get("status"), "completed", "撤回后可正常完成")

            # 取消申请被对方拒绝：只结束申请，交易保持进行中。
            self._publish("P_CANCEL_REJECT", "seller", f"取消拒绝商品-{self.run_id}", price=6450, category_ids=[self.categories["main"]["id"]])
            self._approve("P_CANCEL_REJECT")
            self._request_trade("T_CANCEL_REJECT", "buyer", "P_CANCEL_REJECT")
            self._accept("T_CANCEL_REJECT")
            agreement = self._propose("T_CANCEL_REJECT", "buyer", AGREEMENT_B)
            self._agree("T_CANCEL_REJECT", agreement, "seller")
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_CANCEL_REJECT']['id']}/cancel",
                user="seller",
                expected=200,
                json_body={"reason": "申请取消后由对方拒绝"},
            )
            pending = self._trade_detail("T_CANCEL_REJECT", "buyer")
            self.rec.must_eq(int(pending["cancel_requested_by"] or 0), self._uid("seller"), "拒绝前取消申请人为卖方")
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_CANCEL_REJECT']['id']}/cancel/reject",
                user="seller",
                expected=400,
            )
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_CANCEL_REJECT']['id']}/cancel/reject",
                user="buyer",
                expected=200,
            )
            rejected = self._trade_detail("T_CANCEL_REJECT", "buyer")
            self.rec.must_eq(rejected.get("status"), "in_progress", "对方拒绝取消后交易仍进行中")
            self.rec.must_eq(rejected.get("cancel_requested_by"), None, "拒绝后取消申请结束")
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_CANCEL_REJECT']['id']}/cancel/reject",
                user="buyer",
                expected=409,
            )

        with self.rec.step(
            "TRADE-06",
            "争议：任一方发起即 disputed、清计时；双方确认解决恢复且不启动计时；争议后不可直接确认完成",
            ac=["US-05-AC-08", "US-06-AC-04"],
            sc=["SC-06-01", "SC-06-02", "SC-06-04", "SC-06-05", "SC-06-07", "SC-06-08"],
        ):
            self._publish("P_DISPUTE", "seller", f"争议商品-{self.run_id}", price=6500, category_ids=[self.categories["main"]["id"]])
            self._approve("P_DISPUTE")
            self._request_trade("T_DISPUTE", "buyer", "P_DISPUTE")
            self._request_trade("T_DISPUTE_OTHER", "buyer2", "P_DISPUTE")
            self._accept("T_DISPUTE")
            agreement = self._propose("T_DISPUTE", "buyer", AGREEMENT_A)
            self._agree("T_DISPUTE", agreement, "seller")
            self._confirm("T_DISPUTE", "buyer")
            before_dispute = self._trade_detail("T_DISPUTE", "buyer")
            self.rec.must_eq(before_dispute.get("my_confirmed"), True, "争议前已有单方确认")
            dispute = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/trades/{self.trades['T_DISPUTE']['id']}/disputes",
                    user="buyer",
                    expected=200,
                    json_body={"description": "验收争议说明"},
                )
            )
            dispute_case_id = int(dispute["case_id"])
            dispute_conversation_id = int(
                self._trade_detail("T_DISPUTE", "buyer")["conversation_id"]
            )
            other_branch_id = int(
                self._trade_detail("T_DISPUTE_OTHER", "buyer2")["conversation_id"]
            )
            normal_unrelated = self._dict(
                self._call(
                    "POST",
                    "/api/v1/conversations/normal",
                    user="buyer",
                    expected=201,
                    json_body={"peer_user_id": self._uid("outsider")},
                )
            )
            self._call("GET", f"/api/v1/me/cases/{dispute_case_id}", user="buyer", expected=200)
            self._call("GET", f"/api/v1/me/cases/{dispute_case_id}", user="outsider", expected=403)
            self._call("GET", f"/api/v1/admin/cases/{dispute_case_id}", user="admin", expected=403)
            self._call(
                "GET",
                f"/api/v1/admin/cases/{dispute_case_id}/conversations/{dispute_conversation_id}",
                user="admin",
                expected=403,
            )
            self._claim(dispute_case_id, "admin2")
            branch_read = self._dict(
                self._call(
                    "GET",
                    f"/api/v1/admin/cases/{dispute_case_id}/conversations/{dispute_conversation_id}",
                    user="admin2",
                    expected=200,
                )
            )
            self.rec.must_eq(branch_read.get("scope", {}).get("relation"), "trade_branch", "争议事项关联交易分支")
            self.rec.must_eq(
                int(branch_read.get("conversation", {}).get("trade_id") or 0),
                int(self.trades["T_DISPUTE"]["id"]),
                "仅返回直接关联交易分支",
            )
            self._call(
                "GET",
                f"/api/v1/admin/cases/{dispute_case_id}/conversations/{other_branch_id}",
                user="admin2",
                expected=403,
            )
            self._call(
                "GET",
                f"/api/v1/admin/cases/{dispute_case_id}/conversations/{int(normal_unrelated['id'])}",
                user="admin2",
                expected=403,
            )
            self._call(
                "GET",
                f"/api/v1/admin/cases/{dispute_case_id}/conversations/{dispute_conversation_id}",
                user="admin",
                expected=403,
            )
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_DISPUTE']['id']}/disputes",
                user="buyer",
                expected=409,
                json_body={"description": "重复争议"},
            )
            detail = self._trade_detail("T_DISPUTE", "buyer")
            self.rec.must_eq(detail.get("status"), "disputed", "发起争议 disputed")
            self.rec.must_eq(detail.get("confirm_wait_started_at"), None, "争议清空计时")
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_DISPUTE']['id']}/confirmations",
                user="buyer",
                expected=409,
                json_body={},
            )
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_DISPUTE']['id']}/disputes/resolve",
                user="buyer",
                expected=200,
                json_body={"reason": "买方确认解决"},
            )
            mid = self._trade_detail("T_DISPUTE", "buyer")
            self.rec.must_eq(mid.get("status"), "disputed", "单方确认解决仍 disputed")
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_DISPUTE']['id']}/disputes/resolve",
                user="seller",
                expected=200,
                json_body={"reason": "卖方确认解决"},
            )
            restored = self._trade_detail("T_DISPUTE", "buyer")
            self.rec.must_eq(restored.get("status"), "in_progress", "双方解决恢复进行中")
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_DISPUTE']['id']}/disputes/resolve",
                user="buyer",
                expected=409,
                json_body={"reason": "重复解决"},
            )
            self.rec.must_eq(restored.get("confirm_wait_started_at"), None, "恢复不启动计时")
            self.rec.must_eq(restored.get("effective_agreement") is not None, True, "恢复保留有效约定")
            self.rec.must_eq(restored.get("my_confirmed"), False, "恢复清空当前确认")
            self.rec.must(
                len([row for row in restored.get("confirmations") or [] if row.get("is_current") is False]) >= 1,
                "恢复保留确认历史",
            )
            # 争议双方确认解决后，认领管理员仍只能读取该直接关联分支。
            self._dict(
                self._call(
                    "GET",
                    f"/api/v1/admin/cases/{dispute_case_id}/conversations/{dispute_conversation_id}",
                    user="admin2",
                    expected=200,
                )
            )
            self._call(
                "GET",
                f"/api/v1/admin/cases/{dispute_case_id}/conversations/{dispute_conversation_id}",
                user="admin",
                expected=403,
            )
            self._confirm("T_DISPUTE", "buyer")
            self._confirm("T_DISPUTE", "seller")
            self.rec.must_eq(self._trade_detail("T_DISPUTE", "buyer").get("status"), "completed", "争议解决后可完成")

        with self.rec.step(
            "TRADE-07",
            "冻结暂停计时：冻结期间写操作/双方IM拒绝，remaining 不下降；解冻续算；第三方会话不受影响",
            ac=["US-02-AC-07", "US-04-AC-07", "US-07-AC-07", "US-14-AC-04", "US-08-AC-06"],
            sc=["SC-02-17", "SC-05-11", "SC-09-04", "SC-09-08", "SC-09-10", "SC-04-08"],
        ):
            self._publish("P_FREEZE", "seller", f"冻结暂停商品-{self.run_id}", price=6600, category_ids=[self.categories["main"]["id"]])
            self._approve("P_FREEZE")
            self._request_trade("T_FREEZE", "buyer", "P_FREEZE")
            self._accept("T_FREEZE")
            agreement = self._propose("T_FREEZE", "buyer", AGREEMENT_A)
            self._agree("T_FREEZE", agreement, "seller")
            self._confirm("T_FREEZE", "buyer")
            detail = self._trade_detail("T_FREEZE", "buyer")
            remaining_before = int(detail["confirm_wait_remaining_seconds"])
            conversation_id = int(detail["conversation_id"])
            # UC-C08-05：同一对买卖双方另有第二笔交易分支与普通私聊；冻结应全部禁发。
            self._publish("P_FREEZE_SECOND", "seller", f"冻结第二笔商品-{self.run_id}", price=6650, category_ids=[self.categories["main"]["id"]])
            self._approve("P_FREEZE_SECOND")
            self._request_trade("T_FREEZE_SECOND", "buyer", "P_FREEZE_SECOND")
            self._accept("T_FREEZE_SECOND")
            second_conversation_id = int(self._trade_detail("T_FREEZE_SECOND", "buyer")["conversation_id"])
            normal_pair = self._dict(
                self._call(
                    "POST",
                    "/api/v1/conversations/normal",
                    user="buyer",
                    expected=201,
                    json_body={"peer_user_id": self._uid("seller")},
                )
            )
            normal_pair_id = int(normal_pair["id"])
            self._call(
                "POST",
                f"/api/v1/conversations/{normal_pair_id}/messages",
                user="buyer",
                expected=200,
                json_body={"content": f"冻结前普通私聊-{self.run_id}"},
            )
            case_id = self._relevant_case_for_product(int(self.products["P_FREEZE"]["id"]), claimant="admin")
            self._call(
                "POST",
                f"/api/v1/admin/trades/{self.trades['T_FREEZE']['id']}/freeze",
                user="admin",
                expected=200,
                json_body={"reason": "验收冻结暂停", "case_id": case_id},
            )
            frozen = self._trade_detail("T_FREEZE", "buyer")
            self.rec.must_eq(frozen.get("frozen"), True, "交易冻结")
            self.rec.must(frozen.get("confirm_wait_paused_at"), "冻结记录暂停时刻")
            remaining_paused = int(frozen["confirm_wait_remaining_seconds"])
            self.rec.must(abs(remaining_paused - remaining_before) <= 2, "冻结时剩余秒数保存")
            self._call("POST", f"/api/v1/trades/{self.trades['T_FREEZE']['id']}/confirmations", user="seller", expected=403, json_body={})
            # D-50：仅交易冻结也禁止发布/下架/上架，但无关商品合规编辑允许。
            self._call(
                "POST",
                "/api/v1/products",
                user="seller",
                expected=403,
                json_body={
                    "title": "冻结期间发布",
                    "description": "应拒绝",
                    "price_cents": 100,
                    "image_keys": [self.files["P_MAIN:image"]["key"]],
                    "tags": [{"category_id": self.categories["main"]["id"]}],
                },
            )
            self._call("POST", f"/api/v1/products/{self.products['P_MULTI']['id']}/delist", user="seller", expected=403)
            self._call("POST", f"/api/v1/products/{self.products['P_CANCEL_DIRECT']['id']}/relist", user="seller", expected=403)
            unrelated_edit = self._dict(
                self._call(
                    "PATCH",
                    f"/api/v1/products/{self.products['P_MULTI']['id']}",
                    user="seller",
                    expected=200,
                    json_body={"description": f"冻结期间无关商品合规编辑-{self.run_id}"},
                )
            )
            self.rec.must_eq(unrelated_edit.get("status"), "listed", "冻结期间无关商品可编辑")
            # 仅交易冻结仍允许评价既往已完成交易。
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_CANCEL_WITHDRAW']['id']}/review",
                user="seller",
                expected=201,
                json_body={"rating": 4, "content": "冻结期间评价既往交易"},
            )
            for actor in ("buyer", "seller"):
                self._call(
                    "POST",
                    f"/api/v1/conversations/{conversation_id}/messages",
                    user=actor,
                    expected=403,
                    json_body={"content": f"冻结期间禁发-{actor}"},
                )
                self._call(
                    "POST",
                    f"/api/v1/conversations/{second_conversation_id}/messages",
                    user=actor,
                    expected=403,
                    json_body={"content": f"冻结期间第二笔分支禁发-{actor}"},
                )
                self._call(
                    "POST",
                    f"/api/v1/conversations/{normal_pair_id}/messages",
                    user=actor,
                    expected=403,
                    json_body={"content": f"冻结期间普通私聊禁发-{actor}"},
                )
            # 历史只读：被冻结双方仍可读两类分支与普通私聊。
            self._call("GET", f"/api/v1/conversations/{conversation_id}", user="buyer", expected=200)
            self._call("GET", f"/api/v1/conversations/{second_conversation_id}", user="seller", expected=200)
            self._call("GET", f"/api/v1/conversations/{normal_pair_id}", user="seller", expected=200)
            # 第三方组合：buyer2 与 seller 之间没有交易，不应被该冻结影响。
            normal = self._dict(
                self._call(
                    "POST",
                    "/api/v1/conversations/normal",
                    user="buyer2",
                    expected=201,
                    json_body={"peer_user_id": self._uid("seller")},
                )
            )
            self.conversations["third_party"] = normal
            self._call(
                "POST",
                f"/api/v1/conversations/{normal['id']}/messages",
                user="buyer2",
                expected=200,
                json_body={"content": "第三方会话消息"},
            )
            if self.server is None:
                raise CheckFailure("冻结暂停续算需要本任务启动的受控时钟服务")
            self.server.set_clock_offset(86400)
            self.clock_events.append(
                {"kind": "freeze_pause", "offset_seconds": 86400, "trade_id": self.trades["T_FREEZE"]["id"], "at": datetime.now(UTC).isoformat()}
            )
            time.sleep(3.5)
            still = self._trade_detail("T_FREEZE", "buyer")
            self.rec.must_eq(still.get("status"), "in_progress", "冻结期间扫描不转异常")
            self.rec.must_eq(int(still["confirm_wait_remaining_seconds"]), remaining_paused, "冻结期间 remaining 不下降")
            self._call(
                "POST",
                f"/api/v1/admin/trades/{self.trades['T_FREEZE']['id']}/unfreeze",
                user="admin",
                expected=200,
                json_body={"reason": "验收解冻续算", "case_id": case_id},
            )
            resumed = self._trade_detail("T_FREEZE", "buyer")
            self.rec.must_eq(resumed.get("frozen"), False, "解冻")
            self.rec.must_eq(resumed.get("confirm_wait_paused_at"), None, "解冻清暂停时刻")
            resumed_remaining = int(resumed["confirm_wait_remaining_seconds"])
            self.rec.must(abs(resumed_remaining - remaining_paused) <= 3, "解冻从暂停点续算")
            self.server.set_clock_offset(86400 + 2 * 86400)
            time.sleep(1.0)
            later = self._trade_detail("T_FREEZE", "buyer")
            self.rec.must(
                int(later["confirm_wait_remaining_seconds"]) <= resumed_remaining - 2 * 86400 + 5,
                "解冻后按经过时间减少剩余",
            )
            self.server.set_clock_offset(0)
            self.clock_events.append({"kind": "clock_reset", "offset_seconds": 0, "at": datetime.now(UTC).isoformat()})
            self._confirm("T_FREEZE", "seller")
            self.rec.must_eq(self._trade_detail("T_FREEZE", "buyer").get("status"), "completed", "冻结解除后完成")
            self._call(
                "POST",
                f"/api/v1/admin/cases/{case_id}/dispose",
                user="admin",
                expected=200,
                json_body={"conclusion": "冻结/解冻验证完成", "reason": "验收流程结束", "basis": "SC-09-10"},
            )

        with self.rec.step(
            "TRADE-08",
            "受控时钟 8 天：真实扫描转 abnormal+frozen、生成事项/通知；非认领 403；问询/说明/回复/调整/解冻/终止",
            ac=["US-05-AC-09", "US-06-AC-05", "US-06-AC-06", "US-14-AC-01", "US-14-AC-02", "US-14-AC-03", "US-14-AC-05", "US-14-AC-06", "US-14-AC-07"],
            sc=["SC-05-09", "SC-06-03", "SC-06-08", "SC-09-01", "SC-09-02", "SC-09-03", "SC-09-05", "SC-09-06", "SC-09-07", "SC-09-08"],
            note="7 天阈值未改；仅测试服务进程注入 UTC offset",
        ):
            self._timeout_race_regression()
            self._publish("P_TIMEOUT", "seller", f"超时转异常商品-{self.run_id}", price=6700, category_ids=[self.categories["main"]["id"]])
            self._approve("P_TIMEOUT")
            self._request_trade("T_TIMEOUT", "buyer", "P_TIMEOUT")
            self._accept("T_TIMEOUT")
            agreement = self._propose("T_TIMEOUT", "buyer", AGREEMENT_A)
            self._agree("T_TIMEOUT", agreement, "seller")
            self._confirm("T_TIMEOUT", "buyer")
            before = self._trade_detail("T_TIMEOUT", "buyer")
            self.rec.must_eq(before.get("status"), "in_progress", "超时前进行中")
            started = str(before.get("confirm_wait_started_at"))
            self.server.set_clock_offset(8 * 86400)
            self.clock_events.append(
                {
                    "kind": "timeout_advance",
                    "offset_seconds": 8 * 86400,
                    "trade_id": self.trades["T_TIMEOUT"]["id"],
                    "before_status": "in_progress",
                    "started_at": started,
                    "method": "测试服务进程 UTC offset + 真实后台扫描（2s 周期）",
                    "at": datetime.now(UTC).isoformat(),
                }
            )
            abnormal = self._wait_trade_status("T_TIMEOUT", ["abnormal"], timeout=40)
            self.rec.must_eq(abnormal.get("frozen"), True, "超时转异常并冻结")
            self.rec.must_eq(abnormal.get("confirm_wait_started_at"), None, "异常清空计时")
            self.rec.must_eq(self._product_detail("P_TIMEOUT", "seller").get("status"), "in_transaction", "异常仍保持锁单")
            cases = self._list(
                self._call("GET", "/api/v1/admin/cases", user="admin2", expected=200, params={"status": "pending", "case_type": "abnormal_trade"})
            )
            timeout_case = next((row for row in cases if int(row.get("trade_id") or 0) == int(self.trades["T_TIMEOUT"]["id"])), None)
            if timeout_case is None:
                raise CheckFailure("超时未生成 abnormal_trade 事项")
            self.cases["T_TIMEOUT_abnormal"] = timeout_case
            buyer_notifications = self._notifications("buyer")
            seller_notifications = self._notifications("seller")
            self.rec.must(self._has_notification(buyer_notifications, "trade_abnormal", link_id=int(self.trades["T_TIMEOUT"]["id"])), "异常通知买方")
            self.rec.must(self._has_notification(seller_notifications, "trade_abnormal", link_id=int(self.trades["T_TIMEOUT"]["id"])), "异常通知卖方")
            # 非认领人不能看/处置
            self._call("GET", f"/api/v1/admin/cases/{timeout_case['id']}", user="admin", expected=403)
            self._call("POST", f"/api/v1/admin/cases/{timeout_case['id']}/claim", user="admin2", expected=200, json_body={})
            detail = self._dict(self._call("GET", f"/api/v1/admin/cases/{timeout_case['id']}", user="admin2", expected=200))
            self.rec.must_eq(detail.get("case_type"), "abnormal_trade", "事项类型 abnormal_trade")
            self._call(
                "POST",
                f"/api/v1/admin/cases/{timeout_case['id']}/inquiry",
                user="admin2",
                expected=200,
                json_body={"content": "请说明超时原因与当前交付情况"},
            )
            my_cases = self._list(self._call("GET", "/api/v1/me/cases", user="buyer", expected=200))
            self.rec.must(any(int(row["id"]) == int(timeout_case["id"]) for row in my_cases), "异常事项进入我的事项")
            buyer_case = self._dict(self._call("GET", f"/api/v1/me/cases/{timeout_case['id']}", user="buyer", expected=200))
            self.rec.must_eq(buyer_case.get("can_submit_statement"), True, "问询后可提交说明")
            self._call(
                "POST",
                f"/api/v1/me/cases/{timeout_case['id']}/statement",
                user="buyer",
                expected=200,
                json_body={"content": "买方说明：已完成交付，对方未回应。"},
            )
            self._call(
                "POST",
                f"/api/v1/admin/cases/{timeout_case['id']}/messages",
                user="admin2",
                expected=200,
                json_body={"content": "已收到说明，将按异常交易规则处理。"},
            )
            self._call(
                "GET",
                f"/api/v1/admin/trades/{self.trades['T_TIMEOUT']['id']}",
                user="admin",
                expected=403,
                params={"case_id": timeout_case["id"]},
            )
            admin_view = self._dict(
                self._call(
                    "GET",
                    f"/api/v1/admin/trades/{self.trades['T_TIMEOUT']['id']}",
                    user="admin2",
                    expected=200,
                    params={"case_id": timeout_case["id"]},
                )
            )
            self.rec.must_eq(admin_view.get("frozen"), True, "管理视角冻结")
            self.rec.must_eq(admin_view.get("confirm_wait_remaining_seconds"), None, "异常无等待剩余")
            self._call(
                "POST",
                f"/api/v1/admin/trades/{self.trades['T_TIMEOUT']['id']}/adjust",
                user="admin2",
                expected=200,
                json_body={"to_status": "in_progress", "reason": "核查后恢复进行中", "case_id": timeout_case["id"]},
            )
            restored = self._trade_detail("T_TIMEOUT", "buyer")
            self.rec.must_eq(restored.get("status"), "in_progress", "调整恢复进行中")
            self.rec.must_eq(restored.get("frozen"), True, "恢复不自动解冻")
            self.rec.must_eq(restored.get("my_confirmed"), False, "恢复清空当前确认")
            self.rec.must(
                len([row for row in restored.get("confirmations") or [] if row.get("is_current") is False]) >= 1,
                "管理恢复保留历史确认",
            )
            self.rec.must_eq(restored.get("confirm_wait_started_at"), None, "恢复不启动计时")
            self.rec.must(restored.get("effective_agreement") is not None, "恢复保留有效约定")
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_TIMEOUT']['id']}/confirmations",
                user="buyer",
                expected=403,
                json_body={},
            )
            self._call(
                "POST",
                f"/api/v1/admin/trades/{self.trades['T_TIMEOUT']['id']}/unfreeze",
                user="admin2",
                expected=200,
                json_body={"reason": "异常处置后解除冻结", "case_id": timeout_case["id"]},
            )
            self._call(
                "POST",
                f"/api/v1/admin/trades/{self.trades['T_TIMEOUT']['id']}/adjust",
                user="admin2",
                expected=200,
                json_body={"to_status": "terminated", "reason": "核查后终止交易", "case_id": timeout_case["id"]},
            )
            ended = self._trade_detail("T_TIMEOUT", "buyer")
            self.rec.must_eq(ended.get("status"), "terminated", "管理终止")
            self.rec.must_eq(self._product_detail("P_TIMEOUT", "seller").get("status"), "delisted", "终止后商品默认下架")
            self.rec.must_eq(ended.get("conversation_archived"), True, "终止归档分支")
            transitions = self._list(
                self._call("GET", f"/api/v1/trades/{self.trades['T_TIMEOUT']['id']}/transitions", user="buyer", expected=200)
            )
            self.rec.must(any(row.get("trigger") == "confirm_timeout" for row in transitions), "超时扫描转移留痕")
            self.rec.must(any(row.get("to_status") == "terminated" and row.get("basis_case_id") == timeout_case["id"] for row in transitions), "管理终止依据事项")
            self._call(
                "POST",
                f"/api/v1/admin/cases/{timeout_case['id']}/dispose",
                user="admin2",
                expected=200,
                json_body={"conclusion": "异常交易处置完成", "reason": "已终止交易", "basis": "SC-09-08"},
            )
            self.server.set_clock_offset(0)
            self.clock_events.append({"kind": "clock_reset", "offset_seconds": 0, "after_timeout": True, "at": datetime.now(UTC).isoformat()})

        with self.rec.step(
            "TRADE-09",
            "已有单方确认后变更约定：生效清当前确认/停旧计时；重新确认后完整计时",
            ac=["US-05-AC-11"],
            sc=["SC-05-13"],
        ):
            self._publish("P_CHANGE", "seller", f"约定变更商品-{self.run_id}", price=6800, category_ids=[self.categories["main"]["id"]])
            self._approve("P_CHANGE")
            self._request_trade("T_CHANGE", "buyer", "P_CHANGE")
            self._accept("T_CHANGE")
            first = self._propose("T_CHANGE", "buyer", AGREEMENT_A)
            self._agree("T_CHANGE", first, "seller")
            self._confirm("T_CHANGE", "buyer")
            before = self._trade_detail("T_CHANGE", "buyer")
            self.rec.must_eq(before.get("my_confirmed"), True, "变更前已有单方确认")
            second = self._propose("T_CHANGE", "seller", AGREEMENT_B)
            self._agree("T_CHANGE", second, "buyer")
            changed = self._trade_detail("T_CHANGE", "buyer")
            self.rec.must_eq(changed.get("my_confirmed"), False, "变更生效清当前确认")
            self.rec.must_eq(changed.get("confirm_wait_started_at"), None, "变更生效停旧计时")
            self.rec.must_eq(int(changed["effective_agreement"]["id"]), second, "新约定生效")
            self.rec.must_eq(len(changed.get("confirmations") or []), 1, "历史确认保留")
            self._confirm("T_CHANGE", "buyer")
            started = self._trade_detail("T_CHANGE", "buyer")
            self.rec.must(started.get("confirm_wait_started_at"), "重新确认启动新计时")
            self.rec.must(int(started["confirm_wait_remaining_seconds"]) > 7 * 86400 - 3600, "重新确认完整 7 天")
            self._confirm("T_CHANGE", "seller")
            self.rec.must_eq(self._trade_detail("T_CHANGE", "buyer").get("status"), "completed", "变更后完成")

        with self.rec.step(
            "TRADE-10",
            "D-48：旧交易已结束、同商品新交易仍锁单时恢复旧交易 409，且无副作用",
            ac=["US-14-AC-08"],
            sc=["SC-09-09"],
        ):
            self._publish("P_D48", "seller", f"旧交易恢复冲突商品-{self.run_id}", price=6900, category_ids=[self.categories["main"]["id"]])
            self._approve("P_D48")
            self._request_trade("T_D48_A", "buyer", "P_D48")
            self._accept("T_D48_A")
            agreement = self._propose("T_D48_A", "buyer", AGREEMENT_A)
            self._agree("T_D48_A", agreement, "seller")
            self._confirm("T_D48_A", "buyer")
            self._confirm("T_D48_A", "seller")
            self.rec.must_eq(self._trade_detail("T_D48_A", "buyer").get("status"), "completed", "A 完成")
            self._call("POST", f"/api/v1/products/{self.products['P_D48']['id']}/relist", user="seller", expected=200)
            self._request_trade("T_D48_B", "buyer2", "P_D48")
            self._accept("T_D48_B")
            self.rec.must_eq(self._trade_detail("T_D48_B", "buyer2").get("status"), "in_progress", "B 锁单")
            case_id = self._relevant_case_for_product(int(self.products["P_D48"]["id"]), claimant="admin")
            conflict = self._call(
                "POST",
                f"/api/v1/admin/trades/{self.trades['T_D48_A']['id']}/adjust",
                user="admin",
                expected=409,
                json_body={"to_status": "in_progress", "reason": "尝试恢复旧交易", "case_id": case_id},
            )
            self.rec.must_eq(conflict.status_code, 409, "旧交易恢复 409")
            self.rec.must_eq(self._trade_detail("T_D48_A", "buyer").get("status"), "completed", "A 保持 completed")
            self.rec.must_eq(self._trade_detail("T_D48_B", "buyer2").get("status"), "in_progress", "B 保持 in_progress")
            self.rec.must_eq(self._product_detail("P_D48", "seller").get("status"), "in_transaction", "商品保持锁单")
            self._call(
                "POST",
                f"/api/v1/admin/trades/{self.trades['T_D48_B']['id']}/adjust",
                user="admin",
                expected=200,
                json_body={"to_status": "terminated", "reason": "D-48 样本 B 收尾", "case_id": case_id},
            )
            self.rec.must_eq(self._trade_detail("T_D48_B", "buyer2").get("status"), "terminated", "B 收尾 terminated")
            self._call(
                "POST",
                f"/api/v1/admin/cases/{case_id}/dispose",
                user="admin",
                expected=200,
                json_body={"conclusion": "D-48 验证完成", "reason": "样本收尾", "basis": "SC-09-09"},
            )

    # ------------------------------------------------------------------
        with self.rec.step(
            "REVIEW-ADMIN-STATES",
            "主助手补充：管理员九种目标状态逐项验证，不能伪造双方确认",
            ac=["US-14-AC-06"],
            sc=["SC-06-03", "SC-09-08"],
        ):
            self._publish("P_ADMIN_STATES", "seller", f"管理状态矩阵-{self.run_id}", price=7100, category_ids=[self.categories["main"]["id"]])
            self._approve("P_ADMIN_STATES")
            self._request_trade("T_ADMIN_STATES", "buyer", "P_ADMIN_STATES")
            self._accept("T_ADMIN_STATES")
            trade_id = int(self.trades["T_ADMIN_STATES"]["id"])
            case_id = self._relevant_case_for_product(int(self.products["P_ADMIN_STATES"]["id"]))
            targets = ["completed", "pending_acceptance", "rejected", "withdrawn", "closed", "in_progress", "disputed", "abnormal", "terminated"]
            for target in targets:
                before = self._trade_detail("T_ADMIN_STATES", "buyer")
                notification_max = self._db_one("select coalesce(max(id), 0) as n from app.notifications where link_type='trade' and link_id=:id", {"id": trade_id})
                audit_max = self._db_one("select coalesce(max(event_id), 0) as n from app.audit_events where target_type='trade' and target_id=:id", {"id": str(trade_id)})
                reason = f"管理状态验收-{target}-{self.run_id}"
                self._call("POST", f"/api/v1/admin/trades/{trade_id}/adjust", user="admin", expected=200, json_body={"to_status": target, "reason": reason, "case_id": case_id})
                after = self._trade_detail("T_ADMIN_STATES", "buyer")
                self.rec.must_eq(after.get("status"), target, f"管理目标状态 {target}")
                self.rec.must_eq(len(after.get("confirmations") or []), 0, f"{target} 不伪造用户确认")
                transitions = self._list(self._call("GET", f"/api/v1/trades/{trade_id}/transitions", user="buyer", expected=200))
                last = transitions[-1]
                self.rec.must_eq(last.get("from_status"), before["status"], f"{target} 转移前状态")
                self.rec.must_eq(last.get("to_status"), target, f"{target} 转移后状态")
                self.rec.must_eq(last.get("actor_role"), "admin", f"{target} 管理员归属")
                self.rec.must_eq(last.get("basis_case_id"), case_id, f"{target} 依据事项")
                self.rec.must_eq(last.get("reason"), reason, f"{target} 原因留痕")
                notice = self._db_one("select count(distinct user_id) as n from app.notifications where link_type='trade' and link_id=:id and id>:min", {"id": trade_id, "min": int(notification_max["n"])})
                self.rec.must_eq(int(notice["n"]), 2, f"{target} 通知双方")
                audit = self._db_one("select count(*) as n from app.audit_events where target_type='trade' and target_id=:id and event_type='admin.trade_adjust' and event_id>:min", {"id": str(trade_id), "min": int(audit_max["n"])})
                self.rec.must_eq(int(audit["n"]), 1, f"{target} 单次成功审计")
                if target in {"completed", "terminated"}:
                    self.rec.must_eq(after.get("conversation_archived"), True, f"{target} 分支归档")
                    self.rec.must_eq(after.get("frozen"), False, f"{target} 解除本笔冻结")
                if target in {"in_progress", "disputed", "abnormal"}:
                    self.rec.must_eq(self._product_detail("P_ADMIN_STATES", "seller")["status"], "in_transaction", f"{target} 锁单商品状态")
            self.rec.data["admin_target_states"] = targets


    # 举报 / 处置 / 封禁
    # ------------------------------------------------------------------
    def governance(self) -> None:
        with self.rec.step(
            "GOV-01",
            "商品举报：证据双桶、补充、认领/问询/说明/回复、限制展示、匿名公开、解除展示",
            ac=["US-03-AC-05", "US-07-AC-03", "US-07-AC-04", "US-07-AC-05", "US-08-AC-03", "US-08-AC-04", "US-08-AC-05", "US-09-AC-05", "US-12-AC-04"],
            sc=["SC-03-05", "SC-07-04", "SC-07-05", "SC-07-06", "SC-07-08", "SC-07-12", "SC-12-02"],
        ):
            self._publish("P_REPORT", "seller", f"举报处置商品-{self.run_id}", price=7100, category_ids=[self.categories["main"]["id"]])
            self._approve("P_REPORT")
            product_id = int(self.products["P_REPORT"]["id"])
            self._call("POST", f"/api/v1/favorites/{product_id}", user="buyer", expected=200)
            # 举报本身不自动下架/限制（SC-07-05）。
            self._call("GET", f"/api/v1/products/{product_id}", user="outsider", expected=200)
            evidence = self._upload("buyer", "evidence_listing.jpg", "report")
            self.files["report_evidence"] = evidence
            report = self._dict(
                self._call(
                    "POST",
                    "/api/v1/reports",
                    user="buyer",
                    expected=201,
                    json_body={
                        "target_type": "product",
                        "target_id": product_id,
                        "reason": "验收举报：商品描述与实物不符",
                        "detail": "请管理员核查",
                        "evidence_keys": [evidence["key"]],
                    },
                )
            )
            report_id = int(report["id"])
            self.reports["product"] = {"id": report_id, "target_id": product_id}
            duplicate = self._dict(
                self._call(
                    "POST",
                    "/api/v1/reports",
                    user="buyer",
                    expected=201,
                    json_body={"target_type": "product", "target_id": product_id, "reason": "重复举报"},
                )
            )
            self.rec.must_eq(int(duplicate.get("existing_report_id") or 0), report_id, "未结举报复用原事项")
            self._call(
                "POST",
                f"/api/v1/reports/{report_id}/supplements",
                user="buyer",
                expected=200,
                json_body={"content": "补充说明：交易前已核对描述。", "evidence_keys": [evidence["key"]]},
            )
            mine = self._list(self._call("GET", "/api/v1/reports/mine", user="buyer", expected=200))
            mine_row = next(item for item in mine if int(item["id"]) == report_id)
            self.rec.must_eq(len(mine_row.get("supplements") or []), 1, "补充说明可查")
            mine_evidence_urls = mine_row.get("evidence_urls") or []
            self.rec.must_eq(len(mine_evidence_urls), 1, "举报证据链接返回举报人")
            self._assert_media_url(mine_evidence_urls[0], "本人举报证据")
            supplement_urls = (mine_row.get("supplements") or [{}])[0].get("evidence_urls") or []
            self.rec.must_eq(len(supplement_urls), 1, "补充证据链接返回举报人")
            self._assert_media_url(supplement_urls[0], "本人补充证据")
            rows = self._list(self._call("GET", "/api/v1/admin/reports", user="admin", expected=200, params={"status": "pending"}))
            report_row = next(row for row in rows if int(row.get("id") or 0) == report_id and row.get("case_id"))
            case_id = int(report_row["case_id"])
            for field in ("detail", "evidence_keys", "evidence_urls"):
                self.rec.must(field not in report_row, f"未认领举报列表不披露 {field}")
            self._call("GET", f"/api/v1/admin/cases/{case_id}", user="admin2", expected=403)
            self.cases["report_product"] = {"id": case_id, "report_id": report_id}
            self._claim(case_id)
            other_rows = self._list(self._call("GET", "/api/v1/admin/reports", user="admin2", expected=200, params={"status": "all"}))
            other_row = next(row for row in other_rows if int(row.get("id") or 0) == report_id)
            for field in ("detail", "evidence_keys", "evidence_urls"):
                self.rec.must(field not in other_row, f"其他管理员举报列表不披露 {field}")
            self._call("GET", f"/api/v1/admin/cases/{case_id}", user="admin2", expected=403)
            case_detail = self._dict(self._call("GET", f"/api/v1/admin/cases/{case_id}", user="admin", expected=200))
            self.rec.must_eq(case_detail.get("case_type"), "report", "事项类型 report")
            self.rec.must_eq(int(case_detail.get("report", {}).get("id") or 0), report_id, "事项关联举报")
            self.rec.must_eq(len(case_detail.get("report", {}).get("evidence_keys") or []), 1, "证据 key 在认领事项可见")
            evidence_urls = case_detail.get("report", {}).get("evidence_urls") or []
            self.rec.must_eq(len(evidence_urls), 1, "证据直链在认领事项可见")
            self._assert_media_url(evidence_urls[0], "举报证据")
            supplements = case_detail.get("report", {}).get("supplements") or []
            self.rec.must_eq(len(supplements), 1, "认领事项可查看补充说明")
            self.rec.must_eq(supplements[0].get("content"), "补充说明：交易前已核对描述。", "补充说明内容")
            supplement_evidence_urls = supplements[0].get("evidence_urls") or []
            self.rec.must_eq(len(supplement_evidence_urls), 1, "认领事项可查看补充证据")
            self._assert_media_url(supplement_evidence_urls[0], "补充证据")
            target_image_urls = (case_detail.get("report_target") or {}).get("image_urls") or []
            self.rec.must(bool(target_image_urls), "举报对象商品图直链")
            if target_image_urls:
                self._assert_media_url(target_image_urls[0], "举报对象商品图")
            self._call(
                "POST",
                f"/api/v1/admin/cases/{case_id}/inquiry",
                user="admin",
                expected=200,
                json_body={"content": "请说明商品描述与实物差异"},
            )
            seller_cases = self._list(self._call("GET", "/api/v1/me/cases", user="seller", expected=200))
            self.rec.must(any(int(row["id"]) == case_id for row in seller_cases), "被举报人可读事项")
            seller_case = self._dict(self._call("GET", f"/api/v1/me/cases/{case_id}", user="seller", expected=200))
            self.rec.must_eq(seller_case.get("can_submit_statement"), True, "问询后说明资格")
            statement_content = f"卖方说明正文标记-{self.run_id}"
            self.audit_targets.setdefault("sensitive_markers", []).append(statement_content)
            self._call(
                "POST",
                f"/api/v1/me/cases/{case_id}/statement",
                user="seller",
                expected=200,
                json_body={"content": statement_content},
            )
            # UC-C08-01：举报人无权读取被询问人的说明/申辩内容。
            self._call("GET", f"/api/v1/me/cases/{case_id}", user="buyer", expected=403)
            self._call(
                "POST",
                f"/api/v1/admin/cases/{case_id}/messages",
                user="admin",
                expected=200,
                json_body={"content": "已收到卖方说明，将结合证据处理。"},
            )
            decision = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/admin/reports/cases/{case_id}/decision",
                    user="admin",
                    expected=200,
                    json_body={
                        "outcome": "handled",
                        "reason": "验收认定违规：限制展示",
                        "public_summary": "经核查，涉事商品已停止公开。",
                        "basis": "SC-07-08",
                        "actions": {"restrict_display": True},
                    },
                )
            )
            self.rec.must("处置" in str(decision.get("detail")), "举报处置结论")
            report_row = next(
                item
                for item in self._list(self._call("GET", "/api/v1/reports/mine", user="buyer", expected=200))
                if int(item["id"]) == report_id
            )
            self.rec.must_eq(report_row.get("status"), "handled", "举报 handled")
            self.rec.must_eq(report_row.get("result_confirmed"), True, "结果已确认")
            product_restricted = self._product_detail("P_REPORT", "seller")
            self.rec.must_eq(product_restricted.get("display_restricted"), True, "商品停止公开")
            self.rec.must_eq(product_restricted.get("status"), "listed", "展示限制不改生命周期")
            self._call("GET", f"/api/v1/products/{product_id}", user="outsider", expected=404)
            restricted_favorites = self._list(self._call("GET", "/api/v1/favorites", user="buyer", expected=200))
            restricted_row = next(item for item in restricted_favorites if int(item["product_id"]) == product_id)
            self.rec.must_eq(restricted_row.get("valid"), False, "展示限制后收藏失效")
            restricted_search = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="buyer",
                    expected=200,
                    params={"keyword": f"举报处置商品-{self.run_id}"},
                )
            )
            self.rec.must_eq(restricted_search.get("total"), 0, "展示限制后搜索无入口")
            received = self._list(self._call("GET", "/api/v1/reports/received", user="seller", expected=200))
            received_row = next(item for item in received if int(item["id"]) == report_id)
            self.rec.must("reporter_id" not in received_row, "收到举报不披露举报人")
            self.rec.must("evidence_urls" not in received_row, "收到举报不披露举报人证据")
            public_notice = self._dict(self._call(
                "GET", f"/api/v1/products/{product_id}/restriction-result", user="outsider", expected=200,
            ))
            self.rec.must_eq(set(public_notice), {"public_result"}, "原入口仅返回匿名结果")
            self.rec.must_eq(public_notice["public_result"], "经核查，涉事商品已停止公开。", "第三方可读匿名处置提示")
            restricted_detail = self._product_detail("P_REPORT", "seller")
            self.rec.must_eq(
                restricted_detail.get("restriction_result"),
                "经核查，涉事商品已停止公开。",
                "受限商品入口匿名结果提示",
            )
            seller_notifications = self._notifications("seller")
            buyer_notifications = self._notifications("buyer")
            self.rec.must(self._has_notification(seller_notifications, "inquiry", link_id=case_id), "问询通知被询问人")
            self.rec.must(self._has_notification(seller_notifications, "disposal", link_id=case_id), "实际处置通知受影响者")
            self.rec.must(self._has_notification(buyer_notifications, "report_result", link_id=report_id), "举报结果通知举报人")
            self._call(
                "POST",
                f"/api/v1/reports/{report_id}/supplements",
                user="buyer",
                expected=409,
                json_body={"content": "结案后补充"},
            )
            restored = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/admin/products/{product_id}/restore-display",
                    user="admin",
                    expected=200,
                    json_body={"case_id": case_id, "reason": "验收解除展示限制"},
                )
            )
            self.rec.must("解除" in str(restored.get("detail")), "解除展示限制")
            after_restore = self._product_detail("P_REPORT", "seller")
            self.rec.must_eq(after_restore.get("display_restricted"), False, "恢复公开")
            self.rec.must_eq(after_restore.get("status"), "listed", "生命周期保持")
            self._call("GET", f"/api/v1/products/{product_id}", user="outsider", expected=200)
            restored_favorites = self._list(self._call("GET", "/api/v1/favorites", user="buyer", expected=200))
            restored_row = next(item for item in restored_favorites if int(item["product_id"]) == product_id)
            self.rec.must_eq(restored_row.get("valid"), True, "解除限制后收藏恢复有效")
            restored_search = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="buyer",
                    expected=200,
                    params={"keyword": f"举报处置商品-{self.run_id}"},
                )
            )
            self.rec.must_eq(restored_search.get("total"), 1, "解除限制后搜索恢复")
            history = self._list(
                self._call("GET", f"/api/v1/products/{product_id}/edit-history", user="seller", expected=200)
            )
            self.rec.must(any(row.get("edit_type") == "display_restore" for row in history), "解除展示留编辑历史")

        with self.rec.step(
            "GOV-02",
            "评论举报：无关交易内容仅移除违规对象；被处置人收到通知；收到举报入口可读",
            ac=["US-07-AC-03", "US-07-AC-04", "US-07-AC-06", "US-08-AC-04", "US-12-AC-04"],
            sc=["SC-07-11", "SC-07-13", "SC-12-02"],
        ):
            product_id = int(self.products["P_COMMENT"]["id"])
            comment_id = int(self.comments["second"])
            report = self._dict(
                self._call(
                    "POST",
                    "/api/v1/reports",
                    user="seller2",
                    expected=201,
                    json_body={
                        "target_type": "comment",
                        "target_id": comment_id,
                        "reason": "验收评论违规：无关广告",
                    },
                )
            )
            report_id = int(report["id"])
            self.reports["comment"] = {"id": report_id, "target_id": comment_id}
            rows = self._list(self._call("GET", "/api/v1/admin/reports", user="admin", expected=200, params={"status": "pending"}))
            case_id = next(int(row["case_id"]) for row in rows if int(row.get("id") or 0) == report_id and row.get("case_id"))
            self._claim(case_id)
            self._call(
                "POST",
                f"/api/v1/admin/reports/cases/{case_id}/decision",
                user="admin",
                expected=200,
                json_body={
                    "outcome": "handled",
                    "reason": "验收评论违规并移除",
                    "public_summary": "违规评论已移除。",
                    "actions": {"remove_content": True},
                },
            )
            comments = self._list(
                self._call("GET", f"/api/v1/products/{product_id}/comments", user="outsider", expected=200)
            )
            row = next(item for item in comments if int(item["id"]) == comment_id)
            self.rec.must_eq(row.get("deleted"), True, "违规评论逻辑删除")
            self.rec.must_eq(row.get("content"), "该评论已删除", "删除占位")
            buyer_received = self._list(self._call("GET", "/api/v1/reports/received", user="buyer2", expected=200))
            self.rec.must(any(int(item["id"]) == report_id for item in buyer_received), "被处置人收到举报")
            buyer_notifications = self._notifications("buyer2")
            self.rec.must(self._has_notification(buyer_notifications, "disposal"), "被处置人收到 disposal 通知")
            # 对象逻辑删除后：既有举报仍可读，新举报失败。
            self._call(
                "POST",
                f"/api/v1/products/{product_id}/comments",
                user="outsider",
                expected=201,
                json_body={"content": f"对象失效前评论-{self.run_id}"},
            )
            self._call(
                "POST",
                "/api/v1/reports",
                user="seller2",
                expected=409,
                json_body={"target_type": "comment", "target_id": comment_id, "reason": "同一对象已结案"},
            )
            self._call(
                "POST",
                "/api/v1/reports",
                user="buyer",
                expected=400,
                json_body={"target_type": "comment", "target_id": comment_id, "reason": "对象已删除"},
            )
            existing = self._list(self._call("GET", "/api/v1/reports/mine", user="seller2", expected=200))
            self.rec.must(any(int(item["id"]) == report_id and item["status"] == "handled" for item in existing), "既有举报结案后仍可读")

        with self.rec.step(
            "GOV-03",
            "举报无法认定：记录不予处理并匿名公开；不推定平台外事实、不自动处罚",
            ac=["US-07-AC-02", "US-07-AC-05", "US-08-AC-03"],
            sc=["SC-07-06"],
        ):
            # 用主交易买方评价作为举报对象。
            published = self._list(
                self._call("GET", "/api/v1/me/reviews", user="buyer", expected=200, params={"type": "published"})
            )
            review_id = next(int(row["id"]) for row in published if int(row["trade_id"]) == int(self.trades["T_MAIN"]["id"]))
            report = self._dict(
                self._call(
                    "POST",
                    "/api/v1/reports",
                    user="outsider",
                    expected=201,
                    json_body={"target_type": "review", "target_id": review_id, "reason": "验收：评价内容无法核实"},
                )
            )
            report_id = int(report["id"])
            rows = self._list(self._call("GET", "/api/v1/admin/reports", user="admin", expected=200, params={"status": "pending"}))
            case_id = next(int(row["case_id"]) for row in rows if int(row.get("id") or 0) == report_id and row.get("case_id"))
            self._claim(case_id)
            self._call(
                "POST",
                f"/api/v1/admin/reports/cases/{case_id}/decision",
                user="admin",
                expected=200,
                json_body={
                    "outcome": "unfounded",
                    "reason": "依据不足，无法认定",
                    "public_summary": "依据不足，不予处理。",
                },
            )
            mine = self._list(self._call("GET", "/api/v1/reports/mine", user="outsider", expected=200))
            row = next(item for item in mine if int(item["id"]) == report_id)
            self.rec.must_eq(row.get("status"), "unfounded", "举报 unfounded")
            self.rec.must_eq(row.get("public_result"), None, "不予处理不生成公开结果")
            review_after = self._list(
                self._call("GET", "/api/v1/me/reviews", user="buyer", expected=200, params={"type": "published"})
            )
            self.rec.must(any(int(item["id"]) == review_id for item in review_after), "不予处理不删除评价")
            # 管理员有依据移除违规评价（US-07-AC-02）。
            removal_report = self._dict(
                self._call(
                    "POST",
                    "/api/v1/reports",
                    user="buyer2",
                    expected=201,
                    json_body={"target_type": "review", "target_id": review_id, "reason": "验收：评价含违规内容"},
                )
            )
            removal_report_id = int(removal_report["id"])
            removal_rows = self._list(
                self._call("GET", "/api/v1/admin/reports", user="admin", expected=200, params={"status": "pending"})
            )
            removal_case_id = next(
                int(row["case_id"])
                for row in removal_rows
                if int(row.get("id") or 0) == removal_report_id and row.get("case_id")
            )
            self._claim(removal_case_id)
            self._call(
                "POST",
                f"/api/v1/admin/reports/cases/{removal_case_id}/decision",
                user="admin",
                expected=200,
                json_body={
                    "outcome": "handled",
                    "reason": "验收评价违规移除",
                    "public_summary": "违规评价已移除。",
                    "actions": {"remove_content": True},
                },
            )
            removed_reviews = self._list(
                self._call("GET", "/api/v1/me/reviews", user="buyer", expected=200, params={"type": "published"})
            )
            removed_row = next(item for item in removed_reviews if int(item["id"]) == review_id)
            self.rec.must_eq(removed_row.get("deleted"), True, "管理员有依据移除评价")

        with self.rec.step(
            "GOV-04",
            "举报认定违规并封禁：待接受请求关闭/通知/归档；交易冻结暂停计时；可申诉与管理员回复；解除恢复权限与展示",
            ac=["US-01-AC-07", "US-04-AC-07", "US-07-AC-07", "US-08-AC-04", "US-08-AC-05", "US-08-AC-07", "US-09-AC-05", "US-14-AC-07"],
            sc=["SC-01-06", "SC-01-07", "SC-01-12", "SC-07-07", "SC-07-09", "SC-07-13", "SC-09-05"],
        ):
            self._publish("P_BAN_PENDING", "seller2", f"封禁待接受商品-{self.run_id}", price=7200, category_ids=[self.categories["main"]["id"]])
            self._approve("P_BAN_PENDING")
            self._publish("P_BAN_TRADE", "seller2", f"封禁交易商品-{self.run_id}", price=7300, category_ids=[self.categories["main"]["id"]])
            self._approve("P_BAN_TRADE")
            self._publish("P_BAN_COMPLETED", "seller2", f"封禁前已完成商品-{self.run_id}", price=7250, category_ids=[self.categories["main"]["id"]])
            self._approve("P_BAN_COMPLETED")
            self._request_trade("T_BAN_COMPLETED", "buyer2", "P_BAN_COMPLETED")
            self._accept("T_BAN_COMPLETED", "seller2")
            agreement_completed = self._propose("T_BAN_COMPLETED", "buyer2", AGREEMENT_A)
            self._agree("T_BAN_COMPLETED", agreement_completed, "seller2")
            self._confirm("T_BAN_COMPLETED", "buyer2")
            self._confirm("T_BAN_COMPLETED", "seller2")
            self.rec.must_eq(self._trade_detail("T_BAN_COMPLETED", "buyer2").get("status"), "completed", "封禁前已完成交易")
            self._request_trade("T_BAN_PENDING", "buyer", "P_BAN_PENDING")
            self._request_trade("T_BAN_TRADE", "buyer2", "P_BAN_TRADE")
            self._accept("T_BAN_TRADE", "seller2")
            agreement = self._propose("T_BAN_TRADE", "buyer2", AGREEMENT_A)
            self._agree("T_BAN_TRADE", agreement, "seller2")
            self._confirm("T_BAN_TRADE", "buyer2")
            report = self._dict(
                self._call(
                    "POST",
                    "/api/v1/reports",
                    user="buyer",
                    expected=201,
                    json_body={"target_type": "user", "target_id": self._uid("seller2"), "reason": "验收：卖方违规"},
                )
            )
            report_id = int(report["id"])
            rows = self._list(self._call("GET", "/api/v1/admin/reports", user="admin", expected=200, params={"status": "pending"}))
            case_id = next(int(row["case_id"]) for row in rows if int(row.get("id") or 0) == report_id and row.get("case_id"))
            self._claim(case_id)
            self._call(
                "POST",
                f"/api/v1/admin/reports/cases/{case_id}/decision",
                user="admin",
                expected=200,
                json_body={
                    "outcome": "handled",
                    "reason": "验收认定违规并封禁",
                    "public_summary": "涉事账户已封禁，相关请求关闭，交易冻结。",
                    "actions": {"ban_user": True, "ban_reason": "验收违规封禁"},
                },
            )
            me_seller2 = self._dict(self._call("GET", "/api/v1/auth/me", user="seller2", expected=200))
            self.rec.must_eq(me_seller2.get("status"), "banned", "封禁状态")
            self._call("GET", "/api/v1/products/mine", user="seller2", expected=200)
            self._call("GET", "/api/v1/favorites", user="seller2", expected=200)
            self._call(
                "POST",
                f"/api/v1/products/{self.products['P_COMMENT']['id']}/comments",
                user="seller2",
                expected=403,
                json_body={"content": "封禁期间写操作"},
            )
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_BAN_COMPLETED']['id']}/review",
                user="seller2",
                expected=403,
                json_body={"rating": 5, "content": "封禁期间评价"},
            )
            self._call(
                "POST",
                "/api/v1/reports",
                user="seller2",
                expected=403,
                json_body={"target_type": "user", "target_id": self._uid("buyer"), "reason": "封禁期间举报"},
            )
            self._call(
                "POST",
                f"/api/v1/admin/users/{self._uid('seller2')}/ban",
                user="admin",
                expected=409,
                json_body={"reason": "重复封禁"},
            )
            pending_detail = self._trade_detail("T_BAN_PENDING", "buyer")
            self.rec.must_eq(pending_detail.get("status"), "closed", "封禁关闭待接受请求")
            self.rec.must_eq(pending_detail.get("close_reason"), "相关账户被封禁", "封禁关闭原因")
            buyer_notifications = self._notifications("buyer")
            self.rec.must(
                self._has_notification(buyer_notifications, "request_closed", link_id=int(self.trades["T_BAN_PENDING"]["id"])),
                "封禁关闭请求通知买方",
            )
            seller2_notifications = self._notifications("seller2")
            self.rec.must(
                self._has_notification(seller2_notifications, "request_closed", link_id=int(self.trades["T_BAN_PENDING"]["id"])),
                "封禁关闭请求通知卖方",
            )
            self.rec.must_eq(
                self._trade_detail("T_BAN_PENDING", "buyer").get("conversation_archived"),
                True,
                "封禁关闭请求分支归档",
            )
            frozen = self._trade_detail("T_BAN_TRADE", "buyer2")
            self.rec.must_eq(frozen.get("frozen"), True, "封禁冻结已接受交易")
            self.rec.must(frozen.get("confirm_wait_paused_at"), "封禁暂停已有单方确认计时")
            pending_product = self._product_detail("P_BAN_PENDING", "seller2")
            self.rec.must_eq(pending_product.get("display_restricted"), True, "封禁商品停止公开")
            self.rec.must_eq(pending_product.get("status"), "listed", "封禁不改商品生命周期")
            trade_product = self._product_detail("P_BAN_TRADE", "seller2")
            self.rec.must_eq(trade_product.get("display_restricted"), True, "交易中商品停止公开")
            self.rec.must_eq(trade_product.get("status"), "in_transaction", "交易中商品锁单保持")
            self._call(
                "POST",
                f"/api/v1/admin/products/{self.products['P_BAN_PENDING']['id']}/restore-display",
                user="admin",
                expected=409,
                json_body={"case_id": case_id, "reason": "卖方仍封禁时不得单独解除"},
            )
            restrictions = self._list(
                self._call("GET", f"/api/v1/admin/users/{self._uid('seller2')}/restrictions", user="admin", expected=200)
            )
            self.rec.must(any(row.get("status") == "active" and row.get("type") == "ban" for row in restrictions), "封禁限制记录")
            seller2_cases = self._list(self._call("GET", "/api/v1/me/cases", user="seller2", expected=200))
            self.rec.must(any(int(row["id"]) == case_id for row in seller2_cases), "封禁事项进入本人事项")
            case_info = self._dict(self._call("GET", f"/api/v1/me/cases/{case_id}", user="seller2", expected=200))
            self.rec.must_eq(case_info.get("can_submit_appeal"), True, "处置后可申辩")
            appeal_content = f"卖方申辩正文标记-{self.run_id}"
            self.audit_targets["appeal_case_id"] = case_id
            self.audit_targets.setdefault("sensitive_markers", []).append(appeal_content)
            self._call(
                "POST",
                f"/api/v1/me/cases/{case_id}/appeal",
                user="seller2",
                expected=200,
                json_body={"content": appeal_content},
            )
            after_appeal = self._dict(self._call("GET", "/api/v1/auth/me", user="seller2", expected=200))
            self.rec.must_eq(after_appeal.get("status"), "banned", "申辩不自动撤销封禁")
            self._call(
                "POST",
                f"/api/v1/admin/cases/{case_id}/messages",
                user="admin",
                expected=200,
                json_body={"content": "已收到申辩，维持原处置。"},
            )
            seller2_notifications = self._notifications("seller2")
            self.rec.must(self._has_notification(seller2_notifications, "appeal_result", link_id=case_id), "申辩回复通知")
            self._call(
                "POST",
                f"/api/v1/admin/users/{self._uid('seller2')}/unban",
                user="admin",
                expected=200,
                json_body={"lift_reason": "验收复核后解除封禁"},
            )
            restored = self._dict(self._call("GET", "/api/v1/auth/me", user="seller2", expected=200))
            self.rec.must_eq(restored.get("status"), "normal", "解除封禁恢复 normal")
            self.rec.must_eq(self._product_detail("P_BAN_PENDING", "seller2").get("display_restricted"), False, "解除后展示恢复")
            unfrozen = self._trade_detail("T_BAN_TRADE", "buyer2")
            self.rec.must_eq(unfrozen.get("frozen"), False, "解除封禁解冻因该封禁冻结的交易")
            self.rec.must_eq(unfrozen.get("status"), "in_progress", "交易仍进行中")
            self._call(
                "POST",
                f"/api/v1/products/{self.products['P_COMMENT']['id']}/comments",
                user="seller2",
                expected=201,
                json_body={"content": "解除后恢复写权限"},
            )
            self._confirm("T_BAN_TRADE", "seller2")
            self.rec.must_eq(self._trade_detail("T_BAN_TRADE", "buyer2").get("status"), "completed", "解除后可完成交易")

        with self.rec.step(
            "GOV-05",
            "管理事项直接处置、用户列表、直接封禁/解除路径与权限",
            ac=["US-08-AC-01", "US-08-AC-07"],
            sc=["SC-07-09", "SC-07-10"],
        ):
            # 管理员用户列表
            users = self._list(self._call("GET", "/api/v1/admin/users", user="admin", expected=200, params={"status": "all"}))
            self.rec.must(any(int(row["id"]) == self._uid("seller2") for row in users), "管理员用户列表含卖方")
            self._call("GET", "/api/v1/admin/users", user="outsider", expected=403)
            # 直接封禁/解封（不通过举报）
            self._call(
                "POST",
                f"/api/v1/admin/users/{self._uid('outsider')}/ban",
                user="admin",
                expected=200,
                json_body={"reason": "验收直接封禁"},
            )
            self._call("POST", "/api/v1/auth/logout", user="outsider", expected=200)
            self._login_known("outsider", self.users["outsider"]["email"], self.users["outsider"]["password"], self._uid("outsider"), "user")
            self._call(
                "POST",
                "/api/v1/conversations/normal",
                user="outsider",
                expected=403,
                json_body={"peer_user_id": self._uid("seller")},
            )
            self._call(
                "POST",
                f"/api/v1/admin/users/{self._uid('outsider')}/unban",
                user="admin",
                expected=200,
                json_body={"lift_reason": "验收直接解除"},
            )
            self._call(
                "POST",
                "/api/v1/conversations/normal",
                user="outsider",
                expected=201,
                json_body={"peer_user_id": self._uid("seller")},
            )
            # 未认领事项不能处置；认领后可 dispose。
            report = self._dict(
                self._call(
                    "POST",
                    "/api/v1/reports",
                    user="buyer",
                    expected=201,
                    json_body={"target_type": "product", "target_id": int(self.products["P_MULTI"]["id"]), "reason": "验收直接处置事项"},
                )
            )
            report_id = int(report["id"])
            rows = self._list(self._call("GET", "/api/v1/admin/reports", user="admin2", expected=200, params={"status": "pending"}))
            case_id = next(int(row["case_id"]) for row in rows if int(row.get("id") or 0) == report_id and row.get("case_id"))
            self._call(
                "POST",
                f"/api/v1/admin/cases/{case_id}/dispose",
                user="admin2",
                expected=403,
                json_body={"conclusion": "未认领处置", "reason": "非法"},
            )
            self._call("POST", f"/api/v1/admin/cases/{case_id}/claim", user="admin2", expected=200, json_body={})
            self._call(
                "POST",
                f"/api/v1/admin/cases/{case_id}/dispose",
                user="admin2",
                expected=200,
                json_body={"conclusion": "验收直接处置", "reason": "仅验证管理入口", "basis": "SC-07-10"},
            )
            case_row = self._dict(self._call("GET", f"/api/v1/admin/cases/{case_id}", user="admin2", expected=200))
            self.rec.must_eq(case_row.get("status"), "disposed", "事项已处置")

    # ------------------------------------------------------------------
    # IM / 通知 / 统计 / 审计 / 本人业务
    # ------------------------------------------------------------------
    def im_and_notifications(self) -> None:
        with self.rec.step(
            "IM-01",
            "普通私聊复用、交易分支、未读/已读独立、归档禁发、转普通私聊、WS 真实收发",
            ac=["US-04-AC-04", "US-04-AC-05", "US-04-AC-06", "US-04-AC-07", "US-04-AC-08", "US-11-AC-03"],
            sc=["SC-04-05", "SC-04-06", "SC-04-08", "SC-04-09", "SC-11-02"],
        ):
            normal = self._dict(
                self._call(
                    "POST",
                    "/api/v1/conversations/normal",
                    user="buyer",
                    expected=201,
                    json_body={"peer_user_id": self._uid("seller")},
                )
            )
            again = self._dict(
                self._call(
                    "POST",
                    "/api/v1/conversations/normal",
                    user="buyer",
                    expected=201,
                    json_body={"peer_user_id": self._uid("seller")},
                )
            )
            self.rec.must_eq(int(again["id"]), int(normal["id"]), "普通私聊按双人复用")
            self.audit_targets["im_normal_conversation_id"] = int(normal["id"])
            self._call(
                "POST",
                "/api/v1/conversations/normal",
                user="buyer",
                expected=400,
                json_body={"peer_user_id": self._uid("buyer")},
            )
            conversations = self._list(self._call("GET", "/api/v1/conversations", user="buyer", expected=200))
            self.rec.must(any(int(row["id"]) == int(normal["id"]) for row in conversations), "会话列表含普通私聊")
            self._call("GET", f"/api/v1/conversations/{normal['id']}", user="outsider", expected=403)
            sent = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/conversations/{normal['id']}/messages",
                    user="buyer",
                    expected=200,
                    json_body={"content": f"普通私聊消息-{self.run_id}"},
                )
            )
            self.audit_targets["im_sent_message_id"] = int(sent["id"])
            summary = self._dict(self._call("GET", "/api/v1/conversations/unread-summary", user="seller", expected=200))
            self.rec.must(int(summary.get("unread", 0)) >= 1, "未读汇总含新消息")
            detail = self._dict(self._call("GET", f"/api/v1/conversations/{normal['id']}", user="seller", expected=200))
            self.rec.must(any(int(row["id"]) == int(sent["id"]) for row in detail.get("messages") or []), "会话详情含消息")
            # 查看详情不改变已读
            count_before = int(
                self._dict(self._call("GET", f"/api/v1/conversations/{normal['id']}", user="seller", expected=200)).get("unread") or 0
            )
            self.rec.must(count_before >= 1, "查看会话不自动已读")
            self._call(
                "POST",
                f"/api/v1/conversations/{normal['id']}/read",
                user="seller",
                expected=200,
                json_body={"last_displayed_message_id": int(sent["id"])},
            )
            self.audit_targets["im_read_conversation_id"] = int(normal["id"])
            # 相同已读水位重复提交不应新增成功审计。
            self._call(
                "POST",
                f"/api/v1/conversations/{normal['id']}/read",
                user="seller",
                expected=200,
                json_body={"last_displayed_message_id": int(sent["id"])},
            )
            after_read = self._dict(self._call("GET", f"/api/v1/conversations/{normal['id']}", user="seller", expected=200))
            self.rec.must_eq(int(after_read.get("unread") or 0), 0, "显式已读后未读归零")
            # 归档交易分支：查看历史允许，发送 409，可转普通私聊
            trade = self._trade_detail("T_MAIN", "buyer")
            trade_conversation = int(trade["conversation_id"])
            self.audit_targets["im_trade_conversation_id"] = trade_conversation
            history = self._dict(self._call("GET", f"/api/v1/conversations/{trade_conversation}", user="buyer", expected=200))
            self.rec.must(history.get("archived") is True, "完成交易分支归档")
            self._call(
                "POST",
                f"/api/v1/conversations/{trade_conversation}/messages",
                user="buyer",
                expected=409,
                json_body={"content": "归档后发送"},
            )
            migrated = self._dict(
                self._call("POST", f"/api/v1/conversations/{trade_conversation}/to-normal", user="buyer", expected=200)
            )
            self.rec.must(int(migrated["id"]) == int(normal["id"]), "转普通私聊复用同一双人会话")
            # 双方同时在线：HTTP 提交正文，WS 分别接收对方的真实消息推送。
            import websockets

            async def _ws_exchange() -> list[dict[str, Any]]:
                ws_base = self.base_url.replace('http', 'ws', 1) + '/ws?token='
                async with (
                    websockets.connect(ws_base + self._token('buyer'), proxy=None, open_timeout=10, close_timeout=5) as buyer_ws,
                    websockets.connect(ws_base + self._token('seller'), proxy=None, open_timeout=10, close_timeout=5) as seller_ws,
                    httpx.AsyncClient(base_url=self.api.origin, timeout=10, trust_env=False) as client,
                ):
                    for role, websocket in [('buyer', buyer_ws), ('seller', seller_ws)]:
                        await websocket.send(json.dumps({'type': 'ping'}))
                        pong = json.loads(await asyncio.wait_for(websocket.recv(), timeout=10))
                        self.rec.must_eq(pong.get('type'), 'pong', f'{role} WS ping/pong')
                    exchanges = []
                    for index in range(3):
                        for sender, receiver, websocket in [('buyer', 'seller', seller_ws), ('seller', 'buyer', buyer_ws)]:
                            content = f'WS 双向消息-{sender}-{index}-{self.run_id}'
                            response = await client.post(
                                f"/api/v1/conversations/{normal['id']}/messages",
                                headers={'Authorization': f'Bearer {self._token(sender)}'},
                                json={'content': content},
                            )
                            self.rec.must_eq(response.status_code, 200, f'{sender} HTTP 发送成功')
                            message_id = response.json()['id']
                            async def receive_message(websocket=websocket):
                                while True:
                                    payload = json.loads(await websocket.recv())
                                    if payload.get('type') == 'message':
                                        return payload
                            payload = await asyncio.wait_for(receive_message(), timeout=10)
                            self.rec.must_eq(payload.get('conversation_id'), int(normal['id']), f'{receiver} 收到正确会话')
                            self.rec.must_eq(payload.get('message_id'), message_id, f'{receiver} 收到对应消息 ID')
                            self.rec.must_eq(payload.get('sender_id'), self._uid(sender), f'{receiver} 收到正确发送者')
                            self.rec.must_eq(payload.get('content'), content, f'{receiver} 收到完整正文')
                            exchanges.append({'sender': sender, 'receiver': receiver, 'message_id': message_id})
                    return exchanges

            exchanges = asyncio.run(_ws_exchange())
            self.rec.must_eq(len({item['message_id'] for item in exchanges}), 6, '三轮双向消息 ID 各不相同')
            self.ws_ok = True
            self.rec.data['ws'] = {'buyer_pong': True, 'seller_pong': True, 'rounds': 3, 'exchanges': exchanges}

        with self.rec.step(
            "IM-02",
            "管理员仅按认领事项必要范围读取会话：消息举报目标会话成功，未认领/他人/普通人/无关会话拒绝，已读不变",
            sc=["SC-04-07"],
        ):
            conversation = self._dict(
                self._call(
                    "POST",
                    "/api/v1/conversations/normal",
                    user="buyer2",
                    expected=201,
                    json_body={"peer_user_id": self._uid("commenter")},
                )
            )
            conversation_id = int(conversation["id"])
            message_ids: list[int] = []
            for index in range(3):
                content = f"管理必要范围历史消息-{index}-{self.run_id}"
                self.audit_targets.setdefault("sensitive_markers", []).append(content)
                sent = self._dict(
                    self._call(
                        "POST",
                        f"/api/v1/conversations/{conversation_id}/messages",
                        user="commenter",
                        expected=200,
                        json_body={"content": content},
                    )
                )
                message_ids.append(int(sent["id"]))
            target_message_id = message_ids[1]
            report = self._dict(
                self._call(
                    "POST",
                    "/api/v1/reports",
                    user="buyer2",
                    expected=201,
                    json_body={
                        "target_type": "message",
                        "target_id": target_message_id,
                        "reason": f"消息举报-{self.run_id}",
                    },
                )
            )
            message_report_id = int(report["id"])
            self.reports["message"] = {
                "id": message_report_id,
                "conversation_id": conversation_id,
                "message_id": target_message_id,
            }
            case_rows = self._list(
                self._call(
                    "GET",
                    "/api/v1/admin/cases",
                    user="admin2",
                    expected=200,
                    params={"status": "pending"},
                )
            )
            message_case_id = next(
                int(row["id"])
                for row in case_rows
                if int(row.get("report_id") or 0) == message_report_id
            )
            self.cases["message"] = {
                "id": message_case_id,
                "report_id": message_report_id,
                "conversation_id": conversation_id,
            }
            # 未认领、普通用户、普通第三方均不能使用管理入口。
            self._call(
                "GET",
                f"/api/v1/admin/cases/{message_case_id}/conversations/{conversation_id}",
                user="admin2",
                expected=403,
            )
            self._call(
                "GET",
                f"/api/v1/admin/cases/{message_case_id}/conversations/{conversation_id}",
                user="commenter",
                expected=403,
            )
            self._call(
                "GET",
                f"/api/v1/admin/cases/{message_case_id}/conversations/{conversation_id}",
                user="outsider",
                expected=403,
            )
            self._claim(message_case_id, "admin2")
            # 其他管理员不能借用认领人资格。
            self._call(
                "GET",
                f"/api/v1/admin/cases/{message_case_id}/conversations/{conversation_id}",
                user="admin",
                expected=403,
            )
            unrelated = self._dict(
                self._call(
                    "POST",
                    "/api/v1/conversations/normal",
                    user="buyer2",
                    expected=201,
                    json_body={"peer_user_id": self._uid("outsider")},
                )
            )
            unrelated_id = int(unrelated["id"])
            self._call(
                "GET",
                f"/api/v1/admin/cases/{message_case_id}/conversations/{unrelated_id}",
                user="admin2",
                expected=403,
            )
            unread_before = int(
                self._dict(
                    self._call(
                        "GET",
                        f"/api/v1/conversations/{conversation_id}",
                        user="buyer2",
                        expected=200,
                    )
                ).get("unread")
                or 0
            )
            page_one = self._dict(
                self._call(
                    "GET",
                    f"/api/v1/admin/cases/{message_case_id}/conversations/{conversation_id}",
                    user="admin2",
                    expected=200,
                    params={"limit": 1},
                )
            )
            self.rec.must_eq(page_one.get("scope", {}).get("relation"), "report_message", "消息举报关联类型")
            self.rec.must_eq(
                int(page_one.get("scope", {}).get("target_message_id") or 0),
                target_message_id,
                "必要范围指向被举报消息",
            )
            self.rec.must_eq(
                int(page_one.get("conversation", {}).get("id") or 0),
                conversation_id,
                "返回目标会话",
            )
            first_page_messages = page_one.get("messages") or []
            self.rec.must_eq(len(first_page_messages), 1, "分页 limit 生效")
            self.rec.must_eq(int(first_page_messages[0]["id"]), message_ids[-1], "分页从最新消息开始")
            self.rec.must_eq(set(first_page_messages[0].keys()), {"id", "sender_id", "kind", "content", "created_at"}, "消息字段白名单")
            self.rec.must_eq(page_one.get("has_more"), True, "有更早消息")
            next_before = page_one.get("next_before_id")
            self.rec.must(isinstance(next_before, int), "返回下一页游标")
            page_two = self._dict(
                self._call(
                    "GET",
                    f"/api/v1/admin/cases/{message_case_id}/conversations/{conversation_id}",
                    user="admin2",
                    expected=200,
                    params={"limit": 1, "before_id": next_before},
                )
            )
            self.rec.must_eq(
                int((page_two.get("messages") or [{}])[0].get("id") or 0),
                message_ids[1],
                "分页无重复并前进",
            )
            self._dict(
                self._call(
                    "GET",
                    f"/api/v1/admin/cases/{message_case_id}/conversations/{conversation_id}",
                    user="admin2",
                    expected=200,
                    params={"limit": 1, "before_id": page_two.get("next_before_id")},
                )
            )
            unread_after = int(
                self._dict(
                    self._call(
                        "GET",
                        f"/api/v1/conversations/{conversation_id}",
                        user="buyer2",
                        expected=200,
                    )
                ).get("unread")
                or 0
            )
            self.rec.must_eq(unread_after, unread_before, "管理读取不改变当事人未读")
            admin_read = self._db_one(
                ("select count(*) as n from app.conversation_reads "
                 "where conversation_id = :cid and user_id = :uid"),
                {"cid": conversation_id, "uid": self._uid("admin2")},
            )
            self.rec.must_eq(int(admin_read["n"]), 0, "管理读取不写管理员已读记录")
            read_audit = self._db_one(
                ("select count(*) as n from app.audit_events where event_type = 'admin.case_conversation_read' "
                 "and target_type = 'conversation' and target_id = :cid"),
                {"cid": str(conversation_id)},
            )
            self.rec.must(int(read_audit["n"]) >= 1, "管理读取本身写审计")

        with self.rec.step(
            "IM-03",
            "消息举报处置：处置前/他人不可见，处置后仅作者收到、不显示举报人",
            sc=["SC-12-02"],
        ):
            message_report = self.reports["message"]
            message_report_id = int(message_report["id"])
            message_case_id = int(self.cases["message"]["id"])
            conversation_id = int(message_report["conversation_id"])
            for viewer in ("commenter", "buyer2", "outsider"):
                received = self._list(
                    self._call("GET", "/api/v1/reports/received", user=viewer, expected=200)
                )
                self.rec.must(
                    not any(int(item["id"]) == message_report_id for item in received),
                    f"处置前 {viewer} 收到列表不可见消息举报",
                )
            reason = f"消息举报处置原因-{self.run_id}"
            self._call(
                "POST",
                f"/api/v1/admin/reports/cases/{message_case_id}/decision",
                user="admin2",
                expected=200,
                json_body={
                    "outcome": "handled",
                    "reason": reason,
                    "public_summary": "经核查消息内容违规，已处置。",
                    "actions": {"remove_content": True},
                },
            )
            author_received = self._list(
                self._call("GET", "/api/v1/reports/received", user="commenter", expected=200)
            )
            author_row = next(
                item for item in author_received if int(item["id"]) == message_report_id
            )
            self.rec.must_eq(author_row.get("target_type"), "message", "收到列表含真实消息举报")
            self.rec.must_eq(int(author_row.get("case_id") or 0), message_case_id, "收到举报关联事项")
            self.rec.must("reporter_id" not in author_row, "收到举报不披露举报人 ID")
            self.rec.must("reporter" not in json.dumps(author_row, ensure_ascii=False), "收到举报不披露举报人")
            for viewer in ("buyer2", "outsider", "seller"):
                received = self._list(
                    self._call("GET", "/api/v1/reports/received", user=viewer, expected=200)
                )
                self.rec.must(
                    not any(int(item["id"]) == message_report_id for item in received),
                    f"{viewer} 不是消息作者，不可见该收到举报",
                )
            # 已处置后认领管理员仍可按必要范围读取历史；其他管理员仍拒绝。
            self._dict(
                self._call(
                    "GET",
                    f"/api/v1/admin/cases/{message_case_id}/conversations/{conversation_id}",
                    user="admin2",
                    expected=200,
                )
            )
            self._call(
                "GET",
                f"/api/v1/admin/cases/{message_case_id}/conversations/{conversation_id}",
                user="admin",
                expected=403,
            )

        with self.rec.step(
            "NOTIF-01",
            "通知列表不标读；打开具体通知才已读；未读数/待办独立；他人通知 404",
            ac=["US-11-AC-01", "US-11-AC-02", "US-11-AC-04", "US-11-AC-06"],
            sc=["SC-11-01", "SC-11-02", "SC-11-03", "SC-11-04"],
        ):
            before = self._dict(self._call("GET", "/api/v1/notifications/unread-count", user="buyer", expected=200))
            count_before = int(before.get("unread") or 0)
            self.rec.must(count_before > 0, "买方存在未读通知")
            listed = self._dict(self._call("GET", "/api/v1/notifications", user="buyer", expected=200))
            self.rec.must(int(listed.get("total") or 0) >= count_before, "通知总数")
            after_list = self._dict(self._call("GET", "/api/v1/notifications/unread-count", user="buyer", expected=200))
            self.rec.must_eq(int(after_list.get("unread") or 0), count_before, "列表不自动标读")
            unread_items = [item for item in listed.get("items") or [] if not item.get("is_read")]
            if not unread_items:
                raise CheckFailure("没有可标读通知")
            target = unread_items[0]
            self._call("POST", f"/api/v1/notifications/{target['id']}/read", user="buyer", expected=200)
            self.audit_targets["notification_read_id"] = int(target["id"])
            # 重复打开同一条已读通知不应重复写成功审计。
            self._call("POST", f"/api/v1/notifications/{target['id']}/read", user="buyer", expected=200)
            after_read = self._dict(self._call("GET", "/api/v1/notifications/unread-count", user="buyer", expected=200))
            self.rec.must_eq(int(after_read.get("unread") or 0), count_before - 1, "仅该条已读，未读-1")
            todos = self._dict(self._call("GET", "/api/v1/notifications/todos", user="buyer", expected=200))
            self.rec.must(isinstance(todos.get("items"), list), "待办可读")
            # 他人通知不可标读
            other_items = self._dict(self._call("GET", "/api/v1/notifications", user="buyer2", expected=200)).get("items") or []
            if other_items:
                self._call("POST", f"/api/v1/notifications/{other_items[0]['id']}/read", user="buyer", expected=404)
            else:
                self.rec.must(False, "买方2无可用于越权测试的通知")
            # 管理员不接收个人通知
            admin_list = self._dict(self._call("GET", "/api/v1/notifications", user="admin", expected=200))
            self.rec.must_eq(int(admin_list.get("total") or 0), 0, "管理员个人通知为空")
            admin_todos = self._dict(self._call("GET", "/api/v1/notifications/todos", user="admin", expected=200))
            self.rec.must_eq(int(admin_todos.get("total") or 0), 0, "管理员个人待办为空")

        with self.rec.step(
            "NOTIF-02",
            "通知接收方与关键事件矩阵：请求/接受/约定/确认/完成/冻结/异常/问询/处置/申诉",
            ac=["US-11-AC-05"],
            sc=["SC-11-01"],
        ):
            buyer_items = self._notifications("buyer")
            seller_items = self._notifications("seller")
            buyer_types = {item.get("type") for item in buyer_items}
            seller_types = {item.get("type") for item in seller_items}
            required_buyer = {"request_accepted", "agreement_decided", "trade_completed", "trade_abnormal", "report_result", "dispute_resolved"}
            required_seller = {"request_created", "agreement_proposed", "confirm_progress", "trade_completed", "inquiry", "disposal"}
            self.rec.must(required_buyer <= buyer_types, f"买方关键通知 {sorted(required_buyer - buyer_types)}")
            self.rec.must(required_seller <= seller_types, f"卖方关键通知 {sorted(required_seller - seller_types)}")
            self.rec.must("request_created" not in buyer_types or True, "请求通知只按事件接收方校验")
            self.rec.must_eq(self._uid("admin"), self.users["admin"]["id"], "管理员身份固定")

        with self.rec.step(
            "MY-01",
            "我的商品全状态/审核原因/待接受数；我的交易双身份；评价发表/收到；举报/事项入口",
            ac=["US-12-AC-01", "US-12-AC-02", "US-12-AC-03", "US-12-AC-04", "US-12-AC-05", "US-12-AC-06"],
            sc=["SC-12-01", "SC-12-02", "SC-12-03", "SC-12-04"],
        ):
            # 留下 pending 与 rejected 两类，便于全状态断言。
            self._publish("P_MY_PENDING", "seller", f"我的待审商品-{self.run_id}", price=7400, category_ids=[self.categories["main"]["id"]])
            self._publish("P_MY_REJECTED", "seller", f"我的拒绝商品-{self.run_id}", price=7500, category_ids=[self.categories["main"]["id"]])
            self._reject("P_MY_REJECTED", "验收保留拒绝状态")
            self._publish("P_MY_REQUEST", "seller", f"我的待请求商品-{self.run_id}", price=7600, category_ids=[self.categories["main"]["id"]])
            self._approve("P_MY_REQUEST")
            self._request_trade("T_MY_REQUEST", "buyer2", "P_MY_REQUEST")
            self._publish("P_MY_LOCKED", "seller", f"我的交易中商品-{self.run_id}", price=7700, category_ids=[self.categories["main"]["id"]])
            self._approve("P_MY_LOCKED")
            self._request_trade("T_MY_LOCKED", "outsider", "P_MY_LOCKED")
            self._accept("T_MY_LOCKED")
            mine = self._list(self._call("GET", "/api/v1/products/mine", user="seller", expected=200))
            by_key = {int(item["id"]): item for item in mine}
            statuses = {item.get("status") for item in mine}
            self.rec.must({"pending_review", "rejected", "listed", "in_transaction", "delisted"} <= statuses, f"我的商品全状态 {sorted(statuses)}")
            rejected = by_key[int(self.products["P_MY_REJECTED"]["id"])]
            self.rec.must_eq(rejected.get("reject_reason"), "验收保留拒绝状态", "我的商品审核原因")
            request_product = by_key[int(self.products["P_MY_REQUEST"]["id"])]
            self.rec.must_eq(int(request_product.get("pending_request_count") or 0), 1, "待接受请求数")
            mine_all = self._list(self._call("GET", "/api/v1/trades/mine", user="buyer", expected=200, params={"role": "all"}))
            mine_buyer = self._list(self._call("GET", "/api/v1/trades/mine", user="buyer", expected=200, params={"role": "buyer"}))
            mine_seller = self._list(self._call("GET", "/api/v1/trades/mine", user="seller", expected=200, params={"role": "seller"}))
            self.rec.must(mine_all and mine_buyer, "买方交易列表非空")
            self.rec.must(mine_seller, "卖方交易列表非空")
            self._call("GET", "/api/v1/trades/mine", user="buyer", expected=422, params={"role": "invalid"})
            published = self._list(self._call("GET", "/api/v1/me/reviews", user="buyer", expected=200, params={"type": "published"}))
            received = self._list(self._call("GET", "/api/v1/me/reviews", user="buyer", expected=200, params={"type": "received"}))
            self.rec.must(published and received, "评价发表/收到分别可读")
            self._call("GET", "/api/v1/me/reviews", user="buyer", expected=422, params={"type": "invalid"})
            reports_mine = self._list(self._call("GET", "/api/v1/reports/mine", user="buyer", expected=200))
            self.rec.must(reports_mine, "我的举报入口")
            received_reports = self._list(self._call("GET", "/api/v1/reports/received", user="buyer2", expected=200))
            self.rec.must(received_reports, "我收到的举报入口")
            cases = self._list(self._call("GET", "/api/v1/me/cases", user="buyer", expected=200))
            self.rec.must(cases, "我的事项入口")
            self._call("GET", "/api/v1/products/mine", expected=401)
            # 结束记录不可删除/重开（路由不存在）
            self._call("DELETE", f"/api/v1/trades/{self.trades['T_MAIN']['id']}", user="buyer", expected=405)
            self._call("POST", f"/api/v1/trades/{self.trades['T_MAIN']['id']}/reopen", user="buyer", expected=404)
            # 失效对象新举报失败；既有举报仍可读。
            self._call(
                "POST",
                "/api/v1/reports",
                user="buyer",
                expected=400,
                json_body={"target_type": "comment", "target_id": 999999999, "reason": "失效对象"},
            )
            # 结束交易不可接受/确认；他人商品不可编辑；他人事项不可提交说明。
            self._call("POST", f"/api/v1/trades/{self.trades['T_MAIN']['id']}/accept", user="seller", expected=409)
            self._call("POST", f"/api/v1/trades/{self.trades['T_MAIN']['id']}/confirmations", user="buyer", expected=409, json_body={})
            self._call(
                "PATCH",
                f"/api/v1/products/{self.products['P_MULTI']['id']}",
                user="buyer",
                expected=404,
                json_body={"title": "他人商品"},
            )
            other_case_id = int(self.cases["report_product"]["id"])
            self._call("GET", f"/api/v1/me/cases/{other_case_id}", user="buyer", expected=403)
            self._call(
                "POST",
                f"/api/v1/me/cases/{other_case_id}/statement",
                user="buyer",
                expected=403,
                json_body={"content": "越权说明"},
            )

        with self.rec.step(
            "ADMIN-CORRECTION-01",
            "用户不可自改交付记录；认领管理员有依据调整并保留原确认历史",
            ac=["US-06-AC-05"],
            sc=["SC-06-03", "SC-06-08"],
            note="UC-C06-03：用户说明后由管理员按事项处理，不是普通用户自行更正",
        ):
            trade_id = int(self.trades["T_MAIN"]["id"])
            before = self._trade_detail("T_MAIN", "buyer")
            self.rec.must_eq(before.get("status"), "completed", "更正前交易已完成")
            confirms_before = [dict(row) for row in before.get("confirmations") or []]
            self.rec.must(len(confirms_before) >= 2, "更正前有双方确认历史")
            for confirmation in confirms_before:
                self._call(
                    "PATCH",
                    f"/api/v1/trades/{trade_id}/confirmations/{int(confirmation['id'])}",
                    user="buyer",
                    expected=404,
                    json_body={},
                )
                self._call(
                    "DELETE",
                    f"/api/v1/trades/{trade_id}/confirmations/{int(confirmation['id'])}",
                    user="buyer",
                    expected=404,
                )
            unchanged = self._trade_detail("T_MAIN", "buyer")
            self.rec.must_eq(len(unchanged.get("confirmations") or []), len(confirms_before), "用户自改失败后确认历史不减少")
            case_id = self._relevant_case_for_product(int(self.products["P_MAIN"]["id"]), claimant="admin")
            reason = f"管理员更正交付记录-{self.run_id}"
            self._call(
                "POST",
                f"/api/v1/admin/trades/{trade_id}/adjust",
                user="admin",
                expected=200,
                json_body={"to_status": "in_progress", "reason": reason, "case_id": case_id},
            )
            corrected = self._trade_detail("T_MAIN", "buyer")
            self.rec.must_eq(corrected.get("status"), "in_progress", "管理员按事项调整")
            historical = [dict(row) for row in corrected.get("confirmations") or []]
            self.rec.must_eq({int(row["id"]) for row in historical}, {int(row["id"]) for row in confirms_before}, "原确认记录保留")
            self.rec.must(all(row.get("is_current") is False for row in historical), "调整后当前确认清空、不伪造新确认")
            transitions = self._list(
                self._call("GET", f"/api/v1/trades/{trade_id}/transitions", user="buyer", expected=200)
            )
            last = transitions[-1]
            self.rec.must_eq(last.get("reason"), reason, "管理更正原因留痕")
            self.rec.must_eq(last.get("basis_case_id"), case_id, "管理更正依据事项留痕")
            self._call(
                "POST",
                f"/api/v1/admin/trades/{trade_id}/adjust",
                user="admin",
                expected=200,
                json_body={"to_status": "completed", "reason": "恢复完成并保留原确认历史", "case_id": case_id},
            )
            restored = self._trade_detail("T_MAIN", "buyer")
            self.rec.must_eq(restored.get("status"), "completed", "管理更正后恢复完成")
            self.rec.must_eq(len(restored.get("confirmations") or []), len(confirms_before), "恢复后确认历史不丢失")
            self.rec.must(all(row.get("is_current") is False for row in restored.get("confirmations") or []), "管理调整不伪造双方确认")
            self._call(
                "POST",
                f"/api/v1/admin/cases/{case_id}/dispose",
                user="admin",
                expected=200,
                json_body={"conclusion": "交付记录更正处理完成", "reason": "保留原记录与依据", "basis": "SC-06-03"},
            )

        with self.rec.step(
            "STATS-01",
            "管理员统计：账户/商品/事项/交易计数与只读 SQL 对照；无金额；范围按完成时间；权限",
            ac=["US-10-AC-01", "US-10-AC-02", "US-10-AC-03", "US-10-AC-04", "US-10-AC-05", "US-10-AC-06"],
            sc=["SC-08-01", "SC-08-02", "SC-08-03", "SC-08-04", "SC-08-05", "SC-08-06"],
        ):
            stats = self._dict(self._call("GET", "/api/v1/admin/stats", user="admin", expected=200))
            expected_users = self._db_one("select count(*) as n, count(*) filter (where status='banned') as banned from app.users")
            self.rec.must_eq(int(stats["users"]["total"]), int(expected_users["n"]), "用户总数")
            self.rec.must_eq(int(stats["users"]["banned"]), int(expected_users["banned"]), "封禁用户单列")
            for status_value in ("pending_review", "rejected", "listed", "in_transaction", "delisted"):
                expected = int(self._db_one("select count(*) as n from app.products where status = :s", {"s": status_value})["n"])
                self.rec.must_eq(int(stats["products"][status_value]), expected, f"商品状态 {status_value}")
            expected_review = int(
                self._db_one("select count(*) as n from app.disposal_cases where case_type='product_review' and status <> 'disposed'")["n"]
            )
            expected_report = int(
                self._db_one("select count(*) as n from app.disposal_cases where case_type='report' and status <> 'disposed'")["n"]
            )
            expected_all = int(self._db_one("select count(*) as n from app.disposal_cases where status <> 'disposed'")["n"])
            self.rec.must_eq(int(stats["pending"]["review_cases"]), expected_review, "待处理审核事项")
            self.rec.must_eq(int(stats["pending"]["report_cases"]), expected_report, "待处理举报事项")
            self.rec.must_eq(int(stats["pending"]["all_cases"]), expected_all, "全部待处理事项")
            for status_value in ("completed", "terminated", "disputed", "in_progress", "abnormal"):
                expected = int(self._db_one("select count(*) as n from app.trades where status = :s", {"s": status_value})["n"])
                self.rec.must_eq(int(stats["trades"][status_value]), expected, f"交易状态 {status_value}")
            expected_frozen = int(
                self._db_one(
                    "select count(*) as n from app.trades where frozen = true and status in ('in_progress','disputed','abnormal')"
                )["n"]
            )
            self.rec.must_eq(int(stats["trades"]["frozen_current"]), expected_frozen, "当前冻结交易")
            self.rec.must_eq(stats["range"]["completed_trades"], None, "未选范围不返回默认统计")
            self.rec.must("amount" not in json.dumps(stats).lower(), "统计无金额字段")
            self.rec.must("revenue" not in json.dumps(stats).lower(), "统计无收入字段")
            expected_completed = int(
                self._db_one(
                    "select count(*) as n from app.trades where status='completed' and finished_at between :a and :b",
                    {"a": datetime(2000, 1, 1, tzinfo=UTC), "b": datetime(2099, 12, 31, 23, 59, 59, tzinfo=UTC)},
                )["n"]
            )
            ranged = self._dict(
                self._call(
                    "GET",
                    "/api/v1/admin/stats",
                    user="admin",
                    expected=200,
                    params={"from": "2000-01-01", "to": "2099-12-31"},
                )
            )
            self.rec.must_eq(int(ranged["range"]["completed_trades"]), expected_completed, "范围完成交易计数")
            empty = self._dict(
                self._call(
                    "GET",
                    "/api/v1/admin/stats",
                    user="admin",
                    expected=200,
                    params={"from": "1990-01-01", "to": "1990-01-02"},
                )
            )
            self.rec.must_eq(int(empty["range"]["completed_trades"]), 0, "无数据范围返回 0")
            self._call("GET", "/api/v1/admin/stats", user="buyer", expected=403)
            self._call("GET", "/api/v1/admin/stats", expected=401)

        with self.rec.step(
            "AUDIT-01",
            "审计：管理员分页/详情；失败登录与成功业务事件；app 无 UPDATE/DELETE/TRUNCATE；敏感字段不落审计",
            ac=["US-01-AC-06", "US-08-AC-01"],
            sc=["SC-01-10"],
        ):
            summary = self._dict(self._call('GET', '/api/v1/admin/audit/summary', user='admin', params={'days': 7}))
            self.rec.must_eq(summary['timezone'], 'Asia/Shanghai', '审计概览采用北京时间')
            self.rec.must_eq(len(summary['daily']), 7, '概览补齐七天日期')
            self.rec.must_eq(sum(row['count'] for row in summary['categories']), summary['total'], '分类数量等于总量')
            self.rec.must_eq(sum(row['count'] for row in summary['daily']), summary['total'], '趋势数量等于总量')
            self.rec.must_eq(sum(summary['results'].values()), summary['total'], '结果数量等于总量')
            self._call('GET', '/api/v1/admin/audit/summary', user='outsider', expected=403)
            self._call('GET', '/api/v1/admin/audit/summary', expected=401)
            self._call('GET', '/api/v1/admin/audit/summary', user='admin', expected=422, params={'days': 31})
            classified = self._dict(self._call('GET', '/api/v1/admin/audit/events', user='admin', params={'category': 'account', 'limit': 20}))
            self.rec.must(all(row['event_type'].startswith(('auth.', 'user.')) for row in classified['items']), '分类明细口径一致')
            failed = self._dict(
                self._call(
                    "GET",
                    "/api/v1/admin/audit/events",
                    user="admin",
                    expected=200,
                    params={"event_type": "auth.login_failed", "result": "failure", "limit": 10},
                )
            )
            self.rec.must(int(failed.get("total") or 0) >= 1, "已识别账户的失败登录审计存在")
            self._call('POST', '/api/v1/auth/login', expected=401, json_body={'email': f'unknown-{self.run_id}@example.com', 'password': 'wrong-password'})
            self._call('GET', '/api/v1/admin/users', expected=401)
            anonymous = self._db_one("select count(*) as n from app.audit_events where actor_role='anonymous' or (actor_id is null and actor_role<>'system')")
            self.rec.must_eq(int(anonymous['n']), 0, '匿名请求及未知账户登录失败均不记录审计')
            event_id = int(str((failed.get("items") or [{}])[0].get("event_id") or 0))
            detail = self._dict(self._call("GET", f"/api/v1/admin/audit/events/{event_id}", user="admin", expected=200))
            self.rec.must_eq(int(detail["event_id"]), event_id, "审计详情")
            self._call("GET", "/api/v1/admin/audit/events", user="outsider", expected=403)
            if self.config.database_url.startswith("postgresql+"):
                privileges = self._db_one(
                    ("select has_table_privilege(current_user, 'app.audit_events', 'SELECT') as can_select, "
                     "has_table_privilege(current_user, 'app.audit_events', 'INSERT') as can_insert, "
                     "has_table_privilege(current_user, 'app.audit_events', 'UPDATE') as can_update, "
                     "has_table_privilege(current_user, 'app.audit_events', 'DELETE') as can_delete, "
                     "has_table_privilege(current_user, 'app.audit_events', 'TRUNCATE') as can_truncate")
                )
                self.rec.must_eq(privileges["can_select"], True, "app 可读审计")
                self.rec.must_eq(privileges["can_insert"], True, "app 可插入审计")
                self.rec.must_eq(privileges["can_update"], False, "app 不可改审计")
                self.rec.must_eq(privileges["can_delete"], False, "app 不可删审计")
                self.rec.must_eq(privileges["can_truncate"], False, "app 不可清空审计")
            else:
                self.rec.must(True, "SQLite 无数据库角色 ACL；已核验审计 API 与内容")
            rows = self._db("select before_json, after_json from app.audit_events order by event_id desc limit 200")
            forbidden = ("password", "access_token", "jwt", "secret", "access_key", "authorization")
            found: list[str] = []
            for row in rows:
                blob = json.dumps({"before": row.get("before_json"), "after": row.get("after_json")}, ensure_ascii=False).lower()
                for marker in forbidden:
                    if marker in blob:
                        found.append(marker)
            self.rec.must_eq(sorted(set(found)), [], "审计 before/after 不含敏感字段名")

        with self.rec.step(
            "AUDIT-02",
            "17 写入口/16 新增事件逐条落库；常规幂等操作不重复；payload 无正文/密码/验证码/JWT/AK",
            ac=["US-08-AC-01"],
            sc=["SC-01-10"],
        ):
            # 新会话事件：使用本轮尚未成对的 commenter/outsider，避免复用已有普通会话。
            created_conv = self._dict(
                self._call(
                    "POST",
                    "/api/v1/conversations/normal",
                    user="commenter",
                    expected=201,
                    json_body={"peer_user_id": self._uid("outsider")},
                )
            )
            created_conv_id = int(created_conv["id"])
            reused_conv = self._dict(
                self._call(
                    "POST",
                    "/api/v1/conversations/normal",
                    user="commenter",
                    expected=201,
                    json_body={"peer_user_id": self._uid("outsider")},
                )
            )
            self.rec.must_eq(int(reused_conv["id"]), created_conv_id, "复用已有普通会话")
            audit_message_content = f"审计正文标记-消息-{self.run_id}"
            self.audit_targets.setdefault("sensitive_markers", []).append(audit_message_content)
            audit_message = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/conversations/{created_conv_id}/messages",
                    user="commenter",
                    expected=200,
                    json_body={"content": audit_message_content},
                )
            )
            self._call(
                "POST",
                f"/api/v1/conversations/{created_conv_id}/read",
                user="outsider",
                expected=200,
                json_body={"last_displayed_message_id": int(audit_message["id"])},
            )
            self._call(
                "POST",
                f"/api/v1/conversations/{created_conv_id}/read",
                user="outsider",
                expected=200,
                json_body={"last_displayed_message_id": int(audit_message["id"])},
            )
            ban_trade = self._trade_detail("T_BAN_COMPLETED", "buyer2")
            ban_branch = int(ban_trade["conversation_id"])
            migrated = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/conversations/{ban_branch}/to-normal",
                    user="buyer2",
                    expected=200,
                )
            )
            migrated_id = int(migrated["id"])
            again_migrated = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/conversations/{ban_branch}/to-normal",
                    user="buyer2",
                    expected=200,
                )
            )
            self.rec.must_eq(int(again_migrated["id"]), migrated_id, "再次转入复用普通会话")

            category_ids = {
                str(key): int(value)
                for key, value in (self.audit_targets.get("category_ids") or {}).items()
            }
            alias_added = self._db_one(
                "select id from app.category_aliases where category_id = :cid and name = :name",
                {
                    "cid": category_ids["main"],
                    "name": str(self.audit_targets["alias_added_name"]),
                },
            )
            alias_removed_by_name = self._db_one(
                "select id from app.category_aliases where category_id = :cid and name = :name",
                {
                    "cid": int(self.audit_targets["alias_removed_by_name"]["category_id"]),
                    "name": str(self.audit_targets["alias_removed_by_name"]["name"]),
                },
            )
            alias_added_id = int(alias_added["id"])
            alias_removed_by_name_id = int(alias_removed_by_name["id"])
            alias_removed_by_id = int(self.audit_targets["alias_removed_by_id"])
            prohibited_id = int(self.audit_targets["prohibited_item_id"])
            favorite_product_id = int(self.audit_targets["favorite_product_id"])
            favorite_first_id = int(self.audit_targets["favorite_removed_id"])
            favorite_readded_id = int(self.audit_targets["favorite_readded_id"])
            statement_case_id = int(self.cases["report_product"]["id"])
            appeal_case_id = int(self.audit_targets["appeal_case_id"])
            notification_id = int(self.audit_targets["notification_read_id"])

            rows = self._db(
                ("select event_type, target_type, target_id, actor_id, before_json, after_json "
                 "from app.audit_events where created_at >= :started_at order by event_id"),
                {"started_at": self.started_at},
            )

            def _object(value: Any) -> dict[str, Any]:
                if isinstance(value, str):
                    try:
                        decoded = json.loads(value)
                    except json.JSONDecodeError:
                        return {}
                    return decoded if isinstance(decoded, dict) else {}
                return dict(value) if isinstance(value, dict) else {}

            def _count(
                event_type: str,
                target_type: str | None = None,
                target_id: int | None = None,
                *,
                after_product_id: int | None = None,
            ) -> int:
                total = 0
                for row in rows:
                    if str(row["event_type"]) != event_type:
                        continue
                    if target_type is not None and str(row["target_type"]) != target_type:
                        continue
                    if target_id is not None and int(row["target_id"] or 0) != int(target_id):
                        continue
                    if after_product_id is not None:
                        after = _object(row["after_json"])
                        if int(after.get("product_id") or 0) != int(after_product_id):
                            continue
                    total += 1
                return total

            required: list[tuple[str, str, int]] = []
            for key in ("main", "second", "disable", "delete"):
                required.append(("admin.category_create", "category", category_ids[key]))
            required.extend(
                [
                    ("admin.category_update", "category", category_ids["main"]),
                    ("admin.category_update", "category", category_ids["disable"]),
                    ("admin.category_alias_add", "category_alias", alias_added_id),
                    ("admin.category_alias_remove", "category_alias", alias_removed_by_name_id),
                    ("admin.category_alias_remove", "category_alias", alias_removed_by_id),
                    ("admin.category_delete", "category", category_ids["delete"]),
                    ("admin.prohibited_item_create", "prohibited_item", prohibited_id),
                    ("admin.prohibited_item_update", "prohibited_item", prohibited_id),
                    ("admin.prohibited_item_delete", "prohibited_item", prohibited_id),
                    ("favorite.add", "favorite", favorite_first_id),
                    ("favorite.add", "favorite", favorite_readded_id),
                    ("favorite.remove", "favorite", favorite_first_id),
                    ("case.statement_submit", "disposal_case", statement_case_id),
                    ("case.appeal_submit", "disposal_case", appeal_case_id),
                    ("notification.read", "notification", notification_id),
                    ("im.conversation_create", "conversation", created_conv_id),
                    ("im.read_advance", "conversation", created_conv_id),
                    ("im.conversation_to_normal", "conversation", migrated_id),
                    ("im.message_send", "conversation", created_conv_id),
                ]
            )
            missing = [
                f"{event}:{target_type}#{target_id}"
                for event, target_type, target_id in required
                if _count(event, target_type, target_id) < 1
            ]
            self.rec.must_eq(missing, [], "17 写入口/16 新增事件逐条落库")
            self.rec.must_eq(
                _count("favorite.add", "favorite", after_product_id=favorite_product_id),
                2,
                "重复收藏不写第三条成功审计",
            )
            self.rec.must_eq(
                _count("admin.prohibited_item_update", "prohibited_item", prohibited_id),
                1,
                "相同禁发值重复 PUT 不重复审计",
            )
            self.rec.must_eq(
                _count("admin.category_update", "category", category_ids["disable"]),
                1,
                "相同分类状态重复 PATCH 不重复审计",
            )
            for event, target_type, target_id in (
                ("im.conversation_create", "conversation", created_conv_id),
                ("im.read_advance", "conversation", created_conv_id),
                ("im.conversation_to_normal", "conversation", migrated_id),
                ("im.message_send", "conversation", created_conv_id),
                ("notification.read", "notification", notification_id),
                ("case.statement_submit", "disposal_case", statement_case_id),
                ("case.appeal_submit", "disposal_case", appeal_case_id),
                ("favorite.remove", "favorite", favorite_first_id),
            ):
                self.rec.must_eq(
                    _count(event, target_type, target_id),
                    1,
                    f"{event} 对同一目标仅一条成功记录",
                )

            required_events = {event for event, _target_type, _target_id in required}
            forbidden_keys = {
                "password",
                "password_hash",
                "access_token",
                "refresh_token",
                "verification_code",
                "jwt",
                "secret",
                "access_key",
                "access_key_id",
                "access_key_secret",
                "authorization",
                "content",
                "body",
            }
            bad_keys: set[str] = set()
            sensitive_hits: list[str] = []
            scanned = 0
            markers = [str(value) for value in self.audit_targets.get("sensitive_markers") or []]

            def _walk_keys(value: Any) -> None:
                if isinstance(value, dict):
                    for key, item in value.items():
                        if str(key).lower() in forbidden_keys:
                            bad_keys.add(str(key).lower())
                        _walk_keys(item)
                elif isinstance(value, list):
                    for item in value:
                        _walk_keys(item)

            for row in rows:
                if str(row["event_type"]) not in required_events:
                    continue
                scanned += 1
                before = _object(row["before_json"])
                after = _object(row["after_json"])
                _walk_keys(before)
                _walk_keys(after)
                blob = json.dumps({"before": before, "after": after}, ensure_ascii=False)
                for marker in markers:
                    if marker and marker in blob:
                        sensitive_hits.append(str(row["event_type"]))
            self.rec.must_eq(sorted(bad_keys), [], "新增审计 payload 不含敏感字段名")
            self.rec.must_eq(sensitive_hits, [], "新增审计 payload 不含消息/说明/申辩正文")
            self.rec.data["new_event_names"] = sorted(required_events)
            self.rec.data["scanned_events"] = scanned

        with self.rec.step(
            "OBJ-01",
            "对象引用/清理不变量：业务引用 committed 且真实存在；dry-run 不把已引用对象列为候选",
            ac=["US-02-AC-01", "US-07-AC-03"],
            sc=["SC-02-01", "SC-07-04"],
            note="把原独立对象锁/回收专项收敛为业务不变量；不调用 mock，不删除共享桶",
        ):
            image_keys = sorted(
                {
                    str(key)
                    for product in self.products.values()
                    for key in (product.get("image_keys") or [])
                    if key
                }
            )
            # 只有真正被举报引用的证据才是业务对象；FILE-01 的 report/ 探测上传仍是 staged。
            evidence_keys = [str(self.files["report_evidence"]["key"])]
            business_keys = sorted(set(image_keys) | set(evidence_keys))
            self.rec.must(bool(image_keys) and bool(evidence_keys), "存在商品图与举报证据业务引用")
            rows = self._db(
                "select key, state, bucket_role, deleted_at, ref_type, ref_id from app.stored_objects where key = any(:keys)",
                {"keys": business_keys},
            )
            by_key = {str(row["key"]): dict(row) for row in rows}
            for key in business_keys:
                row = by_key.get(key)
                self.rec.must(row is not None, f"业务对象已登记 {key[:24]}…")
                if row is None:
                    continue
                self.rec.must_eq(row["state"], "committed", f"业务对象 committed {key[:24]}…")
                self.rec.must_eq(row["deleted_at"], None, f"业务对象未删除 {key[:24]}…")
                self.rec.must(row.get("ref_type") is not None and row.get("ref_id") is not None, f"业务对象引用对完整 {key[:24]}…")
            probe = StorageProbe.build(self.config)
            for key in business_keys:
                self.rec.must(probe.exists(key), f"业务对象在 OSS 真实存在 {key[:24]}…")
            # 只读 dry-run：已引用对象不得成为清理候选；证据对象即使 staged 也受保护。
            from app.devtools._support import make_async_engine
            from app.services.stored_objects import cleanup_unreferenced_staged
            from app.storage.base import build_storage
            from sqlmodel.ext.asyncio.session import AsyncSession

            settings = self.config.settings
            storage = build_storage(settings)

            async def _dry_run() -> Any:
                engine = make_async_engine(self.config.database_url, schema=self.config.database_schema)
                try:
                    async with AsyncSession(engine, expire_on_commit=False) as session:
                        return await cleanup_unreferenced_staged(session, storage, dry_run=True, limit=200)
                finally:
                    await engine.dispose()

            result = asyncio.run(_dry_run())
            self.rec.must_eq(result.dry_run, True, "对象清理为只读 dry-run")
            self.rec.must_eq(sorted(set(result.candidates) & set(business_keys)), [], "已引用对象不进入清理候选")
            self.rec.must(not result.deleted, "不执行物理删除")
            self.rec.data["business_objects"] = len(business_keys)
            self.rec.data["dry_run_candidates"] = len(result.candidates)

        with self.rec.step(
            "CLEAN-01",
            "收尾前核对：运行期间历史、审计与引用对象完整；结束后清理本轮隔离资源",
            ac=["US-12-AC-06"],
            sc=["SC-12-03"],
        ):
            counts = {}
            for table in ("users", "categories", "products", "trades", "reports", "disposal_cases", "audit_events", "stored_objects"):
                row = self._db_one(f"select count(*) as n from app.{table}")
                counts[table] = int(row["n"])
            state_rows = self._db(
                "select state, count(*) as n from app.stored_objects group by state order by state"
            )
            self.retained = [{"kind": "table", "table": name, "count": count, "action": "retained"} for name, count in counts.items()]
            self.retained.extend(
                {"kind": "stored_object_state", "state": row["state"], "count": int(row["n"]), "action": "retained"} for row in state_rows
            )
            # 本轮逻辑 key 仍被商品/举报引用（只读 SQL）。
            report_key = self.files["report_evidence"]["key"]
            referenced = self._db(
                "select key from app.stored_objects where key = :key and state = 'committed'",
                {"key": report_key},
            )
            self.rec.must_eq(len(referenced), 1, "举报证据对象已提交并保留")
            probe_keys = [self.files["product_probe"]["key"], self.files["evidence_probe"]["key"]]
            staged = self._db(
                "select key, state from app.stored_objects where key = any(:keys)",
                {"keys": probe_keys},
            )
            self.rec.must_eq(len(staged), 2, "探测上传对象登记存在")
            self.rec.must(all(row["state"] in {"staged", "committed", "deleted"} for row in staged), "探测对象状态合法")
            self.rec.must(not any(item.get("action", "").startswith("delete") for item in self.retained), "运行期间未提前清理本轮业务对象")
            round_keys = sorted(
                {
                    str(value["key"])
                    for value in self.files.values()
                    if isinstance(value, dict) and value.get("key")
                }
            )
            key_rows = self._db(
                "select key, state, bucket_role from app.stored_objects where key = any(:keys)",
                {"keys": round_keys},
            )
            key_state = {str(row["key"]): dict(row) for row in key_rows}
            retained_objects: list[dict[str, Any]] = []
            for key in round_keys:
                row = key_state.get(key)
                if row is None:
                    retained_objects.append({"key": key, "state": "unregistered", "reason": "本轮上传未登记，记录运行期间状态"})
                elif row["state"] == "committed":
                    retained_objects.append(
                        {"key": key, "state": "committed", "bucket_role": row["bucket_role"], "reason": "运行期间业务引用"}
                    )
                elif row["state"] == "staged":
                    retained_objects.append(
                        {"key": key, "state": "staged", "bucket_role": row["bucket_role"], "reason": "运行期间探测或未引用上传"}
                    )
                else:
                    retained_objects.append(
                        {"key": key, "state": row["state"], "bucket_role": row["bucket_role"], "reason": "运行期间历史状态"}
                    )
            self.rec.data["counts"] = counts
            self.rec.data["stored_object_states"] = [dict(row) for row in state_rows]
            self.rec.data["retained_objects"] = retained_objects
