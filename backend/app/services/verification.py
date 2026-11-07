"""Email verification codes: pre-registration verification, forgot password, and email change (one code each for old and new email).

Codes are stored in the configured KV, with expiration and send interval controlled by
configuration. Codes are delivered by email and never returned in API responses.
"""

import secrets

from fastapi import HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.kv.base import KVError, get_kv
from app.services.mail_delivery import deliver_code

PURPOSE_REGISTER = "register"  # D-47: verify control of the current email before registration
PURPOSE_RESET = "reset_password"
PURPOSE_EMAIL_OLD = "change_email_old"
PURPOSE_EMAIL_NEW = "change_email_new"


def _normalized_email(email: str) -> str:
    return email.strip().lower()


def _key(purpose: str, email: str) -> str:
    return f"vcode:{purpose}:{_normalized_email(email)}"


def _interval_key(purpose: str, email: str) -> str:
    return f"vcode-interval:{purpose}:{_normalized_email(email)}"


async def send_code(purpose: str, email: str) -> str:
    settings = get_settings()
    kv = get_kv()
    try:
        if await kv.get(_interval_key(purpose, email)):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "验证码发送过于频繁，请稍后再试")
        code = f"{secrets.randbelow(1_000_000):06d}"
        await kv.set(_key(purpose, email), code, settings.verification_code_ttl_seconds)
        await kv.set(_interval_key(purpose, email), "1", settings.verification_send_interval_seconds)
    except KVError:
        # Security state is fail-closed: never send a code while the shared
        # store is unavailable, because it could not be verified atomically.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "验证码服务暂不可用，请稍后重试") from None
    try:
        await run_in_threadpool(deliver_code, settings, purpose, email, code)
    except Exception:  # noqa: BLE001 - clear active codes and redact all transport/credential errors
        await kv.delete(_key(purpose, email))
        await kv.delete(_interval_key(purpose, email))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "验证码邮件发送失败，请稍后重试") from None
    return ""


async def verify_code(purpose: str, email: str, code: str) -> None:
    kv = get_kv()
    key = _key(purpose, email)
    try:
        stored = await kv.get(key)
        if not stored or stored != code.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "验证码错误或已过期")
        await kv.delete(key)
    except KVError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "验证码服务暂不可用，请稍后重试") from None
