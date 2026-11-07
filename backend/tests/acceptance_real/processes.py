"""Stop the owned acceptance server and wait for graceful shutdown."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from app.core.private_files import protect_private


def stop_server(process: subprocess.Popen, clock_file: Path) -> None:
    if process.poll() is not None:
        return
    if sys.platform == 'win32':
        stop_file = clock_file.with_suffix('.stop')
        stop_file.write_text('stop\n', encoding='ascii')
        protect_private(stop_file)
    else:
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
