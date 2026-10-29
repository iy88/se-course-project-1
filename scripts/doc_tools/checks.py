from __future__ import annotations

from pathlib import Path

from .markdown import validate_links


def check_repository(root: Path) -> None:
    errors = []
    excluded = {".git", "node_modules"}
    paths = [p for p in root.rglob("*.md") if excluded.isdisjoint(p.parts)]
    for path in paths:
        errors.extend(validate_links(path.resolve(), path.read_text(), {}))
    if errors:
        raise ValueError("\n".join(errors))
    print(f"Local Markdown links and anchors: {len(paths)} documents, current")
