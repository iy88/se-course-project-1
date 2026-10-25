"""C-07 IM 会话（普通私聊/交易分支）、C-08 消息、会话已读。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.enums import ConversationType, MessageKind


class Conversation(Base):
    """普通私聊按双人复用；交易分支按请求/交易独立（BR-18）。user_low/high 用于唯一约束。"""

    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "uq_normal_pair",
            "user_low_id",
            "user_high_id",
            unique=True,
            sqlite_where=text("type = 'normal'"),
        ),
        Index("uq_trade_branch", "trade_id", unique=True, sqlite_where=text("type = 'trade'")),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(16), default=ConversationType.NORMAL.value)
    user_low_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    user_high_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    trade_id: Mapped[int | None] = mapped_column(ForeignKey("trades.id"), nullable=True, index=True)
    archived: Mapped[bool] = mapped_column(default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation", order_by="Message.id")


class Message(Base):
    """C-08：文字消息与系统消息；不向非会话成员公开（BR-18/19）。"""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)  # 系统消息为空
    kind: Mapped[str] = mapped_column(String(16), default=MessageKind.TEXT.value)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class ConversationRead(Base):
    """会话级已读进度：仅打开并展示消息时推进（BR-18）。"""

    __tablename__ = "conversation_reads"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    last_read_message_id: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
