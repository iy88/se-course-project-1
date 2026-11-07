"""FR-01 account lifecycle: registration, login, logout, forgot password, password change, email change, and display-name change."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import CurrentUser, DbSession, get_optional_user
from app.core.security import create_access_token, hash_password, verify_password
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
from app.services import audit as audit_service
from app.services import permissions, verification
from app.services.verification import (
    PURPOSE_EMAIL_NEW,
    PURPOSE_EMAIL_OLD,
    PURPOSE_REGISTER,
    PURPOSE_RESET,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _normalized_email(email: str) -> str:
    """Registration, login, verification codes, and bound emails share the same normalization."""
    return email.strip().lower()


async def _user_out(db: AsyncSession, user: User) -> UserOut:
    frozen = await permissions.has_active_frozen_trade(db, user.id)
    from app.storage.base import get_storage
    storage = get_storage()
    return UserOut.model_validate(user).model_copy(update={"has_frozen_trade": frozen, "avatar_url": storage.public_url(user.avatar_key) if user.avatar_key else None, "avatar_pending_url": storage.public_url(user.avatar_pending_key) if user.avatar_pending_key else None})


async def _token_out(db: AsyncSession, user: User) -> TokenOut:
    return TokenOut(access_token=create_access_token(user.id, user.role), user=await _user_out(db, user))


@router.post("/register/send-code", response_model=CodeOut)
async def register_send_code(body: SendCodeIn, db: DbSession) -> CodeOut:
    """D-47: verify that the registrant controls the registration email before creating the account; in development the code is still returned."""
    email = _normalized_email(body.email)
    await verification.send_code(PURPOSE_REGISTER, email)
    return CodeOut(detail="验证码已发送，请验证当前注册邮箱后完成注册")


@router.post("/register", response_model=TokenOut)
async def register(body: RegisterIn, db: DbSession) -> TokenOut:
    """BR-20/D-47: create the account only after the registration email is verified, the email is unique, and the profile is valid."""
    email = _normalized_email(body.email)
    exists = (await db.exec(select(User).where(col(User.email) == email))).first()
    if exists:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该邮箱已被使用")
    # Purpose-bound, email-bound, and single-use; a failed verification creates no account
    await verification.verify_code(PURPOSE_REGISTER, email, body.code)
    user = User(
        email=email,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        role=UserRole.USER.value,
    )
    db.add(user)
    try:
        # Flush first to obtain the primary key and surface unique-constraint conflicts;
        # the audit write precedes the same commit so an audit failure rolls back account creation too.
        await db.flush()
    except IntegrityError:
        # For concurrent registrations of the same email, the unique constraint is the backstop, returning a business rejection rather than 500
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该邮箱已被使用") from None
    await audit_service.record_event(
        db,
        audit_service.EVENT_AUTH_REGISTER,
        target_type="user",
        target_id=user.id,
        actor_id=user.id,
        actor_role=user.role,
        after={"role": user.role},
    )
    await db.commit()
    await db.refresh(user)
    return await _token_out(db, user)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, db: DbSession) -> TokenOut:
    """BR-32: a ban does not prevent signing in to read one's own records; login does not check ban status."""
    user = (await db.exec(select(User).where(col(User.email) == _normalized_email(body.email)))).first()
    if user is not None:
        # A failed login for a known account is still attributable; an unknown email stays anonymous and is not written to the audit.
        audit_service.set_actor(user.id, user.role)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "邮箱或密码错误")
    await audit_service.record_event(
        db,
        audit_service.EVENT_AUTH_LOGIN_SUCCESS,
        target_type="user",
        target_id=user.id,
        actor_id=user.id,
        actor_role=user.role,
        after={"role": user.role},
    )
    await db.commit()
    return await _token_out(db, user)


@router.post("/logout")
async def logout(
    db: DbSession,
    user: Annotated[User | None, Depends(get_optional_user)],
) -> dict:
    """Stateless JWT logout: the client only needs to discard the token; the endpoint remains and records authenticated logout."""
    if user is not None:
        await audit_service.record_event(
            db,
            audit_service.EVENT_AUTH_LOGOUT,
            target_type="user",
            target_id=user.id,
            actor_id=user.id,
            actor_role=user.role,
        )
        await db.commit()
    return {"detail": "已退出登录"}


