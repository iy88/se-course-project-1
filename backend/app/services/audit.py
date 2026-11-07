"""P3 audit service: request context, same-transaction success events, standalone failure events, and sensitive-field redaction.

Design notes:
- A successful business change only calls ``record_event`` to add an event to the
  current Session; it does not commit on its own. The caller commits it together with
  the business writes. A failed audit INSERT raises and rolls back the business change.
- ``record_standalone_failure`` commits independently in a new session on the request's
  engine for failed logins/denied operations; it never reads .env, prints exception
  bodies, or writes into the business transaction.
- Middleware handles only status >= 400 and must never add success events after a
  business commit.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
from contextvars import ContextVar, Token
from datetime import date, datetime
from typing import Any, Final

from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    async_sessionmaker,
)
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.requests import Request

from app.core.config import get_settings
from app.models.audit import AuditEvent

logger = logging.getLogger(__name__)

AsyncBind = AsyncEngine | AsyncConnection

# ---------------------------------------------------------------------------
# Event names (stable contract; never write free text or object content)
# ---------------------------------------------------------------------------

EVENT_AUTH_REGISTER: Final = "auth.register"
EVENT_AUTH_LOGIN_SUCCESS: Final = "auth.login_success"
EVENT_AUTH_LOGIN_FAILED: Final = "auth.login_failed"
EVENT_AUTH_LOGOUT: Final = "auth.logout"
EVENT_AUTH_PASSWORD_RESET: Final = "auth.password_reset"
EVENT_AUTH_PASSWORD_CHANGE: Final = "auth.password_change"
EVENT_AUTH_EMAIL_CHANGE: Final = "auth.email_change"
EVENT_USER_PROFILE_UPDATE: Final = "user.profile_update"

EVENT_PRODUCT_PUBLISH: Final = "product.publish"
EVENT_PRODUCT_RESUBMIT: Final = "product.resubmit"
EVENT_PRODUCT_EDIT: Final = "product.edit"
EVENT_PRODUCT_WITHDRAW_REVIEW: Final = "product.withdraw_review"
EVENT_PRODUCT_DELIST: Final = "product.delist"
EVENT_PRODUCT_RELIST: Final = "product.relist"
EVENT_ADMIN_PRODUCT_REVIEW: Final = "admin.product_review"
EVENT_ADMIN_PRODUCT_RESTORE_DISPLAY: Final = "admin.product_restore_display"
EVENT_ADMIN_PRODUCT_CATEGORY_CORRECT: Final = "admin.product_category_correct"

EVENT_TRADE_REQUEST_CREATE: Final = "trade.request_create"
EVENT_TRADE_ACCEPT: Final = "trade.accept"
EVENT_TRADE_REJECT: Final = "trade.reject"
EVENT_TRADE_WITHDRAW: Final = "trade.withdraw"
EVENT_AGREEMENT_PROPOSE: Final = "trade.agreement_propose"
EVENT_AGREEMENT_CONFIRM: Final = "trade.agreement_confirm"
EVENT_AGREEMENT_REJECT: Final = "trade.agreement_reject"
EVENT_TRADE_COMPLETION_CONFIRM: Final = "trade.completion_confirm"
EVENT_TRADE_CANCEL_REQUEST: Final = "trade.cancel_request"
EVENT_TRADE_CANCEL_CONFIRM: Final = "trade.cancel_confirm"
EVENT_TRADE_CANCEL_WITHDRAW: Final = "trade.cancel_withdraw"
EVENT_TRADE_CANCEL_REJECT: Final = "trade.cancel_reject"
EVENT_TRADE_DISPUTE_CREATE: Final = "trade.dispute_create"
EVENT_TRADE_DISPUTE_RESOLVE: Final = "trade.dispute_resolve"

EVENT_ADMIN_TRADE_FREEZE: Final = "admin.trade_freeze"
EVENT_ADMIN_TRADE_UNFREEZE: Final = "admin.trade_unfreeze"
EVENT_ADMIN_TRADE_ADJUST: Final = "admin.trade_adjust"
EVENT_ADMIN_ACCOUNT_BAN: Final = "admin.account_ban"
EVENT_ADMIN_ACCOUNT_UNBAN: Final = "admin.account_unban"
EVENT_ADMIN_CASE_CLAIM: Final = "admin.case_claim"
EVENT_ADMIN_CASE_INQUIRY: Final = "admin.case_inquiry"
EVENT_ADMIN_CASE_MESSAGE: Final = "admin.case_message"
EVENT_ADMIN_CASE_DISPOSE: Final = "admin.case_dispose"
EVENT_ADMIN_REPORT_DECISION: Final = "admin.report_decision"

EVENT_REPORT_CREATE: Final = "report.create"
EVENT_REPORT_SUPPLEMENT: Final = "report.supplement"
EVENT_TRADE_REVIEW_CREATE: Final = "trade.review_create"
EVENT_COMMENT_CREATE: Final = "comment.create"
EVENT_COMMENT_DELETE: Final = "comment.delete"
EVENT_IM_MESSAGE_SEND: Final = "im.message_send"

EVENT_SYSTEM_TRADE_TIMEOUT: Final = "system.trade_timeout"

EVENT_LOGIN_FAILED: Final = EVENT_AUTH_LOGIN_FAILED
EVENT_DENIED_ADMIN: Final = "admin.denied"
EVENT_DENIED_TRADE: Final = "trade.denied"
EVENT_DENIED_PRODUCT: Final = "product.denied"
EVENT_DENIED_REQUEST: Final = "request.denied"
EVENT_DENIED_AUDIT_QUERY: Final = "admin.audit_query_denied"

_ALLOWED_RESULTS: Final = {"success", "failure", "denied"}
_ALLOWED_ROLES: Final = {"user", "admin", "system", "anonymous"}

# ---------------------------------------------------------------------------
# Request context (contextvars; middleware binds and restores it at request start/end)
# ---------------------------------------------------------------------------

_REQUEST_ID: ContextVar[str | None] = ContextVar("audit_request_id", default=None)
_ACTOR_ID: ContextVar[int | None] = ContextVar("audit_actor_id", default=None)
_ACTOR_ROLE: ContextVar[str] = ContextVar("audit_actor_role", default="anonymous")
_IP: ContextVar[str | None] = ContextVar("audit_ip", default=None)
_USER_AGENT: ContextVar[str | None] = ContextVar("audit_user_agent", default=None)
_AUDIT_BIND: ContextVar[AsyncBind | None] = ContextVar("audit_bind", default=None)


class _Unset:
    """Distinguish "not passed" from an explicit None (background/anonymous actors need an explicit None)."""


_UNSET: Final = _Unset()


def bind_request_context(*, request_id: str | None, ip: str | None, user_agent: str | None) -> dict[str, Token[Any]]:
    """Bind the audit context for one request; pass the return value to ``reset_request_context``."""
    return {
        "request_id": _REQUEST_ID.set(_clean_request_id(request_id)),
        "actor_id": _ACTOR_ID.set(None),
        "actor_role": _ACTOR_ROLE.set("anonymous"),
        "ip": _IP.set(_clean_ip(ip)),
        "user_agent": _USER_AGENT.set(_clean_user_agent(user_agent)),
        "audit_bind": _AUDIT_BIND.set(None),
    }


def reset_request_context(tokens: dict[str, Token[Any]]) -> None:
    for token in reversed(list(tokens.values())):
        try:
            token.var.reset(token)
        except (ValueError, RuntimeError):  # pragma: no cover - defensive restore
            pass


def set_actor(actor_id: int | None, role: str = "user") -> None:
    _ACTOR_ID.set(actor_id)
    _ACTOR_ROLE.set(role if role in _ALLOWED_ROLES else "anonymous")


def current_actor_id() -> int | None:
    return _ACTOR_ID.get()


def current_actor_role() -> str:
    return _ACTOR_ROLE.get()


def current_request_id() -> str | None:
    return _REQUEST_ID.get()


def set_audit_bind(bind: AsyncBind | None) -> None:
    """The DbSession dependency puts the business-session engine into the context so failure audits can open an independent session."""
    _AUDIT_BIND.set(bind)


def current_audit_bind() -> AsyncBind | None:
    return _AUDIT_BIND.get()


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

_SENSITIVE_KEY_TOKENS: Final = (
    "password",
    "passwd",
    "pwd",
    "hash",
    "token",
    "secret",
    "authorization",
    "cookie",
    "session",
    "api_key",
    "apikey",
    "access_key",
    "credential",
    "jwt",
    "bearer",
    "code",
    "verification",
    "vcode",
    "captcha",
    "otp",
    "url",
    "uri",
    "signed",
    "signature",
    "chat",
    "message",
    "content",
    "body",
    "text",
    "description",
    "detail",
    "note",
    "email",
    "phone",
    "evidence",
    "file_key",
    "image_key",
    "avatar",
)

_URL_RE = re.compile(r"(?i)\b(?:https?|ftp|oss|s3)://|(?:\bsig=|\bsignature=|\bexpires=)")
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_ALIYUN_AK_RE = re.compile(r"\bLTAI[A-Za-z0-9]{12,}\b")

_MAX_STRING = 300
_MAX_LIST = 20
_MAX_DEPTH = 4
_MAX_PAYLOAD_CHARS = 8000
_REDACTED = "[redacted]"
_REDACTED_URL = "[redacted-url]"
_REDACTED_EMAIL = "[redacted-email]"
_REDACTED_TOKEN = "[redacted-token]"


def _normalized_key(key: object) -> str:
    return str(key).strip().lower().replace("-", "_").replace(" ", "_")


def _is_sensitive_key(key: object) -> bool:
    normalized = _normalized_key(key)
    return any(token in normalized for token in _SENSITIVE_KEY_TOKENS)


def _clean_string(value: str, *, limit: int = _MAX_STRING) -> str:
    cleaned = "".join(ch for ch in value if ch == "\t" or ch.isprintable()).strip()
    if len(cleaned) > limit:
        cleaned = cleaned[:limit] + "…"
    return cleaned


def _sanitize_string(value: str) -> str:
    if _URL_RE.search(value):
        return _REDACTED_URL
    if _JWT_RE.search(value) or _ALIYUN_AK_RE.search(value):
        return _REDACTED_TOKEN
    if _EMAIL_RE.search(value):
        return _REDACTED_EMAIL if _EMAIL_RE.fullmatch(value.strip()) else _EMAIL_RE.sub(_REDACTED_EMAIL, value)
    return _clean_string(value)


def sanitize_payload(value: Any, *, _depth: int = 0) -> Any:
    """Recursively redact so the result is JSON-serializable with bounded depth/count/size.

    A value is replaced wholesale when its key contains sensitive words such as
    password, hash, token, AK, verification code, URL, chat body, or email; URLs/JWTs/
    AKs/emails inside strings are detected and replaced too.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return _sanitize_string(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return "[bytes]"
    if _depth >= _MAX_DEPTH:
        return "[truncated-depth]"
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_LIST:
                sanitized["_truncated"] = True
                break
            safe_key = _clean_string(str(key), limit=64)
            sanitized[safe_key] = _REDACTED if _is_sensitive_key(key) else sanitize_payload(item, _depth=_depth + 1)
        return _cap_payload(sanitized)
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        result = [sanitize_payload(item, _depth=_depth + 1) for item in items[:_MAX_LIST]]
        if len(items) > _MAX_LIST:
            result.append("[truncated]")
        return result
    # Never write arbitrary object reprs to the audit, avoiding leaking models/connections/exception bodies.
    return "[unserializable]"


def _cap_payload(value: Any) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover - should be serializable after sanitization
        return {"truncated": True}
    if len(encoded) <= _MAX_PAYLOAD_CHARS:
        return value
    if isinstance(value, dict):
        return {"truncated": True, "fields": sorted(str(k) for k in value)[:20]}
    return {"truncated": True}


# ---------------------------------------------------------------------------
# Request metadata (IP/UA trusted only from explicitly configured proxies and length-limited)
# ---------------------------------------------------------------------------


def _trusted_proxies() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    raw = get_settings().audit_trusted_proxies.strip()
    if raw.lower() == "none":
        return ()
    return tuple(ipaddress.ip_network(part.strip(), strict=False)
                 for part in raw.split(",") if part.strip())


def _clean_ip(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate or len(candidate) > 45:
        return None
    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return str(parsed)


def _clean_user_agent(value: str | None) -> str | None:
    if not value:
        return None
    # Column width is 255; the truncation ellipsis takes 1 character, so content is limited to 254.
    cleaned = _clean_string(value, limit=254)
    return cleaned or None


def _clean_request_id(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", candidate):
        return candidate
    return None


def request_client_ip(request: Request) -> str | None:
    """Trust the first X-Forwarded-For entry only when the direct address belongs to AUDIT_TRUSTED_PROXIES."""
    direct = _clean_ip(request.client.host if request.client else None)
    trusted = _trusted_proxies()
    if direct and any(ipaddress.ip_address(direct) in network for network in trusted):
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0]
        forwarded_ip = _clean_ip(forwarded)
        if forwarded_ip:
            return forwarded_ip
    return direct


def request_user_agent(request: Request) -> str | None:
    return _clean_user_agent(request.headers.get("user-agent"))


# ---------------------------------------------------------------------------
# Event construction and writing
# ---------------------------------------------------------------------------

_EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_.]{1,63}$")
_REASON_CODE_RE = re.compile(r"[^A-Za-z0-9_.:-]+")


def _clean_event_type(event_type: str) -> str:
    value = str(event_type).strip()
    if not _EVENT_TYPE_RE.fullmatch(value):
        raise ValueError("invalid audit event_type")
    return value


def _clean_reason_code(reason_code: str | None) -> str | None:
    if not reason_code:
        return None
    cleaned = _REASON_CODE_RE.sub("_", str(reason_code).strip())[:64]
    return cleaned or None


def _clean_target_type(target_type: str | None) -> str | None:
    if not target_type:
        return None
    cleaned = re.sub(r"[^a-z0-9_]+", "_", str(target_type).strip().lower())[:32].strip("_")
    return cleaned or None


def _clean_target_id(target_id: int | str | None) -> str | None:
    if target_id is None:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "", str(target_id).strip())[:64]
    return cleaned or None


