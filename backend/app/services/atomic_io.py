"""Atomic file writes for cache/index artifacts (P1, item 3-i).

Every index/cache/meta write used to be a truncate+write_text. A concurrent
reader (participant POST /search loading the index, GET /index, l2_builder's
cache read, filter_service) could observe a half-written file: an
intermittent 500, or — worse — a silently EMPTY index served as if it were
the truth. The temp-name + os.replace form makes a reader see either the
whole old file or the whole new one, never a torn one, and lets concurrent
writers each own their temp file.

Promoted from dataflow_service._atomic_write_text (E4 item 8), which now
delegates here so both index-layer and graph-layer writers share one
implementation.
"""
import os
import uuid
from pathlib import Path

__all__ = ["atomic_write_text", "atomic_write_bytes"]


def _replace(tmp: Path, path: Path) -> None:
    os.replace(tmp, path)  # atomic on the same filesystem


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write ``text`` via a unique temp file + os.replace."""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(text, encoding)
        _replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass  # best-effort — the previous artifact stays intact
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` via a unique temp file + os.replace."""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_bytes(data)
        _replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
