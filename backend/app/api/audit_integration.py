"""审计装配：请求上下文/失败中间件 + 管理员查询路由。

由任务 A 在 ``app.main`` 中调用 ``install_audit(app)``。成功事件不在此处补写：
业务路由必须在自身事务内调用 ``app.services.audit.record_event``。此中间件只处理
status >= 400 的失败/拒绝，并使用独立短事务，避免随业务回滚丢失。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI
from starlette.requests import Request

from app.api.v1.admin.audit import router as admin_audit_router
from app.services import audit as audit_service

logger = logging.getLogger(__name__)

_AUDIT_INSTALLED_ATTR = "audit_installed"


class AuditMiddleware:
    """纯 ASGI 中间件：与下游共享同一任务上下文，能读到 deps 设置的 actor。"""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        tokens = audit_service.bind_request_context(
            request_id=request_id,
            ip=audit_service.request_client_ip(request),
            user_agent=audit_service.request_user_agent(request),
        )
        status_code = 500
        response_started = False

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code, response_started
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 500))
                response_started = True
            await send(message)

        try:
            try:
                await self.app(scope, receive, send_wrapper)
            except Exception:
                # 未被 FastAPI 异常处理器转换的异常：按 500 记录后原样抛出。
                if not response_started:
                    await _record_failure(request, 500)
                raise
            else:
                if status_code >= 400:
                    await _record_failure(request, status_code)
        finally:
            audit_service.reset_request_context(tokens)


async def _record_failure(request: Request, status_code: int) -> None:
    """独立事务记录失败/拒绝；审计本身故障不影响原响应。"""
    bind = audit_service.current_audit_bind()
    if bind is None:
        return
    classified = audit_service.classify_denied(request.method, request.url.path, status_code)
    actor_id = audit_service.current_actor_id()
    # 未识别操作人的所有失败与拒绝均留在访问日志，包括未知账户登录失败。
    if actor_id is None:
        return
    target_type = classified.get("target_type")
    target_id = classified.get("target_id")
    if classified["event_type"] == audit_service.EVENT_AUTH_LOGIN_FAILED and actor_id is not None:
        target_type = "user"
        target_id = str(actor_id)
    try:
        await audit_service.record_standalone_failure(
            bind,
            event_type=classified["event_type"],
            target_type=target_type,
            target_id=target_id,
            result=classified["result"],
            reason_code=classified["reason_code"],
            actor_id=actor_id,
            actor_role=audit_service.current_actor_role() if actor_id is not None else "anonymous",
        )
    except Exception as exc:  # noqa: BLE001 - 中间件不得改变原响应
        logger.warning("audit middleware failure write skipped: %s", type(exc).__name__)


def install_audit(app: FastAPI) -> None:
    """装配审计中间件与管理员查询路由；幂等，供 main.py 调用。"""
    if getattr(app.state, _AUDIT_INSTALLED_ATTR, False):
        return
    app.state.audit_installed = True
    app.add_middleware(AuditMiddleware)
    # 不修改共享 api/v1/__init__.py：直接挂在 app 上，路径仍为 /api/v1/admin/audit。
    app.include_router(admin_audit_router, prefix="/api/v1")
