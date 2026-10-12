from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

IGNORED_DIRS = {
    ".git", ".gradle", ".idea", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".svn", ".tox", ".venv", ".hg", "__pycache__", ".cxx", ".dart_tool",
    "build", "dist", "env", "generated", "intermediates", "node_modules", "out",
    "site-packages", "venv", "__pypackages__",
}
SOURCE_EXT = {".kt": "kotlin", ".java": "java", ".py": "python"}
LAYOUT_RE = re.compile(r"(^|/)res/layout[^/]*/[^/]+\.xml$")
NAV_RE = re.compile(r"(^|/)res/navigation[^/]*/[^/]+\.xml$")


@dataclass
class ScanResult:
    sources: list[tuple[str, Path, str]] = field(default_factory=list)  # (rel, abs, language)
    layouts: list[tuple[str, Path]] = field(default_factory=list)
    navs: list[tuple[str, Path]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_large: int = 0


def scan(root: Path, max_file_bytes: int, max_files: int) -> ScanResult:
    root = root.resolve()
    res = ScanResult()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in IGNORED_DIRS and not os.path.islink(os.path.join(dirpath, d)))
        for fn in sorted(filenames):
            full = Path(dirpath) / fn
            if full.is_symlink() or not full.is_file():
                continue
            rel = full.relative_to(root).as_posix()
            ext = full.suffix.lower()
            kind = None
            if ext in SOURCE_EXT:
                kind = "src"
            elif ext == ".xml" and LAYOUT_RE.search(rel):
                kind = "layout"
            elif ext == ".xml" and NAV_RE.search(rel):
                kind = "nav"
            if kind is None:
                continue
            if full.stat().st_size > max_file_bytes:
                res.skipped_large += 1
                res.warnings.append(f"Skipped {rel}: larger than {max_file_bytes} bytes")
                continue
            if len(res.sources) >= max_files:
                res.warnings.append(f"File limit {max_files} reached; remaining files skipped")
                return res
            if kind == "src":
                res.sources.append((rel, full, SOURCE_EXT[ext]))
            elif kind == "layout":
                res.layouts.append((rel, full))
            else:
                res.navs.append((rel, full))
    return res
