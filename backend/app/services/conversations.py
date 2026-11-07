"""IM conversation helpers (C-07/C-08): regular private-chat reuse, trade branches, system messages, and archiving."""
from datetime import UTC, datetime

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Conversation, Message
from app.models.enums import ConversationType, MessageKind
from app.realtime.events import emit_events


async def get_or_create_normal_conversation(db: AsyncSession, user_a: int, user_b: int) -> Conversation:
    """Reuse one regular private chat for the same pair of users (BR-18)."""
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
    """One dedicated trade branch per active request (BR-01/18)."""
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
    """Save a text message and write durable events for both parties in the same transaction.

    The sender's other devices are notified too, avoiding multi-device inconsistency;
    the message-sending HTTP request waits on no socket. The caller (API) commits or
    rolls back everything together with the audit.
    """
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
    await emit_events(
        db,
        member_ids,
        event_type="im.message",
        payload=payload,
        entity_type="conversation",
        entity_id=conversation.id,
    )
    return message


async def archive_trade_branch(db: AsyncSession, trade_id: int) -> None:
    """Archive the branch by default when a request/trade ends, retaining history (BR-18)."""
    result = await db.exec(
        select(Conversation).where(col(Conversation.type) == ConversationType.TRADE.value, col(Conversation.trade_id) == trade_id)
    )
    for conversation in result:
        if not conversation.archived:
            conversation.archived = True
            conversation.archived_at = datetime.now(UTC)


async def get_conversation_members(conversation: Conversation) -> list[int]:
    return [conversation.user_low_id, conversation.user_high_id]
