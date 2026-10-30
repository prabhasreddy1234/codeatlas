from __future__ import annotations

import hmac
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

from ..errors import AppError
from ..github.client import GitHubClient
from .deps import SESSION_COOKIE, STATE_COOKIE, current_session, require_csrf

router = APIRouter()


def _serializer(request: Request) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(request.app.state.settings.effective_secret, salt="oauth-state")


def _frontend_redirect(request: Request, params: dict[str, str] | None = None) -> RedirectResponse:
    base_url = request.app.state.settings.frontend_url.rstrip("/")
    query = urlencode(params or {})
    target = f"{base_url}/" if not query else f"{base_url}/?{query}"
    return RedirectResponse(target, status_code=302)


def _redirect_error(request: Request, code: str) -> RedirectResponse:
    response = _frontend_redirect(request, {"auth_error": code})
    response.delete_cookie(STATE_COOKIE)
    return response


def _oauth_state_cookie(request: Request, *, state: str, scope: str) -> str:
    return _serializer(request).dumps({"state": state, "scope": scope})


def _oauth_authorize_url(request: Request, *, state: str, scope: str) -> str:
    settings = request.app.state.settings
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.callback_url,
        "state": state,
        "allow_signup": "false",
        "scope": scope,
    }
    return f"{settings.github_web_url}/login/oauth/authorize?{urlencode(params)}"


def _oauth_token_exchange(request: Request, code: str) -> dict:
    settings = request.app.state.settings
    with httpx.Client(timeout=20) as http:
        response = http.post(
            f"{settings.github_web_url}/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": settings.callback_url,
            },
        )
    return response.json()


@router.get("/auth/github")
def start_oauth(request: Request):
    settings = request.app.state.settings
    if not settings.github_client_id or not settings.github_client_secret:
        raise AppError(
            503,
            "oauth_not_configured",
            "GitHub OAuth is not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in .env.",
        )

    state = secrets.token_urlsafe(32)
    scope = "repo"
    response = RedirectResponse(_oauth_authorize_url(request, state=state, scope=scope), status_code=302)
    response.set_cookie(
        STATE_COOKIE,
        _oauth_state_cookie(request, state=state, scope=scope),
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return response


@router.get("/auth/github/callback")
def oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    settings = request.app.state.settings
    if error:
        return _redirect_error(request, "access_denied")

    cookie = request.cookies.get(STATE_COOKIE)
    if not cookie or not state or not code:
        return _redirect_error(request, "invalid_state")

    try:
        payload = _serializer(request).loads(cookie, max_age=600)
    except BadSignature:
        return _redirect_error(request, "invalid_state")

    if not hmac.compare_digest(str(payload.get("state", "")), state):
        return _redirect_error(request, "invalid_state")

    try:
        body = _oauth_token_exchange(request, code)
    except (httpx.HTTPError, ValueError):
        return _redirect_error(request, "token_exchange_failed")

    token = body.get("access_token")
    if not token:
        return _redirect_error(request, "token_exchange_failed")

    granted = body.get("scope", "") or ""
    gh = GitHubClient(token, settings)
    try:
        user = gh.get_user()
    except AppError:
        return _redirect_error(request, "user_fetch_failed")
    finally:
        gh.close()

    old = request.cookies.get(SESSION_COOKIE)
    if old:
        request.app.state.sessions.delete(old)

    sess = request.app.state.sessions.create(token, user, granted)
    response = _frontend_redirect(request)
    response.delete_cookie(STATE_COOKIE, path="/")
    response.set_cookie(
        SESSION_COOKIE,
        sess.id,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return response


@router.get("/api/auth/me")
def me(request: Request):
    sess = current_session(request)
    configured = bool(request.app.state.settings.github_client_id)
    if sess is None:
        return {"authenticated": False, "oauth_configured": configured}
    return {"authenticated": True, "oauth_configured": configured, "csrf_token": sess.csrf,
            "scope": sess.scope, "private_access": sess.private_access,
            "user": {"login": sess.login, "name": sess.name, "avatar_url": sess.avatar_url}}


@router.post("/api/auth/logout")
def logout(request: Request, sess=Depends(require_csrf)):
    request.app.state.sessions.delete(sess.id)
    s = request.app.state.settings
    try:
        with httpx.Client(timeout=10) as http:
            http.request("DELETE", f"{s.github_api_url}/applications/{s.github_client_id}/grant",
                         auth=(s.github_client_id, s.github_client_secret),
                         json={"access_token": sess.token})
    except httpx.HTTPError:
        pass
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp
