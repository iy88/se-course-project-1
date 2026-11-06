"""Owned Redis must remain alive until namespace cleanup has finished."""
import subprocess

import pytest

from tests.integration_real import runner


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_cleanup_precedes_shutdown_and_shutdown_survives_cleanup_failure(tmp_path, monkeypatch, cleanup_fails):
    work = tmp_path / "owned"
    work.mkdir()
    env_file = work / "runtime.env"
    env_file.write_text("")
    calls = []
    monkeypatch.setenv("CI_REALTIME_APPROVED", "1")
    monkeypatch.setattr(runner, "_start_managed_redis", lambda _: ("redis://owned", None, {}))

    async def setup(*_):
        return {"INTEGRATION_ENV_FILE": str(env_file)}, '"owned"'

    async def cleanup_redis(*_):
        assert "stop" not in calls
        calls.append("keys")
        if cleanup_fails:
            raise ConnectionError("controlled cleanup failure")
        return []

    def stop(*_):
        calls.append("stop")
        return []

    async def cleanup_pg(*_):
        return []

    monkeypatch.setattr(runner, "_setup", setup)
    monkeypatch.setattr(runner, "_cleanup_redis", cleanup_redis)
    monkeypatch.setattr(runner, "_stop_managed_redis", stop)
    monkeypatch.setattr(runner, "_cleanup", cleanup_pg)
    # Fail migration deliberately: finally must have the same correct ordering
    # even when pytest was never started.
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
    result = runner.main(["--pg-url", "postgresql://owned", "--managed-redis"])
    assert calls == ["keys", "stop"]
    assert result == (3 if cleanup_fails else 2)
