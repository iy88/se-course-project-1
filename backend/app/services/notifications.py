"""站内通知服务（4.17）：创建通知并经 WS 推送未读提醒。"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification
from app.ws.manager import manager


async def notify(
    db: AsyncSession,
    user_ids: list[int],
    type_: str,
    title: str,
    content: str = "",
    link_type: str | None = None,
    link_id: int | None = None,
    payload: dict | None = None,
) -> list[Notification]:
    """给每个接收者创建一条通知；BR-32：封禁账户仍可读取本人通知。"""
    users = list({uid for uid in user_ids if uid is not None})
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
    await manager.push_to_users(
        users,
        {"type": "notification", "event": type_, "title": title, "link_type": link_type, "link_id": link_id},
    )
    return notifications
