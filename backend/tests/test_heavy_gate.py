"""MSC-1 — the heavy gate is release-proof (unit tests on the gate itself).

The defect (CRITICAL, found live by the MSC multi-user audit): ``HeavyGate``
kept per-call state (``self._acquired``) on the MODULE-LEVEL SINGLETON every
heavy-op endpoint shares. A second — 409-refused — entrant overwrote the
holder's ``True`` before the holder unwound, so neither ``__exit__`` called
``release()`` and the module global ``_busy`` stayed True FOREVER: every
search on every workspace (and every /analyze) answered 409 "system busy —
please wait" until the container restarted. Reproduced live at 0% CPU after
one concurrent burst.

The fix: per-call tokens. ``__enter__`` returns a token carrying ITS OWN
acquired flag; ``__exit__`` releases only what ITS OWN ``__enter__`` acquired,
once. These tests pin the deterministic wedge sequence plus the contract the
routers depend on. End-to-end 409 coverage lives in test_r31_gate.py (search
+ /analyze) and test_multiuser_workspace.py / test_multiuser_sessions.py
(concurrent bursts).
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import heavy_gate

client = TestClient(app)


@pytest.fixture(autouse=True)
def _gate_idle(monkeypatch):
    """Every test starts from (and leaves behind) an idle gate.

    The tests here drive the module global ``_busy`` through its public API;
    the forced reset is only the safety net that keeps a failure in ONE test
    from turning every later search in the suite into a 409 — the exact
    blast radius MSC-1 had.
    """
    monkeypatch.setattr(heavy_gate, "_busy", False)
    yield
    heavy_gate.release()


# ── the deterministic MSC-1 wedge sequence ────────────────────────────────


def test_two_overlapping_enters_lose_nothing():
    """The exact sequence that wedged the gate: two enters on the shared
    singleton, the refused one unwinding FIRST."""
    g = heavy_gate.HeavyGate()
    first = g.__enter__()
    second = g.__enter__()
    try:
        assert first            # the call that owns the gate
        assert not second       # the 409-refused concurrent call
        assert heavy_gate._busy is True
    finally:
        g.__exit__(None, None, None)   # the refused entrant unwinds first
        g.__exit__(None, None, None)   # the real holder unwinds
    assert heavy_gate._busy is False, "MSC-1: the gate stayed busy"
    assert heavy_gate.try_acquire() is True, "the gate is unusable afterwards"
    heavy_gate.release()


def test_refused_entrant_on_another_thread_never_touches_the_holder():
    """The live shape of the wedge: a holder on one thread, a 409-refused
    request on another, the REFUSED one unwinding before the holder."""
    g = heavy_gate.HeavyGate()
    holder_entered = threading.Event()
    refused_done = threading.Event()
    holder_may_unwind = threading.Event()
    refused = []

    def holder():
        assert g.__enter__().acquired is True
        holder_entered.set()
        holder_may_unwind.wait(5)
        g.__exit__(None, None, None)

    def refused_entrant():
        token = g.__enter__()
        refused.append(bool(token))
        g.__exit__(None, None, None)
        refused_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        h = pool.submit(holder)
        assert holder_entered.wait(5)
        pool.submit(refused_entrant).result(timeout=5)
        assert refused_done.wait(5)
        # the refusal has already unwound — the old code had by now clobbered
        # the holder's flag and the gate stayed busy forever after this point
        assert refused == [False]
        assert heavy_gate._busy is True
        holder_may_unwind.set()
        h.result(timeout=5)

    assert heavy_gate._busy is False, "MSC-1: the holder's release was lost"
    assert heavy_gate.try_acquire() is True
    heavy_gate.release()


def test_five_caller_burst_leaves_the_gate_usable():
    """MSC's live repro: 5 simultaneous heavy ops, then a sequential one."""
    g = heavy_gate.HeavyGate()
    entered = []

    def burst(i):
        token = g.__enter__()
        entered.append(bool(token))
        g.__exit__(None, None, None)

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(burst, range(5)))

    assert sum(entered) >= 1                     # somebody owned the gate
    assert len(entered) == 5                     # every caller got an answer
    assert heavy_gate._busy is False, "MSC-1: one burst wedged the gate"
    with g as acquired:                          # the next search goes through
        assert acquired
    assert heavy_gate._busy is False


# ── token semantics ───────────────────────────────────────────────────────


def test_refused_call_is_falsy_so_the_router_answers_409():
    """`with gate as acquired: if not acquired: raise HTTPException(409)` —
    the contract every heavy-op router relies on, unchanged."""
    with heavy_gate.gate as acquired:
        assert acquired                          # the holder proceeds
        with heavy_gate.gate as refused:
            assert not refused                   # → the 409 branch


