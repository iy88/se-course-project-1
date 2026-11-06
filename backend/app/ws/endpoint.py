"""WS entrypoint: one-time ticket, Origin, auth expiry and gateway handoff.

The WebSocket handshake never holds a SQL connection while the socket lives.
The ticket is consumed atomically before any replay work; the ticket value is
the only credential in the WSS URL. Legacy ``?token=`` is an explicit opt-in
transition and is rejected by default in production.
"""

from __future__ import annotations

import contextlib
import logging
import re

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketDisconnected

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.session import get_sessionmaker
from app.kv.base import KVError
from app.models import User
from app.realtime.gateway import CLOSE_AUTH, CLOSE_FORBIDDEN, Gateway, get_gateway
from app.realtime.tickets import (
    consume_ticket,
    origin_allowed,
    ticket_expiry_from_payload,
)

logger = logging.getLogger(__name__)

_USER_ID_RE = re.compile(r"[1-9][0-9]*")
_MAX_USER_ID = 2**63 - 1


async def _reject(websocket: WebSocket, code: int) -> None:
    """First accept the handshake so clients observe a business close code."""
    try:
        await websocket.accept()
    except (WebSocketDisconnect, WebSocketDisconnected, OSError):
        return
    with contextlib.suppress(Exception):
        await websocket.close(code=code)


def _parse_legacy_token(token: str) -> tuple[int, int] | None:
    payload = decode_access_token(token)
    if not payload:
        return None
    sub = payload.get("sub")
    if not isinstance(sub, str) or _USER_ID_RE.fullmatch(sub) is None or len(sub) > 19:
        return None
    user_id = int(sub)
    if user_id > _MAX_USER_ID:
        return None
    return user_id, ticket_expiry_from_payload(payload)


async def _legacy_user_exists(user_id: int) -> bool:
    try:
        async with get_sessionmaker()() as db:
            return await db.get(User, user_id) is not None
    except Exception as exc:  # noqa: BLE001 - auth failure is fail-closed
        logger.warning("ws legacy auth database check failed: %s", type(exc).__name__)
        return False


async def ws_endpoint(websocket: WebSocket) -> None:
    settings = get_settings()
    origin = websocket.headers.get("origin")
    if not origin_allowed(origin):
        await _reject(websocket, CLOSE_FORBIDDEN)
        return

    ticket_value = websocket.query_params.get("ticket", "")
    legacy_value = websocket.query_params.get("token", "")
    user_id: int | None = None
    since = 0
    auth_expires_at = 0
    legacy = False

    if ticket_value:
        try:
            ticket = await consume_ticket(ticket_value)
        except KVError:
            # Ticket storage is security-critical: no shared state means no auth.
            logger.warning("ws ticket store unavailable")
            await _reject(websocket, 1011)
            return
        if ticket is None:
            await _reject(websocket, CLOSE_AUTH)
            return
        user_id = ticket.user_id
        since = ticket.since
        auth_expires_at = ticket.auth_expires_at
    elif legacy_value and settings.allow_query_token and not settings.is_production:
        parsed = _parse_legacy_token(legacy_value)
        if parsed is None or not await _legacy_user_exists(parsed[0]):
            await _reject(websocket, CLOSE_AUTH)
            return
        user_id, auth_expires_at = parsed
        legacy = True
    else:
        await _reject(websocket, CLOSE_AUTH)
        return

    gateway: Gateway = get_gateway()
    client = websocket.client
    await gateway.serve(
        websocket,
        user_id=int(user_id),
        since=since,
        auth_expires_at=auth_expires_at,
        ip=client.host if client else None,
        legacy=legacy,
    )
