"""R31 append-only audit logs: per-workspace activity + server-global audit.

Settled design: wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md (§5.4, §6, A-M3,
A-H3) + wiki/R31_IMPLEMENTATION.md (§2.2).

- activity.json (per workspace) and audit.json (server-global) are NDJSON:
  one `{...}` record per line, appended with O_APPEND — REAL appends, never
  read-modify-write, so concurrent appends are never lost (A-M3).
- The creator's physical DELETE is recorded in the SERVER-GLOBAL audit log
  BEFORE the workspace is removed (A-H3) — the per-workspace activity file is
  removed with the workspace, so the deletion event must live outside it.

MSC-3 (the multi-user audit trail): #285 had dropped visit logging and the
other actions were never written, so a trail that the History panel labels as
"who did what" held exactly one record (`workspace_created`) no matter what a
participant did. The full action set is now written (see the hook points in
app/routers/workspace.py + app/routers/dataflow.py), and the trail is
BOUNDED — the MSC-5 views.json lesson: a busy shared workspace must not be
able to grow a per-workspace file without limit.
"""

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:  # POSIX only — the service runs in a Linux container
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

from app.services.atomic_io import atomic_write_text
from app.services.workspace_service import WORKSPACE_ROOT, is_valid_ws_id

# ── MSC-3: the per-workspace trail is bounded ─────────────────────────────
# Last ACTIVITY_CAP records kept per workspace — the invariant is exact
# (the trail NEVER holds more than ACTIVITY_CAP records), which is what an
# audit surface should promise and what makes "last 200" readable as a fact.
# A trail at the cap is a few dozen KB, so rewriting it on each append past
# the cap costs microseconds; a deploy that would rather amortize those
# rewrites can raise _ACTIVITY_TRIM_SLACK (the trail then oscillates between
# CAP and CAP+SLACK — see tests/test_audit_trail.py).
ACTIVITY_CAP = 200
_ACTIVITY_TRIM_SLACK = 0
# A detail string is clipped so one huge payload can never blow the trail
# past the cap (the trim counts RECORDS, not bytes).
_DETAIL_MAX = 200
# Dotfile (never mistaken for a workspace artifact by anything that walks a
# workspace dir) and NOT activity.json itself: the trim does os.replace, which
# swaps the inode out from under a lock held on the data file.
_TRAIL_LOCK_NAME = ".activity.lock"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_record(path: Path, record: dict) -> None:
    """Append one NDJSON line with O_APPEND — real append, no read-modify-write.

    Creates the record's parent dir (not just WORKSPACE_ROOT) so a concurrent
    delete of the workspace dir doesn't 500 the append. Writes the full buffer
    in a loop — os.write may return fewer bytes than asked, and a single-shot
    write would silently drop the tail."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    data = line.encode("utf-8")
    fd = os.open(str(path), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        view = memoryview(data)
        while view:
            n = os.write(fd, view)
            view = view[n:]
    finally:
        os.close(fd)


@contextmanager
def _trail_lock(ws_id: str):
    """Serialize this workspace's append+trim pairs.

    The append itself stays a REAL O_APPEND write (never lost on its own), but
    the MSC-3 cap trim IS a read-modify-write: a concurrent append landing
    between the trim's read and its os.replace would be silently dropped. A
    dedicated lock file keeps every appender of ONE workspace serialized for
    that window (other workspaces never contend — the lock is per-workspace).
    Where fcntl is unavailable the trail degrades to plain O_APPEND: records
    still append, only the cap becomes best-effort. Never raises.
    """
    path = WORKSPACE_ROOT / ws_id / _TRAIL_LOCK_NAME
    fd = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        fd = None  # no lock — append anyway (an audit failure must not fail a request)
    try:
        yield
    finally:
        if fd is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


def _trim_to_cap(path: Path) -> None:
    """Keep only the last ACTIVITY_CAP records (MSC-5's views.json lesson).

    Caller holds the trail lock, so no append can be dropped by the replace.
    Cheap: a trail at the cap is a few dozen KB and the count short-circuits
    the rewrite while the file is under the cap.
    Never raises — housekeeping must not fail the user's request.
    """
    try:
        with path.open("r", encoding="utf-8") as fh:
            total = sum(1 for line in fh if line.strip())
        if total <= ACTIVITY_CAP + _ACTIVITY_TRIM_SLACK:
            return
        records = [line for line in path.read_text(encoding="utf-8").splitlines()
                   if line.strip()]
        atomic_write_text(path, "\n".join(records[-ACTIVITY_CAP:]) + "\n")
    except Exception:
        pass  # an over-cap trail is a cosmetic problem, never a 500


def append_activity(ws_id: str, username: str, ip: str, action: str,
                    detail: str | None = None) -> None:
    """Per-workspace activity log record (any opener can read the history).

    MSC-4: the record shape is the R31 one the History panel already renders
    ({username, ip, ts, action, detail}) — the ip is part of the EXISTING
    format, so it stays; nothing new is added to it.
    """
    if detail is not None:
        detail = str(detail)[:_DETAIL_MAX]
    if not is_valid_ws_id(ws_id or ""):
        return  # defense-in-depth: never build a path from an unvalidated id
    record = {
        "username": username,
        "ip": ip,
        "ts": _now_iso(),
        "action": action,
        "detail": detail,
    }
    path = WORKSPACE_ROOT / ws_id / "activity.json"
    with _trail_lock(ws_id):
        _append_record(path, record)
        _trim_to_cap(path)


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
        # X2 (review): the encoding is NAMED. `_append_record` writes
        # `json.dumps(..., ensure_ascii=False)` — raw UTF-8 bytes — so a reader
        # that leaves the encoding to the locale decodes correctly only where
        # the preferred encoding happens to be UTF-8. Under a C/POSIX locale
        # (PYTHONCOERCECLOCALE=0 LC_ALL=C) the first non-ASCII detail (a
        # Chinese table name in a search's detail, a UTF-8 username) raises
        # UnicodeDecodeError here, which the `except Exception` below swallows
        # into `[]` — the History panel went silently blank rather than error.
        for line in path.read_text(encoding="utf-8").splitlines():
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
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception:
        return []
    return records
