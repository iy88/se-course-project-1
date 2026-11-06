"""Safe runtime observations shared by HTTP, SQL and realtime layers.

Only counters, durations and stable error categories are recorded. SQL
statements, bind parameters, tokens, URLs and message bodies never enter the
snapshot. In-process values are diagnostic hints for one worker; durable outbox
age and delivery counters are queried from PostgreSQL/Redis where correctness
matters.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import re
import threading
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

_SECRET_QUERY_RE = re.compile(r"([?&](?:ticket|token)=)[^&\s\"']+", re.IGNORECASE)


class RedactSecretsFilter(logging.Filter):
    """Keep one-time tickets and legacy query tokens out of access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _SECRET_QUERY_RE.sub(r"\1[redacted]", record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                _SECRET_QUERY_RE.sub(r"\1[redacted]", item) if isinstance(item, str) else item
                for item in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: (_SECRET_QUERY_RE.sub(r"\1[redacted]", value) if isinstance(value, str) else value)
                for key, value in record.args.items()
            }
        return True


def install_log_redaction() -> None:
    for name in ("", "uvicorn", "uvicorn.access", "uvicorn.error"):
        target = logging.getLogger(name)
        if not any(isinstance(item, RedactSecretsFilter) for item in target.filters):
            target.addFilter(RedactSecretsFilter())

_REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("observability_request_id", default=None)
_SQL_COUNT: contextvars.ContextVar[int] = contextvars.ContextVar("observability_sql_count", default=0)
_SQL_MS: contextvars.ContextVar[float] = contextvars.ContextVar("observability_sql_ms", default=0.0)
_SQL_START: contextvars.ContextVar[float | None] = contextvars.ContextVar("observability_sql_start", default=None)
_DB_REQUEST_START: contextvars.ContextVar[float | None] = contextvars.ContextVar("observability_db_start", default=None)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class Counters:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, float] = {}

    def incr(self, name: str, amount: float = 1.0) -> None:
        with self._lock:
            self._values[name] = self._values.get(name, 0.0) + amount

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            self._values[name + ".count"] = self._values.get(name + ".count", 0.0) + 1
            self._values[name + ".sum"] = self._values.get(name + ".sum", 0.0) + value
            current_max = self._values.get(name + ".max", 0.0)
            if value > current_max:
                self._values[name + ".max"] = value

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            return {key: round(value, 3) if isinstance(value, float) else value
                    for key, value in sorted(self._values.items())}

    def reset(self) -> None:
        with self._lock:
            self._values.clear()


counters = Counters()


def clean_request_id(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    return candidate if _REQUEST_ID_RE.fullmatch(candidate) else None


def current_request_id() -> str | None:
    return _REQUEST_ID.get()


def current_sql() -> tuple[int, float]:
    return _SQL_COUNT.get(), _SQL_MS.get()


def mark_db_request_start() -> None:
    _DB_REQUEST_START.set(time.perf_counter())


def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
    if _SQL_COUNT.get() == 0:
        started = _DB_REQUEST_START.get()
        if started is not None:
            counters.observe("db.first_sql_wait_ms", (time.perf_counter() - started) * 1000)
    _SQL_START.set(time.perf_counter())


def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
    started = _SQL_START.get()
    if started is None:
        return
    _SQL_START.set(None)
    _SQL_COUNT.set(_SQL_COUNT.get() + 1)
    _SQL_MS.set(_SQL_MS.get() + (time.perf_counter() - started) * 1000)
    counters.incr("sql.statements")


def install_sql_observers(engine: Any) -> None:
    """Attach listeners exactly once per engine; no statement text is retained."""
    from sqlalchemy import event

    sync_engine = getattr(engine, "sync_engine", engine)
    if getattr(sync_engine, "_dsh_observability", False):
        return
    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(sync_engine, "after_cursor_execute", _after_cursor_execute)
    sync_engine._dsh_observability = True  # type: ignore[attr-defined]


class ObservabilityMiddleware:
    """Pure ASGI middleware to keep request IDs identical across audit logs."""

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = list(scope.get("headers", []))
        supplied = None
        for key, value in headers:
            if key == b"x-request-id":
                supplied = clean_request_id(value.decode("latin-1", "ignore"))
                break
        request_id = supplied or uuid.uuid4().hex
        headers = [(k, v) for k, v in headers if k != b"x-request-id"] + [(b"x-request-id", request_id.encode())]
        scope = dict(scope)
        scope["headers"] = headers
        token = _REQUEST_ID.set(request_id)
        _SQL_COUNT.set(0)
        _SQL_MS.set(0)
        _SQL_START.set(None)
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status
            if message.get("type") == "http.response.start":
                status = int(message.get("status", 500))
                raw = list(message.get("headers", []))
                raw = [(k, v) for k, v in raw if k != b"x-request-id"] + [(b"x-request-id", request_id.encode())]
                message = dict(message)
                message["headers"] = raw
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            sql_count, sql_ms = current_sql()
            counters.observe("http.request_ms", elapsed_ms)
            counters.incr(f"http.status.{status // 100}xx")
            counters.observe("http.sql_ms", sql_ms)
            counters.observe("http.sql_count", float(sql_count))
            if elapsed_ms >= 1000:
                logger.warning(
                    "slow request path=%s status=%s duration_ms=%.1f sql_count=%d request_id=%s",
                    scope.get("path", ""), status, elapsed_ms, sql_count, request_id,
                )
            _REQUEST_ID.reset(token)


def install_observability(app: Any) -> None:
    install_log_redaction()
    app.add_middleware(ObservabilityMiddleware)

    @app.get("/api/health/observability", include_in_schema=False)
    async def observability_snapshot(request: Request) -> dict:
        """Process-local diagnostics; never returns SQL text or user data."""
        return {
            "request_id": current_request_id(),
            "role": getattr(request.app.state, "role", "combined"),
            "protocol_version": getattr(request.app.state, "protocol_version", 0),
            "release_id": getattr(request.app.state, "release_id", ""),
            "counters": counters.snapshot(),
            "sql_pool": _pool_snapshot(),
        }


def _pool_snapshot() -> dict[str, int]:
    try:
        from app.db.session import get_engine

        pool = get_engine().pool
        return {
            "checkedout": int(pool.checkedout()),
            "overflow": int(getattr(pool, "overflow", lambda: -1)()),
            "size": int(getattr(pool, "size", lambda: -1)()),
        }
    except Exception:  # noqa: BLE001 - diagnostics must not fail a request
        return {"checkedout": -1, "overflow": -1, "size": -1}


@contextlib.asynccontextmanager
async def timed(operation: str) -> AsyncIterator[None]:
    started = time.perf_counter()
    ok = False
    try:
        yield
        ok = True
    finally:
        counters.observe(operation, (time.perf_counter() - started) * 1000)
        if not ok:
            counters.incr(operation + ".errors")


async def probe_event_loop_lag(interval: float = 1.0) -> None:
    """Record scheduling lag without spawning threads or reading user data."""
    import asyncio

    while True:
        started = time.perf_counter()
        await asyncio.sleep(interval)
        counters.observe("event_loop.lag_ms", max(0.0, (time.perf_counter() - started - interval) * 1000))


def response_with_request_id(response: Response, request: Request) -> Response:
    request_id = current_request_id()
    if request_id:
        response.headers.setdefault("X-Request-ID", request_id)
    return response
