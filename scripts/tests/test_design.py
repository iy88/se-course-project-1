from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from doc_tools.design import documents


class DesignDocumentsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.base = self.root / "docs/design"
        (self.base / "architecture").mkdir(parents=True)
        (self.base / "基线索引.md").write_text("# 入口\n")
        (self.base / "asset.txt").write_text("evidence\n")
        self.source = self.base / "architecture/01.md"
        self.source.write_text("# 架构\n\n[附件](../asset.txt)\n\n## 场景\n\n待讨论。\n")
        self.manifest = {"documents": [{"id": "architecture", "title": "讨论稿",
            "output": "软件架构设计方案_讨论稿.md", "sources": ["architecture/01.md"]}]}
        self.output = self.root / "docs/软件架构设计方案_讨论稿.md"

    def run_documents(self, check=False):
        (self.base / "拼合清单.json").write_text(json.dumps(self.manifest))
        with redirect_stdout(StringIO()):
            documents(self.root, check)

    def test_relocation_stability_and_read_only_staleness_check(self):
        self.run_documents()
        original = self.output.read_bytes()
        self.assertIn("[附件](design/asset.txt)", original.decode())
        self.assertIn("## 架构", original.decode())
        self.run_documents()
        self.assertEqual(original, self.output.read_bytes())
        self.run_documents(check=True)
        self.source.write_text(self.source.read_text() + "\n补充。\n")
        with self.assertRaisesRegex(ValueError, "Regenerate"):
            self.run_documents(check=True)
        self.assertEqual(original, self.output.read_bytes())

    def test_invalid_source_does_not_publish_partial_output(self):
        self.manifest["documents"].append({"id": "plan", "title": "计划",
            "output": "分阶段实现与测试计划.md", "sources": ["../requirements/01.md"]})
        with self.assertRaisesRegex(ValueError, "Invalid design source"):
            self.run_documents()
        self.assertFalse(self.output.exists())

    def test_requirement_and_baseline_outputs_are_protected(self):
        for name in ("需求规格说明书.md", "软件架构设计方案_基线版.md"):
            with self.subTest(name=name):
                self.manifest["documents"][0]["output"] = name
                with self.assertRaises(ValueError):
                    self.run_documents()
                self.assertFalse((self.root / "docs" / name).exists())


if __name__ == "__main__":
    unittest.main()
