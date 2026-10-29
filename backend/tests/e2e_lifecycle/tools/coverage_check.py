"""覆盖核对：把真实运行结果与需求覆盖矩阵（coverage_expected.json）比对。

统计口径：
- “直接登记”指检查项编号字段（check_id）中出现预期 AC/SC 编号；
- “有关联记录”还包括检查项的 us/sc 字段指向该编号；
- 只有 PASS/FAIL 计入“已执行”，仅 SKIP 不计执行；
- FAIL 计执行但不计通过；
- “至少一条 PASS”只表示出现过 PASS，可与 FAIL 并存，不能称为通过；
  “有 PASS 且无 FAIL”是独立的检查项结果指标，仍不是完整 AC/SC 语义通过；
- 编号对应不等于完整验收条件语义验证，同 SC 的其他检查项只标“关联待补证”，
  不自动补齐 AC，也不把仅 SKIP 的 SC 视为已执行。

用法（在 backend/tests/e2e_lifecycle 下）：
  ../../.venv/bin/python tools/coverage_check.py \
      --results ../../../var/e2e-results/<runid>/results.json \
      --coverage coverage_expected.json \
      --out ../../../var/e2e-results/<runid>/coverage_check.md
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict

AC_RE = re.compile(r"US-\d{2}-AC-\d{2}")
SC_RE = re.compile(r"SC-\d{2}-\d{2}")
EXECUTED_STATUSES = ("PASS", "FAIL")


def normalize(text: str) -> str:
    text = text or ""
    text = re.sub(r"US(\d{2})", r"US-\1", text)
    text = re.sub(r"SC(\d{2})", r"SC-\1", text)
    return text


def _ids(pattern: re.Pattern[str], text: str) -> set[str]:
    return set(pattern.findall(normalize(text)))


def _status(row: dict) -> str:
    return str(row.get("status") or "").upper()


def _is_executed(row: dict) -> bool:
    return _status(row) in EXECUTED_STATUSES


def _escape(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _evidence(rows: list[dict], limit: int = 6) -> str:
    if not rows:
        return "无"
    ordered = sorted(rows, key=lambda row: (0 if _status(row) == "FAIL" else 1, row.get("check_id") or ""))
    shown = [
        f"`{_escape(row.get('check_id') or '')}` {_status(row) or 'UNKNOWN'}"
        for row in ordered[:limit]
    ]
    if len(ordered) > limit:
        shown.append(f"另 {len(ordered) - limit} 条")
    return "；".join(shown)


def _classify(rows: list[dict]) -> str:
    if not rows:
        return "missing"
    if not any(_is_executed(row) for row in rows):
        return "skip_only"
    if any(_status(row) == "FAIL" for row in rows):
        return "fail"
    if any(_status(row) == "PASS" for row in rows):
        return "pass_no_fail"
    return "unknown"


def collect(results: list[dict], coverage: dict) -> dict:
    """把结果按 AC/SC 分组；直接登记、字段关联与执行状态分开保存。"""
    ac_expected = {item["ac"]: item for item in coverage.get("items", [])}
    sc_expected = {item["sc"]: item for item in coverage.get("sc_branches", [])}

    ac_direct: dict[str, list[dict]] = defaultdict(list)
    ac_linked: dict[str, list[dict]] = defaultdict(list)
    sc_direct: dict[str, list[dict]] = defaultdict(list)
    sc_linked: dict[str, list[dict]] = defaultdict(list)
    unmapped: list[dict] = []

    for row in results:
        check_id = row.get("check_id") or ""
        direct_ac = _ids(AC_RE, check_id)
        direct_sc = _ids(SC_RE, check_id)
        field_ac = _ids(AC_RE, row.get("us") or "")
        field_sc = _ids(SC_RE, row.get("sc") or "")
        for identifier in direct_ac:
            ac_direct[identifier].append(row)
        for identifier in direct_ac | field_ac:
            ac_linked[identifier].append(row)
        for identifier in direct_sc:
            sc_direct[identifier].append(row)
        for identifier in direct_sc | field_sc:
            sc_linked[identifier].append(row)
        if not direct_ac and not field_ac:
            unmapped.append(row)

    return {
        "ac_expected": ac_expected,
        "sc_expected": sc_expected,
        "ac_direct": ac_direct,
        "ac_linked": ac_linked,
        "sc_direct": sc_direct,
        "sc_linked": sc_linked,
        "unmapped": unmapped,
    }


def summarize(ids, expected: dict, direct: dict, linked: dict) -> dict:
    """生成 id 级统计；PASS/FAIL 可同时存在，不把 FAIL 当通过。"""
    direct_ids = [identifier for identifier in ids if direct.get(identifier)]
    linked_ids = [identifier for identifier in ids if linked.get(identifier)]
    executed_ids = [
        identifier for identifier in ids
        if any(_is_executed(row) for row in linked.get(identifier, []))
    ]
    pass_any_ids = [
        identifier for identifier in ids
        if any(_status(row) == "PASS" for row in linked.get(identifier, []))
    ]
    fail_ids = [
        identifier for identifier in ids
        if any(_status(row) == "FAIL" for row in linked.get(identifier, []))
    ]
    fail_set = set(fail_ids)
    pass_no_fail_ids = [identifier for identifier in pass_any_ids if identifier not in fail_set]
    skip_only_ids = [
        identifier for identifier in ids
        if linked.get(identifier) and not any(_is_executed(row) for row in linked[identifier])
    ]
    missing_ids = [identifier for identifier in ids if not linked.get(identifier)]
    return {
        "total": len(expected),
        "direct": direct_ids,
        "linked_not_direct": [identifier for identifier in linked_ids if identifier not in direct],
        "executed": executed_ids,
        "pass_any": pass_any_ids,
        "pass_no_fail": pass_no_fail_ids,
        "fail": fail_ids,
        "skip_only": skip_only_ids,
        "missing": missing_ids,
        "direct_count": len(direct_ids),
        "executed_count": len(executed_ids),
        "pass_any_count": len(pass_any_ids),
        "pass_no_fail_count": len(pass_no_fail_ids),
        "fail_count": len(fail_ids),
        "skip_only_count": len(skip_only_ids),
        "missing_count": len(missing_ids),
    }


def same_sc_links(ac_summary: dict, data: dict) -> dict[str, list[str]]:
    """未直接出现在 AC 编号中的 AC，若同 SC 有检查项，仅登记为关联待补证。"""
    result: dict[str, list[str]] = {}
    accounted = set(data["ac_linked"])
    for ac, item in data["ac_expected"].items():
        if ac in accounted:
            continue
        sc_ids = _ids(SC_RE, str(item.get("sc") or ""))
        supporting = [
            sc for sc in sorted(sc_ids)
            if any(_is_executed(row) for row in data["sc_linked"].get(sc, []))
        ]
        if supporting:
            result[ac] = supporting
    return result


def _metric_lines(label: str, summary: dict, missing_label: str = "未出现该编号关联记录") -> list[str]:
    return [
        f"- 预期 {label}：**{summary['total']}** 条",
        f"- 检查项编号直接登记：**{summary['direct_count']}** 条"
        "（只从 `check_id` 提取编号，不代表语义已验证）",
        f"- 有非 SKIP 记录（已执行）：**{summary['executed_count']}** 条"
        "（只有 PASS/FAIL 计执行，FAIL 计执行但不计通过）",
        f"- 存在 PASS 记录（可与 FAIL 并存，不能称为通过）：**{summary['pass_any_count']}** 条；"
        f"有 FAIL：**{summary['fail_count']}** 条",
        f"- 有 PASS 且无 FAIL（仅检查项结果，不是完整验收条件语义通过）："
        f"**{summary['pass_no_fail_count']}** 条",
        f"- 仅 SKIP、未计执行：**{summary['skip_only_count']}** 条",
        f"- {missing_label}：**{summary['missing_count']}** 条",
    ]


def build_coverage_report(results: list[dict], coverage: dict,
                          results_path: str = "<results>", coverage_path: str = "<coverage>") -> str:
    """生成 Markdown 核对报告。返回文本，不写文件、不访问网络或数据库。"""
    data = collect(results, coverage)
    ac = summarize(data["ac_expected"], data["ac_expected"], data["ac_direct"], data["ac_linked"])
    sc = summarize(data["sc_expected"], data["sc_expected"], data["sc_direct"], data["sc_linked"])
    linked_by_sc = same_sc_links(ac, data)
    ac["missing"] = [identifier for identifier in ac["missing"] if identifier not in linked_by_sc]
    ac["missing_count"] = len(ac["missing"])

    lines: list[str] = []
    lines.append("# 覆盖核对：编号登记、执行结果与 AC 语义边界")
    lines.append("")
    lines.append(f"- 结果文件：`{results_path}`（{len(results)} 条检查项）")
    lines.append(
        f"- 覆盖矩阵：`{coverage_path}`（AC {len(data['ac_expected'])} 条、"
        f"SC 分支 {len(data['sc_expected'])} 条）"
    )
    lines.append("")
    lines.append("> 本报告只统计检查项编号与矩阵编号的对应，以及 PASS/FAIL/SKIP 的实际记录。")
    lines.append("> 编号出现不等于完整验收条件语义已验证；同 SC 的其他检查项不自动算作 AC 已覆盖；")
    lines.append("> 仅 SKIP 不计执行。不得把编号对应写成完整覆盖或验收结论。")
    lines.append("")

    lines.append("## 1. AC（用户故事验收条件）")
    lines.append("")
    lines.extend(_metric_lines("AC", ac, "未出现 AC 编号关联记录（同 SC 关联另计，见 1.5）"))
    lines.append(f"- 未直接登记但同 SC 有检查项、仅登记为关联待补证：**{len(linked_by_sc)}** 条")
    lines.append("")

    def section(title: str, identifiers: list[str], *, linked_sc: dict[str, list[str]] | None = None,
                include_sc: bool = True) -> None:
        lines.append(f"### {title}（{len(identifiers)}）")
        lines.append("")
        if not identifiers:
            lines.append("无。")
            lines.append("")
            return
        headers = ["AC", "US", "矩阵 SC", "证据（check_id／状态）"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for identifier in identifiers:
            item = data["ac_expected"][identifier]
            rows = data["ac_linked"].get(identifier, [])
            if linked_sc and identifier in linked_sc:
                evidence = "同 SC 关联待补证：" + "、".join(
                    f"{sc}（{_evidence(data['sc_linked'].get(sc, []))}）" for sc in linked_sc[identifier]
                )
            else:
                evidence = _evidence(rows)
            lines.append(
                "| " + " | ".join(
                    _escape(value) for value in (
                        identifier,
                        item.get("us") or "",
                        item.get("sc") or "",
                        evidence,
                    )
                ) + " |"
            )
        lines.append("")

    ac_unknown = [
        identifier for identifier in data["ac_expected"]
        if _classify(data["ac_linked"].get(identifier, [])) == "unknown"
    ]
    section("1.1 未出现（无 AC 编号记录；同 SC 关联见 1.5）", ac["missing"])
    section("1.2 仅 SKIP（未计执行）", ac["skip_only"])
    section("1.3 有 FAIL（FAIL 计执行，不计通过）", ac["fail"])
    section("1.4 有 PASS 且无 FAIL（仅检查项结果，非完整 AC 语义通过）",
            ac["pass_no_fail"])
    section("1.5 同 SC 有检查项但 AC 编号未直接登记（关联待补证）",
            sorted(linked_by_sc), linked_sc=linked_by_sc)
    if ac_unknown:
        section("1.6 状态异常（未计入执行）", ac_unknown)
    lines.append("")

    lines.append("## 2. SC（场景分支）")
    lines.append("")
    lines.extend(_metric_lines("SC 分支", sc))
    lines.append("")

    def sc_section(title: str, identifiers: list[str]) -> None:
        lines.append(f"### {title}（{len(identifiers)}）")
        lines.append("")
        if not identifiers:
            lines.append("无。")
            lines.append("")
            return
        headers = ["SC", "类别", "关联 AC", "证据（check_id／状态）"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for identifier in identifiers:
            item = data["sc_expected"][identifier]
            lines.append(
                "| " + " | ".join(
                    _escape(value) for value in (
                        identifier,
                        item.get("category") or "",
                        item.get("related") or "",
                        _evidence(data["sc_linked"].get(identifier, [])),
                    )
                ) + " |"
            )
        lines.append("")

    sc_unknown = [
        identifier for identifier in data["sc_expected"]
        if _classify(data["sc_linked"].get(identifier, [])) == "unknown"
    ]
    sc_section("2.1 未出现（无任何关联检查项）", sc["missing"])
    sc_section("2.2 仅 SKIP（未计执行）", sc["skip_only"])
    sc_section("2.3 有 FAIL（FAIL 计执行，不计通过）", sc["fail"])
    sc_section("2.4 有 PASS 且无 FAIL（仅检查项结果，非完整 SC 分支语义通过）",
               sc["pass_no_fail"])
    if sc_unknown:
        sc_section("2.5 状态异常（未计入执行）", sc_unknown)
    lines.append("")

    lines.append("## 3. 未映射到 US/AC 的检查项")
    lines.append("")
    if data["unmapped"]:
        lines.append(f"共 **{len(data['unmapped'])}** 条（多为可靠性/统计/边界检查项，仍需在报告中人工归类）：")
        lines.append("")
        for row in data["unmapped"]:
            lines.append(f"- `{row.get('check_id')}` {row.get('desc')}（{_status(row) or 'UNKNOWN'}）")
    else:
        lines.append("无。")
    lines.append("")
    return "\n".join(lines)


def write_or_print(text: str, out: str | None) -> None:
    if out:
        with open(out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print("written", out)
    else:
        print(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="核对运行结果与 US-AC/SC 覆盖矩阵的编号对应及执行状态")
    parser.add_argument("--results", required=True)
    parser.add_argument("--coverage", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    with open(args.results, encoding="utf-8") as handle:
        results = json.load(handle)["results"]
    with open(args.coverage, encoding="utf-8") as handle:
        coverage = json.load(handle)

    data = collect(results, coverage)
    ac = summarize(data["ac_expected"], data["ac_expected"], data["ac_direct"], data["ac_linked"])
    sc = summarize(data["sc_expected"], data["sc_expected"], data["sc_direct"], data["sc_linked"])
    text = build_coverage_report(results, coverage, args.results, args.coverage)
    write_or_print(text, args.out)
    print(
        f"\nAC 直接登记 {ac['direct_count']}/{ac['total']}；AC 有非SKIP记录 {ac['executed_count']}；"
        f"AC 仅SKIP {ac['skip_only_count']}；AC 未出现 {ac['missing_count']}；AC 有FAIL {ac['fail_count']}；"
        f"AC 有PASS且无FAIL {ac['pass_no_fail_count']}；"
        f"SC 直接登记 {sc['direct_count']}/{sc['total']}；SC 有非SKIP记录 {sc['executed_count']}；"
        f"SC 仅SKIP {sc['skip_only_count']}；SC 未出现 {sc['missing_count']}；SC 有FAIL {sc['fail_count']}；"
        f"SC 有PASS且无FAIL {sc['pass_no_fail_count']}；"
        f"未映射检查项 {len(data['unmapped'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
