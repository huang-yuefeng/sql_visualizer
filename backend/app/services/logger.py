"""Structured logger for the SQL analysis pipeline.

Logs to stdout (Docker-compatible) at key stages with balanced detail.
Also fans out to per-CONSUMER thread-safe queues for SSE streaming to the
frontend.

MSC-6: this used to be ONE ref-counted queue per WORKSPACE, so two
participants (or two browser tabs) streaming the same workspace SPLIT the
stream — every pushed line was `put` exactly once and therefore consumed by
exactly one reader (a 13-line diagnostic block reached alice as 1 line and
bob as 0). The registry is now a fan-out: one bounded queue per SUBSCRIBER,
and every producer line is delivered to ALL of them.
"""
import asyncio
import itertools
import os
import queue  # thread-safe, unlike asyncio.Queue
import sys
import threading
import time

# E4 (item 7): the per-line stderr print is gated behind SQL_VIZ_LOG_STDERR
# (default OFF). Every pipeline stage previously printed to stderr with
# flush=True — when stderr is a pipe (docker logs), a blocked/backpressured
# pipe would block the calling stage, a candidate contributor to a frozen
# service. The SSE queues deliver every event to connected frontends, so
# the stderr line is redundant; set the env var to re-enable it for
# debugging. Value parsed once at import time.
_LOG_STDERR = os.environ.get("SQL_VIZ_LOG_STDERR", "").lower() not in ("", "0", "false", "no")


# ── SSE fan-out registry (MSC-6) ────────────────────────────────────────
# Shape: _log_queues[ws_id] = {consumer_id: ConsumerQueue} (insertion
# ordered). There is no separate ref counter — the live-consumer count IS
# len(_log_queues[ws_id]) (see the `_log_refs` compatibility view below).
#
# Lifecycle: a consumer queue is created by register_queue() at stream start
# and dropped by unregister_queue() in the stream's finally block, so the
# workspace's fan-out disappears with its LAST consumer. _push() only writes
# to queues that ALREADY exist — recreating one there would resurrect a
# just-dropped fan-out with nobody listening (the registry would grow
# forever; that was bug M7).
_log_queues: dict[str, dict[int, "ConsumerQueue"]] = {}
_log_lock = threading.Lock()
_consumer_ids = itertools.count(1)
_MAX_QUEUE = 500  # per consumer, so one slow tab cannot starve another

# MSC-6 slow-consumer policy, see _offer().
_drop_lock = threading.Lock()
_dropped_total = 0


