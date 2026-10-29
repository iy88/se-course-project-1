"""真实开发环境生命周期测试编排器。

用法（在 backend/tests/e2e_lifecycle 下，使用 backend/.venv 运行）：
    ../../.venv/bin/python e2e_runner.py --list
    ../../.venv/bin/python e2e_runner.py --only p01 p02
    ../../.venv/bin/python e2e_runner.py --base-url http://127.0.0.1:8000

默认串行执行全部阶段：p01 账户 → p02 分类/禁发 → p03 商品发布审核 → p04 检索收藏评论
→ p05 交易核心 → p06 IM 与通知 → p07 评价举报治理 → p08 超时异常 → p09 统计/本人业务 → p10 可靠性。
`--db-path` 默认仓库 var/db/app.db（仅 p08 时间加速），`--results-dir` 默认仓库 var/e2e-results；
相对路径按当前工作目录解析。
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import httpx

from e2e_client import Api
from e2e_recorder import Recorder
from e2e_report import build_report
from e2e_support import Ctx, refresh_inventory

HARNESS_DIR = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_DIR.parents[2]  # backend/tests/e2e_lifecycle → 仓库根
DEFAULT_RESULTS_DIR = REPO_ROOT / "var" / "e2e-results"

# id, 标题, 模块, 依赖说明（报告展示用）
PHASES = [
    ("p01", "账户生命周期与访问控制", "phases.p01_accounts", "US-01、SC-01"),
    ("p02", "分类标签与禁发范围维护", "phases.p02_catalog_admin", "US-08、US-13、SC-10、SC-02"),
    ("p03", "商品发布、审核与维护", "phases.p03_products_review", "US-02、US-09、SC-02"),
    ("p04", "检索、详情、收藏与评论", "phases.p04_search_favorites_comments", "US-03、US-04、SC-03"),
    ("p05", "请求、约定、确认与终止", "phases.p05_trades_core", "US-05、US-06、SC-05、SC-06"),
    ("p06", "两类 IM 与站内通知", "phases.p06_im_notifications", "US-04、US-11、SC-04、SC-11"),
    ("p07", "评价、举报、认领与封禁", "phases.p07_reviews_reports_governance", "US-07、US-08、SC-07"),
    ("p08", "单方确认超时与异常交易", "phases.p08_abnormal_timeout", "US-14、SC-09"),
    ("p09", "统计、本人业务与待办", "phases.p09_stats_my_business", "US-10、US-12、SC-08、SC-12、SC-11"),
    ("p10", "可靠性与权限边界", "phases.p10_reliability", "7.3 可靠性、越权/重复提交"),
]
PHASE_BY_ID = {p[0]: p for p in PHASES}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="真实开发环境生命周期测试编排器")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="运行中的后端地址")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR), help="结果输出目录")
    parser.add_argument("--only", nargs="*", default=None, help="只运行指定阶段，如 --only p01 p03")
    parser.add_argument("--skip", nargs="*", default=None, help="跳过指定阶段")
    parser.add_argument("--run-id", default=None, help="运行标识（写入报告）")
    parser.add_argument(
        "--db-path",
        default=str(REPO_ROOT / "var" / "db" / "app.db"),
        help="SQLite 路径（仅 p08 时间加速使用；不影响其他阶段）",
    )
    parser.add_argument("--no-refresh", action="store_true", help="跳过结束后数据状态复核")
    parser.add_argument("--list", action="store_true", help="列出阶段后退出")
    return parser.parse_args(argv)


def select_phases(args: argparse.Namespace) -> list[tuple]:
    selected = PHASES
    if args.only:
        wanted = {p.lower() for p in args.only}
        selected = [p for p in PHASES if p[0] in wanted]
        if not selected:
            raise SystemExit(f"未知阶段：{args.only}")
    if args.skip:
        skipped = {p.lower() for p in args.skip}
        selected = [p for p in selected if p[0] not in skipped]
    return selected


def check_health(base_url: str) -> dict:
    try:
        resp = httpx.get(base_url.rstrip("/") + "/api/health", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"后端不可用（{base_url}/api/health）：{exc}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list:
        for pid, title, module, reqs in PHASES:
            print(f"{pid}  {title}  [{reqs}]")
        return 0

    selected = select_phases(args)
    health = check_health(args.base_url)
    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    ctx = Ctx(run_id=run_id, db_path=args.db_path)
    started_at = datetime.now().astimezone()
    phase_summaries: list[dict] = []
    all_results: list[dict] = []
    all_defects: list[dict] = []
    call_counts: list[dict] = []

    print(f"== 运行 {run_id} | {args.base_url} | 健康检查：{health}")
    print(f"== 结果目录：{results_dir}")

    api: Api | None = None
    try:
        for pid, title, module_name, reqs in selected:
            print(f"\n-- [{pid}] {title} ({reqs})")
            recorder = Recorder(pid, title)
            api = Api(args.base_url, recorder)
            t0 = time.monotonic()
            try:
                module = importlib.import_module(module_name)
                module.run(ctx, api, recorder)
            except Exception as exc:  # noqa: BLE001 - 阶段失败继续后续独立阶段
                recorder.phase_aborted(pid, exc)
                print(f"   阶段异常：{type(exc).__name__}: {exc}")
                traceback.print_exc(limit=3)
            elapsed = round(time.monotonic() - t0, 1)
            counts = recorder.counts()
            print(
                f"   完成：PASS={counts.get('PASS', 0)} FAIL={counts.get('FAIL', 0)} "
                f"SKIP={counts.get('SKIP', 0)} 用时={elapsed}s"
            )
            all_results.extend(recorder.results)
            all_defects.extend(recorder.defects)
            phase_summaries.append(
                {
                    "id": pid,
                    "title": title,
                    "requirements": reqs,
                    "elapsed_seconds": elapsed,
                    "counts": counts,
                    "aborted": any(d.get("kind") == "phase_aborted" for d in recorder.defects),
                }
            )
            call_counts.append(
                {
                    "phase": pid,
                    "calls": len(api.calls),
                    "errors": len([c for c in api.calls if c["status"] == "ERR"]),
                    "server_5xx": len([c for c in api.calls if isinstance(c["status"], int) and c["status"] >= 500]),
                }
            )
    finally:
        if api is not None:
            api.close()

    # 结束后复核清单中对象真实状态（通过只读接口重新读取）
    refresh_notes: list[str] = []
    if not args.no_refresh:
        print("\n== 结束时复核数据状态")
        refresh_recorder = Recorder("inventory", "数据状态复核")
        refresh_api = Api(args.base_url, refresh_recorder)
        try:
            refresh_notes = refresh_inventory(refresh_api, ctx)
        except Exception as exc:  # noqa: BLE001
            refresh_notes = [f"数据状态复核异常：{type(exc).__name__}: {exc}"]
            traceback.print_exc(limit=2)
        finally:
            refresh_api.close()
            all_defects.extend(refresh_recorder.defects)

    finished_at = datetime.now().astimezone()
    report = build_report(
        run_id=run_id,
        base_url=args.base_url,
        health=health,
        started_at=started_at,
        finished_at=finished_at,
        phases=selected,
        phase_summaries=phase_summaries,
        results=all_results,
        defects=all_defects,
        call_counts=call_counts,
        ctx=ctx,
        refresh_notes=refresh_notes,
    )
    (results_dir / "results.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "base_url": args.base_url,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "phases": phase_summaries,
                "results": all_results,
                "defects": all_defects,
                "notes": ctx.notes,
                "refresh_notes": refresh_notes,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (results_dir / "inventory.json").write_text(
        json.dumps(ctx.inventory, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (results_dir / "report.md").write_text(report, encoding="utf-8")

    total = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for row in all_results:
        total[row["status"]] = total.get(row["status"], 0) + 1
    print(f"\n== 总计 PASS={total['PASS']} FAIL={total['FAIL']} SKIP={total['SKIP']}")
    print(f"== 报告：{results_dir / 'report.md'}")
    return 0 if total["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
