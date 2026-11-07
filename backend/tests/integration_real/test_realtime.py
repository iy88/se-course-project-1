"""Real PostgreSQL + Redis contract tests for issue #36.

These tests exercise actual row locks, SKIP LOCKED leases, Alembic grants and
Redis Lua/GETDEL semantics. SQLite results are not accepted as evidence for any
of them.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import redis.asyncio as aioredis
from app.api.audit_integration import install_audit
from app.api.v1 import api_router
from app.core.config import get_settings
from app.db.session import engine, get_sessionmaker
from app.kv.base import get_kv
from app.models import Conversation, Message, Product, Trade
from app.models.realtime import (
    IdempotencyRecord,
    RealtimeEvent,
    RealtimeRetention,
    UserEventCounter,
)
from app.realtime.dispatcher import OutboxDispatcher
from app.realtime.events import (
    advance_retention,
    emit_events,
    high_watermark,
    low_watermark,
    replay_events,
)
from app.realtime.gateway import Connection, Gateway
from app.realtime.tickets import consume_ticket, issue_ticket
from fastapi import FastAPI
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DBAPIError
from sqlmodel import func, select

from .support import (
    count_messages,
    create_conversation,
    create_user,
    event_count_for,
    token_for,
)


def api_app() -> FastAPI:
    from app.realtime.admission import install_admission_handler

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    install_audit(app)
    install_admission_handler(app)
    return app


def _recv(conn):
    return json.loads(conn.recv_stream.receive_nowait())


def _empty(conn) -> bool:
    return conn.recv_stream.statistics().current_buffer_used == 0


async def _redis():
    return aioredis.from_url(os.environ["CI_REALTIME_REDIS_URL"], decode_responses=True)


async def test_redis_fixed_window_ticket_lease_and_connection_limit():
    settings = get_settings()
    redis = await _redis()
    kv = get_kv()
    key = f"it:window:{secrets.token_hex(4)}"
    try:
        assert await kv.incr_with_ttl(key, 30) == 1
        first_ttl = await redis.pttl(settings.redis_key_prefix + key)
        assert 20_000 < first_ttl <= 30_000
        await redis.pexpire(settings.redis_key_prefix + key, 1000)
        assert await kv.incr_with_ttl(key, 30) == 2
        second_ttl = await redis.pttl(settings.redis_key_prefix + key)
        assert 0 < second_ttl <= 1000, "later hits must preserve the remaining TTL"

        ticket, _ttl = await issue_ticket(
            user_id=42,
            since=7,
            auth_expires_at=int(datetime.now(UTC).timestamp()) + 60,
            role="user",
        )
        results = await asyncio.gather(consume_ticket(ticket), consume_ticket(ticket))
        assert sum(1 for value in results if value is not None) == 1
        assert next(value for value in results if value is not None).since == 7

        lease_key = f"it:lease:{secrets.token_hex(4)}"
        assert await kv.acquire_lease(lease_key, "owner-a", 30) is True
        assert await kv.acquire_lease(lease_key, "owner-b", 30) is False
        assert await kv.release_lease(lease_key, "owner-b") is False
        assert await kv.renew_lease(lease_key, "owner-b", 30) is False
        assert await kv.release_lease(lease_key, "owner-a") is True

        conn_key = f"it:conns:{secrets.token_hex(4)}"
        assert await kv.register_connection(conn_key, "gateway-a:1", 60, 1) == 1
        assert await kv.register_connection(conn_key, "gateway-b:1", 60, 1) is None
        await kv.unregister_connection(conn_key, "gateway-a:1")
        assert await kv.register_connection(conn_key, "gateway-b:1", 60, 1) == 1
        await kv.unregister_connection(conn_key, "gateway-b:1")
    finally:
        await redis.delete(settings.redis_key_prefix + key)
        await redis.aclose()


async def test_rollback_has_no_event_and_concurrent_counter_init_is_safe():
    user = await create_user(f"counter-{secrets.token_hex(4)}")
    async with get_sessionmaker()() as db:
        await db.begin()
        await emit_events(db, [user.id], event_type="test", payload={"type": "test"})
        await db.rollback()
    assert await event_count_for(user.id) == 0

    async def publish() -> None:
        async with get_sessionmaker()() as db, db.begin():
            await emit_events(db, [user.id], event_type="test", payload={"type": "test"})

    await asyncio.gather(publish(), publish())
    async with get_sessionmaker()() as db:
        events = (await db.exec(
            select(RealtimeEvent).where(RealtimeEvent.recipient_user_id == user.id).order_by(RealtimeEvent.user_seq)
        )).all()
        counter = await db.get(UserEventCounter, user.id)
    assert [int(event.user_seq) for event in events] == [1, 2]
    assert int(counter.last_seq) == 2


@pytest.mark.asyncio
async def test_idempotency_key_produces_one_message_and_rejects_different_body():
    a = await create_user(f"idem-a-{secrets.token_hex(4)}")
    b = await create_user(f"idem-b-{secrets.token_hex(4)}")
    conversation = await create_conversation(a.id, b.id)
    token = token_for(a)
    app = api_app()
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "same-key-1"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first, second = await asyncio.gather(
            client.post(f"/api/v1/conversations/{conversation.id}/messages", json={"content": "hello"}, headers=headers),
            client.post(f"/api/v1/conversations/{conversation.id}/messages", json={"content": "hello"}, headers=headers),
        )
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["id"] == second.json()["id"]
        conflict = await client.post(
            f"/api/v1/conversations/{conversation.id}/messages",
            json={"content": "different"},
            headers=headers,
        )
        assert conflict.status_code == 409
    assert await count_messages(conversation.id) == 1
    async with get_sessionmaker()() as db:
        assert (await db.exec(select(IdempotencyRecord))).first() is not None
    assert await event_count_for(a.id) == 1
    assert await event_count_for(b.id) == 1


async def test_frozen_trade_blocks_message_without_event():
    buyer = await create_user(f"freeze-buyer-{secrets.token_hex(4)}")
    seller = await create_user(f"freeze-seller-{secrets.token_hex(4)}")
    async with get_sessionmaker()() as db, db.begin():
        product = Product(seller_id=seller.id, title="item", description="x", price_cents=100, status="in_transaction")
        db.add(product)
        await db.flush()
        trade = Trade(product_id=product.id, buyer_id=buyer.id, seller_id=seller.id,
                      status="in_progress", frozen=True)
        db.add(trade)
        await db.flush()
        conversation = Conversation(type="trade", user_low_id=buyer.id, user_high_id=seller.id,
                                    trade_id=trade.id)
        db.add(conversation)
        await db.flush()
        conversation_id = conversation.id
    app = api_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "should not send"},
            headers={"Authorization": f"Bearer {token_for(buyer)}"},
        )
    assert response.status_code == 403
    assert await count_messages(conversation_id) == 0
    assert await event_count_for(buyer.id) == 0
    assert await event_count_for(seller.id) == 0


async def test_dispatcher_does_not_hold_sql_during_publish_and_leases_take_over():
    user = await create_user(f"lease-{secrets.token_hex(4)}")
    async with get_sessionmaker()() as db, db.begin():
        await emit_events(db, [user.id], event_type="test", payload={"type": "test"})

    class BlockingStream:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.published: list[str] = []

        async def publish(self, frame, *, event_id, user_id, user_seq):
            self.started.set()
            await self.release.wait()
            self.published.append(event_id)
            return "1-0"

    stream = BlockingStream()
    dispatcher = OutboxDispatcher(get_settings(), stream=stream)
    task = asyncio.create_task(dispatcher.run_once())
    await asyncio.wait_for(stream.started.wait(), timeout=5)
    # The claim transaction was committed before publish; no SQL slot is held.
    assert engine.pool.checkedout() == 0
    stream.release.set()
    assert await asyncio.wait_for(task, timeout=5) == 1
    async with get_sessionmaker()() as db:
        event = (await db.exec(select(RealtimeEvent).where(RealtimeEvent.recipient_user_id == user.id))).one()
        assert event.delivered_at is not None

    # Simulate "published then crashed before confirm": a second worker can take
    # over the expired lease and confirm; the stale owner cannot overwrite it.
    async with get_sessionmaker()() as db, db.begin():
        await emit_events(db, [user.id], event_type="test", payload={"type": "test"})
    first = OutboxDispatcher(get_settings(), stream=None)
    claimed = await first._claim()
    assert len(claimed) == 1
    async with get_sessionmaker()() as db, db.begin():
        await db.exec(
            update(RealtimeEvent)
            .where(RealtimeEvent.event_id == claimed[0].event_id)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    second = OutboxDispatcher(get_settings(), stream=None)
    taken = await second._claim()
    assert [event.event_id for event in taken] == [claimed[0].event_id]
    await second._confirm(taken)
    await first._confirm(claimed)  # conditional on old owner; must be a no-op
    async with get_sessionmaker()() as db:
        row = await db.get(RealtimeEvent, claimed[0].event_id)
    assert row.delivered_at is not None
    assert row.attempts >= 2




async def test_retention_advances_low_watermark_only_after_delivery():
    user = await create_user(f"retain-{secrets.token_hex(4)}")
    async with get_sessionmaker()() as db, db.begin():
        await emit_events(db, [user.id], event_type="test", payload={"type": "test"})
    async with get_sessionmaker()() as db, db.begin():
        event = (await db.exec(select(RealtimeEvent).where(RealtimeEvent.recipient_user_id == user.id))).one()
        event.delivered_at = datetime.now(UTC)
        event.created_at = datetime.now(UTC) - timedelta(hours=100)
        db.add(event)
    async with get_sessionmaker()() as db, db.begin():
        deleted = await advance_retention(db)
    assert deleted == 1
    async with get_sessionmaker()() as db:
        assert await low_watermark(db, user.id) == 2
        assert await replay_events(db, user.id, after_seq=0) == []
        assert (await db.get(RealtimeRetention, user.id)).low_seq == 2


async def test_real_app_role_cannot_mutate_audit_or_run_ddl():
    async with engine.begin() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("UPDATE audit_events SET result='success'"))
    async with engine.begin() as conn:
        with pytest.raises(DBAPIError):
            await conn.execute(text("CREATE TABLE ci_should_not_exist (id int)"))
    async with engine.begin() as conn:
        # Realtime and idempotency tables are intentionally writable by the app.
        await conn.execute(text("SELECT count(*) FROM realtime_events"))




async def test_retention_does_not_advance_past_retained_out_of_order_event():
    user = await create_user(f"retain-order-{secrets.token_hex(4)}")
    async with get_sessionmaker()() as db, db.begin():
        await emit_events(db, [user.id], event_type="test", payload={"type": "one"})
        await emit_events(db, [user.id], event_type="test", payload={"type": "two"})
    async with get_sessionmaker()() as db, db.begin():
        events = (await db.exec(
            select(RealtimeEvent).where(RealtimeEvent.recipient_user_id == user.id).order_by(RealtimeEvent.user_seq)
        )).all()
        events[0].created_at = datetime.now(UTC)  # seq 1 is NOT expired
        events[1].created_at = datetime.now(UTC) - timedelta(hours=100)  # seq 2 is expired
        for event in events:
            event.delivered_at = datetime.now(UTC)
            db.add(event)
    async with get_sessionmaker()() as db, db.begin():
        # seq 2 is expired but sits behind retained seq 1: no prefix deletion.
        assert await advance_retention(db) == 0
    async with get_sessionmaker()() as db:
        assert await low_watermark(db, user.id) == 1
        remaining = await replay_events(db, user.id, after_seq=0)
        assert [int(event.user_seq) for event in remaining] == [1, 2]
    # Once the prefix is also expired, both contiguous rows are safely removed.
    async with get_sessionmaker()() as db, db.begin():
        events = (await db.exec(
            select(RealtimeEvent).where(RealtimeEvent.recipient_user_id == user.id)
        )).all()
        for event in events:
            event.created_at = datetime.now(UTC) - timedelta(hours=100)
            db.add(event)
    async with get_sessionmaker()() as db, db.begin():
        assert await advance_retention(db) == 2
    async with get_sessionmaker()() as db:
        assert await low_watermark(db, user.id) == 3


async def test_publish_idempotency_key_creates_one_product_case_and_audit(monkeypatch):
    seller = await create_user(f"pub-idem-{secrets.token_hex(4)}")
    async with get_sessionmaker()() as db, db.begin():
        from app.models import Category

        category = Category(name=f"cat-{secrets.token_hex(4)}", status="active", created_by_id=seller.id)
        db.add(category)
        await db.flush()
        category_id = category.id

    async def noop_validate(db, keys, owner_id):
        return None

    monkeypatch.setattr("app.api.v1.products._validate_image_keys", noop_validate)
    app = api_app()
    transport = httpx.ASGITransport(app=app)
    payload = {
        "title": "idempotent publish",
        "description": "body",
        "price_cents": 100,
        "image_keys": ["product/2026/11/06/00000000-0000-0000-0000-000000000001.jpg"],
        "tags": [{"category_id": category_id}],
    }
    headers = {"Authorization": f"Bearer {token_for(seller)}", "Idempotency-Key": "publish-key-1"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first, second = await asyncio.gather(
            client.post("/api/v1/products", json=payload, headers=headers),
            client.post("/api/v1/products", json=payload, headers=headers),
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]
    product_id = first.json()["id"]
    async with get_sessionmaker()() as db:
        from app.models import AuditEvent, DisposalCase, Product, ReviewRecord
        from sqlmodel import func

        assert int((await db.exec(
            select(func.count()).select_from(Product).where(Product.id == product_id)
        )).first() or 0) == 1
        assert int((await db.exec(
            select(func.count()).select_from(ReviewRecord).where(ReviewRecord.product_id == product_id)
        )).first() or 0) == 1
        assert int((await db.exec(
            select(func.count()).select_from(DisposalCase).where(DisposalCase.product_id == product_id)
        )).first() or 0) == 1
        assert int((await db.exec(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.event_type == "product.publish", AuditEvent.target_id == str(product_id)
            )
        )).first() or 0) == 1


async def test_conversation_list_batch_projection_on_real_pg():
    a = await create_user(f"list-a-{secrets.token_hex(4)}")
    b = await create_user(f"list-b-{secrets.token_hex(4)}")
    conversation = await create_conversation(a.id, b.id)
    async with get_sessionmaker()() as db, db.begin():
        first = Message(conversation_id=conversation.id, sender_id=b.id, kind="text", content="first")
        second = Message(conversation_id=conversation.id, sender_id=b.id, kind="text", content="second")
        db.add_all([first, second])
        from app.models import ConversationRead

        db.add(ConversationRead(conversation_id=conversation.id, user_id=a.id, last_read_message_id=0))
        await db.flush()
        expected_last = second.id
    app = api_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/conversations",
            headers={"Authorization": f"Bearer {token_for(a)}"},
        )
    assert response.status_code == 200, response.text
    item = next(row for row in response.json() if row["id"] == conversation.id)
    assert item["unread"] == 2
    assert item["peer_name"] == b.display_name
    assert item["last_message"]["id"] == expected_last


async def test_dispatcher_publishes_xadd_before_confirm():
    user = await create_user(f"xadd-{secrets.token_hex(4)}")
    async with get_sessionmaker()() as db, db.begin():
        await emit_events(db, [user.id], event_type="test", payload={"type": "test"})
    settings = get_settings()
    from app.realtime.stream import RealtimeStream, StreamReader

    stream = RealtimeStream(settings)
    reader = StreamReader(settings, stream.name)
    redis = await _redis()
    try:
        dispatcher = OutboxDispatcher(settings, stream=stream)
        assert await dispatcher.run_once() == 1
        rows = await reader.read("0-0", count=20)
        assert any(fields.get("event_id") for _entry, fields in rows)
    finally:
        await reader.close()
        await stream.close()
        await redis.delete(settings.redis_key_prefix + settings.realtime_stream_name)
        await redis.aclose()


async def test_catch_up_honors_nonzero_cursor_with_no_or_one_new_event():
    user = await create_user(f"cursor-{secrets.token_hex(4)}")
    async with get_sessionmaker()() as db, db.begin():
        for index in range(5):
            await emit_events(db, [user.id], event_type="test", payload={"type": "test", "n": index})
    settings = get_settings()
    gateway = Gateway(settings)
    conn = Connection(ws=None, user_id=user.id, since=5, sent_seq=5,
                      auth_expires_at=int(datetime.now(UTC).timestamp()) + 60, settings=settings)
    await gateway._catch_up(conn)
    frame = _recv(conn)
    assert frame["type"] == "replay_complete"
    assert frame["user_seq"] == 5 and frame["high_seq"] == 5
    assert conn.sent_seq == 5

    async with get_sessionmaker()() as db, db.begin():
        await emit_events(db, [user.id], event_type="test", payload={"type": "test", "n": 5})
    conn2 = Connection(ws=None, user_id=user.id, since=5, sent_seq=5,
                       auth_expires_at=int(datetime.now(UTC).timestamp()) + 60, settings=settings)
    await gateway._catch_up(conn2)
    delivered = _recv(conn2)
    assert delivered["type"] == "event" and delivered["user_seq"] == 6
    done = _recv(conn2)
    assert done["type"] == "replay_complete" and done["user_seq"] == 6
    assert conn2.sent_seq == 6


async def test_deferred_intents_avoid_abba_and_do_not_serialize_unrelated_users():
    a = await create_user(f"abba-a-{secrets.token_hex(4)}")
    b = await create_user(f"abba-b-{secrets.token_hex(4)}")
    async with get_sessionmaker()() as db, db.begin():
        p1 = Product(seller_id=a.id, title="p1", description="x", price_cents=1, status="listed")
        p2 = Product(seller_id=b.id, title="p2", description="x", price_cents=1, status="listed")
        db.add_all([p1, p2])
        await db.flush()
        p1_id, p2_id = p1.id, p2.id

    async def worker(order, product_id):
        async with get_sessionmaker()() as db, db.begin():
            await db.get(Product, product_id, with_for_update=True)
            for uid in order:
                await emit_events(db, [uid], event_type="test", payload={"type": "test"})
            await db.flush()

    # Business row locks are acquired before any counter; the two transactions
    # use opposite recipient orders and must still commit without an ABBA lock.
    await asyncio.wait_for(asyncio.gather(
        worker([b.id, a.id], p1_id),
        worker([a.id, b.id], p2_id),
    ), timeout=10)
    async with get_sessionmaker()() as db:
        assert await high_watermark(db, a.id) == 2
        assert await high_watermark(db, b.id) == 2

    # An open transaction that only has intents must not block an unrelated
    # user's finalization (no global event lock).
    holder = get_sessionmaker()()
    await holder.begin()
    await emit_events(holder, [b.id], event_type="test", payload={"type": "test"})
    await holder.flush()
    async def unrelated():
        async with get_sessionmaker()() as db, db.begin():
            await emit_events(db, [a.id], event_type="test", payload={"type": "test"})
    await asyncio.wait_for(unrelated(), timeout=5)
    await holder.rollback()
    await holder.close()


async def test_readiness_rejects_stale_release_or_stopping_heartbeat():
    from app.models.realtime import ServiceHeartbeat
    from app.realtime.health import readiness

    settings = get_settings().model_copy(update={"app_role": "worker"})
    async with get_sessionmaker()() as db, db.begin():
        db.add(ServiceHeartbeat(
            name=f"stale-{secrets.token_hex(4)}", role="worker", instance_id="x",
            release_id="other-release", protocol_version=2, status="ready", details={}, pid=1,
        ))
    payload, ok = await readiness(settings)
    assert ok is False
    assert payload["checks"]["worker"]["status"] is None


async def test_outbox_admission_rolls_back_business_and_recovers(monkeypatch):
    from app.models import AuditEvent
    from app.models import User as UserModel
    from app.models.realtime import RealtimeEvent
    from app.realtime import admission
    from app.realtime.events import emit_events

    user = await create_user(f"admit-{secrets.token_hex(4)}")
    async with get_sessionmaker()() as db, db.begin():
        for seq in range(1, 4):
            db.add(RealtimeEvent(recipient_user_id=user.id, user_seq=seq, event_type="test",
                                 payload={"type": "test"}))
    settings = get_settings().model_copy(update={
        "realtime_outbox_max_pending": 2,
        "realtime_outbox_max_age_seconds": 3600,
        "realtime_outbox_admission_cache_seconds": 0,
        "realtime_admission_enabled": True,
    })
    monkeypatch.setattr(admission, "get_settings", lambda: settings)
    admission.clear_admission_cache()
    email = f"rejected-{secrets.token_hex(4)}@integration.invalid"
    try:
        async with get_sessionmaker()() as db, db.begin():
            new_user = UserModel(email=email, password_hash="x", display_name="rejected",
                                 role="user", status="normal")
            db.add(new_user)
            await db.flush()
            db.add(AuditEvent(event_type="test.admission_success", actor_id=new_user.id,
                              actor_role="user", result="success"))
            await emit_events(db, [new_user.id], event_type="test", payload={"type": "test"})
    except admission.OutboxAdmissionError as exc:
        assert exc.reason == "backlog"
    else:  # pragma: no cover
        raise AssertionError("admission did not reject")
    async with get_sessionmaker()() as db:
        assert (await db.exec(select(UserModel).where(UserModel.email == email))).first() is None
        assert (await db.exec(select(AuditEvent).where(AuditEvent.event_type == "test.admission_success"))).first() is None
        assert int((await db.exec(
            select(func.count()).select_from(RealtimeEvent).where(RealtimeEvent.delivered_at.is_(None))
        )).first() or 0) == 3
        # Reads and dispatcher claim remain available while admission is closed.
        assert (await db.exec(select(RealtimeEvent).limit(1))).first() is not None
    dispatcher = OutboxDispatcher(settings, stream=None)
    assert len(await dispatcher._claim()) >= 1

    # Recover the backlog and clear the process cache: new business passes again.
    async with get_sessionmaker()() as db, db.begin():
        await db.exec(delete(RealtimeEvent))
    admission.clear_admission_cache()
    email2 = f"recovered-{secrets.token_hex(4)}@integration.invalid"
    async with get_sessionmaker()() as db, db.begin():
        recovered = UserModel(email=email2, password_hash="x", display_name="recovered",
                              role="user", status="normal")
        db.add(recovered)
        await db.flush()
        await emit_events(db, [recovered.id], event_type="test", payload={"type": "test"})
    async with get_sessionmaker()() as db:
        assert (await db.exec(select(UserModel).where(UserModel.email == email2))).first() is not None
        assert await high_watermark(db, recovered.id) == 1


async def test_api_returns_503_retry_after_and_rolls_back_message(monkeypatch):
    from app.realtime import admission

    a = await create_user(f"admit-api-a-{secrets.token_hex(4)}")
    b = await create_user(f"admit-api-b-{secrets.token_hex(4)}")
    conversation = await create_conversation(a.id, b.id)
    async with get_sessionmaker()() as db, db.begin():
        for seq in range(1, 3):
            db.add(RealtimeEvent(recipient_user_id=b.id, user_seq=seq, event_type="test",
                                 payload={"type": "test"}))
    settings = get_settings().model_copy(update={
        "realtime_outbox_max_pending": 1,
        "realtime_outbox_max_age_seconds": 3600,
        "realtime_outbox_admission_cache_seconds": 0,
        "realtime_admission_enabled": True,
    })
    monkeypatch.setattr(admission, "get_settings", lambda: settings)
    admission.clear_admission_cache()
    app = api_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/conversations/{conversation.id}/messages",
            json={"content": "must be rejected"},
            headers={"Authorization": f"Bearer {token_for(a)}"},
        )
    assert response.status_code == 503
    assert response.headers["Retry-After"] == str(settings.realtime_outbox_retry_after_seconds)
    assert await count_messages(conversation.id) == 0
