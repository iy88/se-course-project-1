"""C-07 IM 会话（普通私聊/交易分支）、C-08 消息、会话已读。"""

from datetime import datetime
from typing import Any, cast

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
    text,
)
from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship

from app.db.session import Base
from app.models.enums import ConversationType, MessageKind


class Conversation(Base, table=True):
    """普通私聊按双人复用；交易分支按请求/交易独立（BR-18）。user_low/high 用于唯一约束。"""

    __tablename__ = cast(Any, "conversations")
    __table_args__ = (
        Index(
            "uq_normal_pair",
            "user_low_id",
            "user_high_id",
            unique=True,
            sqlite_where=text("type = 'normal'"),
            postgresql_where=text("type = 'normal'"),
        ),
        Index(
            "uq_trade_branch",
            "trade_id",
            unique=True,
            sqlite_where=text("type = 'trade'"),
            postgresql_where=text("type = 'trade'"),
        ),
    )

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    type: str = Field(default=ConversationType.NORMAL.value, sa_column=Column(String(16), default=ConversationType.NORMAL.value, nullable=False))
    user_low_id: int = Field(sa_column=Column(ForeignKey("users.id"), index=True, nullable=False))
    user_high_id: int = Field(sa_column=Column(ForeignKey("users.id"), index=True, nullable=False))
    trade_id: int | None = Field(default=None, sa_column=Column(ForeignKey("trades.id"), nullable=True, index=True))
    archived: bool = Field(default=False, sa_column=Column(Boolean, default=False, nullable=False))
    archived_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))

    messages: list["Message"] = Relationship(sa_relationship=relationship(back_populates="conversation", order_by="Message.id"))


class Message(Base, table=True):
    """C-08：文字消息与系统消息；不向非会话成员公开（BR-18/19）。"""

    __tablename__ = cast(Any, "messages")

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    conversation_id: int = Field(sa_column=Column(ForeignKey("conversations.id"), index=True, nullable=False))
    sender_id: int | None = Field(default=None, sa_column=Column(ForeignKey("users.id"), nullable=True))  # 系统消息为空
    kind: str = Field(default=MessageKind.TEXT.value, sa_column=Column(String(16), default=MessageKind.TEXT.value, nullable=False))
    content: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False))

    conversation: Conversation = Relationship(sa_relationship=relationship(back_populates="messages"))


class ConversationRead(Base, table=True):
    """会话级已读进度：仅打开并展示消息时推进（BR-18）。"""

    __tablename__ = cast(Any, "conversation_reads")
    __table_args__ = (UniqueConstraint("conversation_id", "user_id"),)

    id: int = Field(default=None, sa_column=Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True))
    conversation_id: int = Field(sa_column=Column(ForeignKey("conversations.id"), index=True, nullable=False))
    user_id: int = Field(sa_column=Column(ForeignKey("users.id"), index=True, nullable=False))
    last_read_message_id: int = Field(default=0, sa_column=Column(Integer, default=0, nullable=False))
    updated_at: datetime = Field(default=None, sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False))
