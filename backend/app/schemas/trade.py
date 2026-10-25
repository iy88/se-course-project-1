"""交易相关 Pydantic 模型。"""

from pydantic import BaseModel, Field


class RequestCreateIn(BaseModel):
    product_id: int
    note: str | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class AgreementProposeIn(BaseModel):
    """约定要素（4.15）：交付时间/文字地点/方式 + 约定金额/支付方式/支付时点。"""

    delivery_time: str = Field(min_length=1, max_length=200)
    delivery_location: str = Field(min_length=1, max_length=200)
    delivery_method: str = Field(min_length=1, max_length=200)
    amount_cents: int = Field(ge=0, le=100_000_000)
    payment_method: str = Field(min_length=1, max_length=100)
    payment_timing: str = Field(min_length=1, max_length=200)


class ConfirmationIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class DisputeIn(BaseModel):
    description: str = Field(min_length=1, max_length=1000)


class CancelIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)
