from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

from ..schemas.graph import GraphDocument
from .db import Database


def _slug(branch: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", branch)[:60]
    return f"{safe}-{hashlib.sha1(branch.encode()).hexdigest()[:8]}"


class GraphStore:
    def __init__(self, workspace: Path, db: Database) -> None:
        self.root = (workspace / "graphs").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = db

    def _path(self, owner: str, repo: str, branch: str, sha: str) -> Path:
        owner, repo = owner.lower(), repo.lower()
        path = (self.root / owner / repo / _slug(branch) / f"{sha}.json").resolve()
        if self.root not in path.parents:
            raise ValueError("graph path escapes the storage root")
        return path

    def save(self, doc: GraphDocument) -> Path:
        repository = doc.repository
        path = self._path(repository.owner, repository.name, doc.branch, doc.commit_sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_document(path, doc)
        self._record_document(doc, path)
        return path

    @staticmethod
    def _write_document(path: Path, doc: GraphDocument) -> None:
        temporary_path = path.with_suffix(".tmp")
        temporary_path.write_text(doc.model_dump_json(), encoding="utf-8")
        os.replace(temporary_path, path)

    def _record_document(self, doc: GraphDocument, path: Path) -> None:
        repository = doc.repository
        self.db.execute(
            "INSERT OR REPLACE INTO graphs VALUES (?,?,?,?,?,?,?,?)",
            (
                repository.owner.lower(),
                repository.name.lower(),
                doc.branch,
                doc.commit_sha,
                str(path),
                doc.indexed_at,
                len(doc.nodes),
                len(doc.edges),
            ),
        )

    def has(self, owner: str, repo: str, branch: str, sha: str) -> bool:
        rows = self.db.execute(
            "SELECT path FROM graphs WHERE owner=? AND repo=? AND branch=? AND commit_sha=?",
            (owner.lower(), repo.lower(), branch, sha),
        )
        return bool(rows) and Path(rows[0]["path"]).exists()

    def load(self, owner: str, repo: str, branch: str, sha: str) -> GraphDocument | None:
        if not self.has(owner, repo, branch, sha):
            return None
        path = self._path(owner, repo, branch, sha)
        return GraphDocument.model_validate_json(path.read_text(encoding="utf-8"))

    def latest_sha(self, owner: str, repo: str, branch: str) -> str | None:
        rows = self.db.execute(
            "SELECT commit_sha, path FROM graphs WHERE owner=? AND repo=? AND branch=? "
            "ORDER BY indexed_at DESC",
            (owner.lower(), repo.lower(), branch),
        )
        for row in rows:
            if Path(row["path"]).exists():
                return row["commit_sha"]
        return None

    def load_latest(self, owner: str, repo: str, branch: str) -> GraphDocument | None:
        sha = self.latest_sha(owner, repo, branch)
        return self.load(owner, repo, branch, sha) if sha else None

    def grant(self, login: str, owner: str, repo: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO graph_access VALUES (?,?,?,?)",
            (login, owner.lower(), repo.lower(), time.time()),
        )

    def can_access(self, login: str, owner: str, repo: str) -> bool:
        return bool(self.db.execute(
            "SELECT 1 FROM graph_access WHERE login=? AND owner=? AND repo=?",
            (login, owner.lower(), repo.lower()),
        ))
