"""R31 global heavy-operation gate (design §6.4).

All CPU-heavy operations — the debugger search and the analysis API
(/analyze, /analyze_multi) — share ONE gate and run one at a time. While one
is in progress, a new one is refused with HTTP 409 "system busy — please
wait" instead of starting in parallel and blocking the server. (The single
uvicorn worker, A-M8, already serializes; this turns the queue into a clear
user message.)

Thread-safe across FastAPI's threadpool (`def` endpoints run there) and the
event loop (`async` endpoints).
"""

import threading

_lock = threading.Lock()
_busy = False


def try_acquire() -> bool:
    """Try to take the gate. Returns True if acquired (caller must release)."""
    global _busy
    with _lock:
        if _busy:
            return False
        _busy = True
        return True


def release() -> None:
    global _busy
    with _lock:
        _busy = False


class HeavyGate:
    """Context manager — `with HeavyGate():` returns True if acquired."""

    def __enter__(self):
        self._acquired = try_acquire()
        return self._acquired

    def __exit__(self, exc_type, exc, tb):
        if self._acquired:
            release()
        return False


# R31 (#273): the shared SINGLETON gate instance. Every heavy-op endpoint
# (debugger search, /analyze, /analyze_multi) imports THIS instance so the
# global busy flag serializes all of them — one heavy op at a time, and a
# new one while busy is refused with HTTP 409 "system busy — please wait".
gate = HeavyGate()
