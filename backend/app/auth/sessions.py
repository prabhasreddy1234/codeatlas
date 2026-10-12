from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Optional

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

    def create(self, token: str, user: dict, scope: str) -> Session:
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = time.time()
        self.db.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        self.db.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)",
            (sid, self.fernet.encrypt(token.encode()), user["login"], user.get("name"),
             user.get("avatar_url"), scope, csrf, now, now + self.settings.session_ttl_hours * 3600))
        return Session(sid, token, user["login"], user.get("name"), user.get("avatar_url"), scope, csrf)

    def get(self, sid: Optional[str]) -> Optional[Session]:
        if not sid:
            return None
        rows = self.db.execute("SELECT * FROM sessions WHERE id=? AND expires_at > ?", (sid, time.time()))
        if not rows:
            return None
        r = rows[0]
        try:
            token = self.fernet.decrypt(bytes(r["token_enc"])).decode()
        except InvalidToken:
            self.delete(sid)
            return None
        return Session(r["id"], token, r["login"], r["name"], r["avatar_url"], r["scope"], r["csrf"])

    def delete(self, sid: str) -> None:
        self.db.execute("DELETE FROM sessions WHERE id=?", (sid,))
