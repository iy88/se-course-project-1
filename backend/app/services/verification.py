"""邮箱验证码：忘记密码、更换邮箱（新旧邮箱各一码）。

验证码存 KV（Redis 优先，进程内兜底），TTL 10 分钟；同一用途 60 秒内限发一次。
开发环境可经配置将验证码随接口返回（仅联调用，见 bits/开发阶段技术决策.md）。
"""

import random

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.kv.base import get_kv

CODE_TTL_SECONDS = 600
SEND_INTERVAL_SECONDS = 60

PURPOSE_RESET = "reset_password"
PURPOSE_EMAIL_OLD = "change_email_old"
PURPOSE_EMAIL_NEW = "change_email_new"


def _key(purpose: str, email: str) -> str:
    return f"vcode:{purpose}:{email.lower()}"


def _interval_key(purpose: str, email: str) -> str:
    return f"vcode-interval:{purpose}:{email.lower()}"


async def send_code(purpose: str, email: str) -> str:
    settings = get_settings()
    kv = get_kv()
    if await kv.get(_interval_key(purpose, email)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "验证码发送过于频繁，请稍后再试")
    code = f"{random.randint(0, 999999):06d}"
    await kv.set(_key(purpose, email), code, CODE_TTL_SECONDS)
    await kv.set(_interval_key(purpose, email), "1", SEND_INTERVAL_SECONDS)
    # 本期不接入真实邮件通道：开发环境直接返回验证码（由配置开关控制）
    if settings.environment == "dev" and settings.dev_expose_verification_code:
        return code
    return ""


async def verify_code(purpose: str, email: str, code: str) -> None:
    kv = get_kv()
    key = _key(purpose, email)
    stored = await kv.get(key)
    if not stored or stored != code.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "验证码错误或已过期")
    await kv.delete(key)
