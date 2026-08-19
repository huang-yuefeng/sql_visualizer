"""L1 Pass-A cache-aware tests (performance design 2026-08-14).

Part 1: when >= 2 matched scripts and the analysis cache is present, L1's
Pass A builds the `all_scripts` entries from the cache (version-guarded,
mirror of dataflow_service.get_level2_graph) instead of re-running the
full extraction pipeline per script. The cache-hit L1 output must be
BYTE-IDENTICAL to a fresh-extraction L1 run, and `run_full_analysis`
must not be called on a cache hit (the ~197ms/script extraction is what
the cache eliminates).
"""

import io
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.folder_index_service import index_scripts
from app.services.l1_builder import _build_l1_graph
from app.services.workspace_service import (
    create_workspace,
    delete_workspace,
)

WORKFLOW_DIR = BACKEND_DIR.parent / "samples" / "multi_workflow"
TARGET_TABLE = "stg_customers"
TARGET_FIELD = "customer_id"


@pytest.fixture
def multi_workflow_ws():
    """Workspace with the 5 multi_workflow scripts (real zip-upload path)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(WORKFLOW_DIR.glob("step*.sql")):
            zf.write(f, f.name)
    ws_id = create_workspace(buf.getvalue())
    yield ws_id
    delete_workspace(ws_id)


def _script_names() -> list[str]:
    return sorted(f.name for f in WORKFLOW_DIR.glob("step*.sql"))


def test_l1_pass_a_cache_hit_does_not_extract_and_is_byte_identical(
        multi_workflow_ws, monkeypatch):
    """Fresh-extraction L1 (no analysis cache) and cache-hit L1 (after
    index) must be byte-identical, and the cache-hit run must NOT call
    run_full_analysis (Pass A builds all_scripts entries from the cache)."""
    names = _script_names()

    # Fresh run — no analysis cache on disk yet (workspace just uploaded).
    fresh = _build_l1_graph(multi_workflow_ws, names, TARGET_TABLE, TARGET_FIELD)
    assert fresh.get("degraded") is False
    assert fresh.get("flow_empty") is False
    assert fresh.get("nodes"), "fresh L1 must produce nodes"

    # Index the workspace → writes analysis_{cache_key}.json files.
    index_scripts(multi_workflow_ws, names)

    # Patch run_full_analysis: any call inside the cache-hit L1 run is a
    # regression (Pass A must serve from the analysis cache).
    from app.extractor import adapter as adapter_mod
    calls = []

    def _forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError(
            "run_full_analysis must not be called on an L1 cache hit")

    monkeypatch.setattr(adapter_mod, "run_full_analysis", _forbidden)

    cached = _build_l1_graph(multi_workflow_ws, names, TARGET_TABLE, TARGET_FIELD)
    assert calls == [], \
        "run_full_analysis called %d time(s) on a cache hit" % len(calls)
    # Byte-identity: the cache-hit L1 must equal the fresh-extraction L1.
    assert cached == fresh, \
        "cache-hit L1 must be byte-identical to fresh-extraction L1"


def test_l1_cache_miss_falls_back_to_extraction(multi_workflow_ws, monkeypatch):
    """A workspace with NO analysis cache (never indexed) still builds L1
    correctly via the fresh-extraction fallback — run_full_analysis is
    called and the result is non-degraded."""
    names = _script_names()
    from app.extractor import adapter as adapter_mod
    calls = []
    real = adapter_mod.run_full_analysis

    def _counting(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(adapter_mod, "run_full_analysis", _counting)
    l1 = _build_l1_graph(multi_workflow_ws, names, TARGET_TABLE, TARGET_FIELD)
    assert l1.get("degraded") is False
    assert l1.get("flow_empty") is False
    assert l1.get("nodes"), "fresh L1 must produce nodes"
    assert len(calls) >= len(names), \
        "cache miss must fall back to run_full_analysis per script"


def test_l1_rejects_stale_analysis_after_edit(multi_workflow_ws, monkeypatch):
    """C-H1 regression (2026-08-19 review): an edited script must never be
    served the stale analysis left in the cache dir — same script_name +
    extractor_version, different sql_text. The old reader keyed by
    script_name with a version-only guard and would accept it; the fix (exact
    sql-keyed read + sql_text equality, shared by Pass A and Pass B) must
    reject the stale hit and fall back to fresh extraction."""
    from app.services.workspace_service import get_workspace_dir

    names = _script_names()
    index_scripts(multi_workflow_ws, names)  # writes analysis_<key>.json

    # Simulate an edit: different sql_text, SAME script_name, NO re-index
    # (re-indexing writes a fresh-key file; an edit leaves the old one
    # behind — the exact stale state the bug serves).
    edited_name = names[0]
    sp = get_workspace_dir(multi_workflow_ws) / "scripts" / edited_name
    original_sql = sp.read_text(encoding="utf-8", errors="replace")
    edited_sql = "-- C-H1 edit marker\n" + original_sql
    assert edited_sql != original_sql
    sp.write_text(edited_sql, encoding="utf-8")

    from app.extractor import adapter as adapter_mod
    calls = []
    real = adapter_mod.run_full_analysis

    def _counting(*args, **kwargs):
        calls.append(args[1] if len(args) > 1 else kwargs.get("script_name"))
        return real(*args, **kwargs)

    monkeypatch.setattr(adapter_mod, "run_full_analysis", _counting)

    l1 = _build_l1_graph(multi_workflow_ws, names, TARGET_TABLE, TARGET_FIELD)
    assert l1.get("degraded") is False
    assert l1.get("nodes"), "edited workspace must still produce L1 nodes"
    assert edited_name in calls, \
        "edited script's stale analysis cache must be rejected → fresh extraction"
