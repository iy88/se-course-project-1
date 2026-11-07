"""C-02 products, C-04 review records, C-05 favorites, C-06 product comments, C-16 prohibited items."""

from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship, col

from app.db.session import Base
from app.db.types import JSONType
from app.models.enums import ProductStatus, ReviewResult

if TYPE_CHECKING:
    from app.models.category import Category


class Product(Base, table=True):
    __tablename__ = cast(Any, "products")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    seller_id: int = Field(sa_column=Column(ForeignKey("users.id"), index=True, nullable=False))
    title: str = Field(sa_column=Column(Text, nullable=False))
    description: str = Field(sa_column=Column(Text, nullable=False))
    price_cents: int = Field(sa_column=Column(BigInteger, nullable=False))  # list price (cents)
    status: str = Field(default=ProductStatus.PENDING_REVIEW.value, sa_column=Column(String(24), default=ProductStatus.PENDING_REVIEW.value, index=True, nullable=False))

    # Display restriction (violations revoke public access, TR-09/10): kept separate from the lifecycle status (4.10)
    display_restricted: bool = Field(default=False, sa_column=Column(Boolean, default=False, nullable=False))
    display_restricted_reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    display_restricted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    display_restricted_case_id: int | None = Field(default=None, sa_column=Column(
        ForeignKey(
            "disposal_cases.id", use_alter=True, name="fk_products_display_restricted_case_id_disposal_cases"
        ),
        nullable=True,
    ))

    # Latest note for pending review/rejection (historical conclusions live in review_records)
    reject_reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True))

    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    updated_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False))
    listed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    delisted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    images: list["ProductImage"] = Relationship(sa_relationship=relationship(
        back_populates="product", order_by="ProductImage.sort", lazy="selectin"
    ))
    tags: list["Category"] = Relationship(sa_relationship=relationship(
        "Category", secondary="product_tags", lazy="selectin", order_by="Category.id"
    ))


class ProductImage(Base, table=True):
    __tablename__ = cast(Any, "product_images")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    product_id: int = Field(sa_column=Column(ForeignKey("products.id"), index=True, nullable=False))
    file_key: str = Field(sa_column=Column(String(255), nullable=False))
    sort: int = Field(default=0, sa_column=Column(Integer, default=0, nullable=False))

    product: Product = Relationship(sa_relationship=relationship(back_populates="images"))


class ProductTag(Base, table=True):
    __tablename__ = cast(Any, "product_tags")

    product_id: int = Field(sa_column=Column(ForeignKey("products.id"), primary_key=True))
    category_id: int = Field(sa_column=Column(ForeignKey("categories.id"), primary_key=True))


class ProductTagApplication(Base, table=True):
    """New tag application submitted with a product: approved together when the product review passes (4.16)."""

    __tablename__ = cast(Any, "product_tag_applications")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    product_id: int = Field(sa_column=Column(ForeignKey("products.id"), index=True, nullable=False))
    requested_name: str = Field(sa_column=Column(Text, nullable=False))
    # pending / approved_new / approved_alias / rejected / withdrawn
    status: str = Field(default='pending', sa_column=Column(String(24), default="pending", nullable=False))
    resolved_category_id: int | None = Field(default=None, sa_column=Column(ForeignKey("categories.id"), nullable=True))
    # Administrator business note for this application; required non-empty only on rejection. Historical records may be null and are not backfilled.
    decision_reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    decided_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))


class ProductEditHistory(Base, table=True):
    """Edit history: retains before/after content, editor, and time (BR-11, 4.18); administrator category corrections are recorded in the same table."""

    __tablename__ = cast(Any, "product_edit_histories")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    product_id: int = Field(sa_column=Column(ForeignKey("products.id"), index=True, nullable=False))
    editor_id: int = Field(sa_column=Column(ForeignKey("users.id"), nullable=False))
    edit_type: str = Field(default='edit', sa_column=Column(String(24), default="edit", nullable=False))  # edit / category_correction
    before_json: dict = Field(sa_column=Column(JSONType, nullable=False))
    after_json: dict = Field(sa_column=Column(JSONType, nullable=False))
    reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))


class ReviewRecord(Base, table=True):
    """C-04: conclusion of one product content review (resubmission creates a separate record; history is retained)."""

    __tablename__ = cast(Any, "review_records")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    product_id: int = Field(sa_column=Column(ForeignKey("products.id"), index=True, nullable=False))
    content_json: dict = Field(sa_column=Column(JSONType, nullable=False))  # content reviewed at that time
    reviewer_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))
    result: str = Field(default=ReviewResult.PENDING.value, sa_column=Column(String(16), default=ReviewResult.PENDING.value, nullable=False))
    reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True))  # rejection reason (including requests for supplements)
    reviewed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    case_id: int | None = Field(default=None, sa_column=Column(ForeignKey("disposal_cases.id"), nullable=True))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))


class Favorite(Base, table=True):
    """C-05: a user's own favorites, visible only to that user (BR-16)."""

    __tablename__ = cast(Any, "favorites")
    __table_args__ = (UniqueConstraint("user_id", "product_id"),)

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    user_id: int = Field(sa_column=Column(ForeignKey("users.id"), index=True, nullable=False))
    product_id: int = Field(sa_column=Column(ForeignKey("products.id"), index=True, nullable=False))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))


class Comment(Base, table=True):
    """C-06: product-page comments (inquiries); the seller may reply to the buyer; soft deletion keeps history (BR-17)."""

    __tablename__ = cast(Any, "comments")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    product_id: int = Field(sa_column=Column(ForeignKey("products.id"), index=True, nullable=False))
    author_id: int = Field(sa_column=Column(ForeignKey("users.id"), index=True, nullable=False))
    content: str = Field(sa_column=Column(Text, nullable=False))
    reply_to_comment_id: int | None = Field(default=None, sa_column=Column(ForeignKey("comments.id"), nullable=True))
    reply_to_user_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))
    deleted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    deleted_by_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))
    delete_reason: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))


Index("uq_product_active", col(Product.seller_id), col(Product.status))


class ProhibitedItem(Base, table=True):
    """C-16: prohibited items (maintained by administrators, viewable by signed-in users before publishing; BR-13/22)."""

    __tablename__ = cast(Any, "prohibited_items")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    group_name: str = Field(sa_column=Column(Text, nullable=False))  # group (e.g. "hazardous and controlled goods")
    content: str = Field(sa_column=Column(Text, nullable=False))  # item
    sort: int = Field(default=0, sa_column=Column(Integer, default=0, nullable=False))
    updated_by_id: int = Field(sa_column=Column(ForeignKey("users.id"), nullable=False))
    updated_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False))
