"""Monitor safety: read-only connection defaults and exclusive private output."""
import json
import os
import stat
from types import SimpleNamespace

import pytest

from app.devtools import load_monitor


class Context:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def begin(self):
        return Context()


@pytest.mark.asyncio
async def test_monitor_uses_read_only_defaults_and_never_overwrites(tmp_path, monkeypatch):
    options = {}
    class Engine:
        disposed = 0
        def connect(self):
            return Context()
        async def dispose(self):
            self.disposed += 1
    engine = Engine()
    def factory(_url, **kwargs):
        options.update(kwargs)
        return engine
    async def collect(_connection):
        return {'timestamp_utc': '2026-11-06T00:00:00+00:00', 'session_states': {'active': 2}}
    monkeypatch.setattr(load_monitor, 'create_async_engine', factory)
    monkeypatch.setattr(load_monitor, 'collect', collect)
    settings = SimpleNamespace(database_url='postgresql+asyncpg://unused', database_schema='app')
    output = tmp_path / 'monitor.jsonl'
    await load_monitor.monitor(settings, output, duration=0.02, interval=0.2)
    assert options['connect_args']['server_settings']['default_transaction_read_only'] == 'on'
    assert options['pool_size'] == 1 and options['max_overflow'] == 0
    contents = output.read_text()
    assert json.loads(contents)['session_states'] == {'active': 2}
    if os.name != 'nt':
        assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        await load_monitor.monitor(settings, output, duration=0.02, interval=0.2)
    assert output.read_text() == contents
    assert engine.disposed == 2


def test_monitor_rejects_production_before_opening_output(tmp_path):
    output = tmp_path / 'never-created.jsonl'
    assert load_monitor.main(['--env-file', str(tmp_path / '.env.prod'), '--output', str(output)]) == 1
    assert not output.exists()
