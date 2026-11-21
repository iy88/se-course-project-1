"""Assemble design documents from an explicit, ordered source manifest."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .common import META, atomic_write, generated_markdown
from .markdown import relocate, shift_headings, validate_links


def documents(root: Path, check: bool = False) -> None:
    directory = (root / "docs/design").resolve()
    manifest = json.loads((directory / "拼合清单.json").read_text(encoding="utf-8"))
    planned: dict[Path, str] = {}
    source_paths: set[Path] = set()
    identifiers: set[str] = set()
    for document in manifest["documents"]:
        identifier = document["id"]
        if not re.fullmatch(r"[a-z][a-z0-9-]*", identifier) or identifier in identifiers:
            raise ValueError(f"Invalid or duplicate design document id: {identifier}")
        identifiers.add(identifier)
        output = (directory.parent / document["output"]).resolve()
        if output.parent != directory.parent or output.suffix != ".md":
            raise ValueError(f"Invalid design output: {output}")
        if output.name == "软件架构设计方案_基线版.md":
            raise ValueError("The architecture baseline is maintained separately")
        if output.name not in {
            "软件架构设计方案_讨论稿.md", "架构确认与决策记录.md",
            "接口与关键设计说明书.md", "分阶段实现与测试计划.md",
        }:
            raise ValueError(f"Output is outside design deliverables: {output}")
        if output in planned:
            raise ValueError(f"Duplicate design output: {output}")
        paths = [(directory / name).resolve() for name in document["sources"]]
        if not paths or len(set(paths)) != len(paths):
            raise ValueError(f"Empty or duplicate source list: {identifier}")
        for path in paths:
            if not path.is_relative_to(directory) or not path.is_file() or path.suffix != ".md":
                raise ValueError(f"Invalid design source: {path}")
        source_paths.update(paths)
        anchors = {path: f"{identifier}-{index:02}" for index, path in enumerate(paths, 1)}
        chapters = []
        for path in paths:
            content = META.sub("", path.read_text(encoding="utf-8")).strip()
            title = re.search(r"^# (.+)$", content, re.MULTILINE)
            if title is None:
                raise ValueError(f"Missing design chapter title: {path}")
            chapters.append((path, title[1], content))
        body = f'# {document["title"]}\n\n'
        body += "本文按[拼合清单](design/拼合清单.json)整合章节源文件。\n\n"
        body += "[基线索引](design/基线索引.md)\n\n## 目录\n\n"
        body += "\n".join(f"- [{title}](#{anchors[path]})" for path, title, _ in chapters)
        for path, _, content in chapters:
            source = path.relative_to(directory.parent).as_posix()
            body += f'\n\n<a id="{anchors[path]}"></a>\n\n'
            body += shift_headings(relocate(content + "\n", path, output, anchors), 1).strip()
            body += f"\n\n[章节源文件]({source})"
        planned[output] = generated_markdown(output, body)
    errors = []
    for path in source_paths | planned.keys():
        content = planned[path] if path in planned else path.read_text(encoding="utf-8")
        if re.search(r"^#{7,} ", content, re.MULTILINE):
            errors.append(f"{path.name}: heading deeper than H6")
        errors.extend(validate_links(path, content, planned))
    if errors:
        raise ValueError("\n".join(errors))
    stale = [path for path, content in planned.items()
             if not path.exists() or path.read_text(encoding="utf-8") != content]
    if check and stale:
        raise ValueError("Regenerate design documents: " + ", ".join(p.name for p in stale))
    if not check:
        for path, content in planned.items():
            atomic_write(path, content.encode())
    print(f"Design documents: {len(planned)}, {'current' if check else 'generated'}")
