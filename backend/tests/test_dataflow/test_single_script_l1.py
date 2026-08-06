"""R24 — single-script workspaces must show their script in L1.

User requirement: "when there is only one script in the folder, we should
show it in L1, when clicking on script there should be L2."

Regression: a single-script workspace search returned a 0-node L1. The
single-script shortcut in `_build_l1_graph` returned only the bare script
node (no tables/edges), and `_filter_l1_by_lineage`'s R18.1 cleanup then
pruned that script as "disconnected" (0 edges) — nothing left to
double-click into L2.

Fix (R24):
  1. `_build_l1_graph` runs the single script's analysis inline and builds
     the full pipeline graph (script + tables + reads/writes edges +
     lineage field children) — the same shape as the multi-script path.
  2. `_filter_l1_by_lineage` never prunes the only script of a 1-script
     graph (the search already matched it); multi-script R18.1 pruning is
     unchanged.
  3. R22 no_matches semantics are preserved: a field no script queries
     still returns match_mode=no_matches + message + empty L1.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from tests.test_dataflow.conftest import _make_zip  # noqa: E402

from app.services.workspace_service import get_workspace_dir  # noqa: E402

CASE_DIR = REPO_ROOT / "samples" / "sql_sample_v1"
SCRIPT_NAME = "BDM_ACC_LOAN_INFO_SUP_M.sql"

# The repro script queries lending_ref (control search) but never queries
# ABROAD_LOAD_PURPOSE (the R22 no_matches case).
TARGET_TABLE = "bdm_acc_loan_info"
TARGET_FIELD = "lending_ref"
ABSENT_FIELD = "ABROAD_LOAD_PURPOSE"


@pytest.fixture
def single_script_ws(workspace_client):
    """Single-script workspace built from samples/sql_sample_v1 (the user's
    exact repro folder), indexed, ready to search."""
    ws_id = workspace_client.create(_make_zip(CASE_DIR))
    try:
        workspace_client.index(ws_id)
        yield ws_id
    finally:
        workspace_client.delete(ws_id)


def _script_node_ids(graph: dict) -> list:
    return [n.get("data", n).get("id") for n in graph.get("nodes", [])
            if n.get("data", n).get("type") == "script_node"]


def _script_node_labels(graph: dict) -> list:
    return [n.get("data", n).get("label") for n in graph.get("nodes", [])
            if n.get("data", n).get("type") == "script_node"]


class TestSingleScriptSearchL1:
    """(a) A matching search in a single-script workspace must return the
    script node in L1 — with its flow tables when the lineage filter keeps
    them."""

    def test_search_l1_contains_script_node(self, workspace_client, single_script_ws):
        result = workspace_client.search(single_script_ws, TARGET_TABLE, TARGET_FIELD)
        assert result["match_mode"] == "exact", result
        assert result["script_ids"] == [SCRIPT_NAME], result
        l1 = result["l1_graph"]
        assert _script_node_ids(l1), "L1 must contain the script node"
        assert l1["edges"], "L1 must carry the script↔table edges"
        # Tables in the field's flow survive the R18 lineage filter
        tables = {n.get("data", n).get("table_name", "")
                  for n in l1["nodes"] if n.get("data", n).get("table_name")}
        assert TARGET_TABLE in tables, tables

    def test_search_l1_script_node_clickable_shape(self, workspace_client, single_script_ws):
        """The script node carries script_name — the frontend double-click
        handler (onDblTap → handleOpenL2) resolves L2 by script_name."""
        result = workspace_client.search(single_script_ws, TARGET_TABLE, TARGET_FIELD)
        script_nodes = [n.get("data", n) for n in result["l1_graph"]["nodes"]
                        if n.get("data", n).get("type") == "script_node"]
        assert script_nodes
        for nd in script_nodes:
            assert nd.get("script_name") == SCRIPT_NAME, nd
            assert nd.get("id"), nd

    def test_build_l1_graph_single_script_full_pipeline(self, workspace_client, single_script_ws):
        """_build_l1_graph itself (pre-filter) builds the full pipeline for
        one script: script node + tables + edges + lineage_field_pairs —
        not the old bare script node."""
        from app.services.l1_builder import _build_l1_graph
        l1 = _build_l1_graph(single_script_ws, [SCRIPT_NAME],
                             TARGET_TABLE, TARGET_FIELD)
        assert _script_node_labels(l1) == [SCRIPT_NAME], l1
        assert l1["edges"], "single-script L1 must have script↔table edges"
        assert l1.get("lineage_field_pairs"), \
            "single-script L1 must carry lineage_field_pairs"
        tables = {n.get("data", n).get("table_name", "")
                  for n in l1["nodes"] if n.get("data", n).get("table_name")}
        assert TARGET_TABLE in tables, tables


class TestSingleScriptLevel1Endpoint:
    """(b) The level1 endpoint for the view rebuilds the same graph — the
    script node must be present there too."""

    def test_level1_script_node_present(self, workspace_client, single_script_ws):
        from app.routers.dataflow import search_dataflow, get_level1
        sr = asyncio.run(search_dataflow(
            single_script_ws, {"table": TARGET_TABLE, "field": TARGET_FIELD}))
        l1 = asyncio.run(get_level1(single_script_ws, sr["view_id"]))
        assert _script_node_ids(l1["l1_graph"]), l1
        # Same node set as the search response (same builder + same filter)
        search_ids = {n.get("data", n).get("id")
                      for n in sr["l1_graph"]["nodes"]}
        level1_ids = {n.get("data", n).get("id")
                      for n in l1["l1_graph"]["nodes"]}
        assert level1_ids == search_ids, (search_ids, level1_ids)


class TestSingleScriptNoMatchesPreserved:
    """(c) R22 no_matches semantics are untouched: a field no script queries
    still yields match_mode=no_matches + message + EMPTY L1 — even in a
    single-script workspace."""

    def test_no_matches_still_empty(self, workspace_client, single_script_ws):
        result = workspace_client.search(single_script_ws,
                                         TARGET_TABLE, ABSENT_FIELD)
        assert result["match_mode"] == "no_matches", result
        assert result["script_ids"] == [], result
        assert result["l1_graph"]["nodes"] == [], result
        assert result["l1_graph"]["edges"] == [], result
        assert "not queried by any script" in result["message"], result


class TestSingleScriptViewCache:
    """(d) The persisted view cache (views.json l1_graph_cache) must hold the
    fixed non-empty graph — new searches write correct caches, so a reload /
    view-tree click shows the script node."""

    def test_view_cache_persists_script_node(self, workspace_client, single_script_ws):
        result = workspace_client.search(single_script_ws,
                                         TARGET_TABLE, TARGET_FIELD)
        views_path = get_workspace_dir(single_script_ws) / "cache" / "views.json"
        views = json.loads(views_path.read_text())
        view = next(v for v in views if v["view_id"] == result["view_id"])
        cached = view.get("l1_graph_cache", {})
        assert _script_node_ids(cached), cached
        assert cached["nodes"], "cached L1 must not be the old 0-node graph"


class TestFilterL1LineageGuard:
    """Unit-level guard checks for the _filter_l1_by_lineage change."""

    def test_single_script_bare_graph_keeps_script(self):
        """Degenerate case: a 1-script graph with no tables/fields at all
        (e.g. the searched table never became an L1 node) must keep its
        script node — the R18.1 disconnected-script removal must not leave
        an empty, unclickable L1."""
        from app.services.dataflow_service import _filter_l1_by_lineage
        g = {
            "nodes": [{"data": {"id": "s1", "label": SCRIPT_NAME,
                                "type": "script_node",
                                "script_name": SCRIPT_NAME}}],
            "edges": [],
            "target": f"{TARGET_TABLE}.{TARGET_FIELD}",
            "lineage_field_pairs": [[TARGET_TABLE, TARGET_FIELD]],
        }
        f = _filter_l1_by_lineage(g, TARGET_TABLE, TARGET_FIELD)
        assert [n.get("data", n).get("id") for n in f["nodes"]] == ["s1"], f

    def test_multi_script_disconnected_pruning_unchanged(self):
        """R18.1 preservation: with >1 script, a script with no remaining
        table connections is still pruned (only the single-script case is
        exempt)."""
        from app.services.dataflow_service import _filter_l1_by_lineage
        g = {
            "nodes": [
                {"data": {"id": "sA", "label": "a.sql", "type": "script_node",
                          "script_name": "a.sql"}},
                {"data": {"id": "sB", "label": "b.sql", "type": "script_node",
                          "script_name": "b.sql"}},
                {"data": {"id": "t1", "label": "t1", "type": "source_table",
                          "table_name": "t1"}},
                {"data": {"id": "t2", "label": "t2", "type": "source_table",
                          "table_name": "t2"}},
                {"data": {"id": "f1", "label": "f", "type": "field",
                          "parent": "t1", "table_name": "t1",
                          "field_name": "f"}},
            ],
            "edges": [
                {"data": {"source": "t1", "target": "sA",
                          "edge_type": "reads_from"}},
                {"data": {"source": "t2", "target": "sB",
                          "edge_type": "reads_from"}},
            ],
            "target": f"{TARGET_TABLE}.{TARGET_FIELD}",
            "lineage_field_pairs": [["t1", "f"]],
        }
        f = _filter_l1_by_lineage(g, TARGET_TABLE, TARGET_FIELD)
        kept = {n.get("data", n).get("id") for n in f["nodes"]}
        assert kept == {"sA", "t1", "f1"}, kept
