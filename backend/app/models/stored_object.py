"""对象登记：上传后 staged，业务引用后 committed。

物理对象与数据库事务不能跨系统提交，因此上传成功而登记失败时只允许补偿删除
本次刚创建的对象。业务记录引用对象后，登记状态转为 committed；任何自动清理
都只能处理 state=staged 且经实时引用查询确认无业务引用的对象。
"""

from datetime import datetime
from typing import Any, cast

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlmodel import Field

from app.db.session import Base
from app.db.types import JSONType


class StoredObject(Base, table=True):
    """一个逻辑对象 key 的登记与引用状态，不保存对象内容、签名 URL 或凭据。"""

    __tablename__ = cast(Any, "stored_objects")
    __table_args__ = (
        CheckConstraint(
            "state IN ('staged', 'committed', 'deleted')",
            name="state_allowed",
        ),
        CheckConstraint(
            "bucket_role IN ('media', 'evidence')",
            name="bucket_role_allowed",
        ),
        CheckConstraint(
            "(ref_type IS NULL) = (ref_id IS NULL)",
            name="reference_pair",
        ),
        Index("ix_stored_objects_state_created_at", "state", "created_at"),
        Index("ix_stored_objects_ref", "ref_type", "ref_id"),
    )

    key: str = Field(sa_column=Column(String(512), primary_key=True))
    namespace: str = Field(sa_column=Column(String(32), index=True, nullable=False))
    bucket_role: str = Field(sa_column=Column(String(16), nullable=False))
    owner_id: int | None = Field(default=None, sa_column=Column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    ))
    content_type: str = Field(sa_column=Column(String(64), nullable=False))
    size_bytes: int = Field(sa_column=Column(BigInteger, nullable=False))
    # 仅保存非敏感描述（原文件名、图片类型等），不得放入 URL、token 或对象正文。
    object_metadata: dict = Field(default_factory=dict, sa_column=Column(JSONType, default=dict, nullable=False))
    state: str = Field(default='staged', sa_column=Column(String(16), default="staged", index=True, nullable=False))
    ref_type: str | None = Field(default=None, sa_column=Column(String(32), nullable=True))
    ref_id: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))
    committed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    deleted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
