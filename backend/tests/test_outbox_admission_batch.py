"""A known event batch must fit the soft budget even with caching disabled."""

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import RealtimeEvent
from app.realtime import admission
from app.realtime.events import emit_events
from tests.test_outbox_admission import _engine, _pending


async def test_uncached_admission_accounts_for_incoming_event_batch(tmp_path, monkeypatch):
    settings = get_settings().model_copy(update={
        "realtime_outbox_max_pending": 2,
        "realtime_outbox_max_age_seconds": 3600,
        "realtime_outbox_admission_cache_seconds": 0,
    })
    monkeypatch.setattr(admission, "get_settings", lambda: settings)
    admission.clear_admission_cache()
    engine, maker = await _engine(tmp_path, "batch-budget.db")
    try:
        async with maker() as db, db.begin():
            await _pending(db, 1, 1)
        async with maker() as db:
            await emit_events(db, [2, 3], event_type="probe", payload={"value": "new-batch"})
            with pytest.raises(admission.OutboxAdmissionError):
                await db.commit()
            await db.rollback()
        async with maker() as db:
            count = await db.scalar(select(func.count()).select_from(RealtimeEvent))
            assert count == 1
    finally:
        await engine.dispose()
        admission.clear_admission_cache()
