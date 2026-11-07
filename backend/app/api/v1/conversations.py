"""IM conversations and messages (C-07/C-08, BR-18): regular private chats and trade branches are organized under the same two-person entry point."""

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status
from sqlmodel import and_, col, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import idempotency as idempotency_service
from app.api.deps import CurrentUser, DbSession, ensure_can_write
from app.core.text import grapheme_count
from app.models import Conversation, ConversationRead, Message, Product, Trade, User
from app.models.enums import ConversationType
from app.schemas.conversation import (
    MessageIn,
    NormalConversationCreateIn,
    ReadAdvanceIn,
)
from app.services import audit as audit_service
from app.services import conversations as conversation_service
from app.services import im as im_service
from app.services.im import MAX_MESSAGE_LENGTH, ensure_member, pair_frozen

router = APIRouter(prefix="/conversations", tags=["conversations"])


async def _get_member_conversation(db: AsyncSession, conversation_id: int, user_id: int) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    try:
        await ensure_member(conversation, user_id)
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    return conversation


async def _get_last_read_id(db: AsyncSession, conversation_id: int, user_id: int) -> int:
    row = (await db.exec(
        select(ConversationRead).where(
            col(ConversationRead.conversation_id) == conversation_id, col(ConversationRead.user_id) == user_id
        )
    )).first()
    return row.last_read_message_id if row else 0


async def _existing_normal_conversation_id(
    db: AsyncSession, user_a: int, user_b: int
) -> int | None:
    """Regular private chats are reused by a stable key from the sorted user pair; used to distinguish creation from idempotent reuse (BR-18)."""
    low, high = sorted((user_a, user_b))
    return (await db.exec(
        select(col(Conversation.id)).where(
            col(Conversation.type) == ConversationType.NORMAL.value,
            col(Conversation.user_low_id) == low,
            col(Conversation.user_high_id) == high,
        )
    )).first()


async def _conversation_item(db: AsyncSession, conversation: Conversation, user_id: int) -> dict:
    last_read_id = await _get_last_read_id(db, conversation.id, user_id)
    unread = await im_service.unread_count(db, conversation.id, user_id, last_read_id)
    last_message = (await db.exec(
        select(Message).where(col(Message.conversation_id) == conversation.id).order_by(col(Message.id).desc()).limit(1)
    )).first()
    peer_name = await im_service.get_peer_display_name(db, conversation, user_id)
    peer_id = conversation.user_high_id if user_id == conversation.user_low_id else conversation.user_low_id
    item = {
        "id": conversation.id,
        "type": conversation.type,
        "peer_id": peer_id,
        "peer_name": peer_name,
        "archived": conversation.archived,
        "unread": unread,
        "last_message": (
            {
                "id": last_message.id,
                "sender_id": last_message.sender_id,
                "kind": last_message.kind,
                "content": last_message.content[:80],
                "created_at": last_message.created_at.isoformat() if last_message.created_at else None,
            }
            if last_message
            else None
        ),
        "trade": None,
    }
    if conversation.type == "trade" and conversation.trade_id:
        trade = await db.get(Trade, conversation.trade_id)
        product = await db.get(Product, trade.product_id) if trade else None
        item["trade"] = {
            "id": trade.id if trade else None,
            "status": trade.status if trade else None,
            "frozen": trade.frozen if trade else False,
            "product_id": trade.product_id if trade else None,
            "product_title": product.title if product else "",
            "my_role": "seller" if (trade and trade.seller_id == user_id) else "buyer",
        }
    return item




