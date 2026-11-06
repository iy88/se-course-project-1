"""Role, budget and security validation for the layered runtime."""

from pathlib import Path

import pytest

from app.core.config import (
    PROD_ENV_FILE,
    ConfigurationError,
    get_settings,
    load_settings,
    set_runtime_role,
)


def _env(tmp_path: Path, *, redis: bool = True, extra: str = "") -> Path:
    lines = [
        "APP_NAME=Realtime Test",
        "ENVIRONMENT=test",
        f"DATABASE_URL=sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}",
        "DATABASE_SCHEMA=app",
        "DB_AUTO_CREATE=true",
        "AUDIT_TRUSTED_PROXIES=none",
        f"STORAGE_LOCAL_ROOT={tmp_path / 'storage'}",
        "JWT_SECRET=config-test-jwt-secret-0123456789abcdef",
        "JWT_ALGORITHM=HS256",
        "FILE_URL_SECRET=config-test-file-secret-0123456789abcdef",
        "SMTP_HOST=smtp.invalid",
        "SMTP_PORT=465",
        "SMTP_SECURITY=ssl",
        "SMTP_USERNAME=config-test",
        "SMTP_PASSWORD=config-test-password",
        "SMTP_FROM_EMAIL=config@example.com",
        "SMTP_FROM_NAME=Realtime Test",
        "ALLOWED_ORIGINS=http://localhost:5173",
    ]
    if redis:
        lines.extend(["REDIS_URL=redis://127.0.0.1:6379/0", "REDIS_KEY_PREFIX=test:"])
    overrides = {}
    for line in extra.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            overrides[key.strip()] = value.strip()
    lines = [line for line in lines if line.split("=", 1)[0] not in overrides]
    lines.extend(f"{key}={value}" for key, value in overrides.items())
    path = tmp_path / ".env"
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.fixture(autouse=True)
def reset_role():
    set_runtime_role(None)
    yield
    set_runtime_role(None)
    get_settings.cache_clear()


def test_split_role_requires_shared_redis(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_RUNTIME_ROLE", "api")
    with pytest.raises(ConfigurationError, match="shared REDIS_URL"):
        load_settings(_env(tmp_path, redis=False))


def test_split_role_reports_effective_role_and_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_RUNTIME_ROLE", "api")
    with pytest.raises(ConfigurationError, match="SQL connection budget exceeded"):
        load_settings(_env(tmp_path, extra="API_WORKERS=4\nAPI_DB_POOL_SIZE=8\nDB_CONNECTION_BUDGET=10"))
    settings = load_settings(_env(tmp_path))
    assert settings.app_role == "api"


def test_combined_accepts_split_worker_values_but_cli_forces_one_process(tmp_path):
    settings = load_settings(_env(tmp_path, extra="API_WORKERS=2\nWS_WORKERS=2"))
    assert settings.app_role == "combined"
    assert settings.api_workers == 2


def test_reclaim_idle_covers_running_and_prefetched_work(tmp_path):
    with pytest.raises(ConfigurationError, match="TASKIQ_RECLAIM_IDLE_MS"):
        load_settings(_env(tmp_path, extra="ENVIRONMENT=dev\nTASKIQ_RECLAIM_IDLE_MS=60000"))
    settings = load_settings(_env(tmp_path, extra="ENVIRONMENT=dev"))
    assert settings.taskiq_reclaim_idle_ms == 300000


def test_worker_redis_budget_includes_publish_and_task_outcome_connections(tmp_path):
    settings = load_settings(_env(tmp_path))
    baseline = settings._worker_redis_budget()
    changed = settings.model_copy(update={
        "redis_publish_max_connections": settings.redis_publish_max_connections + 1,
        "taskiq_max_async_tasks": settings.taskiq_max_async_tasks + 1,
    })
    assert changed._worker_redis_budget() - baseline == 2 * settings.taskiq_worker_processes


def test_wildcard_origin_is_rejected(tmp_path):
    with pytest.raises(ConfigurationError, match="invalid or missing configuration fields"):
        load_settings(_env(tmp_path, extra="ALLOWED_ORIGINS=*"))


def test_production_requires_explicit_origins_and_query_token_off(tmp_path):
    settings = load_settings(_env(tmp_path))
    prod = settings.model_copy(update={"environment": "prod", "allowed_origins": "", "allow_query_token": True})
    with pytest.raises(ConfigurationError) as exc:
        prod.validate_for_runtime(PROD_ENV_FILE)
    message = str(exc.value)
    assert "ALLOWED_ORIGINS is required in prod" in message
    assert "ALLOW_QUERY_TOKEN must be false in prod" in message


def test_role_apps_expose_only_their_own_surface(tmp_path, monkeypatch):
    from app.runtime import create_app

    path = _env(tmp_path)
    monkeypatch.setenv("APP_ENV_FILE", str(path))
    monkeypatch.setenv("APP_RUNTIME_ROLE", "api")
    get_settings.cache_clear()
    api = create_app()
    api_paths = set(api.openapi()["paths"])
    assert "/api/v1/products" in api_paths
    assert not any(getattr(route, "path", "") == "/ws" for route in api.routes)
    ws = create_app("ws")
    ws_paths = {getattr(route, "path", "") for route in ws.routes}
    assert "/ws" in ws_paths
    assert not (ws.openapi()["paths"].keys() & {"/api/v1/products"})
    combined = create_app("combined")
    combined_paths = {getattr(route, "path", "") for route in combined.routes}
    assert "/ws" in combined_paths
    assert "/api/v1/products" in combined.openapi()["paths"]


def test_release_id_parses_key_not_first_line():
    from app.core.config import parse_release_id

    text = "revision=" + "a" * 40 + "\nbuild_number=7\nrelease_id=" + "a" * 40 + "-7\n"
    assert parse_release_id(text) == "a" * 40 + "-7"
    assert parse_release_id("revision=x\n") == "invalid"
    assert parse_release_id("release_id=../../etc/passwd\n") == "invalid"


def test_frame_budget_must_include_envelope(tmp_path):
    with pytest.raises(ConfigurationError, match="WS_MAX_FRAME_BYTES"):
        load_settings(_env(tmp_path, extra="REALTIME_PAYLOAD_MAX_BYTES=16384\nWS_MAX_FRAME_BYTES=16384"))


def test_redis_url_query_cannot_override_explicit_pool_budget(tmp_path):
    with pytest.raises(ConfigurationError, match="query overrides explicit budget"):
        load_settings(_env(tmp_path, extra="REDIS_URL=redis://127.0.0.1:6379/0?max_connections=99&timeout=1"))


def test_outbox_admission_budget_relation(tmp_path):
    with pytest.raises(ConfigurationError, match="REALTIME_OUTBOX_MAX_PENDING"):
        load_settings(_env(tmp_path, extra="REALTIME_PENDING_DEGRADED_THRESHOLD=100\nREALTIME_OUTBOX_MAX_PENDING=50"))
