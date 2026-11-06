"""One-time WebSocket tickets.

The opaque ticket is the only credential in the WSS URL. Its server-side value
is consumed atomically (GETDEL/Lua), so two gateways racing on the same ticket
produce exactly one authenticated connection. Tickets are short-lived and bind
the user, the subscription cursor and the auth expiry at issue time.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from app.core.config import get_settings
from app.kv.base import get_kv

AUDIENCE = "campus-market-ws"
_TICKET_KEY = "ws:ticket:"


@dataclass(frozen=True)
class TicketData:
    user_id: int
    since: int
    auth_expires_at: int
    issued_at: int
    role: str
    audience: str = AUDIENCE
    protocol_version: int = 2


async def issue_ticket(*, user_id: int, since: int, auth_expires_at: int, role: str) -> tuple[str, int]:
    settings = get_settings()
    now = datetime.now(UTC)
    data = TicketData(
        user_id=int(user_id),
        since=max(0, int(since)),
        auth_expires_at=int(auth_expires_at),
        issued_at=int(now.timestamp()),
        role=role,
        protocol_version=settings.realtime_protocol_version,
    )
    token = secrets.token_urlsafe(32)
    ttl = settings.ws_ticket_ttl_seconds
    await get_kv().set(_TICKET_KEY + token, json.dumps(asdict(data), separators=(",", ":")), ttl)
    return token, ttl


async def consume_ticket(token: str) -> TicketData | None:
    if not token or len(token) > 128:
        return None
    raw = await get_kv().consume_once(_TICKET_KEY + token)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        parsed = TicketData(
            user_id=int(data["user_id"]),
            since=max(0, int(data.get("since", 0))),
            auth_expires_at=int(data["auth_expires_at"]),
            issued_at=int(data["issued_at"]),
            role=str(data.get("role", "user")),
            audience=str(data.get("audience", "")),
            protocol_version=int(data.get("protocol_version", 0)),
        )
    except (KeyError, TypeError, ValueError):
        return None
    settings = get_settings()
    now = int(datetime.now(UTC).timestamp())
    if parsed.audience != AUDIENCE or parsed.protocol_version != settings.realtime_protocol_version:
        return None
    # A ticket is valid for at most its issue TTL, and never past the JWT.
    if now > parsed.auth_expires_at or now > parsed.issued_at + settings.ws_ticket_ttl_seconds + 1:
        return None
    if parsed.user_id <= 0:
        return None
    return parsed


def origin_allowed(origin: str | None) -> bool:
    settings = get_settings()
    if not origin:
        return settings.allow_missing_origin
    return origin.rstrip("/") in settings.origin_allowlist


def ticket_expiry_from_payload(payload: dict | None) -> int:
    if not payload:
        return 0
    try:
        return int(payload.get("exp", 0))
    except (TypeError, ValueError):
        return 0

