"""站内通知服务（4.17）：创建通知并经 WS 推送未读提醒。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification, User
from app.models.enums import UserRole
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
    """给每个有效普通用户创建一条通知。

    4.17：管理员待办来自共享处理池，不接收站内个人通知；未知用户不落库，
    避免非法外键。BR-32：封禁账户仍可读取本人通知，故不按账户状态过滤。
    """
    candidates = list(dict.fromkeys(uid for uid in user_ids if uid is not None))
    if not candidates:
        return []

    existing_ids = set(
        (
            await db.scalars(
                select(User.id).where(
                    User.id.in_(candidates),
                    User.role != UserRole.ADMIN.value,
                )
            )
        ).all()
    )
    # 保持入参顺序去重，使返回值、持久化与 WS 接收人完全一致。
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
    await manager.push_to_users(
        users,
        {"type": "notification", "event": type_, "title": title, "link_type": link_type, "link_id": link_id},
    )
    return notifications
