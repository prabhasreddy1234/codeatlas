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


def _should_skip_directory(dirpath: str, dirname: str) -> bool:
    full = os.path.join(dirpath, dirname)
    return dirname in IGNORED_DIRS or os.path.islink(full)


def _classify_file(rel: str, ext: str) -> str | None:
    if ext in SOURCE_EXT:
        return "src"
    if ext == ".xml" and LAYOUT_RE.search(rel):
        return "layout"
    if ext == ".xml" and NAV_RE.search(rel):
        return "nav"
    return None


def _store_file(res: ScanResult, rel: str, full: Path, kind: str, ext: str) -> None:
    if kind == "src":
        res.sources.append((rel, full, SOURCE_EXT[ext]))
    elif kind == "layout":
        res.layouts.append((rel, full))
    elif kind == "nav":
        res.navs.append((rel, full))


def _handle_file(res: ScanResult, root: Path, full: Path, max_file_bytes: int, max_files: int) -> bool:
    if full.is_symlink() or not full.is_file():
        return True

    rel = full.relative_to(root).as_posix()
    ext = full.suffix.lower()
    kind = _classify_file(rel, ext)
    if kind is None:
        return True

    if full.stat().st_size > max_file_bytes:
        res.skipped_large += 1
        res.warnings.append(f"Skipped {rel}: larger than {max_file_bytes} bytes")
        return True

    if len(res.sources) >= max_files:
        res.warnings.append(f"File limit {max_files} reached; remaining files skipped")
        return False

    _store_file(res, rel, full, kind, ext)
    return True


def scan(root: Path, max_file_bytes: int, max_files: int) -> ScanResult:
    """Collect repository source, layout, and navigation files while filtering noise."""
    root = root.resolve()
    res = ScanResult()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if not _should_skip_directory(dirpath, d))
        for fn in sorted(filenames):
            full = Path(dirpath) / fn
            if not _handle_file(res, root, full, max_file_bytes, max_files):
                return res
    return res
