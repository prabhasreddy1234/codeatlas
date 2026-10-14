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


def _redirect_error(request: Request, code: str) -> RedirectResponse:
    s = request.app.state.settings
    resp = RedirectResponse(f"{s.frontend_url.rstrip('/')}/?{urlencode({'auth_error': code})}", status_code=302)
    resp.delete_cookie(STATE_COOKIE)
    return resp


@router.get("/auth/github")
def start_oauth(request: Request):
    s = request.app.state.settings
    if not s.github_client_id or not s.github_client_secret:
        raise AppError(503, "oauth_not_configured",
                       "GitHub OAuth is not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in .env.")
    state = secrets.token_urlsafe(32)
    # GitHub OAuth Apps require the `repo` scope to access private repositories.
    scope = "repo"
    params = {"client_id": s.github_client_id, "redirect_uri": s.callback_url, "state": state,
              "allow_signup": "false"}
    params["scope"] = scope
    resp = RedirectResponse(f"{s.github_web_url}/login/oauth/authorize?{urlencode(params)}", status_code=302)
    resp.set_cookie(STATE_COOKIE, _serializer(request).dumps({"state": state, "scope": scope}),
                    max_age=600, httponly=True, samesite="lax", secure=s.cookie_secure, path="/")
    return resp


@router.get("/auth/github/callback")
def oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    s = request.app.state.settings
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
        with httpx.Client(timeout=20) as http:
            tr = http.post(f"{s.github_web_url}/login/oauth/access_token",
                           headers={"Accept": "application/json"},
                           data={"client_id": s.github_client_id, "client_secret": s.github_client_secret,
                                 "code": code, "redirect_uri": s.callback_url})
        body = tr.json()
    except (httpx.HTTPError, ValueError):
        return _redirect_error(request, "token_exchange_failed")
    token = body.get("access_token")
    if not token:
        return _redirect_error(request, "token_exchange_failed")
    granted = body.get("scope", "") or ""
    gh = GitHubClient(token, s)
    try:
        user = gh.get_user()
    except AppError:
        return _redirect_error(request, "user_fetch_failed")
    finally:
        gh.close()
    old = request.cookies.get(SESSION_COOKIE)
    if old:
        request.app.state.sessions.delete(old)
    sess = request.app.state.sessions.create(token, user, granted)  # fresh id: no session fixation
    resp = RedirectResponse(s.frontend_url.rstrip("/") + "/", status_code=302)
    resp.delete_cookie(STATE_COOKIE, path="/")
    resp.set_cookie(SESSION_COOKIE, sess.id, max_age=s.session_ttl_hours * 3600, httponly=True,
                    samesite="lax", secure=s.cookie_secure, path="/")
    return resp


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
