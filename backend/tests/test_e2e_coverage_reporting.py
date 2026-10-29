"""coverage_check 纯工具单元测试（不访问服务、数据库或真实 .env）。

重点核对统计口径：
- 同一 AC 同时有 PASS 与 FAIL 时，FAIL 计执行、不计通过；
- “至少一条 PASS”与“有 PASS 且无 FAIL”分开统计，前者不能称为通过；
- 仅 SKIP 的 AC/SC 不计执行；
- 未直接登记但同 SC 有检查项时，只标“关联待补证”，不自动补齐 AC；
- 未出现编号分别列出。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "e2e_lifecycle" / "tools" / "coverage_check.py"
SPEC = importlib.util.spec_from_file_location("e2e_coverage_check", MODULE_PATH)
coverage_check = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(coverage_check)


def _coverage():
    return {
        "items": [
            {"us": "US-01", "ac": "US-01-AC-01", "sc": "SC-01-01", "type": "N"},
            {"us": "US-01", "ac": "US-01-AC-02", "sc": "SC-01-02", "type": "N"},
            {"us": "US-01", "ac": "US-01-AC-03", "sc": "SC-01-03", "type": "N"},
            {"us": "US-01", "ac": "US-01-AC-04", "sc": "SC-01-04", "type": "N"},
            {"us": "US-01", "ac": "US-01-AC-05", "sc": "SC-01-05", "type": "N"},
        ],
        "sc_branches": [
            {"sc": "SC-01-01", "category": "正常", "related": "US-01-AC-01"},
            {"sc": "SC-01-02", "category": "正常", "related": "US-01-AC-02"},
            {"sc": "SC-01-03", "category": "正常", "related": "US-01-AC-03"},
            {"sc": "SC-01-04", "category": "正常", "related": "US-01-AC-04"},
            {"sc": "SC-01-05", "category": "正常", "related": "US-01-AC-05"},
        ],
    }


def _results():
    return [
        # 同一 AC：PASS + FAIL，必须同时保留，且不能算“通过”。
        {"check_id": "US-01-AC-01_pass", "us": "US-01", "sc": "SC-01-01", "status": "PASS", "desc": "通过分支"},
        {"check_id": "US-01-AC-01_fail", "us": "US-01", "sc": "SC-01-01", "status": "FAIL", "desc": "失败分支"},
        # 仅 SKIP：不计执行。
        {"check_id": "US-01-AC-02_skip", "us": "US-01", "sc": "SC-01-02", "status": "SKIP", "desc": "跳过分支"},
        {"check_id": "P10-SC-01-02-support", "us": "US-01", "sc": "SC-01-02", "status": "PASS", "desc": "同 SC 支撑"},
        # AC-03 没有 AC 编号，只有同 SC 的检查项：关联待补证，不能算 AC 已执行。
        {"check_id": "P10-SC-01-03-support", "us": "US-01", "sc": "SC-01-03", "status": "PASS", "desc": "同 SC 支撑"},
        # SC-01-04 只有 SKIP，不能视为 SC 已执行。
        {"check_id": "P10-SC-01-04-skip", "us": "US-01", "sc": "SC-01-04", "status": "SKIP", "desc": "场景跳过"},
        # AC-05/SC-01-05 不出现。
    ]


def test_same_ac_pass_and_fail_is_executed_but_not_passed():
    data = coverage_check.collect(_results(), _coverage())
    summary = coverage_check.summarize(
        data["ac_expected"], data["ac_expected"], data["ac_direct"], data["ac_linked"]
    )
    assert "US-01-AC-01" in summary["executed"]
    assert "US-01-AC-01" in summary["fail"]
    assert "US-01-AC-01" in summary["pass_any"]
    assert "US-01-AC-01" not in summary["pass_no_fail"]
    assert summary["fail_count"] == 1
    assert summary["pass_any_count"] == 1
    assert summary["pass_no_fail_count"] == 0

    text = coverage_check.build_coverage_report(_results(), _coverage())
    assert "US-01-AC-01" in text
    assert "US-01-AC-01_pass` PASS" in text
    assert "US-01-AC-01_fail` FAIL" in text
    assert "全部通过" not in text


def test_skip_only_is_not_executed():
    data = coverage_check.collect(_results(), _coverage())
    summary = coverage_check.summarize(
        data["ac_expected"], data["ac_expected"], data["ac_direct"], data["ac_linked"]
    )
    sc_summary = coverage_check.summarize(
        data["sc_expected"], data["sc_expected"], data["sc_direct"], data["sc_linked"]
    )
    assert "US-01-AC-02" in summary["skip_only"]
    assert "US-01-AC-02" not in summary["executed"]
    assert "SC-01-04" in sc_summary["skip_only"]
    assert "SC-01-04" not in sc_summary["executed"]


def test_same_sc_different_ac_is_link_only():
    data = coverage_check.collect(_results(), _coverage())
    summary = coverage_check.summarize(
        data["ac_expected"], data["ac_expected"], data["ac_direct"], data["ac_linked"]
    )
    links = coverage_check.same_sc_links(summary, data)
    assert links == {"US-01-AC-03": ["SC-01-03"]}
    assert "US-01-AC-03" not in summary["executed"]
    assert "US-01-AC-03" not in summary["pass_any"]
    assert "US-01-AC-03" not in summary["pass_no_fail"]

    text = coverage_check.build_coverage_report(_results(), _coverage())
    assert "同 SC 关联待补证" in text
    assert "P10-SC-01-03-support` PASS" in text


def test_missing_ac_and_sc_are_listed_separately():
    data = coverage_check.collect(_results(), _coverage())
    summary = coverage_check.summarize(
        data["ac_expected"], data["ac_expected"], data["ac_direct"], data["ac_linked"]
    )
    sc_summary = coverage_check.summarize(
        data["sc_expected"], data["sc_expected"], data["sc_direct"], data["sc_linked"]
    )
    assert "US-01-AC-05" in summary["missing"]
    assert "SC-01-05" in sc_summary["missing"]
    text = coverage_check.build_coverage_report(_results(), _coverage())
    assert "1.1 未出现" in text and "2.1 未出现" in text
    assert "US-01-AC-05" in text and "SC-01-05" in text
