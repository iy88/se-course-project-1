"""Invalid WS credentials must not force a database checkout via dependency."""

from app.db import session as db_session


async def test_db_dependency_preserves_lazy_checkout(monkeypatch):
    class Session:
        checkouts = 0
        closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            self.closed = True

        async def connection(self):
            self.checkouts += 1
            return object()

    session = Session()
    monkeypatch.setattr(db_session, "get_sessionmaker", lambda: lambda: session)
    dependency = db_session.get_db()
    try:
        assert await anext(dependency) is session
        # WS rejects Origin/ticket before any SQL. Instrumentation must not
        # allocate a scarce DB connection for these unauthenticated handshakes.
        assert session.checkouts == 0
    finally:
        await dependency.aclose()
    assert session.closed
