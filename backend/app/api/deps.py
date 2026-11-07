"""Dependency injection: current user, administrator, and ban validation."""

from contextvars import ContextVar
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User
from app.models.enums import AccountStatus, UserRole
from app.services import audit as audit_service

bearer_scheme = HTTPBearer(auto_error=False)
_TOKEN_EXPIRES_AT: ContextVar[int] = ContextVar("token_expires_at", default=0)


def current_token_expires_at() -> int:
    return _TOKEN_EXPIRES_AT.get()


async def get_audit_db(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AsyncSession:
    """Business request session: also exposes the same engine to the audit context for independent failure transactions.

    Uses a contextvar rather than Request injection so HTTP and WebSocket can share
    DbSession; the audit middleware only reads the engine and does not commit or close
    the business session.
    """
    audit_service.set_audit_bind(db.bind)
    return db


DbSession = Annotated[AsyncSession, Depends(get_audit_db)]


async def get_optional_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User | None:
    if credentials is None:
        return None
    payload = decode_access_token(credentials.credentials)
    if not payload:
        return None
    try:
        _TOKEN_EXPIRES_AT.set(int(payload.get("exp", 0)))
    except (TypeError, ValueError):
        _TOKEN_EXPIRES_AT.set(0)
    user = await db.get(User, int(payload["sub"]))
    if user is not None:
        # Audit context: success events and failure/denial events are attributed to the resolved actor.
        audit_service.set_actor(user.id, user.role)
    return user


async def get_current_user(
    user: Annotated[User | None, Depends(get_optional_user)],
) -> User:
    """BR-22: business content requires sign-in; unauthenticated/invalid tokens return 401."""
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录或登录已过期")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要平台管理员权限")
    return user


CurrentAdmin = Annotated[User, Depends(get_current_admin)]


def ensure_not_banned(user: User) -> None:
    """BR-32: banned accounts cannot perform business writes (except disposal communication cases, which individual endpoints may relax)."""
    if user.status == AccountStatus.BANNED.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账户已被封禁，当前操作不可用")


def ensure_can_write(user: User) -> None:
    ensure_not_banned(user)
