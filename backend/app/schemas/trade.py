"""Pydantic models for trades."""

from pydantic import BaseModel, Field
from app.core.text import NonBlank100, NonBlank1000, NonBlank200, Text200, Text500


class RequestCreateIn(BaseModel):
    product_id: int
    note: Text500 | None = Field(default=None)


class RejectIn(BaseModel):
    reason: Text200 | None = Field(default=None)


class AgreementProposeIn(BaseModel):
    """Agreement elements (4.15): delivery time/text location/method plus agreed amount/payment method/payment timing."""

    delivery_time: NonBlank200
    delivery_location: NonBlank200
    delivery_method: NonBlank200
    amount_cents: int = Field(ge=0, le=100_000_000)
    payment_method: NonBlank100
    payment_timing: NonBlank200


class ConfirmationIn(BaseModel):
    note: Text500 | None = Field(default=None)


class DisputeIn(BaseModel):
    description: NonBlank1000


class CancelIn(BaseModel):
    reason: Text200 | None = Field(default=None)
