"""检查项记录器：把每个 US/AC/SC 检查项映射为 PASS / FAIL / SKIP，并收集缺陷候选。"""

from __future__ import annotations

import contextlib
import traceback


class Recorder:
    def __init__(self, phase_id: str, phase_title: str):
        self.phase_id = phase_id
        self.phase_title = phase_title
        self.results: list[dict] = []
        self.defects: list[dict] = []
        self._current: dict | None = None

    # -- 检查项 -----------------------------------------------------------
    @contextlib.contextmanager
    def step(self, check_id: str, *, us: str = "", sc: str = "", desc: str = "", expected: str = ""):
        """检查项上下文：正常退出记 PASS，任一异常记 FAIL，不中断本阶段后续检查项。

        except 中不应吞掉异常；调用方使用 must()/assert_* 触发失败。
        """
        self._current = {
            "phase": self.phase_id,
            "check_id": check_id,
            "us": us,
            "sc": sc,
            "desc": desc,
            "expected": expected,
            "status": "PASS",
            "detail": "",
            "actual": None,
        }
        try:
            yield self._current
        except Exception as exc:  # noqa: BLE001 - 检查框架需要承接全部断言异常
            self._current["status"] = "FAIL"
            if hasattr(exc, "body") and getattr(exc, "body", ""):
                self._current["actual"] = {
                    "status_code": getattr(exc, "status_code", None),
                    "body": getattr(exc, "body", "")[:1500],
                }
            self._current["detail"] = f"{type(exc).__name__}: {exc}"[:2000]
            if not hasattr(exc, "body"):
                self._current["detail"] += "\n" + "".join(traceback.format_exception_only(type(exc), exc))[-1000:]
        finally:
            self.results.append(self._current)
            self._current = None

    def pass_(self, check_id: str, *, us: str = "", sc: str = "", desc: str = "", expected: str = "", detail: str = "", actual=None):
        self.results.append(
            {
                "phase": self.phase_id,
                "check_id": check_id,
                "us": us,
                "sc": sc,
                "desc": desc,
                "expected": expected,
                "status": "PASS",
                "detail": detail,
                "actual": actual,
            }
        )

    def fail(self, check_id: str, *, us: str = "", sc: str = "", desc: str = "", expected: str = "", detail: str = "", actual=None):
        self.results.append(
            {
                "phase": self.phase_id,
                "check_id": check_id,
                "us": us,
                "sc": sc,
                "desc": desc,
                "expected": expected,
                "status": "FAIL",
                "detail": detail,
                "actual": actual,
            }
        )

    def skip(self, check_id: str, *, us: str = "", sc: str = "", desc: str = "", reason: str = ""):
        self.results.append(
            {
                "phase": self.phase_id,
                "check_id": check_id,
                "us": us,
                "sc": sc,
                "desc": desc,
                "expected": "",
                "status": "SKIP",
                "detail": reason,
                "actual": None,
            }
        )

    # -- 断言辅助 ---------------------------------------------------------
    @staticmethod
    def must(condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(message)

    @staticmethod
    def must_eq(actual, expected, label: str) -> None:
        if actual != expected:
            raise AssertionError(f"{label}：期望 {expected!r}，实际 {actual!r}")

    @staticmethod
    def must_in(value, allowed, label: str) -> None:
        if value not in allowed:
            raise AssertionError(f"{label}：期望属于 {allowed!r}，实际 {value!r}")

    def defect(self, kind: str, detail: dict) -> None:
        self.defects.append({"phase": self.phase_id, "kind": kind, **detail})

    def phase_aborted(self, phase_id: str, exc: BaseException) -> None:
        self.defects.append(
            {
                "phase": phase_id,
                "kind": "phase_aborted",
                "detail": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-3000:],
            }
        )

    # -- 汇总 -------------------------------------------------------------
    def counts(self) -> dict[str, int]:
        out = {"PASS": 0, "FAIL": 0, "SKIP": 0}
        for r in self.results:
            out[r["status"]] = out.get(r["status"], 0) + 1
        return out
