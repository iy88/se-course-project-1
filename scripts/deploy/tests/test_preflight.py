"""Preflight path/quoting and fail-closed behaviour tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "preflight.py"
REPO = Path(__file__).resolve().parents[3]


def test_preflight_discovers_repository_backend_module():
    result = subprocess.run(
        [sys.executable, "-c",
         "import importlib.util,sys;"
         f"spec=importlib.util.spec_from_file_location('p','{SCRIPT}');"
         + "m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
         + "print(m.BACKEND_ROOT)"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).resolve() == (REPO / "backend").resolve()


def test_non_production_configuration_fails_closed_without_secret_values():
    env_file = REPO / "var" / "test" / "offline.env"
    if not env_file.is_file():
        # The offline synthetic env is a local test resource, not production.
        return
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--role", "combined", "--json"],
        capture_output=True, text=True, timeout=30, check=False,
        env={"APP_ENV_FILE": str(env_file), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 1
    assert "ENVIRONMENT must be prod" in result.stdout
    assert "DATABASE_URL" not in result.stdout


def test_preflight_split_mode_does_not_validate_combined_port_twice(tmp_path):
    env = tmp_path / "prod.env"
    env.write_text("\n".join([
        "APP_NAME=Preflight Test",
        "ENVIRONMENT=test",
        f"DATABASE_URL=sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}",
        "DATABASE_SCHEMA=app",
        "DB_AUTO_CREATE=true",
        "AUDIT_TRUSTED_PROXIES=none",
        f"STORAGE_LOCAL_ROOT={tmp_path / 'storage'}",
        "JWT_SECRET=preflight-test-jwt-secret-0123456789abcdef",
        "JWT_ALGORITHM=HS256",
        "FILE_URL_SECRET=preflight-test-file-secret-0123456789abcdef",
        "SMTP_HOST=smtp.invalid", "SMTP_PORT=465", "SMTP_SECURITY=ssl",
        "SMTP_USERNAME=x", "SMTP_PASSWORD=xxxxxxxx", "SMTP_FROM_EMAIL=x@example.com",
        "SMTP_FROM_NAME=X", "ALLOWED_ORIGINS=http://localhost:5173",
        "REDIS_URL=redis://127.0.0.1:6379/0", "REDIS_KEY_PREFIX=test:",
        "API_PORT=8001", "WS_PORT=8002", "JOBS_PORT=8003",
    ]) + "\n")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--mode", "split", "--json"],
        capture_output=True, text=True, timeout=30, check=False,
        env={"APP_ENV_FILE": str(env), "PATH": "/usr/bin:/bin"},
    )
    import json

    payload = json.loads(result.stdout)
    assert set(payload["roles"]) == {"api", "ws", "worker", "scheduler"}
    assert "ports collide" not in " ".join(payload["problems"])
