"""Process-local job resources created inside the running event loop."""

from __future__ import annotations

from app.core.config import Settings
from app.realtime.dispatcher import OutboxService


def get_outbox_service(settings: Settings) -> OutboxService:
    # Every task invocation needs a unique lease owner. Concurrent tasks in one
    # worker must not confirm a later invocation's reclaimed rows after expiry.
    # Redis stream pools remain process-local and shared via get_realtime_stream.
    return OutboxService(settings)


async def close_job_resources() -> None:
    from app.realtime.stream import close_realtime_stream

    await close_realtime_stream()