def _build_event(
    *,
    event_type: str,
    target_type: str | None,
    target_id: int | str | None,
    result: str,
    reason_code: str | None,
    before: dict | None,
    after: dict | None,
    actor_id: int | None,
    actor_role: str | None,
    request_id: str | None | _Unset,
    ip: str | None | _Unset,
    user_agent: str | None | _Unset,
) -> AuditEvent:
    normalized_result = str(result).strip().lower()
    if normalized_result not in _ALLOWED_RESULTS:
        raise ValueError("invalid audit result")

    if actor_id is None and actor_role == "system":
        role = "system"
    elif actor_role in _ALLOWED_ROLES:
        role = actor_role
    elif actor_id is not None:
        role = _ACTOR_ROLE.get() if _ACTOR_ROLE.get() in {"user", "admin", "system"} else "user"
    else:
        role = "anonymous"

    effective_request_id = _REQUEST_ID.get() if isinstance(request_id, _Unset) else request_id
    effective_ip = _IP.get() if isinstance(ip, _Unset) else ip
    effective_ua = _USER_AGENT.get() if isinstance(user_agent, _Unset) else user_agent

    return AuditEvent(
        request_id=_clean_request_id(effective_request_id),
        actor_id=actor_id,
        actor_role=role,
        event_type=_clean_event_type(event_type),
        target_type=_clean_target_type(target_type),
        target_id=_clean_target_id(target_id),
        result=normalized_result,
        reason_code=_clean_reason_code(reason_code),
        before_json=sanitize_payload(before),
        after_json=sanitize_payload(after),
        ip=_clean_ip(effective_ip),
        user_agent=_clean_user_agent(effective_ua),
    )


