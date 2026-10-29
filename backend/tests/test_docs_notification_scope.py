"""4.17 站内通知范围回归：管理员不接收个人通知，历史行不被暴露或改写。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.models import Notification, User
from app.models.enums import AccountStatus
from app.services import notifications as notification_service
from tests.conftest import admin_headers, make_admin, user_headers

pytestmark = pytest.mark.asyncio


async def _user_id(db, email: str) -> int:
    return await db.scalar(select(User.id).where(User.email == email))


async def _notification_rows(db) -> list[Notification]:
    return list((await db.execute(select(Notification).order_by(Notification.id))).scalars())


async def test_notify_mixed_recipients_dedupes_to_non_admin_users(client, db, monkeypatch):
    admin = await db.scalar(select(User).where(User.email == "admin@test.edu"))
    await user_headers(client, "scope-normal@test.com", "普通用户")
    await user_headers(client, "scope-other@test.com", "另一用户")
    await user_headers(client, "scope-banned@test.com", "封禁用户")
    normal_id = await _user_id(db, "scope-normal@test.com")
    other_id = await _user_id(db, "scope-other@test.com")
    banned_id = await _user_id(db, "scope-banned@test.com")

    banned = await db.get(User, banned_id)
    banned.status = AccountStatus.BANNED.value
    await db.commit()

    push = AsyncMock()
    monkeypatch.setattr(notification_service, "manager", SimpleNamespace(push_to_users=push))

    created = await notification_service.notify(
        db,
        [admin.id, normal_id, normal_id, banned_id, 999_999, other_id],
        "trade_completed",
        "交易完成",
        "关联交易 #7",
        "trade",
        7,
        {"trade_id": 7},
    )
    await db.commit()

    # 返回值、落库与 WS 接收人完全一致：仅实际存在的普通用户，且每人一条。
    expected_ids = [normal_id, banned_id, other_id]
    assert [n.user_id for n in created] == expected_ids
    assert len(created) == 3

    stored = await _notification_rows(db)
    assert [n.user_id for n in stored] == expected_ids
    assert all(n.type == "trade_completed" and n.link_id == 7 for n in stored)
    assert all(n.is_read is False for n in stored)

    push.assert_awaited_once()
    ws_user_ids, ws_payload = push.await_args.args
    assert ws_user_ids == expected_ids
    assert admin.id not in ws_user_ids
    assert 999_999 not in ws_user_ids
    assert ws_payload["type"] == "notification"
    assert ws_payload["event"] == "trade_completed"


async def test_notify_all_admin_empty_or_unknown_does_not_persist_or_push(client, db, monkeypatch):
    admin = await db.scalar(select(User).where(User.email == "admin@test.edu"))
    admin2 = await make_admin(db, "scope-admin2@test.edu")

    push = AsyncMock()
    monkeypatch.setattr(notification_service, "manager", SimpleNamespace(push_to_users=push))

    assert await notification_service.notify(db, [admin.id, admin2.id, admin.id], "notice", "管理员") == []
    assert await notification_service.notify(db, [], "notice", "空集合") == []
    assert await notification_service.notify(db, [999_999], "notice", "未知用户") == []
    await db.commit()

    assert await db.scalar(select(func.count()).select_from(Notification)) == 0
    push.assert_not_awaited()


async def test_admin_legacy_notifications_hidden_and_read_rejected_without_changes(client, db):
    admin = await db.scalar(select(User).where(User.email == "admin@test.edu"))
    admin_h = await admin_headers(client)
    normal_h = await user_headers(client, "scope-reader@test.com", "通知读者")
    other_h = await user_headers(client, "scope-stranger@test.com", "无关用户")
    normal_id = await _user_id(db, "scope-reader@test.com")

    # 预置历史误发给管理员的个人通知：接口不得暴露，也不得删除或改写。
    admin_legacy = Notification(
        user_id=admin.id,
        type="legacy_admin_notice",
        title="历史管理员个人通知",
        content="旧数据",
        payload={},
    )
    normal_notice = Notification(
        user_id=normal_id,
        type="inquiry",
        title="待说明事项",
        content="请提交说明",
        link_type="case",
        link_id=11,
        payload={},
    )
    db.add_all([admin_legacy, normal_notice])
    await db.commit()

    resp = await client.get("/api/v1/notifications", headers=admin_h)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"total": 0, "items": []}
    resp = await client.get("/api/v1/notifications", headers=admin_h, params={"unread_only": True})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"total": 0, "items": []}
    resp = await client.get("/api/v1/notifications/unread-count", headers=admin_h)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"unread": 0}

    resp = await client.post(f"/api/v1/notifications/{admin_legacy.id}/read", headers=admin_h)
    assert resp.status_code == 404, resp.text
    await db.refresh(admin_legacy)
    assert admin_legacy.is_read is False
    assert admin_legacy.read_at is None

    # 普通用户列表保持未读，只有打开本人具体通知才标读。
    resp = await client.get("/api/v1/notifications", headers=normal_h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [normal_notice.id]
    assert body["items"][0]["is_read"] is False
    resp = await client.get("/api/v1/notifications", headers=normal_h)
    assert resp.json()["items"][0]["is_read"] is False
    resp = await client.get("/api/v1/notifications/unread-count", headers=normal_h)
    assert resp.json() == {"unread": 1}

    # 不得读取或标读他人通知。
    resp = await client.post(f"/api/v1/notifications/{normal_notice.id}/read", headers=other_h)
    assert resp.status_code == 404, resp.text
    await db.refresh(normal_notice)
    assert normal_notice.is_read is False
    assert normal_notice.read_at is None

    resp = await client.post(f"/api/v1/notifications/{normal_notice.id}/read", headers=normal_h)
    assert resp.status_code == 200, resp.text
    await db.refresh(normal_notice)
    assert normal_notice.is_read is True
    assert normal_notice.read_at is not None
    resp = await client.get("/api/v1/notifications/unread-count", headers=normal_h)
    assert resp.json() == {"unread": 0}

    # 历史管理员行仍在库中且未被标读，只做当前通知视图隐藏。
    await db.refresh(admin_legacy)
    assert admin_legacy.is_read is False
    assert admin_legacy.read_at is None
    assert await db.scalar(select(func.count()).select_from(Notification)) == 2


async def test_banned_user_can_still_read_own_notifications(client, db):
    banned_h = await user_headers(client, "scope-banned-reader@test.com", "封禁读者")
    banned_id = await _user_id(db, "scope-banned-reader@test.com")
    banned = await db.get(User, banned_id)
    banned.status = AccountStatus.BANNED.value
    await db.commit()

    await notification_service.notify(db, [banned_id], "disposal_notice", "处置通知", "请查看")
    await db.commit()

    resp = await client.get("/api/v1/notifications", headers=banned_h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["is_read"] is False
    resp = await client.get("/api/v1/notifications/unread-count", headers=banned_h)
    assert resp.json() == {"unread": 1}

    notice_id = body["items"][0]["id"]
    resp = await client.post(f"/api/v1/notifications/{notice_id}/read", headers=banned_h)
    assert resp.status_code == 200, resp.text
    resp = await client.get("/api/v1/notifications/unread-count", headers=banned_h)
    assert resp.json() == {"unread": 0}
