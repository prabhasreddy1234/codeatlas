from __future__ import annotations

import httpx

from ..config import Settings
from ..errors import AppError


class GitHubClient:
    """Thin GitHub REST client. The access token never leaves the backend."""

    def __init__(self, token: str, settings: Settings, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(
            base_url=settings.github_api_url, timeout=20, transport=transport,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "CodeAtlas"})

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: dict | None = None):
        try:
            r = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise AppError(502, "github_unreachable", "Could not reach GitHub.") from exc
        if r.status_code == 401:
            raise AppError(401, "github_token_invalid",
                           "GitHub rejected the stored token. Please reconnect GitHub.")
        if r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0":
            raise AppError(429, "github_rate_limited", "GitHub API rate limit reached. Try again later.")
        if r.status_code in (403, 404):
            raise AppError(404, "github_not_found",
                           "Repository or branch not found, or the granted access does not include it.")
        if r.status_code >= 400:
            raise AppError(502, "github_error", f"GitHub returned HTTP {r.status_code}.")
        return r.json()

    def _paginate(self, path: str, params: dict, max_items: int):
        out, page = [], 1
        while len(out) < max_items:
            data = self._get(path, {**params, "per_page": 100, "page": page})
            if not data:
                break
            out.extend(data)
            if len(data) < 100:
                break
            page += 1
        return out[:max_items]

    def get_user(self) -> dict:
        return self._get("/user")

    def list_repos(self, max_items: int = 1000) -> list[dict]:
        raw = self._paginate("/user/repos", {"sort": "updated",
                                             "affiliation": "owner,collaborator,organization_member"}, max_items)
        return [{"id": r["id"], "name": r["name"], "owner": r["owner"]["login"],
                 "full_name": r["full_name"], "private": bool(r["private"]),
                 "visibility": r.get("visibility") or ("private" if r["private"] else "public"),
                 "default_branch": r.get("default_branch") or "main",
                 "description": r.get("description"), "archived": bool(r.get("archived")),
                 "language": r.get("language")} for r in raw]

    def list_branches(self, owner: str, repo: str, max_items: int = 1000) -> list[dict]:
        raw = self._paginate(f"/repos/{owner}/{repo}/branches", {}, max_items)
        return [{"name": b["name"], "commit_sha": b["commit"]["sha"], "protected": bool(b.get("protected"))}
                for b in raw]

    def get_branch(self, owner: str, repo: str, branch: str) -> dict:
        from urllib.parse import quote
        b = self._get(f"/repos/{owner}/{repo}/branches/{quote(branch, safe='/')}")
        return {"name": b["name"], "commit_sha": b["commit"]["sha"]}
