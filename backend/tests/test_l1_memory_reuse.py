"""L1 in-memory cache tests (J12-11 #193 + #252, 2026-08-24).

T1 (#193): the per-call disk build of `analysis_cache_map` is memoized per
ws_id, invalidated by the analysis cache-dir file-set/mtime signature.

T2 (#252): the Final-L1-graph (the return value of `_build_l1_graph`) is
memoized per (signature, ws_id, script_names, table, field, direction),
LRU-bounded, invalidated by the analysis-cache signature PLUS the
matched-script file-set signature (a script edit without a re-index must
invalidate — the C-H1 stale-edit class).

Invariant (this project's rule): a cache hit is BYTE-IDENTICAL to a fresh
build — the memo serves the SAME dicts a fresh build would produce. The
tests prove a hit without re-reading by patching the build/loader to RAISE
on the second call (the raise proves the memo served it), mirroring
test_l1_cache_aware.py's byte-identity pattern.
"""

import io
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services import l1_builder
from app.services.folder_index_service import index_scripts
from app.services.l1_builder import _build_l1_graph
from app.services.workspace_service import (
    create_workspace,
    delete_workspace,
    get_workspace_dir,
)

WORKFLOW_DIR = BACKEND_DIR.parent / "samples" / "multi_workflow"
TARGET_TABLE = "stg_customers"
TARGET_FIELD = "customer_id"


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(WORKFLOW_DIR.glob("step*.sql")):
            zf.write(f, f.name)
    return buf.getvalue()


@pytest.fixture
def ws():
    ws_id = create_workspace(_zip_bytes())
    yield ws_id
    delete_workspace(ws_id)


@pytest.fixture
def ws_indexed(ws):
    index_scripts(ws, _script_names())
    return ws


def _script_names() -> list[str]:
    return sorted(f.name for f in WORKFLOW_DIR.glob("step*.sql"))


def _patch_uncached_to_raise(monkeypatch):
    """Patch `_build_l1_graph_uncached` to RAISE — any call on a memo hit
    is a regression (the build must not re-run)."""

    def _forbidden(*args, **kwargs):
        raise AssertionError(
            "_build_l1_graph_uncached must not run on an L1 memo hit")

    monkeypatch.setattr(l1_builder, "_build_l1_graph_uncached", _forbidden)


# ── T2: Final-L1-graph memo ─────────────────────────────────────────────


def test_t2_memo_serves_repeat_call_without_rebuild_and_is_byte_identical(
        ws_indexed, monkeypatch):
    """The second identical call is served from the in-memory memo: the
    build is NOT re-run (uncached patched to raise), and the returned graph
    is byte-identical to the first build."""
    names = _script_names()

    first = _build_l1_graph(ws_indexed, names, TARGET_TABLE, TARGET_FIELD)
    assert first.get("degraded") is False

    _patch_uncached_to_raise(monkeypatch)

    second = _build_l1_graph(ws_indexed, names, TARGET_TABLE, TARGET_FIELD)
    assert second == first, \
        "memo hit must be byte-identical to the fresh build"

    # A caller-style mutation of the returned copy must not corrupt the
    # cache — the next hit still returns the pristine cached graph.
    second["nodes"].append({"data": {"id": "junk", "label": "junk"}})
    third = _build_l1_graph(ws_indexed, names, TARGET_TABLE, TARGET_FIELD)
    assert third == first, \
        "mutating a memo-hit copy must not corrupt the cached graph"


def test_t2_invalidates_when_analysis_cache_changes(ws_indexed, monkeypatch):
    """Re-indexing changes the analysis cache-dir file-set signature → the
    memo misses and the graph is rebuilt (and re-memoized under the new
    signature)."""
    names = _script_names()

    first = _build_l1_graph(ws_indexed, names, TARGET_TABLE, TARGET_FIELD)

    real_uncached = l1_builder._build_l1_graph_uncached
    rebuilds = []

    def _counting(*args, **kwargs):
        rebuilds.append(1)
        return real_uncached(*args, **kwargs)

    monkeypatch.setattr(l1_builder, "_build_l1_graph_uncached", _counting)

    # Re-index rewrites the analysis files (new mtime) → signature change.
    index_scripts(ws_indexed, names)
    rebuilt = _build_l1_graph(ws_indexed, names, TARGET_TABLE, TARGET_FIELD)
    assert rebuilds == [1], \
        "a changed analysis file-set must be a memo miss → rebuild"
    assert rebuilt == first, \
        "rebuilt graph (same scripts re-indexed) must be byte-identical"

    # Now the memo holds the NEW signature — a further identical call is a hit.
    _patch_uncached_to_raise(monkeypatch)
    again = _build_l1_graph(ws_indexed, names, TARGET_TABLE, TARGET_FIELD)
    assert again == first


def test_t2_invalidates_when_script_edited_without_reindex(
        ws_indexed, monkeypatch):
    """C-H1 stale-edit class: editing a matched script WITHOUT re-indexing
    must invalidate the graph memo — the script file-set signature is part
    of the key. A memo keyed on the analysis signature alone would serve the
    stale pre-edit graph; the fresh build must re-extract the edited script."""
    names = _script_names()

    _build_l1_graph(ws_indexed, names, TARGET_TABLE, TARGET_FIELD)  # memoized

    edited_name = names[0]
    sp = get_workspace_dir(ws_indexed) / "scripts" / edited_name
    original_sql = sp.read_text(encoding="utf-8", errors="replace")
    sp.write_text("-- C-H1 edit marker\n" + original_sql, encoding="utf-8")

    from app.extractor import adapter as adapter_mod
    calls = []
    real = adapter_mod.run_full_analysis

    def _counting(*args, **kwargs):
        calls.append(args[1] if len(args) > 1 else kwargs.get("script_name"))
        return real(*args, **kwargs)

    monkeypatch.setattr(adapter_mod, "run_full_analysis", _counting)

    result = _build_l1_graph(ws_indexed, names, TARGET_TABLE, TARGET_FIELD)
    assert result.get("degraded") is False
    assert edited_name in calls, \
        "an edited script must invalidate the graph memo → fresh re-extract"


