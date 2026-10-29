from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .navigation import _hash_file
from .types import ExporterBase, ExportError, Plan


class IncrementalExport(ExporterBase):

    def load_export_cache(self) -> dict:
        path = self.output / ".export-cache.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("schema") == 1 and isinstance(data.get("documents"), dict):
                return data["documents"]
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError):
            print(f"Ignoring unreadable export cache: {path}", file=sys.stderr)
        return {}


    def save_export_cache(self, entries: dict) -> None:
        self.output.mkdir(parents=True, exist_ok=True)
        path = self.output / ".export-cache.json"
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        try:
            temporary.write_text(json.dumps({"schema": 1, "documents": entries},
                                           ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


    def export_fingerprints(self, plan: Plan) -> dict:
        self.pandoc = self._resolve_tool(self.pandoc)
        self.pdf_engine = self._resolve_tool(self.pdf_engine)
        if self._font_preamble is None:
            self.require_fonts()
        hashes = {}
        def hashed(path):
            path = Path(path).resolve()
            if path not in hashes:
                hashes[path] = _hash_file(path)
            return hashes[path]

        versions = {}
        for tool in (self.pandoc, self.pdf_engine):
            result = subprocess.run([tool, "--version"], capture_output=True,
                                    text=True, timeout=30, check=False)
            if result.returncode:
                raise ExportError(f"Cannot identify renderer: {tool}")
            versions[tool] = result.stdout.splitlines()[0]
        common = {
            "tooling_sha256": {str(path.relative_to(Path(__file__).resolve().parents[1])): hashed(path)
                               for path in sorted(Path(__file__).resolve().parents[1].rglob("*.py"))},
            "header_sha256": hashed(self.header),
            "font_preamble": self._font_preamble,
            "fonts": {str(path): hashed(path) for path in self._font_paths},
            "renderers": versions,
            "landscape_tables": self.landscape_tables,
            "wide_table_columns": self.wide_table_columns,
        }
        fingerprints = {}
        for source in plan.documents:
            source_sha = hashed(source)
            if source_sha != plan.source_hashes[source]:
                raise ExportError(f"Source changed during export planning: {source}")
            payload = {
                "source_sha256": source_sha,
                "document": plan.rewritten[source],
                "command": self.pdf_command(self.output_for_markdown(source), Path("__FONT_HEADER__")),
                "images": {str(record.target): hashed(record.target)
                           for record in plan.records[source]
                           if record.kind == "Image" and record.target is not None},
                "common": common,
            }
            fingerprints[source] = {
                "source_sha256": source_sha,
                "input_sha256": hashlib.sha256(json.dumps(
                    payload, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":")).encode("utf-8")).hexdigest(),
            }
        return fingerprints


    def cache_entry_current(self, source: Path, fingerprint: dict, cache: dict) -> bool:
        entry = cache.get(source.relative_to(self.docs).as_posix(), {})
        if not isinstance(entry, dict) or entry.get("input_sha256") != fingerprint["input_sha256"]:
            return False
        output = self.output_for_markdown(source)
        try:
            with output.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    return False
            return entry.get("pdf_sha256") == _hash_file(output)
        except OSError:
            return False


    def export(self, plan: Plan, *, force: bool = False) -> list[str]:
        fingerprints = self.export_fingerprints(plan)
        cache = self.load_export_cache()
        pending = [source for source in plan.documents
                   if force or not self.cache_entry_current(source, fingerprints[source], cache)]
        reused = len(plan.documents) - len(pending)
        copied = self.prepare_assets(plan)
        errors: list[str] = []
        started = time.monotonic()
        print(f"Incremental export: {len(pending)} rebuild, {reused} reused, "
              f"{copied} changed assets; {self.jobs} job(s) to {self.output}", flush=True)

        def completed(source, destination):
            if _hash_file(source) != fingerprints[source]["source_sha256"]:
                raise ExportError(f"Source changed while rendering; not cached: {source}")
            cache[source.relative_to(self.docs).as_posix()] = {
                **fingerprints[source], "pdf_sha256": _hash_file(destination),
            }
            self.save_export_cache(cache)

        if self.jobs == 1:
            for index, source in enumerate(pending, 1):
                try:
                    destination = self.convert_document(source, plan.rewritten[source])
                    completed(source, destination)
                    print(f"[{index}/{len(pending)}] {destination.relative_to(self.output)}", flush=True)
                except (ExportError, OSError) as error:
                    errors.append(str(error))
                    print(f"[{index}/{len(pending)}] FAILED {source}", flush=True)
        else:
            with ThreadPoolExecutor(max_workers=self.jobs) as pool:
                futures = {pool.submit(self.convert_document, source, plan.rewritten[source]): source
                           for source in pending}
                for index, future in enumerate(as_completed(futures), 1):
                    source = futures[future]
                    try:
                        destination = future.result()
                        completed(source, destination)
                        print(f"[{index}/{len(pending)}] {destination.relative_to(self.output)}", flush=True)
                    except (ExportError, OSError) as error:
                        errors.append(str(error))
                        print(f"[{index}/{len(pending)}] FAILED {source}", flush=True)
        print(f"Exported {len(pending) - len(errors)}/{len(pending)} PDFs; "
              f"reused {reused}; {time.monotonic() - started:.1f}s", flush=True)
        return errors
