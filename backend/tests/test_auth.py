"""账户生命周期测试（FR-01）。"""

import pytest

from tests.conftest import login, register, user_headers

pytestmark = pytest.mark.asyncio


async def test_register_login_and_duplicate_email(client):
    data = await register(client, "a@test.com", "用户A")
    assert data["user"]["email"] == "a@test.com"
    assert data["access_token"]
    # 重复邮箱被拒绝（BR-21）
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "a@test.com", "display_name": "B", "password": "secret123"},
    )
    assert resp.status_code == 400


async def test_login_wrong_password(client):
    await register(client, "b@test.com", "用户B")
    resp = await client.post("/api/v1/auth/login", json={"email": "b@test.com", "password": "wrong"})
    assert resp.status_code == 401


async def test_business_requires_login(client):
    """BR-22：未登录不可访问业务内容。"""
    for path in ["/api/v1/products/search", "/api/v1/products/1", "/api/v1/favorites", "/api/v1/notifications"]:
        resp = await client.get(path)
        assert resp.status_code == 401, path


async def test_forgot_password_flow(client):
    await register(client, "c@test.com", "用户C")
    resp = await client.post("/api/v1/auth/forgot-password/send-code", json={"email": "c@test.com"})
    assert resp.status_code == 200
    code = resp.json()["dev_code"]
    assert code
    resp = await client.post(
        "/api/v1/auth/forgot-password/reset",
        json={"email": "c@test.com", "code": code, "new_password": "newsecret123"},
    )
    assert resp.status_code == 200
    token = await login(client, "c@test.com", "newsecret123")
    assert token


async def test_change_password_requires_current(client):
    headers = await user_headers(client, "d@test.com", "用户D")
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": "wrong", "new_password": "newsecret123"},
    )
    assert resp.status_code == 400
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": "secret123", "new_password": "newsecret123"},
    )
    assert resp.status_code == 200


async def test_update_display_name(client):
    headers = await user_headers(client, "e@test.com", "旧名称")
    resp = await client.patch("/api/v1/auth/profile", headers=headers, json={"display_name": "新名称"})
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "新名称"
