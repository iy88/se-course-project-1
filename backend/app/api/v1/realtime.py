"""Authorized realtime ticket, watermark and paginated replay endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession, current_token_expires_at
from app.core.config import get_settings
from app.kv.base import KVError
from app.realtime.events import event_wire, high_watermark, low_watermark, replay_events
from app.realtime.tickets import issue_ticket

router = APIRouter(prefix="/realtime", tags=["realtime"])


class TicketIn(BaseModel):
    # Last contiguous user_seq the client applied. 0 asks for the retained range.
    since: int = Field(default=0, ge=0, le=2**63 - 1)


@router.post("/ticket")
async def create_ticket(body: TicketIn, user: CurrentUser) -> dict:
    settings = get_settings()
    auth_expires_at = current_token_expires_at() or int(time.time()) + settings.ws_ticket_ttl_seconds
    try:
        ticket, ttl = await issue_ticket(
            user_id=user.id,
            since=body.since,
            auth_expires_at=auth_expires_at,
            role=user.role,
        )
    except KVError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "实时连接票据服务暂不可用") from None
    return {
        "ticket": ticket,
        "expires_in": ttl,
        "protocol_version": settings.realtime_protocol_version,
        "ws_path": "/ws",
        "since": body.since,
    }


@router.get("/watermark")
async def watermark(user: CurrentUser, db: DbSession) -> dict:
    settings = get_settings()
    return {
        "user_id": user.id,
        "low_seq": await low_watermark(db, user.id),
        "high_seq": await high_watermark(db, user.id),
        "protocol_version": settings.realtime_protocol_version,
        "retention_hours": settings.realtime_event_retention_hours,
    }


@router.get("/events")
async def replay(
    user: CurrentUser,
    db: DbSession,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1),
) -> dict:
    """Own-user only, bounded page. A stale cursor returns resync_required."""
    settings = get_settings()
    low = await low_watermark(db, user.id)
    high = await high_watermark(db, user.id)
    if after_seq < low - 1:
        return {
            "events": [],
            "low_seq": low,
            "high_seq": high,
            "has_more": True,
            "resync_required": True,
        }
    page = min(limit, settings.realtime_replay_max_events)
    events = await replay_events(db, user.id, after_seq=after_seq, upto_seq=high, limit=page)
    last = int(events[-1].user_seq) if events else after_seq
    return {
        "events": [event_wire(event) for event in events],
        "low_seq": low,
        "high_seq": high,
        "has_more": last < high,
        "resync_required": False,
    }
