"""Offline transaction semantics: events share the business transaction."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Conversation, Notification, RealtimeEvent, User
from app.realtime.events import emit_events
from app.services.conversations import send_text_message
from app.services.notifications import notify


async def _db(tmp_path, name: str):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")
    from app.db.session import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def test_message_and_events_rollback_together(tmp_path):
    engine, maker = await _db(tmp_path, "tx.db")
    async with maker() as db, db.begin():
        a = User(email="a@example.com", password_hash="x", display_name="a", role="user", status="normal")
        b = User(email="b@example.com", password_hash="x", display_name="b", role="user", status="normal")
        db.add_all([a, b])
        await db.flush()
        conversation = Conversation(type="normal", user_low_id=min(a.id, b.id), user_high_id=max(a.id, b.id))
        db.add(conversation)
        await db.flush()
        await send_text_message(db, conversation, a.id, "hello")
        # Intents are intentionally not turned into rows until commit.
        assert db.sync_session.info["realtime_event_intents"]
        assert (await db.exec(select(RealtimeEvent))).all() == []
        await db.rollback()
    async with maker() as db:
        assert (await db.exec(select(RealtimeEvent))).all() == []
        assert (await db.exec(select(Notification))).all() == []
    await engine.dispose()


async def test_message_and_events_commit_together(tmp_path):
    engine, maker = await _db(tmp_path, "commit.db")
    async with maker() as db, db.begin():
        a = User(email="ca@example.com", password_hash="x", display_name="a", role="user", status="normal")
        b = User(email="cb@example.com", password_hash="x", display_name="b", role="user", status="normal")
        db.add_all([a, b])
        await db.flush()
        conversation = Conversation(type="normal", user_low_id=min(a.id, b.id), user_high_id=max(a.id, b.id))
        db.add(conversation)
        await db.flush()
        await send_text_message(db, conversation, a.id, "hello")
    async with maker() as db:
        events = (await db.exec(select(RealtimeEvent).order_by(RealtimeEvent.user_seq))).all()
        assert len(events) == 2
        assert sorted(event.user_seq for event in events) == [1, 1]
    await engine.dispose()


async def test_notify_creates_notification_and_event_in_same_transaction(tmp_path):
    engine, maker = await _db(tmp_path, "notify.db")
    async with maker() as db, db.begin():
        user = User(email="n@example.com", password_hash="x", display_name="n", role="user", status="normal")
        db.add(user)
        await db.flush()
        created = await notify(db, [user.id], "trade_completed", "完成", link_type="trade", link_id=9)
        assert len(created) == 1
    async with maker() as db:
        assert len((await db.exec(select(Notification))).all()) == 1
        events = (await db.exec(select(RealtimeEvent))).all()
        assert len(events) == 1
        assert events[0].payload["type"] == "notification"
        assert events[0].payload["event"] == "trade_completed"
    await engine.dispose()


async def test_payload_limit_rejects_without_business_commit(tmp_path):
    import json

    from app.core.config import get_settings
    from app.realtime.events import EventValidationError

    engine, maker = await _db(tmp_path, "limit.db")
    async with maker() as db, db.begin():
        user = User(email="p@example.com", password_hash="x", display_name="p", role="user", status="normal")
        db.add(user)
        await db.flush()
        too_big = "x" * (get_settings().realtime_payload_max_bytes + 10)
        with pytest.raises(EventValidationError):
            await emit_events(db, [user.id], event_type="test", payload={"type": "x", "body": too_big})
        assert json.dumps({"ok": True})
    await engine.dispose()


async def test_savepoint_rollback_drops_only_its_event_intents(tmp_path):
    engine, maker = await _db(tmp_path, "savepoint.db")
    async with maker() as db, db.begin():
        a = User(email="sa@example.com", password_hash="x", display_name="a", role="user", status="normal")
        b = User(email="sb@example.com", password_hash="x", display_name="b", role="user", status="normal")
        db.add_all([a, b])
        await db.flush()
        conversation = Conversation(type="normal", user_low_id=min(a.id, b.id), user_high_id=max(a.id, b.id))
        db.add(conversation)
        await db.flush()
        await send_text_message(db, conversation, a.id, "outer")
        savepoint = await db.begin_nested()
        await send_text_message(db, conversation, a.id, "rolled-back")
        await savepoint.rollback()
        await send_text_message(db, conversation, a.id, "after")
    async with maker() as db:
        payloads = [event.payload["content"] for event in
                    (await db.exec(select(RealtimeEvent).order_by(RealtimeEvent.payload))).all()]
        assert "rolled-back" not in payloads
        assert payloads.count("outer") == 2
        assert payloads.count("after") == 2
    await engine.dispose()
