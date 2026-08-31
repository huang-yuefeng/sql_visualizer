"""MSC-6: the SSE log pipeline must BROADCAST, not split.

The pre-fix registry kept ONE queue per WORKSPACE, ref-counted across
consumers. Two participants (or two browser tabs) streaming the same
workspace therefore SPLIT the stream: every pushed line was `put` exactly
once, so exactly one reader drained it — a 13-line diagnostic block reached
alice as 1 line and bob as 0, i.e. the LogPanel silently lost a random ~1/N
of the stream. Each stream also parked a default-executor thread
indefinitely (`run_in_executor(q.get(timeout=1))` while idle).

The registry is now a fan-out: one bounded queue per SUBSCRIBER, and every
producer line is delivered to ALL of them. These tests pin that contract:

  * two concurrent subscribers on one workspace both receive EVERY line,
  * unsubscribing removes only that consumer's queue,
  * a slow/full consumer never blocks the producer (drop-oldest),
  * a single consumer sees exactly what it saw before (order + content),
  * the last unsubscribe releases the workspace's resources (no leak),
  * the SSE generator parks NO executor thread while idle.
"""

import asyncio
import json
import queue
import threading
import time

import pytest

from app.routers.logs import stream_logs
from app.services import logger as logger_mod


BLOCK_LINES = 13  # the size of the diagnostic block from the finding


@pytest.fixture
def clean_registry():
    logger_mod._log_queues.clear()
    with logger_mod._drop_lock:
        logger_mod._dropped_total = 0
    yield
    logger_mod._log_queues.clear()
    with logger_mod._drop_lock:
        logger_mod._dropped_total = 0


def _drain(q) -> list:
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


# ═══════════════ 1. the split-stream repro ═══════════════

def test_two_subscribers_both_receive_every_line(clean_registry):
    """THE bug: two consumers on one workspace must not divide the stream."""
    ws = "msc6_ws_two"
    alice = logger_mod.register_queue(ws)
    bob = logger_mod.register_queue(ws)

    for i in range(BLOCK_LINES):
        logger_mod._push(ws, "info", f"diag-line-{i}")

    a, b = _drain(alice), _drain(bob)
    expected = [f"diag-line-{i}" for i in range(BLOCK_LINES)]
    assert [e["msg"] for e in a] == expected, \
        f"alice got {len(a)}/{BLOCK_LINES} lines: {[e['msg'] for e in a]}"
    assert [e["msg"] for e in b] == expected, \
        f"bob got {len(b)}/{BLOCK_LINES} lines: {[e['msg'] for e in b]}"


def test_three_subscribers_all_get_the_full_stream(clean_registry):
    """Fan-out is not limited to two: N subscribers each see 100% of it."""
    ws = "msc6_ws_three"
    consumers = [logger_mod.register_queue(ws) for _ in range(3)]
    for i in range(BLOCK_LINES):
        logger_mod._push(ws, "profile", f"line-{i}")
    for n, q in enumerate(consumers):
        assert [e["msg"] for e in _drain(q)] == [f"line-{i}" for i in range(BLOCK_LINES)], \
            f"consumer {n} lost lines"


def test_unsubscribe_removes_only_that_consumer(clean_registry):
    """Leaving one tab must not disturb the other subscriber's stream."""
    ws = "msc6_ws_leave"
    alice = logger_mod.register_queue(ws)
    bob = logger_mod.register_queue(ws)

    logger_mod.unregister_queue(ws, alice)
    assert ws in logger_mod._log_queues, "bob's fan-out was dropped too"

    logger_mod._push(ws, "info", "only-bob-should-see-this")
    assert _drain(alice) == [], "unsubscribed consumer still received lines"
    bob_lines = _drain(bob)
    assert [e["msg"] for e in bob_lines] == ["only-bob-should-see-this"]

    logger_mod.unregister_queue(ws, bob)
    assert ws not in logger_mod._log_queues
    assert ws not in logger_mod._log_refs


