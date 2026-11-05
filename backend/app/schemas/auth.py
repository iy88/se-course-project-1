"""认证与账户相关 Pydantic 模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.text import NonBlank64
from app.models.enums import AccountStatus, UserRole


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    display_name: str
    role: UserRole
    status: AccountStatus
    avatar_url: str | None = None
    avatar_pending_url: str | None = None
    avatar_review_status: str | None = None
    avatar_review_reason: str | None = None
    has_frozen_trade: bool = False  # 当前是否存在有效交易冻结（D-50，供前端刷新限制）
    created_at: datetime


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str


class RegisterIn(BaseModel):
    email: EmailStr
    display_name: NonBlank64
    password: str = Field(min_length=6, max_length=72)
    code: str = Field(pattern=r"^\d{6}$")  # 注册邮箱验证码（D-47）

    @field_validator("display_name")
    @classmethod
    def _display_name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("显示名称不能为空白")
        return value.strip()


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class SendCodeIn(BaseModel):
    email: EmailStr


class CodeOut(BaseModel):
    detail: str


class ResetPasswordIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=6, max_length=72)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=72)


class SendEmailChangeCodeIn(BaseModel):
    target: str = Field(pattern="^(old|new)$")  # 向旧绑定邮箱或新邮箱发码
    new_email: EmailStr | None = None  # target=new 时必填


class ChangeEmailIn(BaseModel):
    new_email: EmailStr
    old_code: str = Field(pattern=r"^[0-9]{6}$")
    new_code: str = Field(pattern=r"^[0-9]{6}$")


class ProfileUpdateIn(BaseModel):
    display_name: NonBlank64

    @field_validator("display_name")
    @classmethod
    def _display_name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("显示名称不能为空白")
        return value.strip()
