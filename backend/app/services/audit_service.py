"""R31 append-only audit logs: per-workspace activity + server-global audit.

Settled design: wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md (§5.4, §6, A-M3,
A-H3) + wiki/R31_IMPLEMENTATION.md (§2.2).

- activity.json (per workspace) and audit.json (server-global) are NDJSON:
  one `{...}` record per line, appended with O_APPEND — REAL appends, never
  read-modify-write, so concurrent appends are never lost (A-M3).
- The creator's physical DELETE is recorded in the SERVER-GLOBAL audit log
  BEFORE the workspace is removed (A-H3) — the per-workspace activity file is
  removed with the workspace, so the deletion event must live outside it.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from app.services.workspace_service import WORKSPACE_ROOT


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_record(path: Path, record: dict) -> None:
    """Append one NDJSON line with O_APPEND — real append, no read-modify-write."""
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    fd = os.open(str(path), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def append_activity(ws_id: str, username: str, ip: str, action: str,
                    detail: str | None = None) -> None:
    """Per-workspace activity log record (any opener can read the history)."""
    record = {
        "username": username,
        "ip": ip,
        "ts": _now_iso(),
        "action": action,
        "detail": detail,
    }
    _append_record(WORKSPACE_ROOT / ws_id / "activity.json", record)


def append_audit(username: str, ip: str, ws_id: str, action: str) -> None:
    """Server-global audit log — survives the workspace it describes (A-H3)."""
    record = {
        "username": username,
        "ip": ip,
        "ts": _now_iso(),
        "ws_id": ws_id,
        "action": action,
    }
    _append_record(WORKSPACE_ROOT / "audit.json", record)


def read_activity(ws_id: str) -> list[dict]:
    """Read the workspace's history (for the history panel). Never raises."""
    path = WORKSPACE_ROOT / ws_id / "activity.json"
    records = []
    try:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn tail record is skipped, not fatal
    except Exception:
        return []
    return records


def read_audit() -> list[dict]:
    """Read the server-global audit log. Never raises."""
    path = WORKSPACE_ROOT / "audit.json"
    records = []
    try:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception:
        return []
    return records
