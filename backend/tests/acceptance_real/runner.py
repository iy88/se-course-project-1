"""任务 F 全 API/全 AC/SC 真实验收运行器（显式 opt-in）。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from app.core.private_files import protect_private

from tests.acceptance_real.catalog import build_payload
from tests.acceptance_real.core import (
    BACKEND_ROOT,
    FAIL,
    PARTIAL,
    PASS,
    REPO_ROOT,
    SKIP,
    UNCOVERED,
    Catalog,
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
        raise CheckFailure(f"端口 {port} 已被占用；拒绝 kill 已有服务，请改 --port 或 --no-start-server")
    clock_file = sandbox.root / f"clock-{run_id}.txt"
    clock_file.parent.mkdir(parents=True, exist_ok=True)
    clock_file.write_text("0\n", encoding="ascii")
    protect_private(clock_file)
    log_path = sandbox.root / f"server-{run_id}.log"
    log_handle = log_path.open("wb")
    env = sandbox.server_env()
    env["PYTHONUNBUFFERED"] = "1"
    command = [
        sys.executable,
        "-m",
        "tests.acceptance_real.clock_server",
        "--port",
        str(port),
        "--clock-file",
        str(clock_file),
    ]
    command = [sys.executable, "-m", *sandbox.code_coverage.server_command(command[2:])]
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
            raise CheckFailure(f"测试服务启动失败（exit={process.returncode}）；日志仅保留退出码")
        try:
            response = httpx.get(base_url + "/api/health", timeout=3, trust_env=False)
            if response.status_code == 200:
                return ServerHandle(process=process, base_url=base_url, clock_file=clock_file, log_path=log_path)
            last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = type(exc).__name__
        time.sleep(0.5)
    from tests.acceptance_real.processes import stop_server
    stop_server(process, clock_file)
    raise CheckFailure(f"测试服务未在 45s 内健康（最后 {last_error}）")


def _requirements_coverage(catalog: Catalog, checks: Sequence[Any], kind: str) -> dict[str, Any]:
    ids = catalog.ac_ids if kind == "AC" else catalog.sc_ids
    by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for check in checks:
        for item_id in (check.ac if kind == "AC" else check.sc):
            by_item[item_id].append(
                {
                    "check_id": check.check_id,
                    "status": check.status,
                    "coverage": check.coverage,
                    "note": check.note,
                }
            )
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = defaultdict(int)
    for item_id in ids:
        item = catalog.items[item_id]
        mappings = by_item.get(item_id, [])
        if not mappings:
            status = UNCOVERED
        elif any(row["status"] == FAIL for row in mappings):
            status = FAIL
        elif all(row["status"] == SKIP for row in mappings):
            status = SKIP
        elif any(row["status"] == PASS and row["coverage"] == "full" for row in mappings):
            status = PASS
        elif any(row["status"] == PASS for row in mappings):
            status = PARTIAL
        else:
            status = UNCOVERED
        counts[status] += 1
        rows.append(
            {
                "id": item_id,
                "kind": kind,
                "title": item.title,
                "source_file": item.file,
                "text": item.text[:800],
                "status": status,
                "mappings": mappings,
            }
        )
    return {
        "counts": dict(counts),
        "total": len(ids),
        "items": rows,
        "missing": [row["id"] for row in rows if row["status"] == UNCOVERED],
        "failing": [row["id"] for row in rows if row["status"] == FAIL],
        "partial": [row["id"] for row in rows if row["status"] == PARTIAL],
        "skipped": [row["id"] for row in rows if row["status"] == SKIP],
    }


def _uc_coverage(payload: Mapping[str, Any], checks: Sequence[Any]) -> dict[str, Any]:
    """主用例/子用例覆盖：只有全部映射 check PASS 才 PASS。"""
    status_by_check = {check.check_id: check.status for check in checks}
    sub_rows: list[dict[str, Any]] = []
    counts: dict[str, int] = defaultdict(int)
    for item in payload.get("uc_subcases") or []:
        mapped = list(item.get("check_ids") or [])
        statuses = [status_by_check.get(check_id, UNCOVERED) for check_id in mapped]
        if not mapped:
            status = UNCOVERED
        elif any(value == FAIL for value in statuses):
            status = FAIL
        elif any(value == SKIP for value in statuses):
            status = SKIP
        elif all(value == PASS for value in statuses):
            status = PASS
        elif any(value == PASS for value in statuses):
            status = PARTIAL
        else:
            status = UNCOVERED
        counts[status] += 1
        sub_rows.append(
            {
                "id": item.get("id"),
                "main_uc": item.get("main_uc"),
                "title": item.get("title"),
                "source_file": item.get("source_file"),
                "check_ids": mapped,
                "check_status": dict(zip(mapped, statuses)),
                "status": status,
                "evidence": item.get("evidence"),
            }
        )
    main_rows: list[dict[str, Any]] = []
    main_counts: dict[str, int] = defaultdict(int)
    for main in payload.get("uc") or []:
        subs = [row for row in sub_rows if row["main_uc"] == main.get("id")]
        if not subs:
            status = UNCOVERED
        elif any(row["status"] == FAIL for row in subs):
            status = FAIL
        elif any(row["status"] == SKIP for row in subs):
            status = SKIP
        elif all(row["status"] == PASS for row in subs):
            status = PASS
        elif any(row["status"] == PASS for row in subs):
            status = PARTIAL
        else:
            status = UNCOVERED
        main_counts[status] += 1
        main_rows.append(
            {
                "id": main.get("id"),
                "title": main.get("title"),
                "source_file": main.get("source_file"),
                "subcase_count": len(subs),
                "subcases": [row["id"] for row in subs],
                "check_ids": sorted({check_id for row in subs for check_id in row["check_ids"]}),
                "status": status,
            }
        )
    return {
        "counts": dict(main_counts),
        "total": len(main_rows),
        "items": main_rows,
        "subcase_counts": dict(counts),
        "subcase_total": len(sub_rows),
        "subcases": sub_rows,
        "missing": [row["id"] for row in sub_rows if row["status"] in {UNCOVERED, PARTIAL}],
        "failing": [row["id"] for row in sub_rows if row["status"] == FAIL],
        "skipped": [row["id"] for row in sub_rows if row["status"] == SKIP],
        "main_failing": [row["id"] for row in main_rows if row["status"] == FAIL],
        "main_missing": [row["id"] for row in main_rows if row["status"] in {UNCOVERED, PARTIAL, SKIP}],
    }


def _route_coverage(run: AcceptanceRun, checks: Sequence[Any]) -> dict[str, Any]:
    calls_by_route: dict[tuple[str, str], list[Any]] = defaultdict(list)
    unmatched: list[dict[str, Any]] = []
    infra_paths = {"/api/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    for call in run.api.calls:
        if call.template:
            calls_by_route[(call.method, call.template)].append(call)
        elif call.actual_path not in infra_paths:
            unmatched.append(call.as_dict())
    check_by_id = {check.check_id: check for check in checks}
    rows: list[dict[str, Any]] = []
    for method, path in sorted(run.all_business_routes, key=lambda row: (row[1], row[0])):
        calls = calls_by_route.get((method, path), [])
        normal = [call for call in calls if isinstance(call.status, int) and 200 <= call.status < 300]
        semantic = [
            call for call in normal if check_by_id.get(call.check_id) and check_by_id[call.check_id].status == PASS
        ]
        negative = [
            call
            for call in calls
            if isinstance(call.status, int)
            and 400 <= call.status < 500
            and check_by_id.get(call.check_id)
            and check_by_id[call.check_id].status == PASS
        ]
        rows.append(
            {
                "method": method,
                "path": path,
                "calls": len(calls),
                "normal_2xx": len(normal),
                "semantic_success": len(semantic),
                "meaningful_negative": len(negative),
                "check_ids": sorted({call.check_id for call in calls}),
                "status": "PASS" if semantic else ("FAIL" if calls else UNCOVERED),
            }
        )
    missing = [row for row in rows if row["status"] != "PASS"]
    return {
        "total": len(rows),
        "covered": len(rows) - len(missing),
        "missing_or_unverified": missing,
        "infrastructure": {
            "health": any(call.actual_path == "/api/health" and call.status == 200 for call in run.api.calls),
            "openapi": any(call.actual_path == "/openapi.json" and call.status == 200 for call in run.api.calls),
            "docs": any(call.actual_path == "/docs" and call.status == 200 for call in run.api.calls),
            "websocket": run.ws_ok,
        },
        "unmatched_calls": unmatched,
        "routes": rows,
    }


def _markdown(report: Mapping[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"# 真实验收报告 {report['run_id']}",
        "",
        f"- 时间：{report['started_at']} — {report['finished_at']}",
        f"- 目标：`{report['environment']['base_url']}`（{report['environment']['database']} / {report['environment']['storage_backend']}；独立服务）",
        f"- 源码：HEAD `{report['runtime_source']['git_head']}`，工作区脏={report['runtime_source']['working_tree_dirty']}，摘要 `{report['runtime_source']['source_digest_sha256'][:16]}…`",
        f"- 检查：PASS={summary['checks']['PASS']} FAIL={summary['checks']['FAIL']} SKIP={summary['checks']['SKIP']}",
        f"- 路由：语义通过 {report['routes']['covered']}/{report['routes']['total']}",
        f"- AC：{summary['ac']['counts']}",
        f"- SC：{summary['sc']['counts']}",
        "",
    ]
    measurement = report.get("code_coverage")
    if measurement:
        lines.extend([
            "", "## 应用代码覆盖率", "",
            f"- 行：{measurement['covered_lines']}/{measurement['total_lines']}（{measurement['line_percent']}%）",
            f"- 分支：{measurement['covered_branches']}/{measurement['total_branches']}（{measurement['branch_percent']}%）",
            f"- 范围：{measurement['scope']}；进程：{', '.join(measurement['processes'])}",
            f"- 真实 API 子进程采集验证：{measurement['api_subprocess_verified']}",
            f"- [HTML 逐行报告]({measurement['artifacts']['html']}) / [JSON]({measurement['artifacts']['json']}) / [XML]({measurement['artifacts']['xml']})",
            "",
        ])
    if report.get("code_coverage_error"):
        lines.extend(["", "## 代码覆盖率采集失败", "", report["code_coverage_error"], ""])
    lines.extend(["", "## 检查结果", ""])
    for check in report["checks"]:
        mark = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}.get(check["status"], "❔")
        lines.append(f"- {mark} `{check['check_id']}` {check['title']}（{check['coverage']}）")
        if check.get("error"):
            lines.append(f"  - 失败：{check['error']}")
        if check.get("assertions"):
            lines.append(f"  - 断言：{len(check['assertions'])} 条")
    lines += ["", "## 路由缺口", ""]
    missing = report["routes"]["missing_or_unverified"]
    if missing:
        for row in missing:
            lines.append(f"- ❌ `{row['method']} {row['path']}` calls={row['calls']} semantic={row['semantic_success']}")
    else:
        lines.append("- 全部业务路由均有真实 2xx 成功语义调用。")
    uc = report["uc"]
    uc_gaps = [row for row in uc["items"] if row["status"] != "PASS"] + [
        row for row in uc["subcases"] if row["status"] != "PASS"
    ]
    lines += ["", f"## UC 缺口（主用例 {uc['counts']}；子用例 {uc['subcase_counts']}）", ""]
    if not uc_gaps:
        lines.append("- 14 主用例 / 66 子用例全部映射检查 PASS。")
    else:
        for row in uc_gaps:
            mapped = ", ".join(row.get("check_ids") or []) or "无"
            lines.append(f"- {row['status']} `{row['id']}`（映射：{mapped}）")
    for kind, key in (("AC", "ac"), ("SC", "sc")):
        data = report[key]
        gaps = [row for row in data["items"] if row["status"] != "PASS"]
        lines += ["", f"## {kind} 缺口（{len(gaps)}/{data['total']}）", ""]
        if not gaps:
            lines.append(f"- 全部 {kind} 有 full PASS 映射。")
        else:
            for row in gaps:
                mapped = ", ".join(item["check_id"] for item in row["mappings"]) or "无"
                lines.append(f"- {row['status']} `{row['id']}`（映射：{mapped}）")
    lines += [
        "",
        "## 时间模拟与并发",
        "",
        f"- 7 天/冻结：{report['time_simulation']['method']}",
        f"- 扫描周期 override：{report['time_simulation']['scan_interval_seconds']}s（7 天业务阈值未改）",
        f"- 时钟事件：{len(report['clock_events'])} 条",
        f"- 并发证据：{len(report['concurrency'])} 组",
        "",
        "## 清理与保留",
        "",
        f"- 隔离清理：{json.dumps(report['cleanup'], ensure_ascii=False)}",
        f"- 服务进程：{'已停止' if report['cleanup']['server_stopped'] else '未停止（需人工检查）'}",
    ]
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Task F 全 API/全 AC/SC 真实验收")
    parser.add_argument("--base-url", default=None, help="已运行服务地址；默认由本任务启动 127.0.0.1:8101")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-start-server", action="store_true", help="复用已启动服务（不注入受控时钟，7 天场景将 FAIL/SKIP）")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--inject-failure", choices=["after-files"], help=argparse.SUPPRESS)
    parser.add_argument("--only", nargs="*", default=None, help="只跑指定组（调试）")
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
    if not args.no_start_server and args.port == 8000:
        print("acceptance fatal: 拒绝在 8000 启动验收测试服务；请用独立 --port（如 8101/8107）", file=sys.stderr)
        return 2
    ACCEPTANCE_ROOT.mkdir(parents=True, exist_ok=True)
    started_at = _now()
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
                "seed 账号已被用户修改/封禁，拒绝重置；请使用新 --run-id："
                + ",".join(seed_summary.preserved)
            )
        credentials = load_credentials(
            config.credentials_path,
            require_private=True,
            identities=identities_for_run(run_id),
        )
        if credentials is None:
            raise CheckFailure("seed 未生成本轮凭据")
        seed_fingerprint = credentials.fingerprint
        if args.no_start_server:
            raise CheckFailure("验收必须启动本轮独立服务")
        if args.base_url and not args.no_start_server:
            raise CheckFailure("--base-url 仅与 --no-start-server 同用；否则由 --port 启动独立服务")
        if args.no_start_server:
            if not args.base_url:
                raise CheckFailure("--no-start-server 需要 --base-url")
            base_url = args.base_url.rstrip("/")
        else:
            server = start_server(port=args.port, run_id=run_id, sandbox=sandbox)
            base_url = server.base_url
        catalog = Catalog().load()
        manifest_payload = build_payload(catalog)
        if not manifest_payload["validation"]["ok"]:
            raise CheckFailure(
                "业务测试清单校验失败：" + "; ".join(manifest_payload["validation"]["errors"])
            )
        openapi_client = httpx.Client(base_url=base_url, timeout=20, trust_env=False)
        try:
            openapi_response = openapi_client.get("/openapi.json")
            if openapi_response.status_code != 200:
                raise CheckFailure("无法读取 OpenAPI")
            openapi = openapi_response.json()
        finally:
            openapi_client.close()
        route_index = RouteIndex(openapi)
        run = AcceptanceRun(
            base_url=base_url,
            config=config,
            catalog=catalog,
            run_id=run_id,
            server=server,
            only=args.only,
        )
        # 用运行 OpenAPI 替换初始空索引。
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
                        title=f"场景组 {name} 未完成",
                        status=FAIL,
                        ac=[],
                        sc=[],
                        coverage="none",
                        note=None,
                        error=str(exc),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                run.rec.checks.append(
                    CheckRecord(
                        check_id=f"GROUP-{name}",
                        title=f"场景组 {name} 异常",
                        status=FAIL,
                        ac=[],
                        sc=[],
                        coverage="none",
                        note=None,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
            if args.inject_failure == "after-files" and name == "files_products":
                raise CheckFailure("注入失败：商品与对象写入后中止")
        run.finished_at = datetime.now(UTC)
        routes = _route_coverage(run, run.rec.checks)
        ac = _requirements_coverage(catalog, run.rec.checks, "AC")
        sc = _requirements_coverage(catalog, run.rec.checks, "SC")
        uc = _uc_coverage(manifest_payload, run.rec.checks)
        check_counts = run.rec.counts()
        manifest_checks = {row["check_id"]: row for row in manifest_payload["checks"]}
        checks_payload: list[dict[str, Any]] = []
        for check in run.rec.checks:
            item = check.as_dict()
            meta = manifest_checks.get(check.check_id, {})
            for field in ("role", "precondition", "action", "expected", "uc_subcases"):
                item[field] = meta.get(field)
            checks_payload.append(item)
        report = {
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": run.finished_at.isoformat(),
            "runtime_source": _source_digest(),
            "catalog": catalog.summary(),
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
            "summary": {
                "checks": check_counts,
                "routes": {"total": routes["total"], "covered": routes["covered"]},
                "ac": {"total": ac["total"], "counts": ac["counts"]},
                "sc": {"total": sc["total"], "counts": sc["counts"]},
                "uc": {"total": uc["total"], "counts": uc["counts"]},
                "uc_subcases": {"total": uc["subcase_total"], "counts": uc["subcase_counts"]},
            },
            "gaps": {
                "routes_missing_or_unverified": routes["missing_or_unverified"],
                "ac_failing": ac["failing"],
                "ac_partial": ac["partial"],
                "ac_uncovered": ac["missing"],
                "sc_failing": sc["failing"],
                "sc_partial": sc["partial"],
                "sc_uncovered": sc["missing"],
                "uc_main_failing": uc["main_failing"],
                "uc_main_missing": uc["main_missing"],
                "uc_subcase_failing": uc["failing"],
                "uc_subcase_missing": uc["missing"],
                "uc_subcase_skipped": uc["skipped"],
            },
            "checks": checks_payload,
            "routes": routes,
            "ac": ac,
            "sc": sc,
            "uc": uc,
            "catalog_manifest": {
                "validation": manifest_payload["validation"],
                "summary": manifest_payload["summary"],
                "source_digest_sha256": manifest_payload["source"]["source_digest_sha256"],
                "manual_channel": manifest_payload["manual_channel"],
            },
            "concurrency": run.concurrency,
            "clock_events": run.clock_events,
            "time_simulation": {
                "method": "测试服务进程注入 UTC offset（文件控制，now()=真实UTC+offset）；未修改数据库时间字段；未缩短 7 天阈值",
                "clock_file_mode": "Windows private ACL" if sys.platform == "win32" else "0600",
                "scan_interval_seconds": 2,
                "production_rule_unchanged": True,
            },
            "cleanup": {
                "counts": (run.rec.checks[-1].data.get("counts") if run.rec.checks and run.rec.checks[-1].data else {}),
                "retained": run.retained,
                "retained_objects": (run.rec.checks[-1].data.get("retained_objects") if run.rec.checks and run.rec.checks[-1].data else []),
                "server_stopped": False,
                "destructive_cleanup": False,
            },
            "notes": run.notes,
        }
        json_path = ACCEPTANCE_ROOT / f"acceptance-{run_id}.json"
        md_path = ACCEPTANCE_ROOT / f"acceptance-{run_id}.md"
        # 停服务后再标记停止状态并重写报告。
        if server is not None:
            server.stop()
            report["cleanup"]["server_stopped"] = True
        sandbox.report_paths = (json_path, md_path)
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        print(
            f"acceptance: run_id={run_id} checks={check_counts} "
            f"routes={routes['covered']}/{routes['total']} ac={ac['counts']} sc={sc['counts']} "
            f"uc={uc['counts']} subuc={uc['subcase_counts']}"
        )
        print(f"report: {json_path}")
        print(f"summary: {md_path}")
        full_pass = (
            check_counts.get(FAIL, 0) == 0
            and check_counts.get(SKIP, 0) == 0
            and check_counts.get(PASS, 0) == len(run.rec.checks)
            and all(check.coverage == "full" for check in run.rec.checks)
            and not routes["missing_or_unverified"]
            and ac["counts"].get(PASS, 0) == ac["total"]
            and sc["counts"].get(PASS, 0) == sc["total"]
            and uc["counts"].get(PASS, 0) == uc["total"]
            and uc["subcase_counts"].get(PASS, 0) == uc["subcase_total"]
            and not uc["failing"]
            and not uc["missing"]
            and not uc["skipped"]
            and manifest_payload["validation"]["ok"]
        )
        return 0 if full_pass else 1
    except Exception as exc:  # noqa: BLE001 - 顶层只输出安全类型
        fatal = str(exc) if isinstance(exc, CheckFailure) else type(exc).__name__
        print(f"acceptance fatal: {fatal}", file=sys.stderr)
        return 2
    finally:
        if server is not None:
            server.stop()
            server.clock_file.unlink(missing_ok=True)
            server.log_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    import signal

    from tests.acceptance_real.code_coverage import CodeCoverage

    sandbox = None
    collector = None
    result = 2
    actual_args = list(sys.argv[1:] if argv is None else argv)
    if actual_args and actual_args[0] == "--recover":
        if len(actual_args) != 2:
            print("用法：--recover <ownership.json>", file=sys.stderr)
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
        collector = CodeCoverage()
        signal.signal(signal.SIGTERM, interrupted)
        from app.devtools._support import load_dev_config

        from tests.acceptance_real.sandbox import Sandbox

        sandbox = Sandbox(load_dev_config(for_acceptance=True, require_storage=True))
        sandbox.code_coverage = collector
        config = sandbox.create()
        sandbox.active = True
        sandbox._write_manifest("active")
        result = _run(argv, sandbox, config)
    except BaseException as exc:  # noqa: BLE001 - cleanup also handles interruption
        print(f"acceptance fatal: {type(exc).__name__}", file=sys.stderr)
    finally:
        previous_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if sandbox is not None:
            try:
                process = getattr(sandbox, "process", None)
                if process is not None and process.poll() is None:
                    from tests.acceptance_real.processes import stop_server
                    stop_server(process, sandbox.clock_file)
                cleanup = sandbox.cleanup()
                print("cleanup: " + json.dumps(cleanup, ensure_ascii=False))
                paths = getattr(sandbox, "report_paths", None)
                if paths:
                    json_path, md_path = paths
                    report = json.loads(json_path.read_text(encoding="utf-8"))
                    report["cleanup"] = {**cleanup, "server_stopped": True}
                    report["exit_code"] = 2 if cleanup["cleanup_failures"] else result
                    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                    md_path.write_text(_markdown(report), encoding="utf-8")
                if cleanup["cleanup_failures"]:
                    result = 2
            except BaseException as exc:  # noqa: BLE001 - cleanup also handles interruption
                print(f"cleanup failed: {type(exc).__name__}; manifest={sandbox.manifest}", file=sys.stderr)
                result = 2
        if collector is not None:
            try:
                measurement = collector.finish(
                    server_started=sandbox is not None and sandbox.process is not None,
                    acceptance_exit_code=result,
                )
                print("code coverage: " + json.dumps(measurement, ensure_ascii=False))
                paths = getattr(sandbox, "report_paths", None)
                if paths:
                    json_path, md_path = paths
                    report = json.loads(json_path.read_text(encoding="utf-8"))
                    report["code_coverage"] = measurement
                    report["exit_code"] = result
                    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                    md_path.write_text(_markdown(report), encoding="utf-8")
            except Exception as exc:  # noqa: BLE001 - preserve cleanup success but fail missing measurement
                print(f"code coverage failed: {type(exc).__name__}", file=sys.stderr)
                result = 2
                paths = getattr(sandbox, "report_paths", None)
                if paths:
                    json_path, md_path = paths
                    report = json.loads(json_path.read_text(encoding="utf-8"))
                    report["code_coverage_error"] = type(exc).__name__
                    report["exit_code"] = result
                    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                    md_path.write_text(_markdown(report), encoding="utf-8")
        signal.signal(signal.SIGTERM, previous)
        signal.signal(signal.SIGINT, previous_int)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
