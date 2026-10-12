from __future__ import annotations

from collections import OrderedDict
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from ..auth.deps import require_csrf, require_session
from ..auth.sessions import Session
from ..errors import AppError
from ..github.validation import validate_branch, validate_owner, validate_repo
from ..graph.index import GraphIndex
from ..schemas.graph import GenerateRequest

router = APIRouter(prefix="/api")
_cache: "OrderedDict[tuple, GraphIndex]" = OrderedDict()


# ---- GitHub ---------------------------------------------------------------
@router.get("/github/repos")
def list_repos(request: Request, sess: Session = Depends(require_session)):
    gh = request.app.state.jobs.github_factory(sess.token)
    try:
        return {"repositories": gh.list_repos()}
    finally:
        gh.close()


@router.get("/github/repos/{owner}/{repo}/branches")
def list_branches(owner: str, repo: str, request: Request, sess: Session = Depends(require_session)):
    validate_owner(owner), validate_repo(repo)
    gh = request.app.state.jobs.github_factory(sess.token)
    try:
        return {"branches": gh.list_branches(owner, repo)}
    finally:
        gh.close()


# ---- Graph generation -----------------------------------------------------
@router.post("/graphs/generate")
def generate(body: GenerateRequest, request: Request, sess: Session = Depends(require_csrf)):
    job = request.app.state.jobs.start(sess.token, sess.login, body.owner, body.repo, body.branch, body.force)
    return job


def _check(owner: str, repo: str, branch: str, request: Request, sess: Session) -> None:
    validate_owner(owner), validate_repo(repo), validate_branch(branch)
    if not request.app.state.store.can_access(sess.login, owner, repo):
        raise AppError(404, "graph_not_found",
                       "No graph for this repository. Generate it first with your GitHub account.")


def load_index(owner: str, repo: str, branch: str, request: Request, sess: Session) -> GraphIndex:
    _check(owner, repo, branch, request, sess)
    store = request.app.state.store
    sha = store.latest_sha(owner, repo, branch)
    if not sha:
        raise AppError(404, "graph_not_found", "Graph has not been generated for this branch yet.")
    key = (owner.lower(), repo.lower(), branch, sha)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    doc = store.load(owner, repo, branch, sha)
    if doc is None:
        raise AppError(404, "graph_not_found", "Stored graph file is missing; regenerate it.")
    _cache[key] = GraphIndex(doc)
    while len(_cache) > 4:
        _cache.popitem(last=False)
    return _cache[key]


@router.get("/graphs/{owner}/{repo}/status")
def graph_status(owner: str, repo: str, request: Request, branch: str = Query(...),
                 sess: Session = Depends(require_session)):
    validate_owner(owner), validate_repo(repo), validate_branch(branch)
    return request.app.state.jobs.status(owner, repo, branch)


@router.get("/graphs/{owner}/{repo}")
def get_graph(owner: str, repo: str, request: Request, branch: str = Query(...),
              limit: int = Query(120, ge=10, le=500), sess: Session = Depends(require_session)):
    idx = load_index(owner, repo, branch, request, sess)
    d = idx.doc
    return {"repository": d.repository, "branch": d.branch, "commit_sha": d.commit_sha,
            "indexed_at": d.indexed_at, "analyzer": d.analyzer, "stats": d.stats,
            "warnings": d.warnings, "overview": idx.overview(limit)}


@router.get("/graphs/{owner}/{repo}/export")
def export_graph(owner: str, repo: str, request: Request, branch: str = Query(...),
                 sess: Session = Depends(require_session)):
    idx = load_index(owner, repo, branch, request, sess)
    d = idx.doc
    path = request.app.state.store._path(owner, repo, branch, d.commit_sha)
    return FileResponse(path, media_type="application/json",
                        filename=f"{owner}-{repo}-{d.commit_sha[:8]}.codeatlas.json")


@router.get("/graphs/{owner}/{repo}/search")
def search(owner: str, repo: str, request: Request, branch: str = Query(...), q: str = Query("", max_length=200),
           types: Optional[str] = None, sess: Session = Depends(require_session)):
    idx = load_index(owner, repo, branch, request, sess)
    tset = set(types.split(",")) if types else None
    return {"results": idx.search(q, tset)}


@router.get("/graphs/{owner}/{repo}/nodes/{node_id}")
def node_details(owner: str, repo: str, node_id: str, request: Request, branch: str = Query(...),
                 sess: Session = Depends(require_session)):
    idx = load_index(owner, repo, branch, request, sess)
    if node_id not in idx.nodes:
        raise AppError(404, "node_not_found", "Node not found in this graph.")
    return idx.details(node_id)


@router.get("/graphs/{owner}/{repo}/neighbors/{node_id}")
def neighbors(owner: str, repo: str, node_id: str, request: Request, branch: str = Query(...),
              direction: str = Query("both", pattern="^(in|out|both)$"), depth: int = Query(1, ge=1, le=3),
              types: Optional[str] = None, members: bool = False,
              sess: Session = Depends(require_session)):
    idx = load_index(owner, repo, branch, request, sess)
    if node_id not in idx.nodes:
        raise AppError(404, "node_not_found", "Node not found in this graph.")
    tset = set(types.split(",")) if types else None
    return idx.neighbors(node_id, direction, depth, tset, members)
