"""Commit boundaries that must not retain or prematurely finalize intents."""

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.models import RealtimeEvent, UserEventCounter
from app.realtime.events import emit_events
from tests.test_realtime_transactional import _db


async def _emit(db, value):
    await emit_events(db, [1], event_type="probe", payload={"value": value})


async def test_savepoint_commit_keeps_counter_locks_until_outer_commit(tmp_path):
    engine, maker = await _db(tmp_path, "nested-commit.db")
    try:
        async with maker() as db:
            async with db.begin():
                await _emit(db, "outer")
                async with db.begin_nested():
                    await _emit(db, "inner-committed")
                assert (await db.exec(select(RealtimeEvent))).all() == []
                assert (await db.exec(select(UserEventCounter))).all() == []
            rows = (await db.exec(select(RealtimeEvent).order_by(RealtimeEvent.user_seq))).all()
            assert [(r.user_seq, r.payload["value"]) for r in rows] == [
                (1, "outer"), (2, "inner-committed"),
            ]
    finally:
        await engine.dispose()


async def test_close_and_reuse_session_does_not_commit_abandoned_intents(tmp_path):
    engine, maker = await _db(tmp_path, "session-reuse.db")
    try:
        db = maker()
        try:
            await db.begin()
            await _emit(db, "abandoned")
            await db.close()
            await db.begin()
            await _emit(db, "fresh")
            await db.commit()
            rows = (await db.exec(select(RealtimeEvent))).all()
            assert [r.payload["value"] for r in rows] == ["fresh"]
        finally:
            await db.close()
    finally:
        await engine.dispose()


async def test_rollback_before_first_sql_discards_event_only_intents(tmp_path):
    engine, maker = await _db(tmp_path, "intent-only.db")
    try:
        async with maker() as db:
            await _emit(db, "rolled-back-before-sql")
            await db.rollback()
            await _emit(db, "fresh")
            await db.commit()
            rows = (await db.exec(select(RealtimeEvent))).all()
            assert [r.payload["value"] for r in rows] == ["fresh"]
    finally:
        await engine.dispose()


async def test_failed_flush_in_savepoint_preserves_outer_intents(tmp_path):
    engine, maker = await _db(tmp_path, "savepoint-constraint.db")
    try:
        async with maker() as db:
            db.add(UserEventCounter(user_id=1, last_seq=0))
            await db.commit()
            await _emit(db, "outer")
            try:
                async with db.begin_nested():
                    await _emit(db, "rolled-back")
                    db.add(UserEventCounter(user_id=1, last_seq=0))
                    await db.flush()
            except IntegrityError:
                pass
            await db.commit()
            rows = (await db.exec(select(RealtimeEvent))).all()
            assert [r.payload["value"] for r in rows] == ["outer"]
    finally:
        await engine.dispose()
