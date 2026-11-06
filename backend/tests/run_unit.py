"""Run offline unit tests against a private temporary dotenv, never user resources."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile


def main() -> int:
    backend = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="project1-unit-") as temp:
        root = Path(temp)
        env_file = root / "unit.env"
        fields = {
            "APP_NAME": "Project1 Unit Tests", "ENVIRONMENT": "test",
            "DATABASE_URL": f"sqlite+aiosqlite:///{root / 'unit.db'}",
            "DATABASE_SCHEMA": "app", "DB_AUTO_CREATE": "false",
            "STORAGE_LOCAL_ROOT": str(root / "storage"),
            "AUDIT_TRUSTED_PROXIES": "none", "JWT_ALGORITHM": "HS256",
            "JWT_SECRET": secrets.token_urlsafe(48), "FILE_URL_SECRET": secrets.token_urlsafe(48),
            "SMTP_HOST": "smtp.invalid", "SMTP_PORT": "465", "SMTP_SECURITY": "ssl",
            "SMTP_USERNAME": "unit-tests", "SMTP_PASSWORD": secrets.token_urlsafe(24),
            "SMTP_FROM_EMAIL": "unit@example.invalid", "SMTP_FROM_NAME": "Unit Tests",
        }
        env_file.write_text("".join(f"{key}={value}\n" for key, value in fields.items()))
        env_file.chmod(0o600)
        env = dict(os.environ, APP_ENV_FILE=str(env_file), APP_RUNTIME_ROLE="combined",
                   CI_REALTIME_APPROVED="0")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests",
             "--ignore=tests/acceptance_real", "--ignore=tests/integration_real", *sys.argv[1:]],
            cwd=backend, env=env, check=False,
        )
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
