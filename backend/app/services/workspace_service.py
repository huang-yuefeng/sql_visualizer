"""Workspace service — zip extraction, directory management, multi-user isolation."""
import json
import re
import shutil
import zipfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_ROOT = Path("/tmp/workspaces")

# R31/A-H4: ws_id is a server-generated full UUID4 (uuid4().hex = 32 hex /
# 128-bit), never client-supplied, never sequential. No endpoint enumerates
# ids. Reject anything else (path traversal guard).
_WS_ID_RE = re.compile(r"^[0-9a-f]{32}$")


import time

def cleanup_old_workspaces(max_age_hours: int = 24) -> int:
    """Remove workspaces older than max_age_hours. Returns count removed."""
    _ensure_root()
    removed = 0
    now = time.time()
    for ws_dir in WORKSPACE_ROOT.iterdir():
        if not ws_dir.is_dir():
            continue
        meta_path = ws_dir / "meta.json"
        if not meta_path.exists():
            # No metadata — remove orphaned directory
            shutil.rmtree(ws_dir)
            removed += 1
            continue
        try:
            import json as _json
            meta = _json.loads(meta_path.read_text())
            created = meta.get("created_at", "")
            if created:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(created)
                age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                if age_hours > max_age_hours:
                    shutil.rmtree(ws_dir)
                    removed += 1
        except Exception:
            pass  # unreadable meta → skip (never delete what we can't age)
    return removed


def is_valid_ws_id(ws_id: str) -> bool:
    """Validate a workspace id against the workspace charset (full UUID4,
    32 hex chars, as created by create_workspace — R31/A-H4). Shared by
    routes that need a 400 for malformed ids vs a 404 for valid-format but
    missing workspaces."""
    return bool(_WS_ID_RE.fullmatch(ws_id))


def _ensure_root():
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

def create_workspace(zip_bytes: bytes, creator_username: str | None = None) -> str:
    """Extract zip archive, return workspace_id.

    R31/A-H4: ws_id is a full server-generated UUID4 (128-bit), never
    client-supplied. R31/A-M6: the existing folder/zip upload is the create
    path — it stamps creator_username (when provided) into meta.json so the
    workspace carries its creator from birth.
    """
    _ensure_root()
    ws_id = uuid.uuid4().hex
    ws_dir = WORKSPACE_ROOT / ws_id
    scripts_dir = ws_dir / "scripts"
    cache_dir = ws_dir / "cache"
    scripts_dir.mkdir(parents=True)
    cache_dir.mkdir(parents=True)

    # Extract zip
    import io
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for member in zf.namelist():
            # Skip directories and __MACOSX junk
            if member.endswith('/') or member.startswith('__MACOSX'):
                continue
            # Security: prevent path traversal (component-wise, like
            # get_script_path — a string-prefix check would accept
            # `../scripts_evil/x.sql` and any id-prefix-colliding sibling
            # workspace as "inside").
            target = (scripts_dir / member).resolve()
            if not target.is_relative_to(scripts_dir.resolve()):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, 'wb') as dst:
                dst.write(src.read())

    # Write metadata (R31-extended schema: creator, CAS state_version, layouts)
    meta = {
        "workspace_id": ws_id,
        "creator_username": creator_username,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "state_version": 0,
        "indexed": False,
        "indexed_scripts": [],
        "last_search": None,
        "opened_l2s": [],
        "layouts": {},
    }
    (ws_dir / "meta.json").write_text(json.dumps(meta))
    return ws_id

def get_workspace(ws_id: str) -> dict | None:
    """Return workspace metadata, or None if not found."""
    if not _WS_ID_RE.fullmatch(ws_id):
        return None
    ws_dir = WORKSPACE_ROOT / ws_id
    meta_path = ws_dir / "meta.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    # Count files
    scripts_dir = ws_dir / "scripts"
    file_count = sum(1 for _ in scripts_dir.rglob("*") if _.is_file()) if scripts_dir.exists() else 0
    meta["file_count"] = file_count
    return meta

def delete_workspace(ws_id: str) -> bool:
    """Remove workspace directory recursively."""
    if not _WS_ID_RE.fullmatch(ws_id):
        return False
    ws_dir = WORKSPACE_ROOT / ws_id
    if not ws_dir.exists():
        return False
    shutil.rmtree(ws_dir)
    return True

