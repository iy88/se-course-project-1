"""An application port change cannot bypass the installed source proxy."""

import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "preflight.py"))


def check(monkeypatch, role, **changes):
    from app.core import config

    values = {
        "environment": "prod", "db_auto_create": False, "is_split": role != "combined",
        "kv_backend": "redis", "api_host": "127.0.0.1", "api_port": 8001,
        "ws_host": "127.0.0.1", "ws_port": 8002, "jobs_host": "127.0.0.1",
        "jobs_port": 8003, "db_pool": (8, 0), "redis_control_limit": 16,
        "taskiq_worker_processes": 2, "taskiq_broker_max_connections": 4,
        "taskiq_schedule_max_connections": 2, "outbox_max_attempts": 8,
        "taskiq_retry_max_retries": 3, "release_id": "test",
        "realtime_protocol_version": 2, "validate_for_runtime": lambda: None,
        "split_sql_budget": lambda: 40, "sql_connection_budget": lambda: 8,
    }
    values.update(changes)
    monkeypatch.setattr(config, "load_settings", lambda: SimpleNamespace(**values))
    monkeypatch.setattr(config, "set_runtime_role", lambda _role: None)
    monkeypatch.setattr(config, "get_settings", SimpleNamespace(cache_clear=lambda: None))
    return MODULE["_validate_role"](role)[1]


@pytest.mark.parametrize(("role", "changes"), [
    ("api", {"api_port": 8009}), ("combined", {"api_host": "0.0.0.0"}),
    ("ws", {"ws_port": 8012}), ("ws", {"ws_host": "0.0.0.0"}),
    ("jobs", {"jobs_host": "0.0.0.0"}),
    ("worker", {"taskiq_broker_max_connections": 1}),
    ("scheduler", {"taskiq_broker_max_connections": 0}),
])
def test_route_mismatch_is_rejected(monkeypatch, role, changes):
    assert check(monkeypatch, role, **changes)


def test_internal_jobs_port_can_change_without_changing_proxy(monkeypatch):
    assert check(monkeypatch, "jobs", jobs_port=8013) == []


def test_taskiq_worker_and_scheduler_have_no_http_listener(monkeypatch):
    assert check(monkeypatch, "worker", jobs_port=9999, api_port=9999, ws_port=9999) == []
    assert check(monkeypatch, "scheduler", jobs_port=9999, api_port=9999, ws_port=9999) == []
