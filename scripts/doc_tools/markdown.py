from __future__ import annotations
import os
from pathlib import Path
import re
import unicodedata
from urllib.parse import unquote, urlsplit

from .common import INCLUDE, META, LINK

def map_prose(text: str, transform) -> str:
    """Leave fenced examples and inline code unchanged."""
    output = []
    fence = None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            output.append(line)
        elif fence:
            output.append(line)
        else:
            pieces = re.split(r"(`+[^`\n]*`+)", line)
            output.append("".join(
                piece if index % 2 else transform(piece)
                for index, piece in enumerate(pieces)
            ))
    return "".join(output)

def relocate(text: str, source: Path, destination: Path,
             chapters: dict[Path, str] | None = None) -> str:
    def replace(match):
        raw = match[2]
        url = raw[1:-1] if raw.startswith("<") else raw
        if re.match(r"^[a-zA-Z][\w+.-]*:", url):
            return match[0]
        parts = urlsplit(url)
        target = (source.parent / unquote(parts.path)).resolve() if parts.path else source.resolve()
        if chapters and target in chapters:
            updated = "#" + (unquote(parts.fragment) or chapters[target])
        elif not parts.path and source.resolve() == destination.resolve():
            return match[0]
        else:
            updated = os.path.relpath(target, destination.parent)
            if parts.query:
                updated += "?" + parts.query
            if parts.fragment:
                updated += "#" + parts.fragment
        if any(char.isspace() for char in updated):
            updated = "<" + updated + ">"
        return match[1] + updated + match[3]
    return map_prose(text, lambda part: LINK.sub(replace, part))

def shift_headings(text: str, amount: int) -> str:
    def change(part):
        return re.sub(r"^(#{1,6}) ", lambda m: "#" * (len(m[1]) + amount) + " ", part)
    return map_prose(text, change)

def expand_chapter(path: Path) -> str:
    def replace(match):
        relative, level, view = match[1], int(match[2]), match[3]
        source = (path.parent / relative).resolve()
        allowed = path.parent.resolve()
        if not (source.is_relative_to(allowed) or source.is_relative_to(allowed.parent / "appendices")) or not source.is_file():
            raise ValueError(f"Invalid include in {path.name}: {relative}")
        if source.name in {"index.md", "draft-index.md"}:
            raise ValueError(f"Index files must be linked, not included: {source}")
        body = META.sub("", source.read_text()).strip()
        if "spec-include:" in body:
            raise ValueError(f"Nested includes are not supported: {source}")
        # Child-document navigation and repeated draft labels are not report content.
        body = re.sub(r"(^# [^\n]+\n)\s*状态：[^\n]+\n*", r"\1\n", body, count=1)
        body = re.split(r"^## (?:关联材料|关联入口|验收与对应用户故事)\s*$", body, flags=re.M)[0].strip()
        if not re.match(r"^# [^\n]+", body):
            raise ValueError(f"Missing document title: {source}")
        if view == "acceptance":
            title = re.search(r"^# (.+)$", body, re.M)[1]
            rows = []
            for line in body.splitlines():
                if not re.match(r"^\| SC-\d+-\d+ \|", line):
                    continue
                cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
                if len(cells) != 7:
                    raise ValueError(f"Expected seven scenario columns: {source}")
                rows.append(f"| {cells[0]} | {cells[2]}；{cells[3]} | {cells[4]} | {cells[6]} | |")
            if not rows:
                raise ValueError(f"No scenario branches: {source}")
            body = (f"# {title}验收检查\n\n"
                    "| 场景 | 检查操作／情境 | 期望结果 | 依据 | 结论 |\n"
                    "|---|---|---|---|---|\n" + "\n".join(rows))
        body = shift_headings(body + "\n", level - 1).strip()
        body = relocate(body, source, path)
        return (
            f'<!-- spec-include: path="{relative}" level="{level}"'
            + (' view="acceptance"' if view else '') + ' -->\n'
            + body + f"\n\n[完整材料]({relative})。\n"
            + "<!-- /spec-include -->"
        )
    return INCLUDE.sub(replace, path.read_text())

def heading_ids(text: str) -> set[str]:
    clean = map_prose(text, lambda part: part)
    clean = re.sub(r"```.*?```|~~~.*?~~~", "", clean, flags=re.S)
    ids = set(re.findall(r'<a\s+(?:id|name)="([^"]+)"', clean))
    seen = {}
    for title in re.findall(r"^#{1,6}\s+(.+?)\s*#*$", clean, re.M):
        title = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", title)
        title = re.sub(r"<[^>]+>", "", title).lower()
        slug = "".join(c for c in title if unicodedata.category(c)[0] in "LN" or c in "_- ")
        slug = slug.replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        ids.add(slug + (f"-{count}" if count else ""))
    return ids

def validate_links(path: Path, text: str, overrides: dict[Path, str]) -> list[str]:
    errors = []
    def inspect(part):
        for match in LINK.finditer(part):
            raw = match[2]
            url = raw[1:-1] if raw.startswith("<") else raw
            if re.match(r"^[a-zA-Z][\w+.-]*:", url):
                continue
            if any(c.isspace() for c in url) and not raw.startswith("<"):
                errors.append(f"{path.name}: unescaped whitespace in {url}")
            parts = urlsplit(url)
            target = (path.parent / unquote(parts.path)).resolve() if parts.path else path.resolve()
            if target not in overrides and not target.exists():
                errors.append(f"{path.name}: missing {url}")
            elif parts.fragment and target.suffix == ".md":
                content = overrides.get(target)
                if content is None:
                    content = target.read_text()
                if unquote(parts.fragment) not in heading_ids(content):
                    errors.append(f"{path.name}: missing anchor {url}")
        return part
    map_prose(text, inspect)
    return errors
