"""Backend management commands.

Usage (reads backend/.env.dev by default; only the standalone migration command
reads migration credentials)::

    python -m app.manage migrate
    python -m app.manage seed --admin-email <administrator email>
    python -m app.manage demo-seed --env-file .env.dev
    python -m app.manage demo-verify --env-file .env.dev

Persistent initialization uses the seed subcommand; automated identity seeding
belongs to the acceptance suite (``python -m tests.acceptance_real.seed``) and is
no longer provided by the application management command; application modules
must not depend on tests.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import json
import logging
import os
import re
import sys
import traceback
from argparse import Namespace

from app.core.config import (
    BACKEND_ROOT,
    ConfigurationError,
    load_migration_settings,
    load_settings,
    set_runtime_role,
    validate_migration_context,
)

_REVISION = re.compile(r"^[A-Za-z0-9_]+$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.manage", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    migrate = sub.add_parser("migrate", help="apply versioned PostgreSQL migrations")
    migrate.add_argument("--revision", default="head", help="target revision (default: head)")

    sub.add_parser("serve-api", help="run only the HTTP API role")
    sub.add_parser("serve-ws", help="run only the WebSocket gateway role")
    sub.add_parser("taskiq-worker", help="run the native Taskiq worker with dotenv budgets")
    sub.add_parser("taskiq-scheduler", help="run the single native Taskiq scheduler with dotenv schedules")
    probe = sub.add_parser("taskiq-probe", help="enqueue a real task and wait for worker execution")
    probe.add_argument("--timeout", type=float, default=None)
    health = sub.add_parser("health", help="probe role readiness without starting the service")
    health.add_argument("--role", choices=("api", "ws", "worker", "scheduler"), required=True)
    health.add_argument("--no-probe", action="store_true", help="worker: skip the live task-execution probe")
    retry = sub.add_parser("realtime-retry", help="requeue failed/expired realtime outbox events")
    retry.add_argument("--event-id", default=None, help="only requeue this event id")
    retry.add_argument("--max-age-hours", type=int, default=24)
    seed = sub.add_parser("seed", help="persist initial administrator and optional reference categories")
    seed.add_argument("--admin-email", default=None, help="administrator email; prompted if omitted")
    seed.add_argument("--admin-name", default="管理员", help="display name for a new administrator")
    seed.add_argument("--category", action="append", default=[], help="optional initial category; repeatable")
    demo = sub.add_parser("demo-seed", help="persist demonstration accounts and business scenarios in the selected environment")
    demo.add_argument("--env-file", default=None, help="dotenv file (default: APP_ENV_FILE or .env.dev)")
    demo.add_argument("--manifest", default=None, help="private demo manifest path")
    verify = sub.add_parser("demo-verify", help="read-only verification for persistent demo-seed records")
    verify.add_argument("--env-file", default=None, help="dotenv file (default: APP_ENV_FILE or .env.dev)")
    verify.add_argument("--manifest", default=None, help="private demo manifest path")
    verify.add_argument("--skip-api", action="store_true", help="skip read-only API visibility checks")
    verify.add_argument("--json", action="store_true", help="print JSON summary")
    load = sub.add_parser("load-seed", help="bulk persistent dev/test performance fixtures")
    load.add_argument("--env-file", default=".env.dev")
    load.add_argument("--manifest", default=None)
    load.add_argument("--users", type=int, default=100)
    load.add_argument("--products", type=int, default=10000)
    load.add_argument("--upload-workers", type=int, default=16)
    load.add_argument("--verify-only", action="store_true")
    return parser


def run_migrate(revision: str) -> int:
    if not _REVISION.match(revision):
        raise ConfigurationError("invalid migration revision")
    settings = load_settings()
    if settings.database_url.startswith("sqlite+"):
        if revision != "head":
            raise ConfigurationError("SQLite local initialization supports head only; use versioned migrations for PostgreSQL")
        from sqlalchemy.ext.asyncio import create_async_engine

        import app.models  # noqa: F401 - register metadata  # pyright: ignore[reportUnusedImport]
        from app.db.migrations import upgrade_additive_schema, drop_upload_size_constraint
        from app.db.session import Base

        async def migrate_local() -> None:
            settings.prepare_runtime_paths()
            engine = create_async_engine(settings.database_url)
            try:
                async with engine.begin() as connection:
                    await connection.run_sync(Base.metadata.create_all)
                    await connection.run_sync(upgrade_additive_schema)
                    await connection.run_sync(drop_upload_size_constraint)
            finally:
                await engine.dispose()

        asyncio.run(migrate_local())
        print("SQLite schema initialized; existing data preserved.")
        return 0
    migration = load_migration_settings()
    validate_migration_context(migration)
    # Delayed import: normal services/tests never load Alembic or migration configuration.
    from alembic import command
    from alembic.config import Config

    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # Alembic reads INI files with the OS locale encoding (GBK on some Windows
    # machines). Load this repository's UTF-8 file explicitly before attaching
    # its filename; Config.file_config is then cached and will not reread it.
    config_path = BACKEND_ROOT / "alembic.ini"
    config = Config()
    config.file_config.read_string(config_path.read_text(encoding="utf-8"))
    config.file_config.set("DEFAULT", "here", str(BACKEND_ROOT).replace("%", "%%"))
    config.config_file_name = str(config_path)
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(config, revision)
    return 0


def _activate_role(role: str | None) -> None:
    if role is None:
        return
    # Child uvicorn workers re-import app.main; an environment selector is the
    # only value a forked/spawned process reliably inherits. It selects a role,
    # never a business configuration value.
    os.environ["APP_RUNTIME_ROLE"] = role
    set_runtime_role(role)


def run_serve(role: str) -> int:
    _activate_role(role)
    settings = load_settings()
    settings.validate_for_runtime()
    effective = settings.app_role
    import uvicorn

    common = {
        "log_level": "info",
        "timeout_graceful_shutdown": settings.graceful_shutdown_seconds,
    }
    if effective == "api":
        uvicorn.run("app.main:app", host=settings.api_host, port=settings.api_port,
                    workers=settings.api_workers, **common)
    elif effective == "ws":
        uvicorn.run("app.main:app", host=settings.ws_host, port=settings.ws_port,
                    workers=settings.ws_workers, ws="websockets", **common)
    else:
        raise ConfigurationError("Only API and WS roles expose an HTTP listener")
    return 0


def run_taskiq_worker() -> int:
    """Start the official Taskiq worker; all budgets come from the dotenv."""
    _activate_role("worker")
    settings = load_settings()
    settings.validate_for_runtime()
    from taskiq.acks import AcknowledgeType
    from taskiq.cli.worker.args import WorkerArgs
    from taskiq.cli.worker.run import run_worker

    args = WorkerArgs(
        broker="app.jobs.broker:broker",
        modules=list(settings.taskiq_modules),
        app_dir=None,
        workers=settings.taskiq_worker_processes,
        max_async_tasks=settings.taskiq_max_async_tasks,
        max_prefetch=settings.taskiq_max_prefetch,
        ack_type=AcknowledgeType.WHEN_EXECUTED,
        shutdown_timeout=settings.taskiq_shutdown_timeout_seconds,
        wait_tasks_timeout=settings.taskiq_shutdown_timeout_seconds,
        hardkill_count=3,
    )
    return int(run_worker(args) or 0)


def run_taskiq_scheduler() -> int:
    """Start exactly one official Taskiq scheduler in this process."""
    _activate_role("scheduler")
    settings = load_settings()
    settings.validate_for_runtime()
    import signal

    from taskiq.cli.scheduler.args import SchedulerArgs
    from taskiq.cli.scheduler.run import run_scheduler

    args = SchedulerArgs(
        scheduler="app.jobs.broker:scheduler",
        modules=list(settings.taskiq_modules),
        update_interval=settings.taskiq_scheduler_update_interval_seconds,
        loop_interval=settings.taskiq_scheduler_loop_interval_seconds,
        send_timeout=settings.taskiq_scheduler_send_timeout_seconds,
    )

    async def managed() -> None:
        # The official runner owns scheduling; this wrapper only translates
        # SIGTERM/SIGINT into cancellation so its own shutdown hooks run.
        task = asyncio.create_task(run_scheduler(args), name="taskiq-scheduler")
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop.set)
        stopper = asyncio.create_task(stop.wait(), name="taskiq-scheduler-stop")
        try:
            done, _ = await asyncio.wait({task, stopper}, return_when=asyncio.FIRST_COMPLETED)
            if task not in done:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        finally:
            stopper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await stopper

    asyncio.run(managed())
    return 0


def run_taskiq_probe(timeout: float | None) -> int:
    _activate_role("worker")
    settings = load_settings()
    settings.validate_for_runtime()
    from app.jobs.probe import run_probe

    try:
        result = asyncio.run(run_probe(settings, timeout=timeout))
    except Exception as exc:  # noqa: BLE001 - CLI reports a stable category
        print(json.dumps({"status": "failed", "category": type(exc).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def run_realtime_retry(event_id: str | None, max_age_hours: int) -> int:
    _activate_role(None)
    settings = load_settings()
    settings.validate_for_runtime()
    import asyncio
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update
    from sqlmodel import col

    from app.db.session import dispose_engine, get_sessionmaker
    from app.models.realtime import RealtimeEvent

    async def retry() -> int:
        cutoff = datetime.now(UTC) - timedelta(hours=max(1, max_age_hours))
        conditions = [
            col(RealtimeEvent.delivered_at).is_(None),
            (col(RealtimeEvent.lease_expires_at).is_(None) |
             (col(RealtimeEvent.lease_expires_at) < datetime.now(UTC))),
            col(RealtimeEvent.created_at) >= cutoff,
        ]
        if event_id:
            conditions.append(col(RealtimeEvent.event_id) == event_id)
        try:
            async with get_sessionmaker()() as db, db.begin():
                result = await db.execute(
                    update(RealtimeEvent)
                    .where(*conditions)
                    .values(next_retry_at=datetime.now(UTC), lease_owner=None,
                            lease_expires_at=None, dead_at=None, attempts=0, last_error=None)
                )
                count = int(result.rowcount or 0)
        finally:
            await dispose_engine()
        print(f"realtime outbox requeued: {count}")
        return 0

    return asyncio.run(retry())


def run_health(role: str, *, no_probe: bool = False) -> int:
    _activate_role(role)
    settings = load_settings()
    settings.validate_for_runtime()
    import asyncio

    from app.realtime.health import readiness

    async def probe() -> tuple[dict, bool]:
        from app.db.session import dispose_engine

        try:
            task_probe: dict = {}
            if role == "worker" and not no_probe:
                # A heartbeat alone is not consumption evidence: enqueue a real
                # task and wait for a worker process to execute it. This also
                # bootstraps the first success row on a freshly started worker.
                from app.jobs.probe import run_probe

                try:
                    task_probe = await run_probe(settings)
                except Exception as exc:  # noqa: BLE001 - stable category only
                    task_probe = {"status": "failed", "category": type(exc).__name__}
            payload, ok = await readiness(settings)
            if task_probe:
                payload["checks"]["task_probe"] = task_probe
                if task_probe.get("status") != "ok":
                    ok = False
                    payload["status"] = "not_ready"
            return payload, ok
        finally:
            await dispose_engine()

    payload, ok = asyncio.run(probe())
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if ok else 1


def run_seed(admin_email: str | None, admin_name: str, categories: list[str]) -> int:
    from app.initialization import InitialPasswordRequired, initialize

    settings = load_settings()
    email = admin_email or input("Administrator email: ").strip()
    try:
        result = asyncio.run(initialize(settings, admin_email=email, admin_name=admin_name, categories=categories))
    except InitialPasswordRequired:
        if not sys.stdin.isatty():
            raise ConfigurationError("A new administrator needs an interactive terminal for the password; plaintext command-line passwords are not accepted") from None
        password = getpass.getpass("New administrator password: ")
        if password != getpass.getpass("Confirm administrator password: "):
            raise ConfigurationError("The two passwords do not match")
        result = asyncio.run(initialize(settings, admin_email=email, password=password, admin_name=admin_name, categories=categories))
    print(f"Initialization: admin_id={result.admin_id} admin_created={result.admin_created} "
           f"categories_created={result.categories_created} categories_existing={result.categories_existing}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args: Namespace = _parser().parse_args(argv)
    try:
        if args.command == "migrate":
            return run_migrate(args.revision)
        if args.command == "serve-api":
            return run_serve("api")
        if args.command == "serve-ws":
            return run_serve("ws")
        if args.command == "taskiq-worker":
            return run_taskiq_worker()
        if args.command == "taskiq-scheduler":
            return run_taskiq_scheduler()
        if args.command == "taskiq-probe":
            return run_taskiq_probe(args.timeout)
        if args.command == "health":
            return run_health(args.role, no_probe=args.no_probe)
        if args.command == "realtime-retry":
            return run_realtime_retry(args.event_id, args.max_age_hours)
        if args.command == "seed":
            return run_seed(args.admin_email, args.admin_name, args.category)
        if args.command == "load-seed":
            from app.devtools.load_seed import main as run_load_seed

            load_args = ["--env-file", args.env_file, "--users", str(args.users),
                         "--products", str(args.products), "--upload-workers", str(args.upload_workers)]
            if args.manifest is not None:
                load_args.extend(["--manifest", args.manifest])
            if args.verify_only:
                load_args.append("--verify-only")
            return run_load_seed(load_args)
        if args.command == "demo-seed":
            from app.devtools.demo_seed import main as run_demo_seed

            demo_args = []
            if args.env_file is not None:
                demo_args.extend(["--env-file", args.env_file])
            if args.manifest is not None:
                demo_args.extend(["--manifest", args.manifest])
            return run_demo_seed(demo_args)
        if args.command == "demo-verify":
            from app.devtools.demo_verify import main as run_demo_verify

            verify_args = []
            if args.env_file is not None:
                verify_args.extend(["--env-file", args.env_file])
            if args.manifest is not None:
                verify_args.extend(["--manifest", args.manifest])
            if args.skip_api:
                verify_args.append("--skip-api")
            if args.json:
                verify_args.append("--json")
            return run_demo_verify(verify_args)
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - print the full exception so management-command failures are diagnosable
        traceback.print_exc()
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
