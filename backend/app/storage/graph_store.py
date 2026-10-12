from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Optional

from ..schemas.graph import GraphDocument
from .db import Database


def _slug(branch: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", branch)[:60]
    return f"{safe}-{hashlib.sha1(branch.encode()).hexdigest()[:8]}"


class GraphStore:
    def __init__(self, workspace: Path, db: Database):
        self.root = (workspace / "graphs").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = db

    def _path(self, owner: str, repo: str, branch: str, sha: str) -> Path:
        owner, repo = owner.lower(), repo.lower()
        p = (self.root / owner / repo / _slug(branch) / f"{sha}.json").resolve()
        if self.root not in p.parents:
            raise ValueError("graph path escapes the storage root")
        return p

    def save(self, doc: GraphDocument) -> Path:
        r = doc.repository
        path = self._path(r.owner, r.name, doc.branch, doc.commit_sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(doc.model_dump_json(), encoding="utf-8")
        os.replace(tmp, path)
        self.db.execute(
            "INSERT OR REPLACE INTO graphs VALUES (?,?,?,?,?,?,?,?)",
            (r.owner.lower(), r.name.lower(), doc.branch, doc.commit_sha, str(path), doc.indexed_at,
             len(doc.nodes), len(doc.edges)))
        return path

    def has(self, owner: str, repo: str, branch: str, sha: str) -> bool:
        rows = self.db.execute(
            "SELECT path FROM graphs WHERE owner=? AND repo=? AND branch=? AND commit_sha=?",
            (owner.lower(), repo.lower(), branch, sha))
        return bool(rows) and Path(rows[0]["path"]).exists()

    def load(self, owner: str, repo: str, branch: str, sha: str) -> Optional[GraphDocument]:
        if not self.has(owner, repo, branch, sha):
            return None
        path = self._path(owner, repo, branch, sha)
        return GraphDocument.model_validate_json(path.read_text(encoding="utf-8"))

    def latest_sha(self, owner: str, repo: str, branch: str) -> Optional[str]:
        rows = self.db.execute(
            "SELECT commit_sha, path FROM graphs WHERE owner=? AND repo=? AND branch=? "
            "ORDER BY indexed_at DESC", (owner.lower(), repo.lower(), branch))
        for r in rows:
            if Path(r["path"]).exists():
                return r["commit_sha"]
        return None

    def load_latest(self, owner: str, repo: str, branch: str) -> Optional[GraphDocument]:
        sha = self.latest_sha(owner, repo, branch)
        return self.load(owner, repo, branch, sha) if sha else None

    def grant(self, login: str, owner: str, repo: str) -> None:
        import time
        self.db.execute("INSERT OR REPLACE INTO graph_access VALUES (?,?,?,?)",
                        (login, owner.lower(), repo.lower(), time.time()))

    def can_access(self, login: str, owner: str, repo: str) -> bool:
        return bool(self.db.execute(
            "SELECT 1 FROM graph_access WHERE login=? AND owner=? AND repo=?",
            (login, owner.lower(), repo.lower())))
