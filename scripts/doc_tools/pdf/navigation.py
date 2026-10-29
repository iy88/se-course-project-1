from __future__ import annotations

import hashlib
import json
import posixpath
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .types import ANCHOR_ID, PDF_FILE_ACTION, PDF_URI_ACTION, ExportError


def raw_path(value: str) -> str:
    return unquote(value)

def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def _plain_text(value) -> str:
    """Return the textual content of a Pandoc inline tree."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_plain_text(item) for item in value)
    if not isinstance(value, dict):
        return ""
    kind = value.get("t")
    content = value.get("c")
    if kind == "Str":
        return content if isinstance(content, str) else ""
    if kind == "Code":
        return content[0] if isinstance(content, list) and content and isinstance(content[0], str) else ""
    if kind == "Math":
        return content[1] if isinstance(content, list) and len(content) > 1 and isinstance(content[1], str) else ""
    if kind in {"Space", "SoftBreak", "LineBreak"}:
        return " "
    if kind in {"Link", "Image"}:
        return _plain_text(content[1]) if isinstance(content, list) and len(content) > 1 else ""
    if kind == "Note":
        return ""
    if kind in {"RawInline", "RawBlock"}:
        return ""
    return _plain_text(content)

def github_slug(text: str) -> str:
    """Approximate GitHub's heading slug, which is what the source fragments use."""
    text = re.sub(r"<[^>]*>", "", text).strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text)
    return text or "section"

def pdf_anchor(name: str) -> str:
    """Return a PDF-safe destination name.

    XeLaTeX/hyperref does not preserve non-ASCII destination names reliably
    (they can be written double-encoded), so non-ASCII fragments and heading
    IDs map to a stable ASCII name.  ASCII IDs are kept verbatim.
    """
    if name.isascii() and ANCHOR_ID.fullmatch(name):
        return name
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]
    return f"pdf-{digest}"

