"""验收核心：OpenAPI 路由归一化、真实 HTTP 客户端、步骤记录与断言。"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


class CheckFailure(AssertionError):
    """可安全写入报告的断言失败（不含响应正文/凭据）。"""


def _short(value: Any, limit: int = 300) -> str:
    text = str(value).replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


class RouteIndex:
    """把真实请求路径映射回 OpenAPI 规范模板。"""

    def __init__(self, openapi: Mapping[str, Any]) -> None:
        self.templates: list[tuple[str, str, re.Pattern[str]]] = []
        self.exact: dict[str, str] = {}
        for path, item in (openapi.get("paths") or {}).items():
            if not isinstance(path, str):
                continue
            for method in item:
                if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                method_upper = method.upper()
                if "{" not in path:
                    self.exact[f"{method_upper} {path}"] = path
                    continue
                escaped = re.escape(path)
                if path.startswith("/api/v1/files/{key}"):
                    pattern = escaped.replace(r"\{key\}", r".+")
                else:
                    pattern = re.sub(r"\\\{[^}]+\\\}", r"[^/]+", escaped)
                self.templates.append((method_upper, path, re.compile(rf"^{pattern}$")))
        # 更具体的模板优先：参数更少者先匹配，再比较静态长度。
        self.templates.sort(key=lambda row: (row[1].count("{"), -len(row[1].replace("{", ""))))

    @property
    def business_routes(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for key, path in self.exact.items():
            method = key.split(" ", 1)[0]
            if path == "/api/health":
                continue
            rows.append((method, path))
        for method, path, _ in self.templates:
            rows.append((method, path))
        return sorted(set(rows), key=lambda row: (row[1], row[0]))

    def resolve(self, method: str, actual_path: str) -> str | None:
        key = f"{method.upper()} {actual_path}"
        if key in self.exact:
            return actual_path
        for route_method, template, pattern in self.templates:
            if route_method == method.upper() and pattern.match(actual_path):
                return template
        return None


@dataclass
class CallRecord:
    seq: int
    check_id: str
    method: str
    actual_path: str
    template: str | None
    status: int | str
    duration_ms: float
    role: str
    expected: list[int]
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "check_id": self.check_id,
            "method": self.method,
            "path_template": self.template or "<unmatched>",
            "actual_path": self.actual_path,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "role": self.role,
            "expected": self.expected,
            "note": self.note,
        }


class ApiClient:
    """真实 HTTP 客户端；只记录方法/模板/状态，不保存响应正文或查询串。"""

    def __init__(self, base_url: str, route_index: RouteIndex, *, timeout: float = 40.0) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise CheckFailure("base_url 必须是 http(s) 地址")
        if parsed.username or parsed.password:
            raise CheckFailure("base_url 不能包含凭据")
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.route_index = route_index
        self.client = httpx.Client(
            base_url=self.origin,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "application/json"},
        )
        self.calls: list[CallRecord] = []
        self.allowed_storage_hosts: set[str] = set()
        self.current_check: str = "setup"
        self.current_role: str = "anonymous"

    def close(self) -> None:
        self.client.close()

    def _path_only(self, path: str) -> str:
        return urlsplit(path).path or "/"

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        expected: int | Sequence[int] | None = 200,
        json_body: Any = None,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        note: str = "",
    ) -> httpx.Response:
        method = method.upper()
        actual_path = self._path_only(path)
        template = self.route_index.resolve(method, actual_path)
        allowed = [] if expected is None else [expected] if isinstance(expected, int) else list(expected)
        request_headers = {"Accept": "application/json"}
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        if headers:
            request_headers.update(headers)
        started = time.monotonic()
        request_kwargs: dict[str, Any] = {
            "headers": request_headers,
            "json": json_body,
            "data": data,
            "files": files,
        }
        if params:
            request_kwargs["params"] = dict(params)
        if content is not None:
            request_kwargs["content"] = content
        try:
            response = self.client.request(method, path, **request_kwargs)
        except httpx.HTTPError as exc:
            self.calls.append(
                CallRecord(
                    len(self.calls) + 1,
                    self.current_check,
                    method,
                    actual_path,
                    template,
                    "ERR",
                    round((time.monotonic() - started) * 1000, 1),
                    self.current_role,
                    allowed,
                    note or type(exc).__name__,
                )
            )
            raise CheckFailure(f"{method} {actual_path} 请求失败（{type(exc).__name__}）") from None
        duration = round((time.monotonic() - started) * 1000, 1)
        self.calls.append(
            CallRecord(
                len(self.calls) + 1,
                self.current_check,
                method,
                actual_path,
                template,
                response.status_code,
                duration,
                self.current_role,
                allowed,
                note,
            )
        )
        if allowed and response.status_code not in allowed:
            raise CheckFailure(
                f"{method} {actual_path} 返回 {response.status_code}，预期 {allowed}"
                + (f"（{note}）" if note else "")
            )
        return response

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)

    @staticmethod
    def json_of(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            raise CheckFailure(f"HTTP {response.status_code} 响应不是 JSON") from None

    @staticmethod
    def dict_of(response: httpx.Response) -> dict[str, Any]:
        value = ApiClient.json_of(response)
        if not isinstance(value, dict):
            raise CheckFailure("响应不是 JSON 对象")
        return value

    @staticmethod
    def list_of(response: httpx.Response) -> list[Any]:
        value = ApiClient.json_of(response)
        if not isinstance(value, list):
            raise CheckFailure("响应不是 JSON 数组")
        return value

    def signed_get(self, url: str, *, expected: int = 200) -> httpx.Response:
        parsed = urlsplit(url)
        origin = urlsplit(self.origin)
        if not parsed.scheme and not parsed.netloc:
            # 后端返回站内相对签名 URL；补 base origin，仍不记录查询串。
            target = self.origin + (url if url.startswith("/") else "/" + url)
            parsed = urlsplit(target)
        elif parsed.netloc != origin.netloc:
            if parsed.scheme != 'https' or parsed.netloc not in self.allowed_storage_hosts or parsed.username or parsed.password:
                raise CheckFailure('签名 URL 主机不在配置的存储白名单')
        safe_path = parsed.path or "/"
        try:
            response = self.client.get(parsed.geturl())
        except httpx.HTTPError as exc:
            raise CheckFailure(f"GET {safe_path} 请求失败（{type(exc).__name__}）") from None
        self.calls.append(
            CallRecord(
                len(self.calls) + 1,
                self.current_check,
                "GET",
                safe_path,
                self.route_index.resolve("GET", safe_path),
                response.status_code,
                0.0,
                self.current_role,
                [expected],
                "signed-download",
            )
        )
        if response.status_code != expected:
            raise CheckFailure(f"GET {safe_path} 返回 {response.status_code}，预期 {expected}")
        return response


@dataclass
class CheckRecord:
    check_id: str
    title: str
    status: str
    note: str | None
    assertions: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0
    call_seq: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "title": self.title,
            "status": self.status,
            "note": self.note,
            "assertions": self.assertions,
            "data": self.data,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "call_seq": self.call_seq,
        }


class Recorder:
    def __init__(self, api: ApiClient) -> None:
        self.api = api
        self.checks: list[CheckRecord] = []
        self._stack: list[CheckRecord] = []

    def must(self, condition: Any, message: str) -> None:
        if not condition:
            raise CheckFailure(message)
        self._assertion(f"OK: {message}")

    def must_eq(self, actual: Any, expected: Any, message: str) -> None:
        if actual != expected:
            raise CheckFailure(f"{message}：实际 {actual!r}，预期 {expected!r}")
        self._assertion(f"OK: {message} = {expected!r}")

    def must_in(self, member: Any, container: Iterable[Any], message: str) -> None:
        if member not in container:
            raise CheckFailure(f"{message}：{member!r} 不在预期集合")
        self._assertion(f"OK: {message}")

    def _assertion(self, text: str) -> None:
        if self._stack:
            self._stack[-1].assertions.append(_short(text, 500))

    def _set_check(self, check_id: str) -> None:
        self.api.current_check = check_id

    def step(
        self,
        check_id: str,
        title: str,
        *,
        note: str | None = None,
    ) -> Any:
        outer = self
        rec = CheckRecord(
            check_id=check_id,
            title=title,
            status=FAIL,
            note=note,
        )

        class _Ctx:
            def __enter__(self) -> Recorder:
                outer._stack.append(rec)
                outer._set_check(check_id)
                self.started = time.monotonic()
                self.first_call = len(outer.api.calls)
                return outer

            def __exit__(self, exc_type, exc, tb) -> bool:
                rec.duration_ms = round((time.monotonic() - self.started) * 1000, 1)
                rec.call_seq = [c.seq for c in outer.api.calls[self.first_call :]]
                if exc_type is None:
                    rec.status = PASS
                elif issubclass(exc_type, CheckFailure):
                    rec.status = FAIL
                    rec.error = _short(exc)
                else:
                    rec.status = FAIL
                    rec.error = f"{exc_type.__name__}: {_short(exc)}"
                outer._stack.pop()
                outer.checks.append(rec)
                return True

        return _Ctx()

    def skip(self, check_id: str, title: str, *, reason: str) -> None:
        self.checks.append(
            CheckRecord(
                check_id=check_id,
                title=title,
                status=SKIP,
                note=reason,
            )
        )

    @property
    def data(self) -> dict[str, Any]:
        if not self._stack:
            return {}
        return self._stack[-1].data

    def counts(self) -> dict[str, int]:
        result = {PASS: 0, FAIL: 0, SKIP: 0}
        for check in self.checks:
            result[check.status] = result.get(check.status, 0) + 1
        return result
