"""Regression tests for the Markdown-to-PDF exporter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib

from doc_tools.pdf import exporter as export_pdf
from doc_tools.pdf import navigation


def _png_1x1() -> bytes:
    raw = b"\x00\xff\xff\xff\xff"

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data)))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


PNG = _png_1x1()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def walk_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_nodes(child)


def links(document: dict):
    return [node for node in walk_nodes(document) if node.get("t") == "Link"]


def codes(document: dict):
    return [node["c"][1] for node in walk_nodes(document)
            if node.get("t") == "CodeBlock"] + [
        node["c"][1] for node in walk_nodes(document) if node.get("t") == "Code"
    ]


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class Fixture:
    def __init__(self, temporary: str):
        self.root = Path(temporary).resolve()
        self.docs = self.root / "docs"
        self.requirements = write(
            self.docs / "requirements/b.md",
            "# B\n\n## Section\n\n## 4.1.6 单级分类标签\n\n内容。\n",
        )
        self.spaced = write(
            self.docs / "requirements/b c.md",
            "# Space\n\n## Space\n\n内容。\n",
        )
        self.rendered = self.docs / "appendices/rendered"
        self.rendered.mkdir(parents=True)
        (self.rendered / "pic.png").write_bytes(PNG)
        self.models = self.docs / "appendices/models"
        self.models.mkdir(parents=True)
        (self.models / "x.puml").write_text("@startuml\nA -> B\n@enduml\n")
        self.agents = write(
            self.root / "AGENTS.md",
            "# Rules\n\n[Notes](docs/requirements/notes.md#target)\n",
        )
        self.notes = write(
            self.docs / "requirements/notes.md",
            "# Notes\n\n## Target\n\n内容。\n",
        )
        (self.root / "bits").mkdir()
        write(self.root / "bits/unlinked.md", "# Unlinked\n\n不应导出。\n")
        self.source = write(
            self.docs / "requirements/a.md",
            "\n".join([
                "# A",
                "",
                "[inline](b.md#section \"title\")",
                "",
                "中文内容。",
                "",
                "状态转换：待审核 → 公开可交易。",
                "",
                "[github](<b.md#416-单级分类标签>)",
                "",
                "[ref][r]",
                "",
                "[frag](#a)",
                "",
                "[web](https://example.com/x.md#frag)",
                "",
                "[mail](mailto:a@b.c)",
                "",
                "[space](<b%20c.md#space>)",
                "",
                "[asset](../appendices/rendered/pic.png)",
                "",
                "[model](../appendices/models/x.puml)",
                "",
                "[outside](../../AGENTS.md#rules)",
                "",
                "![figure](../appendices/rendered/pic.png)",
                "",
                "`[code](x.md)`",
                "",
                "```",
                "[fenced](y.md)",
                "```",
                "",
                "[r]: b.md#section",
                "",
            ]),
        )
        self.exporter = export_pdf.PdfExporter(
            root=self.root, output=self.root / "docs-pdf",
            jobs=1, pdf_link_check="off",
        )

    def plan(self):
        return self.exporter.build_plan(self.exporter.discover_documents())


class ExportTests(unittest.TestCase):
    def test_pdf_anchor_is_stable_and_ascii(self):
        self.assertEqual(navigation.pdf_anchor("section"), "section")
        anchor = navigation.pdf_anchor("中文片段")
        self.assertTrue(anchor.isascii())
        self.assertEqual(anchor, navigation.pdf_anchor("中文片段"))
        self.assertNotEqual(anchor, navigation.pdf_anchor("另一片段"))
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = Fixture(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_inline_reference_fragment_external_and_code(self):
        plan = self.fixture.plan()
        source = self.fixture.source.resolve()
        document = plan.rewritten[source]
        records = {record.original: record for record in plan.records[source]}

        self.assertEqual(records["b.md#section"].rewritten, "b.pdf#section")
        self.assertEqual(records["b.md#section"].fragment, "section")
        anchor = navigation.pdf_anchor("416-单级分类标签")
        self.assertTrue(anchor.isascii())
        self.assertEqual(
            records["b.md#416-单级分类标签"].rewritten,
            f"b.pdf#{anchor}",
        )
        self.assertEqual(records["#a"].rewritten, "#a")
        self.assertEqual(
            records["https://example.com/x.md#frag"].rewritten,
            "https://example.com/x.md#frag",
        )
        self.assertEqual(records["mailto:a@b.c"].rewritten, "mailto:a@b.c")
        self.assertEqual(
            records["b%20c.md#space"].rewritten, "b c.pdf#space"
        )
        self.assertEqual(
            records["../appendices/rendered/pic.png"].rewritten,
            "../appendices/rendered/pic.png",
        )
        self.assertTrue(records["../../AGENTS.md#rules"].omitted)
        self.assertFalse(any(link["c"][2][0] == "../../AGENTS.md#rules"
                             for link in links(document)))

        latex = json.dumps(document)
        self.assertIn("ProjectPdfLink", latex)
        self.assertIn("FEFF" + "b.pdf".encode("utf-16-be").hex().upper(), latex)
        self.assertIn("inline", latex)

        self.assertIn("[code](x.md)", codes(document))
        self.assertIn("[fenced](y.md)", codes(document))
        self.assertNotIn("x.md", [record.original for record in records.values()])

        targets = plan.aliases[self.fixture.requirements.resolve()]
        self.assertIn("section", targets)
        self.assertIn("416-单级分类标签", targets)
        self.assertIn("单级分类标签", targets)

    def test_assets_and_repository_markdown(self):
        plan = self.fixture.plan()
        source = self.fixture.source.resolve()
        agents = self.fixture.agents.resolve()
        notes = self.fixture.notes.resolve()

        self.assertNotIn(agents, plan.documents)
        self.assertNotIn((self.fixture.root / "bits/unlinked.md").resolve(),
                         plan.documents)
        self.assertIn(self.fixture.rendered / "pic.png", plan.assets)
        self.assertIn(self.fixture.models / "x.puml", plan.assets)

        copied = self.fixture.exporter.prepare_assets(plan)
        self.assertGreaterEqual(copied, 2)
        self.assertEqual(
            (self.fixture.root / "docs-pdf/appendices/rendered/pic.png").read_bytes(),
            PNG,
        )
        self.assertEqual(
            (self.fixture.root / "docs-pdf/appendices/models/x.puml").read_bytes(),
            (self.fixture.models / "x.puml").read_bytes(),
        )
        with self.assertRaisesRegex(export_pdf.ExportError, "outside docs/"):
            self.fixture.exporter.output_for_markdown(agents)

    def test_raw_anchor_and_github_heading_alias(self):
        source = write(
            self.fixture.docs / "requirements/anchor.md",
            "\n".join([
                "# 目录",
                "",
                "- [第一章](#chapter-01)",
                "",
                '<a id="chapter-01"></a>',
                "",
                "# 1. 项目概述",
                "",
                "[自己](#1-项目概述)",
                "",
            ]),
        )
        plan = self.fixture.exporter.build_plan([source])
        aliases = plan.aliases[source.resolve()]
        self.assertIn("chapter-01", aliases)
        self.assertIn("1-项目概述", aliases)
        self.assertIn("项目概述", aliases)

        latex = json.dumps(plan.rewritten[source.resolve()], ensure_ascii=False)
        anchor = navigation.pdf_anchor("1-项目概述")
        self.assertIn("\\\\hypertarget{chapter-01}", latex)
        self.assertIn("\\\\label{chapter-01}", latex)
        self.assertIn(f"\\\\hypertarget{{{anchor}}}", latex)
        self.assertIn(f"\\\\label{{{anchor}}}", latex)
        self.assertIn(f"\\\\hyperlink{{{anchor}}}", latex)

    def test_wide_table_uses_landscape(self):
        source = write(
            self.fixture.docs / "requirements/wide.md",
            "| a | b | c | d | e | f | g |\n"
            "|---|---|---|---|---|---|---|\n"
            "| 1 | 2 | 3 | 4 | 5 | 6 | 7 |\n",
        )
        plan = self.fixture.exporter.build_plan([source])
        blocks = plan.rewritten[source.resolve()]["blocks"]
        self.assertIn({"t": "RawBlock", "c": ["latex", "\\begin{landscape}"]},
                      blocks)
        self.assertIn({"t": "RawBlock", "c": ["latex", "\\end{landscape}"]},
                      blocks)

    def test_invalid_fragment_and_missing_target_fail(self):
        source = write(
            self.fixture.docs / "requirements/bad.md",
            "[bad](b.md#does-not-exist)\n",
        )
        with self.assertRaisesRegex(export_pdf.ExportError, "fragment not found"):
            self.fixture.exporter.build_plan(
                self.fixture.exporter.discover_documents()
            )

        source.write_text("[missing](nope.md)\n", encoding="utf-8")
        with self.assertRaisesRegex(export_pdf.ExportError, "missing link target"):
            self.fixture.exporter.build_plan([source])

    def test_check_detects_missing_outputs(self):
        # Synthetic placeholder PDFs are not readable by pdftotext, so the
        # glyph scan is disabled for this output-existence test.
        self.fixture.exporter.glyph_check = "off"
        plan = self.fixture.plan()
        errors, stats = self.fixture.exporter.check(plan)
        self.assertEqual(stats["documents"], len(plan.documents))
        self.assertTrue(any("Missing output PDF" in error for error in errors))

        self.fixture.exporter.prepare_assets(plan)
        for source in plan.documents:
            output = self.fixture.exporter.output_for_markdown(source)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"%PDF-1.7\n% test\n")
        errors, _ = self.fixture.exporter.check(plan)
        self.assertEqual(errors, [])

        victim = self.fixture.exporter.output_for_markdown(plan.documents[0])
        victim.unlink()
        errors, _ = self.fixture.exporter.check(plan)
        self.assertTrue(any(str(victim) in error for error in errors))

    def test_failure_preserves_existing_output(self):
        plan = self.fixture.plan()
        source = self.fixture.source.resolve()
        destination = self.fixture.exporter.output_for_markdown(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"OLD")
        failure = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b"latex error"
        )
        self.fixture.exporter.require_fonts()
        with patch.object(export_pdf.subprocess, "run", return_value=failure):
            with self.assertRaisesRegex(export_pdf.ExportError, "PDF conversion failed"):
                self.fixture.exporter.convert_document(
                    source, plan.rewritten[source]
                )
        self.assertEqual(destination.read_bytes(), b"OLD")
        self.assertEqual(
            list(destination.parent.glob(".*.tmp-*")), []
        )

    def test_only_selects_one_document(self):
        selected = self.fixture.exporter.discover_documents(
            [str(self.fixture.source)]
        )
        self.assertEqual(selected, [self.fixture.source.resolve()])

    def test_input_markdown_is_not_modified(self):
        files = sorted(self.fixture.docs.rglob("*.md")) + [self.fixture.agents]
        before = {path: digest(path) for path in files}
        plan = self.fixture.plan()
        self.fixture.exporter.prepare_assets(plan)
        after = {path: digest(path) for path in files}
        self.assertEqual(before, after)

    def test_real_pdf_export_and_annotation_targets(self):
        if not (shutil.which("pandoc") and shutil.which("xelatex")):
            self.skipTest("Pandoc/XeLaTeX unavailable")
        self.fixture.exporter.pdf_link_check = "on" if shutil.which("qpdf") else "off"
        plan = self.fixture.plan()
        errors = self.fixture.exporter.export(plan)
        self.assertEqual(errors, [])

        source_pdf = self.fixture.root / "docs-pdf/requirements/a.pdf"
        target_pdf = self.fixture.root / "docs-pdf/requirements/b.pdf"
        self.assertTrue(source_pdf.is_file())
        self.assertTrue(target_pdf.is_file())
        self.assertEqual(source_pdf.read_bytes()[:5], b"%PDF-")

        errors, stats = self.fixture.exporter.check(plan)
        self.assertEqual(errors, [])
        self.assertEqual(stats["documents"], len(plan.documents))

        qpdf = shutil.which("qpdf")
        if qpdf:
            targets = navigation.pdf_file_targets(source_pdf, qpdf)
            normalized = {navigation.normalize_pdf_target(item)
                          for item in targets}
            self.assertIn("b.pdf", normalized)
            self.assertIn("../appendices/rendered/pic.png", normalized)
            self.assertFalse(any(item.endswith(".md") for item in normalized))

        pdfinfo = shutil.which("pdfinfo")
        if pdfinfo:
            destinations = subprocess.run(
                [pdfinfo, "-dests", str(target_pdf)],
                capture_output=True, text=True, timeout=30,
            ).stdout
            self.assertIn("section", destinations)
            self.assertIn(
                navigation.pdf_anchor("416-单级分类标签"), destinations
            )

        pdftotext = shutil.which("pdftotext")
        if pdftotext:
            text = subprocess.run(
                [pdftotext, str(source_pdf), "-"],
                capture_output=True, text=True, timeout=30,
            ).stdout
            self.assertIn("中文", text)
            # Arrows must resolve to a real glyph, not an empty box.
            self.assertIn("→", text)
            self.assertNotIn("\ufffd", text)
            self.assertEqual(navigation.pdf_replacement_glyphs(source_pdf), 0)

    def test_glyph_check_requires_pdftotext_when_enabled(self):
        exporter = self.fixture.exporter
        exporter.glyph_check = "on"
        with patch("doc_tools.pdf.exporter.shutil.which", return_value=None):
            errors, _ = exporter.check(self.fixture.plan())
        self.assertTrue(
            any("pdftotext is required" in error for error in errors)
        )

    def test_glyph_check_can_be_disabled(self):
        exporter = self.fixture.exporter
        exporter.glyph_check = "off"
        with patch("doc_tools.pdf.checks.pdf_replacement_glyphs") as glyphs:
            exporter.check(self.fixture.plan())
        glyphs.assert_not_called()

    def test_missing_pdftotext_skips_glyph_scan(self):
        with patch("doc_tools.pdf.exporter.shutil.which", return_value=None):
            self.assertIsNone(navigation.pdf_replacement_glyphs(Path("x.pdf")))


if __name__ == "__main__":
    unittest.main()
