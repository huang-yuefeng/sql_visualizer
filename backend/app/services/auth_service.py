"""R31 multi-user login: local accounts, sessions, open-visit registry.

Settled design: wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md (§5.1, §5.2,
A-H1/H2, A-M7/A-M9/A-M10) + wiki/R31_IMPLEMENTATION.md (§2.1).

- Usernames are `*@hsbc.com` local accounts, PRE-PROVISIONED from the admin
  allowlist (no self-registration; an unknown username is rejected at login).
- Passwords hashed with salted PBKDF2-HMAC (stdlib hashlib, no new deps).
- Password recovery is ADMIN-MEDIATED only (A-H1): the only way a password
  changes is POST /api/admin/users. No self-service reset path exists here.
- Sessions are in-memory, keyed by an opaque token (HttpOnly cookie on the
  wire), 30-min idle expiry, and record the client IP at login (A-M7).
- open_visits is keyed by SESSION token (A-M10); the session carries the
  username so per-user memo aggregation works at flush time.
- Sessions and open_visits are lost on restart — ACCEPTED (A-M9).
"""

import hashlib
import json
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app.services.workspace_service import WORKSPACE_ROOT

# Single source of truth for the quota cap (design §4/A-M2). The history cap
# IS the creation cap — a creator can never hold more than this many of their
# own workspaces because a creator's remove-from-history physically deletes.
MAX_WORKSPACES_PER_USER = 10

# In-memory session/visit stores. Single uvicorn worker enforced (A-M8) — these
# are process-local by design and a multi-worker launch is a documented
# misconfiguration (sessions created on worker 1 are unknown to worker 2).
_sessions: dict[str, dict] = {}
_open_visits: dict[str, dict] = {}
_lock = threading.Lock()

SESSION_TTL_SECONDS = 30 * 60  # 30-min idle timeout (design §4 Q8)

_USERNAME_RE = re.compile(r"^[A-Za-z0-9._%+-]+@hsbc\.com$")
MIN_PASSWORD_LEN = 6
_PBKDF2_ITERATIONS = 100_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _users_path() -> Path:
    return WORKSPACE_ROOT / "users.json"


def load_users() -> dict:
    """Load the account store. Missing/corrupt file => empty store (never raise)."""
    path = _users_path()
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_users(users: dict) -> None:
    """Persist the account store — temp + rename (accepted-loss, A-M3).

    A race may drop the losing writer's change but never corrupts the file.
    """
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    path = _users_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(users))
    tmp.replace(path)


def verify_username_format(username: str) -> bool:
    """Username MUST be `*@hsbc.com` (design §4/§5.1). Used only as an
    identifier — no mail is ever sent anywhere."""
    return bool(_USERNAME_RE.fullmatch(username or ""))


def _valid_password(password: str) -> bool:
    return isinstance(password, str) and len(password) >= MIN_PASSWORD_LEN


def _hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    """Return (salt_hex, hash_hex). PBKDF2-HMAC-SHA256, 100k iterations."""
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return salt.hex(), digest.hex()


def user_exists(username: str) -> bool:
    return username in load_users()


def provision_user(username: str, password: str, force: bool = False) -> bool:
    """Pre-provision an account from the admin allowlist (A-H2/A-H1).

    Creates a NEW account, or (force=True, admin reset) overwrites the
    password of an EXISTING one. The admin reset is the only path that
    changes a password; nothing in the service self-services it.
    Returns False on invalid username/short password.
    """
    if not verify_username_format(username) or not _valid_password(password):
        return False
    users = load_users()
    if username in users and not force:
        return False
    salt, digest = _hash_password(password)
    users.setdefault(username, {"salt": "", "password_hash": "", "created_at": _now()})
    rec = users[username]
    rec["salt"] = salt
    rec["password_hash"] = digest
    rec.setdefault("last_login_ip", "")
    rec.setdefault("workspaces", [])
    save_users(users)
    return True


def _verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    if not salt_hex or not hash_hex:
        return False
    _, digest = _hash_password(password, salt_hex)
    return secrets.compare_digest(digest, hash_hex)


# --- sessions --------------------------------------------------------------

def _new_token() -> str:
    return secrets.token_hex(32)


def login(username: str, password: str, ip: str) -> str | None:
    """Authenticate and open a session. Returns a session token, or None.

    A-H2: an unknown username is REJECTED (no auto-create) — the account must
    already exist in the pre-provisioned allowlist. Password is verified with
    a constant-time compare.
    """
    users = load_users()
    rec = users.get(username)
    if rec is None:
        return None  # not provisioned — never reveal whether the name exists
    if not _verify_password(password, rec.get("salt", ""), rec.get("password_hash", "")):
        return None
    # Record login IP (design §5.1) — last writer wins; accepted-loss write.
    rec["last_login_ip"] = ip
    users[username] = rec
    save_users(users)
    token = _new_token()
    with _lock:
        _sessions[token] = {
            "username": username,
            "ip": ip,
            "last_active": time.time(),
        }
    return token