def should_record_actor(actor_id: int | None, actor_role: str | None) -> bool:
    """Retain only events attributable to an account or to an explicit system task."""
    return actor_role != 'anonymous' and (actor_id is not None or actor_role == 'system')


async def record_event(
    db: AsyncSession,
    event_type: str,
    *,
    target_type: str | None = None,
    target_id: int | str | None = None,
    result: str = "success",
    reason_code: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    actor_id: int | None | _Unset = _UNSET,
    actor_role: str | None = None,
    request_id: str | None | _Unset = _UNSET,
) -> AuditEvent | None:
    """Add attributable events to the current transaction; skip anonymous events without changing the business transaction."""
    effective_actor = _ACTOR_ID.get() if isinstance(actor_id, _Unset) else actor_id
    effective_role = actor_role or _ACTOR_ROLE.get()
    if effective_actor is not None and actor_role is None and effective_role == 'anonymous':
        effective_role = 'user'
    if not should_record_actor(effective_actor, effective_role):
        return None
    event = _build_event(
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        result=result,
        reason_code=reason_code,
        before=before,
        after=after,
        actor_id=effective_actor,
        actor_role=effective_role,
        request_id=request_id,
        ip=_UNSET,
        user_agent=_UNSET,
    )
    db.add(event)
    return event


