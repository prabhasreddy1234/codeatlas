from __future__ import annotations

import re

from ..errors import AppError

OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
REPO_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/+@#-]{1,200}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def validate_owner(owner: str) -> str:
    if not OWNER_RE.match(owner or ""):
        raise AppError(400, "invalid_owner", "Invalid repository owner name.")
    return owner


def validate_repo(repo: str) -> str:
    if not REPO_RE.match(repo or "") or repo in (".", "..") or repo.endswith(".git"):
        raise AppError(400, "invalid_repo", "Invalid repository name.")
    return repo


def validate_branch(branch: str) -> str:
    bad = (
        not BRANCH_RE.match(branch or "") or branch.startswith(("-", "/")) or branch.endswith(("/", ".", ".lock"))
        or ".." in branch or "//" in branch or "@{" in branch or "/." in branch or branch == "@"
    )
    if bad:
        raise AppError(400, "invalid_branch", "Invalid branch name.")
    return branch
