from __future__ import annotations

import base64
import hashlib
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    github_client_id: str = ""
    github_client_secret: str = ""
    secret_key: str = ""
    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"
    workspace_dir: Path = ROOT_DIR / ".codeatlas-data"
    github_api_url: str = "https://api.github.com"
    github_web_url: str = "https://github.com"
    cookie_secure: bool = False
    session_ttl_hours: int = 12
    max_file_bytes: int = 1_000_000
    max_files: int = 20_000
    git_timeout_seconds: int = 600
    # Test hook: when set, remotes are built from this template instead of github.com.
    clone_url_template: str = ""

    @property
    def callback_url(self) -> str:
        return f"{self.backend_url.rstrip('/')}/auth/github/callback"

    @property
    def effective_secret(self) -> str:
        if self.secret_key:
            return self.secret_key
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        key_file = self.workspace_dir / "secret.key"
        if not key_file.exists():
            key_file.write_text(secrets.token_urlsafe(48))
            key_file.chmod(0o600)
        return key_file.read_text().strip()

    @property
    def fernet_key(self) -> bytes:
        return base64.urlsafe_b64encode(hashlib.sha256(self.effective_secret.encode()).digest())


@lru_cache
def get_settings() -> Settings:
    return Settings()