def get_session(token: str | None) -> dict | None:
    """Return the session if valid and not idle-expired; else None."""
    if not token:
        return None
    with _lock:
        sess = _sessions.get(token)
        if sess is None:
            return None
        now = time.time()
        if now - sess["last_active"] > SESSION_TTL_SECONDS:
            _sessions.pop(token, None)
            _open_visits.pop(token, None)
            return None
        sess["last_active"] = now  # activity extends the idle window
        return dict(sess)


def destroy_session(token: str) -> dict | None:
    """Destroy a session (logout) and return what it was (for visit flush)."""
    with _lock:
        sess = _sessions.pop(token, None)
        visits = _open_visits.pop(token, None)
    if sess is None:
        return None
    return {"session": sess, "visits": visits or {}}


# --- open visits (A-M10) ---------------------------------------------------

def open_visit(token: str, ws_id: str) -> None:
    """Record that this SESSION has opened ws_id (one tab = one visit)."""
    sess = get_session(token)
    if sess is None:
        return
    with _lock:
        visits = _open_visits.setdefault(token, {})
        visits[ws_id] = {"opened_at": _now(), "last_active": time.time()}


def touch_visit(token: str, ws_id: str) -> None:
    with _lock:
        visits = _open_visits.get(token)
        if visits and ws_id in visits:
            visits[ws_id]["last_active"] = time.time()


def session_has_visit(token: str, ws_id: str) -> bool:
    with _lock:
        return ws_id in _open_visits.get(token, {})


def close_visit(token: str, ws_id: str) -> None:
    """Explicit close-workspace: end this session's visit to ws_id."""
    with _lock:
        visits = _open_visits.get(token)
        if visits:
            visits.pop(ws_id, None)


def flush_session_visits(token: str) -> list[dict]:
    """Flush a session's open visits on logout/expiry.

    Returns the flushed visit list [{username, ws_id, opened_at, last_active}]
    so the caller can write activity-log entries + memos. The CALLER performs
    the per-user aggregation (A-M10): a memo/creator-alert is created only if
    no OTHER session of the same username still has the workspace open.
    """
    with _lock:
        sess = _sessions.get(token)
        visits = _open_visits.pop(token, {})
    if sess is None:
        return []
    out = []
    for ws_id, v in visits.items():
        out.append({
            "username": sess["username"],
            "ip": sess["ip"],
            "ws_id": ws_id,
            "opened_at": v.get("opened_at"),
        })
    return out


def other_sessions_have_visit(username: str, ws_id: str, except_token: str) -> bool:
    """A-M10: does ANY other session belonging to username still have ws_id open?"""
    with _lock:
        for tok, visits in _open_visits.items():
            if tok == except_token:
                continue
            sess = _sessions.get(tok)
            if sess and sess.get("username") == username and ws_id in visits:
                return True
    return False


# --- per-user workspace index (design §5.5 / §6) ----------------------------

def _index_of(username: str) -> list[dict]:
    users = load_users()
    return users.get(username, {}).get("workspaces", [])


def _save_index(username: str, workspaces: list[dict]) -> None:
    users = load_users()
    rec = users.setdefault(username, {"workspaces": []})
    rec["workspaces"] = workspaces
    save_users(users)


def add_workspace_to_index(username: str, ws_id: str, role: str) -> bool:
    """Add/refresh the user's index entry. Returns False when the quota is full
    (409 upstream). Role: 'creator' | 'participant'."""
    workspaces = _index_of(username)
    existing = next((w for w in workspaces if w.get("ws_id") == ws_id), None)
    if existing is not None:
        existing["last_opened"] = _now()
        if existing.get("role") != "creator":
            existing["role"] = role  # creator status is sticky
        _save_index(username, workspaces)
        return True
    if len(workspaces) >= MAX_WORKSPACES_PER_USER:
        return False  # quota full — "remove one from your list first"
    workspaces.append({
        "ws_id": ws_id,
        "role": role,
        "first_opened": _now(),
        "last_opened": _now(),
    })
    _save_index(username, workspaces)
    return True


def remove_workspace_from_index(username: str, ws_id: str) -> None:
    workspaces = [w for w in _index_of(username) if w.get("ws_id") != ws_id]
    _save_index(username, workspaces)


def remove_ws_from_all_indexes(ws_id: str) -> None:
    """Physical delete (creator remove): drop the workspace from EVERY index."""
    users = load_users()
    changed = False
    for rec in users.values():
        workspaces = rec.get("workspaces", [])
        filtered = [w for w in workspaces if w.get("ws_id") != ws_id]
        if len(filtered) != len(workspaces):
            rec["workspaces"] = filtered
            changed = True
    if changed:
        save_users(users)


def index_has_room(username: str) -> bool:
    return len(_index_of(username)) < MAX_WORKSPACES_PER_USER


def get_my_workspaces(username: str) -> dict:
    workspaces = _index_of(username)
    return {"workspaces": workspaces, "count": len(workspaces), "cap": MAX_WORKSPACES_PER_USER}


def reset_for_tests() -> None:
    """Test hook: clear the in-memory session/visit stores (never on disk)."""
    with _lock:
        _sessions.clear()
        _open_visits.clear()
