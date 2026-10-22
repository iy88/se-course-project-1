from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zlib

from .common import PNG_SIGNATURE, timestamp, atomic_write, generated_markdown

def png_chunks(data: bytes):
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("Renderer did not return a PNG")
    offset = len(PNG_SIGNATURE)
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        chunk = data[offset:offset + length + 12]
        if len(chunk) != length + 12:
            raise ValueError("Truncated PNG")
        yield kind, payload, chunk
        offset += length + 12

def png_resolution(data: bytes, dpi: int) -> bytes:
    ppm = round(dpi / 0.0254)
    payload = struct.pack(">IIB", ppm, ppm, 1)
    kind = b"pHYs"
    physical = struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
    result = bytearray(PNG_SIGNATURE)
    for chunk_type, _, chunk in png_chunks(data):
        if chunk_type != b"pHYs":
            result.extend(chunk)
        if chunk_type == b"IHDR":
            result.extend(physical)
    return bytes(result)

def png_info(data: bytes) -> tuple[int, int, float | None]:
    width = height = 0
    dpi = None
    for kind, payload, _ in png_chunks(data):
        if kind == b"IHDR":
            width, height = struct.unpack(">II", payload[:8])
        elif kind == b"pHYs" and payload[8] == 1:
            dpi = struct.unpack(">I", payload[:4])[0] * 0.0254
    if not width or not height:
        raise ValueError("PNG has no image dimensions")
    return width, height, dpi

def render(root: Path, dpi: int, check: bool,
           executable: str, force: bool) -> None:
    sources = sorted((root / "docs/appendices/models").glob("*.puml"))
    if not sources:
        raise ValueError("No PlantUML sources found")
    destination = root / "docs/appendices/rendered"
    pending = []
    renderer = shutil.which(executable)
    for source in sources:
        output = destination / (source.stem + ".png")
        sidecar = output.with_suffix(".png.version")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        record = sidecar.read_text() if sidecar.exists() else ""
        current = False
        if output.exists() and f"Source-SHA256: {digest}\n" in record:
            _, _, physical_dpi = png_info(output.read_bytes())
            current = physical_dpi is not None and abs(physical_dpi - dpi) < 0.1
            current = current and f"PNG-SHA256: {hashlib.sha256(output.read_bytes()).hexdigest()}\n" in record
        if current and not force:
            continue
        if check:
            raise ValueError(f"Regenerate diagram at {dpi} DPI: {source.name}")
        if not renderer:
            raise ValueError("PlantUML is required; use --plantuml to select its executable")
        env = {**os.environ, "PLANTUML_LIMIT_SIZE": "32768"}
        result = subprocess.run(
            [renderer, "-pipe", "-tpng", "-charset", "UTF-8", f"-Sdpi={dpi}"],
            input=source.read_bytes(), cwd=source.parent, env=env,
            capture_output=True, timeout=240,
        )
        if result.returncode:
            raise ValueError(source.name + ": " + result.stderr.decode(errors="replace")[:2000])
        data = png_resolution(result.stdout, dpi)
        width, height, _ = png_info(data)
        source_version = re.search(
            r"^'?\s*Version:\s*(\S+)\s*$", source.read_text(), re.M
        )
        version = re.search(r"^Version: (.+)$", record, re.M)
        record = (
            f"Version: {source_version[1] if source_version else (version[1] if version else '0.1.0')}\nVersion-Datetime: {timestamp()}\n"
            f"Source-SHA256: {digest}\nPNG-SHA256: {hashlib.sha256(data).hexdigest()}\nDPI: {dpi}\n"
        )
        pending.append((output, data, sidecar, record.encode()))
        print(f"Rendered {source.name}: {width} x {height}, {dpi} DPI", flush=True)
    # Publish after every requested source has rendered successfully.
    if not check:
        for output, data, sidecar, record in pending:
            atomic_write(output, data)
            atomic_write(sidecar, record)
        render_index(root)
    print(f"Diagrams: {len(sources)}, regenerated {len(pending)}, {dpi} DPI")

def render_index(root: Path) -> None:
    directory = root / "docs/appendices/rendered"
    body = (
        "# 图源渲染索引\n\nPNG 使用单一字体 PingFang SC（苹方），中文与西文均按该字体渲染；"
        "图源 skinparam 已统一字体设置。\n\n"
        "| 图名称 | 可编辑源文件 | PNG | 像素尺寸 | DPI |\n|---|---|---|---|---|\n"
    )
    for folder in ["appendices/models"]:
        for source in sorted((root / "docs" / folder).glob("*.puml")):
            png = directory / (source.stem + ".png")
            if not png.exists():
                continue
            width, height, dpi = png_info(png.read_bytes())
            value = str(round(dpi)) if dpi else "未登记"
            body += f"| {source.stem} | [PlantUML](../../{folder}/{source.name}) | [PNG]({png.name}) | {width} × {height} | {value} |\n"
    path = directory / "README.md"
    atomic_write(path, generated_markdown(path, body).encode())
