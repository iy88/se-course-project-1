"""离线导出统一业务测试清单（coverage.json），不启动服务、不读取 .env。

命令::

    cd backend
    .venv/bin/python -m tests.acceptance_real.catalog --output tests/acceptance_real/coverage.json

输出供自动验收和浏览器人工清单共用；人工通道项单独标记 ``api_verified=false``。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tests.acceptance_real.core import BACKEND_ROOT, Catalog
from tests.acceptance_real.manifest import (
    CHECK_META,
    MANUAL_CHANNEL_ITEMS,
    SUBCASE_CHECKS,
)

DEFAULT_OUTPUT = BACKEND_ROOT / "tests" / "acceptance_real" / "coverage.json"
ACCEPTANCE_SOURCE = BACKEND_ROOT / "tests" / "acceptance_real" / "acceptance.py"


def _string_list(node: ast.AST | None) -> list[str]:
    if not isinstance(node, ast.List):
        return []
    return [str(element.value) for element in node.elts if isinstance(element, ast.Constant)]


def _extract_checks(path: Path = ACCEPTANCE_SOURCE) -> dict[str, dict[str, Any]]:
    """从真实测试入口抽取 check_id/title/ac/sc，不导入 app。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    checks: dict[str, dict[str, Any]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", "") != "step":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        check_id = str(node.args[0].value)
        title = str(node.args[1].value) if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else check_id
        ac: list[str] = []
        sc: list[str] = []
        for keyword in node.keywords:
            if keyword.arg == "ac":
                ac = _string_list(keyword.value)
            elif keyword.arg == "sc":
                sc = _string_list(keyword.value)
        if check_id in checks:
            raise ValueError(f"重复 check_id: {check_id}")
        checks[check_id] = {"check_id": check_id, "title": title, "ac": ac, "sc": sc}
    return checks


def _validate(catalog: Catalog, checks: Mapping[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if set(checks) != set(CHECK_META):
        missing = sorted(set(checks) - set(CHECK_META))
        extra = sorted(set(CHECK_META) - set(checks))
        if missing:
            errors.append("check 缺少清单元数据: " + ",".join(missing))
        if extra:
            errors.append("清单元数据无对应 check: " + ",".join(extra))
    if set(SUBCASE_CHECKS) != set(catalog.subuc_ids):
        missing = sorted(set(catalog.subuc_ids) - set(SUBCASE_CHECKS))
        extra = sorted(set(SUBCASE_CHECKS) - set(catalog.subuc_ids))
        if missing:
            errors.append("子用例未映射: " + ",".join(missing))
        if extra:
            errors.append("子用例映射不在源文档: " + ",".join(extra))
    known_ac = set(catalog.ac_ids)
    known_sc = set(catalog.sc_ids)
    known_uc = set(catalog.uc_ids)
    for check_id, check in checks.items():
        if any(item not in known_ac for item in check["ac"]):
            errors.append(f"{check_id} 引用未知 AC")
        if any(item not in known_sc for item in check["sc"]):
            errors.append(f"{check_id} 引用未知 SC")
    for sub_id, (mapped, _evidence) in SUBCASE_CHECKS.items():
        if not mapped:
            errors.append(f"{sub_id} 没有具体检查")
        for check_id in mapped:
            if check_id not in checks:
                errors.append(f"{sub_id} 引用不存在的 check {check_id}")
    mapped_ac = {item for check in checks.values() for item in check["ac"]}
    mapped_sc = {item for check in checks.values() for item in check["sc"]}
    if known_ac - mapped_ac:
        errors.append("AC 无检查映射: " + ",".join(sorted(known_ac - mapped_ac)))
    if known_sc - mapped_sc:
        errors.append("SC 无检查映射: " + ",".join(sorted(known_sc - mapped_sc)))
    for uc_id in catalog.uc_ids:
        if not any(sub_id.startswith(uc_id + "-") for sub_id in SUBCASE_CHECKS):
            errors.append(f"{uc_id} 没有子用例映射")
    for uc_id in known_uc:
        if uc_id not in catalog.uc_ids:
            errors.append(f"未知主用例 {uc_id}")
    return errors


def build_payload(catalog: Catalog | None = None, *, source: Path = ACCEPTANCE_SOURCE) -> dict[str, Any]:
    catalog = catalog or Catalog().load()
    checks = _extract_checks(source)
    errors = _validate(catalog, checks)
    reverse: dict[str, list[str]] = {check_id: [] for check_id in checks}
    for sub_id, (mapped, _evidence) in SUBCASE_CHECKS.items():
        for check_id in mapped:
            if check_id in reverse:
                reverse[check_id].append(sub_id)
    check_rows: list[dict[str, Any]] = []
    for check_id in sorted(checks, key=lambda value: list(checks).index(value)):
        check = checks[check_id]
        meta = CHECK_META.get(check_id)
        row = {
            "check_id": check_id,
            "title": check["title"],
            "channel": "api+real-resources",
            "role": meta.role if meta else "",
            "precondition": meta.precondition if meta else "",
            "action": meta.action if meta else "",
            "expected": meta.expected if meta else "",
            "ac": check["ac"],
            "sc": check["sc"],
            "uc_subcases": sorted(reverse.get(check_id, [])),
            "source_file": str(source.relative_to(BACKEND_ROOT.parent)),
        }
        check_rows.append(row)
    subcase_rows: list[dict[str, Any]] = []
    for sub_id in catalog.subuc_ids:
        mapped, evidence = SUBCASE_CHECKS.get(sub_id, ((), ""))
        item = catalog.items[sub_id]
        main_id = "-".join(sub_id.split("-")[:2])
        subcase_rows.append(
            {
                "id": sub_id,
                "main_uc": main_id,
                "title": item.title,
                "source_file": item.file,
                "source_text": item.text,
                "check_ids": list(mapped),
                "evidence": evidence,
                "mapping_status": "MAPPED" if mapped and all(check_id in checks for check_id in mapped) else "UNMAPPED",
            }
        )
    main_rows: list[dict[str, Any]] = []
    for main_id in catalog.uc_ids:
        item = catalog.items[main_id]
        subs = [row for row in subcase_rows if row["main_uc"] == main_id]
        main_rows.append(
            {
                "id": main_id,
                "title": item.title,
                "source_file": item.file,
                "subcase_count": len(subs),
                "subcases": [row["id"] for row in subs],
                "check_ids": sorted({check_id for row in subs for check_id in row["check_ids"]}),
                "mapping_status": "MAPPED" if subs and all(row["mapping_status"] == "MAPPED" for row in subs) else "UNMAPPED",
            }
        )
    ac_rows = [
        {
            "id": item_id,
            "kind": "AC",
            "title": catalog.items[item_id].title,
            "source_file": catalog.items[item_id].file,
            "text": catalog.items[item_id].text,
            "check_ids": sorted(check_id for check_id, check in checks.items() if item_id in check["ac"]),
        }
        for item_id in catalog.ac_ids
    ]
    sc_rows = [
        {
            "id": item_id,
            "kind": "SC",
            "title": catalog.items[item_id].title,
            "source_file": catalog.items[item_id].file,
            "text": catalog.items[item_id].text,
            "check_ids": sorted(check_id for check_id, check in checks.items() if item_id in check["sc"]),
        }
        for item_id in catalog.sc_ids
    ]
    return {
        "schema_version": 1,
        "generated_by": "tests.acceptance_real.catalog",
        "note": "MAPPED 仅表示静态清单有具体 check 与人工审查证据；运行结果以真实报告 PASS 为准。",
        "source": catalog.summary(),
        "validation": {"ok": not errors, "errors": errors},
        "summary": {
            "checks": len(check_rows),
            "ac": len(ac_rows),
            "sc": len(sc_rows),
            "uc_main": len(main_rows),
            "uc_subcases": len(subcase_rows),
            "manual_channel": len(MANUAL_CHANNEL_ITEMS),
        },
        "checks": check_rows,
        "ac": ac_rows,
        "sc": sc_rows,
        "uc": main_rows,
        "uc_subcases": subcase_rows,
        "manual_channel": list(MANUAL_CHANNEL_ITEMS),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出统一业务测试清单（不需要服务/.env）")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = parser.parse_args(argv)
    payload = build_payload()
    if not args.check:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"coverage: {output}")
    print(
        ("coverage: "
         f"checks={payload['summary']['checks']} "
         f"ac={payload['summary']['ac']} sc={payload['summary']['sc']} "
         f"uc={payload['summary']['uc_main']} subuc={payload['summary']['uc_subcases']} "
         f"manual={payload['summary']['manual_channel']} "
         f"valid={payload['validation']['ok']}")
    )
    for error in payload["validation"]["errors"]:
        print(f"coverage error: {error}", file=sys.stderr)
    return 0 if payload["validation"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
