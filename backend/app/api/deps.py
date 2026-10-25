"""依赖注入：当前用户、管理员、封禁校验。"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User
from app.models.enums import AccountStatus, UserRole

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_optional_user(
    db: DbSession,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User | None:
    if credentials is None:
        return None
    payload = decode_access_token(credentials.credentials)
    if not payload:
        return None
    user = await db.get(User, int(payload["sub"]))
    return user


async def get_current_user(
    user: Annotated[User | None, Depends(get_optional_user)],
) -> User:
    """BR-22：业务内容要求已登录；未登录/无效令牌返回 401。"""
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
    """BR-32：封禁账户禁止业务写操作（处置沟通单除外，由各接口自行放宽）。"""
    if user.status == AccountStatus.BANNED.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账户已被封禁，当前操作不可用")


def ensure_can_write(user: User) -> None:
    ensure_not_banned(user)