def test_unregister_of_unknown_queue_never_touches_others(clean_registry):
    """A stale/foreign queue object must not pop somebody else's consumer."""
    ws = "msc6_ws_stale"
    live = logger_mod.register_queue(ws)
    stranger = logger_mod.ConsumerQueue()
    logger_mod.unregister_queue(ws, stranger)
    assert ws in logger_mod._log_queues
    logger_mod._push(ws, "info", "still-alive")
    assert [e["msg"] for e in _drain(live)] == ["still-alive"]


def test_bare_unregister_drops_oldest_consumer(clean_registry):
    """Legacy no-queue form still counts 'one consumer left' (FIFO)."""
    ws = "msc6_ws_legacy"
    first = logger_mod.register_queue(ws)
    second = logger_mod.register_queue(ws)
    logger_mod.unregister_queue(ws)          # no queue → oldest (first) leaves
    logger_mod._push(ws, "info", "legacy")
    assert _drain(first) == [], "the oldest consumer should have been dropped"
    assert [e["msg"] for e in _drain(second)] == ["legacy"]
    logger_mod.unregister_queue(ws)
    assert ws not in logger_mod._log_queues


# ═══════════════ 2. slow consumer: producer never blocks ═══════════════

def test_slow_consumer_never_blocks_producer_and_fast_is_unaffected(clean_registry):
    """Policy = DROP-OLDEST per consumer queue (bounded at _MAX_QUEUE).

    The slow tab's queue is pre-filled to capacity; pushing must still be
    O(1) non-blocking per line, the fast tab must lose nothing, and the slow
    tab keeps the NEWEST lines (the diagnostic tail it is watching).
    """
    ws = "msc6_ws_slow"
    slow = logger_mod.register_queue(ws)
    fast = logger_mod.register_queue(ws)

    filler = {"ts": "00:00:00", "stage": "info", "msg": "stale"}
    for _ in range(logger_mod._MAX_QUEUE):  # slow consumer stops reading
        slow.put(dict(filler))
    assert slow.qsize() == logger_mod._MAX_QUEUE

    total = 400  # < _MAX_QUEUE: the fast consumer can absorb every line
    dropped_before = logger_mod.dropped_line_count()
    started = time.perf_counter()
    for i in range(total):
        logger_mod._push(ws, "info", f"line-{i}")
    elapsed = time.perf_counter() - started

    # 400 pushes into a FULL queue: non-blocking. The old blocking-put design
    # would have stalled here; even a blocking hand-off would be seconds.
    assert elapsed < 2.0, f"producer blocked on a full consumer queue: {elapsed:.2f}s"

    fast_lines = _drain(fast)
    assert [e["msg"] for e in fast_lines] == [f"line-{i}" for i in range(total)], \
        f"fast consumer lost {total - len(fast_lines)} lines to the slow one"

    # The slow consumer is still bounded, and holds the newest lines.
    assert slow.qsize() <= logger_mod._MAX_QUEUE
    slow_lines = _drain(slow)
    assert slow_lines[-1]["msg"] == f"line-{total - 1}", "newest line was dropped"
    assert len(slow_lines) == logger_mod._MAX_QUEUE
    # 400 sheds (one per push) + the 100 oldest fillers that were pushed out
    assert len([e for e in slow_lines if e["msg"] == "stale"]) == \
        logger_mod._MAX_QUEUE - total
    assert logger_mod.dropped_line_count() - dropped_before == total

    # Both consumers were independent: dropping for one never touched the other.
    logger_mod.unregister_queue(ws, slow)
    logger_mod.unregister_queue(ws, fast)
    assert ws not in logger_mod._log_queues


# ═══════════════ 3. single consumer: unchanged behavior ═══════════════

def test_single_consumer_stream_identical_to_previous_behavior(clean_registry):
    """Backward compat: one subscriber sees the full stream, in order,
    with the same entry shape the LogPanel already parses."""
    ws = "msc6_ws_single"
    q = logger_mod.register_queue(ws)

    for i in range(BLOCK_LINES):
        logger_mod._push(ws, "deps", f"[12:00:0{i}] ▶ deps  edges={i}")

    entries = _drain(q)
    assert len(entries) == BLOCK_LINES
    assert [e["msg"] for e in entries] == [f"[12:00:0{i}] ▶ deps  edges={i}" for i in range(BLOCK_LINES)]
    for e in entries:
        assert set(e) == {"ts", "stage", "msg"}, e
        assert e["stage"] == "deps"
        assert isinstance(e["ts"], str) and e["ts"]


