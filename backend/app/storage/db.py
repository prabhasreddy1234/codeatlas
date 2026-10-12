from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, token_enc BLOB NOT NULL, login TEXT NOT NULL, name TEXT, avatar_url TEXT,
  scope TEXT NOT NULL DEFAULT '', csrf TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS graphs (
  owner TEXT NOT NULL, repo TEXT NOT NULL, branch TEXT NOT NULL, commit_sha TEXT NOT NULL,
  path TEXT NOT NULL, indexed_at TEXT NOT NULL, node_count INTEGER, edge_count INTEGER,
  PRIMARY KEY (owner, repo, branch, commit_sha)
);
CREATE TABLE IF NOT EXISTS graph_access (
  login TEXT NOT NULL, owner TEXT NOT NULL, repo TEXT NOT NULL, granted_at REAL NOT NULL,
  PRIMARY KEY (login, owner, repo)
);
"""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
            self._conn.commit()
            return rows
