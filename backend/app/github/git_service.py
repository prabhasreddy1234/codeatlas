from __future__ import annotations

import base64
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from ..config import Settings
from ..errors import AppError
from .validation import SHA_RE, validate_branch, validate_owner, validate_repo


class GitService:
    """Clones/updates repositories inside a controlled workspace using the Git CLI.

    Source code is only ever read by the analyzer; nothing from the repo is executed.
    The access token is passed through a transient HTTP header and never stored in .git/config.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base = (settings.workspace_dir / "repos").resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def repo_dir(self, owner: str, repo: str) -> Path:
        validate_owner(owner), validate_repo(repo)
        p = (self.base / owner.lower() / repo.lower()).resolve()
        if self.base not in p.parents:
            raise AppError(400, "invalid_path", "Repository path escapes the workspace.")
        return p

    def _remote_url(self, owner: str, repo: str) -> str:
        if self.settings.clone_url_template:
            return self.settings.clone_url_template.format(owner=owner, repo=repo)
        return f"{self.settings.github_web_url}/{owner}/{repo}.git"

    def _git(self, cwd: Path, args: list[str], token: Optional[str] = None) -> str:
        cmd = ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
               "-c", "credential.helper=", "-c", "protocol.ext.allow=never"]
        if not self.settings.clone_url_template:
            cmd += ["-c", "protocol.file.allow=never"]
        else:
            cmd += ["-c", "protocol.file.allow=always"]
        if token:
            basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            cmd += ["-c", f"http.extraHeader=Authorization: Basic {basic}"]
        cmd += args
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1",
               "GIT_CONFIG_NOSYSTEM": "1"}
        try:
            r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env,
                               timeout=self.settings.git_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise AppError(504, "git_timeout", "Git operation timed out.") from exc
        except FileNotFoundError as exc:
            raise AppError(500, "git_missing", "Git CLI is not installed on the server.") from exc
        if r.returncode != 0:
            raise AppError(502, "git_failed", self._clean(args[0], r.stderr, token))
        return r.stdout.strip()

    @staticmethod
    def _clean(op: str, stderr: str, token: Optional[str]) -> str:
        msg = stderr.strip().splitlines()[-1] if stderr.strip() else "unknown error"
        if token:
            msg = msg.replace(token, "***")
        msg = re.sub(r"https://[^@\s]+@", "https://", msg)
        low = msg.lower()
        if "couldn't find remote ref" in low:
            return "Branch not found on the remote (or the repository is empty)."
        if "authentication failed" in low or "could not read username" in low or "not found" in low:
            return "Git could not access this repository with the granted GitHub permissions."
        return f"git {op} failed: {msg[:300]}"

    def sync(self, owner: str, repo: str, branch: str, token: Optional[str]) -> tuple[Path, str]:
        """Fetch the exact branch and check it out. Returns (worktree path, resolved commit SHA)."""
        validate_owner(owner), validate_repo(repo), validate_branch(branch)
        d = self.repo_dir(owner, repo)
        d.mkdir(parents=True, exist_ok=True)
        if not (d / ".git").exists():
            self._git(d, ["init", "--quiet"])
        url = self._remote_url(owner, repo)
        remotes = self._git(d, ["remote"]).split()
        if "origin" in remotes:
            self._git(d, ["remote", "set-url", "origin", url])
        else:
            self._git(d, ["remote", "add", "origin", url])
        remote_ref = f"refs/remotes/origin/{branch}"
        self._git(d, ["fetch", "--quiet", "--no-tags", "--depth", "1", "--no-recurse-submodules",
                      "origin", f"+refs/heads/{branch}:{remote_ref}"], token)
        self._git(d, ["checkout", "--quiet", "--force", "-B", branch, remote_ref])
        self._git(d, ["clean", "-fdxq"])
        sha = self._git(d, ["rev-parse", "HEAD"])
        if not SHA_RE.match(sha):
            raise AppError(500, "git_failed", "Could not resolve the checked out commit.")
        current = self._git(d, ["rev-parse", "--abbrev-ref", "HEAD"])
        if current != branch:
            raise AppError(500, "git_failed", f"Checked out '{current}' instead of '{branch}'.")
        return d, sha