def _decode_pdf_literal(raw: str) -> str:
    body = raw[1:-1]
    out = []
    index = 0
    escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
               "(": "(", ")": ")", "\\": "\\"}
    while index < len(body):
        char = body[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        index += 1
        if index >= len(body):
            break
        char = body[index]
        if char in escapes:
            out.append(escapes[char])
            index += 1
        elif char in "01234567":
            octal = char
            index += 1
            while index < len(body) and len(octal) < 3 and body[index] in "01234567":
                octal += body[index]
                index += 1
            out.append(chr(int(octal, 8)))
        elif char in "\r\n":
            index += 1
            if char == "\r" and index < len(body) and body[index] == "\n":
                index += 1
        else:
            out.append(char)
            index += 1
    return "".join(out)

def _decode_pdf_string(raw: str) -> str:
    if raw.startswith("("):
        return _decode_pdf_literal(raw)
    data = bytes.fromhex(re.sub(r"\s+", "", raw[1:-1]))
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")

def normalize_pdf_target(value: str) -> str:
    value = unquote(value).replace("\\", "/")
    return posixpath.normpath(value)

def pdf_file_targets(pdf: Path, qpdf: str | None = None,
                     timeout: float = 120.0) -> list[str] | None:
    """Return local file targets from PDF link annotations, if qpdf is available.

    Hyperref emits GoToR actions with ``/F`` for Markdown/PDF targets and
    relative ``/URI`` actions for other local assets.  External URIs are not
    local file targets and are deliberately excluded.
    """
    executable = qpdf or shutil.which("qpdf")
    if not executable:
        return None
    result = subprocess.run(
        [executable, "--qdf", "--object-streams=disable", str(pdf), "-"],
        capture_output=True, timeout=timeout, check=False,
    )
    if result.returncode:
        raise ExportError(
            f"{pdf}: qpdf failed\n{result.stderr.decode(errors='replace')[-2000:]}"
        )
    text = result.stdout.decode("latin-1")
    targets = [_decode_pdf_string(match.group(1))
               for match in PDF_FILE_ACTION.finditer(text)]
    for match in PDF_URI_ACTION.finditer(text):
        value = _decode_pdf_string(match.group(1))
        parts = urlsplit(value)
        if parts.scheme or parts.netloc:
            continue
        targets.append(value)
    return targets

def pdf_navigation(pdf: Path, qpdf: str) -> dict:
    """Inspect resolved name trees and link actions using qpdf's structured JSON."""
    result = subprocess.run([qpdf, "--json", str(pdf)], capture_output=True,
                            timeout=120, check=False)
    if result.returncode:
        raise ExportError(f"{pdf}: qpdf failed: {result.stderr.decode(errors='replace')[-1000:]}")
    data = json.loads(result.stdout)
    objects = {}
    for group in data.get("qpdf", [])[1:]:
        for key, item in group.items():
            if key.startswith("obj:"):
                objects[key[4:]] = item.get("value", {})

    def resolve(value):
        seen = set()
        while isinstance(value, str) and value in objects and value not in seen:
            seen.add(value)
            value = objects[value]
        return value

    def string(value):
        value = resolve(value)
        if isinstance(value, str) and value.startswith("u:"):
            return value[2:]
        if isinstance(value, str) and value.startswith("b:"):
            raw = bytes.fromhex(value[2:])
            return (raw[2:].decode("utf-16-be") if raw.startswith(b"\xfe\xff")
                    else raw.decode("utf-8", errors="replace"))
        return value

    names = {}
    def tree(node):
        node = resolve(node)
        if not isinstance(node, dict):
            return
        entries = resolve(node.get("/Names", []))
        for index in range(0, len(entries), 2):
            names[string(entries[index])] = resolve(entries[index + 1])
        for child in resolve(node.get("/Kids", [])):
            tree(child)

    catalog = next((v for v in objects.values()
                    if isinstance(v, dict) and v.get("/Type") == "/Catalog"), {})
    catalog_names = resolve(catalog.get("/Names", {}))
    if isinstance(catalog_names, dict):
        tree(catalog_names.get("/Dests", {}))
    legacy = resolve(catalog.get("/Dests", {}))
    if isinstance(legacy, dict):
        for key, value in legacy.items():
            names[key.lstrip("/")] = resolve(value)
    pages = {page["object"] for page in data.get("pages", [])}

    def destination(value):
        value = resolve(value)
        if isinstance(value, str):
            value = names.get(string(value).lstrip("/"))
            value = resolve(value)
        if isinstance(value, dict):
            value = resolve(value.get("/D"))
        return value

    def valid(value):
        value = destination(value)
        return isinstance(value, list) and bool(value) and value[0] in pages

    links = []
    for page in data.get("pages", []):
        page_object = resolve(page["object"])
        if not isinstance(page_object, dict):
            continue
        annotations = resolve(page_object.get("/Annots", []))
        if not isinstance(annotations, list):
            continue
        for ref in annotations:
            annot = resolve(ref)
            if not isinstance(annot, dict) or annot.get("/Subtype") != "/Link":
                continue
            action = resolve(annot.get("/A", {}))
            if not isinstance(action, dict):
                action = {}
            if "/Dest" in annot:
                links.append({"kind": "/GoTo", "dest": string(annot["/Dest"]),
                              "valid": valid(annot["/Dest"]), "resolved": destination(annot["/Dest"])})
            elif action.get("/S") == "/GoTo":
                links.append({"kind": "/GoTo", "dest": string(action.get("/D")),
                              "valid": valid(action.get("/D")), "resolved": destination(action.get("/D"))})
            elif action.get("/S") == "/GoToR":
                spec = resolve(action.get("/F"))
                unicode_file = isinstance(spec, dict) and "/UF" in spec
                if isinstance(spec, dict):
                    spec = spec.get("/UF", spec.get("/F"))
                links.append({"kind": "/GoToR", "file": string(spec),
                              "dest": string(action.get("/D")),
                              "unicode_file": unicode_file})
            elif action.get("/S") == "/URI":
                links.append({"kind": "/URI", "uri": string(action.get("/URI"))})
    return {"links": links, "destinations": {name: valid(name) for name in names},
            "resolved": {name: destination(name) for name in names}, "pages": len(pages)}

def pdf_replacement_glyphs(pdf: Path, pdftotext: str | None = None,
                           timeout: float = 120.0) -> int | None:
    """Count replacement characters in extracted PDF text, if pdftotext exists.

    A character missing from every configured font is emitted as ``U+FFFD``
    by ``pdftotext``; counting them lets ``--check`` catch empty boxes such as
    an arrow that the CJK text fonts do not provide.
    """
    executable = pdftotext or shutil.which("pdftotext")
    if not executable:
        return None
    result = subprocess.run(
        [executable, "-enc", "UTF-8", "-q", str(pdf), "-"],
        capture_output=True, timeout=timeout, check=False,
    )
    if result.returncode:
        raise ExportError(
            f"{pdf}: pdftotext failed\n"
            f"{result.stderr.decode(errors='replace')[-2000:]}"
        )
    return result.stdout.decode("utf-8", errors="replace").count("\ufffd")
