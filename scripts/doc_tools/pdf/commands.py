from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .exporter import PdfExporter
from .types import DEFAULT_OUTPUT, ROOT, ExportError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="extend", nargs="+", default=[],
                        metavar="PATH",
                        help="export only these Markdown files/directories")
    parser.add_argument("--force", action="store_true",
                        help="rebuild selected PDFs even when cached inputs match")
    parser.add_argument("--check", action="store_true",
                        help="validate outputs and rewritten links without writing")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help="output directory (default: docs-pdf)")
    parser.add_argument("--root", default=str(ROOT),
                        help="repository root (default: project root)")
    parser.add_argument("--pandoc", default="pandoc")
    parser.add_argument("--pdf-engine", default="xelatex")
    parser.add_argument("--cjk-main-font", default="PingFang SC")
    parser.add_argument("--cjk-sans-font", default="PingFang SC")
    parser.add_argument("--cjk-mono-font", default="PingFang SC")
    parser.add_argument("--latin-main-font", default="Times New Roman")
    parser.add_argument("--latin-mono-font", default="Fira Code")
    parser.add_argument("--margin", default="1.6cm")
    parser.add_argument("--fontsize", default="10pt")
    parser.add_argument("--wide-table-columns", type=int, default=6)
    parser.add_argument("--no-landscape-tables", action="store_true")
    parser.add_argument("--jobs", type=int, default=4,
                        help="parallel XeLaTeX conversions (default: 4)")
    parser.add_argument("--timeout", type=float, default=600.0,
                        help="seconds per conversion (default: 600)")
    parser.add_argument("--pdf-link-check", choices=["auto", "on", "off"],
                        default="auto",
                        help="inspect PDF link annotations with qpdf")
    parser.add_argument("--glyph-check", choices=["auto", "on", "off"],
                        default="auto",
                        help="detect characters rendered as missing glyphs (pdftotext)")
    return parser

def main(argv: Sequence[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    try:
        exporter = PdfExporter(
            root=Path(options.root),
            output=options.output,
            pandoc=options.pandoc,
            pdf_engine=options.pdf_engine,
            cjk_main_font=options.cjk_main_font,
            cjk_sans_font=options.cjk_sans_font,
            cjk_mono_font=options.cjk_mono_font,
            latin_main_font=options.latin_main_font,
            latin_mono_font=options.latin_mono_font,
            margin=options.margin,
            fontsize=options.fontsize,
            landscape_tables=not options.no_landscape_tables,
            wide_table_columns=options.wide_table_columns,
            jobs=options.jobs,
            timeout=options.timeout,
            pdf_link_check=options.pdf_link_check,
            glyph_check=options.glyph_check,
        )
        selected = exporter.discover_documents(options.only)
        if options.check:
            exporter.require_tools(exporting=False)
            plan = exporter.build_plan(selected)
            errors, stats = exporter.check(plan)
            summary = (
                f"Checked {stats['documents']} PDFs, {stats['assets']} assets, "
                f"{stats['local_markdown']} Markdown links, "
                f"{stats['local_assets']} asset links, "
                f"{stats['fragment_only']} fragment-only links, "
                f"{stats['external']} external URLs; "
                f"PDF annotations inspected: {stats['pdf_link_checked']}; "
                f"navigation actions checked: {stats['navigation_checked']}; "
                f"PDF texts scanned for missing glyphs: {stats['glyphs_checked']}"
            )
            if errors:
                print(summary)
                for error in errors:
                    print(f"ERROR: {error}", file=sys.stderr)
                return 1
            print(summary + "; OK")
            return 0

        exporter.require_tools(exporting=True)
        plan = exporter.build_plan(selected)
        print(
            (f"Plan: {len(plan.documents)} PDFs, {len(plan.assets)} assets, "
             f"{sum(len(items) for items in plan.records.values())} links"),
            flush=True,
        )
        errors = exporter.export(plan, force=options.force)
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        return 0
    except (ExportError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