async def _conversation_items(db: AsyncSession, conversations: list[Conversation], user_id: int) -> list[dict]:
    """Batch projection for the conversation list (avoids per-row N+1 queries)."""
    if not conversations:
        return []
    ids = [c.id for c in conversations]
    unread_rows = (
        await db.exec(
            select(col(Message.conversation_id), func.count())
            .select_from(Message)
            .outerjoin(
                ConversationRead,
                and_(
                    col(ConversationRead.conversation_id) == col(Message.conversation_id),
                    col(ConversationRead.user_id) == user_id,
                ),
            )
            .where(
                col(Message.conversation_id).in_(ids),
                col(Message.id) > func.coalesce(col(ConversationRead.last_read_message_id), 0),
                or_(col(Message.sender_id) != user_id, col(Message.sender_id).is_(None)),
            )
            .group_by(col(Message.conversation_id))
        )
    ).all()
    unread = {int(cid): int(count) for cid, count in unread_rows}

    ranked = (
        select(
            col(Message.id).label("id"),
            col(Message.conversation_id).label("conversation_id"),
            col(Message.sender_id).label("sender_id"),
            col(Message.kind).label("kind"),
            col(Message.content).label("content"),
            col(Message.created_at).label("created_at"),
            func.row_number().over(
                partition_by=col(Message.conversation_id),
                order_by=col(Message.id).desc(),
            ).label("rn"),
        )
        .where(col(Message.conversation_id).in_(ids))
        .subquery()
    )
    last_rows = (
        await db.exec(
            select(ranked.c.id, ranked.c.conversation_id, ranked.c.sender_id, ranked.c.kind,
                   ranked.c.content, ranked.c.created_at).where(ranked.c.rn == 1)
        )
    ).all()
    last_message = {
        int(row.conversation_id): {
            "id": int(row.id),
            "sender_id": row.sender_id,
            "kind": row.kind,
            "content": row.content[:80],
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in last_rows
    }

    peers = {c.user_high_id if user_id == c.user_low_id else c.user_low_id for c in conversations}
    peer_names = {
        int(uid): name
        for uid, name in (await db.exec(select(col(User.id), col(User.display_name)).where(col(User.id).in_(peers)))).all()
    }
    trade_ids = {c.trade_id for c in conversations if c.type == "trade" and c.trade_id}
    trades = {int(t.id): t for t in (await db.exec(select(Trade).where(col(Trade.id).in_(trade_ids)))).all()} if trade_ids else {}
    product_ids = {t.product_id for t in trades.values()}
    products = {int(p.id): p for p in (await db.exec(select(Product).where(col(Product.id).in_(product_ids)))).all()} if product_ids else {}

    items: list[dict] = []
    for conversation in conversations:
        peer_id = conversation.user_high_id if user_id == conversation.user_low_id else conversation.user_low_id
        item = {
            "id": conversation.id,
            "type": conversation.type,
            "peer_id": peer_id,
            "peer_name": peer_names.get(peer_id, ""),
            "archived": conversation.archived,
            "unread": unread.get(conversation.id, 0),
            "last_message": last_message.get(conversation.id),
            "trade": None,
        }
        if conversation.type == "trade" and conversation.trade_id:
            trade = trades.get(int(conversation.trade_id))
            product = products.get(int(trade.product_id)) if trade else None
            item["trade"] = {
                "id": trade.id if trade else None,
                "status": trade.status if trade else None,
                "frozen": trade.frozen if trade else False,
                "product_id": trade.product_id if trade else None,
                "product_title": product.title if product else "",
                "my_role": "seller" if (trade and trade.seller_id == user_id) else "buyer",
            }
        items.append(item)
    return items


@router.get("")
async def list_conversations(user: CurrentUser, db: DbSession) -> list[dict]:
    """Show regular private chats and trade branches under the same two-person entry point (FR-04); batch projection avoids N+1."""
    result = await db.exec(
        select(Conversation)
        .where((col(Conversation.user_low_id) == user.id) | (col(Conversation.user_high_id) == user.id))
        .order_by(col(Conversation.id).desc())
    )
    return await _conversation_items(db, list(result), user.id)


@router.post("/normal", status_code=201)
async def create_normal(body: NormalConversationCreateIn, user: CurrentUser, db: DbSession) -> dict:
    """Start/reuse a regular private chat: no product or purchase request is required (BR-18)."""
    ensure_can_write(user)
    if body.peer_user_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能向本人发起私聊")
    peer = await db.get(User, body.peer_user_id)
    if not peer:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "对方用户不存在")
    existing_id = await _existing_normal_conversation_id(db, user.id, body.peer_user_id)
    conversation = await conversation_service.get_or_create_normal_conversation(db, user.id, body.peer_user_id)
    if existing_id is None:
        await audit_service.record_event(
            db,
            "im.conversation_create",
            target_type="conversation",
            target_id=conversation.id,
            after={"type": ConversationType.NORMAL.value, "peer_user_id": body.peer_user_id},
        )
    await db.commit()
    return {"id": conversation.id, "detail": "会话已就绪"}


@router.get("/unread-summary")
async def unread_summary(user: CurrentUser, db: DbSession) -> dict:
    result = await db.exec(
        select(col(Conversation.id)).where(
            (col(Conversation.user_low_id) == user.id) | (col(Conversation.user_high_id) == user.id)
        )
    )
    total = 0
    for conversation_id in result.all():
        last_read_id = await _get_last_read_id(db, conversation_id, user.id)
        total += await im_service.unread_count(db, conversation_id, user.id, last_read_id)
    return {"unread": total}


