"""认证与账户相关 Pydantic 模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import AccountStatus, UserRole


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    display_name: str
    role: UserRole
    status: AccountStatus
    created_at: datetime


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str


class RegisterIn(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=72)


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
    dev_code: str | None = None  # 仅开发环境返回，便于联调


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
    old_code: str = Field(min_length=6, max_length=6)
    new_code: str = Field(min_length=6, max_length=6)


class ProfileUpdateIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=64)
