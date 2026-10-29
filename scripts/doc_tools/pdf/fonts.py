from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .types import ExporterBase, ExportError


class FontSupport(ExporterBase):

    def _resolve_tool(self, value: str) -> str:
        candidate = Path(value)
        if candidate.is_file():
            return str(candidate)
        found = shutil.which(value)
        if not found:
            raise ExportError(f"Required executable not found: {value}")
        return found


    def require_tools(self, *, exporting: bool) -> None:
        self.pandoc = self._resolve_tool(self.pandoc)
        if exporting:
            self.pdf_engine = self._resolve_tool(self.pdf_engine)
            if not self.header.is_file():
                raise ExportError(f"Missing LaTeX header: {self.header}")
            self.require_fonts()


    def require_fonts(self) -> None:
        matcher = shutil.which("fc-match")
        if not matcher:
            raise ExportError("fc-match is required to resolve PDF font files")
        cache = {}

        def face(family, pattern=""):
            key = (family, pattern)
            if key in cache:
                return cache[key]
            path = Path(family).expanduser()
            if path.is_file():
                result = (path.resolve(), 0)
            else:
                match = subprocess.run(
                    [matcher, "-f", "%{family}\n%{file}\n%{index}\n", family + pattern],
                    capture_output=True, text=True, timeout=30, check=False,
                )
                lines = match.stdout.splitlines()
                if (match.returncode or len(lines) < 3 or
                        family.casefold() not in [v.strip().casefold() for v in lines[0].split(",")]):
                    raise ExportError(f"Requested font unavailable (fallback rejected): {family}")
                result = (Path(lines[1]), int(lines[2]))
            if not result[0].is_file():
                raise ExportError(f"Resolved font file missing: {result[0]}")
            if any(c in str(result[0]) for c in "{}%#\n\r"):
                raise ExportError(f"Font path cannot be represented in LaTeX: {result[0]}")
            cache[key] = result
            return result

        def features(item):
            path, index = item
            options = ["Path={" + path.parent.as_posix() + "/}"]
            if path.suffix.lower() in {".ttc", ".otc"}:
                options.append(f"FontIndex={index}")
            return options

        commands = [r"\usepackage{xeCJK}"]
        for command, family in [
            ("setmainfont", self.latin_main_font),
            ("setsansfont", self.latin_main_font),
            ("setmonofont", self.latin_mono_font),
            ("setCJKmainfont", self.cjk_main_font),
            ("setCJKsansfont", self.cjk_sans_font),
            ("setCJKmonofont", self.cjk_mono_font),
        ]:
            regular = face(family)
            options = features(regular)
            for shape, pattern in [("Bold", ":weight=bold"),
                                   ("Italic", ":slant=italic"),
                                   ("BoldItalic", ":weight=bold:slant=italic")]:
                variant = face(family, pattern)
                shape_features = features(variant)
                if "Italic" in shape:
                    upright = face(family, ":weight=bold" if shape == "BoldItalic" else "")
                    if variant == upright:
                        shape_features.append("FakeSlant=0.2")
                options += [shape + "Font={" + variant[0].name + "}",
                            shape + "Features={" + ",".join(shape_features) + "}"]
            commands.append("\\" + command + "[" + ",".join(options) + "]{" + regular[0].name + "}")
        self._font_preamble = "\n".join(commands) + "\n"
        self._font_paths = sorted({path for path, _index in cache.values()})
