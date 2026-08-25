"""R31 auth router (login gate backend).

Settled design: wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md (§5.1, §7) +
wiki/R31_IMPLEMENTATION.md (§2.5). All endpoints require a valid session
except login itself (and health, which lives in main.py).
"""

import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.services import auth_service

router = APIRouter(tags=["auth"])

SESSION_COOKIE = "session"


def _client_ip(request: Request) -> str:
    """Client IP for audit (design §5.1: request.client.host)."""
    try:
        return request.client.host if request.client else ""
    except Exception:
        return ""


def require_login(request: Request) -> str:
    """FastAPI dependency: the current session's username, or 401.

    The login gate middleware (main.py) also checks this; the dependency
    lets individual endpoints reuse the resolved username directly.
    """
    username = auth_service.get_session(request.cookies.get(SESSION_COOKIE))
    if username is None:
        raise HTTPException(status_code=401, detail="Not logged in")
    return username["username"]


@router.post("/auth/login")
async def login(request: Request, body: dict):
    """Log in with a pre-provisioned local account (`*@hsbc.com`).

    A-H2: an unknown username is rejected — accounts exist only when
    pre-provisioned from the admin allowlist. Records the client IP at
    login. Sets an HttpOnly + SameSite=Lax session cookie (A-M7).
    """
    # P1: reject non-string credentials cleanly. A JSON body with a non-string
    # username/password (e.g. a list/int) must be a 401, not a 500 from
    # `.strip()`/`.encode()` on a non-str. (FastAPI already 422s a non-dict
    # body — str/list/null — so only the field types need guarding here.)
    username = body.get("username")
    password = body.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise HTTPException(status_code=401, detail="invalid username or password")
    username = username.strip()
    if not auth_service.verify_username_format(username):
        raise HTTPException(status_code=401, detail="account not provisioned")
    ip = _client_ip(request)
    token = auth_service.login(username, password, ip)
    if token is None:
        # #303 H1: exponential backoff on failed login — per-username primary
        # + per-IP secondary, NO account lockout.
        time.sleep(auth_service.record_failed_login(username, ip))
        raise HTTPException(status_code=401, detail="invalid username or password")
    auth_service.clear_failed_logins(username, ip)
    resp = JSONResponse({"username": username, "ip": ip})
    # R31 (#279): ZERO session expiry — the cookie is a SESSION cookie (no
    # max_age) so the browser drops it on close; the in-memory session lives
    # until logout or server restart. No 30-min absolute wall-clock expiry.
    # Secure is config-driven and OFF by default: the service runs over plain
    # HTTP, so a blanket secure=True would stop the browser sending the cookie
    # and break login. Deploys behind TLS opt in with COOKIE_SECURE=true.
    secure_cookie = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                    secure=secure_cookie)
    return resp


@router.post("/auth/logout")
async def logout(request: Request):
    """Destroy the session and clear the cookie (R31 #285: no visit flush —
    per-user visit logging is dropped)."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth_service.destroy_session(token)
    resp = Response(status_code=200)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@router.get("/auth/me")
async def me(request: Request, username: str = Depends(require_login)):
    """Current session identity (username + last login IP)."""
    users = auth_service.load_users()
    rec = users.get(username, {})
    return {"username": username, "last_login_ip": rec.get("last_login_ip", "")}
