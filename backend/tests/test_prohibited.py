"""禁发范围接口回归：ORM 响应序列化、权限、封禁读取资格及排序（BR-13/22/32）。"""

import pytest
from sqlalchemy import select

from app.models import User
from app.models.enums import AccountStatus
from tests.conftest import admin_headers, login, make_admin, user_headers

pytestmark = pytest.mark.asyncio

ITEMS_URL = "/api/v1/prohibited-items"


def _payload(group_name: str = "危险品与管制物品", content: str = "易燃易爆物品", sort: int = 0) -> dict:
    return {"group_name": group_name, "content": content, "sort": sort}


async def test_admin_crud_visible_to_regular_user(client, db):
    """管理员新增/更新返回完整 Out，普通用户从 ORM 读取并看到最新结果，删除后移除。"""
    await make_admin(db)
    admin_h = await admin_headers(client)
    reader_h = await user_headers(client, "prohibited-reader@test.com", "普通用户")

    resp = await client.post(ITEMS_URL, headers=admin_h, json=_payload())
    assert resp.status_code == 200, resp.text
    created = resp.json()
    assert set(created) == {"id", "group_name", "content", "sort"}
    assert isinstance(created["id"], int)
    assert created["group_name"] == "危险品与管制物品"
    assert created["content"] == "易燃易爆物品"
    assert created["sort"] == 0

    resp = await client.get(ITEMS_URL, headers=reader_h)
    assert resp.status_code == 200, resp.text
    assert resp.json() == [created]

    resp = await client.put(
        f"{ITEMS_URL}/{created['id']}",
        headers=admin_h,
        json=_payload(group_name="违规服务", content="代写代考", sort=5),
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert set(updated) == {"id", "group_name", "content", "sort"}
    assert updated == {**created, "group_name": "违规服务", "content": "代写代考", "sort": 5}

    resp = await client.get(ITEMS_URL, headers=reader_h)
    assert resp.status_code == 200, resp.text
    assert resp.json() == [updated]

    resp = await client.delete(f"{ITEMS_URL}/{created['id']}", headers=admin_h)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"detail": "已删除"}

    resp = await client.get(ITEMS_URL, headers=reader_h)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_access_control_for_read_and_write(client, db):
    """未登录不能读；普通角色不能新增、更新或删除。"""
    await make_admin(db)
    admin_h = await admin_headers(client)
    user_h = await user_headers(client, "prohibited-normal@test.com", "普通用户")

    resp = await client.get(ITEMS_URL)
    assert resp.status_code == 401

    resp = await client.post(ITEMS_URL, headers=admin_h, json=_payload())
    assert resp.status_code == 200, resp.text
    item_id = resp.json()["id"]

    resp = await client.post(ITEMS_URL, headers=user_h, json=_payload(group_name="越权新增"))
    assert resp.status_code == 403

    resp = await client.put(f"{ITEMS_URL}/{item_id}", headers=user_h, json=_payload(group_name="越权更新"))
    assert resp.status_code == 403

    resp = await client.delete(f"{ITEMS_URL}/{item_id}", headers=user_h)
    assert resp.status_code == 403

    # 越权尝试未改变数据
    resp = await client.get(ITEMS_URL, headers=admin_h)
    assert resp.status_code == 200, resp.text
    assert resp.json() == [
        {"id": item_id, "group_name": "危险品与管制物品", "content": "易燃易爆物品", "sort": 0}
    ]


async def test_banned_user_keeps_read_access(client, db):
    """封禁只限制写操作；普通用户仍可登录并读取禁发范围。"""
    await make_admin(db)
    admin_h = await admin_headers(client)
    email = "prohibited-banned@test.com"
    await user_headers(client, email, "封禁用户")

    resp = await client.post(ITEMS_URL, headers=admin_h, json=_payload())
    assert resp.status_code == 200, resp.text
    item = resp.json()

    user = await db.scalar(select(User).where(User.email == email))
    assert user is not None
    user.status = AccountStatus.BANNED.value
    await db.commit()

    banned_h = {"Authorization": f"Bearer {await login(client, email)}"}
    resp = await client.get(ITEMS_URL, headers=banned_h)
    assert resp.status_code == 200, resp.text
    assert resp.json() == [item]


async def test_items_ordered_by_sort_then_id(client, db):
    """列表按 sort 升序，同一 sort 内按 id 升序。"""
    await make_admin(db)
    admin_h = await admin_headers(client)

    created = []
    for group_name, sort in (("组二", 2), ("组一A", 1), ("组一B", 1)):
        resp = await client.post(ITEMS_URL, headers=admin_h, json=_payload(group_name=group_name, sort=sort))
        assert resp.status_code == 200, resp.text
        created.append(resp.json())

    resp = await client.get(ITEMS_URL, headers=admin_h)
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert [item["id"] for item in items] == [created[1]["id"], created[2]["id"], created[0]["id"]]
    assert [item["group_name"] for item in items] == ["组一A", "组一B", "组二"]
    assert [item["sort"] for item in items] == [1, 1, 2]
