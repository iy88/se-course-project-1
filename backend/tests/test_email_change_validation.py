"""更换邮箱 API：邮箱/验证码格式及账户不变性。"""

import pytest

from tests.conftest import user_headers

pytestmark = pytest.mark.asyncio

ORIGINAL_EMAIL = "email-change-source@test.edu"
TARGET_EMAIL = "email-change-target@test.edu"


async def _send_code(client, headers, target, new_email=None):
    payload = {"target": target}
    if new_email is not None:
        payload["new_email"] = new_email
    resp = await client.post("/api/v1/auth/email/send-code", headers=headers, json=payload)
    assert resp.status_code == 200, resp.text
    code = resp.json()["dev_code"]
    assert code
    return code


async def _me(client, headers):
    resp = await client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_invalid_email_and_codes_are_rejected_without_changing_account(client):
    headers = await user_headers(client, ORIGINAL_EMAIL, "换邮箱用户")
    before = await _me(client, headers)
    old_code = await _send_code(client, headers, "old")
    new_code = await _send_code(client, headers, "new", TARGET_EMAIL)
    wrong_code = "000000" if old_code != "000000" else "111111"

    invalid_requests = [
        (422, {"new_email": "not-an-email", "old_code": old_code, "new_code": new_code}),
        (422, {"new_email": TARGET_EMAIL, "old_code": "12345", "new_code": new_code}),
        (422, {"new_email": TARGET_EMAIL, "old_code": old_code, "new_code": "１２３４５６"}),
        (400, {"new_email": TARGET_EMAIL, "old_code": wrong_code, "new_code": new_code}),
    ]

    for expected_status, payload in invalid_requests:
        resp = await client.post("/api/v1/auth/email/change", headers=headers, json=payload)
        assert resp.status_code == expected_status, resp.text
        current = await _me(client, headers)
        assert current["id"] == before["id"]
        assert current["email"] == ORIGINAL_EMAIL

    # 被拒绝的请求未消耗验证码用途/接收方，有效请求仍可使用同一对新旧验证码完成更换。
    resp = await client.post(
        "/api/v1/auth/email/change",
        headers=headers,
        json={"new_email": TARGET_EMAIL, "old_code": old_code, "new_code": new_code},
    )
    assert resp.status_code == 200, resp.text
    changed = resp.json()
    assert changed["id"] == before["id"]
    assert changed["email"] == TARGET_EMAIL
    assert (await _me(client, headers))["email"] == TARGET_EMAIL


async def test_same_email_case_insensitive_is_rejected_without_changing_account(client):
    headers = await user_headers(client, "email-change-case@test.edu", "大小写用户")
    before = await _me(client, headers)

    resp = await client.post(
        "/api/v1/auth/email/change",
        headers=headers,
        json={
            "new_email": "Email-Change-Case@TEST.EDU",
            "old_code": "000000",
            "new_code": "000000",
        },
    )
    assert resp.status_code == 400, resp.text
    current = await _me(client, headers)
    assert current["id"] == before["id"]
    assert current["email"] == before["email"]
