"""Workspace service — zip extraction, directory management, multi-user isolation."""
import json
import shutil
import zipfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_ROOT = Path("/tmp/workspaces")


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
            pass
    return removed


def cleanup_all_workspaces() -> int:
    """Remove ALL workspaces. Returns count removed."""
    _ensure_root()
    removed = 0
    for ws_dir in list(WORKSPACE_ROOT.iterdir()):
        if ws_dir.is_dir():
            shutil.rmtree(ws_dir)
            removed += 1
    return removed


def _ensure_root():
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

def create_workspace(zip_bytes: bytes) -> str:
    """Extract zip archive, return workspace_id."""
    _ensure_root()
    ws_id = uuid.uuid4().hex[:12]
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
            # Security: prevent path traversal
            target = (scripts_dir / member).resolve()
            if not str(target).startswith(str(scripts_dir.resolve())):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, 'wb') as dst:
                dst.write(src.read())

    # Write metadata
    meta = {
        "workspace_id": ws_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "indexed": False,
        "indexed_scripts": [],
    }
    (ws_dir / "meta.json").write_text(json.dumps(meta))
    return ws_id

def get_workspace(ws_id: str) -> dict | None:
    """Return workspace metadata, or None if not found."""
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
    if not str(target).startswith(str(scripts_dir.resolve())):
        return None
    if not target.exists():
        return None
    return target

def get_workspace_dir(ws_id: str) -> Path:
    return WORKSPACE_ROOT / ws_id
