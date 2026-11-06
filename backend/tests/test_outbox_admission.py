"""Offline admission boundaries/cache isolation (real PG semantics separate)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models import RealtimeEvent
from app.realtime import admission


async def _engine(tmp_path, name):
    from app.db.session import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _pending(session, user_id, seq, old=False):
    session.add(RealtimeEvent(
        recipient_user_id=user_id, user_seq=seq, event_type="test", payload={"type": "test"},
        created_at=datetime.now(UTC) - timedelta(hours=2) if old else datetime.now(UTC),
    ))
    await session.flush()


async def test_admission_cache_is_engine_isolated_and_can_be_disabled(tmp_path, monkeypatch):
    settings = get_settings().model_copy(update={
        "realtime_outbox_max_pending": 2,
        "realtime_outbox_max_age_seconds": 3600,
        "realtime_outbox_admission_cache_seconds": 60,
    })
    monkeypatch.setattr(admission, "get_settings", lambda: settings)
    admission.clear_admission_cache()
    e1, m1 = await _engine(tmp_path, "a.db")
    e2, m2 = await _engine(tmp_path, "b.db")
    try:
        async with m1() as db, db.begin():
            await _pending(db, 1, 1)
        async with m1() as db:
            await db.run_sync(lambda sync: admission.check_outbox_admission(sync))  # cache engine 1 = 1
        async with m2() as db, db.begin():
            for seq in range(1, 4):
                await _pending(db, 2, seq)
        async with m2() as db:
            # Same process, different engine/database: must not reuse engine 1's
            # cached count (1 would pass; actual 3 exceeds the limit).
            with pytest.raises(admission.OutboxAdmissionError):
                await db.run_sync(lambda sync: admission.check_outbox_admission(sync))
    finally:
        await e1.dispose()
        await e2.dispose()
        admission.clear_admission_cache()


async def test_admission_age_limit_and_zero_cache(tmp_path, monkeypatch):
    settings = get_settings().model_copy(update={
        "realtime_outbox_max_pending": 100,
        "realtime_outbox_max_age_seconds": 60,
        "realtime_outbox_admission_cache_seconds": 0,
    })
    monkeypatch.setattr(admission, "get_settings", lambda: settings)
    admission.clear_admission_cache()
    engine, maker = await _engine(tmp_path, "age.db")
    try:
        async with maker() as db, db.begin():
            await _pending(db, 1, 1, old=True)
        async with maker() as db:
            with pytest.raises(admission.OutboxAdmissionError) as exc:
                await db.run_sync(lambda sync: admission.check_outbox_admission(sync))
            assert exc.value.reason == "backlog"
            assert exc.value.age_seconds >= 60
    finally:
        await engine.dispose()
        admission.clear_admission_cache()


async def test_admission_handler_returns_stable_503_with_retry_after():
    import httpx
    from fastapi import FastAPI

    app = FastAPI()
    admission.install_admission_handler(app)

    @app.get("/fail")
    async def fail():
        raise admission.OutboxAdmissionError("backlog", pending=2, age_seconds=10, retry_after=17)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/fail")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "17"
