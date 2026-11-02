from __future__ import annotations

import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from cryptography.fernet import Fernet, InvalidToken

from ..config import Settings
from ..storage.db import Database


@dataclass
class Session:
    id: str
    token: str
    login: str
    name: Optional[str]
    avatar_url: Optional[str]
    scope: str
    csrf: str

    @property
    def private_access(self) -> bool:
        return "repo" in self.scope.replace(",", " ").split()


class SessionStore:
    """Server-side sessions. The browser only holds an opaque, HttpOnly session id;
    the GitHub token is stored encrypted (Fernet) and never sent to the frontend."""

    def __init__(self, db: Database, settings: Settings):
        self.db, self.settings = db, settings
        self.fernet = Fernet(settings.fernet_key)

    def create(self, token: str, user: Mapping[str, Any], scope: str) -> Session:
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        now = time.time()
        expires_at = now + self.settings.session_ttl_hours * 3600

        self.db.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        self.db.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)",
            (
                session_id,
                self.fernet.encrypt(token.encode()),
                user["login"],
                user.get("name"),
                user.get("avatar_url"),
                scope,
                csrf_token,
                now,
                expires_at,
            ),
        )
        return Session(
            id=session_id,
            token=token,
            login=user["login"],
            name=user.get("name"),
            avatar_url=user.get("avatar_url"),
            scope=scope,
            csrf=csrf_token,
        )

    def get(self, sid: Optional[str]) -> Optional[Session]:
        if not sid:
            return None
        rows = self.db.execute(
            "SELECT * FROM sessions WHERE id=? AND expires_at > ?",
            (sid, time.time()),
        )
        if not rows:
            return None

        row = rows[0]
        try:
            token = self.fernet.decrypt(bytes(row["token_enc"])).decode()
        except InvalidToken:
            self.delete(sid)
            return None

        return self._session_from_row(row, token)

    @staticmethod
    def _session_from_row(row: sqlite3.Row, token: str) -> Session:
        return Session(
            id=row["id"],
            token=token,
            login=row["login"],
            name=row["name"],
            avatar_url=row["avatar_url"],
            scope=row["scope"],
            csrf=row["csrf"],
        )

    def delete(self, sid: str) -> None:
        self.db.execute("DELETE FROM sessions WHERE id=?", (sid,))