def test_nested_with_blocks_each_release_their_own_call():
    g = heavy_gate.HeavyGate()
    with g as outer:
        assert outer
        with g as inner:
            assert not inner
    assert heavy_gate._busy is False
    with g as again:
        assert again
    assert heavy_gate._busy is False


def test_double_exit_is_idempotent():
    """A double `__exit__` releases at most once — never someone else's slot."""
    g = heavy_gate.HeavyGate()
    token = g.__enter__()
    assert token.acquired is True
    g.__exit__(None, None, None)
    g.__exit__(None, None, None)          # stray second unwind
    assert token.released is True
    assert heavy_gate._busy is False
    g.__exit__(None, None, None)          # an unwind with nothing held: no-op
    assert heavy_gate._busy is False
    assert heavy_gate.try_acquire() is True
    heavy_gate.release()


def test_release_is_idempotent():
    heavy_gate.release()
    heavy_gate.release()
    assert heavy_gate._busy is False
    assert heavy_gate.try_acquire() is True
    heavy_gate.release()


def test_try_acquire_refuses_without_touching_the_holder():
    """The module-level pair the routers' 409 path rests on stays exact."""
    assert heavy_gate.try_acquire() is True
    assert heavy_gate.try_acquire() is False
    assert heavy_gate._busy is True
    heavy_gate.release()
    assert heavy_gate.try_acquire() is True
    heavy_gate.release()


# ── the 409 contract the routers rely on ──────────────────────────────────


def test_busy_heavy_op_still_answers_409_then_recovers():
    """A refused caller gets the same 409 "system busy — please wait" as
    before, and the gate is free the moment the holder is done."""
    assert heavy_gate.try_acquire() is True
    try:
        r = client.post("/api/analyze", data={"sql_text": "SELECT 1"})
        assert r.status_code == 409
        assert r.json()["detail"] == "system busy — please wait"
    finally:
        heavy_gate.release()
    r = client.post("/api/analyze", data={"sql_text": "SELECT 1"})
    assert r.status_code == 200


def test_exception_inside_the_gate_still_releases():
    """A failing heavy op unwinds through __exit__ and frees the gate — it
    must not take every later search down with it."""
    with pytest.raises(RuntimeError):
        with heavy_gate.gate as acquired:
            assert acquired
            raise RuntimeError("analysis blew up")
    assert heavy_gate._busy is False
    with heavy_gate.gate as acquired:
        assert acquired


# ── hammer: real concurrency on the shared singleton ──────────────────────


def test_eight_thread_hammer_never_wedges_never_overlaps():
    """8 threads × 50 attempts on the SINGLETON the endpoints share.

    Deterministic properties, whatever the interleaving:
      * at most ONE holder at any instant (mutual exclusion);
      * exactly one release per successful acquire (no wedge, no over-release);
      * the gate is idle — and usable — when the hammer stops.
    """
    gate = heavy_gate.gate
    guard = threading.Lock()
    state = {"in_critical": 0, "successes": 0, "releases": 0}
    overlap = []

    real_release = heavy_gate.release

    def spy_release():
        with guard:
            state["releases"] += 1
        real_release()

    patch = pytest.MonkeyPatch()
    patch.setattr(heavy_gate, "release", spy_release)
    try:

        def attempt(_i):
            with gate as acquired:
                if not acquired:
                    return
                with guard:
                    state["successes"] += 1
                    if state["in_critical"]:
                        overlap.append(state["in_critical"])
                    state["in_critical"] += 1
                time.sleep(0.0005)   # widen the window an overlap must cross
                with guard:
                    state["in_critical"] -= 1

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(attempt, range(8 * 50)))
    finally:
        patch.undo()

    assert not overlap, f"{len(overlap)} mutual-exclusion violations"
    assert state["successes"] > 0
    assert state["releases"] == state["successes"], (
        f"{state['successes']} acquires but {state['releases']} releases — "
        "the gate leaks")
    assert heavy_gate._busy is False, "the hammer left the gate busy"
    with gate as acquired:
        assert acquired, "the gate is unusable after the hammer"


# ── the singleton is shared, and stays a singleton ────────────────────────


def test_endpoints_share_one_gate_instance():
    """/search and /analyze serialize through the SAME module-global flag —
    that shared state is what made MSC-1 service-wide."""
    from app.routers import analysis as analysis_router
    from app.routers import dataflow as dataflow_router

    assert analysis_router.gate is heavy_gate.gate
    assert dataflow_router.gate is heavy_gate.gate
