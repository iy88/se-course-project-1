from pathlib import Path, PureWindowsPath
from unittest import TestCase
from unittest.mock import patch

from doc_tools.markdown import relocate


class WindowsMarkdownLinksTests(TestCase):
    def test_native_windows_relative_path_becomes_markdown_url(self):
        # Windows Path.as_posix is simulated on POSIX; relpath returns Windows syntax.
        source = Path('/tmp/design/source.md')
        destination = Path('/tmp/report.md')
        with patch('doc_tools.markdown.os.path.relpath', return_value=r'design\target.md'), \
             patch('doc_tools.markdown.Path', side_effect=PureWindowsPath):
            result = relocate('[目标](target.md#section)', source, destination)
        self.assertEqual(result, '[目标](design/target.md#section)')
