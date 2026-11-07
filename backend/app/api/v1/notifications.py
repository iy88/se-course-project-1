"""In-site notifications (C-15/4.17): list and unread count; a notification is read only when opened specifically."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, DbSession
from app.models import Notification
from app.models.enums import UserRole
from app.services import audit as audit_service
from app.services import todos as todo_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    user: CurrentUser,
    db: DbSession,
    unread_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
) -> dict:
    # 4.17: administrators receive no in-site notifications. Historical misdirected personal notifications are retained but no longer exposed as current notifications.
    if user.role == UserRole.ADMIN.value:
        return {"total": 0, "items": []}

    query = select(Notification).where(col(Notification.user_id) == user.id)
    if unread_only:
        query = query.where(col(Notification.is_read).is_(False))
    total = (await db.exec(select(func.count()).select_from(query.subquery()))).first()
    result = await db.exec(
        query.order_by(col(Notification.id).desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return {
        "total": int(total or 0),
        "items": [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "content": n.content,
                "link_type": n.link_type,
                "link_id": n.link_id,
                "payload": n.payload,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in result
        ],
    }


@router.get("/todos")
async def list_todos(user: CurrentUser, db: DbSession) -> dict:
    """D-53: aggregate to-dos from currently eligible matters; notification read state does not change to-dos, and administrators have no personal to-dos."""
    items = await todo_service.build_todos(db, user)
    return {"total": len(items), "items": items}


@router.get("/unread-count")
async def unread_count(user: CurrentUser, db: DbSession) -> dict:
    if user.role == UserRole.ADMIN.value:
        return {"unread": 0}
    count = (await db.exec(
        select(func.count()).select_from(Notification).where(
            col(Notification.user_id) == user.id, col(Notification.is_read).is_(False)
        )
    )).first()
    return {"unread": int(count or 0)}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: int, user: CurrentUser, db: DbSession) -> dict:
    """A notification is read only when opened specifically; entering the list does not count (4.17)."""
    # Historical personal notifications for administrators cannot be operated on as current notifications, nor used to mark old rows read.
    if user.role == UserRole.ADMIN.value:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "通知不存在")
    notification = await db.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "通知不存在")
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(UTC)
        await audit_service.record_event(
            db,
            "notification.read",
            target_type="notification",
            target_id=notification.id,
            before={"is_read": False},
            after={"is_read": True},
        )
        await db.commit()
    return {"detail": "已读"}
