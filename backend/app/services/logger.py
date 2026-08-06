"""Structured logger for the SQL analysis pipeline.

Logs to stdout (Docker-compatible) at key stages with balanced detail.
Also pushes to per-workspace thread-safe queues for SSE streaming to frontend.
"""
import time
import sys
import queue  # thread-safe, unlike asyncio.Queue
import threading

# ── SSE queue registry ──────────────────────────────────────────────────
# Per-workspace thread-safe queues for frontend log streaming.
# queue.Queue is thread-safe — safe to put() from sync thread pool threads.
_log_queues: dict[str, queue.Queue] = {}
# L2: registry mutations are guarded by a lock; _log_refs counts active SSE
# streams per workspace so a queue is only dropped when the LAST consumer
# disconnects (auto-cleanup — was: removed only on explicit delete).
_log_lock = threading.Lock()
_log_refs: dict[str, int] = {}
_MAX_QUEUE = 500


def _ts() -> str:
    return time.strftime("%H:%M:%S", time.localtime())


def _push(ws_id: str | None, stage: str, message: str):
    """Push a log entry to stderr + optionally the thread-safe SSE queue."""
    print(message, file=sys.stderr, flush=True)
    if ws_id:
        try:
            # M7: only put when a queue ALREADY exists. register_queue creates
            # it before any stream starts; unregister_queue pops it when the
            # last SSE client disconnects. Recreating it here (the old
            # ensure_queue call) would resurrect a just-dropped queue with
            # nobody listening — the registry would grow forever.
            with _log_lock:
                q = _log_queues.get(ws_id)
            if q is None:
                return  # no active SSE consumer — skip the put
            entry = {"ts": _ts(), "stage": stage, "msg": message}
            if q.qsize() < _MAX_QUEUE:
                q.put_nowait(entry)
        except Exception:
            pass  # queue full or other error — silently skip


def ensure_queue(ws_id: str) -> queue.Queue:
    """Get or create the thread-safe queue for a workspace."""
    with _log_lock:
        if ws_id not in _log_queues:
            _log_queues[ws_id] = queue.Queue(maxsize=_MAX_QUEUE)
        return _log_queues[ws_id]


def register_queue(ws_id: str) -> queue.Queue:
    """Mark an active SSE consumer for a workspace (L2: auto-cleanup).

    Returns the shared queue. Call on stream start; the stream's finally
    block must call unregister_queue.
    """
    with _log_lock:
        q = _log_queues.get(ws_id)
        if q is None:
            q = _log_queues[ws_id] = queue.Queue(maxsize=_MAX_QUEUE)
        _log_refs[ws_id] = _log_refs.get(ws_id, 0) + 1
        return q


def unregister_queue(ws_id: str):
    """Drop a consumer's reference; remove the queue when the last one leaves.

    L2: SSE streams auto-clean their queue on disconnect instead of leaving
    it in the registry forever.
    """
    with _log_lock:
        remaining = _log_refs.get(ws_id, 0) - 1
        if remaining > 0:
            _log_refs[ws_id] = remaining
        else:
            _log_refs.pop(ws_id, None)
            _log_queues.pop(ws_id, None)


def remove_queue(ws_id: str):
    """Remove the queue for a workspace (explicit cleanup, e.g. delete)."""
    with _log_lock:
        _log_refs.pop(ws_id, None)
        _log_queues.pop(ws_id, None)


# ── Pipeline stages ────────────────────────────────────────────────────

def pipeline_start(script_name: str, sql_len: int, ws_id: str | None = None):
    msg = f"[{_ts()}] ⏳ PIPELINE START  script={script_name}  sql_bytes={sql_len}"
    _push(ws_id, "parse", msg)


def stage_extract(variable_count: int, table_count: int, cte_count: int,
                  ws_id: str | None = None):
    msg = f"[{_ts()}]   ▶ extract  vars={variable_count}  tables={table_count}  ctes={cte_count}"
    _push(ws_id, "extract", msg)


def stage_deps(edge_count: int, by_type: dict, ws_id: str | None = None):
    summary = "  ".join(f"{k}={v}" for k, v in sorted(by_type.items())[:6])
    msg = f"[{_ts()}]   ▶ deps  edges={edge_count}  {summary}"
    _push(ws_id, "deps", msg)


def stage_graph(nodes: int, edges: int, ws_id: str | None = None):
    msg = f"[{_ts()}]   ▶ graph  nodes={nodes}  edges={edges}"
    _push(ws_id, "graph", msg)


def pipeline_done(total_ms: float, ws_id: str | None = None):
    msg = f"[{_ts()}] ✅ PIPELINE DONE  elapsed={total_ms:.0f}ms"
    _push(ws_id, "done", msg)


def api_request(method: str, path: str, status: int, detail: str = "",
                ws_id: str | None = None):
    extra = f"  {detail}" if detail else ""
    msg = f"[{_ts()}] 🌐 {method} {path}  → {status}{extra}"
    _push(ws_id, "info", msg)


def pipeline_profile(script_name: str, counts: dict, ws_id: str | None = None):
    """Emit a compact, photographable ASCII profile block after pipeline completes.

    counts dict keys:
      sql_len, line_count, stmt_count, stmt_types, clauses,
      funcs, var_types, edge_types, nesting, timing
    """
    W = 80
    def _line(text: str):
        """Pad a content line to fit inside │...│ borders."""
        inner = text.ljust(W - 4)
        return f"│ {inner}│"

    def _kv(prefix: str, d: dict) -> str:
        parts = [f"{k}={v}" for k, v in sorted(d.items())]
        if not parts:
            return f"{prefix}: (none)"
        return f"{prefix}: " + " ".join(parts)

    t = counts.get("timing", {})
    timing_str = (
        f"Parse: {t.get('parse',0)}ms  Extract: {t.get('extract',0)}ms  "
        f"Deps: {t.get('deps',0)}ms  Graph: {t.get('graph',0)}ms  "
        f"Total: {t.get('total',0)}ms"
    )

    lines = [
        f"┌─ SCRIPT PROFILE: {script_name} " + "─" * (W - 24 - len(script_name)) + "┐",
        _line(f"Size: {counts.get('sql_len',0)}B  Lines: {counts.get('line_count',0)}  Stmts: {counts.get('stmt_count',0)}    {timing_str}"),
        _line(_kv("Stmts", counts.get("stmt_types", {}))),
        _line(_kv("Clauses", counts.get("clauses", {}))),
        _line(_kv("Funcs", counts.get("funcs", {}))),
        _line(_kv("Vars", counts.get("var_types", {}))),
        _line(_kv("Edges", counts.get("edge_types", {}))),
        _line(_kv("Nesting", counts.get("nesting", {}))),
        f"└{'─' * (W - 2)}┘",
    ]

    for line in lines:
        _push(ws_id, "profile", line)
