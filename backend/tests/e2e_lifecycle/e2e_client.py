"""真实 HTTP 客户端：鉴权、JSON 请求、预期状态码、调用日志与 5xx 侦测。

所有测试必须通过本客户端直接请求运行中的开发服务（默认 http://127.0.0.1:8000），
不使用 ASGI 内存传输，不绕过接口直接写库（超时场景的计时起点前移除外，见 p08 说明）。
"""

from __future__ import annotations

import time
from typing import Any

import httpx


class CheckFailed(AssertionError):
    """检查项失败；可携带实际响应，便于报告记录实际状态码与响应体。"""

    def __init__(self, message: str, response: httpx.Response | None = None):
        self.response = response
        self.status_code = response.status_code if response is not None else None
        self.body = ""
        if response is not None:
            try:
                self.body = response.text
            except (UnicodeError, LookupError):  # pragma: no cover - 极端编码问题
                self.body = "<response body not decodable>"
            message = (
                f"{message} | 实际 HTTP {response.status_code} "
                f"{response.request.method} {response.request.url.path}"
                + (f" | 响应：{self.body[:600]}" if self.body else "")
            )
        super().__init__(message)


class Api:
    """对 /api/v1 的真实 HTTP 封装；每次调用都计入运行日志。"""

    def __init__(self, base_url: str, recorder, timeout: float = 40.0):
        self.base_url = base_url.rstrip("/")
        self.api_url = self.base_url + "/api/v1"
        self.recorder = recorder
        self.client = httpx.Client(base_url=self.api_url, timeout=timeout, follow_redirects=False)
        self.calls: list[dict[str, Any]] = []

    # -- 基础设施 ---------------------------------------------------------
    def close(self) -> None:
        self.client.close()

    def _record(self, method: str, path: str, status: Any, duration_ms: float, note: str = "") -> None:
        self.calls.append(
            {"method": method, "path": path, "status": status, "duration_ms": round(duration_ms, 1), "note": note}
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        expected: int | tuple[int, ...] | list[int] | None = None,
        json_body: Any = None,
        params: dict | None = None,
        data: dict | None = None,
        files: dict | None = None,
        headers: dict | None = None,
    ) -> httpx.Response:
        hdrs: dict[str, str] = {"Accept": "application/json"}
        if headers:
            hdrs.update(headers)
        if token:
            hdrs["Authorization"] = f"Bearer {token}"
        started = time.monotonic()
        try:
            resp = self.client.request(
                method, path, json=json_body, params=params, data=data, files=files, headers=hdrs
            )
        except httpx.HTTPError as exc:
            self._record(method, path, "ERR", (time.monotonic() - started) * 1000, str(exc)[:200])
            raise CheckFailed(f"请求失败（{method} {path}）：{exc}") from exc
        duration = (time.monotonic() - started) * 1000
        self._record(method, path, resp.status_code, duration)
        if resp.status_code >= 500:
            self.recorder.defect(
                "server_5xx",
                {
                    "method": method,
                    "path": path,
                    "status": resp.status_code,
                    "body": resp.text[:800],
                },
            )
        if expected is not None:
            allowed = (expected,) if isinstance(expected, int) else tuple(expected)
            if resp.status_code not in allowed:
                raise CheckFailed(f"预期状态码 {allowed}，实际 {resp.status_code}（{method} {path}）", resp)
        return resp

    # -- 便捷方法 ---------------------------------------------------------
    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs) -> httpx.Response:
        return self.request("PATCH", path, **kwargs)

    def put(self, path: str, **kwargs) -> httpx.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)

    # -- 常用断言 ---------------------------------------------------------
    @staticmethod
    def json_of(response: httpx.Response) -> Any:
        if not response.content:
            return None
        return response.json()

    def ok_json(self, response: httpx.Response) -> Any:
        if response.status_code >= 400:
            raise CheckFailed("请求未成功", response)
        return self.json_of(response)

    def expect_status(self, response: httpx.Response, status: int | tuple[int, ...], message: str = "") -> httpx.Response:
        allowed = (status,) if isinstance(status, int) else tuple(status)
        if response.status_code not in allowed:
            raise CheckFailed(message or f"预期状态码 {allowed}", response)
        return response
