"""R31 in-app notifications — one file per user, all records kept.

Settled design: wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md (§5.4, §6, A-M3,
Q7) + wiki/R31_IMPLEMENTATION.md (§2.3).

- notifications/{username}.json is a JSON list of
  {id, kind: "memo"|"alert", title, body, read, created_at}.
- "memo" = the visiting user's own workspace-close summary; "alert" = the
  creator is told someone else worked on their workspace. Pull-based: the
  user sees them on next login (unread badge + inbox panel).
- ALL records are kept (user-confirmed). Writes are temp+rename on the
  owning user's file only (accepted-loss, A-M3/§6).
"""

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from app.services.workspace_service import WORKSPACE_ROOT


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(username: str) -> Path:
    return WORKSPACE_ROOT / "notifications" / f"{username}.json"


def _read(username: str) -> list[dict]:
    try:
        data = json.loads(_path(username).read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write(username: str, records: list[dict]) -> None:
    path = _path(username)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(records))
    tmp.replace(path)


def add_notification(username: str, kind: str, title: str, body: str) -> dict:
    records = _read(username)
    rec = {
        "id": secrets.token_hex(12),
        "kind": kind,
        "title": title,
        "body": body,
        "read": False,
        "created_at": _now_iso(),
    }
    records.append(rec)
    _write(username, records)
    return rec


def add_memo(username: str, ws_id: str, body: str) -> dict:
    """Visit-end memo for the visiting user (A-M10: memos carry the username —
    the caller embeds the username in `body`)."""
    title = f"[SQL Data Flow Visualizer] Workspace {ws_id} · {_now_iso()[:16]}"
    return add_notification(username, "memo", title, body)


def add_creator_alert(creator_username: str, ws_id: str, body: str) -> dict:
    """Tell the creator someone else changed their workspace."""
    title = f"[SQL Data Flow Visualizer] Workspace {ws_id} · {_now_iso()[:16]}"
    return add_notification(creator_username, "alert", title, body)


def list_notifications(username: str) -> list[dict]:
    records = _read(username)
    # newest first
    return list(reversed(records))


def unread_count(username: str) -> int:
    return sum(1 for r in _read(username) if not r.get("read"))


def mark_read(username: str, notification_id: str) -> bool:
    records = _read(username)
    changed = False
    for r in records:
        if r.get("id") == notification_id and not r.get("read"):
            r["read"] = True
            changed = True
    if changed:
        _write(username, records)
    return changed
