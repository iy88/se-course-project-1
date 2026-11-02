from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from .navigation import _plain_text, github_slug, pdf_anchor, raw_path
from .types import (
    ANCHOR_ID,
    HTML_ANCHOR_ATTR,
    HTML_ANCHOR_CLOSE,
    HTML_ANCHOR_OPEN,
    URI_SAFE,
    ExporterBase,
    ExportError,
    LinkRecord,
    TransformState,
)


class DocumentTransform(ExporterBase):

    def _anchor_ids(self, content: str) -> list[str]:
        match = HTML_ANCHOR_OPEN.fullmatch(content)
        if not match:
            return []
        ids = []
        for item in HTML_ANCHOR_ATTR.finditer(match.group("attrs")):
            value = item.group(1) if item.group(1) is not None else item.group(2)
            if value and ANCHOR_ID.fullmatch(value):
                ids.append(value)
        return ids


    def _anchor_paragraph(self, node: dict) -> tuple[str, list[str], list[str]] | None:
        """Replace a paragraph made only of raw <a id=...> tags with LaTeX."""
        inlines = node.get("c")
        if not isinstance(inlines, list) or not inlines:
            return None
        ids: list[str] = []
        for inline in inlines:
            if not isinstance(inline, dict) or inline.get("t") != "RawInline":
                return None
            fmt, content = inline.get("c", ["", ""])
            if fmt not in {"html", "html5"}:
                return None
            if HTML_ANCHOR_CLOSE.fullmatch(content):
                continue
            found = self._anchor_ids(content)
            if not found:
                return None
            ids.extend(found)
        if not ids:
            return None
        unique = list(dict.fromkeys(ids))
        anchors = list(dict.fromkeys(pdf_anchor(ident) for ident in unique))
        latex = "\n".join(
            f"\\phantomsection\\hypertarget{{{anchor}}}{{}}\\label{{{anchor}}}"
            for anchor in anchors
        )
        return latex, unique, anchors


    def _add_header_targets(self, node: dict, state: TransformState) -> None:
        _level, attr, inlines = node["c"]
        ident = attr[0] if attr else ""
        if ident and ANCHOR_ID.fullmatch(ident):
            state.aliases.add(ident)
        text = _plain_text(inlines)
        slug = github_slug(text)
        count = state.slug_counts.get(slug, 0)
        state.slug_counts[slug] = count + 1
        alias = slug if count == 0 else f"{slug}-{count}"
        state.aliases.add(alias)

        commands: list[str] = []
        for name, is_ident in ((ident, True), (alias, False)):
            if not name or name == "" or not ANCHOR_ID.fullmatch(name):
                continue
            if not is_ident and name == ident:
                continue
            anchor = pdf_anchor(name)
            if anchor in state.targets:
                continue
            if anchor in self._pandoc_ids:
                # Pandoc already emits \label{anchor}.  Add a named
                # destination only for the header that owns that ID.
                if not (is_ident and anchor == ident):
                    continue
                state.targets.add(anchor)
                commands.append(f"\\hypertarget{{{anchor}}}{{}}")
            else:
                # A GitHub-style fragment should work both inside this PDF and
                # across PDFs.  The label handles same-document \hyperref; the
                # hypertarget handles the GoToR named destination from other
                # PDFs.  Emit before the header because \hypertarget is not
                # robust inside a \section moving argument.
                state.targets.add(anchor)
                commands.append(
                    (f"\\phantomsection\\hypertarget{{{anchor}}}{{}}"
                     f"\\label{{{anchor}}}")
                )
        if commands:
            state.header_targets[id(node)] = "\n".join(commands)


    def _insert_header_targets(self, value, mapping: dict[int, str]):
        """Insert header anchors as blocks before their Header node."""
        if isinstance(value, list):
            result = []
            for child in value:
                if isinstance(child, dict) and id(child) in mapping:
                    result.append({"t": "RawBlock",
                                   "c": ["latex", mapping[id(child)]]})
                result.append(self._insert_header_targets(child, mapping))
            return result
        if not isinstance(value, dict):
            return value
        for key, child in list(value.items()):
            if key != "t" and isinstance(child, (list, dict)):
                value[key] = self._insert_header_targets(child, mapping)
        return value


    def _collect_pandoc_ids(self, document: dict) -> set[str]:
        ids: set[str] = set()
        for node in self._walk_nodes(document):
            if node.get("t") == "Header":
                attr = node["c"][1]
                if attr and attr[0]:
                    ids.add(attr[0])
        return ids


    def _walk_nodes(self, value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from self._walk_nodes(child)
        elif isinstance(value, list):
            for child in value:
                yield from self._walk_nodes(child)


    def _rewrite_target(self, raw: str, state: TransformState,
                        kind: str) -> tuple[str, LinkRecord]:
        parts = urlsplit(raw)
        if parts.scheme or parts.netloc:
            record = LinkRecord(
                source=state.source, kind=kind, original=raw, rewritten=raw,
                target=None, destination=None, is_markdown=False,
                is_external=True, has_path=bool(parts.path),
                fragment=parts.fragment, query=parts.query,
            )
            return raw, record

        if not parts.path:
            if kind == "Image":
                raise ExportError(
                    f"{state.source}: image target has no file path: {raw}"
                )
            rewritten = raw
            if parts.fragment:
                rewritten = "#" + pdf_anchor(unquote(parts.fragment))
            record = LinkRecord(
                source=state.source, kind=kind, original=raw,
                rewritten=rewritten, target=None, destination=None,
                is_markdown=False, is_external=False, has_path=False,
                fragment=parts.fragment, query=parts.query,
            )
            return rewritten, record

        local_path = unquote(parts.path)
        target = (state.source.parent / local_path).resolve()
        if not target.is_relative_to(self.root):
            raise ExportError(
                f"{state.source}: link escapes the repository: {raw}"
            )
        if not target.exists():
            raise ExportError(f"{state.source}: missing link target: {raw}")
        if target.is_dir():
            raise ExportError(
                f"{state.source}: directory links are not supported: {raw}"
            )

        if not target.is_relative_to(self.docs):
            if kind == "Image":
                raise ExportError(f"{state.source}: image outside docs/: {raw}")
            return raw, LinkRecord(
                source=state.source, kind=kind, original=raw, rewritten=raw,
                target=target, destination=None, is_markdown=False,
                is_external=False, has_path=True, fragment=parts.fragment,
                query=parts.query, omitted=True,
            )

        is_markdown = target.suffix.lower() == ".md"
        if is_markdown:
            destination = self.output_for_markdown(target)
        else:
            destination = self.output_for_asset(target)
            state.assets[target] = destination

        if kind == "Image" and is_markdown:
            raise ExportError(
                f"{state.source}: image target is Markdown, not an asset: {raw}"
            )
        if kind == "Image":
            rewritten = quote(
                Path(os.path.relpath(destination, self.output_for_markdown(
                    state.source).parent)).as_posix(),
                safe=URI_SAFE,
            )
        else:
            relative = os.path.relpath(
                destination, self.output_for_markdown(state.source).parent
            )
            # GoToR /F is a file specification, not a URI: keep Unicode and
            # spaces literal. Percent encoding makes viewers seek %E7...pdf.
            rewritten = (Path(relative).as_posix() if is_markdown else
                         quote(Path(relative).as_posix(), safe=URI_SAFE))
        if parts.query:
            rewritten += "?" + parts.query
        if parts.fragment:
            fragment = parts.fragment
            if is_markdown:
                fragment = pdf_anchor(unquote(fragment))
            rewritten += "#" + fragment
        elif raw.endswith("#"):
            rewritten += "#"

        record = LinkRecord(
            source=state.source, kind=kind, original=raw, rewritten=rewritten,
            target=target, destination=destination, is_markdown=is_markdown,
            is_external=False, has_path=True,
            fragment=parts.fragment, query=parts.query,
        )
        return rewritten, record


    def _transform(self, value, state: TransformState):
        if isinstance(value, list):
            return [self._transform(item, state) for item in value]
        if not isinstance(value, dict):
            return value

        kind = value.get("t")
        if kind == "Para":
            replacement = self._anchor_paragraph(value)
            if replacement is not None:
                latex, ids, anchors = replacement
                state.aliases.update(ids)
                state.targets.update(anchors)
                return {"t": "RawBlock", "c": ["latex", latex]}
        elif kind in {"Link", "Image"}:
            target = value["c"][2][0]
            rewritten, record = self._rewrite_target(target, state, kind)
            state.records.append(record)
            if record.omitted:
                label = self._transform(value["c"][1], state)
                return {"t": "Span", "c": [["", [], []], label + [
                    {"t": "Space"}, {"t": "Str", "c": "（仓库路径："},
                    {"t": "Code", "c": [["", [], []], raw_path(record.original)]},
                    {"t": "Str", "c": "）"},
                ]]}
            if kind == "Link" and not record.has_path and record.fragment:
                # Keep the explicit alias: Pandoc otherwise remaps heading IDs
                # to section*.N, hiding the intended named destination.
                anchor = pdf_anchor(unquote(record.fragment))
                label = self._transform(value["c"][1], state)
                return {"t": "Span", "c": [value["c"][0], [
                    {"t": "RawInline", "c": ["latex", r"\hyperlink{" + anchor + "}{"]},
                    *label, {"t": "RawInline", "c": ["latex", "}"]},
                ]]}
            if kind == "Link" and record.is_markdown and record.destination is not None:
                # Explicit UTF-16BE file specifications avoid both URI
                # escaping and PDFDocEncoding ambiguity in short CJK names.
                relative_file = Path(os.path.relpath(
                    record.destination, self.output_for_markdown(state.source).parent
                )).as_posix()
                file_hex = "FEFF" + relative_file.encode("utf-16-be").hex().upper()
                anchor = pdf_anchor(unquote(record.fragment)) if record.fragment else ""
                destination = "(" + anchor + ")" if anchor else "[0 /Fit]"
                label = self._transform(value["c"][1], state)
                return {"t": "Span", "c": [value["c"][0], [
                    {"t": "RawInline", "c": ["latex", r"\ProjectPdfLink{" + file_hex + "}{" + destination + "}{"]},
                    *label, {"t": "RawInline", "c": ["latex", "}"]},
                ]]}
            if kind == "Image" and record.destination is not None:
                # The PDF embeds the image; use its absolute source path so
                # Pandoc can find it while running XeLaTeX in a temp folder.
                value["c"][2][0] = str(record.target)
            else:
                value["c"][2][0] = rewritten
        elif kind == "Header":
            self._add_header_targets(value, state)
        elif kind in {"RawInline", "RawBlock"}:
            fmt, content = value.get("c", ["", ""])
            if fmt in {"html", "html5"}:
                ids = self._anchor_ids(content)
                if ids:
                    anchors = list(dict.fromkeys(
                        pdf_anchor(ident) for ident in dict.fromkeys(ids)
                    ))
                    state.aliases.update(ids)
                    state.targets.update(anchors)
                    latex = "".join(
                        (f"\\phantomsection\\hypertarget{{{anchor}}}{{}}"
                         f"\\label{{{anchor}}}")
                        for anchor in anchors
                    )
                    return {"t": kind, "c": ["latex", latex]}
                if HTML_ANCHOR_CLOSE.fullmatch(content):
                    return {"t": kind, "c": ["latex", ""]}

        # A Pandoc document keeps its block list under "blocks" rather than
        # "c", so recurse through every structured member of the node.
        for key, child in list(value.items()):
            if key != "t" and isinstance(child, (list, dict)):
                value[key] = self._transform(child, state)
        return value


    def _wrap_wide_tables(self, blocks: list) -> list:
        if not self.landscape_tables:
            return blocks
        result = []
        for block in blocks:
            if (isinstance(block, dict) and block.get("t") == "Table"
                    and len(block["c"][2]) >= self.wide_table_columns):
                result.append({"t": "RawBlock", "c": ["latex", "\\begin{landscape}"]})
                result.append(block)
                result.append({"t": "RawBlock", "c": ["latex", "\\end{landscape}"]})
            else:
                result.append(block)
        return result
