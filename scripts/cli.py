"""Unified CLI for document generation, diagrams, and PDF delivery."""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
import sys
from doc_tools import checks, diagrams, report
from doc_tools.pdf import commands as pdf

ROOT = Path(__file__).resolve().parents[1]

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in [("build", "render diagrams and generate the specification"),
                            ("report", "synchronize chapters and specification"),
                            ("render", "render diagrams"),
                            ("check", "check sources and generated documents without writing")]:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--dpi", type=int, default=200)
        command.add_argument("--plantuml", default="plantuml")
        command.add_argument("--force", action="store_true")
    commands.add_parser("pdf", help="incrementally export or check PDFs",
                        parents=[pdf.build_parser()], add_help=False)
    options = parser.parse_args(argv)
    if options.command == "pdf":
        return pdf.main(argv[1:])
    if not 72 <= options.dpi <= 600:
        parser.error("--dpi must be between 72 and 600")
    try:
        if options.command in {"build", "render", "check"}:
            diagrams.render(ROOT, options.dpi, options.command == "check",
                            options.plantuml, options.force)
        if options.command in {"build", "report", "check"}:
            report.specification(ROOT, options.command == "check")
            checks.check_repository(ROOT)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
