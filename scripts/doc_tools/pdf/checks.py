from __future__ import annotations
import os
import shutil
import subprocess
from urllib.parse import unquote, urlsplit

from .types import ExportError, Plan
from .navigation import _hash_file, pdf_anchor, normalize_pdf_target, pdf_file_targets, pdf_navigation, pdf_replacement_glyphs

class OutputChecks:

    def check(self, plan: Plan) -> tuple[list[str], dict[str, int]]:
        errors: list[str] = []
        cache = self.load_export_cache()
        if cache:
            fingerprints = self.export_fingerprints(plan)
            for source in plan.documents:
                if not self.cache_entry_current(source, fingerprints[source], cache):
                    errors.append(f"PDF cache is stale, missing or output modified: {self.output_for_markdown(source)}")
        for source in plan.documents:
            destination = self.output_for_markdown(source)
            if not destination.is_file():
                errors.append(f"Missing output PDF: {destination}")
                continue
            try:
                with destination.open("rb") as stream:
                    if stream.read(5) != b"%PDF-":
                        errors.append(f"Not a PDF: {destination}")
            except OSError as error:
                errors.append(f"Unreadable PDF {destination}: {error}")

        for source, destination in plan.assets.items():
            try:
                if not destination.is_file():
                    errors.append(f"Missing copied asset: {destination}")
                elif _hash_file(source) != _hash_file(destination):
                    errors.append(
                        f"Copied asset differs from source: {destination}"
                    )
            except OSError as error:
                errors.append(f"Could not verify asset {destination}: {error}")

        local_markdown = 0
        local_assets = 0
        external = 0
        fragment_only = 0
        for source, records in plan.records.items():
            for record in records:
                if record.omitted:
                    continue
                if record.is_external:
                    external += 1
                    if record.rewritten != record.original:
                        errors.append(
                            f"{source}: external URL changed: {record.original}"
                        )
                    continue
                if not record.has_path:
                    fragment_only += 1
                    expected = record.original
                    if record.fragment:
                        expected = "#" + pdf_anchor(unquote(record.fragment))
                    if record.rewritten != expected:
                        errors.append(
                            f"{source}: fragment-only link changed: {record.original}"
                        )
                    continue
                if record.is_markdown:
                    local_markdown += 1
                    path_part = urlsplit(record.rewritten).path
                    if not path_part.lower().endswith(".pdf"):
                        errors.append(
                            f"{source}: Markdown link is not a .pdf target: "
                            f"{record.rewritten}"
                        )
                else:
                    local_assets += 1
                if record.destination is None or not record.destination.is_file():
                    errors.append(f"{source}: rewritten target missing: {record.rewritten}")
                original_fragment = urlsplit(record.original).fragment
                rewritten_fragment = urlsplit(record.rewritten).fragment
                if record.is_markdown or not record.has_path:
                    expected_fragment = (
                        pdf_anchor(unquote(original_fragment))
                        if original_fragment else ""
                    )
                else:
                    expected_fragment = original_fragment
                if rewritten_fragment != expected_fragment:
                    errors.append(f"{source}: fragment changed: {record.original}")
                if urlsplit(record.original).query != urlsplit(record.rewritten).query:
                    errors.append(f"{source}: query changed: {record.original}")

        pdf_checked = 0
        qpdf = shutil.which("qpdf")
        inspect = self.pdf_link_check == "on" or (
            self.pdf_link_check == "auto" and qpdf is not None
        )
        if self.pdf_link_check == "on" and qpdf is None:
            errors.append("qpdf is required for --pdf-link-check=on but was not found")
        if inspect and qpdf:
            for source in plan.documents:
                pdf = self.output_for_markdown(source)
                if not pdf.is_file():
                    continue
                try:
                    targets = pdf_file_targets(pdf, qpdf)
                except (ExportError, subprocess.TimeoutExpired, OSError) as error:
                    errors.append(str(error))
                    continue
                if targets is None:
                    continue
                pdf_checked += 1
                actual = {normalize_pdf_target(item) for item in targets}
                for target in actual:
                    if target.lower().endswith((".md", ".markdown")):
                        errors.append(f"{pdf}: PDF still links to Markdown: {target}")
                expected = {
                    normalize_pdf_target(urlsplit(record.rewritten).path)
                    for record in plan.records.get(source, [])
                    if record.kind == "Link" and not record.is_external and not record.omitted
                    and record.has_path
                }
                missing = expected - actual
                if missing:
                    errors.append(
                        f"{pdf}: PDF link annotations missing targets: "
                        + ", ".join(sorted(missing))
                    )

        navigation_checked = 0
        navigation = {}
        if inspect and qpdf:
            def read_navigation(path):
                path = path.resolve()
                if path not in navigation:
                    navigation[path] = pdf_navigation(path, qpdf)
                return navigation[path]

            for source in plan.documents:
                pdf = self.output_for_markdown(source)
                if not pdf.is_file():
                    continue
                try:
                    nav = read_navigation(pdf)
                    for alias in plan.aliases[source]:
                        anchor = pdf_anchor(alias)
                        if not nav["destinations"].get(anchor, False):
                            errors.append(f"{pdf}: PDF destination missing or invalid: {anchor}")
                    for action in nav["links"]:
                        if action["kind"] == "/GoTo":
                            navigation_checked += 1
                            if not action["valid"]:
                                errors.append(f"{pdf}: broken internal destination: {action['dest']}")
                        elif action["kind"] == "/GoToR":
                            navigation_checked += 1
                            # File specifications must resolve literally. Do not
                            # unquote: that concealed percent-encoded filenames.
                            file = action["file"]
                            if not isinstance(file, str):
                                errors.append(f"{pdf}: invalid remote file specification")
                                continue
                            if not file.isascii() and not action.get("unicode_file", False):
                                errors.append(f"{pdf}: Unicode filename lacks explicit /UF: {file}")
                            target_pdf = (pdf.parent / file).resolve()
                            if not target_pdf.is_relative_to(self.output):
                                errors.append(f"{pdf}: remote file escapes output: {file}")
                            elif not target_pdf.is_file():
                                errors.append(f"{pdf}: remote file does not exist literally: {file}")
                            elif isinstance(action["dest"], str):
                                target_nav = read_navigation(target_pdf)
                                if not target_nav["destinations"].get(action["dest"], False):
                                    errors.append(f"{pdf}: remote destination missing: {file}#{action['dest']}")
                            elif isinstance(action["dest"], list):
                                target_nav = read_navigation(target_pdf)
                                page_number = action["dest"][0] if action["dest"] else None
                                if not isinstance(page_number, int) or not 0 <= page_number < target_nav["pages"]:
                                    errors.append(f"{pdf}: invalid remote page destination: {file}")
                            else:
                                errors.append(f"{pdf}: missing remote destination: {file}")
                    for record in plan.records[source]:
                        if record.kind != "Link" or record.omitted or record.is_external:
                            continue
                        if not record.has_path and record.fragment:
                            name = pdf_anchor(unquote(record.fragment))
                            expected = nav["resolved"].get(name)
                            if not any(action["kind"] == "/GoTo" and
                                       action.get("resolved") == expected
                                       for action in nav["links"]):
                                errors.append(f"{pdf}: internal link action missing: {record.original}")
                        elif record.is_markdown:
                            expected_file = os.path.relpath(record.destination, pdf.parent)
                            expected_dest = pdf_anchor(unquote(record.fragment)) if record.fragment else None
                            matches = [action for action in nav["links"]
                                       if action["kind"] == "/GoToR" and action["file"] == expected_file]
                            if not any(expected_dest is None or action["dest"] == expected_dest
                                       for action in matches):
                                errors.append(f"{pdf}: remote link action missing or wrong destination: {record.original}")
                except (ExportError, OSError, ValueError, subprocess.TimeoutExpired) as error:
                    errors.append(str(error))

        glyphs_checked = 0
        pdftotext = shutil.which("pdftotext")
        inspect_glyphs = self.glyph_check == "on" or (
            self.glyph_check == "auto" and pdftotext is not None
        )
        if self.glyph_check == "on" and pdftotext is None:
            errors.append("pdftotext is required for --glyph-check=on but was not found")
        if inspect_glyphs and pdftotext:
            for source in plan.documents:
                pdf = self.output_for_markdown(source)
                if not pdf.is_file():
                    continue
                try:
                    missing = pdf_replacement_glyphs(pdf, pdftotext)
                except (ExportError, subprocess.TimeoutExpired, OSError) as error:
                    errors.append(str(error))
                    continue
                if missing is None:
                    continue
                glyphs_checked += 1
                if missing:
                    errors.append(
                        f"{pdf}: {missing} characters render as missing glyphs"
                    )

        stats = {
            "documents": len(plan.documents),
            "assets": len(plan.assets),
            "local_markdown": local_markdown,
            "local_assets": local_assets,
            "external": external,
            "fragment_only": fragment_only,
            "pdf_link_checked": pdf_checked,
            "glyphs_checked": glyphs_checked,
            "navigation_checked": navigation_checked,
        }
        return errors, stats
