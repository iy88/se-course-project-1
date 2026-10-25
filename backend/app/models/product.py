"""C-02 商品、C-04 审核记录、C-05 收藏、C-06 商品评论、C-16 禁发范围。"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import ProductStatus, ReviewResult


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    price_cents: Mapped[int] = mapped_column(BigInteger)  # 标价（分）
    status: Mapped[str] = mapped_column(String(24), default=ProductStatus.PENDING_REVIEW.value, index=True)

    # 展示限制（违规撤销公开访问，TR-09/10）：与生命周期状态分开（4.10）
    display_restricted: Mapped[bool] = mapped_column(default=False)
    display_restricted_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    display_restricted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 待审核/未通过的最新说明（历史结论看 review_records）
    reject_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    listed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    images: Mapped[list["ProductImage"]] = relationship(back_populates="product", order_by="ProductImage.sort")
    tags: Mapped[list["Category"]] = relationship(
        "Category", secondary="product_tags", lazy="selectin", order_by="Category.id"
    )


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    file_key: Mapped[str] = mapped_column(String(255))
    sort: Mapped[int] = mapped_column(default=0)

    product: Mapped[Product] = relationship(back_populates="images")


class ProductTag(Base):
    __tablename__ = "product_tags"
    __table_args__ = (UniqueConstraint("product_id", "category_id"),)

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), primary_key=True)


class ProductTagApplication(Base):
    """随商品提交的新标签申请：商品审核通过时一并批准生效（4.16）。"""

    __tablename__ = "product_tag_applications"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    requested_name: Mapped[str] = mapped_column(String(64))
    # pending / approved_new / approved_alias / rejected
    status: Mapped[str] = mapped_column(String(24), default="pending")
    resolved_category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProductEditHistory(Base):
    """编辑历史：保留前后内容、修改人及时间（BR-11、4.18）；管理员分类纠正同表留痕。"""

    __tablename__ = "product_edit_histories"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    editor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    edit_type: Mapped[str] = mapped_column(String(24), default="edit")  # edit / category_correction
    before_json: Mapped[dict] = mapped_column(JSON)
    after_json: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewRecord(Base):
    """C-04：一次商品内容审核的结论（重提形成独立记录，历史保留）。"""

    __tablename__ = "review_records"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    content_json: Mapped[dict] = mapped_column(JSON)  # 当次被审核内容
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    result: Mapped[str] = mapped_column(String(16), default=ReviewResult.PENDING.value)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 不通过原因（含退回补充）
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("disposal_cases.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Favorite(Base):
    """C-05：本人收藏，仅本人可见（BR-16）。"""

    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "product_id"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Comment(Base):
    """C-06：商品页评论（咨询），卖方可回复买方；逻辑删除保留历史（BR-17）。"""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    reply_to_comment_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id"), nullable=True)
    reply_to_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    delete_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("uq_product_active", Product.seller_id, Product.status)


class ProhibitedItem(Base):
    """C-16：禁发细目（管理员维护，登录用户发布前可查看；BR-13/22）。"""

    __tablename__ = "prohibited_items"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    group_name: Mapped[str] = mapped_column(String(64))  # 类别（如“危险品与管制物品”）
    content: Mapped[str] = mapped_column(String(500))  # 细目
    sort: Mapped[int] = mapped_column(default=0)
    updated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
