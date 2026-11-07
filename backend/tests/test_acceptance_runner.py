"""Business assertions determine acceptance results directly."""
from types import SimpleNamespace

import pytest

from tests.acceptance_real.core import FAIL, PASS, SKIP, CheckRecord, Recorder
from tests.acceptance_real.runner import _checks_passed, _failure_log


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [([], False), ([PASS], True), ([PASS, PASS], True),
     ([PASS, FAIL], False), ([PASS, SKIP], False)],
)
def test_acceptance_result_requires_executed_passing_checks(statuses, expected):
    checks = [CheckRecord(str(i), "business check", status, None)
              for i, status in enumerate(statuses)]
    assert _checks_passed(checks) is expected


def test_business_assertion_failure_is_recorded_and_later_checks_continue():
    recorder = Recorder(SimpleNamespace(calls=[], current_check=""))
    with recorder.step("first", "failed business assertion") as check:
        check.must_eq("pending", "completed", "trade status")
    with recorder.step("second", "successful business assertion") as check:
        check.must_eq("completed", "completed", "trade status")

    assert recorder.counts() == {PASS: 1, FAIL: 1, SKIP: 0}
    assert "pending" in recorder.checks[0].error
    assert _checks_passed(recorder.checks) is False


def test_unexpected_check_exception_is_a_failure():
    recorder = Recorder(SimpleNamespace(calls=[], current_check=""))
    with recorder.step("broken", "unexpected failure"):
        raise ValueError("invalid business state")
    assert recorder.checks[0].status == FAIL
    assert recorder.checks[0].error == "ValueError: invalid business state"


def test_failure_diagnostics_keep_assertion_and_cleanup_errors():
    failed = CheckRecord("trade", "trade status", FAIL, None,
                         error="trade was still pending")
    log = _failure_log(
        run_id="test", exit_code=2, report=None, context=None,
        partial_checks=[failed.as_dict()], call_index={}, fatal=None,
        cleanup={"cleanup_failures": ["temporary storage removal failed"]},
    )
    assert "trade was still pending" in log
    assert "temporary storage removal failed" in log
