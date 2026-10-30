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

    def _git_command(self, args: list[str], token: Optional[str]) -> list[str]:
        command = [
            "git",
            "-c", "core.hooksPath=/dev/null",
            "-c", "core.fsmonitor=false",
            "-c", "credential.helper=",
            "-c", "protocol.ext.allow=never",
            "-c",
            "protocol.file.allow=always" if self.settings.clone_url_template
            else "protocol.file.allow=never",
        ]
        if token:
            basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            command.extend(["-c", f"http.extraHeader=Authorization: Basic {basic}"])
        command.extend(args)
        return command

    @staticmethod
    def _git_environment() -> dict[str, str]:
        return {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
        }

    def _git(self, cwd: Path, args: list[str], token: Optional[str] = None) -> str:
        try:
            result = subprocess.run(
                self._git_command(args, token),
                cwd=cwd,
                capture_output=True,
                text=True,
                env=self._git_environment(),
                timeout=self.settings.git_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise AppError(504, "git_timeout", "Git operation timed out.") from exc
        except FileNotFoundError as exc:
            raise AppError(500, "git_missing", "Git CLI is not installed on the server.") from exc
        if result.returncode != 0:
            raise AppError(502, "git_failed", self._clean(args[0], result.stderr, token))
        return result.stdout.strip()

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
        repo_path = self.repo_dir(owner, repo)
        repo_path.mkdir(parents=True, exist_ok=True)
        self._initialize_repository(repo_path)
        self._configure_origin(repo_path, owner, repo)

        remote_ref = f"refs/remotes/origin/{branch}"
        self._git(
            repo_path,
            [
                "fetch", "--quiet", "--no-tags", "--depth", "1",
                "--no-recurse-submodules", "origin",
                f"+refs/heads/{branch}:{remote_ref}",
            ],
            token,
        )
        self._checkout_branch(repo_path, branch, remote_ref)

        commit_sha = self._git(repo_path, ["rev-parse", "HEAD"])
        if not SHA_RE.match(commit_sha):
            raise AppError(500, "git_failed", "Could not resolve the checked out commit.")
        current_branch = self._git(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"])
        if current_branch != branch:
            raise AppError(500, "git_failed", f"Checked out '{current_branch}' instead of '{branch}'.")
        return repo_path, commit_sha

    def _initialize_repository(self, repo_path: Path) -> None:
        if not (repo_path / ".git").exists():
            self._git(repo_path, ["init", "--quiet"])

    def _configure_origin(self, repo_path: Path, owner: str, repo: str) -> None:
        url = self._remote_url(owner, repo)
        remotes = self._git(repo_path, ["remote"]).split()
        if "origin" in remotes:
            self._git(repo_path, ["remote", "set-url", "origin", url])
        else:
            self._git(repo_path, ["remote", "add", "origin", url])

    def _checkout_branch(self, repo_path: Path, branch: str, remote_ref: str) -> None:
        self._git(repo_path, ["checkout", "--quiet", "--force", "-B", branch, remote_ref])
        self._git(repo_path, ["clean", "-fdxq"])
