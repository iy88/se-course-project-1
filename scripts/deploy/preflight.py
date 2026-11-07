#!/usr/bin/env python3
"""Production release preflight.

Validates the selected dotenv for every runtime role, pool/connection budgets,
security flags and (optionally) real DB/Redis connectivity. Outputs only field
names and status categories, never secret values.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
BACKEND_ROOT = next(
    (candidate for candidate in (
        _HERE.parent.parent / "backend",
        _HERE.parent.parent.parent / "backend",
        Path.cwd() / "backend",
        Path.cwd(),
    ) if (candidate / "app" / "core" / "config.py").is_file()),
    _HERE.parent.parent / "backend",
)
sys.path.insert(0, str(BACKEND_ROOT))

ROLES = ("api", "ws", "worker", "scheduler")


def _validate_role(role: str) -> tuple[dict, list[str]]:
    from app.core.config import (
        ConfigurationError,
        get_settings,
        load_settings,
        set_runtime_role,
    )

    os.environ["APP_RUNTIME_ROLE"] = role
    set_runtime_role(role)
    try:
        settings = load_settings()
        settings.validate_for_runtime()
    except ConfigurationError as exc:
        return {"role": role, "ok": False}, [str(exc)]
    finally:
        get_settings.cache_clear()
    problems: list[str] = []
    if settings.environment != "prod":
        problems.append("ENVIRONMENT must be prod")
    if settings.db_auto_create:
        problems.append("DB_AUTO_CREATE must be false")
    if settings.kv_backend != "redis":
        problems.append("split role requires shared Redis")
    # The administrator-installed source proxy uses these fixed upstreams.
    # Application listeners remain configurable for other deployments, but a
    # release here must not silently diverge from the reviewed production route.
    if role == "api" and (settings.api_host, settings.api_port) != ("127.0.0.1", 8001):
        problems.append("API listener must match the installed upstream 127.0.0.1:8001")
    if role == "ws" and (settings.ws_host, settings.ws_port) != ("127.0.0.1", 8002):
        problems.append("WS listener must match the installed upstream 127.0.0.1:8002")
    if role in {"worker", "scheduler"}:
        # Native Taskiq roles have no public HTTP listener. Their parameters are
        # built from the same dotenv, never duplicated in systemd.
        if settings.taskiq_worker_processes < 1:
            problems.append("worker process budget must be positive")
        if settings.taskiq_broker_max_connections < 2:
            problems.append("Taskiq broker connections must be >= 2")
        if role == "worker" and settings.outbox_max_attempts < settings.taskiq_retry_max_retries + 1:
            problems.append("outbox attempt ceiling must cover Taskiq retries")
    return {
        "role": role,
        "ok": not problems,
        "db_pool_per_worker": settings.db_pool,
        "redis_control_connections": settings.redis_control_limit,
        "release_id": settings.release_id,
        "protocol_version": settings.realtime_protocol_version,
        "db_budget": settings.split_sql_budget(),
        "ports": ([settings.api_port] if role == "api" else
                  ([settings.ws_port] if role == "ws" else [])),
        "taskiq_worker_processes": settings.taskiq_worker_processes,
        "taskiq_broker_connections_per_process": settings.taskiq_broker_max_connections,
        "taskiq_retry_connections_per_process": settings.taskiq_schedule_max_connections,
        "sql_budget": settings.sql_connection_budget(),
    }, problems


async def _connectivity(role: str) -> list[str]:
    from app.core.config import get_settings, set_runtime_role
    from app.db.session import dispose_engine, get_engine
    from sqlalchemy import text

    os.environ["APP_RUNTIME_ROLE"] = role
    set_runtime_role(role)
    get_settings.cache_clear()
    settings = get_settings()
    problems: list[str] = []
    if role != "scheduler":
        # The scheduler owns no SQL pool; do not invent a database probe.
        try:
            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            problems.append(f"database connectivity failed ({type(exc).__name__})")
        finally:
            await dispose_engine()
    if settings.redis_url.strip():
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, max_connections=1,
                                  socket_connect_timeout=2, socket_timeout=2)
        try:
            await client.ping()
        except Exception as exc:  # noqa: BLE001
            problems.append(f"redis connectivity failed ({type(exc).__name__})")
        finally:
            await client.aclose()
        if role in {"worker", "scheduler"}:
            try:
                await _taskiq_capability(settings)
            except Exception as exc:  # noqa: BLE001 - never expose credentials
                problems.append(f"Taskiq Redis group/ACK capability failed ({type(exc).__name__})")
    return problems


async def _taskiq_capability(settings) -> None:
    """Exercise the actual official broker startup, without consuming a task.

    This may initialize the configured stream/group at 0-0. The ACK probe uses
    impossible entry 0-0 and does not alter payloads or execute background jobs.
    Producers do not publish worker SQL heartbeats.
    """
    from app.jobs.broker import build_bundle

    bundle = build_bundle(settings)
    try:
        await bundle.broker.startup()
    finally:
        await bundle.broker.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("split",), default="split")
    parser.add_argument("--role", choices=(*ROLES, "all"), default=None,
                        help="optional single-role probe (all means split roles)")
    parser.add_argument("--connect", action="store_true", help="probe real PostgreSQL and Redis")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    roles = ROLES if args.role in (None, "all") else (args.role,)
    report: dict = {"ok": True, "mode": args.mode, "roles": {}}
    problems: list[str] = []
    for role in roles:
        entry, role_problems = _validate_role(role)
        report["roles"][role] = entry
        problems.extend(f"{role}: {problem}" for problem in role_problems)
    if args.connect:
        for role in roles:
            role_problems = asyncio.run(_connectivity(role))
            problems.extend(f"{role}: {problem}" for problem in role_problems)
    # Ports must not collide across split roles.
    ports = [port for entry in report["roles"].values() for port in entry.get("ports", [])]
    if len(set(ports)) != len(ports):
        problems.append("split role ports collide")
    report["problems"] = problems
    report["ok"] = not problems
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        for role, entry in report["roles"].items():
            print(f"{role}: {'ok' if entry.get('ok') else 'failed'}")
        for problem in problems:
            print(f"FAILED: {problem}", file=sys.stderr)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
