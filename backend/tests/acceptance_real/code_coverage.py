"""Measure application code in the acceptance driver and real API subprocess.

只保留 coverage 原生产物（HTML/JSON/XML/TXT 与 .coverage 数据文件），不写自定义摘要。
"""
from __future__ import annotations

import io
import json
import secrets
from pathlib import Path
from typing import Any

from app.core.private_files import protect_private
from coverage import Coverage, CoverageData

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = BACKEND_ROOT.parent / "var" / "acceptance-real" / "code-coverage"


class CodeCoverage:
    def __init__(self) -> None:
        self.root = REPORT_ROOT / secrets.token_hex(16)
        self.root.mkdir(parents=True, mode=0o700)
        protect_private(self.root, directory=True)
        self.config = BACKEND_ROOT / "pyproject.toml"
        self.source = BACKEND_ROOT / "app"
        self.server_data = self.root / ".coverage.server"
        self.parent = Coverage(
            config_file=str(self.config), source=[str(self.source)],
            data_file=str(self.root / ".coverage.runner"), context="acceptance-runner",
        )
        self.parent.start()

    def server_command(self, arguments: list[str]) -> list[str]:
        """Arguments start with the server module name, after Python's -m."""
        return [
            "coverage", "run", f"--rcfile={self.config}", f"--source={self.source}",
            f"--data-file={self.server_data}", "--context=api-server", "-m", *arguments,
        ]

    def finish(self, *, server_started: bool, acceptance_exit_code: int) -> dict[str, Any]:
        self.parent.stop()
        self.parent.save()
        server_verified = False
        if server_started:
            if not self.server_data.is_file():
                raise RuntimeError("API subprocess coverage data is missing")
            data = CoverageData(basename=str(self.server_data))
            data.read()
            api_files = [name for name in data.measured_files() if "/app/api/v1/" in name.replace("\\", "/")]
            server_verified = bool(data.lines(str(self.source / "main.py"))) and any(data.lines(name) for name in api_files)
            if not server_verified or not data.has_arcs():
                raise RuntimeError("API subprocess did not measure application lines and branches")
        combined = Coverage(
            config_file=str(self.config), source=[str(self.source)],
            data_file=str(self.root / ".coverage"),
        )
        combined.combine(data_paths=[str(self.root)], strict=True, keep=True)
        combined.save()
        combined.json_report(outfile=str(self.root / "coverage.json"))
        combined.xml_report(outfile=str(self.root / "coverage.xml"))
        combined.html_report(directory=str(self.root / "html"))
        table = io.StringIO()
        combined.report(file=table)
        (self.root / "coverage.txt").write_text(table.getvalue(), encoding="utf-8")
        payload = json.loads((self.root / "coverage.json").read_text(encoding="utf-8"))
        total = payload["totals"]
        statements, branches = total["num_statements"], total["num_branches"]
        summary = {
            "acceptance_exit_code": acceptance_exit_code,
            "complete_acceptance": acceptance_exit_code == 0,
            "scope": "backend/app/**/*.py (all application modules, including unexecuted files)",
            "processes": ["acceptance-runner", "api-server"] if server_started else ["acceptance-runner"],
            "api_subprocess_verified": server_verified,
            "covered_lines": total["covered_lines"], "total_lines": statements,
            "line_percent": round(100 * total["covered_lines"] / statements, 2) if statements else 100.0,
            "covered_branches": total["covered_branches"], "total_branches": branches,
            "branch_percent": round(100 * total["covered_branches"] / branches, 2) if branches else 100.0,
            "combined_percent": round(total["percent_covered"], 2),
            "artifacts": {name: str(self.root / path) for name, path in {
                "html": "html/index.html", "json": "coverage.json", "xml": "coverage.xml",
                "text": "coverage.txt", "data": ".coverage",
            }.items()},
        }
        return summary
