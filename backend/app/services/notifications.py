"""站内通知服务（4.17）：创建通知并写入同事务 durable realtime event。

此函数不再直接触碰 WebSocket。调用者提交业务、通知、审计与事件组成的同一
事务后，由 dispatcher 投递；回滚时通知与事件一起消失。
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
    """给每个有效普通用户创建一条通知及其事件。

    4.17：管理员待办来自共享处理池，不接收站内个人通知；未知用户不落库，
    避免非法外键。BR-32：封禁账户仍可读取本人通知，故不按账户状态过滤。
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
    # 保持入参顺序去重，使返回值、持久化与事件接收人完全一致。
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
