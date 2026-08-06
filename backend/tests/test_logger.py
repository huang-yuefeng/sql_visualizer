"""Logger registry tests (M7) — _push must not resurrect dropped SSE queues.

L2 added ref-counted queue cleanup: unregister_queue pops a workspace's
queue when the last SSE consumer disconnects. M7: _push used to call
ensure_queue(), which RECREATED a just-removed queue on the next background
log line (index run, search diagnostic, R16/R17) — nobody listening, no
future unregister, registry grows forever. _push must only put into an
EXISTING queue.
"""

import queue

import pytest

from app.services import logger as logger_mod


@pytest.fixture
def clean_registry():
    logger_mod._log_queues.clear()
    logger_mod._log_refs.clear()
    yield
    logger_mod._log_queues.clear()
    logger_mod._log_refs.clear()


def test_push_does_not_recreate_queue_after_unregister(clean_registry):
    """M7: register → unregister → push must NOT resurrect the queue."""
    ws = "m7_test_ws1"
    logger_mod.register_queue(ws)
    logger_mod.unregister_queue(ws)
    assert ws not in logger_mod._log_queues
    logger_mod._push(ws, "info", "after-unregister message")
    assert ws not in logger_mod._log_queues, "queue resurrected by _push"
    assert ws not in logger_mod._log_refs


def test_push_lands_in_registered_queue(clean_registry):
    """M7: with an active consumer, pushes still arrive in the queue."""
    ws = "m7_test_ws2"
    q = logger_mod.register_queue(ws)
    logger_mod._push(ws, "info", "hello-stream")
    entries = []
    while True:
        try:
            entries.append(q.get_nowait())
        except queue.Empty:
            break
    assert any(e.get("msg") == "hello-stream" for e in entries), entries
    logger_mod.unregister_queue(ws)
    assert ws not in logger_mod._log_queues


def test_push_without_any_consumer_never_creates_queue(clean_registry):
    """A background _push before any stream starts must not create a queue."""
    ws = "m7_test_ws3"
    logger_mod._push(ws, "info", "pre-stream message")
    assert ws not in logger_mod._log_queues


def test_unregister_last_consumer_removes_queue(clean_registry):
    """Ref counting: the queue survives until the LAST consumer leaves."""
    ws = "m7_test_ws4"
    logger_mod.register_queue(ws)
    logger_mod.register_queue(ws)
    logger_mod.unregister_queue(ws)
    assert ws in logger_mod._log_queues  # one consumer left
    logger_mod.unregister_queue(ws)
    assert ws not in logger_mod._log_queues
    assert ws not in logger_mod._log_refs
