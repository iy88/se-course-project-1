"""IM 业务校验辅助：成员、封禁、双人冻结范围（BR-32/33/18）。"""
from sqlmodel import and_, col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Conversation, Trade, User
from app.models.enums import LOCKING_TRADE_STATUSES

MAX_MESSAGE_LENGTH = 2000


async def ensure_member(conversation: Conversation, user_id: int) -> None:
    if user_id not in (conversation.user_low_id, conversation.user_high_id):
        raise PermissionError("非会话成员无权访问")

async def pair_frozen(db: AsyncSession, user_a: int, user_b: int) -> bool:
    """双方之间存在任一有效交易冻结：两人之间普通私聊与全部交易分支禁发（BR-33）。"""
    low, high = sorted((user_a, user_b))
    result = await db.exec(
        select(col(Trade.id)).where(
            col(Trade.frozen).is_(True),
            col(Trade.status).in_([s.value for s in LOCKING_TRADE_STATUSES]),
            or_(
                and_(col(Trade.buyer_id) == low, col(Trade.seller_id) == high),
                and_(col(Trade.buyer_id) == high, col(Trade.seller_id) == low),
            ),
        ).limit(1)
    )
    return result.one_or_none() is not None


async def get_peer_display_name(db: AsyncSession, conversation: Conversation, viewer_id: int) -> str:
    peer_id = conversation.user_high_id if viewer_id == conversation.user_low_id else conversation.user_low_id
    peer = await db.get(User, peer_id)
    return peer.display_name if peer else ""


async def unread_count(db: AsyncSession, conversation_id: int, user_id: int, last_read_id: int) -> int:
    from sqlmodel import func, or_

    from app.models import Message

    return (await db.exec(
        select(func.count())
        .select_from(Message)
        .where(
            col(Message.conversation_id) == conversation_id,
            col(Message.id) > last_read_id,
            or_(col(Message.sender_id) != user_id, col(Message.sender_id).is_(None)),  # 系统消息计入未读
        )
    )).first() or 0
