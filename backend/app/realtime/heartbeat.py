"""Per-process heartbeat rows used by role readiness checks.

Rows are keyed by role/host/pid, so several workers can publish concurrently
without a global lock. The orchestrator only trusts a fresh ``heartbeat_at``;
process existence alone is not readiness.
"""

from __future__ import annotations

import os
import socket
import uuid
from datetime import UTC, datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings
from app.models.realtime import ServiceHeartbeat


def instance_name(settings: Settings) -> str:
    return f"{settings.app_role}:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


async def beat(
    db: AsyncSession,
    settings: Settings,
    *,
    name: str,
    status: str = "ready",
    details: dict | None = None,
    started_at: datetime | None = None,
) -> None:
    row = await db.get(ServiceHeartbeat, name)
    now = datetime.now(UTC)
    if row is None:
        row = ServiceHeartbeat(
            name=name,
            role=settings.app_role,
            instance_id=name.rsplit(":", 1)[-1],
            release_id=settings.release_id,
            protocol_version=settings.realtime_protocol_version,
            status=status,
            details=details or {},
            pid=os.getpid(),
            started_at=started_at or now,
            heartbeat_at=now,
        )
        db.add(row)
    else:
        row.status = status
        row.details = details or {}
        row.release_id = settings.release_id
        row.protocol_version = settings.realtime_protocol_version
        row.heartbeat_at = now
        db.add(row)
    await db.flush()
