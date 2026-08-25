"""R31 multi-user login: local accounts + in-memory sessions.

Settled design: wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md (§5.1, §5.2,
A-H1/H2, A-M7/A-M9) + wiki/R31_IMPLEMENTATION.md (§2.1) + R31 fixes
(#269, #279, #285).

- Usernames are `*@hsbc.com` local accounts, PRE-PROVISIONED from CONFIG
  (PROVISIONED_USERS, provisioned at startup — no self-registration; an
  unknown username is rejected at login). The /api/admin bootstrap endpoint
  is REMOVED (#269).
- Passwords hashed with salted PBKDF2-HMAC (stdlib hashlib, no new deps).
- Sessions are in-memory, keyed by an opaque token (HttpOnly session cookie
  on the wire — no max_age), ZERO expiry: a session lives until logout or
  server restart (#279); the browser drops the cookie on close.
- Sessions are lost on restart — ACCEPTED (A-M9).
- Per-user VISIT logging is DROPPED entirely (#285): no open_visits registry,
  no visit memos/creator-alerts, no flush machinery.
- Failed logins are throttled with exponential backoff (#303 H1): per-username
  primary + per-IP secondary, no account lockout.
- A password overwrite (provision_user force on an existing account) revokes
  every session for that user (#319 M-Po7); zero-expiry (#279) is kept.
"""

import hashlib
import json
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.services.workspace_service import WORKSPACE_ROOT

# Single source of truth for the quota cap (design §4/A-M2). The history cap
# IS the creation cap — a creator can never hold more than this many of their
# own workspaces because a creator's remove-from-history physically deletes.
MAX_WORKSPACES_PER_USER = 10

# In-memory session store. Single uvicorn worker enforced (A-M8) — these are
# process-local by design and a multi-worker launch is a documented
# misconfiguration (sessions created on worker 1 are unknown to worker 2).
_sessions: dict[str, dict] = {}
_lock = threading.Lock()
# P2: guards the read-modify-write of users.json (load → mutate → save). The
# file itself is written atomically (temp + rename), but a lost update can
# still drop a concurrent writer's entry — the lock spans the whole RMW so
# two writers can't interleave their load/mutate/save cycles.
_users_lock = threading.Lock()

