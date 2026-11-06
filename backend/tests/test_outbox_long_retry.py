"""Outbox attempt ceilings stay bounded; Taskiq owns retry delay."""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.realtime import dispatcher


class _Session:
    def __init__(self, updates):
        self.updates = updates

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    def begin(self):
        return self

    async def exec(self, statement):
        self.updates.append(statement.compile().params)


async def test_large_attempt_count_marks_terminal_without_overflow(monkeypatch):
    updates = []
    monkeypatch.setattr(dispatcher, "get_sessionmaker", lambda: lambda: _Session(updates))
    worker = object.__new__(dispatcher.OutboxService)
    worker.worker_id = "retry-probe"
    worker.settings = SimpleNamespace(outbox_max_attempts=8)
    now = datetime.now(UTC)
    retryable = await worker._fail_tx(
        [SimpleNamespace(event_id="retry-event", attempts=1000000)], "connection",
    )
    assert retryable == []
    assert len(updates) == 1
    assert updates[0]["dead_at"] is not None
    assert updates[0]["last_error"] == "connection"
    assert "next_retry_at" not in updates[0]


async def test_below_ceiling_releases_lease_for_taskiq_or_backstop(monkeypatch):
    updates = []
    monkeypatch.setattr(dispatcher, "get_sessionmaker", lambda: lambda: _Session(updates))
    worker = object.__new__(dispatcher.OutboxService)
    worker.worker_id = "retry-probe"
    worker.settings = SimpleNamespace(outbox_max_attempts=8)
    event = SimpleNamespace(event_id="retry-event", attempts=2)
    retryable = await worker._fail_tx([event], "connection")
    assert retryable == [event]
    assert updates[0]["dead_at"] is None
    assert updates[0]["lease_owner"] is None
    assert "next_retry_at" not in updates[0]