async def record_standalone_failure(
    bind: AsyncBind | None,
    *,
    event_type: str,
    target_type: str | None = None,
    target_id: int | str | None = None,
    result: str = "failure",
    reason_code: str | None = None,
    actor_id: int | None = None,
    actor_role: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    request_id: str | None | _Unset = _UNSET,
) -> None:
    """Record failure/denied events in an independent short transaction; an audit failure must not affect the original response."""
    if bind is None or not should_record_actor(actor_id, actor_role):
        return
    if isinstance(bind, AsyncConnection):
        # If the business session is bound to a separate connection, the independent transaction uses its engine and must not reuse the same connection.
        bind = bind.engine
    try:
        marker = async_sessionmaker(bind, expire_on_commit=False, class_=AsyncSession)
        async with marker() as session:
            event = _build_event(
                event_type=event_type,
                target_type=target_type,
                target_id=target_id,
                result=result,
                reason_code=reason_code,
                before=before,
                after=after,
                actor_id=actor_id,
                actor_role=actor_role,
                request_id=request_id,
                ip=_UNSET,
                user_agent=_UNSET,
            )
            session.add(event)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 - an audit failure must not leak bodies or change the original response
        logger.warning("audit standalone write failed: %s", type(exc).__name__)


# ---------------------------------------------------------------------------
# Failure/denied event classification (used by middleware; does not read request bodies)
# ---------------------------------------------------------------------------

