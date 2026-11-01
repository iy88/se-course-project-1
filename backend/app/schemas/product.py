"""商品相关 Pydantic 模型。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ProductStatus


class TagIn(BaseModel):
    category_id: int | None = None  # 已有标签
    new_name: str | None = Field(default=None, max_length=64)  # 或申请新标签


class ProductCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=5000)
    price_cents: int = Field(ge=0, le=100_000_000)
    image_keys: list[str] = Field(min_length=1)
    tags: list[TagIn]  # 至少一个已有标签或一个新标签申请（BR-12）


class ProductUpdateIn(BaseModel):
    """信息微调（BR-11）：允许状态下编辑不二审；交易中禁改（由服务层拒绝）。"""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=5000)
    price_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    image_keys: list[str] | None = None
    category_ids: list[int] | None = None  # 仅允许在已有标签间调整；新标签须重新走审核
    # 待审核期间撤回随商品提交的新标签申请（BR-10、D-46）
    withdraw_tag_application_ids: list[int] | None = None


class PendingTagApplicationOut(BaseModel):
    """卖方本人待审核期间可撤回的新标签申请（D-46/R11）。"""

    id: int
    requested_name: str


class DecidedTagApplicationOut(BaseModel):
    """卖方本人已处理的标签申请结果（含拒绝原因；历史记录原因可空）。"""

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
    # 受限商品的匿名公开结果（BR-25）：经原举报事项关联，仅确认后非空
    restriction_result: str | None = None
    reject_reason: str | None = None
    image_keys: list[str] = []
    image_urls: list[str] = []
    tag_ids: list[int] = []
    tag_names: list[str] = []
    # 仅卖方本人可见的当前有效待审标签申请；其他查看者恒为空
    pending_tag_applications: list[PendingTagApplicationOut] = []
    # 仅卖方本人可见的已处理标签申请及原因；历史记录原因可为空
    decided_tag_applications: list[DecidedTagApplicationOut] = []
    created_at: datetime
    updated_at: datetime
    pending_request_count: int = 0  # 卖方视角：待接受请求数
    can_withdraw_review: bool = False  # 卖方视角：待审核且未被认领，可撤回本次审核
    can_resubmit: bool = False  # 卖方视角：审核拒绝或认领前撤回后的已下架商品可重提


class ProductCardOut(BaseModel):
    """搜索/列表卡片。"""

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
    message: str | None = None  # 无匹配商品提示（BR-15）


class ProductEditHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    editor_id: int
    edit_type: str
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
