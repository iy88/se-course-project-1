"""Shared helpers for the strict real-resource suite."""

from __future__ import annotations

from app.core.security import create_access_token
from app.db.session import get_sessionmaker
from app.models import Conversation, Message, User
from app.models.realtime import (
    IdempotencyRecord,
    RealtimeEvent,
    RealtimeRetention,
    ServiceHeartbeat,
    UserEventCounter,
)
from sqlalchemy import delete
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession


def session():
    return get_sessionmaker()()


async def create_user(name: str) -> User:
    async with session() as db, db.begin():
        user = User(
            email=f"{name}@integration.invalid",
            password_hash="not-used",
            display_name=name,
            role="user",
            status="normal",
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user


async def create_conversation(a: int, b: int) -> Conversation:
    low, high = sorted((a, b))
    async with session() as db, db.begin():
        conversation = Conversation(type="normal", user_low_id=low, user_high_id=high)
        db.add(conversation)
        await db.flush()
        await db.refresh(conversation)
        return conversation


def token_for(user: User) -> str:
    return create_access_token(int(user.id), user.role)


async def clean_realtime_tables() -> None:
    async with session() as db, db.begin():
        for model in (RealtimeEvent, UserEventCounter, RealtimeRetention, IdempotencyRecord, ServiceHeartbeat):
            await db.execute(delete(model))


async def count_rows(model) -> int:
    async with session() as db:
        return int((await db.exec(select(func.count()).select_from(model))).first() or 0)


async def count_messages(conversation_id: int) -> int:
    async with session() as db:
        return int((await db.exec(
            select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id)
        )).first() or 0)


async def event_count_for(user_id: int) -> int:
    async with session() as db:
        return int((await db.exec(
            select(func.count()).select_from(RealtimeEvent).where(RealtimeEvent.recipient_user_id == user_id)
        )).first() or 0)


async def get_session() -> AsyncSession:  # pragma: no cover - helper alias
    return session()
