"""Verification and rate-limit state must fail closed when KV is unavailable."""

import pytest
from fastapi import HTTPException

from app.kv.base import KeyValueStore, KVError
from app.services import verification


class BrokenKV(KeyValueStore):
    async def set(self, key, value, ttl_seconds):
        raise KVError("connection")

    async def get(self, key):
        raise KVError("connection")

    async def delete(self, key):
        raise KVError("connection")


@pytest.fixture
def broken(monkeypatch):
    monkeypatch.setattr(verification, "get_kv", lambda: BrokenKV())


async def test_send_code_returns_503_and_does_not_send_mail(broken, monkeypatch):
    called = False

    def fail_send(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("must not send when KV is unavailable")

    monkeypatch.setattr(verification, "deliver_code", fail_send)
    with pytest.raises(HTTPException) as exc:
        await verification.send_code(verification.PURPOSE_REGISTER, "user@example.com")
    assert exc.value.status_code == 503
    assert called is False


async def test_verify_code_returns_503_not_success(broken):
    with pytest.raises(HTTPException) as exc:
        await verification.verify_code(verification.PURPOSE_REGISTER, "user@example.com", "123456")
    assert exc.value.status_code == 503
