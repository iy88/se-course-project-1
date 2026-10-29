from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

from .common import INCLUDE, META, atomic_write, generated_markdown
from .markdown import expand_chapter, relocate, shift_headings, validate_links


def specification(root: Path, check: bool = False) -> None:
    directory = root / "docs/requirements"
    paths = []
    for number in range(1, 9):
        matches = list(directory.glob(f"{number:02}-*.md"))
        if len(matches) != 1:
            raise ValueError(f"Expected one chapter {number:02}, found {len(matches)}")
        paths.append(matches[0].resolve())
    output = (directory.parent / "需求规格说明书.md").resolve()
    expanded = {path: expand_chapter(path) for path in paths}
    # The baseline chapter lists source versions; actual file metadata is authoritative.
    baseline = paths[-1]
    rows = expanded[baseline].splitlines(keepends=True)
    for index, row in enumerate(rows):
        match = re.match(r"^(\| \[[^\]]+\]\(([^)]+)\) \| )([\d.]+)( \|.*)$", row.rstrip("\n"))
        if not match:
            continue
        target = (baseline.parent / unquote(match[2].split("#", 1)[0])).resolve()
        if target.is_file():
            version = re.search(r"^Version: ([\d.]+)$", target.read_text(), re.MULTILINE)
            if version:
                rows[index] = match[1] + version[1] + match[4] + "\n"
    expanded[baseline] = "".join(rows)
    anchors = {path: f"chapter-{index:02}" for index, path in enumerate(paths, 1)}
    titles = []
    for path in paths:
        title_match = re.search(r"^# (.+)$", expanded[path], re.MULTILINE)
        if title_match is None:
            raise ValueError(f"Missing chapter title: {path.name}")
        titles.append(title_match[1])
    body = "# 校园二手交易与物品流转平台需求规格说明书\n\n"
    body += "本说明书由第1—8章整合生成，纳入材料及源文件版本见第8章。\n\n## 目录\n\n"
    body += "\n".join(f"- [{title}](#chapter-{index:02})" for index, title in enumerate(titles, 1))
    for path in paths:
        chapter = META.sub("", expanded[path]).strip()
        chapter = re.sub(r"<!-- (?:spec-include:.*?|/spec-include) -->\n?", "", chapter)
        chapter = relocate(chapter, path, output, anchors)
        chapter = shift_headings(chapter + "\n", 1)
        body += f'\n\n<a id="{anchors[path]}"></a>\n\n' + chapter.strip()
    report = generated_markdown(output, body)
    overrides = {**expanded, output: report}
    errors = []
    for path, text in overrides.items():
        if re.search(r"^#{7,} ", text, re.MULTILINE):
            errors.append(f"{path.name}: heading deeper than H6")
        errors.extend(validate_links(path, text, overrides))
    if errors:
        raise ValueError("\n".join(errors))
    stale = [p for p, text in overrides.items() if not p.exists() or p.read_text() != text]
    if check and stale:
        raise ValueError("Regenerate specification: " + ", ".join(p.name for p in stale))
    if not check:
        for path, text in overrides.items():
            atomic_write(path, text.encode())
    print(f"Specification: 8 chapters, {sum(len(INCLUDE.findall(t)) for t in expanded.values())} key excerpts; {'current' if check else output}")
