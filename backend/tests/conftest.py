from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.config import Settings
from app.main import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "sample_android"


@pytest.fixture(scope="session")
def sample_root() -> Path:
    return FIXTURE


@pytest.fixture(scope="session")
def sample_doc(sample_root):
    from app.analyzer.pipeline import analyze_repository
    return analyze_repository(sample_root, "acme", "sample", "main", "a" * 40)


def git(cwd: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"], "HOME": str(cwd)}
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout.strip()


@pytest.fixture()
def remote_repo(tmp_path, sample_root):
    """A local 'GitHub remote' with two branches built from the sample project."""
    import shutil
    base = tmp_path / "remotes" / "acme"
    work = tmp_path / "seed"
    shutil.copytree(sample_root, work)
    git(work, "init", "-q", "-b", "main")
    git(work, "add", "-A", "-f")
    git(work, "commit", "-q", "-m", "init")
    base.mkdir(parents=True)
    bare = base / "sample.git"
    git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    git(work, "checkout", "-q", "-b", "feature/extra")
    (work / "app/src/main/java/com/example/app/Extra.kt").write_text(
        "package com.example.app\n\nclass Extra {\n    fun hi() {}\n}\n")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "extra")
    git(work, "push", "-q", str(bare), "feature/extra")
    return {"template": str(tmp_path / "remotes" / "{owner}" / "{repo}.git"), "bare": bare, "work": work}


@pytest.fixture()
def settings(tmp_path, remote_repo):
    return Settings(workspace_dir=tmp_path / "ws", clone_url_template=remote_repo["template"],
                    github_client_id="cid", github_client_secret="csecret", secret_key="k" * 32,
                    _env_file=None)


class FakeGitHub:
    def __init__(self, bare: Path):
        self.bare = bare

    def close(self): ...

    def get_user(self):
        return {"login": "octo", "name": "Octo", "avatar_url": "x"}

    def list_repos(self, visibility="public"):
        repos = [
            {"id": 1, "name": "sample", "owner": "acme", "full_name": "acme/sample", "private": False,
             "visibility": "public", "default_branch": "main"},
            {"id": 2, "name": "private-sample", "owner": "acme", "full_name": "acme/private-sample",
             "private": True, "visibility": "private", "default_branch": "main"},
        ]
        return [repo for repo in repos if repo["visibility"] == visibility]

    def list_branches(self, owner, repo):
        return [{"name": "main", "commit_sha": "x", "protected": False}]

    def get_branch(self, owner, repo, branch):
        if owner != "acme":
            from app.errors import AppError
            raise AppError(404, "github_not_found", "Repository or branch not found")
        try:
            sha = git(self.bare, "rev-parse", f"refs/heads/{branch}")
        except subprocess.CalledProcessError:
            from app.errors import AppError
            raise AppError(404, "github_not_found", "Repository or branch not found")
        return {"name": branch, "commit_sha": sha}


@pytest.fixture()
def app(settings, remote_repo):
    return create_app(settings, github_factory=lambda token: FakeGitHub(remote_repo["bare"]))


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient
    c = TestClient(app, base_url="http://localhost:8000")
    sess = app.state.sessions.create("gho_faketoken", {"login": "octo", "name": "Octo", "avatar_url": ""}, "repo")
    c.cookies.set("codeatlas_session", sess.id)
    c.headers["X-CSRF-Token"] = sess.csrf
    return c