def test_push_without_consumer_still_creates_no_queue(clean_registry):
    """M7 must keep holding: no subscribers → nothing is buffered or created."""
    ws = "msc6_ws_orphan"
    logger_mod._push(ws, "info", "nobody listening")
    assert ws not in logger_mod._log_queues
    assert ws not in logger_mod._log_refs


# ═══════════════ 4. ref-count / resource cleanup ═══════════════

def test_last_unsubscribe_releases_workspace_resources(clean_registry):
    """No leak: many workspaces × many subscribers all released at the end."""
    workspaces = [f"msc6_ws_leak_{i}" for i in range(40)]
    for ws in workspaces:
        for _ in range(3):
            logger_mod.register_queue(ws)

    assert len(logger_mod._log_queues) == 40
    assert len(logger_mod._log_refs) == 40
    assert all(logger_mod._log_refs[ws] == 3 for ws in workspaces)

    # First two leaves: the workspace's fan-out must survive.
    for ws in workspaces:
        logger_mod.unregister_queue(ws)
        logger_mod.unregister_queue(ws)
    assert len(logger_mod._log_queues) == 40, "fan-out released too early"
    assert all(logger_mod._log_refs[ws] == 1 for ws in workspaces)

    # Last leave: everything for that workspace goes away.
    for ws in workspaces:
        logger_mod.unregister_queue(ws)
    assert logger_mod._log_queues == {}, logger_mod._log_queues.keys()
    assert logger_mod._log_refs == {}

    # The released registry is reusable: a new subscriber gets a fresh queue.
    q = logger_mod.register_queue(workspaces[0])
    logger_mod._push(workspaces[0], "info", "reborn")
    assert [e["msg"] for e in _drain(q)] == ["reborn"]


def test_remove_queue_drops_every_consumer_of_a_workspace(clean_registry):
    """Workspace deletion must clear the whole fan-out (routers/workspace.py)."""
    ws = "msc6_ws_deleted"
    a = logger_mod.register_queue(ws)
    b = logger_mod.register_queue(ws)
    other = logger_mod.register_queue("msc6_ws_survivor")

    logger_mod.remove_queue(ws)
    assert ws not in logger_mod._log_queues
    logger_mod._push(ws, "info", "after-delete")
    assert _drain(a) == [] and _drain(b) == []
    logger_mod._push("msc6_ws_survivor", "info", "untouched")
    assert [e["msg"] for e in _drain(other)] == ["untouched"]


# ═══════════════ 5. executor-thread pinning (MSC-6, part 2) ═══════════════

def _run_in_two_threads(ws, push_count):
    """Collect from two live SSE generators while pushes arrive.

    Drives the real endpoint (`stream_logs`) — both generators on a real
    loop, producer lines pushed from a SEPARATE thread, exactly like the
    pipeline worker threads do in production.
    """
    results: dict[str, list] = {}
    loop = asyncio.new_event_loop()

    async def collect(gen, want, out):
        while len(out) < want:
            chunk = await asyncio.wait_for(gen.__anext__(), timeout=5.0)
            if isinstance(chunk, (bytes, bytearray)):
                chunk = chunk.decode()
            for frame in chunk.split("\n\n"):
                if frame.startswith("data: "):
                    out.append(json.loads(frame[len("data: "):]))

    async def scenario():
        gen_a = (await stream_logs(ws)).body_iterator
        gen_b = (await stream_logs(ws)).body_iterator
        assert gen_a is not gen_b, "the two streams share one iterator"
        ta = asyncio.create_task(collect(gen_a, push_count, results.setdefault("a", [])))
        tb = asyncio.create_task(collect(gen_b, push_count, results.setdefault("b", [])))

        # Wait until both subscribers are actually registered.
        for _ in range(500):
            if len(logger_mod._log_queues.get(ws, {})) == 2:
                break
            await asyncio.sleep(0.01)
        assert len(logger_mod._log_queues.get(ws, {})) == 2, "subscribers never registered"

        # Produce from a worker thread, like the pipeline stages do.
        def producer():
            for i in range(push_count):
                logger_mod._push(ws, "info", f"line-{i}")

        threading.Thread(target=producer, daemon=True).start()

        await asyncio.wait_for(asyncio.gather(ta, tb), timeout=10.0)
        for gen in (gen_a, gen_b):
            await gen.aclose()  # runs the generators' finally → unregister

    try:
        loop.run_until_complete(scenario())
    finally:
        loop.close()
    return results