@router.post("/forgot-password/send-code", response_model=CodeOut)
async def forgot_password_send_code(body: SendCodeIn, db: DbSession) -> CodeOut:
    email = _normalized_email(body.email)
    user = (await db.exec(select(User).where(col(User.email) == email))).first()
    if not user:
        # Keep the response consistent; never return the verification code over HTTP
        return CodeOut(detail="如果该邮箱已注册，验证码已发送")
    await verification.send_code(PURPOSE_RESET, email)
    return CodeOut(detail="如果该邮箱已注册，验证码已发送")


@router.post("/forgot-password/reset", response_model=TokenOut)
async def forgot_password_reset(body: ResetPasswordIn, db: DbSession) -> TokenOut:
    """BR-20: self-service password reset after verification through the bound email."""
    email = _normalized_email(body.email)
    user = (await db.exec(select(User).where(col(User.email) == email))).first()
    if not user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "验证码错误或已过期")
    await verification.verify_code(PURPOSE_RESET, email, body.code)
    user.password_hash = hash_password(body.new_password)
    await audit_service.record_event(
        db,
        audit_service.EVENT_AUTH_PASSWORD_RESET,
        target_type="user",
        target_id=user.id,
        actor_id=user.id,
        actor_role=user.role,
    )
    await db.commit()
    await db.refresh(user)
    return await _token_out(db, user)


@router.post("/change-password")
async def change_password(body: ChangePasswordIn, user: CurrentUser, db: DbSession) -> dict:
    """4.19: a voluntary password change must verify the current password."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "当前密码不正确")
    user.password_hash = hash_password(body.new_password)
    await audit_service.record_event(
        db,
        audit_service.EVENT_AUTH_PASSWORD_CHANGE,
        target_type="user",
        target_id=user.id,
        actor_id=user.id,
        actor_role=user.role,
    )
    await db.commit()
    return {"detail": "密码已修改"}


@router.post("/email/send-code", response_model=CodeOut)
async def email_change_send_code(body: SendEmailChangeCodeIn, user: CurrentUser, db: DbSession) -> CodeOut:
    """Changing the email requires verifying both the old and new email addresses (4.19)."""
    if body.target == "new":
        if not body.new_email:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "请填写新邮箱")
        new_email = _normalized_email(body.new_email)
        occupied = (await db.exec(select(User).where(col(User.email) == new_email))).first()
        if occupied:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "新邮箱已被其他账户使用")
        await verification.send_code(PURPOSE_EMAIL_NEW, new_email)
        return CodeOut(detail="验证码已发送至新邮箱")
    await verification.send_code(PURPOSE_EMAIL_OLD, user.email)
    return CodeOut(detail="验证码已发送至当前绑定邮箱")


@router.post("/email/change", response_model=UserOut)
async def email_change(body: ChangeEmailIn, user: CurrentUser, db: DbSession) -> UserOut:
    new_email = _normalized_email(body.new_email)
    if new_email == user.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新邮箱与当前邮箱相同")
    occupied = (await db.exec(select(User).where(col(User.email) == new_email))).first()
    if occupied:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新邮箱已被其他账户使用")
    await verification.verify_code(PURPOSE_EMAIL_OLD, user.email, body.old_code)
    await verification.verify_code(PURPOSE_EMAIL_NEW, new_email, body.new_code)
    # The user ID stays unchanged, so existing business records keep their original user ID (4.19)
    user.email = new_email
    await audit_service.record_event(
        db,
        audit_service.EVENT_AUTH_EMAIL_CHANGE,
        target_type="user",
        target_id=user.id,
        actor_id=user.id,
        actor_role=user.role,
        after={"changed": True},
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "新邮箱已被其他账户使用") from None
    await db.refresh(user)
    return await _user_out(db, user)


@router.patch("/profile", response_model=UserOut)
async def update_profile(body: ProfileUpdateIn, user: CurrentUser, db: DbSession) -> UserOut:
    """4.19: users may change their display name; historical records retain ownership by user ID."""
    before_name = user.display_name
    user.display_name = body.display_name
    await audit_service.record_event(
        db,
        audit_service.EVENT_USER_PROFILE_UPDATE,
        target_type="user",
        target_id=user.id,
        actor_id=user.id,
        actor_role=user.role,
        before={"display_name": before_name},
        after={"display_name": user.display_name},
    )
    await db.commit()
    await db.refresh(user)
    return await _user_out(db, user)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser, db: DbSession) -> UserOut:
    return await _user_out(db, user)
