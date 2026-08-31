"""R31 global heavy-operation gate (design §6.4).

All CPU-heavy operations — the debugger search and the analysis API
(/analyze, /analyze_multi) — share ONE gate and run one at a time. While one
is in progress, a new one is refused with HTTP 409 "system busy — please
wait" instead of starting in parallel and blocking the server. (The single
uvicorn worker, A-M8, already serializes; this turns the queue into a clear
user message.)

Thread-safe across FastAPI's threadpool (`def` endpoints run there) and the
event loop (`async` endpoints).

MSC-1 (2026-08-31): the gate is RELEASE-PROOF. ``HeavyGate`` no longer keeps
per-call state on itself — the module-level singleton is entered concurrently
by every heavy-op endpoint, so a refused entrant used to overwrite the
holder's ``_acquired`` and neither ``__exit__`` released: ``_busy`` stayed
True FOREVER and every search (any user, any workspace) answered 409 until
the process restarted. The acquisition now lives on a per-call token that
only the ``__exit__`` matching its own ``__enter__`` can release.
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


class _GateToken:
    """What ONE ``with HeavyGate():`` call received (MSC-1).

    ``acquired`` is THIS call's own outcome — nothing any other caller does
    can change it, so the holder's release can no longer be lost to a
    concurrent refused entrant.
    """

    __slots__ = ("acquired", "released")

    def __init__(self, acquired: bool):
        self.acquired = acquired
        self.released = False

    def __bool__(self) -> bool:
        # The routers do `with gate as acquired: if not acquired: 409`.
        return self.acquired

    def release(self) -> None:
        # Idempotent: a second __exit__ (or any double release) is a no-op, so
        # a bookkeeping slip can never release someone else's slot either.
        if self.released:
            return
        self.released = True
        if self.acquired:
            release()


class HeavyGate:
    """Context manager — `with gate as acquired:` binds a token that is truthy
    iff THIS call took the gate (falsy → answer 409 and move on).

    Per-call bookkeeping is a per-thread LIFO stack (the same accounting
    ``threading.RLock`` does): nested ``with`` blocks on one thread each get
    their own token, and the innermost one unwinds first. An entrant on
    ANOTHER thread has its own stack, so a concurrent refused entrant can
    never touch the holder's token — the MSC-1 wedge. Enter and exit run on
    the same thread at every call site (`with gate:` inside an `async def`
    handler; only the CPU-bound body is sent to a worker thread), so the
    per-thread stack always sees the matching pair.
    """

    def __init__(self):
        self._local = threading.local()

    def __enter__(self) -> "_GateToken":
        token = _GateToken(try_acquire())
        self._tokens().append(token)
        return token

    def __exit__(self, exc_type, exc, tb) -> bool:
        tokens = self._tokens()
        if tokens:
            tokens.pop().release()
        return False  # never swallow the caller's exception (the 409 raise)

    def _tokens(self):
        tokens = getattr(self._local, "tokens", None)
        if tokens is None:
            tokens = self._local.tokens = []
        return tokens


# R31 (#273): the shared SINGLETON gate instance. Every heavy-op endpoint
# (debugger search, /analyze, /analyze_multi) imports THIS instance so the
# global busy flag serializes all of them — one heavy op at a time, and a
# new one while busy is refused with HTTP 409 "system busy — please wait".
gate = HeavyGate()
