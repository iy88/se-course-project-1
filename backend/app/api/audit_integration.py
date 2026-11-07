"""Audit wiring: request-context/failure middleware plus the administrator query router.

Task A calls ``install_audit(app)`` in ``app.main``. Success events are not written here:
business routes must call ``app.services.audit.record_event`` within their own
transaction. This middleware handles only failures/denials with status >= 400 and uses
an independent short transaction so they are not lost with a business rollback.
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
    """Pure ASGI middleware: shares the same task context as downstream code and can read the actor set by deps."""

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
                # An exception not converted by a FastAPI exception handler: record it as 500 and re-raise unchanged.
                if not response_started:
                    await _record_failure(request, 500)
                raise
            else:
                if status_code >= 400:
                    await _record_failure(request, status_code)
        finally:
            audit_service.reset_request_context(tokens)


async def _record_failure(request: Request, status_code: int) -> None:
    """Record a failure/denial in an independent transaction; an audit failure does not affect the original response."""
    bind = audit_service.current_audit_bind()
    if bind is None:
        return
    classified = audit_service.classify_denied(request.method, request.url.path, status_code)
    actor_id = audit_service.current_actor_id()
    # All failures and denials without an identified actor stay in the access log, including failed logins for unknown accounts.
    if actor_id is None:
        return
    target_type = classified.get("target_type")
    target_id = classified.get("target_id")
    if classified["event_type"] == audit_service.EVENT_AUTH_LOGIN_FAILED:
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
            actor_role=audit_service.current_actor_role(),
        )
    except Exception as exc:  # noqa: BLE001 - middleware must not change the original response
        logger.warning("audit middleware failure write skipped: %s", type(exc).__name__)


def install_audit(app: FastAPI) -> None:
    """Wire the audit middleware and administrator query router; idempotent and called by main.py."""
    if getattr(app.state, _AUDIT_INSTALLED_ATTR, False):
        return
    app.state.audit_installed = True
    app.add_middleware(AuditMiddleware)
    # Do not modify the shared api/v1/__init__.py: mount directly on the app, keeping the path /api/v1/admin/audit.
    app.include_router(admin_audit_router, prefix="/api/v1")
