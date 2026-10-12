from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import router as api_router
from .auth.routes import router as auth_router
from .auth.sessions import SessionStore
from .config import Settings, get_settings
from .errors import AppError
from .github.git_service import GitService
from .graph.jobs import JobManager
from .storage.db import Database
from .storage.graph_store import GraphStore


def create_app(settings: Settings | None = None, github_factory=None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="CodeAtlas", version="0.1.0")
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.workspace_dir / "codeatlas.db")
    store = GraphStore(settings.workspace_dir, db)
    app.state.settings = settings
    app.state.db = db
    app.state.store = store
    app.state.sessions = SessionStore(db, settings)
    app.state.jobs = JobManager(settings, store, GitService(settings), github_factory)

    app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url.rstrip("/")],
                       allow_credentials=True, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "X-CSRF-Token"])

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        return JSONResponse({"error": {"code": "validation_error",
                                       "message": "Invalid request parameters.",
                                       "details": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]}},
                            status_code=422)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "llm_used": False}

    app.include_router(auth_router)
    app.include_router(api_router)
    return app


logging.getLogger("codeatlas").setLevel(logging.INFO)
