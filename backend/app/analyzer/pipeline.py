from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Callable, Optional

from ..schemas.graph import GraphDocument, RepositoryInfo
from .builder import GraphBuilder
from .java_extractor import parse_java
from .kotlin_extractor import parse_kotlin
from .python_extractor import parse_python
from .scanner import scan

Progress = Callable[[str, int, int, str], None]  # stage, done, total, message


def analyze_repository(root: Path, owner: str, repo: str, branch: str, commit_sha: str, *,
                       max_file_bytes: int = 1_000_000, max_files: int = 20_000,
                       progress: Optional[Progress] = None, provider=None) -> GraphDocument:
    progress = progress or (lambda *a: None)
    progress("scanning", 0, 0, "Scanning source files")
    sc = scan(root, max_file_bytes, max_files)
    warnings = list(sc.warnings[:50])
    if not sc.sources:
        warnings.append("No supported Python, Kotlin, or Java source files found on this branch.")
    builder = GraphBuilder(owner, repo, provider)
    total = len(sc.sources)
    parse_errors = 0
    for i, (rel, abs_path, lang) in enumerate(sc.sources, 1):
        progress("parsing", i, total, f"Parsing {rel}")
        try:
            data = abs_path.read_bytes()
            if lang == "kotlin":
                pf = parse_kotlin(rel, data)
            elif lang == "java":
                pf = parse_java(rel, data)
            else:
                pf = parse_python(rel, data)
        except Exception as exc:  # one bad file must not abort indexing
            warnings.append(f"Failed to parse {rel}: {type(exc).__name__}")
            parse_errors += 1
            continue
        if pf.has_errors:
            parse_errors += 1
        builder.add_parsed_file(pf)
    for rel, _ in sc.layouts:
        builder.add_layout(rel)
    progress("resolving", total, total, "Resolving symbols and relationships")
    builder.resolve_all()
    for rel, path in sc.navs:
        builder.add_navigation(rel, path)
    nodes, edges, stats = builder.finish()
    stats.update({"source_files": total, "files_with_syntax_errors": parse_errors,
                  "layout_files": len(sc.layouts), "navigation_files": len(sc.navs)})
    if parse_errors:
        warnings.append(f"{parse_errors} file(s) contained syntax the parser could not fully "
                        "understand; their results may be incomplete.")
    return GraphDocument(
        repository=RepositoryInfo(id=f"{owner}/{repo}", owner=owner, name=repo),
        branch=branch, commit_sha=commit_sha,
        indexed_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        stats=stats, warnings=warnings, nodes=nodes, edges=edges)