_USERNAME_RE = re.compile(r"^[A-Za-z0-9._%+-]+@hsbc\.com$")
MIN_PASSWORD_LEN = 6
# MIN_PASSWORD_LEN stays at 6 (below the usual 8+ guidance) on purpose: the
# default provisioned admin account (admin@hsbc.com / 123456, config.py
# PROVISIONED_USERS) has a 6-char password and MUST keep working — raising
# this would lock that account out at startup. Accepted tradeoff for the
# single-deploy offline model.
_PBKDF2_ITERATIONS = 600_000


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
    identifier — no mail is ever sent anywhere. Non-str input is rejected
    (a list/int username would otherwise raise on `fullmatch`)."""
    if not isinstance(username, str):
        return False
    return bool(_USERNAME_RE.fullmatch(username))


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
    """Pre-provision an account from CONFIG (PROVISIONED_USERS — R31 #269).

    Creates a NEW account, or (force=True) overwrites the password of an
    EXISTING one. The startup provisioning loop (main.py lifespan) calls this
    with force=True for every config entry, so each deploy re-syncs
    accounts/passwords to config. No HTTP endpoint provisions users.
    Returns False on invalid username/short password.
    """
    if not verify_username_format(username) or not _valid_password(password):
        return False
    with _users_lock:
        users = load_users()
        existed = username in users
        if existed and not force:
            return False
        salt, digest = _hash_password(password)
        users.setdefault(username, {"salt": "", "password_hash": "", "created_at": _now()})
        rec = users[username]
        rec["salt"] = salt
        rec["password_hash"] = digest
        rec.setdefault("last_login_ip", "")
        rec.setdefault("workspaces", [])
        save_users(users)
    if existed:
        # #319 (M-Po7): the password was actually overwritten (not a fresh
        # create) — revoke every live session for this user. Zero-expiry
        # (#279) is untouched: sessions still live until logout/restart.
        revoke_user_sessions(username)
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
        # A-H2: unknown usernames are REJECTED without revealing whether the
        # name exists. Burn the same PBKDF2 cost as a real verify against a
        # dummy salt/hash so the response time is indistinguishable from a
        # wrong-password attempt (no account-existence timing oracle).
        _verify_password(password, "00" * 16, "00" * 64)
        return None
    if not _verify_password(password, rec.get("salt", ""), rec.get("password_hash", "")):
        return None
    # Record login IP (design §5.1) — last writer wins; accepted-loss write,
    # under the users-file lock so the RMW can't drop a concurrent entry.
    with _users_lock:
        users = load_users()
        rec = users.get(username)
        if rec is not None:
            rec["last_login_ip"] = ip
            users[username] = rec
            save_users(users)
    token = _new_token()
    with _lock:
        _sessions[token] = {
            "username": username,
            "ip": ip,
        }
    return token


def get_session(token: str | None) -> dict | None:
    """Return the session if valid; else None.

    R31 (#279): ZERO session expiry — no idle reaper, no last_active
    extension. A session lives until logout or server restart (the browser
    drops the session cookie on close).
    """
    if not token:
        return None
    with _lock:
        sess = _sessions.get(token)
        if sess is None:
            return None
        return dict(sess)


def destroy_session(token: str) -> dict | None:
    """Destroy a session (logout) and return it (or None if it did not exist)."""
    with _lock:
        sess = _sessions.pop(token, None)
    if sess is None:
        return None
    return dict(sess)


def revoke_user_sessions(username: str) -> None:
    """#319 (M-Po7): drop every live session for a user.

    Called when a password is overwritten via ``provision_user(force=True)``
    on an EXISTING account, so a compromised/old session token stops working.
    No expiry is added — zero-expiry (#279) stays.
    """
    with _lock:
        for token in [t for t, sess in _sessions.items()
                      if sess.get("username") == username]:
            _sessions.pop(token, None)


# --- failed-login backoff (#303 H1) ----------------------------------------
# Per-username PRIMARY + per-IP SECONDARY, NO account lockout. A failed login
# sleeps with exponential backoff before returning 401, so brute-force becomes
# impractical without ever locking a real account. In-memory like sessions;
# counters are cleared on success and in reset_for_tests().
_failed_users: dict[str, int] = {}
_failed_ips: dict[str, int] = {}
BACKOFF_BASE_SECONDS = 0.05
BACKOFF_CAP_SECONDS = 5.0


def _backoff_delay(failures: int) -> float:
    """base * 2^(failures-1), capped — first failure sleeps `base`."""
    return min(BACKOFF_BASE_SECONDS * (2 ** (failures - 1)), BACKOFF_CAP_SECONDS)


def record_failed_login(username: str, ip: str) -> float:
    """Increment the failed-attempt counters and return the delay to sleep.

    The delay is the max of the per-username and per-IP backoff: an attacker
    rotating usernames is throttled by the IP counter, one rotating IPs by
    the username counter. Callers sleep this before returning 401.
    """
    with _lock:
        user_failures = _failed_users.get(username, 0) + 1
        _failed_users[username] = user_failures
        failures = user_failures
        if ip:
            ip_failures = _failed_ips.get(ip, 0) + 1
            _failed_ips[ip] = ip_failures
            failures = max(failures, ip_failures)
        return _backoff_delay(failures)


def clear_failed_logins(username: str, ip: str) -> None:
    """Reset the backoff counters on a successful login."""
    with _lock:
        _failed_users.pop(username, None)
        if ip:
            _failed_ips.pop(ip, None)


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
    with _users_lock:
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
    with _users_lock:
        workspaces = [w for w in _index_of(username) if w.get("ws_id") != ws_id]
        _save_index(username, workspaces)


def remove_ws_from_all_indexes(ws_id: str) -> None:
    """Physical delete (creator remove): drop the workspace from EVERY index."""
    with _users_lock:
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
    """Test hook: clear the in-memory session store + backoff counters
    (never on disk)."""
    with _lock:
        _sessions.clear()
        _failed_users.clear()
        _failed_ips.clear()