class ConsumerQueue(queue.Queue):
    """One SSE subscriber's bounded log queue.

    A `queue.Queue` subclass on purpose: every existing reader keeps using
    `get` / `get_nowait` / `qsize` unchanged. The subclass only adds the
    thread→event-loop wakeup bridge so a streaming generator can wait for
    the next line WITHOUT holding an executor thread (see attach_loop).
    """

    def __init__(self, maxsize: int = _MAX_QUEUE):
        super().__init__(maxsize=maxsize)
        self.consumer_id: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Arm the thread-safe wakeup for an async consumer.

        Called once, from the consumer's own event loop, right after
        registration. Without it the queue is still fully usable — sync
        consumers simply poll it.
        """
        self._loop = loop
        self._wake = asyncio.Event()

    def wake(self) -> None:
        """Wake a waiting consumer. Called from PRODUCER threads.

        `call_soon_threadsafe` is non-blocking for the caller (it schedules
        a callback on the consumer's loop), so a busy or half-dead frontend
        stream can never stall the pipeline thread that is logging.
        """
        ev = self._wake
        loop = self._loop
        if ev is None or loop is None:
            return
        try:
            if loop.is_closed():
                return
            loop.call_soon_threadsafe(ev.set)
        except RuntimeError:
            pass  # loop already closed/shutting down — the queue still holds the line

    async def wait_ready(self, timeout: float | None = None) -> bool:
        """Wait (async) until a line MAY be available. True if woken, False on timeout.

        Safe against lost wakeups without re-polling: the event is sticky,
        and the producer sets it on EVERY push. A push that lands just
        before the clear() below leaves the event set, so the wait returns
        immediately; the caller re-drains and falls through to a clean wait.
        Worst case that costs one empty drain, never a spin — only a new
        push can set the event again.
        """
        ev = self._wake
        if ev is None:
            # No wakeup channel (sync consumer, or attach_loop not called):
            # fall back to a short poll instead of a busy loop.
            await asyncio.sleep(0.05 if timeout is None else min(0.05, timeout))
            return False
        ev.clear()
        if timeout is None:
            await ev.wait()
            return True
        try:
            await asyncio.wait_for(ev.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False


def _ts() -> str:
    return time.strftime("%H:%M:%S", time.localtime())


def _offer(q: ConsumerQueue, entry: dict) -> None:
    """Deliver one entry to ONE consumer. Never blocks the producer.

    MSC-6 slow-consumer policy: DROP-OLDEST. The queue is bounded at
    _MAX_QUEUE (500); when it is full the OLDEST buffered line is discarded
    to make room for the newest one. Rationale: a log panel is a diagnostic
    tail — the reader is watching the END of the stream, so keeping the
    newest lines and shedding the oldest beats stalling the pipeline stage
    that is logging (unacceptable) or silently dropping the newest line
    (the one the user is waiting for). Loss is counted in _dropped_total
    and readable via dropped_line_count().
    """
    try:
        q.put_nowait(entry)
        q.wake()  # nudge an idle async consumer (non-blocking)
        return
    except queue.Full:
        pass
    except Exception:
        return  # never let diagnostics break the pipeline stage

    try:
        q.get_nowait()  # shed the oldest buffered line
    except queue.Empty:
        return
    except Exception:
        return
    with _drop_lock:
        global _dropped_total
        _dropped_total += 1
    try:
        q.put_nowait(entry)
        q.wake()
    except queue.Full:
        pass  # raced with a concurrent reader filling the slot again — drop
    except Exception:
        pass


def dropped_line_count() -> int:
    """Total log lines shed by the drop-oldest policy (observability)."""
    with _drop_lock:
        return _dropped_total


def _push(ws_id: str | None, stage: str, message: str):
    """Fan a log entry out to stderr (optional) + every live SSE consumer.

    E4 (item 7): the stderr print only happens when SQL_VIZ_LOG_STDERR is
    set — a blocked stderr pipe must never stall a pipeline stage.

    MSC-6: the consumer set is snapshotted under the lock and delivered to
    OUTSIDE it, so one slow consumer's `put` cannot hold up the registry,
    the producer, or the other consumers.
    """
    if _LOG_STDERR:
        print(message, file=sys.stderr, flush=True)
    if not ws_id:
        return
    with _log_lock:
        consumers = _log_queues.get(ws_id)
        targets = list(consumers.values()) if consumers else []
    if not targets:
        return  # no active SSE consumer — do not create a queue (M7)
    entry = {"ts": _ts(), "stage": stage, "msg": message}
    for q in targets:
        _offer(q, entry)


def register_queue(ws_id: str, loop: asyncio.AbstractEventLoop | None = None) -> ConsumerQueue:
    """Register a NEW SSE consumer and return ITS OWN queue (MSC-6).

    Two subscribers on the same workspace get two independent queues and
    each receives the full stream. Call on stream start; the stream's
    finally block must call unregister_queue(ws_id, queue) with the SAME
    queue object.

    `loop` (optional): the consumer's running asyncio loop, enabling
    thread-safe wakeups so the generator waits without holding a thread.
    """
    q = ConsumerQueue()
    if loop is not None:
        q.attach_loop(loop)
    with _log_lock:
        q.consumer_id = next(_consumer_ids)
        _log_queues.setdefault(ws_id, {})[q.consumer_id] = q
    return q


def unregister_queue(ws_id: str, q: queue.Queue | None = None):
    """Remove ONE consumer's queue; drop the workspace when it is the last.

    Pass the queue returned by register_queue so exactly that consumer is
    removed — the other subscribers keep streaming.

    Legacy form (queue omitted) drops the OLDEST consumer of the workspace,
    which preserves the old "one more consumer has left" counting semantics
    for pre-existing callers that never knew about per-consumer queues.
    """
    with _log_lock:
        consumers = _log_queues.get(ws_id)
        if not consumers:
            return
        if q is None:
            consumer_id = next(iter(consumers))
        else:
            consumer_id = next((cid for cid, cq in consumers.items() if cq is q), None)
            if consumer_id is None:
                return  # unknown/already-removed consumer — never touch others
        consumers.pop(consumer_id, None)
        if not consumers:
            _log_queues.pop(ws_id, None)  # last consumer out: release everything


def remove_queue(ws_id: str):
    """Drop every consumer queue of a workspace (explicit cleanup, e.g. delete).

    Live streams are not cancelled: their generators stay in their keepalive
    wait, which is what they did before the workspace disappeared. Ending the
    HTTP stream here would only make the browser's EventSource reconnect and
    re-register a queue for a workspace that no longer exists.
    """
    with _log_lock:
        consumers = _log_queues.pop(ws_id, None)
    if consumers:
        for q in consumers.values():
            q.wake()  # let idle generators notice the (now empty) fan-out


def ensure_queue(ws_id: str) -> ConsumerQueue:
    """Deprecated MSC-6 compatibility shim.

    "The queue for a workspace" no longer exists — every consumer owns one.
    This now registers a NEW consumer, exactly like register_queue(), and
    must be paired with unregister_queue(ws_id, queue). Kept only for
    external callers documented against the old API (REQUIREMENTS.md); there
    are no in-repo callers.
    """
    return register_queue(ws_id)


def __getattr__(name: str):
    """PEP 562 module attribute hook.

    `_log_refs` was the pre-MSC-6 per-workspace consumer ref-count. The
    count is now DERIVED from the registry (there is a single source of
    truth), so this returns a snapshot mapping for existing readers/tests.
    Mutating the snapshot has no effect.
    """
    if name == "_log_refs":
        with _log_lock:
            return {ws: len(consumers) for ws, consumers in _log_queues.items()}
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
