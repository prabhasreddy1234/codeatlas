from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from ..analyzer.pipeline import analyze_repository
from ..config import Settings
from ..errors import AppError
from ..github.client import GitHubClient
from ..github.git_service import GitService
from ..github.validation import validate_branch, validate_owner, validate_repo
from ..schemas.graph import JobStatus
from ..storage.graph_store import GraphStore

log = logging.getLogger("codeatlas.jobs")


class JobManager:
    def __init__(self, settings: Settings, store: GraphStore, git: GitService, github_factory=None):
        self.settings, self.store, self.git = settings, store, git
        self.github_factory = github_factory or (lambda token: GitHubClient(token, settings))
        self.jobs: dict[tuple, JobStatus] = {}
        self._lock = threading.Lock()
        self._repo_locks: dict[tuple, threading.Lock] = {}
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="indexer")

    @staticmethod
    def key(owner: str, repo: str, branch: str) -> tuple:
        return (owner.lower(), repo.lower(), branch)

    def status(self, owner: str, repo: str, branch: str) -> JobStatus:
        with self._lock:
            job = self.jobs.get(self.key(owner, repo, branch))
            if job is not None:
                return job.model_copy()
        sha = self.store.latest_sha(owner, repo, branch)
        if sha:
            return JobStatus(state="ready", stage="ready", percent=100, commit_sha=sha, cached=True,
                             message="Graph available")
        return JobStatus()

    def _set(self, key: tuple, **kw) -> None:
        with self._lock:
            job = self.jobs.setdefault(key, JobStatus())
            for k, v in kw.items():
                setattr(job, k, v)

    def start(self, token: str, login: str, owner: str, repo: str, branch: str, force: bool) -> JobStatus:
        validate_owner(owner), validate_repo(repo), validate_branch(branch)
        key = self.key(owner, repo, branch)
        with self._lock:
            cur = self.jobs.get(key)
            if cur is not None and cur.state in ("queued", "running"):
                return cur.model_copy()
        gh = self.github_factory(token)
        try:
            remote = gh.get_branch(owner, repo, branch)  # also verifies the user's access
        finally:
            gh.close()
        self.store.grant(login, owner, repo)
        sha = remote["commit_sha"]
        if not force and self.store.has(owner, repo, branch, sha):
            doc = self.store.load(owner, repo, branch, sha)
            self._set(key, state="ready", stage="ready", percent=100, commit_sha=sha, cached=True,
                      message="Loaded existing graph for this commit", error=None, files_total=0, files_done=0,
                      nodes=doc.nodes if doc else [], edges=doc.edges if doc else [])
            return self.status(owner, repo, branch)
        self._set(key, state="queued", stage="queued", percent=2, commit_sha=sha, cached=False,
                  message="Queued", error=None, files_total=0, files_done=0)
        self.executor.submit(self._run, token, owner, repo, branch, force, key)
        return self.status(owner, repo, branch)

    def _run(self, token: str, owner: str, repo: str, branch: str, force: bool, key: tuple) -> None:
        with self._lock:
            lock = self._repo_locks.setdefault((key[0], key[1]), threading.Lock())
        try:
            with lock:
                self._set(key, state="running", stage="fetching", percent=8,
                          message="Cloning / fetching branch from GitHub")
                workdir, sha = self.git.sync(owner, repo, branch, token)
                self._set(key, commit_sha=sha, percent=25, message=f"Checked out {sha[:10]}")
                if not force and self.store.has(owner, repo, branch, sha):
                    doc = self.store.load(owner, repo, branch, sha)
                    self._set(key, state="ready", stage="ready", percent=100, cached=True,
                              message="Graph for this commit already indexed",
                              nodes=doc.nodes if doc else [], edges=doc.edges if doc else [])
                    return

                def progress(stage: str, done: int, total: int, msg: str, builder=None) -> None:
                    pct = 25 + int(65 * done / total) if stage == "parsing" and total else (
                        90 if stage == "resolving" else 25)
                    nodes_list = list(builder.nodes.values()) if builder else []
                    edges_list = list(builder.edges.values()) if builder else []
                    self._set(key, stage=stage, percent=pct, files_done=done, files_total=total, message=msg,
                              nodes=nodes_list, edges=edges_list)

                doc = analyze_repository(workdir, owner, repo, branch, sha,
                                         max_file_bytes=self.settings.max_file_bytes,
                                         max_files=self.settings.max_files, progress=progress)
                self._set(key, stage="saving", percent=95, message="Saving graph")
                self.store.save(doc)
                self._set(key, state="ready", stage="ready", percent=100, cached=False,
                          message=f"Indexed {len(doc.nodes)} nodes and {len(doc.edges)} edges",
                          nodes=doc.nodes, edges=doc.edges)
        except AppError as exc:
            self._set(key, state="failed", stage="failed", error={"code": exc.code, "message": exc.message},
                      message=exc.message)
        except Exception as exc:  # noqa: BLE001
            log.exception("indexing failed for %s/%s@%s", owner, repo, branch)
            self._set(key, state="failed", stage="failed",
                      error={"code": "analysis_failed",
                             "message": f"Analysis failed unexpectedly ({type(exc).__name__})."},
                      message="Analysis failed")
