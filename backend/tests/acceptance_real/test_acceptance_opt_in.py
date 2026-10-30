"""唯一 pytest 全量入口：默认拒绝以 0 条/跳过宣称成功。

显式运行::

    RUN_REAL_ACCEPTANCE=1 .venv/bin/python -m pytest -q

默认 pytest 会明确失败并提示，而不是把 skipped/0 条当作验收通过。
"""

from __future__ import annotations

import os

import pytest


def test_real_acceptance() -> None:
    if os.environ.get("RUN_REAL_ACCEPTANCE") != "1":
        pytest.fail(
            "真实全量验收未启用：请显式设置 RUN_REAL_ACCEPTANCE=1；"
            "拒绝以 skipped/0 条视为成功。默认只允许离线清单导出："
            "python -m tests.acceptance_real.catalog --check"
        )
    from tests.acceptance_real.runner import main

    port = int(os.environ.get("ACCEPTANCE_PORT", "8101"))
    run_id = os.environ.get("ACCEPTANCE_RUN_ID")
    argv = ["--port", str(port)]
    if run_id:
        argv.extend(["--run-id", run_id])
    result = main(argv)
    assert result == 0, "真实验收存在 FAIL/SKIP/未语义覆盖，查看 var/acceptance-real/ 报告"