def test_two_sse_streams_each_receive_the_whole_block(clean_registry):
    """End-to-end through the endpoint: both streams get all 13 lines.

    Before the fix this was the reported repro: alice 1, bob 0.
    """
    ws = "msc6_ws_endpoint"
    res = _run_in_two_threads(ws, BLOCK_LINES)

    expected = [f"line-{i}" for i in range(BLOCK_LINES)]
    assert [e["msg"] for e in res["a"]] == expected, \
        f"stream A got {[e['msg'] for e in res['a']]}"
    assert [e["msg"] for e in res["b"]] == expected, \
        f"stream B got {[e['msg'] for e in res['b']]}"
    # Same entry shape on the wire as before (LogPanel needs no change).
    assert set(res["a"][0]) == {"ts", "stage", "msg"}


def test_sse_generator_parks_no_executor_thread(clean_registry):
    """MSC-6 part 2: an idle stream must not occupy a worker thread.

    The old generator looped on `run_in_executor(None, q.get(timeout=1))`,
    which held one default-executor thread per open stream for as long as
    the tab stayed open. The replacement waits on a per-consumer asyncio
    event, so no executor call is made at all.
    """
    ws = "msc6_ws_nothread"
    calls: list = []
    saved = asyncio.BaseEventLoop.run_in_executor

    def spy(self, executor, func, *args, **kwargs):
        calls.append(func)
        return saved(self, executor, func, *args, **kwargs)

    asyncio.BaseEventLoop.run_in_executor = spy
    try:
        res = _run_in_two_threads(ws, 5)
    finally:
        asyncio.BaseEventLoop.run_in_executor = saved

    assert len(res["a"]) == 5 and len(res["b"]) == 5, "streams did not deliver"
    assert calls == [], f"the SSE generator still used the executor: {calls}"


def test_push_from_another_thread_wakes_a_waiting_consumer(clean_registry):
    """The producer (sync worker thread) must wake an idle async stream."""
    ws = "msc6_ws_wake"
    loop = asyncio.new_event_loop()
    received: list = []
    registered = threading.Event()

    async def waiter():
        q = logger_mod.register_queue(ws, loop=asyncio.get_running_loop())
        registered.set()
        await asyncio.wait_for(q.wait_ready(), timeout=5.0)
        received.append(q.get_nowait())
        logger_mod.unregister_queue(ws, q)

    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(waiter())

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    assert registered.wait(2.0), "consumer never registered"
    time.sleep(0.05)  # let it block inside wait_ready()
    logger_mod._push(ws, "info", "wake-up")  # from THIS (producer) thread

    thread.join(10.0)
    assert not thread.is_alive(), "idle consumer was never woken by the push"
    loop.close()
    assert [e["msg"] for e in received] == ["wake-up"]
    assert ws not in logger_mod._log_queues


def test_unattached_consumer_still_receives_lines(clean_registry):
    """A queue registered without a loop is a plain bounded queue."""
    ws = "msc6_ws_plain"
    q = logger_mod.register_queue(ws)
    assert isinstance(q, queue.Queue), "readers must keep the queue.Queue API"
    logger_mod._push(ws, "info", "plain")
    assert [e["msg"] for e in _drain(q)] == ["plain"]
    logger_mod.unregister_queue(ws, q)
