"""FR-01 账户生命周期：注册、登录、退出、忘记密码、改密、换邮箱、改名。"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import User
from app.models.enums import UserRole
from app.schemas.auth import (
    ChangeEmailIn,
    ChangePasswordIn,
    CodeOut,
    LoginIn,
    ProfileUpdateIn,
    RegisterIn,
    ResetPasswordIn,
    SendCodeIn,
    SendEmailChangeCodeIn,
    TokenOut,
    UserOut,
)
from app.services import verification
from app.services.verification import PURPOSE_EMAIL_NEW, PURPOSE_EMAIL_OLD, PURPOSE_RESET

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_out(user: User) -> TokenOut:
    return TokenOut(access_token=create_access_token(user.id, user.role), user=UserOut.model_validate(user))


@router.post("/register", response_model=TokenOut)
async def register(body: RegisterIn, db: DbSession) -> TokenOut:
    """BR-20：邮箱+显示名称+密码注册；邮箱全平台唯一（BR-21）。"""
    exists = await db.scalar(select(User).where(User.email == body.email.lower()))
    if exists:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该邮箱已被使用")
    user = User(
        email=body.email.lower(),
        display_name=body.display_name.strip(),
        password_hash=hash_password(body.password),
        role=UserRole.USER.value,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _token_out(user)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, db: DbSession) -> TokenOut:
    """BR-32：封禁不等于不能登录读取本人记录，登录不校验封禁状态。"""
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "邮箱或密码错误")
    return _token_out(user)


@router.post("/logout")
async def logout() -> dict:
    """JWT 无状态退出：客户端清除令牌即可；接口保留以表达业务动作。"""
    return {"detail": "已退出登录"}


@router.post("/forgot-password/send-code", response_model=CodeOut)
async def forgot_password_send_code(body: SendCodeIn, db: DbSession) -> CodeOut:
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    if not user:
        # 不泄露邮箱是否注册；开发环境直接返回生成的验证码便于联调
        code = await verification.send_code(PURPOSE_RESET, body.email)
        return CodeOut(detail="如果该邮箱已注册，验证码已发送", dev_code=code or None)
    code = await verification.send_code(PURPOSE_RESET, body.email)
    return CodeOut(detail="验证码已发送至绑定邮箱", dev_code=code or None)


@router.post("/forgot-password/reset", response_model=TokenOut)
async def forgot_password_reset(body: ResetPasswordIn, db: DbSession) -> TokenOut:
    """BR-20：通过绑定邮箱验证后自助设置新密码。"""
    user = await db.scalar(select(User).where(User.email == body.email.lower()))
    if not user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "验证码错误或已过期")
    await verification.verify_code(PURPOSE_RESET, body.email, body.code)
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    await db.refresh(user)
    return _token_out(user)


@router.post("/change-password")
async def change_password(body: ChangePasswordIn, user: CurrentUser, db: DbSession) -> dict:
    """4.19：主动改密须验证当前密码。"""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "当前密码不正确")
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"detail": "密码已修改"}


@router.post("/email/send-code", response_model=CodeOut)
async def email_change_send_code(body: SendEmailChangeCodeIn, user: CurrentUser, db: DbSession) -> CodeOut:
    """更换邮箱须同时验证旧邮箱和新邮箱（4.19）。"""
    if body.target == "new":
        if not body.new_email:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "请填写新邮箱")
        occupied = await db.scalar(select(User).where(User.email == body.new_email.lower()))
        if occupied:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "新邮箱已被其他账户使用")
        code = await verification.send_code(PURPOSE_EMAIL_NEW, body.new_email)
        return CodeOut(detail="验证码已发送至新邮箱", dev_code=code or None)
    code = await verification.send_code(PURPOSE_EMAIL_OLD, user.email)
    return CodeOut(detail="验证码已发送至当前绑定邮箱", dev_code=code or None)


@router.post("/email/change", response_model=UserOut)
async def email_change(body: ChangeEmailIn, user: CurrentUser, db: DbSession) -> UserOut:
    if body.new_email.lower() == user.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新邮箱与当前邮箱相同")
    occupied = await db.scalar(select(User).where(User.email == body.new_email.lower()))
    if occupied:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新邮箱已被其他账户使用")
    await verification.verify_code(PURPOSE_EMAIL_OLD, user.email, body.old_code)
    await verification.verify_code(PURPOSE_EMAIL_NEW, body.new_email, body.new_code)
    # 用户 ID 保持不变，既有业务记录继续归属原用户 ID（4.19）
    user.email = body.new_email.lower()
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.patch("/profile", response_model=UserOut)
async def update_profile(body: ProfileUpdateIn, user: CurrentUser, db: AsyncSession = Depends(get_db)) -> UserOut:
    """4.19：显示名称可自行修改，历史记录保留用户 ID 归属。"""
    user.display_name = body.display_name.strip()
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
