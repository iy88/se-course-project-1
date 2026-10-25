"""密码散列与 JWT 签发/校验。"""

import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, role: str) -> str:
    settings = get_settings()
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": datetime.now(UTC) + timedelta(days=settings.jwt_expire_days),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=[get_settings().jwt_algorithm])
    except jwt.PyJWTError:
        return None


def sign_file_key(key: str, expire_seconds: int | None = None) -> str:
    """为文件访问生成带过期时间的签名（配合 BR-22：未登录不可见业务文件）。"""
    settings = get_settings()
    exp = int(time.time()) + (expire_seconds or settings.file_url_expire_seconds)
    sig = hmac.new(settings.file_url_secret.encode(), f"{key}:{exp}".encode(), hashlib.sha256).hexdigest()
    return f"exp={exp}&sig={sig}"


def verify_file_signature(key: str, exp: str, sig: str) -> bool:
    settings = get_settings()
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_i < int(time.time()):
        return False
    expected = hmac.new(settings.file_url_secret.encode(), f"{key}:{exp_i}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)
