"""邮箱验证码：注册前验证、忘记密码、更换邮箱（新旧邮箱各一码）。

验证码存放于配置指定的 KV，过期时间与发送间隔由配置控制。
通过邮件发送验证码，不在接口响应中返回。
"""

import secrets

from fastapi import HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.kv.base import get_kv
from app.services.mail_delivery import deliver_code

PURPOSE_REGISTER = "register"  # D-47：注册前验证当前邮箱控制权
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
    if await kv.get(_interval_key(purpose, email)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "验证码发送过于频繁，请稍后再试")
    code = f"{secrets.randbelow(1_000_000):06d}"
    await kv.set(_key(purpose, email), code, settings.verification_code_ttl_seconds)
    await kv.set(_interval_key(purpose, email), "1", settings.verification_send_interval_seconds)
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
    stored = await kv.get(key)
    if not stored or stored != code.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "验证码错误或已过期")
    await kv.delete(key)
