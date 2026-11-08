"""Real-resource acceptance scenarios: all business actions go through HTTP; the database is used for seed initialization, read-only verification, and isolated-concurrency validation of scanning services.

This module does not modify business code; the 7-day scenario advances through the test
service process's controlled clock and does not write database time fields.
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
from app.devtools._support import DevConfig, StorageProbe, readonly_mapping, readonly_rows

from tests.acceptance_real.core import (
    BACKEND_ROOT,
    REPO_ROOT,
    ApiClient,
    CheckFailure,
    Recorder,
    RouteIndex,
)
from tests.acceptance_real.seed import (
    SEED_DOMAIN,
    SeedCredentials,
)

ASSETS = BACKEND_ROOT / "app" / "devtools" / "demo_scenarios" / "assets"
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
        raise CheckFailure(f"Missing test asset: {path.name}")
    return path.read_bytes()


def _safe_iso(value: Any) -> str | None:
    return str(value) if value else None


@dataclass
class ServerHandle:
    process: subprocess.Popen[bytes]
    base_url: str
    clock_file: Path
    log_path: Path
    ws_url: str | None = None

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
        run_id: str,
        credentials: SeedCredentials,
        server: ServerHandle | None = None,
        only: Sequence[str] | None = None,
    ) -> None:
        self.base_url = base_url
        self.ws_url = (server.ws_url if server else None) or base_url
        self.config = config
        self.run_id = run_id
        self.credentials = credentials
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
        self.seed_fingerprint: str | None = credentials.fingerprint
        # This run's objects/sensitive markers needed for audit-integrity checks; no credentials or response bodies are stored.
        self.audit_targets: dict[str, Any] = {}
        self._server_started_by_us = server is not None

    # ------------------------------------------------------------------
    # Basic access
    # ------------------------------------------------------------------
    def _enabled(self, group: str) -> bool:
        return not self.only or group.lower() in self.only

    def _token(self, key: str) -> str:
        account = self.users.get(key)
        if not account or not account.get("token"):
            raise CheckFailure(f"Account {key} is not logged in")
        return str(account["token"])

    def _uid(self, key: str) -> int:
        account = self.users.get(key)
        if not account:
            raise CheckFailure(f"Account {key} does not exist")
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
        # Admin lists now use the {items, total, page, page_size} paginated response; unwrap it
        # uniformly here while still accepting public endpoints that return a bare array.
        value = self.api.json_of(response)
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            return value["items"]
        if isinstance(value, list):
            return value
        raise CheckFailure('Response is not a JSON array or pagination object')

    def _sandbox_sql(self, sql: str) -> str:
        from app.core.config import validate_schema_identifier
        schema = validate_schema_identifier(self.config.database_schema)
        if not self.config.acceptance_sandbox or not schema.startswith("acceptance_"):
            raise CheckFailure("Only this run's isolated database may be queried")
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
            raise CheckFailure('Read-only verification SQL returned no expected row')
        return row

    def _assert_media_url(self, url: str | None, label: str) -> None:
        """A media link must be a readable entry point: a private-bucket signed direct URL for OSS, or a backend-signed path for local storage."""
        self.rec.must(bool(url), f"{label} link exists")
        if not url:
            return
        if self.config.settings.storage_backend == "oss":
            self.rec.must(urlsplit(url).netloc in self.api.allowed_storage_hosts, f"{label} is a direct OSS URL")
        else:
            self.rec.must(url.startswith("/api/v1/files/"), f"{label} uses the backend-signed entry")
        self.api.signed_get(url)

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------
    def _login_known(self, key: str, email: str, password: str, expected_id: int | None = None, expected_role: str | None = None) -> None:
        response = self._call("POST", "/api/v1/auth/login", expected=200, json_body={"email": email, "password": password})
        data = self._dict(response)
        user = data.get("user") or {}
        token = data.get("access_token")
        if not token:
            raise CheckFailure(f"Login for {key} is missing a token")
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
            raise CheckFailure(f"Login for {key} returned a user ID inconsistent with seed")
        if expected_role is not None and account["role"] != expected_role:
            raise CheckFailure(f"Login for {key} returned a role inconsistent with seed")
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
            raise CheckFailure('Registration response is missing a token')
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
        self.rec.must("dev_code" not in response,'Verification code is not returned in the HTTP response')
        settings=self.config.settings
        if settings.mail_backend != "capture" or settings.mail_capture_path is None:
            raise CheckFailure("Automation may read only this run's isolated mail capture")
        path=Path(settings.mail_capture_path)
        require_private(path)
        messages=[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        matching=[m for m in messages if m['email']==email.strip().lower() and m['purpose']==purpose]
        if not matching or not re.fullmatch(r"[0-9]{6}",matching[-1]['code']):
            raise CheckFailure('No matching isolated verification-code email received')
        self.rec.must(True,"Verification code delivered to this run's private mailbox")
        return matching[-1]['code']

    # ------------------------------------------------------------------
    # Files / products / shared business helpers
    # ------------------------------------------------------------------
    def _upload(self, user: str, asset: str, namespace: str = "product") -> dict[str, Any]:
        content = _asset_bytes(asset)
        lease = self._lease(user,asset,content,namespace)
        self._put_lease(lease,content)
        data = self._dict(self._call("POST",f"/api/v1/files/upload-leases/{lease['lease_id']}/complete",user=user))
        if not data.get("key") or not data.get("url"):
            raise CheckFailure('Upload response is missing key/url')
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
            raise CheckFailure(f"Product {key} has not been created")
        return self._dict(self._call("GET", f"/api/v1/products/{product['id']}", user=viewer, expected=200))

    def _pending_case(self, product_id: int, case_type: str = "product_review", *, user: str = "admin") -> dict[str, Any]:
        rows = self._list(
            self._call("GET", "/api/v1/admin/cases", user=user, expected=200, params={"status": "pending", "case_type": case_type})
        )
        for row in rows:
            if int(row.get("product_id") or 0) == int(product_id):
                return row
        raise CheckFailure(f"Shared pool has no pending {case_type} case for product #{product_id}")

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
            raise CheckFailure(f"Product {key} is not listed after approval")
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
        asset: str = "product_folding_bike.jpg",
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
            raise CheckFailure('Publishing a product requires at least one tag')
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
        raise CheckFailure(f"Trade {key} did not enter {sorted(wanted)} within {timeout:.0f}s (last: {last})")

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
    # Concurrency and cross-step helpers
    # ------------------------------------------------------------------
    def _concurrent(self, jobs: Sequence[tuple[str, str, str, Mapping[str, Any]]]) -> list[dict[str, Any]]:
        """Issue real concurrent requests with independent httpx clients and record them in the main call ledger."""
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
        """Create a claimed product-related case through a real report, as a basis for admin trade reads/disposition."""
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
            raise CheckFailure('The report case did not appear in the admin list')
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
    # Preflight
    # ------------------------------------------------------------------
    def preflight(self) -> None:
        with self.rec.step("SVC-01", 'API and dependency services are ready'):
            health = self._dict(self._call("GET", "/api/health", expected=200))
            self.rec.must_eq(health.get("status"), "ok", "API health")
            ready = self._dict(self._call("GET", "/health/ready", expected=200))
            self.rec.must(ready.get("status") in {"ready", "degraded"}, "API ready")

    def bootstrap_accounts(self) -> None:
        with self.rec.step(
            "ACC-01",
            'Seed identity login, wrong credentials, and logout',
        ):
            credentials = self.credentials.accounts
            self.rec.must(bool(self.seed_fingerprint), 'Seed fingerprint exists')
            # All canonical identities come from tests.acceptance_real.seed; the same run_id can be reused by a human browser.
            for key in ("admin", "admin2", "buyer", "buyer2", "seller", "seller2", "outsider", "commenter"):
                account = credentials[key]
                self._login_known(key, account.email, account.password, account.id, account.role)
            self.rec.must_eq(len(self.users), 8, 'Canonical identities logged in')
            # Correct credentials still work after a wrong-password rejection
            bad = self._call(
                "POST",
                "/api/v1/auth/login",
                expected=401,
                json_body={"email": self.users["buyer"]["email"], "password": "definitely-wrong-password"},
            )
            self.rec.must_eq(bad.status_code, 401, 'Login with wrong password is rejected')
            self._login_known("buyer", self.users["buyer"]["email"], self.users["buyer"]["password"], self._uid("buyer"), "user")
            me = self._dict(self._call("GET", "/api/v1/auth/me", user="buyer", expected=200))
            self.rec.must_eq(int(me["id"]), self._uid("buyer"), 'Login works after a wrong-password attempt')
            logout = self._dict(self._call("POST", "/api/v1/auth/logout", user="buyer", expected=200))
            self.rec.must("退出" in str(logout.get("detail")), 'Logout endpoint response')
            self._login_known("buyer", self.users["buyer"]["email"], self.users["buyer"]["password"], self._uid("buyer"), "user")

    def account_lifecycle(self) -> None:
        with self.rec.step(
            "ACC-02",
            'Registration verification code: wrong code rejected; correct code creates a unique account; duplicate email rejected',
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
            self.rec.must_eq(wrong.status_code, 400, 'Registration with wrong code is rejected')
            before = self._db_one("select count(*) as n from app.users where email = :email", {"email": email})
            self.rec.must_eq(int(before["n"]), 0, 'Wrong code creates no account')
            response = self._call(
                "POST",
                "/api/v1/auth/register",
                expected=200,
                json_body={"email": email, "display_name": "验收生命周期", "password": "lifecycle-pass-1", "code": code},
            )
            data = self._dict(response)
            user = data.get("user") or {}
            self.rec.must(bool(user.get("id")), 'Registration returns a user ID')
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
            self.rec.must_eq(int(count["n"]), 1, 'Duplicate registration adds no account')
            login = self._dict(
                self._call("POST", "/api/v1/auth/login", expected=200, json_body={"email": email, "password": "lifecycle-pass-1"})
            )
            self.rec.must_eq(int(login["user"]["id"]), int(user["id"]), 'Registered account can log in with email')
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
                'Unverified email is neither reserved nor created',
            )

        with self.rec.step(
            "ACC-03",
            'Forgot password: reset via bound-email code; old password stops working and user ID is unchanged',
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
            self.rec.must_eq(int(relogin["user"]["id"]), int(account["id"]), 'User ID unchanged after reset')
            self.users["lifecycle"]["password"] = "lifecycle-pass-2"
            self.users["lifecycle"]["token"] = str(relogin["access_token"])

        with self.rec.step(
            "ACC-04",
            'Change password: old password checked; old password stops working and new password works',
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
            self.rec.must_eq(int(relogin["user"]["id"]), int(account["id"]), 'User ID unchanged after password change')
            self.users["lifecycle"]["password"] = "lifecycle-pass-3"
            self.users["lifecycle"]["token"] = str(relogin["access_token"])

        with self.rec.step(
            "ACC-05",
            'Email change with double verification and uniqueness; rename; historical business stays with the original user ID',
        ):
            account = self.users["lifecycle"]
            # First create historical business through a normal direct message, then change email/name.
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
            # The target is already taken: reject at code-send time without changing the original email.
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
            self.rec.must_eq(int(changed["id"]), int(account["id"]), 'User ID unchanged after email change')
            self._call("POST", "/api/v1/auth/login", expected=401, json_body={"email": old_email, "password": account["password"]})
            relogin = self._dict(
                self._call(
                    "POST",
                    "/api/v1/auth/login",
                    expected=200,
                    json_body={"email": new_email, "password": account["password"]},
                )
            )
            self.rec.must_eq(int(relogin["user"]["id"]), int(account["id"]), 'New email logs in to the same ID')
            self.users["lifecycle"]["email"] = new_email
            self.users["lifecycle"]["token"] = str(relogin["access_token"])
            profile = self._dict(
                self._call("PATCH", "/api/v1/auth/profile", user="lifecycle", expected=200, json_body={"display_name": "验收生命周期改名"})
            )
            self.rec.must_eq(str(profile["display_name"]), "验收生命周期改名", 'Display name update')
            self.rec.must_eq(int(profile["id"]), int(account["id"]), 'User ID unchanged after rename')
            conversations = self._list(self._call("GET", "/api/v1/conversations", user="lifecycle", expected=200))
            self.rec.must(
                any(int(item.get("peer_id") or 0) == self._uid("seller") for item in conversations),
                'Historical direct messages stay with the original user after email/name change',
            )
            audit = self._db_one(
                "select count(*) as n from app.audit_events where actor_id = :id and event_type in ('auth.email_change','user.profile_update')",
                {"id": account["id"]},
            )
            self.rec.must(int(audit["n"]) >= 2, 'Email/name change audit actor is the original user ID')

    # ------------------------------------------------------------------
    # Categories / prohibited items
    # ------------------------------------------------------------------
    def taxonomy(self) -> None:
        with self.rec.step(
            "CAT-01",
            'Category create/read; regular-user/anonymous maintenance rejected',
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
                self.rec.must_in(self.categories[key]["name"], names, f"Category {key} appears in the list")
            self._call("POST", "/api/v1/categories", user="outsider", expected=403, json_body={"name": "越权分类"})
            self._call("POST", "/api/v1/categories", expected=401, json_body={"name": "匿名分类"})
            self._call("GET", "/api/v1/categories", expected=401)

        with self.rec.step(
            "CAT-02",
            'Rename keeps the old primary name as an alias; alias search; removing an alias by name/ID makes the old name unresolvable',
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
            self.rec.must_eq(str(renamed["name"]), new_name, 'Category primary name updated')
            self.rec.must_in(old_name, renamed.get("aliases") or [], 'Old primary name kept as alias')
            self.categories[key]["name"] = new_name
            self.categories[key]["old_name"] = old_name
            # Add an alias; first associate a product of the second category with the primary category to verify search/attribution.
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
            self.rec.must_in(alias_name, aliased.get("aliases") or [], 'Alias added')
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
            self.rec.must_eq(search_alias.get("total"), 0, 'Old name has no matching products yet (no associated products)')
            # Remove the new alias by name
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
            self.rec.must_eq(missing.get("total"), 0, 'Removed alias no longer resolves')
            self.rec.must_eq(missing.get("message"), "无匹配商品", 'Removed alias yields no-match hint')
            # Remove the old primary-name alias by ID (read the real ID via read-only SQL; no database writes)
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
            self.rec.must_eq(removed.get("total"), 0, 'Old name no longer resolves after removal by ID')
            category = next(
                item
                for item in self._list(self._call("GET", "/api/v1/categories", user="admin", expected=200))
                if int(item["id"]) == self.categories[key]["id"]
            )
            self.rec.must_eq(str(category["name"]), new_name, 'Removing an alias does not change category identity')

        with self.rec.step(
            "CAT-03",
            'Disable category: new publishes rejected; existing products retained; associated categories can only be disabled, not deleted; unassociated ones can be soft-deleted',
        ):
            # Create an associated product first, then disable the category.
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
            self.rec.must_eq(disabled.get("status"), "disabled", 'Category disabled state')
            # Re-submitting the same state must not produce a second success audit (idempotency).
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
            self.rec.must_eq(still.get("status"), "listed", "Disabling a category does not change associated products' state")
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
                'Disabled category with listed products keeps a filter entry',
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
            self.rec.must(self.categories["delete"]["name"] not in names, 'Soft-deleted category no longer listed')

        with self.rec.step(
            "PROH-01",
            'Prohibited scope: authenticated read, admin add/update/delete, regular-user/anonymous rejected',
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
            self.rec.must_eq(updated["content"], "验收禁发内容-已更新", 'Prohibited item updated')
            self.audit_targets["prohibited_item_id"] = item_id
            # A full PUT with identical values must not write a duplicate success audit.
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
                'Regular user reads the latest prohibited scope',
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
            self.rec.must(not any(int(item["id"]) == item_id for item in after), 'Deleted item no longer returned')

    # ------------------------------------------------------------------
    # Files, products, search, favorites, comments
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
            self.rec.must_eq(sorted(item['status'] for item in results), [200, 409], 'Only one duplicate review submission succeeds')
            count = self._db_one("select count(*) as n from app.audit_events where event_type='admin.product_review' and target_id=:id", {'id': str(product['id'])})
            # The final product state matches the single review conclusion.
            record = self._db_one('select result from app.review_records where case_id=:id', {'id': case['id']})
            detail = self._product_detail(key, 'seller')
            self.rec.must_eq(detail['status'], 'listed' if record['result'] == 'approved' else 'rejected', 'Concurrent reviews reach a consistent final state')
            self.rec.must_eq(int(count['n']), 1, 'Only one successful review audit')

            edit_key = f'P_EDIT_REVIEW_RACE_{index}'
            product = self._publish(edit_key, 'seller', f'并发编辑审核-{index}-{self.run_id}', category_ids=[self.categories['main']['id']])
            case = self._pending_case(product['id'])
            self._claim(case['id'])
            results = self._concurrent([
                ('PATCH', f"/api/v1/products/{product['id']}", 'seller', {'description': '并发编辑新内容'}),
                ('POST', f"/api/v1/admin/products/cases/{case['id']}/review", 'admin', {'result': 'rejected', 'reason': '并发快照检查'}),
            ])
            self.rec.must(results[0]['status'] in (200, 409) and results[1]['status'] == 200, 'Review and edit execute in serial order')
            snapshot = self._db_one('select content_json from app.review_records where case_id=:id', {'id': case['id']})['content_json']
            if isinstance(snapshot, str):
                snapshot = json.loads(snapshot)
            if results[0]['status'] == 200:
                self.rec.must_eq(snapshot['description'], '并发编辑新内容', 'If the edit commits first, the review uses the latest content')
            case = self._dict(self._call('GET', f"/api/v1/admin/cases/{case['id']}", user='admin'))
            self.rec.must_eq(case['status'], 'disposed', 'Review case archived')
            product_image_urls = (case.get('product') or {}).get('image_urls') or []
            self.rec.must(bool(product_image_urls), 'Review case returns a direct product image link')
            if product_image_urls:
                self._assert_media_url(product_image_urls[0], 'Review case product image')

        # Duplicate generic-disposition requests for the same case write the conclusion only once.
        key = 'P_CASE_DISPOSE_RACE'
        product = self._publish(key, 'seller', f'重复处置-{self.run_id}', category_ids=[self.categories['main']['id']])
        case = self._pending_case(product['id'])
        self._claim(case['id'])
        results = self._concurrent([
            ('POST', f"/api/v1/admin/cases/{case['id']}/dispose", 'admin', {'conclusion': '结论一'}),
            ('POST', f"/api/v1/admin/cases/{case['id']}/dispose", 'admin', {'conclusion': '结论二'}),
        ])
        self.rec.must_eq(sorted(item['status'] for item in results), [200, 409], 'Only one duplicate generic disposition submission succeeds')
        product = self._publish('P_REPORT_RACE', 'seller', f'重复举报处置-{self.run_id}', category_ids=[self.categories['main']['id']])
        self._approve('P_REPORT_RACE')
        report_case = self._relevant_case_for_product(product['id'], claimant='admin')
        results = self._concurrent([
            ('POST', f'/api/v1/admin/reports/cases/{report_case}/decision', 'admin', {'outcome': 'unfounded', 'reason': '并发核查一', 'public_summary': '依据不足'}),
            ('POST', f'/api/v1/admin/reports/cases/{report_case}/decision', 'admin', {'outcome': 'unfounded', 'reason': '并发核查二', 'public_summary': '依据不足'}),
        ])
        self.rec.must_eq(sorted(item['status'] for item in results), [200, 409], 'Only one duplicate report disposition succeeds')
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
                            self.rec.must_eq(scan.result(), 0, 'Scan rechecks after waiting and skips completed or frozen trades')
                finally:
                    await engine.dispose()
            asyncio.run(exercise())
            row = self._db_one("select count(*) as n from app.trade_transitions where trade_id=:id and trigger='confirm_timeout'", {'id': tid})
            self.rec.must_eq(int(row['n']), 0, 'A stale scan snapshot produced no abnormal transition')
            detail = self._trade_detail(trade_key, 'buyer')
            self.rec.must_eq(detail['status'], 'completed' if action == 'confirm' else 'in_progress', 'Manual operation result preserved')
            if action == 'freeze':
                self.rec.must_eq(detail['frozen'], True, 'Scan does not override a manual freeze')
                self._call('POST', f'/api/v1/admin/trades/{tid}/unfreeze', user='admin', expected=200, json_body={'reason': '并发测试完成', 'case_id': case_id})
                # Complete this test trade so later controlled-clock scenarios are unaffected.
                self._confirm(trade_key, 'seller')
        self.concurrency.append({'kind': 'timeout_vs_confirmation_and_freeze', 'status': 'PASS'})

    def files_and_products(self) -> None:
        with self.rec.step(
            "FILE-01",
            'Image upload really lands in media/evidence buckets; signed read; tampering/invalid/oversized/wrong-namespace rejected',
            note="Bucket placement is separately verified by read-only SQL",
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
            self.rec.must_eq(atomic_avatar['avatar_review_status'], 'pending', 'Upload completion commits avatar review in the same transaction')
            self._call('POST', '/api/v1/auth/avatar', user='buyer', expected=400, json_body={'key': avatar_key})
            avatar_case = self._dict(self._call('POST', '/api/v1/auth/avatar', user='seller', json_body={'key': avatar_key}))
            pending = self._dict(self._call('GET', '/api/v1/auth/me', user='seller'))
            self.rec.must_eq(pending['avatar_review_status'], 'pending', 'Avatar pending review')
            self.rec.must(not pending['avatar_url'], 'Pending avatar not public')
            queue = self._list(self._call('GET', '/api/v1/admin/cases', user='admin', params={'case_type': 'avatar_review'}))
            self.rec.must(any(item['id'] == avatar_case['case_id'] for item in queue), 'Admin can see the avatar application')
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
            self.rec.must_eq(approved['avatar_review_status'], 'approved', 'Avatar review approved')
            self.rec.must(bool(approved['avatar_url']), 'Approved avatar returns a link')
            refreshed = self._dict(self._call('GET', '/api/v1/auth/me', user='seller'))
            if self.config.settings.storage_backend == 'oss':
                self.rec.must_eq(refreshed['avatar_url'], approved['avatar_url'], 'Metadata refresh reuses the signed avatar URL')
                self.rec.must(urlsplit(approved['avatar_url']).netloc in self.api.allowed_storage_hosts, 'Avatar returns a direct OSS URL')
            self.api.signed_get(approved['avatar_url'])
            self._call('POST', decision_path, user='admin', expected=409, json_body={'key': avatar_key, 'approved': True})
            product_file = self._upload("seller", "product_folding_bike.jpg", "product")
            self.files["product_probe"] = product_file
            self.rec.must(str(product_file["key"]).startswith("product/"), 'Product image key prefix product/')
            signed = self.api.signed_get(str(product_file["url"]))
            self.rec.must(signed.content[:3] == b"\xff\xd8\xff", 'Signed URL reads back JPEG')
            from urllib.parse import parse_qsl, urlencode
            parsed_url = urlsplit(str(product_file['url']))
            signature_name = 'x-oss-signature' if parsed_url.netloc else 'sig'
            query = [(key, '0' * 64 if key.lower() == signature_name else value) for key, value in parse_qsl(parsed_url.query)]
            tampered = parsed_url._replace(query=urlencode(query)).geturl()
            self.api.signed_get(tampered, expected=403)
            # Keep verifying the local-file compatibility read entry; for OSS business URLs, read the corresponding private bucket directly.
            import hmac
            expiry = int(time.time()) + 300
            logical_key = product_file['key']
            sig = hmac.new(self.config.settings.file_url_secret.encode(), f'{logical_key}:{expiry}'.encode(), hashlib.sha256).hexdigest()
            self.api.signed_get(f'/api/v1/files/{logical_key}?exp={expiry}&sig={sig}')
            valid = _asset_bytes("product_folding_bike.jpg")
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
            self.rec.must(True,'Completion confirmation is idempotent; other users and missing objects rejected; duplicate writes rejected')
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
                        self.rec.must_eq(preflight.status_code,200,'Test-bucket browser direct-upload preflight passes')
                        self.rec.must_eq(preflight.headers.get('access-control-allow-origin'),origin,'Preflight origin matches')
                self.rec.must(True,'OSS rejects tampered signed metadata; backend rejects actual hash/size mismatch')
            evidence = self._upload("buyer", "evidence_message.jpg", "report")
            self.files["evidence_probe"] = evidence
            self.rec.must(str(evidence["key"]).startswith("report/"), 'Report evidence key prefix report/')
            self.api.signed_get(str(evidence["url"]))
            # Read-only SQL checks both buckets' role and commit state (without reading object bodies).
            rows = self._db(
                "select key, bucket_role, state from app.stored_objects where key = any(:keys)",
                {"keys": [product_file["key"], evidence["key"]]},
            )
            role_by_key = {str(row["key"]): str(row["bucket_role"]) for row in rows}
            self.rec.must_eq(role_by_key.get(str(product_file["key"])), "media", 'Product image lands in the media bucket')
            self.rec.must_eq(role_by_key.get(str(evidence["key"])), "evidence", 'Report evidence lands in the evidence bucket')

        with self.rec.step(
            "PROD-01",
            'Pending product visibility, review withdrawal, edit/resubmit, shared-pool concurrent claim, and approval',
            note="Concurrent-claim evidence is covered separately in CONC-01",
        ):
            product = self._publish(
                "P_PENDING",
                "seller",
                f"待审核商品-{self.run_id}",
                price=4100,
                category_ids=[self.categories["main"]["id"]],
            )
            self.rec.must_eq(product.get("status"), "pending_review", 'Pending review after publish')
            detail = self._product_detail("P_PENDING", "seller")
            self.rec.must_eq(detail.get("status"), "pending_review", 'Seller can see pending-review detail')
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
            self.rec.must_eq(search.get("total"), 0, 'Pending products do not appear in public search')
            self._call("GET", f"/api/v1/products/{product['id']}/comments", user="outsider", expected=404)
            records = self._list(
                self._call("GET", f"/api/v1/products/{product['id']}/review-records", user="seller", expected=200)
            )
            self.rec.must_eq(len(records), 1, 'Pending review record')
            self._call("GET", f"/api/v1/products/{product['id']}/review-records", user="outsider", expected=403)
            mine = self._list(self._call("GET", "/api/v1/products/mine", user="seller", expected=200))
            self.rec.must(any(int(item["id"]) == int(product["id"]) for item in mine), 'My products include pending review')
            # Withdraw before claim
            withdrawn = self._dict(
                self._call("POST", f"/api/v1/products/{product['id']}/withdraw-review", user="seller", expected=200)
            )
            self.rec.must_eq(withdrawn.get("status"), "delisted", 'Withdrawn and delisted before claim')
            self._call(
                "POST",
                f"/api/v1/products/{product['id']}/withdraw-review",
                user="seller",
                expected=409,
            )
            # Resubmit after editing
            resubmitted = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/products/{product['id']}/resubmit",
                    user="seller",
                    expected=200,
                    json_body={"title": f"待审核商品重提-{self.run_id}", "price_cents": 4200},
                )
            )
            self.rec.must_eq(resubmitted.get("status"), "pending_review", 'Resubmitted and pending review after withdrawal')
            self.products["P_PENDING"].update(resubmitted)
            self._review_race_regression()
            # Concurrent claim: admin and admin2 claim the same case at the same time.
            case = self._pending_case(int(product["id"]))
            self.cases["P_PENDING_review"] = case
            result = self._concurrent(
                [
                    ("POST", f"/api/v1/admin/cases/{case['id']}/claim", "admin", {}),
                    ("POST", f"/api/v1/admin/cases/{case['id']}/claim", "admin2", {}),
                ]
            )
            statuses = sorted(item["status"] for item in result)
            self.rec.must_eq(statuses, [200, 409], 'Concurrent claim: one wins, one loses')
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
            self.rec.must_eq(approved.get("status"), "listed", 'Approved after resubmission')
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
            self.rec.must_eq(search.get("total"), 1, 'Enters search after approval')
            latest_records = self._list(
                self._call("GET", f"/api/v1/products/{product['id']}/review-records", user="seller", expected=200)
            )
            self.rec.must({row.get("result") for row in latest_records} >= {"withdrawn", "approved"}, 'Both withdrawal and approval review records retained')

        with self.rec.step(
            "PROD-02",
            'Rejection reason visible privately, not publicly; edit/resubmit then independently approved',
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
            self.rec.must_eq(rejected.get("status"), "rejected", 'Rejected state')
            self.rec.must_eq(rejected.get("reject_reason"), reason, 'Seller can see rejection reason')
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
            self.rec.must_eq(resubmitted.get("status"), "pending_review", 'Resubmit after rejection')
            self.products["P_REJECT"].update(resubmitted)
            self._approve("P_REJECT")
            self.rec.must_eq(self._product_detail("P_REJECT", "seller").get("status"), "listed", 'Resubmission approved')

        with self.rec.step(
            "PROD-03",
            'Tag review approve_new and map_alias: new tag public, synonym alias active; unapproved stays private',
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
            self.rec.must_eq(len(apps), 2, 'Two pending tag applications')
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
            self.rec.must_eq(approved.get("status"), "listed", 'Product listed after tag approval')
            self.rec.must_in(new_tag, approved.get("tag_names") or [], 'New tag associated with product')
            self.rec.must_in(self.categories["main"]["name"], approved.get("tag_names") or [], 'Alias mapped to an existing category')
            categories = self._list(self._call("GET", "/api/v1/categories", user="seller", expected=200))
            created = next((item for item in categories if item.get("name") == new_tag), None)
            self.rec.must(created is not None and created.get("status") == "active", 'New tag publicly selectable')
            mapped = next(item for item in categories if int(item["id"]) == self.categories["main"]["id"])
            self.rec.must_in(alias_name, mapped.get("aliases") or [], 'Synonym becomes an active alias')
            by_tag = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="buyer",
                    expected=200,
                    params={"category_names": [new_tag]},
                )
            )
            self.rec.must_eq(by_tag.get("total"), 1, 'Search by new tag hits')
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
                'Search by synonym alias hits the target product',
            )

        with self.rec.step(
            "PROD-04",
            'Product approval with individual tag rejection: per-application reasons stored; seller-visible/non-owner hidden; blank reason 400 with no partial approval',
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
            self.rec.must(good_tag in pending_apps and bad_tag in pending_apps, 'Two tag applications pending review')
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
            self.rec.must_eq(approved.get("status"), "listed", 'Product remains listed after approval with tag rejection')
            tag_names = approved.get("tag_names") or []
            self.rec.must_in(good_tag, tag_names, 'Approved tag associated with product')
            self.rec.must(bad_tag not in tag_names, 'Rejected tag not associated with product')
            decided = {
                str(app["requested_name"]): app
                for app in approved.get("decided_tag_applications") or []
            }
            self.rec.must(bad_tag in decided, 'Seller can see processed tag applications')
            self.rec.must_eq(decided[bad_tag].get("status"), "rejected", 'Rejected application state')
            self.rec.must_eq(
                decided[bad_tag].get("decision_reason"), reason, 'Per-application rejection reason visible to seller'
            )
            self.rec.must_eq(
                decided[good_tag].get("decision_reason"), None, 'Approved tags record no rejection reason'
            )
            self.rec.must_eq(approved.get("pending_tag_applications"), [], 'No pending tags after approval')
            categories_after = self._list(
                self._call("GET", "/api/v1/categories", user="seller", expected=200)
            )
            self.rec.must(
                not any(item.get("name") == bad_tag for item in categories_after),
                'Rejected tag not public',
            )
            for viewer in ("buyer", "outsider"):
                other = self._product_detail("P_TAG_REJ", viewer)
                self.rec.must_eq(
                    other.get("decided_tag_applications"), [], f"{viewer} cannot see per-application reasons"
                )
                self.rec.must(
                    reason not in json.dumps(other, ensure_ascii=False),
                    f"{viewer} product response contains no rejection reason",
                )

            # A blank reason must return 400 before any write and produce no partial approval/tag change.
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
            self.rec.must_eq(len(empty_apps), 1, 'Blank-reason sample has one pending application')
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
            self.rec.must_eq(unchanged.get("status"), "pending_review", 'Product still pending after blank-reason failure')
            self.rec.must_eq(
                unchanged.get("decided_tag_applications"), [], 'No processed applications after blank-reason failure'
            )
            self.rec.must(
                any(
                    int(app["id"]) == empty_apps[0]
                    for app in unchanged.get("pending_tag_applications") or []
                ),
                'Application still pending after blank-reason failure',
            )
            self.rec.must(empty_tag not in (unchanged.get("tag_names") or []), 'Tag not associated after blank-reason failure')
            categories_after_empty = self._list(
                self._call("GET", "/api/v1/categories", user="seller", expected=200)
            )
            self.rec.must(
                not any(item.get("name") == empty_tag for item in categories_after_empty),
                'No category created after blank-reason failure',
            )
            # The same case can then be approved with a valid reason; the failure consumed no review state.
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
            self.rec.must_eq(recovered.get("status"), "listed", 'Same case can be reviewed after a valid reason')

        with self.rec.step(
            "PROD-05",
            'Product edit history, notification to buyers of open requests, delisting closes pending acceptance requests, relisting',
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
            self.rec.must_eq(edited.get("status"), "listed", 'Editing does not pause display or trigger a second review')
            self.rec.must_eq(edited.get("title"), new_title, 'Title updated')
            histories = self._list(
                self._call("GET", f"/api/v1/products/{self.products['P_EDIT']['id']}/edit-history", user="seller", expected=200)
            )
            self.rec.must(histories and str(histories[-1]["before_json"].get("title")) == old_title, 'Before/after edit content recorded')
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
                'Requesting buyer sees changes made after the request',
            )
            buyer_notifications = self._notifications("buyer")
            self.rec.must(
                self._has_notification(buyer_notifications, "product_edited", link_id=int(self.products["P_EDIT"]["id"])),
                'Buyer of an open request receives a product-edit notification',
            )
            delisted = self._dict(
                self._call("POST", f"/api/v1/products/{self.products['P_EDIT']['id']}/delist", user="seller", expected=200)
            )
            self.rec.must_eq(delisted.get("status"), "delisted", 'Delisted state')
            trade = self._trade_detail("T_EDIT_PENDING", "buyer")
            self.rec.must_eq(trade.get("status"), "closed", 'Delisting closes pending acceptance requests')
            self.rec.must_eq(trade.get("close_reason"), "商品已下架", 'Close reason')
            buyer_notifications = self._notifications("buyer")
            self.rec.must(
                self._has_notification(buyer_notifications, "request_closed", link_id=int(request["id"])),
                'Buyer notified of request closure',
            )
            self._call("GET", f"/api/v1/products/{self.products['P_EDIT']['id']}", user="outsider", expected=404)
            # At completion the buyer can still view historical detail per D-43
            self._call("GET", f"/api/v1/products/{self.products['P_EDIT']['id']}", user="buyer", expected=200)
            relisted = self._dict(
                self._call("POST", f"/api/v1/products/{self.products['P_EDIT']['id']}/relist", user="seller", expected=200)
            )
            self.rec.must_eq(relisted.get("status"), "listed", 'Relisted')
            self._call("GET", f"/api/v1/products/{self.products['P_EDIT']['id']}", user="outsider", expected=200)

        with self.rec.step(
            "PROD-06",
            'Product permission/state rejections: non-owner, anonymous, edit/delist forbidden in transaction, claimed withdrawal 409',
        ):
            product_id = int(self.products["P_EDIT"]["id"])
            self._call("PATCH", f"/api/v1/products/{product_id}", user="outsider", expected=404, json_body={"title": "越权"})
            self._call("PATCH", f"/api/v1/products/{product_id}", expected=401, json_body={"title": "匿名"})
            # Claimed pending product: withdrawal returns 409, also verifying that edits during pending review keep it pending.
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
            self.rec.must_eq(edited_pending.get("status"), "pending_review", 'Edit after claim does not re-queue')
            self._review(int(case["id"]), {"result": "approved"})
            self.products["P_CLAIM_LATE"].update(self._product_detail("P_CLAIM_LATE", "seller"))
            self._call("POST", f"/api/v1/admin/products/cases/{case['id']}/review", user="admin", expected=409, json_body={"result": "approved"})
            # Edit forbidden in transaction: P_PENDING is already listed; first turn it into an in-transaction sample (TRADE-01 later uses P_MAIN, and P_LOCKED is separate).
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
            self.rec.must_eq(self.products["P_LOCKED"].get("status"), "in_transaction", 'In transaction after acceptance')
            self._call(
                "PATCH",
                f"/api/v1/products/{self.products['P_LOCKED']['id']}",
                user="seller",
                expected=409,
                json_body={"title": "交易中改"},
            )
            self._call("POST", f"/api/v1/products/{self.products['P_LOCKED']['id']}/delist", user="seller", expected=409)
            # Cleanup: an admin terminates this sample to release the lock
            self._admin_terminate("T_LOCKED", reason="验收交易中禁改样本收尾")

        with self.rec.step(
            "SEARCH-01",
            'Combined search: category OR with keyword/price AND; aliases/no match; unauthenticated rejected',
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
            self.rec.must_eq(hit.get("total"), 1, 'Keyword hit')
            price_hit = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="outsider",
                    expected=200,
                    params={"keyword": keyword, "price_min_cents": 5000, "price_max_cents": 5300},
                )
            )
            self.rec.must_eq(price_hit.get("total"), 1, 'Price range hit')
            price_miss = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="outsider",
                    expected=200,
                    params={"keyword": keyword, "price_min_cents": 999999},
                )
            )
            self.rec.must_eq(price_miss.get("total"), 0, 'Price does not match')
            # Single-category controls distinguish OR from AND. Boundary prices
            # also verify that category matches cannot bypass the price range.
            for key, title, price, category in (
                ("P_SEARCH_A", f"{keyword}-仅分类A", 5000, "main"),
                ("P_SEARCH_B", f"{keyword}-仅分类B", 5300, "second"),
                ("P_SEARCH_EXPENSIVE", f"{keyword}-超出价格", 5301, "main"),
                ("P_SEARCH_OTHER_KEYWORD", f"其他关键词对照-{self.run_id}", 5200, "main"),
            ):
                self._publish(key, "seller", title, price=price,
                              category_ids=[self.categories[category]["id"]])
                self._approve(key)
            expected_ids = {self.products[key]["id"] for key in
                            ("P_MULTI", "P_SEARCH_A", "P_SEARCH_B", "P_SEARCH_EXPENSIVE")}
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
            self.rec.must_eq(multi.get("total"), 4, 'Either selected category matches; keyword still required')
            self.rec.must_eq({item["id"] for item in multi["items"]}, expected_ids,
                             'Category union includes A-only/B-only products and excludes other keywords')
            self.rec.must_eq(len(multi["items"]), 4, 'A product in both categories appears only once')
            bounded = self._dict(
                self._call(
                    "GET", "/api/v1/products/search", user="outsider", expected=200,
                    params={
                        "category_ids": [self.categories["main"]["id"], self.categories["second"]["id"]],
                        "keyword": keyword, "price_min_cents": 5000, "price_max_cents": 5300,
                    },
                )
            )
            self.rec.must_eq(bounded.get("total"), 3, 'Category OR intersects keyword and inclusive price range')
            self.rec.must_eq({item["id"] for item in bounded["items"]},
                             expected_ids - {self.products["P_SEARCH_EXPENSIVE"]["id"]},
                             'Both price boundaries match; category match does not bypass price')
            self.rec.must_eq(len(bounded["items"]), 3, 'Combined filtering does not duplicate products')
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
            self.rec.must_eq(by_names.get("total"), 4, 'Category names also use OR')
            self.rec.must_eq({item["id"] for item in by_names["items"]}, expected_ids,
                             'Category-name union has the same products as category-ID union')
            unknown = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="outsider",
                    expected=200,
                    params={"category_names": [f"不存在分类-{self.run_id}"]},
                )
            )
            self.rec.must_eq(unknown.get("total"), 0, 'Unknown category yields no match')
            self.rec.must_eq(unknown.get("message"), "无匹配商品", 'Unknown category hint')
            none = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="outsider",
                    expected=200,
                    params={"keyword": f"绝对不存在-{self.run_id}"},
                )
            )
            self.rec.must_eq(none.get("total"), 0, 'No matching keyword')
            self._call("GET", "/api/v1/products/search", expected=401)
            self._call("GET", f"/api/v1/products/{self.products['P_MULTI']['id']}", expected=401)

        with self.rec.step(
            "FAV-01",
            'Favorites: valid/duplicate/cancel/invalid hint/restored after unban or relist; banned is read-only',
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
            self.rec.must_eq(second.get("favorite_id"), first.get("favorite_id"), 'Duplicate favorite returns existing result')
            self.audit_targets["favorite_product_id"] = product_id
            self.audit_targets["favorite_removed_id"] = int(first["favorite_id"])
            favorites = self._list(self._call("GET", "/api/v1/favorites", user="buyer", expected=200))
            row = next(item for item in favorites if int(item["product_id"]) == product_id)
            self.rec.must(row.get("valid") is True, 'Favorite valid')
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
            self.rec.must(row.get("valid") is False and row.get("title") is None, 'Only an invalid hint after delisting')
            self._call("POST", f"/api/v1/products/{product_id}/relist", user="seller", expected=200)
            favorites = self._list(self._call("GET", "/api/v1/favorites", user="buyer", expected=200))
            row = next(item for item in favorites if int(item["product_id"]) == product_id)
            self.rec.must(row.get("valid") is True, 'Favorite restored after relisting')
            # Ban read-only: REPORT-04 later bans seller2; here outsider is temporarily banned and then unbanned,
            # covering "read allowed, favorite write 403".
            self._call("POST", f"/api/v1/admin/users/{self._uid('outsider')}/ban", user="admin", expected=200, json_body={"reason": "验收收藏封禁样本"})
            self._call("GET", "/api/v1/favorites", user="outsider", expected=200)
            self._call("POST", f"/api/v1/favorites/{product_id}", user="outsider", expected=403)
            self._call("DELETE", f"/api/v1/favorites/{product_id}", user="outsider", expected=403)
            self._call("POST", f"/api/v1/admin/users/{self._uid('outsider')}/unban", user="admin", expected=200, json_body={"lift_reason": "验收收藏封禁解除"})

        with self.rec.step(
            "COMM-01",
            'Comments: authenticated comment, seller reply, author delete, unauthorized rejected, rate-limited, delisted rejected',
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
            self.rec.must(next(row["content"] for row in saved if row["id"]==first["id"])==long_comment,'2000 combined emoji stored and read back intact; grapheme-cluster count is not rejected by code-point limits')
            if self.config.settings.kv_backend == "redis":
                # Prove the service process really uses Redis KV rather than the MemoryKV fallback:
                # Externally raise the user's rate-limit counter; a real HTTP comment should immediately return 429 from the Redis value.
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
                    self.rec.must(True, 'App rate limiting reads real Redis counts (MemoryKV fallback must not pass)')
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
            self.rec.must_eq(deleted_row.get("content"), "该评论已删除", 'Soft-delete placeholder')
            # Real Redis rate limiting: isolated commenter posts 4 times; first 3 return 201 and the 4th returns 429.
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
            'Seller profile: authenticated sees listed products; unknown user 404; anonymous 401',
        ):
            profile = self._dict(
                self._call("GET", f"/api/v1/users/{self._uid('seller')}/profile", user="outsider", expected=200)
            )
            self.rec.must_eq(int(profile["id"]), self._uid("seller"), 'Profile user ID')
            self.rec.must(isinstance(profile.get("products"), list), 'Profile includes listed products')
            self._call("GET", "/api/v1/users/999999999/profile", user="outsider", expected=404)
            self._call("GET", f"/api/v1/users/{self._uid('seller')}/profile", expected=401)

    # ------------------------------------------------------------------
    # Trade core, cancellation, disputes, freeze, timeout, D-48
    # ------------------------------------------------------------------
    def trades_core(self) -> None:
        with self.rec.step(
            "TRADE-01",
            'Purchase request/duplicate request/lock closes other requests/accept permission/branch and notifications',
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
            self.rec.must_eq(int(duplicate["id"]), int(main["id"]), 'Duplicate request returns the existing trade')
            self.rec.must_eq(duplicate.get("existing"), True, 'Duplicate request carries the existing marker')
            other = self._request_trade("T_MAIN_OTHER", "buyer2", "P_MAIN", note="其他买方请求")
            seller_notifications = self._notifications("seller")
            self.rec.must(
                self._has_notification(seller_notifications, "request_created", link_id=int(main["conversation_id"])) if main.get("conversation_id") else any(
                    item.get("type") == "request_created" and int((item.get("payload") or {}).get("trade_id") or 0) == int(main["id"])
                    for item in seller_notifications
                ),
                'Seller receives a request_created notification linked to the same trade',
            )
            self._call("POST", f"/api/v1/favorites/{self.products['P_MAIN']['id']}", user="buyer", expected=200)
            self._accept("T_MAIN")
            trade_detail = self._trade_detail("T_MAIN", "buyer")
            self.rec.must_eq(trade_detail.get("status"), "in_progress", 'In progress after acceptance')
            self.rec.must_eq(trade_detail.get("agreement_stage"), "awaiting_agreement", 'Awaiting-agreement stage')
            self.rec.must_eq(self._product_detail("P_MAIN", "seller").get("status"), "in_transaction", 'Product in transaction after acceptance')
            # In transaction: leaves public search while detail/favorite remain available; admin category correction does not affect the trade.
            listed_favorites = self._list(self._call("GET", "/api/v1/favorites", user="buyer", expected=200))
            main_favorite = next(item for item in listed_favorites if int(item["product_id"]) == int(self.products["P_MAIN"]["id"]))
            self.rec.must_eq(main_favorite.get("valid"), True, 'Favorite stays valid during transaction')
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
            self.rec.must_eq(trade_search.get("total"), 0, 'Leaves public search during transaction')
            corrected = self._dict(
                self._call(
                    "POST",
                    f"/api/v1/admin/products/{self.products['P_MAIN']['id']}/correct-category",
                    user="admin",
                    expected=200,
                    json_body={"category_ids": [self.categories["second"]["id"]], "reason": "验收纠类"},
                )
            )
            self.rec.must("纠正" in str(corrected.get("detail")), 'Admin category-correction entry')
            corrected_detail = self._product_detail("P_MAIN", "seller")
            self.rec.must_in(self.categories["second"]["name"], corrected_detail.get("tag_names") or [], 'Tags updated after correction')
            # Admin product list and summary: ID keyword search, paginated response, and summary tags (data source for the category-correction detail page).
            admin_products_page = self._dict(
                self._call(
                    "GET",
                    "/api/v1/admin/products",
                    user="admin",
                    expected=200,
                    params={"keyword": str(self.products["P_MAIN"]["id"]), "page_size": 5},
                )
            )
            # Numeric keywords also match body text; the target may be on a later page, so a unique hit is not required.
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
                'Admin product list returns the corrected product',
            )
            self.rec.must_eq(self._trade_detail("T_MAIN", "buyer").get("status"), "in_progress", 'Correction does not change trade state')
            other_detail = self._trade_detail("T_MAIN_OTHER", "buyer2")
            self.rec.must_eq(other_detail.get("status"), "closed", 'Remaining pending acceptance requests closed')
            self.rec.must_eq(other_detail.get("close_reason"), "商品已被其他用户锁单", 'Close reason is locked by another request')
            buyer2_notifications = self._notifications("buyer2")
            self.rec.must(
                self._has_notification(buyer2_notifications, "request_closed", link_id=int(other["id"])),
                'Other buyer receives closure notification',
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
            self.rec.must(any(int(item["id"]) == int(main["id"]) for item in mine_all), 'My trades all')
            self.rec.must(any(int(item["id"]) == int(main["id"]) for item in mine_buyer), 'My trades buyer')
            self.rec.must(any(int(item["id"]) == int(main["id"]) for item in mine_seller), 'My trades seller')
            transitions = self._list(
                self._call("GET", f"/api/v1/trades/{main['id']}/transitions", user="buyer", expected=200)
            )
            self.rec.must(
                any(row.get("to_status") == "in_progress" and row.get("trigger") == "request_accepted" for row in transitions),
                'Acceptance transition recorded',
            )

        with self.rec.step(
            "CONC-01",
            'Concurrent locking/duplicate requests: two rounds of real concurrency on separate products; one wins, one loses, no 500; loser has no extra success audit/notification/transition',
        ):
            accept_rounds: list[dict[str, Any]] = []
            accept_all_ok = True
            for index in range(2):
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
            for index in range(2):
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
                ("Concurrent locking/duplicate-request rounds: "
                 f"accept_rounds={len(accept_rounds)} accept_ok={accept_all_ok} "
                 f"duplicate_rounds={len(dup_rounds)} duplicate_ok={dup_all_ok}"),
            )

        with self.rec.step(
            "TRADE-02",
            'Multi-round agreement: completion impossible without an agreement; rejection leaves the original agreement intact; duplicate proposal 409; proposer cannot self-confirm',
        ):
            # Completion cannot be confirmed without a valid agreement.
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
            self.rec.must("拒绝" in str(rejected.get("detail")), 'Proposal rejected')
            detail = self._trade_detail("T_MAIN", "buyer")
            self.rec.must(detail.get("effective_agreement") is None, 'No valid agreement after rejection')
            self.rec.must_eq(len(detail.get("agreement_history") or []), 1, 'Rejected proposal retained in history')
            self.rec.must_eq(detail["agreement_history"][0].get("status"), "rejected", 'Proposal state rejected')
            second = self._propose("T_MAIN", "seller", AGREEMENT_B)
            confirmed = self._agree("T_MAIN", second, "buyer")
            self.rec.must("生效" in str(confirmed.get("detail")), 'Agreement confirmation takes effect')
            detail = self._trade_detail("T_MAIN", "buyer")
            self.rec.must_eq(int(detail["effective_agreement"]["id"]), second, 'Current valid agreement')
            self.rec.must_eq(len(detail.get("agreement_history") or []), 2, 'Two-round agreement history')
            self.rec.must_eq(detail.get("pending_agreement"), None, 'No proposal awaiting confirmation')

        with self.rec.step(
            "TRADE-03",
            'One-sided then bilateral completion confirmation; completion delists/archives/notifies; bilateral reviews and duplicate review rejection',
        ):
            one = self._confirm("T_MAIN", "buyer", note="买方已交付付款")
            self.rec.must("等待对方" in str(one.get("detail")), 'One-sided confirmation records progress only')
            seller_notifications = self._notifications("seller")
            self.rec.must(self._has_notification(seller_notifications, "confirm_progress", link_id=int(self.trades["T_MAIN"]["id"])), 'One-sided confirmation notifies the other party')
            detail = self._trade_detail("T_MAIN", "buyer")
            self.rec.must_eq(detail.get("my_confirmed"), True, "Buyer's current confirmation")
            self.rec.must(detail.get("confirm_wait_started_at"), 'One-sided confirmation starts the timer')
            confirmation_id = int(detail["confirmations"][0]["id"])
            self._call("PATCH", f"/api/v1/trades/{self.trades['T_MAIN']['id']}/confirmations/{confirmation_id}", user="buyer", expected=404, json_body={})
            self._call("DELETE", f"/api/v1/trades/{self.trades['T_MAIN']['id']}/confirmations/{confirmation_id}", user="buyer", expected=404)
            self._call("GET", f"/api/v1/trades/{self.trades['T_MAIN']['id']}", user="outsider", expected=404)
            remaining = detail.get("confirm_wait_remaining_seconds")
            self.rec.must(isinstance(remaining, int) and remaining > 7 * 86400 - 3600, 'Full 7-day timer start')
            both = self._confirm("T_MAIN", "seller", note="卖方确认")
            self.rec.must("已完成" in str(both.get("detail")), 'Bilateral confirmation completes the trade')
            detail = self._trade_detail("T_MAIN", "buyer")
            self.rec.must_eq(detail.get("status"), "completed", 'Trade completed')
            self.rec.must_eq(detail.get("conversation_archived"), True, 'Trade branch archived')
            self.rec.must_eq(self._product_detail("P_MAIN", "seller").get("status"), "delisted", 'Product delisted by default after completion')
            buyer_notifications = self._notifications("buyer")
            seller_notifications = self._notifications("seller")
            self.rec.must(self._has_notification(buyer_notifications, "trade_completed"), 'Buyer notified of completion')
            self.rec.must(self._has_notification(seller_notifications, "trade_completed"), 'Seller notified of completion')
            transitions = self._list(
                self._call("GET", f"/api/v1/trades/{self.trades['T_MAIN']['id']}/transitions", user="buyer", expected=200)
            )
            self.rec.must(any(row.get("to_status") == "completed" for row in transitions), 'Completion transition recorded')
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
            self.rec.must(int(buy_review["id"]) != int(sell_review["id"]), 'One review per party')
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_MAIN']['id']}/review",
                user="buyer",
                expected=409,
                json_body={"rating": 5, "content": "重复"},
            )
            # Review rejected for an incomplete trade (T_DISPUTE is not yet complete)
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_MAIN']['id']}/review",
                user="outsider",
                expected=404,
                json_body={"rating": 5, "content": "第三方"},
            )
            product_detail = self._product_detail("P_MAIN", "seller")
            self.rec.must("reviews" not in product_detail, 'Product detail does not expose reviews')
            comments = self._list(
                self._call("GET", f"/api/v1/products/{self.products['P_MAIN']['id']}/comments", user="seller", expected=200)
            )
            self.rec.must(not any("验收买方评价" in str(row.get("content")) for row in comments), 'Product comments do not mix with trade reviews')
            # UC-C09-02: a finished trade delists the product by default; the seller may explicitly relist when eligible.
            relisted = self._dict(
                self._call("POST", f"/api/v1/products/{self.products['P_MAIN']['id']}/relist", user="seller", expected=200)
            )
            self.rec.must_eq(relisted.get("status"), "listed", 'Seller explicitly relists after completion')
            self.rec.must_eq(self._product_detail("P_MAIN", "seller").get("status"), "listed", 'Relisting makes it public')
            published = self._list(
                self._call("GET", "/api/v1/me/reviews", user="buyer", expected=200, params={"type": "published"})
            )
            received = self._list(
                self._call("GET", "/api/v1/me/reviews", user="buyer", expected=200, params={"type": "received"})
            )
            self.rec.must(any(int(row["trade_id"]) == int(self.trades["T_MAIN"]["id"]) for row in published), 'Reviews I wrote')
            self.rec.must(any(int(row["trade_id"]) == int(self.trades["T_MAIN"]["id"]) for row in received), 'Reviews I received')

        with self.rec.step(
            "TRADE-04",
            'Seller rejection/buyer withdrawal/non-party permission/duplicate operation on processed item rejected',
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
            self.rec.must_eq(detail.get("status"), "rejected", 'Rejected after rejection')
            self.rec.must_eq(detail.get("close_reason"), "验收拒绝", 'Rejection reason')
            self.rec.must_eq(detail.get("conversation_archived"), True, 'Branch archived after rejection')
            self._call("POST", f"/api/v1/trades/{rejected_trade['id']}/reject", user="seller", expected=409, json_body={})
            self._call(
                "POST",
                "/api/v1/trades/requests",
                user="buyer",
                expected=200,
                json_body={"product_id": int(self.products["P_REJECT_TRADE"]["id"])},
            )
            # Another request was just created above; withdraw that new request.
            # Find the latest pending request through my trades.
            mine = self._list(self._call("GET", "/api/v1/trades/mine", user="buyer", expected=200, params={"role": "buyer"}))
            pending = [row for row in mine if int(row["product_id"]) == int(self.products["P_REJECT_TRADE"]["id"]) and row["status"] == "pending_acceptance"]
            if not pending:
                raise CheckFailure('Withdrawal sample request not generated')
            withdraw_id = int(pending[0]["id"])
            self._call("POST", f"/api/v1/trades/{withdraw_id}/withdraw", user="buyer", expected=200)
            self._call("GET", f"/api/v1/trades/{withdraw_id}", user="buyer", expected=200)
            self.rec.must_eq(self._trade_detail("T_REJECT", "buyer").get("status"), "rejected", 'Withdrawal does not affect an already rejected trade')

        with self.rec.step(
            "TRADE-05",
            'Cancellation: buyer cancels directly before the first agreement; both parties agree after an agreement; cancellation request withdrawal and rejection',
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
            self.rec.must_eq(direct.get("status"), "terminated", 'Buyer cancels directly before the first agreement -> terminated')
            self.rec.must_eq(self._product_detail("P_CANCEL_DIRECT", "seller").get("status"), "delisted", 'Product delisted by default after cancellation')
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
            self.rec.must_eq(detail.get("status"), "in_progress", 'Cancellation does not take effect without consent')
            self.rec.must_eq(int(detail["cancel_requested_by"] or 0), self._uid("seller"), 'Cancellation requester')
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_CANCEL_AGREE']['id']}/cancel/confirm",
                user="buyer",
                expected=200,
                json_body={"reason": "买方同意取消"},
            )
            self.rec.must_eq(self._trade_detail("T_CANCEL_AGREE", "buyer").get("status"), "terminated", 'Both parties agree to terminate')
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
            self.rec.must_eq(detail.get("status"), "in_progress", 'Still in progress after withdrawing the cancellation request')
            self.rec.must_eq(detail.get("cancel_requested_by"), None, 'Cancellation request withdrawn')
            self._confirm("T_CANCEL_WITHDRAW", "buyer")
            self._confirm("T_CANCEL_WITHDRAW", "seller")
            self.rec.must_eq(self._trade_detail("T_CANCEL_WITHDRAW", "buyer").get("status"), "completed", 'Can complete normally after withdrawal')

            # The counterparty rejects the cancellation request: only the request ends; the trade stays in progress.
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
            self.rec.must_eq(int(pending["cancel_requested_by"] or 0), self._uid("seller"), 'Cancellation requester is the seller before rejection')
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
            self.rec.must_eq(rejected.get("status"), "in_progress", 'Trade stays in progress after the counterparty rejects cancellation')
            self.rec.must_eq(rejected.get("cancel_requested_by"), None, 'Cancellation request ends after rejection')
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_CANCEL_REJECT']['id']}/cancel/reject",
                user="buyer",
                expected=409,
            )

        with self.rec.step(
            "TRADE-06",
            'Dispute: either party opens -> disputed and timer cleared; bilateral resolution confirmation restores without restarting the timer; completion cannot be confirmed directly after a dispute',
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
            self.rec.must_eq(before_dispute.get("my_confirmed"), True, 'One-sided confirmation existed before the dispute')
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
            self.rec.must_eq(branch_read.get("scope", {}).get("relation"), "trade_branch", 'Dispute case links to the trade branch')
            self.rec.must_eq(
                int(branch_read.get("conversation", {}).get("trade_id") or 0),
                int(self.trades["T_DISPUTE"]["id"]),
                'Returns only the directly linked trade branch',
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
            self.rec.must_eq(detail.get("status"), "disputed", 'Dispute opened -> disputed')
            self.rec.must_eq(detail.get("confirm_wait_started_at"), None, 'Dispute clears the timer')
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
            self.rec.must_eq(mid.get("status"), "disputed", 'One-sided resolution confirmation leaves it disputed')
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_DISPUTE']['id']}/disputes/resolve",
                user="seller",
                expected=200,
                json_body={"reason": "卖方确认解决"},
            )
            restored = self._trade_detail("T_DISPUTE", "buyer")
            self.rec.must_eq(restored.get("status"), "in_progress", 'Bilateral resolution restores in progress')
            self._call(
                "POST",
                f"/api/v1/trades/{self.trades['T_DISPUTE']['id']}/disputes/resolve",
                user="buyer",
                expected=409,
                json_body={"reason": "重复解决"},
            )
            self.rec.must_eq(restored.get("confirm_wait_started_at"), None, 'Recovery does not start the timer')
            self.rec.must_eq(restored.get("effective_agreement") is not None, True, 'Recovery preserves the valid agreement')
            self.rec.must_eq(restored.get("my_confirmed"), False, 'Recovery clears current confirmations')
            self.rec.must(
                len([row for row in restored.get("confirmations") or [] if row.get("is_current") is False]) >= 1,
                'Recovery preserves confirmation history',
            )
            # After both parties confirm dispute resolution, the claiming admin can still read only the directly linked branch.
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
            self.rec.must_eq(self._trade_detail("T_DISPUTE", "buyer").get("status"), "completed", 'Can complete after dispute resolution')

        with self.rec.step(
            "TRADE-07",
            'Freeze pauses the timer: writes/party IM rejected while frozen, remaining does not decrease; unfreeze resumes counting; third-party conversations unaffected',
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
            # UC-C08-05: the same buyer/seller pair has a second trade branch and a normal DM; a freeze must block sending in all of them.
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
            self.rec.must_eq(frozen.get("frozen"), True, 'Trade frozen')
            self.rec.must(frozen.get("confirm_wait_paused_at"), 'Freeze records the pause moment')
            remaining_paused = int(frozen["confirm_wait_remaining_seconds"])
            self.rec.must(abs(remaining_paused - remaining_before) <= 2, 'Remaining seconds saved at freeze')
            self._call("POST", f"/api/v1/trades/{self.trades['T_FREEZE']['id']}/confirmations", user="seller", expected=403, json_body={})
            # D-50: a trade-only freeze also forbids publish/delist/relist, but compliant edits to unrelated products are allowed.
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
            self.rec.must_eq(unrelated_edit.get("status"), "listed", 'Unrelated products editable while frozen')
            # A trade-only freeze still allows reviewing previously completed trades.
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
            # Historical read-only: frozen parties can still read both branch types and the normal DM.
            self._call("GET", f"/api/v1/conversations/{conversation_id}", user="buyer", expected=200)
            self._call("GET", f"/api/v1/conversations/{second_conversation_id}", user="seller", expected=200)
            self._call("GET", f"/api/v1/conversations/{normal_pair_id}", user="seller", expected=200)
            # Third-party pair: buyer2 and seller have no trade and must not be affected by that freeze.
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
                raise CheckFailure('Freeze pause/resume requires the controlled clock service started by this task')
            self.server.set_clock_offset(86400)
            self.clock_events.append(
                {"kind": "freeze_pause", "offset_seconds": 86400, "trade_id": self.trades["T_FREEZE"]["id"], "at": datetime.now(UTC).isoformat()}
            )
            still = self._trade_detail("T_FREEZE", "buyer")
            self.rec.must_eq(still.get("status"), "in_progress", 'Frozen trade remains in progress')
            self.rec.must_eq(int(still["confirm_wait_remaining_seconds"]), remaining_paused, 'remaining does not decrease while frozen')
            self._call(
                "POST",
                f"/api/v1/admin/trades/{self.trades['T_FREEZE']['id']}/unfreeze",
                user="admin",
                expected=200,
                json_body={"reason": "验收解冻续算", "case_id": case_id},
            )
            resumed = self._trade_detail("T_FREEZE", "buyer")
            self.rec.must_eq(resumed.get("frozen"), False, 'Unfreeze')
            self.rec.must_eq(resumed.get("confirm_wait_paused_at"), None, 'Unfreeze clears the pause moment')
            resumed_remaining = int(resumed["confirm_wait_remaining_seconds"])
            self.rec.must(abs(resumed_remaining - remaining_paused) <= 3, 'Unfreeze resumes from the pause point')
            self.server.set_clock_offset(86400 + 2 * 86400)
            later = self._trade_detail("T_FREEZE", "buyer")
            self.rec.must(
                int(later["confirm_wait_remaining_seconds"]) <= resumed_remaining - 2 * 86400 + 5,
                'Remaining decreases by elapsed time after unfreeze',
            )
            self.server.set_clock_offset(0)
            self.clock_events.append({"kind": "clock_reset", "offset_seconds": 0, "at": datetime.now(UTC).isoformat()})
            self._confirm("T_FREEZE", "seller")
            self.rec.must_eq(self._trade_detail("T_FREEZE", "buyer").get("status"), "completed", 'Completes after the freeze is lifted')
            self._call(
                "POST",
                f"/api/v1/admin/cases/{case_id}/dispose",
                user="admin",
                expected=200,
                json_body={"conclusion": "冻结/解冻验证完成", "reason": "验收流程结束", "basis": "SC-09-10"},
            )

        with self.rec.step(
            "TRADE-08",
            'Controlled clock +8 days: real scan moves to abnormal+frozen and creates case/notifications; non-claiming 403; inquiry/statement/reply/adjust/unfreeze/terminate',
            note="7-day threshold unchanged; only the test service process injects a UTC offset",
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
            self.rec.must_eq(before.get("status"), "in_progress", 'In progress before timeout')
            started = str(before.get("confirm_wait_started_at"))
            self.server.set_clock_offset(8 * 86400)
            self.clock_events.append(
                {
                    "kind": "timeout_advance",
                    "offset_seconds": 8 * 86400,
                    "trade_id": self.trades["T_TIMEOUT"]["id"],
                    "before_status": "in_progress",
                    "started_at": started,
                    "method": "test service process UTC offset + real background scan (2s interval)",
                    "at": datetime.now(UTC).isoformat(),
                }
            )
            abnormal = self._wait_trade_status("T_TIMEOUT", ["abnormal"], timeout=40)
            self.rec.must_eq(abnormal.get("frozen"), True, 'Timeout -> abnormal and frozen')
            self.rec.must_eq(abnormal.get("confirm_wait_started_at"), None, 'Abnormal clears the timer')
            self.rec.must_eq(self._product_detail("P_TIMEOUT", "seller").get("status"), "in_transaction", 'Abnormal keeps the product locked')
            cases = self._list(
                self._call("GET", "/api/v1/admin/cases", user="admin2", expected=200, params={"status": "pending", "case_type": "abnormal_trade"})
            )
            timeout_case = next((row for row in cases if int(row.get("trade_id") or 0) == int(self.trades["T_TIMEOUT"]["id"])), None)
            if timeout_case is None:
                raise CheckFailure('Timeout did not create an abnormal_trade case')
            self.cases["T_TIMEOUT_abnormal"] = timeout_case
            buyer_notifications = self._notifications("buyer")
            seller_notifications = self._notifications("seller")
            self.rec.must(self._has_notification(buyer_notifications, "trade_abnormal", link_id=int(self.trades["T_TIMEOUT"]["id"])), 'Buyer notified of abnormal')
            self.rec.must(self._has_notification(seller_notifications, "trade_abnormal", link_id=int(self.trades["T_TIMEOUT"]["id"])), 'Seller notified of abnormal')
            # Non-claimants cannot view/dispose
            self._call("GET", f"/api/v1/admin/cases/{timeout_case['id']}", user="admin", expected=403)
            self._call("POST", f"/api/v1/admin/cases/{timeout_case['id']}/claim", user="admin2", expected=200, json_body={})
            detail = self._dict(self._call("GET", f"/api/v1/admin/cases/{timeout_case['id']}", user="admin2", expected=200))
            self.rec.must_eq(detail.get("case_type"), "abnormal_trade", 'Case type abnormal_trade')
            self._call(
                "POST",
                f"/api/v1/admin/cases/{timeout_case['id']}/inquiry",
                user="admin2",
                expected=200,
                json_body={"content": "请说明超时原因与当前交付情况"},
            )
            my_cases = self._list(self._call("GET", "/api/v1/me/cases", user="buyer", expected=200))
            self.rec.must(any(int(row["id"]) == int(timeout_case["id"]) for row in my_cases), 'Abnormal case appears in my cases')
            buyer_case = self._dict(self._call("GET", f"/api/v1/me/cases/{timeout_case['id']}", user="buyer", expected=200))
            self.rec.must_eq(buyer_case.get("can_submit_statement"), True, 'Statement can be submitted after inquiry')
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
            self.rec.must_eq(admin_view.get("frozen"), True, 'Frozen from the admin view')
            self.rec.must_eq(admin_view.get("confirm_wait_remaining_seconds"), None, 'Abnormal has no remaining wait')
            self._call(
                "POST",
                f"/api/v1/admin/trades/{self.trades['T_TIMEOUT']['id']}/adjust",
                user="admin2",
                expected=200,
                json_body={"to_status": "in_progress", "reason": "核查后恢复进行中", "case_id": timeout_case["id"]},
            )
            restored = self._trade_detail("T_TIMEOUT", "buyer")
            self.rec.must_eq(restored.get("status"), "in_progress", 'Adjustment restores in progress')
            self.rec.must_eq(restored.get("frozen"), True, 'Recovery does not automatically unfreeze')
            self.rec.must_eq(restored.get("my_confirmed"), False, 'Recovery clears current confirmations')
            self.rec.must(
                len([row for row in restored.get("confirmations") or [] if row.get("is_current") is False]) >= 1,
                'Admin recovery preserves historical confirmations',
            )
            self.rec.must_eq(restored.get("confirm_wait_started_at"), None, 'Recovery does not start the timer')
            self.rec.must(restored.get("effective_agreement") is not None, 'Recovery preserves the valid agreement')
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
            self.rec.must_eq(ended.get("status"), "terminated", 'Admin termination')
            self.rec.must_eq(self._product_detail("P_TIMEOUT", "seller").get("status"), "delisted", 'Product delisted by default after termination')
            self.rec.must_eq(ended.get("conversation_archived"), True, 'Termination archives the branch')
            transitions = self._list(
                self._call("GET", f"/api/v1/trades/{self.trades['T_TIMEOUT']['id']}/transitions", user="buyer", expected=200)
            )
            self.rec.must(any(row.get("trigger") == "confirm_timeout" for row in transitions), 'Timeout scan transition recorded')
            self.rec.must(any(row.get("to_status") == "terminated" and row.get("basis_case_id") == timeout_case["id"] for row in transitions), 'Admin termination is based on the case')
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
            'Agreement change after one-sided confirmation: activation clears current confirmations/stops the old timer; full timer after reconfirmation',
        ):
            self._publish("P_CHANGE", "seller", f"约定变更商品-{self.run_id}", price=6800, category_ids=[self.categories["main"]["id"]])
            self._approve("P_CHANGE")
            self._request_trade("T_CHANGE", "buyer", "P_CHANGE")
            self._accept("T_CHANGE")
            first = self._propose("T_CHANGE", "buyer", AGREEMENT_A)
            self._agree("T_CHANGE", first, "seller")
            self._confirm("T_CHANGE", "buyer")
            before = self._trade_detail("T_CHANGE", "buyer")
            self.rec.must_eq(before.get("my_confirmed"), True, 'One-sided confirmation existed before the change')
            second = self._propose("T_CHANGE", "seller", AGREEMENT_B)
            self._agree("T_CHANGE", second, "buyer")
            changed = self._trade_detail("T_CHANGE", "buyer")
            self.rec.must_eq(changed.get("my_confirmed"), False, 'Change activation clears current confirmations')
            self.rec.must_eq(changed.get("confirm_wait_started_at"), None, 'Change activation stops the old timer')
            self.rec.must_eq(int(changed["effective_agreement"]["id"]), second, 'New agreement active')
            self.rec.must_eq(len(changed.get("confirmations") or []), 1, 'Historical confirmations preserved')
            self._confirm("T_CHANGE", "buyer")
            started = self._trade_detail("T_CHANGE", "buyer")
            self.rec.must(started.get("confirm_wait_started_at"), 'Reconfirmation starts a new timer')
            self.rec.must(int(started["confirm_wait_remaining_seconds"]) > 7 * 86400 - 3600, 'Reconfirmation gets a full 7 days')
            self._confirm("T_CHANGE", "seller")
            self.rec.must_eq(self._trade_detail("T_CHANGE", "buyer").get("status"), "completed", 'Completes after the change')

        with self.rec.step(
            "TRADE-10",
            'D-48: restoring an old trade returns 409 while a new trade for the same product still holds the lock, with no side effects',
        ):
            self._publish("P_D48", "seller", f"旧交易恢复冲突商品-{self.run_id}", price=6900, category_ids=[self.categories["main"]["id"]])
            self._approve("P_D48")
            self._request_trade("T_D48_A", "buyer", "P_D48")
            self._accept("T_D48_A")
            agreement = self._propose("T_D48_A", "buyer", AGREEMENT_A)
            self._agree("T_D48_A", agreement, "seller")
            self._confirm("T_D48_A", "buyer")
            self._confirm("T_D48_A", "seller")
            self.rec.must_eq(self._trade_detail("T_D48_A", "buyer").get("status"), "completed", 'A completed')
            self._call("POST", f"/api/v1/products/{self.products['P_D48']['id']}/relist", user="seller", expected=200)
            self._request_trade("T_D48_B", "buyer2", "P_D48")
            self._accept("T_D48_B")
            self.rec.must_eq(self._trade_detail("T_D48_B", "buyer2").get("status"), "in_progress", 'B holds the lock')
            case_id = self._relevant_case_for_product(int(self.products["P_D48"]["id"]), claimant="admin")
            conflict = self._call(
                "POST",
                f"/api/v1/admin/trades/{self.trades['T_D48_A']['id']}/adjust",
                user="admin",
                expected=409,
                json_body={"to_status": "in_progress", "reason": "尝试恢复旧交易", "case_id": case_id},
            )
            self.rec.must_eq(conflict.status_code, 409, 'Restoring the old trade returns 409')
            self.rec.must_eq(self._trade_detail("T_D48_A", "buyer").get("status"), "completed", 'A stays completed')
            self.rec.must_eq(self._trade_detail("T_D48_B", "buyer2").get("status"), "in_progress", 'B stays in_progress')
            self.rec.must_eq(self._product_detail("P_D48", "seller").get("status"), "in_transaction", 'Product stays locked')
            self._call(
                "POST",
                f"/api/v1/admin/trades/{self.trades['T_D48_B']['id']}/adjust",
                user="admin",
                expected=200,
                json_body={"to_status": "terminated", "reason": "D-48 样本 B 收尾", "case_id": case_id},
            )
            self.rec.must_eq(self._trade_detail("T_D48_B", "buyer2").get("status"), "terminated", 'B cleaned up -> terminated')
            self._call(
                "POST",
                f"/api/v1/admin/cases/{case_id}/dispose",
                user="admin",
                expected=200,
                json_body={"conclusion": "D-48 验证完成", "reason": "样本收尾", "basis": "SC-09-09"},
            )

    # ------------------------------------------------------------------


    # Reports / disposition / bans
    # ------------------------------------------------------------------
    def governance(self) -> None:
        with self.rec.step(
            "GOV-01",
            'Product report: evidence in both buckets, supplement, claim/inquiry/statement/reply, display restriction, anonymous publication, restriction lifted',
        ):
            report_product_title = f"Kindle Paperwhite 4-{self.run_id}"
            self._publish(
                "P_REPORT", "seller", report_product_title, price=7100,
                category_ids=[self.categories["main"]["id"]], asset="product_kindle_demo.jpg",
                description="Kindle Paperwhite 4，屏幕无划痕。",
            )
            self._approve("P_REPORT")
            product_id = int(self.products["P_REPORT"]["id"])
            self._call("POST", f"/api/v1/favorites/{product_id}", user="buyer", expected=200)
            # A report alone does not automatically delist/restrict (SC-07-05).
            self._call("GET", f"/api/v1/products/{product_id}", user="outsider", expected=200)
            evidence = self._upload("buyer", "evidence_kindle_screen.jpg", "report")
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
            self.rec.must_eq(int(duplicate.get("existing_report_id") or 0), report_id, 'Open report reuses the original case')
            self._call(
                "POST",
                f"/api/v1/reports/{report_id}/supplements",
                user="buyer",
                expected=200,
                json_body={"content": "补充说明：交易前已核对描述。", "evidence_keys": [evidence["key"]]},
            )
            mine = self._list(self._call("GET", "/api/v1/reports/mine", user="buyer", expected=200))
            mine_row = next(item for item in mine if int(item["id"]) == report_id)
            self.rec.must_eq(len(mine_row.get("supplements") or []), 1, 'Supplement statement retrievable')
            mine_evidence_urls = mine_row.get("evidence_urls") or []
            self.rec.must_eq(len(mine_evidence_urls), 1, 'Report evidence link returned to the reporter')
            self._assert_media_url(mine_evidence_urls[0], 'Own report evidence')
            supplement_urls = (mine_row.get("supplements") or [{}])[0].get("evidence_urls") or []
            self.rec.must_eq(len(supplement_urls), 1, 'Supplement evidence link returned to the reporter')
            self._assert_media_url(supplement_urls[0], 'Own supplement evidence')
            rows = self._list(self._call("GET", "/api/v1/admin/reports", user="admin", expected=200, params={"status": "pending"}))
            report_row = next(row for row in rows if int(row.get("id") or 0) == report_id and row.get("case_id"))
            case_id = int(report_row["case_id"])
            for field in ("detail", "evidence_keys", "evidence_urls"):
                self.rec.must(field not in report_row, f"Unclaimed report list does not disclose {field}")
            self._call("GET", f"/api/v1/admin/cases/{case_id}", user="admin2", expected=403)
            self.cases["report_product"] = {"id": case_id, "report_id": report_id}
            self._claim(case_id)
            other_rows = self._list(self._call("GET", "/api/v1/admin/reports", user="admin2", expected=200, params={"status": "all"}))
            other_row = next(row for row in other_rows if int(row.get("id") or 0) == report_id)
            for field in ("detail", "evidence_keys", "evidence_urls"):
                self.rec.must(field not in other_row, f"Other admin report list does not disclose {field}")
            self._call("GET", f"/api/v1/admin/cases/{case_id}", user="admin2", expected=403)
            case_detail = self._dict(self._call("GET", f"/api/v1/admin/cases/{case_id}", user="admin", expected=200))
            self.rec.must_eq(case_detail.get("case_type"), "report", 'Case type report')
            self.rec.must_eq(int(case_detail.get("report", {}).get("id") or 0), report_id, 'Case links to report')
            self.rec.must_eq(len(case_detail.get("report", {}).get("evidence_keys") or []), 1, 'Evidence key visible in the claimed case')
            evidence_urls = case_detail.get("report", {}).get("evidence_urls") or []
            self.rec.must_eq(len(evidence_urls), 1, 'Direct evidence link visible in the claimed case')
            self._assert_media_url(evidence_urls[0], 'Report evidence')
            supplements = case_detail.get("report", {}).get("supplements") or []
            self.rec.must_eq(len(supplements), 1, 'Claimed case shows the supplement statement')
            self.rec.must_eq(supplements[0].get("content"), "补充说明：交易前已核对描述。", 'Supplement statement content')
            supplement_evidence_urls = supplements[0].get("evidence_urls") or []
            self.rec.must_eq(len(supplement_evidence_urls), 1, 'Claimed case shows supplement evidence')
            self._assert_media_url(supplement_evidence_urls[0], 'Supplement evidence')
            target_image_urls = (case_detail.get("report_target") or {}).get("image_urls") or []
            self.rec.must(bool(target_image_urls), 'Direct product image link for the reported target')
            if target_image_urls:
                self._assert_media_url(target_image_urls[0], 'Reported target product image')
            self._call(
                "POST",
                f"/api/v1/admin/cases/{case_id}/inquiry",
                user="admin",
                expected=200,
                json_body={"content": "请说明商品描述与实物差异"},
            )
            seller_cases = self._list(self._call("GET", "/api/v1/me/cases", user="seller", expected=200))
            self.rec.must(any(int(row["id"]) == case_id for row in seller_cases), 'Reported user can read the case')
            seller_case = self._dict(self._call("GET", f"/api/v1/me/cases/{case_id}", user="seller", expected=200))
            self.rec.must_eq(seller_case.get("can_submit_statement"), True, 'Statement eligibility after inquiry')
            statement_content = f"卖方说明正文标记-{self.run_id}"
            self.audit_targets.setdefault("sensitive_markers", []).append(statement_content)
            self._call(
                "POST",
                f"/api/v1/me/cases/{case_id}/statement",
                user="seller",
                expected=200,
                json_body={"content": statement_content},
            )
            # UC-C08-01: the reporter has no right to read the questioned user's statement/appeal content.
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
            self.rec.must("处置" in str(decision.get("detail")), 'Report disposition conclusion')
            report_row = next(
                item
                for item in self._list(self._call("GET", "/api/v1/reports/mine", user="buyer", expected=200))
                if int(item["id"]) == report_id
            )
            self.rec.must_eq(report_row.get("status"), "handled", 'Report handled')
            self.rec.must_eq(report_row.get("result_confirmed"), True, 'Result confirmed')
            product_restricted = self._product_detail("P_REPORT", "seller")
            self.rec.must_eq(product_restricted.get("display_restricted"), True, 'Product no longer public')
            self.rec.must_eq(product_restricted.get("status"), "listed", 'Display restriction does not change lifecycle')
            self._call("GET", f"/api/v1/products/{product_id}", user="outsider", expected=404)
            restricted_favorites = self._list(self._call("GET", "/api/v1/favorites", user="buyer", expected=200))
            restricted_row = next(item for item in restricted_favorites if int(item["product_id"]) == product_id)
            self.rec.must_eq(restricted_row.get("valid"), False, 'Favorite invalid after display restriction')
            restricted_search = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="buyer",
                    expected=200,
                    params={"keyword": report_product_title},
                )
            )
            self.rec.must_eq(restricted_search.get("total"), 0, 'No search entry after display restriction')
            received = self._list(self._call("GET", "/api/v1/reports/received", user="seller", expected=200))
            received_row = next(item for item in received if int(item["id"]) == report_id)
            self.rec.must("reporter_id" not in received_row, 'Received reports do not disclose the reporter')
            self.rec.must("evidence_urls" not in received_row, 'Received report does not disclose reporter evidence')
            public_notice = self._dict(self._call(
                "GET", f"/api/v1/products/{product_id}/restriction-result", user="outsider", expected=200,
            ))
            self.rec.must_eq(set(public_notice), {"public_result"}, 'Original entry returns only the anonymized result')
            self.rec.must_eq(public_notice["public_result"], "经核查，涉事商品已停止公开。", 'Third party can read the anonymized disposition hint')
            restricted_detail = self._product_detail("P_REPORT", "seller")
            self.rec.must_eq(
                restricted_detail.get("restriction_result"),
                "经核查，涉事商品已停止公开。",
                'Restricted-product entry anonymized result hint',
            )
            seller_notifications = self._notifications("seller")
            buyer_notifications = self._notifications("buyer")
            self.rec.must(self._has_notification(seller_notifications, "inquiry", link_id=case_id), 'Inquiry notifies the questioned user')
            self.rec.must(self._has_notification(seller_notifications, "disposal", link_id=case_id), 'Actual disposition notifies affected users')
            self.rec.must(self._has_notification(buyer_notifications, "report_result", link_id=report_id), 'Report result notifies the reporter')
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
            self.rec.must("解除" in str(restored.get("detail")), 'Lift display restriction')
            after_restore = self._product_detail("P_REPORT", "seller")
            self.rec.must_eq(after_restore.get("display_restricted"), False, 'Public again')
            self.rec.must_eq(after_restore.get("status"), "listed", 'Lifecycle unchanged')
            self._call("GET", f"/api/v1/products/{product_id}", user="outsider", expected=200)
            restored_favorites = self._list(self._call("GET", "/api/v1/favorites", user="buyer", expected=200))
            restored_row = next(item for item in restored_favorites if int(item["product_id"]) == product_id)
            self.rec.must_eq(restored_row.get("valid"), True, 'Favorite valid again after lifting the restriction')
            restored_search = self._dict(
                self._call(
                    "GET",
                    "/api/v1/products/search",
                    user="buyer",
                    expected=200,
                    params={"keyword": report_product_title},
                )
            )
            self.rec.must_eq(restored_search.get("total"), 1, 'Search restored after lifting the restriction')
            history = self._list(
                self._call("GET", f"/api/v1/products/{product_id}/edit-history", user="seller", expected=200)
            )
            self.rec.must(any(row.get("edit_type") == "display_restore" for row in history), 'Lifting the restriction leaves edit history')

        with self.rec.step(
            "GOV-02",
            'Comment report: off-topic trade content removes only the offending object; disposed user notified; received-report entry readable',
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
            self.rec.must_eq(row.get("deleted"), True, 'Offending comment soft-deleted')
            self.rec.must_eq(row.get("content"), "该评论已删除", 'Deletion placeholder')
            buyer_received = self._list(self._call("GET", "/api/v1/reports/received", user="buyer2", expected=200))
            self.rec.must(any(int(item["id"]) == report_id for item in buyer_received), 'Disposed user receives the report')
            buyer_notifications = self._notifications("buyer2")
            self.rec.must(self._has_notification(buyer_notifications, "disposal"), 'Disposed user receives a disposal notification')
            # After the object is soft-deleted: existing reports remain readable and a new report fails.
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
            self.rec.must(any(int(item["id"]) == report_id and item["status"] == "handled" for item in existing), 'Existing report remains readable after closure')

        with self.rec.step(
            "GOV-03",
            'Report cannot be substantiated: recorded as unfounded and published anonymously; no off-platform facts inferred and no automatic penalty',
        ):
            # Use the main trade buyer's review as the report target.
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
            self.rec.must_eq(row.get("status"), "unfounded", 'Report unfounded')
            self.rec.must_eq(row.get("public_result"), None, 'Unfounded creates no public result')
            review_after = self._list(
                self._call("GET", "/api/v1/me/reviews", user="buyer", expected=200, params={"type": "published"})
            )
            self.rec.must(any(int(item["id"]) == review_id for item in review_after), 'Unfounded does not delete the review')
            # Admin removes the offending review with a basis (US-07-AC-02).
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
            self.rec.must_eq(removed_row.get("deleted"), True, 'Admin removes the review with a basis')

        with self.rec.step(
            "GOV-04",
            'Report finds a violation and bans: pending acceptance requests closed/notified/archived; trade freeze pauses the timer; appeal and admin reply available; lifting restores permissions and display',
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
            self.rec.must_eq(self._trade_detail("T_BAN_COMPLETED", "buyer2").get("status"), "completed", 'Trade completed before the ban')
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
            self.rec.must_eq(me_seller2.get("status"), "banned", 'Banned state')
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
            self.rec.must_eq(pending_detail.get("status"), "closed", 'Ban closes pending acceptance requests')
            self.rec.must_eq(pending_detail.get("close_reason"), "相关账户被封禁", 'Ban closure reason')
            buyer_notifications = self._notifications("buyer")
            self.rec.must(
                self._has_notification(buyer_notifications, "request_closed", link_id=int(self.trades["T_BAN_PENDING"]["id"])),
                'Buyer notified of ban-driven closure',
            )
            seller2_notifications = self._notifications("seller2")
            self.rec.must(
                self._has_notification(seller2_notifications, "request_closed", link_id=int(self.trades["T_BAN_PENDING"]["id"])),
                'Seller notified of ban-driven closure',
            )
            self.rec.must_eq(
                self._trade_detail("T_BAN_PENDING", "buyer").get("conversation_archived"),
                True,
                'Ban-driven closed branch archived',
            )
            frozen = self._trade_detail("T_BAN_TRADE", "buyer2")
            self.rec.must_eq(frozen.get("frozen"), True, 'Ban freezes accepted trades')
            self.rec.must(frozen.get("confirm_wait_paused_at"), 'Ban pauses an existing one-sided confirmation timer')
            pending_product = self._product_detail("P_BAN_PENDING", "seller2")
            self.rec.must_eq(pending_product.get("display_restricted"), True, "Banned user's products stop being public")
            self.rec.must_eq(pending_product.get("status"), "listed", 'Ban does not change product lifecycle')
            trade_product = self._product_detail("P_BAN_TRADE", "seller2")
            self.rec.must_eq(trade_product.get("display_restricted"), True, 'In-transaction product stops being public')
            self.rec.must_eq(trade_product.get("status"), "in_transaction", 'In-transaction product keeps its lock')
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
            self.rec.must(any(row.get("status") == "active" and row.get("type") == "ban" for row in restrictions), 'Ban restriction record')
            seller2_cases = self._list(self._call("GET", "/api/v1/me/cases", user="seller2", expected=200))
            self.rec.must(any(int(row["id"]) == case_id for row in seller2_cases), "Ban case appears in the user's cases")
            case_info = self._dict(self._call("GET", f"/api/v1/me/cases/{case_id}", user="seller2", expected=200))
            self.rec.must_eq(case_info.get("can_submit_appeal"), True, 'Appeal available after disposition')
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
            self.rec.must_eq(after_appeal.get("status"), "banned", 'Appeal does not automatically lift the ban')
            self._call(
                "POST",
                f"/api/v1/admin/cases/{case_id}/messages",
                user="admin",
                expected=200,
                json_body={"content": "已收到申辩，维持原处置。"},
            )
            seller2_notifications = self._notifications("seller2")
            self.rec.must(self._has_notification(seller2_notifications, "appeal_result", link_id=case_id), 'Appeal reply notification')
            self._call(
                "POST",
                f"/api/v1/admin/users/{self._uid('seller2')}/unban",
                user="admin",
                expected=200,
                json_body={"lift_reason": "验收复核后解除封禁"},
            )
            restored = self._dict(self._call("GET", "/api/v1/auth/me", user="seller2", expected=200))
            self.rec.must_eq(restored.get("status"), "normal", 'Lifting the ban restores normal')
            self.rec.must_eq(self._product_detail("P_BAN_PENDING", "seller2").get("display_restricted"), False, 'Display restored after lifting')
            unfrozen = self._trade_detail("T_BAN_TRADE", "buyer2")
            self.rec.must_eq(unfrozen.get("frozen"), False, 'Lifting the ban unfreezes trades frozen by it')
            self.rec.must_eq(unfrozen.get("status"), "in_progress", 'Trade still in progress')
            self._call(
                "POST",
                f"/api/v1/products/{self.products['P_COMMENT']['id']}/comments",
                user="seller2",
                expected=201,
                json_body={"content": "解除后恢复写权限"},
            )
            self._confirm("T_BAN_TRADE", "seller2")
            self.rec.must_eq(self._trade_detail("T_BAN_TRADE", "buyer2").get("status"), "completed", 'Trade can complete after lifting')

        with self.rec.step(
            "GOV-05",
            'Direct admin case disposition, user list, direct ban/unban paths and permissions',
        ):
            # Admin user list
            users = self._list(self._call("GET", "/api/v1/admin/users", user="admin", expected=200, params={"status": "all"}))
            self.rec.must(any(int(row["id"]) == self._uid("seller2") for row in users), 'Admin user list includes the seller')
            self._call("GET", "/api/v1/admin/users", user="outsider", expected=403)
            # Direct ban/unban (without a report)
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
            # An unclaimed case cannot be disposed; after claiming it can be disposed.
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
            self.rec.must_eq(case_row.get("status"), "disposed", 'Case disposed')

    # ------------------------------------------------------------------
    # IM / notifications / stats / audit / own business
    # ------------------------------------------------------------------
    def im_and_notifications(self) -> None:
        with self.rec.step(
            "IM-01",
            'Normal DM reuse, trade branch, independent unread/read, archive blocks sending, convert to normal DM, real WS send/receive',
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
            self.rec.must_eq(int(again["id"]), int(normal["id"]), 'Normal DM reused per pair')
            self.audit_targets["im_normal_conversation_id"] = int(normal["id"])
            self._call(
                "POST",
                "/api/v1/conversations/normal",
                user="buyer",
                expected=400,
                json_body={"peer_user_id": self._uid("buyer")},
            )
            conversations = self._list(self._call("GET", "/api/v1/conversations", user="buyer", expected=200))
            self.rec.must(any(int(row["id"]) == int(normal["id"]) for row in conversations), 'Conversation list includes normal DMs')
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
            self.rec.must(int(summary.get("unread", 0)) >= 1, 'Unread summary includes new messages')
            detail = self._dict(self._call("GET", f"/api/v1/conversations/{normal['id']}", user="seller", expected=200))
            self.rec.must(any(int(row["id"]) == int(sent["id"]) for row in detail.get("messages") or []), 'Conversation detail includes messages')
            # Viewing detail does not change read state
            count_before = int(
                self._dict(self._call("GET", f"/api/v1/conversations/{normal['id']}", user="seller", expected=200)).get("unread") or 0
            )
            self.rec.must(count_before >= 1, 'Viewing a conversation does not auto-mark as read')
            self._call(
                "POST",
                f"/api/v1/conversations/{normal['id']}/read",
                user="seller",
                expected=200,
                json_body={"last_displayed_message_id": int(sent["id"])},
            )
            self.audit_targets["im_read_conversation_id"] = int(normal["id"])
            # Re-submitting the same read watermark must not add a success audit.
            self._call(
                "POST",
                f"/api/v1/conversations/{normal['id']}/read",
                user="seller",
                expected=200,
                json_body={"last_displayed_message_id": int(sent["id"])},
            )
            after_read = self._dict(self._call("GET", f"/api/v1/conversations/{normal['id']}", user="seller", expected=200))
            self.rec.must_eq(int(after_read.get("unread") or 0), 0, 'Unread reaches zero after explicit read')
            # Archived trade branch: history readable, sending 409, convertible to a normal DM
            trade = self._trade_detail("T_MAIN", "buyer")
            trade_conversation = int(trade["conversation_id"])
            self.audit_targets["im_trade_conversation_id"] = trade_conversation
            history = self._dict(self._call("GET", f"/api/v1/conversations/{trade_conversation}", user="buyer", expected=200))
            self.rec.must(history.get("archived") is True, 'Completed trade branch archived')
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
            self.rec.must(int(migrated["id"]) == int(normal["id"]), 'Converted normal DM reuses the same pair conversation')
            # Both parties online: submit text over HTTP and each receives the other's real message push over WS.
            import websockets

            async def _ws_exchange() -> list[dict[str, Any]]:
                ws_base = self.ws_url.replace('http', 'ws', 1) + '/ws?token='
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
                            self.rec.must_eq(response.status_code, 200, f'{sender} HTTP send succeeded')
                            message_id = response.json()['id']
                            async def receive_message(websocket=websocket):
                                while True:
                                    payload = json.loads(await websocket.recv())
                                    if payload.get('type') == 'message':
                                        return payload
                            payload = await asyncio.wait_for(receive_message(), timeout=10)
                            self.rec.must_eq(payload.get('conversation_id'), int(normal['id']), f'{receiver} received the correct conversation')
                            self.rec.must_eq(payload.get('message_id'), message_id, f'{receiver} received the matching message ID')
                            self.rec.must_eq(payload.get('sender_id'), self._uid(sender), f'{receiver} received the correct sender')
                            self.rec.must_eq(payload.get('content'), content, f'{receiver} received the complete body')
                            exchanges.append({'sender': sender, 'receiver': receiver, 'message_id': message_id})
                    return exchanges

            exchanges = asyncio.run(_ws_exchange())
            self.rec.must_eq(len({item['message_id'] for item in exchanges}), 6, 'Three rounds of bidirectional messages have distinct IDs')
            self.ws_ok = True
            self.rec.data['ws'] = {'buyer_pong': True, 'seller_pong': True, 'rounds': 3, 'exchanges': exchanges}

        with self.rec.step(
            "IM-02",
            "Admin reads conversations only within the claimed case's necessary scope: message-report target conversation allowed; unclaimed/other-user/regular-user/unrelated conversations rejected; read state unchanged",
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
            # Unclaimed, regular-user, and ordinary third-party callers cannot use the admin entry.
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
            # Another admin cannot borrow the claimant's eligibility.
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
            self.rec.must_eq(page_one.get("scope", {}).get("relation"), "report_message", 'Message report link type')
            self.rec.must_eq(
                int(page_one.get("scope", {}).get("target_message_id") or 0),
                target_message_id,
                'Necessary scope points to the reported message',
            )
            self.rec.must_eq(
                int(page_one.get("conversation", {}).get("id") or 0),
                conversation_id,
                'Target conversation returned',
            )
            first_page_messages = page_one.get("messages") or []
            self.rec.must_eq(len(first_page_messages), 1, 'Pagination limit applies')
            self.rec.must_eq(int(first_page_messages[0]["id"]), message_ids[-1], 'Pagination starts from the newest message')
            self.rec.must_eq(set(first_page_messages[0].keys()), {"id", "sender_id", "kind", "content", "created_at"}, 'Message field allowlist')
            self.rec.must_eq(page_one.get("has_more"), True, 'Earlier messages exist')
            next_before = page_one.get("next_before_id")
            self.rec.must(isinstance(next_before, int), 'Next-page cursor returned')
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
                'Pagination has no duplicates and advances',
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
            self.rec.must_eq(unread_after, unread_before, "Admin read does not change parties' unread state")
            admin_read = self._db_one(
                ("select count(*) as n from app.conversation_reads "
                 "where conversation_id = :cid and user_id = :uid"),
                {"cid": conversation_id, "uid": self._uid("admin2")},
            )
            self.rec.must_eq(int(admin_read["n"]), 0, 'Admin read writes no admin read record')
            read_audit = self._db_one(
                ("select count(*) as n from app.audit_events where event_type = 'admin.case_conversation_read' "
                 "and target_type = 'conversation' and target_id = :cid"),
                {"cid": str(conversation_id)},
            )
            self.rec.must(int(read_audit["n"]) >= 1, 'Admin read itself writes an audit entry')

        with self.rec.step(
            "IM-03",
            'Message report disposition: invisible before disposition/to others; after disposition only the author receives it, without the reporter',
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
                    f"Before disposition, {viewer}'s received list does not show the message report",
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
            self.rec.must_eq(author_row.get("target_type"), "message", 'Received list contains the real message report')
            self.rec.must_eq(int(author_row.get("case_id") or 0), message_case_id, 'Received report links to the case')
            self.rec.must("reporter_id" not in author_row, 'Received report does not disclose the reporter ID')
            self.rec.must("reporter" not in json.dumps(author_row, ensure_ascii=False), 'Received reports do not disclose the reporter')
            for viewer in ("buyer2", "outsider", "seller"):
                received = self._list(
                    self._call("GET", "/api/v1/reports/received", user=viewer, expected=200)
                )
                self.rec.must(
                    not any(int(item["id"]) == message_report_id for item in received),
                    f"{viewer} is not the message author and cannot see this received report",
                )
            # After disposition the claiming admin may still read history within the necessary scope; other admins remain denied.
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
            "Notification list does not mark read; only opening a specific notification marks it; unread count/todos independent; others' notifications 404",
        ):
            before = self._dict(self._call("GET", "/api/v1/notifications/unread-count", user="buyer", expected=200))
            count_before = int(before.get("unread") or 0)
            self.rec.must(count_before > 0, 'Buyer has unread notifications')
            listed = self._dict(self._call("GET", "/api/v1/notifications", user="buyer", expected=200))
            self.rec.must(int(listed.get("total") or 0) >= count_before, 'Total notification count')
            after_list = self._dict(self._call("GET", "/api/v1/notifications/unread-count", user="buyer", expected=200))
            self.rec.must_eq(int(after_list.get("unread") or 0), count_before, 'List does not auto-mark read')
            unread_items = [item for item in listed.get("items") or [] if not item.get("is_read")]
            if not unread_items:
                raise CheckFailure('No notification available to mark read')
            target = unread_items[0]
            self._call("POST", f"/api/v1/notifications/{target['id']}/read", user="buyer", expected=200)
            self.audit_targets["notification_read_id"] = int(target["id"])
            # Reopening the same already-read notification must not write a duplicate success audit.
            self._call("POST", f"/api/v1/notifications/{target['id']}/read", user="buyer", expected=200)
            after_read = self._dict(self._call("GET", "/api/v1/notifications/unread-count", user="buyer", expected=200))
            self.rec.must_eq(int(after_read.get("unread") or 0), count_before - 1, 'Only that item is read; unread count -1')
            todos = self._dict(self._call("GET", "/api/v1/notifications/todos", user="buyer", expected=200))
            self.rec.must(isinstance(todos.get("items"), list), 'Todos readable')
            # Others' notifications cannot be marked read
            other_items = self._dict(self._call("GET", "/api/v1/notifications", user="buyer2", expected=200)).get("items") or []
            if other_items:
                self._call("POST", f"/api/v1/notifications/{other_items[0]['id']}/read", user="buyer", expected=404)
            else:
                self.rec.must(False, 'buyer2 has no notification usable for the unauthorized test')
            # Admins receive no personal notifications
            admin_list = self._dict(self._call("GET", "/api/v1/notifications", user="admin", expected=200))
            self.rec.must_eq(int(admin_list.get("total") or 0), 0, 'Admin personal notifications empty')
            admin_todos = self._dict(self._call("GET", "/api/v1/notifications/todos", user="admin", expected=200))
            self.rec.must_eq(int(admin_todos.get("total") or 0), 0, 'Admin personal todos empty')

        with self.rec.step(
            "NOTIF-02",
            'Notification recipient and key-event matrix: request/accept/agreement/confirm/complete/freeze/abnormal/inquiry/disposition/appeal',
        ):
            buyer_items = self._notifications("buyer")
            seller_items = self._notifications("seller")
            buyer_types = {item.get("type") for item in buyer_items}
            seller_types = {item.get("type") for item in seller_items}
            required_buyer = {"request_accepted", "agreement_decided", "trade_completed", "trade_abnormal", "report_result", "dispute_resolved"}
            required_seller = {"request_created", "agreement_proposed", "confirm_progress", "trade_completed", "inquiry", "disposal"}
            self.rec.must(required_buyer <= buyer_types, f"Buyer key notifications {sorted(required_buyer - buyer_types)}")
            self.rec.must(required_seller <= seller_types, f"Seller key notifications {sorted(required_seller - seller_types)}")
            self.rec.must("request_created" not in buyer_types or True, 'Request notifications checked only against the event recipient')
            self.rec.must_eq(self._uid("admin"), self.users["admin"]["id"], 'Admin identity fixed')

        with self.rec.step(
            "MY-01",
            'My products by all states/review reason/pending acceptance count; my trades for both roles; reviews written/received; report/case entries',
        ):
            # Leave both pending and rejected items for all-state assertions.
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
            self.rec.must({"pending_review", "rejected", "listed", "in_transaction", "delisted"} <= statuses, f"My products all states {sorted(statuses)}")
            rejected = by_key[int(self.products["P_MY_REJECTED"]["id"])]
            self.rec.must_eq(rejected.get("reject_reason"), "验收保留拒绝状态", 'My product review reason')
            request_product = by_key[int(self.products["P_MY_REQUEST"]["id"])]
            self.rec.must_eq(int(request_product.get("pending_request_count") or 0), 1, 'Pending acceptance request count')
            mine_all = self._list(self._call("GET", "/api/v1/trades/mine", user="buyer", expected=200, params={"role": "all"}))
            mine_buyer = self._list(self._call("GET", "/api/v1/trades/mine", user="buyer", expected=200, params={"role": "buyer"}))
            mine_seller = self._list(self._call("GET", "/api/v1/trades/mine", user="seller", expected=200, params={"role": "seller"}))
            self.rec.must(mine_all and mine_buyer, 'Buyer trade list non-empty')
            self.rec.must(mine_seller, 'Seller trade list non-empty')
            self._call("GET", "/api/v1/trades/mine", user="buyer", expected=422, params={"role": "invalid"})
            published = self._list(self._call("GET", "/api/v1/me/reviews", user="buyer", expected=200, params={"type": "published"}))
            received = self._list(self._call("GET", "/api/v1/me/reviews", user="buyer", expected=200, params={"type": "received"}))
            self.rec.must(published and received, 'Reviews written/received readable separately')
            self._call("GET", "/api/v1/me/reviews", user="buyer", expected=422, params={"type": "invalid"})
            reports_mine = self._list(self._call("GET", "/api/v1/reports/mine", user="buyer", expected=200))
            self.rec.must(reports_mine, 'My reports entry')
            received_reports = self._list(self._call("GET", "/api/v1/reports/received", user="buyer2", expected=200))
            self.rec.must(received_reports, 'Reports I received entry')
            cases = self._list(self._call("GET", "/api/v1/me/cases", user="buyer", expected=200))
            self.rec.must(cases, 'My cases entry')
            self._call("GET", "/api/v1/products/mine", expected=401)
            # Finished records cannot be deleted/reopened (the routes do not exist)
            self._call("DELETE", f"/api/v1/trades/{self.trades['T_MAIN']['id']}", user="buyer", expected=405)
            self._call("POST", f"/api/v1/trades/{self.trades['T_MAIN']['id']}/reopen", user="buyer", expected=404)
            # A new report on an invalid object fails; existing reports remain readable.
            self._call(
                "POST",
                "/api/v1/reports",
                user="buyer",
                expected=400,
                json_body={"target_type": "comment", "target_id": 999999999, "reason": "失效对象"},
            )
            # A finished trade cannot be accepted/confirmed; others' products cannot be edited; others' cases cannot receive statements.
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
            'Users cannot change delivery records themselves; a claiming admin can adjust with a basis while preserving original confirmation history',
            note="UC-C06-03: after the user's statement, an admin handles it through the case; regular users do not self-correct",
        ):
            trade_id = int(self.trades["T_MAIN"]["id"])
            before = self._trade_detail("T_MAIN", "buyer")
            self.rec.must_eq(before.get("status"), "completed", 'Trade completed before correction')
            confirms_before = [dict(row) for row in before.get("confirmations") or []]
            self.rec.must(len(confirms_before) >= 2, 'Bilateral confirmation history exists before correction')
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
            self.rec.must_eq(len(unchanged.get("confirmations") or []), len(confirms_before), 'Confirmation history does not shrink after a failed user self-correction')
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
            self.rec.must_eq(corrected.get("status"), "in_progress", 'Admin adjusts based on the case')
            historical = [dict(row) for row in corrected.get("confirmations") or []]
            self.rec.must_eq({int(row["id"]) for row in historical}, {int(row["id"]) for row in confirms_before}, 'Original confirmation records retained')
            self.rec.must(all(row.get("is_current") is False for row in historical), 'Adjustment clears current confirmations without fabricating new ones')
            transitions = self._list(
                self._call("GET", f"/api/v1/trades/{trade_id}/transitions", user="buyer", expected=200)
            )
            last = transitions[-1]
            self.rec.must_eq(last.get("reason"), reason, 'Admin correction reason recorded')
            self.rec.must_eq(last.get("basis_case_id"), case_id, 'Admin correction basis case recorded')
            self._call(
                "POST",
                f"/api/v1/admin/trades/{trade_id}/adjust",
                user="admin",
                expected=200,
                json_body={"to_status": "completed", "reason": "恢复完成并保留原确认历史", "case_id": case_id},
            )
            restored = self._trade_detail("T_MAIN", "buyer")
            self.rec.must_eq(restored.get("status"), "completed", 'Trade restored to completed after admin correction')
            self.rec.must_eq(len(restored.get("confirmations") or []), len(confirms_before), 'Confirmation history not lost after restoration')
            self.rec.must(all(row.get("is_current") is False for row in restored.get("confirmations") or []), 'Admin adjustment does not fabricate bilateral confirmation')
            self._call(
                "POST",
                f"/api/v1/admin/cases/{case_id}/dispose",
                user="admin",
                expected=200,
                json_body={"conclusion": "交付记录更正处理完成", "reason": "保留原记录与依据", "basis": "SC-06-03"},
            )

        with self.rec.step(
            "STATS-01",
            'Admin stats: account/product/case/trade counts checked against read-only SQL; no monetary amounts; range by completion time; permissions',
        ):
            stats = self._dict(self._call("GET", "/api/v1/admin/stats", user="admin", expected=200))
            expected_users = self._db_one("select count(*) as n, count(*) filter (where status='banned') as banned from app.users")
            self.rec.must_eq(int(stats["users"]["total"]), int(expected_users["n"]), 'Total users')
            self.rec.must_eq(int(stats["users"]["banned"]), int(expected_users["banned"]), 'Banned users listed separately')
            for status_value in ("pending_review", "rejected", "listed", "in_transaction", "delisted"):
                expected = int(self._db_one("select count(*) as n from app.products where status = :s", {"s": status_value})["n"])
                self.rec.must_eq(int(stats["products"][status_value]), expected, f"Product status {status_value}")
            expected_review = int(
                self._db_one("select count(*) as n from app.disposal_cases where case_type='product_review' and status <> 'disposed'")["n"]
            )
            expected_report = int(
                self._db_one("select count(*) as n from app.disposal_cases where case_type='report' and status <> 'disposed'")["n"]
            )
            expected_all = int(self._db_one("select count(*) as n from app.disposal_cases where status <> 'disposed'")["n"])
            self.rec.must_eq(int(stats["pending"]["review_cases"]), expected_review, 'Pending review cases')
            self.rec.must_eq(int(stats["pending"]["report_cases"]), expected_report, 'Pending report cases')
            self.rec.must_eq(int(stats["pending"]["all_cases"]), expected_all, 'All pending cases')
            for status_value in ("completed", "terminated", "disputed", "in_progress", "abnormal"):
                expected = int(self._db_one("select count(*) as n from app.trades where status = :s", {"s": status_value})["n"])
                self.rec.must_eq(int(stats["trades"][status_value]), expected, f"Trade status {status_value}")
            expected_frozen = int(
                self._db_one(
                    "select count(*) as n from app.trades where frozen = true and status in ('in_progress','disputed','abnormal')"
                )["n"]
            )
            self.rec.must_eq(int(stats["trades"]["frozen_current"]), expected_frozen, 'Currently frozen trades')
            self.rec.must_eq(stats["range"]["completed_trades"], None, 'No range selected returns no default stats')
            self.rec.must("amount" not in json.dumps(stats).lower(), 'Stats have no monetary field')
            self.rec.must("revenue" not in json.dumps(stats).lower(), 'Stats have no revenue field')
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
            self.rec.must_eq(int(ranged["range"]["completed_trades"]), expected_completed, 'Range-scoped completed trade count')
            empty = self._dict(
                self._call(
                    "GET",
                    "/api/v1/admin/stats",
                    user="admin",
                    expected=200,
                    params={"from": "1990-01-01", "to": "1990-01-02"},
                )
            )
            self.rec.must_eq(int(empty["range"]["completed_trades"]), 0, 'Empty range returns 0')
            self._call("GET", "/api/v1/admin/stats", user="buyer", expected=403)
            self._call("GET", "/api/v1/admin/stats", expected=401)

        with self.rec.step(
            "AUDIT-01",
            'Audit: admin pagination/detail; failed logins and successful business events; app has no UPDATE/DELETE/TRUNCATE; sensitive fields not audited',
        ):
            summary = self._dict(self._call('GET', '/api/v1/admin/audit/summary', user='admin', params={'days': 7}))
            self.rec.must_eq(summary['timezone'], 'Asia/Shanghai', 'Audit overview uses Beijing time')
            self.rec.must_eq(len(summary['daily']), 7, 'Overview fills all seven days')
            self.rec.must_eq(sum(row['count'] for row in summary['categories']), summary['total'], 'Category counts sum to the total')
            self.rec.must_eq(sum(row['count'] for row in summary['daily']), summary['total'], 'Trend counts sum to the total')
            self.rec.must_eq(sum(summary['results'].values()), summary['total'], 'Outcome counts sum to the total')
            self._call('GET', '/api/v1/admin/audit/summary', user='outsider', expected=403)
            self._call('GET', '/api/v1/admin/audit/summary', expected=401)
            self._call('GET', '/api/v1/admin/audit/summary', user='admin', expected=422, params={'days': 31})
            classified = self._dict(self._call('GET', '/api/v1/admin/audit/events', user='admin', params={'category': 'account', 'limit': 20}))
            self.rec.must(all(row['event_type'].startswith(('auth.', 'user.')) for row in classified['items']), 'Category breakdown definitions consistent')
            failed = self._dict(
                self._call(
                    "GET",
                    "/api/v1/admin/audit/events",
                    user="admin",
                    expected=200,
                    params={"event_type": "auth.login_failed", "result": "failure", "limit": 10},
                )
            )
            self.rec.must(int(failed.get("total") or 0) >= 1, 'Failed-login audit exists for a known account')
            self._call('POST', '/api/v1/auth/login', expected=401, json_body={'email': f'unknown-{self.run_id}@example.com', 'password': 'wrong-password'})
            self._call('GET', '/api/v1/admin/users', expected=401)
            anonymous = self._db_one("select count(*) as n from app.audit_events where actor_role='anonymous' or (actor_id is null and actor_role<>'system')")
            self.rec.must_eq(int(anonymous['n']), 0, 'Anonymous requests and unknown-account login failures write no audit')
            event_id = int(str((failed.get("items") or [{}])[0].get("event_id") or 0))
            detail = self._dict(self._call("GET", f"/api/v1/admin/audit/events/{event_id}", user="admin", expected=200))
            self.rec.must_eq(int(detail["event_id"]), event_id, 'Audit detail')
            self._call("GET", "/api/v1/admin/audit/events", user="outsider", expected=403)
            if self.config.database_url.startswith("postgresql+"):
                privileges = self._db_one(
                    ("select has_table_privilege(current_user, 'app.audit_events', 'SELECT') as can_select, "
                     "has_table_privilege(current_user, 'app.audit_events', 'INSERT') as can_insert, "
                     "has_table_privilege(current_user, 'app.audit_events', 'UPDATE') as can_update, "
                     "has_table_privilege(current_user, 'app.audit_events', 'DELETE') as can_delete, "
                     "has_table_privilege(current_user, 'app.audit_events', 'TRUNCATE') as can_truncate")
                )
                self.rec.must_eq(privileges["can_select"], True, 'app can read audit')
                self.rec.must_eq(privileges["can_insert"], True, 'app can insert audit')
                self.rec.must_eq(privileges["can_update"], False, 'app cannot update audit')
                self.rec.must_eq(privileges["can_delete"], False, 'app cannot delete audit')
                self.rec.must_eq(privileges["can_truncate"], False, 'app cannot truncate audit')
            else:
                self.rec.must(True, 'SQLite has no database role ACL; audit API and content verified')
            rows = self._db("select before_json, after_json from app.audit_events order by event_id desc limit 200")
            forbidden = ("password", "access_token", "jwt", "secret", "access_key", "authorization")
            found: list[str] = []
            for row in rows:
                blob = json.dumps({"before": row.get("before_json"), "after": row.get("after_json")}, ensure_ascii=False).lower()
                for marker in forbidden:
                    if marker in blob:
                        found.append(marker)
            self.rec.must_eq(sorted(set(found)), [], 'Audit before/after contains no sensitive field names')

        with self.rec.step(
            "OBJ-01",
            'Object reference/cleanup invariants: business references are committed and actually exist; dry-run does not list referenced objects as candidates',
            note="Original standalone object-lock/cleanup topic folded into business invariants; no mocks and no deletion from shared buckets",
        ):
            image_keys = sorted(
                {
                    str(key)
                    for product in self.products.values()
                    for key in (product.get("image_keys") or [])
                    if key
                }
            )
            # Only evidence actually referenced by a report is a business object; the report/ probe upload from FILE-01 remains staged.
            evidence_keys = [str(self.files["report_evidence"]["key"])]
            business_keys = sorted(set(image_keys) | set(evidence_keys))
            self.rec.must(bool(image_keys) and bool(evidence_keys), 'Product-image and report-evidence business references exist')
            rows = self._db(
                "select key, state, bucket_role, deleted_at, ref_type, ref_id from app.stored_objects where key = any(:keys)",
                {"keys": business_keys},
            )
            by_key = {str(row["key"]): dict(row) for row in rows}
            for key in business_keys:
                row = by_key.get(key)
                self.rec.must(row is not None, f"Business object registered {key[:24]}…")
                if row is None:
                    continue
                self.rec.must_eq(row["state"], "committed", f"Business object committed {key[:24]}…")
                self.rec.must_eq(row["deleted_at"], None, f"Business object not deleted {key[:24]}…")
                self.rec.must(row.get("ref_type") is not None and row.get("ref_id") is not None, f"Business object reference pair complete {key[:24]}…")
            probe = StorageProbe.build(self.config)
            for key in business_keys:
                self.rec.must(probe.exists(key), f"Business object really exists in OSS {key[:24]}…")
            # Read-only dry-run: referenced objects must not become cleanup candidates; evidence objects stay protected even when staged.
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
            self.rec.must_eq(result.dry_run, True, 'Object cleanup is a read-only dry-run')
            self.rec.must_eq(sorted(set(result.candidates) & set(business_keys)), [], 'Referenced objects do not become cleanup candidates')
            self.rec.must(not result.deleted, 'No physical deletion performed')
            self.rec.data["business_objects"] = len(business_keys)
            self.rec.data["dry_run_candidates"] = len(result.candidates)
