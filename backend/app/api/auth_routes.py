"""Authentication routes: Google sign-in, session, current user."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import settings
from app.core import oauth
from app.core.logging import get_logger

log = get_logger("auth")
router = APIRouter(prefix="/api/auth")

_APP_HOME = "/app"


@router.get("/config")
async def auth_config():
    """Tell the frontend which sign-in methods are available."""
    return {"google": settings.google_oauth_enabled, "dev": settings.dev_auth}


@router.get("/me")
async def me(user: dict = Depends(oauth.current_user)):
    return oauth.public_user(user)


@router.get("/google/login")
async def google_login(request: Request):
    if not settings.google_oauth_enabled:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    state = secrets.token_urlsafe(24)
    resp = RedirectResponse(oauth.login_url(request, state), status_code=302)
    resp.set_cookie(oauth.STATE_COOKIE, state, max_age=600, httponly=True,
                    secure=settings.cookie_secure, samesite="lax", path="/")
    return resp


@router.get("/google/callback")
async def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return RedirectResponse(f"/?auth_error={error}", status_code=302)
    expected = request.cookies.get(oauth.STATE_COOKIE)
    if not code or not state or not expected or not secrets.compare_digest(state, expected):
        return RedirectResponse("/?auth_error=state", status_code=302)
    try:
        tokens = await oauth.exchange_code(request, code)
        info = await oauth.fetch_userinfo(tokens["access_token"])
        user = oauth.upsert_google_user(info)
    except Exception as exc:  # noqa: BLE001 - surface as a friendly redirect
        log.warning("google callback failed: %s", exc)
        return RedirectResponse("/?auth_error=exchange", status_code=302)
    resp = RedirectResponse(_APP_HOME, status_code=302)
    resp.delete_cookie(oauth.STATE_COOKIE, path="/")
    oauth.set_session_cookie(resp, user["id"])
    return resp


@router.post("/dev-login")
async def dev_login():
    """Local testing without real Google credentials (DEV_AUTH only)."""
    if not settings.dev_auth:
        raise HTTPException(status_code=404, detail="Not found")
    user = oauth.dev_user()
    resp = JSONResponse(oauth.public_user(user))
    oauth.set_session_cookie(resp, user["id"])
    return resp


@router.post("/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    oauth.clear_session_cookie(resp)
    return resp
