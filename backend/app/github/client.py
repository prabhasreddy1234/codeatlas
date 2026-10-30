from __future__ import annotations

from typing import Any
from urllib.parse import quote

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

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise AppError(502, "github_unreachable", "Could not reach GitHub.") from exc

        self._raise_for_status(response)
        return response.json()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code == 401:
            raise AppError(401, "github_token_invalid",
                           "GitHub rejected the stored token. Please reconnect GitHub.")
        if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            raise AppError(429, "github_rate_limited", "GitHub API rate limit reached. Try again later.")
        if response.status_code in (403, 404):
            raise AppError(404, "github_not_found",
                           "Repository or branch not found, or the granted access does not include it.")
        if response.status_code >= 400:
            raise AppError(502, "github_error",
                           f"GitHub returned HTTP {response.status_code}.")

    def _paginate(self, path: str, params: dict[str, Any], max_items: int) -> list[Any]:
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
        raw = self._paginate(
            "/user/repos",
            {"sort": "updated", "affiliation": "owner,collaborator,organization_member"},
            max_items,
        )
        return [
            {
                "id": repository["id"],
                "name": repository["name"],
                "owner": repository["owner"]["login"],
                "full_name": repository["full_name"],
                "private": bool(repository["private"]),
                "visibility": repository.get("visibility")
                or ("private" if repository["private"] else "public"),
                "default_branch": repository.get("default_branch") or "main",
                "description": repository.get("description"),
                "archived": bool(repository.get("archived")),
                "language": repository.get("language"),
            }
            for repository in raw
        ]

    def list_branches(self, owner: str, repo: str, max_items: int = 1000) -> list[dict]:
        raw = self._paginate(f"/repos/{owner}/{repo}/branches", {}, max_items)
        return [
            {
                "name": branch["name"],
                "commit_sha": branch["commit"]["sha"],
                "protected": bool(branch.get("protected")),
            }
            for branch in raw
        ]

    def get_branch(self, owner: str, repo: str, branch: str) -> dict:
        response = self._get(
            f"/repos/{owner}/{repo}/branches/{quote(branch, safe='/')}"
        )
        return {"name": response["name"], "commit_sha": response["commit"]["sha"]}
