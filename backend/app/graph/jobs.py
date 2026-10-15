from __future__ import annotations

import logging
import queue
import threading
from concurrent.futures import ThreadPoolExecutor

from ..analyzer.pipeline import analyze_repository
from ..config import Settings
from ..errors import AppError
from ..github.client import GitHubClient
from ..github.git_service import GitService
from ..github.validation import validate_branch, validate_owner, validate_repo
from ..schemas.graph import GraphEdge, GraphNode, JobStatus
from ..storage.graph_store import GraphStore

log = logging.getLogger("codeatlas.jobs")
STREAM_NODE_LIMIT = 240
STREAM_EDGE_LIMIT = 1200


class JobManager:
    def __init__(self, settings: Settings, store: GraphStore, git: GitService, github_factory=None):
        self.settings, self.store, self.git = settings, store, git
        self.github_factory = github_factory or (lambda token: GitHubClient(token, settings))
        self.jobs: dict[tuple, JobStatus] = {}
        self._graphs: dict[tuple, tuple[dict[str, GraphNode], dict[str, GraphEdge]]] = {}
        self._lock = threading.Lock()
        self._repo_locks: dict[tuple, threading.Lock] = {}
        self._listeners: dict[tuple, set[queue.Queue[JobStatus]]] = {}
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="indexer")

    @staticmethod
    def key(owner: str, repo: str, branch: str) -> tuple:
        return (owner.lower(), repo.lower(), branch)

    def status(self, owner: str, repo: str, branch: str) -> JobStatus:
        with self._lock:
            key = self.key(owner, repo, branch)
            job = self.jobs.get(key)
            if job is not None:
                nodes, edges = self._graphs.get(key, ({}, {}))
                return job.model_copy(update={"nodes": list(nodes.values()), "edges": list(edges.values())})
        sha = self.store.latest_sha(owner, repo, branch)
        if sha:
            return JobStatus(state="ready", stage="ready", percent=100, commit_sha=sha, cached=True,
                             message="Graph available")
        return JobStatus()

    def _set(self, key: tuple, **kw) -> None:
        with self._lock:
            job = self.jobs.setdefault(key, JobStatus())
            node_updates = kw.pop("node_updates", [])
            edge_updates = kw.pop("edge_updates", [])
            nodes, edges = self._graphs.setdefault(key, ({}, {}))
            if "nodes" in kw:
                kw["nodes"] = list(kw["nodes"])
                nodes.clear()
                nodes.update((node.id, node) for node in kw["nodes"])
            if "edges" in kw:
                kw["edges"] = list(kw["edges"])
                edges.clear()
                edges.update((edge.id, edge) for edge in kw["edges"])
            nodes.update((node.id, node) for node in node_updates)
            edges.update((edge.id, edge) for edge in edge_updates)
            for k, v in kw.items():
                setattr(job, k, v)
            snapshot = job.model_copy(update={
                "nodes": node_updates if node_updates else (kw.get("nodes") or []),
                "edges": edge_updates if edge_updates else (kw.get("edges") or []),
            })
            for listener in self._listeners.get(key, set()):
                self._publish(listener, snapshot)

    @staticmethod
    def _publish(listener: queue.Queue[JobStatus], snapshot: JobStatus) -> None:
        try:
            previous = listener.get_nowait()
        except queue.Empty:
            previous = None
        if snapshot.state == "ready":
            snapshot = snapshot.model_copy(update={"nodes": [], "edges": []})
        else:
            nodes = {node.id: node for node in previous.nodes} if previous is not None else {}
            nodes.update((node.id, node) for node in snapshot.nodes)
            edges = {edge.id: edge for edge in previous.edges} if previous is not None else {}
            edges.update((edge.id, edge) for edge in snapshot.edges)
            snapshot = snapshot.model_copy(update={
                "nodes": list(nodes.values())[:STREAM_NODE_LIMIT],
                "edges": list(edges.values())[:STREAM_EDGE_LIMIT],
            })
        listener.put_nowait(snapshot)

    def subscribe(self, owner: str, repo: str, branch: str) -> queue.Queue[JobStatus]:
        key = self.key(owner, repo, branch)
        listener: queue.Queue[JobStatus] = queue.Queue(maxsize=1)
        with self._lock:
            self._listeners.setdefault(key, set()).add(listener)
            job = self.jobs.get(key)
            if job is not None:
                nodes, edges = self._graphs.get(key, ({}, {}))
                initial = job.model_copy(update={
                    "nodes": list(nodes.values())[:STREAM_NODE_LIMIT],
                    "edges": list(edges.values())[:STREAM_EDGE_LIMIT],
                })
                self._publish(listener, initial)
        return listener

    def unsubscribe(self, owner: str, repo: str, branch: str, listener: queue.Queue[JobStatus]) -> None:
        key = self.key(owner, repo, branch)
        with self._lock:
            listeners = self._listeners.get(key)
            if listeners is not None:
                listeners.discard(listener)
                if not listeners:
                    self._listeners.pop(key, None)

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
            return self.status(owner, repo, branch).model_copy(update={"nodes": [], "edges": []})
        self._set(key, state="queued", stage="queued", percent=2, commit_sha=sha, cached=False,
                  message="Queued", error=None, files_total=0, files_done=0, nodes=[], edges=[])
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
                    nodes_list, edges_list = builder.drain_changes() if builder else ([], [])
                    self._set(key, stage=stage, percent=pct, files_done=done, files_total=total, message=msg,
                              node_updates=nodes_list, edge_updates=edges_list)

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
