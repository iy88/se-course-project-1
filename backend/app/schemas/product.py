"""Pydantic models for products."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.text import NonBlank120, NonBlank5000, Text64
from app.models.enums import ProductStatus


class TagIn(BaseModel):
    category_id: int | None = None  # existing tag
    new_name: Text64 | None = Field(default=None)  # or request a new tag


class ProductCreateIn(BaseModel):
    title: NonBlank120
    description: NonBlank5000
    price_cents: int = Field(ge=0, le=100_000_000)
    image_keys: list[str] = Field(min_length=1)
    tags: list[TagIn]  # at least one existing tag or one new tag application (BR-12)


class ProductUpdateIn(BaseModel):
    """Minor information edits (BR-11): edits in allowed states need no second review; edits during a trade are rejected by the service layer."""

    title: NonBlank120 | None = Field(default=None)
    description: NonBlank5000 | None = Field(default=None)
    price_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    image_keys: list[str] | None = None
    category_ids: list[int] | None = None  # adjustment is only allowed among existing tags; new tags must go through review again
    # withdraw new tag applications submitted with the product while it is pending review (BR-10, D-46)
    withdraw_tag_application_ids: list[int] | None = None


class PendingTagApplicationOut(BaseModel):
    """A new tag application the seller may withdraw while it is pending review (D-46/R11)."""

    id: int
    requested_name: str


class DecidedTagApplicationOut(BaseModel):
    """Results of tag applications already handled for the seller (including rejection reasons; historical reasons may be null)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    requested_name: str
    status: str
    resolved_category_id: int | None = None
    decision_reason: str | None = None
    decided_at: datetime | None = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    seller_id: int
    title: str
    description: str
    price_cents: int
    status: ProductStatus
    display_restricted: bool = False
    display_restricted_reason: str | None = None
    # Anonymous public result for a restricted product (BR-25): linked through the original report and non-null only after confirmation
    restriction_result: str | None = None
    reject_reason: str | None = None
    image_keys: list[str] = []
    image_urls: list[str] = []
    tag_ids: list[int] = []
    tag_names: list[str] = []
    # Active pending tag applications visible only to the seller; always empty for other viewers
    pending_tag_applications: list[PendingTagApplicationOut] = []
    # Handled tag applications and reasons visible only to the seller; historical reasons may be null
    decided_tag_applications: list[DecidedTagApplicationOut] = []
    created_at: datetime
    updated_at: datetime
    pending_request_count: int = 0  # seller view: number of pending-acceptance requests
    can_withdraw_review: bool = False  # seller view: pending review and unclaimed, so this review can be withdrawn
    can_resubmit: bool = False  # seller view: a delisted product rejected in review or withdrawn before claim can be resubmitted


class ProductCardOut(BaseModel):
    """Search/list card."""

    id: int
    title: str
    price_cents: int
    image_url: str | None = None
    tag_ids: list[int] = []
    tag_names: list[str] = []
    status: ProductStatus
    seller_id: int
    seller_name: str = ""
    created_at: datetime


class ProductSearchOut(BaseModel):
    items: list[ProductCardOut]
    total: int
    message: str | None = None  # no-matching-products hint (BR-15)


class ProductEditHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    editor_id: int
    edit_type: str
    editor_name: str = ''
    before_image_urls: list[str] = Field(default_factory=list)
    after_image_urls: list[str] = Field(default_factory=list)
    before_json: dict
    after_json: dict
    reason: str | None
    created_at: datetime


class ReviewRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    reviewer_id: int | None
    result: str
    reason: str | None
    reviewed_at: datetime | None
    created_at: datetime
