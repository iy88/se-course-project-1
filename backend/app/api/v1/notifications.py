"""站内通知（C-15/4.17）：列表、未读数；仅打开具体通知才已读。"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.models import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    user: CurrentUser,
    db: DbSession,
    unread_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
) -> dict:
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.is_read.is_(False))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    result = await db.execute(
        query.order_by(Notification.id.desc()).offset((page - 1) * page_size).limit(page_size)
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
            for n in result.scalars()
        ],
    }


@router.get("/unread-count")
async def unread_count(user: CurrentUser, db: DbSession) -> dict:
    count = await db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user.id, Notification.is_read.is_(False)
        )
    )
    return {"unread": int(count or 0)}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: int, user: CurrentUser, db: DbSession) -> dict:
    """打开具体通知才已读；进入列表不算（4.17）。"""
    notification = await db.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "通知不存在")
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(UTC)
        await db.commit()
    return {"detail": "已读"}
