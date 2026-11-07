"""In-site notification service (4.17): create notifications and durable realtime events in the same transaction.

This function no longer touches WebSocket directly. After the caller commits the single
transaction containing business rows, notifications, audits, and events, the dispatcher
delivers them; on rollback the notifications and events disappear together.
"""
from collections.abc import Iterable

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Notification, User
from app.models.enums import UserRole
from app.realtime.events import emit_event_intents, validate_payload


async def notify(
    db: AsyncSession,
    user_ids: Iterable[int | None],
    type_: str,
    title: str,
    content: str = "",
    link_type: str | None = None,
    link_id: int | None = None,
    payload: dict | None = None,
) -> list[Notification]:
    """Create one notification and event per valid regular user.

    4.17: administrator to-dos come from the shared processing pool and receive no
    personal in-site notifications; unknown users are not persisted, avoiding invalid
    foreign keys. BR-32: banned accounts can still read their own notifications, so
    account status is not filtered.
    """
    candidates = list(dict.fromkeys(uid for uid in user_ids if uid is not None))
    if not candidates:
        return []

    existing_ids = set(
        (
            await db.exec(
                select(col(User.id)).where(
                    col(User.id).in_(candidates),
                    col(User.role) != UserRole.ADMIN.value,
                )
            )
        ).all()
    )
    # Deduplicate while preserving input order so return values, persistence, and event recipients match exactly.
    users = [uid for uid in candidates if uid in existing_ids]
    if not users:
        return []

    notifications = [
        Notification(
            user_id=uid,
            type=type_,
            title=title,
            content=content,
            link_type=link_type,
            link_id=link_id,
            payload=payload or {},
        )
        for uid in users
    ]
    db.add_all(notifications)
    await db.flush()
    event_payload = validate_payload("notification", {
        # Legacy callback fields stay under ``payload`` unchanged.
        "type": "notification",
        "event": type_,
        "title": title,
        "link_type": link_type,
        "link_id": link_id,
    })
    intents = []
    for notification in notifications:
        payload = dict(event_payload)
        payload["notification_id"] = notification.id
        intents.append((notification.user_id, payload, "notification", str(notification.id), 1))
    # Counters are locked once at transaction finalization, sorted by user ID,
    # after all business locks. No counter is acquired here.
    await emit_event_intents(db, event_type="notification", intents=intents)
    return notifications
