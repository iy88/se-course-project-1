from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs"
DEFAULT_OUTPUT = ROOT / "docs-pdf"
HEADER = Path(__file__).resolve().parent / "header.tex"
URI_SAFE = "/-._~!$&'()*+,;=:@"
ANCHOR_ID = re.compile(r"^[\w.:-]+$", re.UNICODE)
HTML_ANCHOR_OPEN = re.compile(
    r"^\s*<a\b(?P<attrs>[^>]*)>\s*$", re.IGNORECASE | re.DOTALL
)
HTML_ANCHOR_CLOSE = re.compile(r"^\s*</a\s*>\s*$", re.IGNORECASE)
HTML_ANCHOR_ATTR = re.compile(
    r"\b(?:id|name)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.IGNORECASE
)
PDF_FILE_ACTION = re.compile(r"/F\s*(\((?:\\\\.|[^\\\\)])*\)|<[0-9A-Fa-f\s]+>)")
PDF_URI_ACTION = re.compile(r"/URI\s*(\((?:\\\\.|[^\\\\)])*\)|<[0-9A-Fa-f\s]+>)")

class ExportError(RuntimeError):
    """A deterministic export or validation failure."""

@dataclass
class LinkRecord:
    source: Path
    kind: str
    original: str
    rewritten: str
    target: Path | None
    destination: Path | None
    is_markdown: bool
    is_external: bool
    has_path: bool
    fragment: str
    query: str
    omitted: bool = False

@dataclass
class Plan:
    documents: list[Path]
    rewritten: dict[Path, dict]
    records: dict[Path, list[LinkRecord]]
    assets: dict[Path, Path]
    aliases: dict[Path, set[str]]
    output: Path
    source_hashes: dict[Path, str]

@dataclass
class TransformState:
    source: Path
    records: list[LinkRecord] = field(default_factory=list)
    assets: dict[Path, Path] = field(default_factory=dict)
    aliases: set[str] = field(default_factory=set)
    targets: set[str] = field(default_factory=set)
    slug_counts: dict[str, int] = field(default_factory=dict)
    header_targets: dict[int, str] = field(default_factory=dict)
