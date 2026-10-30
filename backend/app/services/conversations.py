"""IM 会话辅助（C-07/C-08）：普通私聊复用、交易分支、系统消息、归档。"""
from datetime import UTC, datetime

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Conversation, Message
from app.models.enums import ConversationType, MessageKind
from app.ws.manager import manager


async def get_or_create_normal_conversation(db: AsyncSession, user_a: int, user_b: int) -> Conversation:
    """同一对用户复用普通私聊（BR-18）。"""
    low, high = sorted((user_a, user_b))
    result = await db.exec(
        select(Conversation).where(
            col(Conversation.type) == ConversationType.NORMAL.value,
            col(Conversation.user_low_id) == low,
            col(Conversation.user_high_id) == high,
        )
    )
    conversation = result.one_or_none()
    if conversation is None:
        conversation = Conversation(type=ConversationType.NORMAL.value, user_low_id=low, user_high_id=high)
        db.add(conversation)
        await db.flush()
    return conversation


async def create_trade_branch(db: AsyncSession, trade_id: int, buyer_id: int, seller_id: int) -> Conversation:
    """每笔有效请求一个独立交易分支（BR-01/18）。"""
    low, high = sorted((buyer_id, seller_id))
    conversation = Conversation(
        type=ConversationType.TRADE.value,
        user_low_id=low,
        user_high_id=high,
        trade_id=trade_id,
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def send_system_message(db: AsyncSession, conversation_id: int, content: str) -> Message:
    message = Message(conversation_id=conversation_id, sender_id=None, kind=MessageKind.SYSTEM.value, content=content)
    db.add(message)
    await db.flush()
    return message


async def send_text_message(
    db: AsyncSession, conversation: Conversation, sender_id: int, content: str
) -> Message:
    """保存文字消息并推送给会话其他成员。"""
    message = Message(conversation_id=conversation.id, sender_id=sender_id, kind=MessageKind.TEXT.value, content=content)
    db.add(message)
    await db.flush()
    payload = {
        "type": "message",
        "conversation_id": conversation.id,
        "message_id": message.id,
        "sender_id": sender_id,
        "kind": message.kind,
        "content": message.content,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }
    member_ids = [conversation.user_low_id, conversation.user_high_id]
    await manager.push_to_users([uid for uid in member_ids if uid != sender_id], payload)
    return message


async def archive_trade_branch(db: AsyncSession, trade_id: int) -> None:
    """请求/交易结束默认归档分支，历史保留（BR-18）。"""
    result = await db.exec(
        select(Conversation).where(col(Conversation.type) == ConversationType.TRADE.value, col(Conversation.trade_id) == trade_id)
    )
    for conversation in result:
        if not conversation.archived:
            conversation.archived = True
            conversation.archived_at = datetime.now(UTC)


async def get_conversation_members(conversation: Conversation) -> list[int]:
    return [conversation.user_low_id, conversation.user_high_id]
