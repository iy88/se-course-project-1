from __future__ import annotations

import re
import tempfile
from datetime import datetime
from pathlib import Path

INCLUDE = re.compile(
    r'<!-- spec-include: path="([^"]+)" level="([3-6])"(?: view="(acceptance)")? -->'
    r'.*?<!-- /spec-include -->', re.DOTALL,
)
META = re.compile(r"\A<!--\n.*?-->\s*", re.DOTALL)
LINK = re.compile(r"(!?\[[^\]\n]*\]\()(<[^>\n]+>|[^)\n]+)(\))")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

def atomic_write(path: Path, data: bytes) -> None:
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)

def generated_markdown(path: Path, body: str) -> str:
    """Preserve the registered version; identical builds preserve metadata too."""
    existing = path.read_text() if path.exists() else ""
    if META.sub("", existing).strip() == body.strip():
        return existing
    version = re.search(r"^Version: (.+)$", existing, re.MULTILINE)
    return (
        "<!--\nVersion: " + (version[1] if version else "0.1.0")
        + "\nVersion-Datetime: " + timestamp() + "\n-->\n\n"
        + body.strip() + "\n"
    )
