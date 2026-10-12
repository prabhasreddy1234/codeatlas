from __future__ import annotations

import hmac
from typing import Optional

from fastapi import Request

from ..errors import AppError
from .sessions import Session

SESSION_COOKIE = "codeatlas_session"
STATE_COOKIE = "codeatlas_oauth_state"


def current_session(request: Request) -> Optional[Session]:
    return request.app.state.sessions.get(request.cookies.get(SESSION_COOKIE))


def require_session(request: Request) -> Session:
    s = current_session(request)
    if s is None:
        raise AppError(401, "not_authenticated", "Connect your GitHub account first.")
    return s


def require_csrf(request: Request) -> Session:
    """Double-submit token tied to the session plus an Origin allow-list check."""
    s = require_session(request)
    origin = request.headers.get("origin")
    allowed = {request.app.state.settings.frontend_url.rstrip("/"),
               request.app.state.settings.backend_url.rstrip("/")}
    if origin and origin.rstrip("/") not in allowed:
        raise AppError(403, "bad_origin", "Request origin is not allowed.")
    sent = request.headers.get("x-csrf-token", "")
    if not sent or not hmac.compare_digest(sent, s.csrf):
        raise AppError(403, "csrf_failed", "Missing or invalid CSRF token.")
    return s