@router.get("/{conversation_id}")
async def conversation_detail(
    conversation_id: int,
    user: CurrentUser,
    db: DbSession,
    before_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict:
    """Conversation messages (reverse-ordered pagination). Viewing history does not change read state; /read advances it explicitly (BR-18)."""
    conversation = await _get_member_conversation(db, conversation_id, user.id)
    query = select(Message).where(col(Message.conversation_id) == conversation.id)
    if before_id is not None:
        query = query.where(col(Message.id) < before_id)
    result = await db.exec(query.order_by(col(Message.id).desc()).limit(limit))
    messages = list(result)
    messages.reverse()
    item = await _conversation_item(db, conversation, user.id)
    item["messages"] = [
        {
            "id": m.id,
            "sender_id": m.sender_id,
            "kind": m.kind,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "mine": m.sender_id == user.id,
        }
        for m in messages
    ]
    item["last_read_message_id"] = await _get_last_read_id(db, conversation.id, user.id)
    return item


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: int,
    body: MessageIn,
    user: CurrentUser,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict:
    """Send a text message: membership, ban, pair-freeze, and archive validation (BR-17/18/32/33).

    An optional Idempotency-Key shares the transaction with the message, audit, and
    durable event; reusing a key with different content is rejected.
    """
    key = idempotency_service.parse_key(idempotency_key)
    async with idempotency_service.guard(
        db, user.id, f"im.send:{conversation_id}", key, body.model_dump()
    ) as idem:
        if idem.replay is not None:
            return {
                "id": int((idem.replay.response or {}).get("id", 0)),
                "detail": "已发送",
                "replayed": True,
            }
        ensure_can_write(user)
        conversation = await _get_member_conversation(db, conversation_id, user.id)
        content = body.content.strip()
        if not content:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "消息内容不能为空")
        if grapheme_count(content) > MAX_MESSAGE_LENGTH:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"消息最长 {MAX_MESSAGE_LENGTH} 字")
        if conversation.archived:
            raise HTTPException(status.HTTP_409_CONFLICT, "该交易分支已归档，可转入普通私聊继续沟通")
        if await pair_frozen(db, conversation.user_low_id, conversation.user_high_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "当前双方交易沟通受限（冻结期间禁发），可查看历史或通过管理沟通处理")
        message = await conversation_service.send_text_message(db, conversation, user.id, content)
        await audit_service.record_event(
            db,
            audit_service.EVENT_IM_MESSAGE_SEND,
            target_type="conversation",
            target_id=conversation.id,
            after={"msg_id": message.id, "kind": message.kind},
        )
        await idem.complete(status_code=200, response={"id": message.id})
        await db.commit()
        return {"id": message.id, "detail": "已发送"}


@router.post("/{conversation_id}/read")
async def advance_read(conversation_id: int, body: ReadAdvanceIn, user: CurrentUser, db: DbSession) -> dict:
    """Mark only displayed messages as read (BR-18): advance the user's read pointer for this conversation."""
    conversation = await _get_member_conversation(db, conversation_id, user.id)
    max_id = (await db.exec(
        select(col(Message.id)).where(col(Message.conversation_id) == conversation.id).order_by(col(Message.id).desc()).limit(1)
    )).first()
    target = min(body.last_displayed_message_id, int(max_id or 0))
    row = (await db.exec(
        select(ConversationRead).where(
            col(ConversationRead.conversation_id) == conversation.id, col(ConversationRead.user_id) == user.id
        )
    )).first()
    previous_read_id = row.last_read_message_id if row is not None else 0
    if row is None:
        row = ConversationRead(conversation_id=conversation.id, user_id=user.id, last_read_message_id=target)
        db.add(row)
        changed = True
    elif target > row.last_read_message_id:
        row.last_read_message_id = target
        changed = True
    else:
        changed = False
    if changed:
        await audit_service.record_event(
            db,
            "im.read_advance",
            target_type="conversation",
            target_id=conversation.id,
            before={"last_read_id": previous_read_id},
            after={"last_read_id": row.last_read_message_id},
        )
    await db.commit()
    return {"last_read_message_id": row.last_read_message_id}


@router.post("/{conversation_id}/to-normal")
async def migrate_to_normal(conversation_id: int, user: CurrentUser, db: DbSession) -> dict:
    """Guide an archived branch into a regular private chat: no messages are migrated and nothing is sent automatically (BR-18)."""
    conversation = await _get_member_conversation(db, conversation_id, user.id)
    peer_id = conversation.user_high_id if user.id == conversation.user_low_id else conversation.user_low_id
    existing_id = await _existing_normal_conversation_id(db, user.id, peer_id)
    normal = await conversation_service.get_or_create_normal_conversation(db, user.id, peer_id)
    if existing_id is None:
        await audit_service.record_event(
            db,
            "im.conversation_to_normal",
            target_type="conversation",
            target_id=normal.id,
            after={"type": ConversationType.NORMAL.value, "source_conversation_id": conversation.id},
        )
    await db.commit()
    return {"id": normal.id, "detail": "已转入普通私聊（历史消息不迁移）"}
