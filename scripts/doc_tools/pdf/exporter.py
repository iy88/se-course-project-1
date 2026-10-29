from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import unquote

from .cache import IncrementalExport
from .checks import OutputChecks
from .fonts import FontSupport
from .navigation import _hash_file
from .transform import DocumentTransform
from .types import (
    DEFAULT_OUTPUT,
    HEADER,
    ROOT,
    ExportError,
    LinkRecord,
    Plan,
    TransformState,
)


class PdfExporter(FontSupport, DocumentTransform, IncrementalExport, OutputChecks):

    def __init__(
        self,
        root: Path = ROOT,
        output: Path | str = DEFAULT_OUTPUT,
        *,
        pandoc: str = "pandoc",
        pdf_engine: str = "xelatex",
        header: Path = HEADER,
        cjk_main_font: str = "PingFang SC",
        cjk_sans_font: str = "PingFang SC",
        cjk_mono_font: str = "PingFang SC",
        latin_main_font: str = "Times New Roman",
        latin_mono_font: str = "Fira Code",
        margin: str = "1.6cm",
        fontsize: str = "10pt",
        landscape_tables: bool = True,
        wide_table_columns: int = 6,
        jobs: int = 4,
        timeout: float = 600.0,
        pdf_link_check: str = "auto",
        glyph_check: str = "auto",
    ) -> None:
        self.root = Path(root).resolve()
        self.docs = self.root / "docs"
        self.output = Path(output)
        if not self.output.is_absolute():
            self.output = (self.root / self.output).resolve()
        else:
            self.output = self.output.resolve()
        if self.output == self.docs or self.output.is_relative_to(self.docs):
            raise ExportError("Output directory must be outside docs/")
        self.pandoc = pandoc
        self.pdf_engine = pdf_engine
        self.header = Path(header).resolve()
        self.cjk_main_font = cjk_main_font
        self.cjk_sans_font = cjk_sans_font
        self.cjk_mono_font = cjk_mono_font
        self.latin_main_font = latin_main_font
        self.latin_mono_font = latin_mono_font
        self.margin = margin
        self.fontsize = fontsize
        self.landscape_tables = landscape_tables
        self.wide_table_columns = wide_table_columns
        self.jobs = max(1, int(jobs))
        self.timeout = float(timeout)
        self.pdf_link_check = pdf_link_check
        self.glyph_check = glyph_check
        self._pandoc_ids: set[str] = set()
        self._font_preamble: str | None = None


    def discover_documents(self, only: Sequence[str] = ()) -> list[Path]:
        if only:
            paths: list[Path] = []
            for item in only:
                path = Path(item)
                if not path.is_absolute():
                    path = self.root / path
                path = path.resolve()
                if not path.is_relative_to(self.docs):
                    raise ExportError(f"Selected path is outside docs/: {item}")
                if path.is_dir():
                    paths.extend(sorted(
                        child for child in path.rglob("*")
                        if child.is_file() and child.suffix.lower() == ".md"
                    ))
                elif path.is_file() and path.suffix.lower() == ".md":
                    paths.append(path)
                else:
                    raise ExportError(f"Not a Markdown file or directory: {item}")
        else:
            paths = sorted(
                path for path in self.docs.rglob("*")
                if path.is_file() and path.suffix.lower() == ".md"
            )
        unique = {path.resolve() for path in paths}
        documents = sorted(unique)
        if not documents:
            raise ExportError("No Markdown documents selected")
        return documents


    def output_for_markdown(self, source: Path) -> Path:
        source = source.resolve()
        if source.is_relative_to(self.docs):
            return self.output / source.relative_to(self.docs).with_suffix(".pdf")
        raise ExportError(f"Markdown outside docs/: {source}")


    def output_for_asset(self, source: Path) -> Path:
        source = source.resolve()
        if source.is_relative_to(self.docs):
            return self.output / source.relative_to(self.docs)
        raise ExportError(f"Asset outside docs/: {source}")


    def run_pandoc(self, command: list[str], *, data: bytes | None = None,
                   timeout: float | None = None) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                command, input=data, capture_output=True, check=False,
                timeout=self.timeout if timeout is None else timeout,
            )
        except FileNotFoundError as error:
            raise ExportError(f"Executable not found: {command[0]}") from error
        except subprocess.TimeoutExpired as error:
            raise ExportError(
                f"Timed out after {self.timeout if timeout is None else timeout}s: "
                f"{' '.join(command[:3])}"
            ) from error


    def parse_markdown(self, source: Path) -> dict:
        result = self.run_pandoc(
            [self.pandoc, "-f", "markdown", "-t", "json", str(source)],
            timeout=min(self.timeout, 180.0),
        )
        if result.returncode:
            raise ExportError(
                f"{source}: Pandoc could not parse Markdown\n"
                + result.stderr.decode(errors="replace")[-3000:]
            )
        try:
            document = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise ExportError(f"{source}: Pandoc returned invalid JSON") from error
        if not isinstance(document, dict) or "blocks" not in document:
            raise ExportError(f"{source}: Pandoc JSON is not a document")
        return document


    def build_plan(self, selected: Sequence[Path]) -> Plan:
        queue = sorted({path.resolve() for path in selected})
        if any(not path.is_relative_to(self.docs) for path in queue):
            raise ExportError("All selected Markdown must be inside docs/")
        seen: set[Path] = set()
        order: list[Path] = []
        rewritten: dict[Path, dict] = {}
        records: dict[Path, list[LinkRecord]] = {}
        assets: dict[Path, Path] = {}
        aliases: dict[Path, set[str]] = {}
        source_hashes = {}

        for source in queue:
            if source in seen:
                continue
            seen.add(source)
            order.append(source)
            source_hashes[source] = _hash_file(source)
            document = self.parse_markdown(source)
            if _hash_file(source) != source_hashes[source]:
                raise ExportError(f"Source changed while parsing: {source}")
            self._pandoc_ids = self._collect_pandoc_ids(document)
            state = TransformState(source=source)
            transformed = self._transform(document, state)
            if isinstance(transformed, dict) and isinstance(transformed.get("blocks"), list):
                transformed = self._insert_header_targets(
                    transformed, state.header_targets
                )
            if not isinstance(transformed, dict):
                raise ExportError(f"{source}: Pandoc document transformation failed")
            blocks = transformed.get("blocks")
            if isinstance(blocks, list):
                transformed["blocks"] = self._wrap_wide_tables(blocks)
            rewritten[source] = transformed
            records[source] = state.records
            aliases[source] = state.aliases
            assets.update(state.assets)

        plan = Plan(
            documents=sorted(order),
            rewritten=rewritten,
            records=records,
            assets=assets,
            aliases=aliases,
            output=self.output,
            source_hashes=source_hashes,
        )
        self._validate_fragments(plan)
        return plan


    def _validate_fragments(self, plan: Plan) -> None:
        errors = []
        for source, records in plan.records.items():
            for record in records:
                if record.omitted or record.is_external or not record.fragment:
                    continue
                if not (record.is_markdown or not record.has_path):
                    continue
                target = record.target if record.has_path else source
                if target is None:
                    continue
                target = target.resolve()
                if target not in plan.aliases:
                    continue
                fragment = unquote(record.fragment)
                if fragment not in plan.aliases[target]:
                    errors.append(
                        f"{source}: fragment not found in {target}: #{record.fragment}"
                    )
        if errors:
            raise ExportError("\n".join(errors))


    def prepare_assets(self, plan: Plan) -> int:
        copied = 0
        for source, destination in sorted(plan.assets.items()):
            if not source.is_file():
                raise ExportError(f"Missing asset: {source}")
            try:
                if (destination.is_file()
                        and _hash_file(source) == _hash_file(destination)):
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(
                    f".{destination.name}.tmp-{os.getpid()}-{time.time_ns()}"
                )
                try:
                    shutil.copy2(source, temporary)
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)
            except OSError as error:
                raise ExportError(
                    f"Could not copy asset {source} -> {destination}: {error}"
                ) from error
            copied += 1
        return copied


    def pdf_command(self, output: Path, font_header: Path | None = None) -> list[str]:
        resource_path = os.pathsep.join(
            [str(self.root), str(self.docs), str(output.parent)]
        )
        command = [
            self.pandoc,
            "--from=json", "--to=pdf", "--standalone",
            f"--output={output}",
            f"--pdf-engine={self.pdf_engine}",
            "--pdf-engine-opt=-halt-on-error",
            "-H", str(self.header),
            "--variable", f"geometry:margin={self.margin}",
            "--variable", f"fontsize={self.fontsize}",
            "--variable", "colorlinks=true",
            "--variable", "linkcolor=blue",
            "--variable", "urlcolor=blue",
            "--variable", "linestretch=1.25",
            "--variable", "papersize=a4",
            "--resource-path", resource_path,
        ]
        if font_header is not None:
            position = command.index("-H")
            command[position:position] = ["-H", str(font_header)]
        return command


    def convert_document(self, source: Path, document: dict) -> Path:
        destination = self.output_for_markdown(source)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ExportError(
                f"{source}: could not create {destination.parent}: {error}"
            ) from error
        temporary = destination.with_name(
            f".{destination.name}.tmp-{os.getpid()}-{time.time_ns()}.pdf"
        )
        payload = json.dumps(document, ensure_ascii=False).encode("utf-8")
        try:
            if self._font_preamble is None:
                self.require_fonts()
            preamble = self._font_preamble
            if preamble is None:
                raise ExportError(f"{source}: font preamble unavailable")
            with tempfile.TemporaryDirectory(prefix="project1-fonts-") as font_directory:
                font_header = Path(font_directory) / "fonts.tex"
                font_header.write_text(preamble, encoding="utf-8")
                result = self.run_pandoc(self.pdf_command(temporary, font_header), data=payload)
            if result.returncode:
                raise ExportError(
                    f"{source}: PDF conversion failed\n"
                    + result.stderr.decode(errors="replace")[-4000:]
                )
            if not temporary.is_file():
                raise ExportError(f"{source}: Pandoc produced no PDF")
            with temporary.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise ExportError(f"{source}: output is not a PDF")
            temporary.replace(destination)
            return destination
        except OSError as error:
            raise ExportError(f"{source}: could not write PDF: {error}") from error
        finally:
            temporary.unlink(missing_ok=True)
