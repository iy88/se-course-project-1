"""Run HTTP/WS acceptance when RUN_REAL_ACCEPTANCE=1 is selected."""

from __future__ import annotations

import os

import pytest


@pytest.mark.skipif(
    os.environ.get("RUN_REAL_ACCEPTANCE") != "1",
    reason="Set RUN_REAL_ACCEPTANCE=1 to run HTTP/WS acceptance",
)
def test_real_acceptance() -> None:
    from tests.acceptance_real.runner import main

    port = int(os.environ.get("ACCEPTANCE_PORT", "8101"))
    run_id = os.environ.get("ACCEPTANCE_RUN_ID")
    argv = ["--port", str(port)]
    if run_id:
        argv.extend(["--run-id", run_id])
    result = main(argv)
    assert result == 0, "真实验收存在失败或跳过的检查，查看 var/acceptance-real/acceptance-failure-*.log"