def get_script_path(ws_id: str, relative_path: str) -> Path | None:
    """Resolve a script path within the workspace. Returns None if path traversal detected."""
    ws_dir = WORKSPACE_ROOT / ws_id
    scripts_dir = ws_dir / "scripts"
    target = (scripts_dir / relative_path).resolve()
    # H1: path-containment check — the old string-prefix test let a
    # same-workspace sibling dir named `scripts_backup` pass; compare
    # paths like resolve_script's is_relative_to.
    if not target.is_relative_to(scripts_dir.resolve()):
        return None
    if not target.exists():
        return None
    return target

def get_workspace_dir(ws_id: str) -> Path:
    return WORKSPACE_ROOT / ws_id


# --- R31: shared workspace state (meta.json) --------------------------------

def read_meta(ws_id: str) -> dict | None:
    """Read a workspace's meta.json (None if missing/unreadable)."""
    if not _WS_ID_RE.fullmatch(ws_id):
        return None
    path = WORKSPACE_ROOT / ws_id / "meta.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def write_meta_cas(ws_id: str, meta: dict, expected_state_version: int) -> bool:
    """CAS-conditional meta write (R31/A-M4).

    Applies only if the stored `state_version` still equals
    `expected_state_version`; on success the state_version is bumped, making
    it genuinely monotonic (single worker, A-M8, makes check-and-rename
    atomic). Returns False when stale — the caller replies 409 with the fresh
    meta so the client reloads + re-applies.
    """
    if not _WS_ID_RE.fullmatch(ws_id):
        return False
    path = WORKSPACE_ROOT / ws_id / "meta.json"
    stored = read_meta(ws_id)
    if stored is None:
        return False
    if stored.get("state_version", 0) != expected_state_version:
        return False
    meta["state_version"] = expected_state_version + 1
    meta["workspace_id"] = stored.get("workspace_id", ws_id)
    meta["created_at"] = stored.get("created_at", meta.get("created_at"))
    if "creator_username" in stored:
        meta["creator_username"] = stored["creator_username"]
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta))
    tmp.replace(path)
    return True


def remove_legacy_workspaces() -> int:
    """R31 rollout migration: delete workspaces without a creator (pre-feature).

    Design §6: old workspaces are removed directly (user-confirmed, no
    backup). Returns the count removed. Only called once at rollout.
    """
    _ensure_root()
    removed = 0
    for ws_dir in list(WORKSPACE_ROOT.iterdir()):
        if not ws_dir.is_dir():
            continue
        meta_path = ws_dir / "meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            continue
        if not meta.get("creator_username"):
            shutil.rmtree(ws_dir)
            removed += 1
    return removed


def remove_from_my_history(ws_id: str, username: str, ip: str) -> tuple[bool, str, bool]:
    """R31 role-dependent remove-from-my-history (A-M1/A-M2/A-H3).

    Returns (ok, message, physically_deleted):
    - creator  → physically delete: server-global AUDIT entry written FIRST
      (A-H3), then rmtree, then dropped from EVERY user's index.
    - non-creator → link removed from the caller's index only; recorded in the
      workspace's activity log (the workspace + files survive).

    Callers MUST check is_valid_ws_id / existence before calling (a valid-format
    but missing id returns ok=False, "not found").
    """
    from app.services.auth_service import (
        remove_ws_from_all_indexes, remove_workspace_from_index)
    from app.services.audit_service import append_activity, append_audit

    ws_dir = WORKSPACE_ROOT / ws_id
    if not _WS_ID_RE.fullmatch(ws_id) or not ws_dir.exists():
        return False, "Workspace not found", False

    meta = read_meta(ws_id) or {}
    is_creator = meta.get("creator_username") == username

    if is_creator:
        # A-H3: the deletion event must survive the workspace it describes.
        append_audit(username, ip, ws_id, "workspace deleted")
        try:
            shutil.rmtree(ws_dir)
        except FileNotFoundError:
            # A concurrent delete already removed the directory (race between
            # the existence check above and rmtree) — the goal is met, so
            # report success instead of a 500. The shared index is still
            # cleaned below.
            pass
        remove_ws_from_all_indexes(ws_id)
        return True, "Workspace deleted", True
    else:
        remove_workspace_from_index(username, ws_id)
        append_activity(ws_id, username, ip, "removed-from-own-list",
                        f"{username} removed this workspace from their list")
        return True, "Removed from your list", False