# ── T1: analysis_cache_map memo ─────────────────────────────────────────


def test_t1_analysis_map_memo_serves_second_uncached_build(
        ws_indexed, monkeypatch):
    """The analysis_cache_map is memoized per ws_id: a second build (even
    bypassing the T2 graph memo, via _build_l1_graph_uncached directly) does
    NOT re-scan the analysis cache dir — the map loader is patched to raise."""
    names = _script_names()

    first = _build_l1_graph(ws_indexed, names, TARGET_TABLE, TARGET_FIELD)

    def _forbidden(*args, **kwargs):
        raise AssertionError(
            "_load_analysis_cache_map must not re-run on a T1 memo hit")

    monkeypatch.setattr(l1_builder, "_load_analysis_cache_map", _forbidden)

    # Bypass the T2 graph memo so this exercises the T1 map memo inside the
    # uncached build path (the exact sql-keyed reads in _lookup_analysis are
    # separate and unchanged — they are NOT the map build).
    again = l1_builder._build_l1_graph_uncached(
        ws_indexed, names, TARGET_TABLE, TARGET_FIELD)
    assert again == first, \
        "T1 memo-hit build must be byte-identical to the fresh build"


def test_t1_analysis_map_invalidates_on_file_change(ws_indexed, monkeypatch):
    """A new analysis file (re-index) changes the signature → the map memo
    rebuilds (the loader runs again)."""
    names = _script_names()

    _build_l1_graph(ws_indexed, names, TARGET_TABLE, TARGET_FIELD)

    real_loader = l1_builder._load_analysis_cache_map
    loads = []

    def _counting(*args, **kwargs):
        loads.append(1)
        return real_loader(*args, **kwargs)

    monkeypatch.setattr(l1_builder, "_load_analysis_cache_map", _counting)

    index_scripts(ws_indexed, names)  # changes the analysis file-set
    l1_builder._build_l1_graph_uncached(
        ws_indexed, names, TARGET_TABLE, TARGET_FIELD)
    assert loads == [1], \
        "a changed analysis file-set must be a T1 memo miss → reload"


# ── Isolation + bounds ──────────────────────────────────────────────────


def test_cross_workspace_isolation(ws_indexed, monkeypatch):
    """Two ws_ids never share analysis/graph memo state — the second
    workspace's identical-content build is a MISS (not served from the first
    workspace's memo), and the memo keys carry the ws_id."""
    ws1 = ws_indexed
    names = _script_names()

    real_uncached = l1_builder._build_l1_graph_uncached
    builds = []

    def _counting(*args, **kwargs):
        builds.append(1)
        return real_uncached(*args, **kwargs)

    monkeypatch.setattr(l1_builder, "_build_l1_graph_uncached", _counting)

    g1 = _build_l1_graph(ws1, names, TARGET_TABLE, TARGET_FIELD)

    ws2 = create_workspace(_zip_bytes())
    try:
        index_scripts(ws2, names)
        g2 = _build_l1_graph(ws2, names, TARGET_TABLE, TARGET_FIELD)
    finally:
        delete_workspace(ws2)

    assert len(builds) == 2, \
        "a second workspace must be a memo miss (never served from ws1)"
    assert g2.get("degraded") is False

    # White-box: the memo keys carry each ws_id (ws_id is part of the key).
    graph_ws_ids = {key[2] for key in l1_builder._l1_graph_memo}
    assert ws1 in graph_ws_ids
    assert ws2 in graph_ws_ids
    # T1: the analysis-map LRU holds a separate entry per ws_id.
    assert ws1 in l1_builder._analysis_map_lru
    assert ws2 in l1_builder._analysis_map_lru


def test_lru_eviction_bounds(monkeypatch):
    """Both memos are LRU-bounded: with the caps forced small, building more
    workspaces than the cap evicts the oldest entry."""
    monkeypatch.setattr(l1_builder, "_ANALYSIS_MAP_LRU_MAX", 2)
    monkeypatch.setattr(l1_builder, "_L1_GRAPH_MEMO_MAX", 2)

    names = _script_names()
    wss = [create_workspace(_zip_bytes()) for _ in range(3)]
    try:
        for w in wss:
            index_scripts(w, names)
            _build_l1_graph(w, names, TARGET_TABLE, TARGET_FIELD)
    finally:
        for w in wss:
            delete_workspace(w)

    assert len(l1_builder._l1_graph_memo) <= 2, \
        "T2 graph memo must be LRU-bounded"
    assert len(l1_builder._analysis_map_lru) <= 2, \
        "T1 analysis-map memo must be LRU-bounded"

    # The oldest workspace (wss[0]) was evicted; the two most recent remain.
    remaining = {key[2] for key in l1_builder._l1_graph_memo}
    assert wss[0] not in remaining
    assert wss[1] in remaining
    assert wss[2] in remaining
