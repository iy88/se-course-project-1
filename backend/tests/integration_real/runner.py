"""CI/local runner for real PostgreSQL + Redis realtime integration tests.

Required environment (missing values fail the gate; nothing is silently
skipped):
  CI_REALTIME_PG_ADMIN_URL   superuser/admin SQLAlchemy URL to the CI instance
  CI_REALTIME_REDIS_URL      dedicated CI Redis URL
  CI_REALTIME_APPROVED=1     explicit acknowledgement that resources are CI-only

The runner creates its own random schema, owner/migrator/app roles and Redis
prefix, runs the real Alembic migration, then executes
``tests/integration_real`` with APP_ENV_FILE pointed at the private temp dotenv.
Cleanup drops only its own schema/roles and deletes only keys under its own
prefix (never FLUSHDB/FLUSHALL).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


def _fail(message: str) -> int:
    print(f"realtime integration refused: {message}", file=sys.stderr)
    return 2


def _plain_pg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _url_with_role(url: str, role: str, password: str) -> str:
    parsed = urlsplit(_plain_pg_url(url))
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    database = parsed.path.lstrip("/") or "postgres"
    return f"postgresql+asyncpg://{role}:{password}@{host}:{port}/{database}"


def _database_name(url: str) -> str:
    return urlsplit(_plain_pg_url(url)).path.lstrip("/") or "postgres"


def _free_ports(count: int) -> list[int]:
    sockets = []
    try:
        for _ in range(count):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
        return [int(sock.getsockname()[1]) for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def _start_managed_redis(suffix: str) -> tuple[str, Path, dict]:
    binary = shutil.which("redis-server")
    if binary is None:
        raise RuntimeError("CI_REALTIME_REDIS_MANAGED=1 requires redis-server on PATH")
    work = REPO_ROOT / "var" / "integration-real" / suffix
    redis_dir = work / "redis"
    redis_dir.mkdir(parents=True, exist_ok=True)
    port = _free_ports(1)[0]
    args = [binary, "--port", str(port), "--bind", "127.0.0.1", "--dir", str(redis_dir),
            "--save", "", "--appendonly", "no", "--maxmemory-policy", "noeviction",
            "--pidfile", str(redis_dir / "redis.pid"), "--logfile", str(redis_dir / "redis.log")]
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    control = work / "redis-control.json"
    control.write_text(json.dumps({"binary": binary, "port": port, "dir": str(redis_dir),
                                   "pid": process.pid, "args": args}), encoding="utf-8")
    control.chmod(0o600)
    import redis as sync_redis

    deadline = time.monotonic() + 20
    client = sync_redis.Redis(host="127.0.0.1", port=port, socket_connect_timeout=1)
    try:
        while time.monotonic() < deadline:
            try:
                if client.ping():
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.1)
        else:
            raise RuntimeError("managed Redis did not start")
    finally:
        client.close()
    return f"redis://127.0.0.1:{port}/0", control, {"pid": process.pid, "process": process}


def _stop_managed_redis(control: Path | None, state: dict | None) -> list[str]:
    errors: list[str] = []
    pids: set[int] = set()
    if control is not None and control.is_file():
        try:
            pids.add(int(json.loads(control.read_text(encoding="utf-8"))["pid"]))
        except (ValueError, KeyError, OSError):
            pass
    if state and state.get("pid"):
        pids.add(int(state["pid"]))
    for pid in pids:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except OSError as exc:
            errors.append(f"redis stop {type(exc).__name__}")
    return errors


def _write_env(path: Path, *, schema: str, app_url: str, migrator_url: str, owner: str,
               app_role: str, redis_url: str, prefix: str, storage: Path,
               api_port: int, ws_port: int, ws2_port: int) -> None:
    values = {
        "APP_NAME": "Project1 Realtime Integration",
        "ENVIRONMENT": "test",
        "API_HOST": "127.0.0.1",
        "API_PORT": str(api_port),
        "WS_HOST": "127.0.0.1",
        "WS_PORT": str(ws_port),
        "DATABASE_URL": app_url,
        "MIGRATION_DATABASE_URL": migrator_url,
        "MIGRATION_OWNER_ROLE": owner,
        "MIGRATION_APP_ROLE": app_role,
        "DATABASE_SCHEMA": schema,
        "DB_AUTO_CREATE": "false",
        "AUDIT_TRUSTED_PROXIES": "none",
        "REDIS_URL": redis_url,
        "REDIS_KEY_PREFIX": prefix,
        "STORAGE_LOCAL_ROOT": str(storage),
        "JWT_SECRET": secrets.token_urlsafe(48),
        "JWT_ALGORITHM": "HS256",
        "FILE_URL_SECRET": secrets.token_urlsafe(48),
        "SMTP_HOST": "smtp.invalid",
        "SMTP_PORT": "465",
        "SMTP_SECURITY": "ssl",
        "SMTP_USERNAME": "ci-integration",
        "SMTP_PASSWORD": secrets.token_urlsafe(24),
        "SMTP_FROM_EMAIL": "ci-integration@example.invalid",
        "SMTP_FROM_NAME": "CI Integration",
        "ALLOWED_ORIGINS": f"http://127.0.0.1:{api_port},http://127.0.0.1:{ws_port},http://127.0.0.1:{ws2_port}",
        "ALLOW_MISSING_ORIGIN": "true",
        "ALLOW_QUERY_TOKEN": "false",
        "WS_RECONCILE_SECONDS": "1",
        "OUTBOX_POLL_INTERVAL_MS": "20",
        "REDIS_STREAM_BLOCK_MS": "500",
        "REDIS_STREAM_SOCKET_TIMEOUT_SECONDS": "2",
        "DB_CONNECTION_BUDGET": "40",
        "REDIS_CONNECTION_BUDGET": "128",
        "TASKIQ_WORKER_PROCESSES": "1",
        "TASKIQ_MAX_ASYNC_TASKS": "8",
        "TASKIQ_MAX_PREFETCH": "4",
        "TASKIQ_OUTBOX_INTERVAL_SECONDS": "1",
        "TASKIQ_SCHEDULER_UPDATE_INTERVAL_SECONDS": "1",
        "TASKIQ_SCHEDULER_HEARTBEAT_TTL_SECONDS": "15",
        "TASKIQ_RETRY_MAX_RETRIES": "2",
        "TASKIQ_RETRY_DELAY_SECONDS": "1",
        "TASKIQ_RETRY_MAX_DELAY_SECONDS": "5",
        "TASKIQ_RECLAIM_IDLE_MS": "2000",
        "TASKIQ_UNACKNOWLEDGED_LOCK_TIMEOUT_SECONDS": "5",
        "TASKIQ_XREAD_BLOCK_MS": "500",
        "TASKIQ_PROBE_TIMEOUT_SECONDS": "3",
        "TASKIQ_EXTRA_TASK_MODULES": "tests.integration_real.probe_tasks",
        "OUTBOX_MAX_ATTEMPTS": "4",
        "OUTBOX_LEASE_SECONDS": "5",
    }
    path.write_text("\n".join(f"{key}={value}" for key, value in values.items()) + "\n", encoding="utf-8")
    path.chmod(0o600)


async def _setup(args, suffix: str) -> tuple[dict[str, str], str]:
    import asyncpg

    admin_url = _plain_pg_url(args.pg_url)
    parsed = urlsplit(admin_url)
    owner = f"ci_rt_owner_{suffix}"
    migrator = f"ci_rt_migrator_{suffix}"
    app_role = f"ci_rt_app_{suffix}"
    schema = f"ci_rt_{suffix}"
    migrator_password = secrets.token_urlsafe(24)
    app_password = secrets.token_urlsafe(24)
    conn = await asyncpg.connect(
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 5432,
        user=parsed.username or "postgres",
        password=parsed.password,
        database=_database_name(args.pg_url),
    )
    try:
        await conn.execute(f'CREATE ROLE "{owner}" NOLOGIN')
        await conn.execute(
            f'CREATE ROLE "{migrator}" LOGIN PASSWORD \'{migrator_password}\' NOSUPERUSER NOCREATEDB NOCREATEROLE'
        )
        await conn.execute(
            f'CREATE ROLE "{app_role}" LOGIN PASSWORD \'{app_password}\' NOSUPERUSER NOCREATEDB NOCREATEROLE'
        )
        await conn.execute(f'GRANT "{owner}" TO "{migrator}"')
        database = _database_name(args.pg_url)
        await conn.execute(f'GRANT CONNECT ON DATABASE "{database}" TO "{migrator}", "{app_role}"')
        await conn.execute(f'CREATE SCHEMA "{schema}" AUTHORIZATION "{owner}"')
        await conn.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{app_role}"')
        await conn.execute(
            f'ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA "{schema}" '
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_role}"'
        )
        await conn.execute(
            f'ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA "{schema}" '
            f'GRANT USAGE, SELECT ON SEQUENCES TO "{app_role}"'
        )
    finally:
        await conn.close()

    base = urlsplit(_plain_pg_url(args.pg_url))
    host = base.hostname or "127.0.0.1"
    port = base.port or 5432
    database = _database_name(args.pg_url)
    app_url = _url_with_role(args.pg_url, app_role, app_password).replace(
        f"{host}:{port}", f"{host}:{port}", 1
    )
    migrator_url = _url_with_role(args.pg_url, migrator, migrator_password)
    work = REPO_ROOT / "var" / "integration-real" / suffix
    work.mkdir(parents=True, exist_ok=True)
    storage = work / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    env_path = work / ".env"
    api_port, ws_port, ws2_port = _free_ports(3)
    _write_env(env_path, schema=schema, app_url=app_url, migrator_url=migrator_url,
               owner=owner, app_role=app_role, redis_url=args.redis_url,
               prefix=f"ci-rt:{suffix}:", storage=storage,
               api_port=api_port, ws_port=ws_port, ws2_port=ws2_port)
    env = dict(os.environ)
    env["APP_ENV_FILE"] = str(env_path)
    env["APP_RUNTIME_ROLE"] = "api"
    env["INTEGRATION_ENV_FILE"] = str(env_path)
    env["INTEGRATION_SCHEMA"] = schema
    env["INTEGRATION_APP_ROLE"] = app_role
    env["INTEGRATION_REDIS_PREFIX"] = f"ci-rt:{suffix}:"
    env["CI_REALTIME_APPROVED"] = "1"
    env["CI_REALTIME_REDIS_URL"] = args.redis_url
    env["INTEGRATION_API_PORT"] = str(api_port)
    env["INTEGRATION_WS_PORT"] = str(ws_port)
    env["INTEGRATION_WS2_PORT"] = str(ws2_port)
    return env, f'"{schema}"'


async def _cleanup(args, schema: str, roles: list[str]) -> list[str]:
    import asyncpg

    errors: list[str] = []
    parsed = urlsplit(_plain_pg_url(args.pg_url))
    try:
        conn = await asyncpg.connect(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 5432,
            user=parsed.username or "postgres",
            password=parsed.password,
            database=_database_name(args.pg_url),
        )
    except Exception as exc:  # noqa: BLE001 - report ownership cleanup failure
        return [f"postgres connect: {type(exc).__name__}"]
    try:
        try:
            await conn.execute(f'DROP SCHEMA IF EXISTS {schema} CASCADE')
        except Exception as exc:  # noqa: BLE001
            errors.append(f"schema: {type(exc).__name__}")
        for role in roles:
            try:
                await conn.execute(f'DROP OWNED BY "{role}"')
            except Exception as exc:  # noqa: BLE001 - role may not exist
                errors.append(f"owned {role}: {type(exc).__name__}")
            try:
                await conn.execute(f'DROP ROLE IF EXISTS "{role}"')
            except Exception as exc:  # noqa: BLE001
                errors.append(f"role {role}: {type(exc).__name__}")
    finally:
        await conn.close()
    return errors


async def _cleanup_redis(url: str, prefix: str) -> list[str]:
    import redis.asyncio as aioredis

    errors: list[str] = []
    client = aioredis.from_url(url, decode_responses=True)
    try:
        batch: list[str] = []
        # taskiq-redis derives claim locks outside the leading app prefix.
        # Both components still carry this runner's random namespace.
        for pattern in (prefix + "*", "autoclaim:" + prefix + "*:" + prefix + "*"):
            async for key in client.scan_iter(match=pattern, count=500):
                batch.append(key)
                if len(batch) >= 200:
                    await client.delete(*batch)
                    batch.clear()
        if batch:
            await client.delete(*batch)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"redis: {type(exc).__name__}")
    finally:
        try:
            await client.aclose()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"redis close: {type(exc).__name__}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-url", default=os.environ.get("CI_REALTIME_PG_ADMIN_URL", ""))
    parser.add_argument("--redis-url", default=os.environ.get("CI_REALTIME_REDIS_URL", ""))
    parser.add_argument("--keep", action="store_true", help="keep the private temp dotenv for debugging")
    parser.add_argument("--managed-redis", action="store_true",
                        default=os.environ.get("CI_REALTIME_REDIS_MANAGED") == "1",
                        help="start a dedicated redis-server and enable restart tests")
    parser.add_argument("--pytest-args", nargs="*", default=[])
    args = parser.parse_args(argv)
    if not args.pg_url:
        return _fail("CI_REALTIME_PG_ADMIN_URL is required")
    if not args.managed_redis and not args.redis_url:
        return _fail("CI_REALTIME_REDIS_URL or CI_REALTIME_REDIS_MANAGED=1 is required")
    if os.environ.get("CI_REALTIME_APPROVED") != "1":
        return _fail("CI_REALTIME_APPROVED=1 is required")
    suffix = secrets.token_hex(4)
    roles = [f"ci_rt_owner_{suffix}", f"ci_rt_migrator_{suffix}", f"ci_rt_app_{suffix}"]
    schema_ident = f'"ci_rt_{suffix}"'
    env: dict[str, str] | None = None
    env_path: Path | None = None
    result_code = 2
    cleanup_failed = False
    setup_error: Exception | None = None
    redis_control: Path | None = None
    redis_state: dict | None = None
    try:
        try:
            if args.managed_redis:
                args.redis_url, redis_control, redis_state = _start_managed_redis(suffix)
            env, schema_ident = asyncio.run(_setup(args, suffix))
            env_path = Path(env["INTEGRATION_ENV_FILE"])
        except Exception as exc:  # noqa: BLE001 - never print credentials
            setup_error = exc
        if env is not None and env_path is not None:
            migrate = subprocess.run(
                [sys.executable, "-m", "app.manage", "migrate"],
                cwd=BACKEND_ROOT, env=env, capture_output=True, text=True, check=False,
            )
            if migrate.returncode != 0:
                print(migrate.stdout[-2000:], file=sys.stderr)
                print(migrate.stderr[-2000:], file=sys.stderr)
                print("realtime integration: Alembic migration failed", file=sys.stderr)
                result_code = 2
            else:
                targets = args.pytest_args or ["tests/integration_real"]
                pytest_args = [sys.executable, "-m", "pytest", "-q", *targets]
                result = subprocess.run(pytest_args, cwd=BACKEND_ROOT, env=env, check=False)
                result_code = int(result.returncode)
    finally:
        # Cleanup is part of the gate: a leaked schema/role/prefix fails even
        # when pytest itself passed. --keep only preserves the private dotenv.
        cleanup_errors: list[str] = []
        if setup_error is not None:
            print(f"realtime integration refused: resource setup failed: {type(setup_error).__name__}", file=sys.stderr)
        try:
            cleanup_errors.extend(asyncio.run(_cleanup_redis(args.redis_url, f"ci-rt:{suffix}:")))
        except Exception as exc:  # noqa: BLE001
            cleanup_errors.append(f"redis runner: {type(exc).__name__}")
        finally:
            # Key cleanup needs the server alive. Always stop the owned server,
            # including when key cleanup failed, and retain both error results.
            cleanup_errors.extend(_stop_managed_redis(redis_control, redis_state))
        try:
            cleanup_errors.extend(asyncio.run(_cleanup(args, schema_ident, roles)))
        except Exception as exc:  # noqa: BLE001
            cleanup_errors.append(f"postgres runner: {type(exc).__name__}")
        if env_path is not None and not args.keep:
            shutil.rmtree(env_path.parent, ignore_errors=True)
        elif env_path is not None:
            print(f"kept private integration workspace: {env_path.parent}", file=sys.stderr)
        if cleanup_errors:
            print("realtime integration cleanup failed: " + "; ".join(cleanup_errors), file=sys.stderr)
            cleanup_failed = True
    return 3 if cleanup_failed else result_code


if __name__ == "__main__":
    raise SystemExit(main())