_TRADE_ID_RE = re.compile(r"/(?:trades|admin/trades)/(\d+)")
_PRODUCT_ID_RE = re.compile(r"/(?:products|admin/products)/(\d+)")
_CASE_ID_RE = re.compile(r"/(?:admin/cases|admin/products/cases|admin/reports/cases)/(\d+)")
_REPORT_ID_RE = re.compile(r"/reports/(\d+)")
_AUDIT_ID_RE = re.compile(r"/admin/audit/events/(\d+)")


def _status_reason(status_code: int) -> str:
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        429: "rate_limited",
    }.get(status_code, "server_error" if status_code >= 500 else "request_failed")


def _target_from_path(path: str) -> tuple[str | None, str | None]:
    for pattern, target_type in (
        (_AUDIT_ID_RE, "audit_event"),
        (_CASE_ID_RE, "disposal_case"),
        (_TRADE_ID_RE, "trade"),
        (_PRODUCT_ID_RE, "product"),
        (_REPORT_ID_RE, "report"),
    ):
        match = pattern.search(path)
        if match:
            return target_type, match.group(1)
    return None, None


def classify_denied(method: str, path: str, status_code: int) -> dict[str, Any]:
    """Map an HTTP failure to a stable audit event without writing URL queries or request bodies into the event."""
    normalized_path = path.rstrip("/") or "/"
    result = "denied" if status_code in (401, 403) else "failure"
    reason = _status_reason(status_code)
    target_type, target_id = _target_from_path(normalized_path)

    if normalized_path == "/api/v1/auth/login" and status_code == 401:
        return {
            "event_type": EVENT_AUTH_LOGIN_FAILED,
            "target_type": "user",
            "target_id": target_id,
            "result": "failure",
            "reason_code": "invalid_credentials",
        }
    if normalized_path == "/api/v1/auth/login":
        return {
            "event_type": EVENT_AUTH_LOGIN_FAILED,
            "target_type": "user",
            "target_id": target_id,
            "result": result,
            "reason_code": reason,
        }
    if normalized_path.startswith("/api/v1/files/upload-leases"):
        if normalized_path.endswith("/complete"):
            event_type = "file.lease_complete"
        elif normalized_path.endswith("/content"):
            event_type = "file.upload"
        else:
            event_type = "file.lease_issue"
    elif normalized_path.startswith("/api/v1/admin/audit"):
        event_type = EVENT_DENIED_AUDIT_QUERY
    elif normalized_path.startswith("/api/v1/admin"):
        event_type = EVENT_DENIED_ADMIN
    elif normalized_path.startswith("/api/v1/trades"):
        event_type = EVENT_DENIED_TRADE
    elif normalized_path.startswith("/api/v1/products"):
        event_type = EVENT_DENIED_PRODUCT
    else:
        event_type = EVENT_DENIED_REQUEST
    return {
        "event_type": event_type,
        "target_type": target_type,
        "target_id": target_id,
        "result": result,
        "reason_code": reason,
    }
