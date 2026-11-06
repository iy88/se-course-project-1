"""Strict gate: these tests never run in the offline suite.

The dedicated runner checks prerequisites *before* pytest and exits non-zero
when they are missing. If somebody invokes pytest directly without the gate,
module-level skip keeps the offline suite green while the gate still cannot be
mistaken for a real-resource pass.
"""

from __future__ import annotations

import os

import pytest

if os.environ.get("CI_REALTIME_APPROVED") != "1" or not os.environ.get("INTEGRATION_ENV_FILE"):
    pytest.skip(
        "real PostgreSQL/Redis integration requires tests.integration_real.runner",
        allow_module_level=True,
    )


@pytest.fixture(autouse=True)
async def isolate_event_loop_resources():
    """asyncpg/redis connections are loop-bound; never reuse across test loops."""
    from app.db.session import dispose_engine
    from app.kv.base import reset_kv

    from .support import clean_realtime_tables

    await clean_realtime_tables()
    try:
        yield
    finally:
        await reset_kv()
        await dispose_engine()
