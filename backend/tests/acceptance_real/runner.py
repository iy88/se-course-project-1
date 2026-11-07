"""Real-business acceptance runner (explicit opt-in).

Writes no test report on success; on failure writes only
``var/acceptance-real/acceptance-failure-<run_id>.log`` with failed checks, cleanup, and
debug information.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from app.core.private_files import protect_private

from tests.acceptance_real.core import (
    BACKEND_ROOT,
    FAIL,
    PASS,
    REPO_ROOT,
    CheckFailure,
    CheckRecord,
    RouteIndex,
)

if TYPE_CHECKING:
    from tests.acceptance_real.acceptance import AcceptanceRun, ServerHandle

ACCEPTANCE_ROOT = REPO_ROOT / "var" / "acceptance-real"

DEFAULT_PORT = 8101


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + os.urandom(3).hex()


def _git_head() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except OSError:
        return "unknown"


def _git_dirty() -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return bool(result.stdout.strip()) if result.returncode == 0 else True
    except OSError:
        return True


def _source_digest() -> dict[str, Any]:
    files: list[Path] = []
    for base in (BACKEND_ROOT / "app", BACKEND_ROOT / "alembic", BACKEND_ROOT / "tests" / "acceptance_real"):
        if base.is_dir():
            files.extend(path for path in base.rglob("*") if path.is_file() and path.suffix in {".py", ".ini", ".toml"})
    hasher = hashlib.sha256()
    for path in sorted(files):
        hasher.update(str(path.relative_to(REPO_ROOT)).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return {
        "git_head": _git_head(),
        "working_tree_dirty": _git_dirty(),
        "source_digest_sha256": hasher.hexdigest(),
        "source_file_count": len(files),
        "digest_scope": [
            "backend/app/**/*.py",
            "backend/alembic/**/*.py/*.ini",
            "backend/tests/acceptance_real/**/*.py",
        ],
    }


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def start_server(*, port: int, run_id: str, sandbox: Any) -> ServerHandle:
    from tests.acceptance_real.acceptance import ServerHandle

    if not _port_is_free(port):
        raise CheckFailure(f"Port {port} is already in use; refusing to kill an existing service; change --port or use --no-start-server")
    clock_file = sandbox.root / f"clock-{run_id}.txt"
    clock_file.parent.mkdir(parents=True, exist_ok=True)
    clock_file.write_text("0\n", encoding="ascii")
    protect_private(clock_file)
    log_path = sandbox.root / f"server-{run_id}.log"
    log_handle = log_path.open("wb")
    env = sandbox.server_env()
    env["PYTHONUNBUFFERED"] = "1"
    from tests.integration_real.runner import _free_ports

    ws_port = _free_ports(1)[0]
    command = [
        sys.executable,
        "-m",
        "tests.acceptance_real.clock_server",
        "--port",
        str(port),
        "--ws-port",
        str(ws_port),
        "--clock-file",
        str(clock_file),
    ]
    process = subprocess.Popen(
        command,
        cwd=BACKEND_ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=sys.platform != "win32",
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    sandbox.process = process
    sandbox.clock_file = clock_file
    sandbox._write_manifest("server_started")
    log_handle.close()
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 45
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise CheckFailure(f"Test service failed to start (exit={process.returncode}); only the exit code is retained")
        try:
            response = httpx.get(base_url + "/api/health", timeout=3, trust_env=False)
            ws_url = f"http://127.0.0.1:{ws_port}"
            if response.status_code == 200 and httpx.get(ws_url + "/health/ready", timeout=3, trust_env=False).is_success:
                return ServerHandle(process=process, base_url=base_url, clock_file=clock_file,
                                    log_path=log_path, ws_url=ws_url)
            last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = type(exc).__name__
        time.sleep(0.5)
    from tests.acceptance_real.processes import stop_server
    stop_server(process, clock_file)
    raise CheckFailure(f"Test service did not become healthy within 45s (last error: {last_error})")


def _checks_passed(checks: Sequence[CheckRecord]) -> bool:
    return bool(checks) and all(check.status == PASS for check in checks)


def _call_index(calls: Sequence[Any]) -> dict[int, dict[str, Any]]:
    return {int(call.seq): call.as_dict() for call in calls}


def _json_excerpt(value: Any, limit: int = 4000) -> str:
    rendered = json.dumps(value, ensure_ascii=False, default=str)
    return rendered if len(rendered) <= limit else rendered[:limit] + "… (truncated)"


def _append_excerpts(lines: list[str], rows: Sequence[Mapping[str, Any]]) -> None:
    for row in rows[:50]:
        lines.append("- " + _json_excerpt(row, 600))
    if len(rows) > 50:
        lines.append(f"- … {len(rows) - 50} more rows omitted")


def _append_check_debug(
    lines: list[str],
    check: Mapping[str, Any],
    call_index: Mapping[int, Mapping[str, Any]],
) -> None:
    lines += ["", f"### [{check.get('status')}] `{check.get('check_id')}` {check.get('title')}", ""]
    meta = [f"{key}={check.get(key)}" for key in ("duration_ms", "role") if check.get(key) is not None]
    if meta:
        lines.append("- " + "; ".join(meta))
    for key, label in (("precondition", "Precondition"), ("action", "Action"), ("expected", "Expected"), ("note", "Note")):
        value = check.get(key)
        if value:
            lines.append(f"- {label}: {value}")
    if check.get("error"):
        lines.append(f"- Error: {check['error']}")
    assertions = check.get("assertions") or []
    if assertions:
        lines.append(f"- Assertions: {len(assertions)} passed (passing content is not written to the log)")
    calls: list[Mapping[str, Any]] = []
    for seq in check.get("call_seq") or []:
        call = call_index.get(int(seq))
        if call is not None:
            calls.append(call)
    if calls:
        lines.append("- Actual calls:")
        for call in calls[:40]:
            lines.append(
                f"  - #{call.get('seq')} {call.get('method')} {call.get('actual_path')} -> {call.get('status')} "
                + f" (expected {call.get('expected')}, {call.get('duration_ms')}ms, {call.get('role')})"
            )
        if len(calls) > 40:
            lines.append(f"  - … {len(calls) - 40} more calls omitted")
    data = check.get("data") or {}
    if data:
        lines += ["- Actual data:", "```json", _json_excerpt(data), "```"]


def _failure_log(
    *,
    run_id: str,
    exit_code: int,
    report: Mapping[str, Any] | None,
    context: Mapping[str, Any] | None,
    partial_checks: Sequence[Mapping[str, Any]],
    call_index: Mapping[int, Mapping[str, Any]],
    fatal: str | None,
    cleanup: Mapping[str, Any] | None,
) -> str:
    lines = [f"# Acceptance failure log {run_id}", ""]
    if report is not None:
        environment = report.get("environment") or {}
        source = report.get("runtime_source") or {}
        digest = str(source.get("source_digest_sha256") or "")
        lines += [
            f"- Time: {report.get('started_at')} — {report.get('finished_at')}",
            f"- Target: `{environment.get('base_url')}` ({environment.get('database')} / {environment.get('storage_backend')}; standalone service; port {environment.get('port')})",
            f"- Source: HEAD `{source.get('git_head')}`, working tree dirty={source.get('working_tree_dirty')}, digest `{digest[:16]}…`",
        ]
    elif context:
        lines += [
            f"- Time: {context.get('started_at')} (interrupted; did not finish normally)",
            f"- Target: `{context.get('base_url') or 'not started'}` ({context.get('database')} / {context.get('storage_backend')}; standalone service; port {context.get('port')})",
        ]
    lines.append(f"- Exit code: {exit_code}")
    if report is not None:
        lines.append(f"- Summary: {report.get('summary')}")
    if fatal:
        lines += ["", "## Fatal error", "", f"- {fatal}"]
    checks = list(report.get("checks") or []) if report is not None else list(partial_checks)
    failed = [check for check in checks if check.get("status") != PASS]
    lines += ["", f"## Failed checks ({len(failed)})"]
    if not failed:
        lines.append("- No failed checks; the failure came from the run or cleanup process.")
    for check in failed:
        _append_check_debug(lines, check, call_index)
    if report is not None:
        notes = report.get("notes") or []
        if notes:
            lines += ["", "## Notes", ""]
            _append_excerpts(lines, [{"note": note} for note in notes])
    if cleanup is not None:
        lines += ["", "## Cleanup result", "", f"- {json.dumps(cleanup, ensure_ascii=False)}"]
    return "\n".join(lines) + "\n"



def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Real-business acceptance")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--inject-failure", choices=["after-files"], help=argparse.SUPPRESS)
    parser.add_argument("--only", nargs="*", default=None, help="Run only the specified groups (debugging)")
    return parser


def _run(argv: list[str] | None, sandbox: Any, config: Any) -> int:
    from tests.acceptance_real.acceptance import AcceptanceRun
    from tests.acceptance_real.seed import (
        identities_for_run,
        load_credentials,
        seed_identities,
    )

    args = _parser().parse_args(argv)

    from app.devtools._support import validate_run_id
    run_id = validate_run_id(args.run_id or _run_id())
    sandbox.run_id = run_id
    if args.port == 8000:
        print("acceptance fatal: refusing to start the acceptance test service on 8000; use a dedicated --port (e.g. 8101/8107)", file=sys.stderr)
        return 2
    ACCEPTANCE_ROOT.mkdir(parents=True, exist_ok=True)
    started_at = _now()
    sandbox.run_context = {
        "started_at": started_at,
        "environment": config.environment,
        "database": config.database.database if config.database_url.startswith("postgresql+") else "sqlite",
        "storage_backend": config.storage_backend,
        "port": args.port,
    }
    server: ServerHandle | None = None
    run: AcceptanceRun | None = None
    fatal: str | None = None

    try:
        from app.devtools._support import probe_database

        __import__("asyncio").run(probe_database(config.database_url, expect_test_target=True))
        seed_summary = __import__("asyncio").run(
            seed_identities(
                run_id=run_id,
                credentials_path=config.credentials_path,
                config=config,
            )
        )
        if seed_summary.preserved:
            raise CheckFailure(
                "Seed accounts were modified/banned by a user; refusing to reset; use a new --run-id: "
                + ",".join(seed_summary.preserved)
            )
        credentials = load_credentials(
            config.credentials_path,
            require_private=True,
            identities=identities_for_run(run_id),
        )
        if credentials is None:
            raise CheckFailure("seed did not produce credentials for this run")
        seed_fingerprint = credentials.fingerprint
        server = start_server(port=args.port, run_id=run_id, sandbox=sandbox)
        base_url = server.base_url
        sandbox.run_context["base_url"] = base_url
        openapi_client = httpx.Client(base_url=base_url, timeout=20, trust_env=False)
        try:
            openapi_response = openapi_client.get("/openapi.json")
            if openapi_response.status_code != 200:
                raise CheckFailure("Unable to read OpenAPI")
            openapi = openapi_response.json()
        finally:
            openapi_client.close()
        route_index = RouteIndex(openapi)
        run = AcceptanceRun(
            base_url=base_url,
            config=config,
            run_id=run_id,
            credentials=credentials,
            server=server,
            only=args.only,
        )
        # Replace the initial empty index with the running OpenAPI.
        run.route_index = route_index
        run.api.route_index = route_index
        run.openapi = openapi
        run.all_business_routes = route_index.business_routes
        groups = [
            ("preflight", run.preflight),
            ("accounts", run.bootstrap_accounts),
            ("account_lifecycle", run.account_lifecycle),
            ("taxonomy", run.taxonomy),
            ("files_products", run.files_and_products),
            ("trades", run.trades_core),
            ("governance", run.governance),
            ("im_notifications", run.im_and_notifications),
        ]
        for name, func in groups:
            if not run._enabled(name):
                continue
            try:
                func()
            except CheckFailure as exc:
                run.rec.checks.append(
                    CheckRecord(
                        check_id=f"GROUP-{name}",
                        title=f"Scenario group {name} did not complete",
                        status=FAIL,
                        note=None,
                        error=str(exc),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                run.rec.checks.append(
                    CheckRecord(
                        check_id=f"GROUP-{name}",
                        title=f"Scenario group {name} raised",
                        status=FAIL,
                        note=None,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
            if args.inject_failure == "after-files" and name == "files_products":
                raise CheckFailure("Injected failure: aborting after product and object writes")
        run.finished_at = datetime.now(UTC)
        check_counts = run.rec.counts()
        checks_payload = [check.as_dict() for check in run.rec.checks]
        report = {
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": run.finished_at.isoformat(),
            "runtime_source": _source_digest(),
            "environment": {
                "base_url": base_url,
                "environment": config.environment,
                "database": config.database.database if config.database_url.startswith("postgresql+") else "sqlite",
                "storage_backend": config.storage_backend,
                "database_user": config.database.username if config.database_url.startswith("postgresql+") else None,
                "media_bucket": config.oss_media_bucket,
                "evidence_bucket": config.oss_evidence_bucket,
                "redis_mode": config.settings.kv_backend,
                "server_started_by_runner": server is not None,
                "port": args.port,
                "scan_interval_seconds": 2,
                "seed_fingerprint": seed_fingerprint or run.seed_fingerprint,
                "env_fingerprint": config.environment_fingerprint,
            },
            "openapi": {
                "business_route_count": len(run.all_business_routes),
                "routes": [{"method": method, "path": path} for method, path in run.all_business_routes],
            },
            "summary": {"checks": check_counts},
            "checks": checks_payload,
            "concurrency": run.concurrency,
            "clock_events": run.clock_events,
            "time_simulation": {
                "method": "Test service process injects a UTC offset (file-controlled; now()=real UTC+offset); database time fields are unchanged; the 7-day threshold is not shortened",
                "clock_file_mode": "Windows private ACL" if sys.platform == "win32" else "0600",
                "scan_interval_seconds": 2,
                "production_rule_unchanged": True,
            },
            "notes": run.notes,
        }
        if server is not None:
            server.stop()
        print(f"acceptance: run_id={run_id} checks={check_counts}")
        full_pass = _checks_passed(run.rec.checks)
        if not full_pass:
            sandbox.failure_state = {
                "report": report,
                "context": sandbox.run_context,
                "fatal": None,
                "partial_checks": [],
                "call_index": _call_index(run.api.calls),
            }
        return 0 if full_pass else 1
    except Exception as exc:  # noqa: BLE001 - top level prints only the safe type
        fatal = str(exc) if isinstance(exc, CheckFailure) else type(exc).__name__
        print(f"acceptance fatal: {fatal}", file=sys.stderr)
        if sandbox is not None:
            sandbox.failure_state = {
                "report": None,
                "context": sandbox.run_context,
                "fatal": fatal,
                "partial_checks": [check.as_dict() for check in run.rec.checks] if run is not None else [],
                "call_index": _call_index(run.api.calls) if run is not None else {},
            }
        return 2
    finally:
        if server is not None:
            server.stop()
            server.clock_file.unlink(missing_ok=True)
            server.log_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    import signal

    sandbox = None
    result = 2
    fatal_error: str | None = None
    actual_args = list(sys.argv[1:] if argv is None else argv)
    if actual_args and actual_args[0] == "--recover":
        if len(actual_args) != 2:
            print("Usage: --recover <ownership.json>", file=sys.stderr)
            return 2
        try:
            from app.devtools._support import load_dev_config

            from tests.acceptance_real.sandbox import Sandbox

            sandbox = Sandbox.recover(Path(actual_args[1]), load_dev_config(for_acceptance=True, require_storage=True))
            cleanup = sandbox.cleanup()
            print("cleanup: " + json.dumps(cleanup, ensure_ascii=False))
            return 2 if cleanup["cleanup_failures"] else 0
        except BaseException as exc:  # noqa: BLE001 - cleanup also handles interruption
            print(f"recovery failed: {type(exc).__name__}", file=sys.stderr)
            return 2
    _parser().parse_args(actual_args)  # Validate/help before allocating any resources.
    previous = signal.getsignal(signal.SIGTERM)
    def interrupted(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        signal.signal(signal.SIGTERM, interrupted)
        from app.devtools._support import load_dev_config

        from tests.acceptance_real.sandbox import Sandbox

        sandbox = Sandbox(load_dev_config(for_acceptance=True, require_storage=True))
        config = sandbox.create()
        sandbox.active = True
        sandbox._write_manifest("active")
        result = _run(argv, sandbox, config)
    except BaseException as exc:  # noqa: BLE001 - cleanup also handles interruption
        fatal_error = type(exc).__name__
        print(f"acceptance fatal: {fatal_error}", file=sys.stderr)
        result = 2
    finally:
        previous_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        cleanup: dict[str, Any] | None = None
        if sandbox is not None:
            try:
                process = getattr(sandbox, "process", None)
                if process is not None and process.poll() is None and sandbox.clock_file is not None:
                    from tests.acceptance_real.processes import stop_server
                    stop_server(process, sandbox.clock_file)
                cleanup = sandbox.cleanup()
                print("cleanup: " + json.dumps(cleanup, ensure_ascii=False))
                if cleanup["cleanup_failures"]:
                    result = 2
            except BaseException as exc:  # noqa: BLE001 - cleanup also handles interruption
                print(f"cleanup failed: {type(exc).__name__}; manifest={sandbox.manifest}", file=sys.stderr)
                result = 2
        if sandbox is not None and result != 0:
            state = getattr(sandbox, "failure_state", None) or {}
            run_id = getattr(sandbox, "run_id", None) or _run_id()
            log_path = ACCEPTANCE_ROOT / f"acceptance-failure-{run_id}.log"
            log_path.write_text(
                _failure_log(
                    run_id=run_id,
                    exit_code=result,
                    report=state.get("report"),
                    context=state.get("context") or getattr(sandbox, "run_context", None),
                    partial_checks=state.get("partial_checks") or [],
                    call_index=state.get("call_index") or {},
                    fatal=state.get("fatal") or fatal_error,
                    cleanup=cleanup,
                ),
                encoding="utf-8",
            )
            print(f"failure log: {log_path}")
        signal.signal(signal.SIGTERM, previous)
        signal.signal(signal.SIGINT, previous_int)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
