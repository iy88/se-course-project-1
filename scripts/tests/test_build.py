"""Regression checks for single-source generation and rendering contracts."""

import base64
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from doc_tools import report, markdown, diagrams
from doc_tools.report import specification
from doc_tools.markdown import relocate, expand_chapter
from doc_tools.diagrams import render, png_resolution, png_info, png_chunks


PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)



class BuildTests(unittest.TestCase):
    def test_canonical_change_reaches_chapter_and_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "docs/requirements"
            (directory / "details").mkdir(parents=True)
            detail = directory / "details/item.md"
            detail.write_text("# 关键内容\n\n状态：草稿。\n\n## 业务状态\n\n状态：待处理、已完成。\n\n唯一业务内容。\n")
            for number in range(1, 9):
                chapter = directory / f"{number:02}-章节.md"
                chapter.write_text(f"# {number}. 章节\n\n" + (
                    '<!-- spec-include: path="details/item.md" level="4" -->\n<!-- /spec-include -->\n'
                    if number == 1 else "章节内容。\n"
                ))
            specification(root)
            specification(root, check=True)
            output = directory.parent / "需求规格说明书.md"
            previous = output.read_bytes()
            specification(root)
            self.assertEqual(previous, output.read_bytes())
            self.assertIn("状态：待处理、已完成。", output.read_text())
            self.assertNotIn("spec-include:", output.read_text())
            detail.write_text(detail.read_text().replace("唯一业务内容", "更新的业务内容"))
            with self.assertRaises(ValueError):
                specification(root, check=True)
            specification(root)
            self.assertIn("更新的业务内容", output.read_text())

    def test_links_and_examples_are_relocated_correctly(self):
        source = Path("/project/docs/requirements/details/item.md")
        output = Path("/project/docs/requirements/report.md")
        text = "[规则](../rules.md#条件)\n`[样例](../fake.md)`\n```md\n[样例](../fake.md)\n```\n"
        actual = relocate(text, source, output)
        self.assertIn("[规则](rules.md#条件)", actual)
        self.assertEqual(actual.count("[样例](../fake.md)"), 2)
        chapters = {(source.parent / "../rules.md").resolve(): "chapter-04"}
        self.assertEqual(relocate("[规则](../rules.md)", source, output, chapters), "[规则](#chapter-04)")

    def test_include_path_cannot_escape_requirements(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "requirements").mkdir()
            (directory / "outside.md").write_text("# Outside\n")
            chapter = directory / "requirements/chapter.md"
            chapter.write_text('<!-- spec-include: path="../outside.md" level="4" --><!-- /spec-include -->')
            with self.assertRaises(ValueError):
                expand_chapter(chapter)

    def test_appendix_source_reaches_chapter(self):
        with tempfile.TemporaryDirectory() as temporary:
            docs = Path(temporary) / "docs"
            (docs / "requirements").mkdir(parents=True)
            (docs / "appendices/details").mkdir(parents=True)
            (docs / "appendices/details/item.md").write_text("# 关键材料\n\n业务说明。\n")
            chapter = docs / "requirements/chapter.md"
            chapter.write_text('<!-- spec-include: path="../appendices/details/item.md" level="4" --><!-- /spec-include -->')
            self.assertIn("#### 关键材料", expand_chapter(chapter))

    def test_index_is_linked_without_expansion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "draft-index.md").write_text("# 索引\n\n索引正文。\n")
            chapter = root / "chapter.md"
            chapter.write_text("# 正文\n\n完整材料见[索引](draft-index.md)。\n")
            self.assertEqual(expand_chapter(chapter), chapter.read_text())
            chapter.write_text('<!-- spec-include: path="draft-index.md" level="3" --><!-- /spec-include -->')
            with self.assertRaisesRegex(ValueError, "Index files must be linked"):
                expand_chapter(chapter)

    def test_acceptance_is_projected_from_scenario(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scene = root / "scene.md"
            scene.write_text("# SC-01 场景\n\n| SC-01-01 | 正常 | 已登录 | 提交 | 保存结果 | 新记录 | BR-01 |\n")
            chapter = root / "chapter.md"
            chapter.write_text('<!-- spec-include: path="scene.md" level="3" view="acceptance" --><!-- /spec-include -->')
            expanded = expand_chapter(chapter)
            self.assertIn("| SC-01-01 | 已登录；提交 | 保存结果 | BR-01 | |", expanded)
            scene.write_text(scene.read_text().replace("保存结果", "保留结果及时间"))
            self.assertIn("保留结果及时间", expand_chapter(chapter))

    def test_render_failure_preserves_existing_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            models = root / "docs/appendices/models"
            models.mkdir(parents=True)
            for name in ["A", "B"]:
                (models / f"{name}.puml").write_text("@startuml\nA -> B\n@enduml\n")
            old = root / "docs/appendices/rendered/A.png"
            old.parent.mkdir()
            old.write_bytes(PIXEL)
            results = [types.SimpleNamespace(returncode=0, stdout=PIXEL, stderr=b""),
                       types.SimpleNamespace(returncode=1, stdout=b"", stderr=b"syntax error")]
            with patch.object(diagrams.shutil, "which", return_value="plantuml"), patch.object(diagrams.subprocess, "run", side_effect=results):
                with self.assertRaises(ValueError):
                    render(root, 200, False, "plantuml", False)
            self.assertEqual(old.read_bytes(), PIXEL)
            self.assertFalse((old.parent / "B.png").exists())

    def test_dpi_is_recorded_without_resampling_pixels(self):
        data = png_resolution(PIXEL, 200)
        width, height, dpi = png_info(data)
        self.assertEqual((width, height), (1, 1))
        self.assertAlmostEqual(dpi, 200, places=1)
        original_pixels = [p for kind, p, _ in png_chunks(PIXEL) if kind == b"IDAT"]
        updated_pixels = [p for kind, p, _ in png_chunks(data) if kind == b"IDAT"]
        self.assertEqual(original_pixels, updated_pixels)


if __name__ == "__main__":
    unittest.main()
