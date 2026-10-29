from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

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

class ExporterBase:
    """Shared exporter contract for the cooperating implementation mixins."""

    root: Path
    docs: Path
    output: Path
    pandoc: str
    pdf_engine: str
    header: Path
    cjk_main_font: str
    cjk_sans_font: str
    cjk_mono_font: str
    latin_main_font: str
    latin_mono_font: str
    margin: str
    fontsize: str
    landscape_tables: bool
    wide_table_columns: int
    jobs: int
    timeout: float
    pdf_link_check: str
    glyph_check: str
    _pandoc_ids: set[str]
    _font_preamble: str | None
    _font_paths: list[Path]

    def _resolve_tool(self, value: str) -> str:
        raise NotImplementedError

    def require_fonts(self) -> None:
        raise NotImplementedError

    def output_for_markdown(self, source: Path) -> Path:
        raise NotImplementedError

    def output_for_asset(self, source: Path) -> Path:
        raise NotImplementedError

    def pdf_command(self, output: Path, font_header: Path | None = None) -> list[str]:
        raise NotImplementedError

    def run_pandoc(self, command: list[str], *, data: bytes | None = None,
                   timeout: float | None = None) -> subprocess.CompletedProcess[bytes]:
        raise NotImplementedError

    def prepare_assets(self, plan: Plan) -> int:
        raise NotImplementedError

    def convert_document(self, source: Path, document: dict) -> Path:
        raise NotImplementedError

    def load_export_cache(self) -> dict:
        raise NotImplementedError

    def export_fingerprints(self, plan: Plan) -> dict:
        raise NotImplementedError

    def cache_entry_current(self, source: Path, fingerprint: dict, cache: dict) -> bool:
        raise NotImplementedError
