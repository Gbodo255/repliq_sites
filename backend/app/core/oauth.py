"""Google OAuth 2.0 sign-in + signed session cookie.

The app is gated behind a Google account. The flow is the standard
Authorization Code flow:

    /api/auth/google/login     -> redirect to Google's consent screen
    /api/auth/google/callback  -> exchange the code, create/find the user,
                                  set a signed ``rx_session`` cookie, go to /app

The session cookie carries only the user id, signed (and time-stamped) with
``itsdangerous`` using ``SESSION_SECRET``; the account record lives in SQLite.
Nothing here runs unless ``GOOGLE_CLIENT_ID``/``SECRET`` are configured, except
the local ``dev-login`` helper (guarded by ``DEV_AUTH``).
"""
from __future__ import annotations

import hashlib
import time
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings
from app.core.logging import get_logger
from app.db.database import db

log = get_logger("oauth")

SESSION_COOKIE = "rx_session"
STATE_COOKIE = "rx_oauth_state"

_GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"

_serializer = URLSafeTimedSerializer(settings.session_secret, salt="rx-session")


# --------------------------------------------------------------------------- #
# Session cookie
# --------------------------------------------------------------------------- #
def sign_session(user_id: str) -> str:
    return _serializer.dumps(user_id)


def load_session(token: str) -> str | None:
    try:
        return _serializer.loads(token, max_age=settings.session_days * 86400)
    except (BadSignature, SignatureExpired):
        return None


def user_from_request(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    uid = load_session(token)
    if not uid:
        return None
    return db.get_user(uid)


async def current_user(request: Request) -> dict:
    """FastAPI dependency: the logged-in user, or 401."""
    user = user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def public_user(user: dict) -> dict:
    return {
        "id": user.get("id", ""),
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "picture": user.get("picture", ""),
    }


# --------------------------------------------------------------------------- #
# Google OAuth helpers
# --------------------------------------------------------------------------- #
def redirect_uri(request: Request) -> str:
    """The OAuth callback URL. Prefer the explicit env value (it must match the
    Google console exactly); otherwise derive it from the request origin."""
    if settings.oauth_redirect_uri:
        return settings.oauth_redirect_uri
    if settings.public_base_url:
        return f"{settings.public_base_url}/api/auth/google/callback"
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/auth/google/callback"


def login_url(request: Request, state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{_GOOGLE_AUTH}?{urlencode(params)}"


async def exchange_code(request: Request, code: str) -> dict:
    data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": redirect_uri(request),
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(_GOOGLE_TOKEN, data=data)
        r.raise_for_status()
        return r.json()


async def fetch_userinfo(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(_GOOGLE_USERINFO,
                             headers={"Authorization": f"Bearer {access_token}"})
        r.raise_for_status()
        return r.json()


def upsert_google_user(info: dict) -> dict:
    """Create or update the account for a Google ``userinfo`` payload."""
    sub = str(info.get("sub") or "")
    if not sub:
        raise HTTPException(status_code=400, detail="Google profile missing subject")
    uid = "g_" + hashlib.sha256(sub.encode()).hexdigest()[:20]
    existing = db.get_user(uid)
    user = {
        "id": uid,
        "sub": sub,
        "email": info.get("email", ""),
        "name": info.get("name") or (info.get("email", "").split("@")[0]),
        "picture": info.get("picture", ""),
        "created_at": existing["created_at"] if existing else time.time(),
    }
    db.upsert_user(user)
    return user


def dev_user() -> dict:
    """A fixed local test account (only usable when DEV_AUTH is enabled)."""
    user = {"id": "dev_local", "sub": "dev", "email": "dev@localhost",
            "name": "Dev User", "picture": "", "created_at": time.time()}
    db.upsert_user(user)
    return user


def set_session_cookie(response, user_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, sign_session(user_id),
        max_age=settings.session_days * 86400,
        httponly=True, secure=settings.cookie_secure, samesite="lax", path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
