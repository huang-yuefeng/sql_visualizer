"""L1/L2 builder integration tests — real ETL workflow (samples/multi_workflow).

Verifies behaviors fixed in the current session (see
tools/BUG_ANALYSIS_AND_SUGGESTIONS.md, "Lessons Learned & Architecture Review"):

  1. L1 lineage_field_pairs follows only production edges — target
     stg_customers.customer_id must resolve to exactly
     {stg_customers, crm_customers} × customer_id, never leaking
     raw_orders/stg_orders pairs through the step3 JOIN.
  2. L2 JOIN edges survive relevance filtering in step3 (so→⟐ output,
     sc→⟐ output).
  3. No TABLE_FLOW edge connects two table nodes where neither endpoint
     is the ⟐ output table (no bypass of the query output).
  4. find_sql_range locates indented keywords at the correct 1-based column.
  5. The L2 graph cache carries a top-level alias_map.
"""

import sys
import io
import json
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.workspace_service import (
    create_workspace,
    delete_workspace,
    get_workspace_dir,
)
from app.services.l1_builder import _build_l1_graph
from app.services.l2_builder import _build_l2_graph
from app.services.sql_range_finder import find_sql_range

SAMPLES_DIR = BACKEND_DIR.parent / "samples"
WORKFLOW_DIR = SAMPLES_DIR / "multi_workflow"

TARGET_TABLE = "stg_customers"
TARGET_FIELD = "customer_id"
STEP3 = "step3_join_orders_customers.sql"
OUTPUT_TABLE = "⟐ output"


# ══════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════

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


def _step3_sql() -> str:
    return (WORKFLOW_DIR / STEP3).read_text()


def _step3_l2_graph(ws_id: str) -> dict:
    """L2 detail graph for step3, target stg_customers.customer_id."""
    return _build_l2_graph(ws_id, STEP3, _step3_sql(),
                           TARGET_TABLE, TARGET_FIELD,
                           relevance_filter=True)


def _table_name_by_id(graph: dict) -> dict:
    return {n["data"]["id"]: n["data"].get("table_name", "")
            for n in graph["nodes"]}


# ══════════════════════════════════════════════════════════════════════
# L1: lineage_field_pairs (production edges only)
# ══════════════════════════════════════════════════════════════════════

def test_l1_lineage_pairs_stg_customers(multi_workflow_ws):
    """L1 over the 5-step workflow: stg_customers.customer_id traces back
    only through production edges — exactly stg_customers + crm_customers,
    with no raw_orders/stg_orders pairs leaked via the step3 JOIN."""
    script_names = sorted(f.name for f in WORKFLOW_DIR.glob("step*.sql"))
    l1 = _build_l1_graph(multi_workflow_ws, script_names,
                         TARGET_TABLE, TARGET_FIELD)
    pairs = {tuple(p) for p in l1.get("lineage_field_pairs", [])}
    assert pairs == {
        ("stg_customers", "customer_id"),
        ("crm_customers", "customer_id"),
    }


# ══════════════════════════════════════════════════════════════════════
# L2 step3: JOIN edges survive relevance filtering
# ══════════════════════════════════════════════════════════════════════

def test_l2_step3_join_edges_survive(multi_workflow_ws):
    """Step3 has two JOIN keys (so.customer_id, sc.customer_id); both JOIN
    edges must survive relevance filtering and land on the ⟐ output table."""
    graph = _step3_l2_graph(multi_workflow_ws)
    table_by_id = _table_name_by_id(graph)
    joins = [e["data"] for e in graph["edges"]
             if e["data"].get("edge_type") == "JOIN"]
    assert len(joins) == 2, \
        f"Expected 2 JOIN edges, got {len(joins)}: {joins}"
    for e in joins:
        assert table_by_id.get(e["target"]) == OUTPUT_TABLE, \
            f"JOIN edge must feed the output table, got target {e['target']}"


def test_l2_step3_no_table_flow_bypass(multi_workflow_ws):
    """TABLE_FLOW edges must route through the ⟐ output table — no direct
    table-to-table flow where neither endpoint is the output table."""
    graph = _step3_l2_graph(multi_workflow_ws)
    table_by_id = _table_name_by_id(graph)
    output_ids = {nid for nid, tname in table_by_id.items()
                  if tname == OUTPUT_TABLE}
    assert output_ids, "L2 step3 graph must contain the ⟐ output table"
    for e in graph["edges"]:
        ed = e["data"]
        if ed.get("edge_type") != "TABLE_FLOW":
            continue
        src_table = table_by_id.get(ed["source"], "")
        tgt_table = table_by_id.get(ed["target"], "")
        if not src_table or not tgt_table:
            continue  # not a table-to-table edge
        assert ed["source"] in output_ids or ed["target"] in output_ids, \
            f"TABLE_FLOW {src_table} -> {tgt_table} bypasses the output table"


# ══════════════════════════════════════════════════════════════════════
# SQL range finding: indented keywords
# ══════════════════════════════════════════════════════════════════════

def test_sql_range_indented_column():
    """find_sql_range must report the 1-based column of the JOIN keyword
    even when the line is indented (here 2 spaces → column 3)."""
    sql = _step3_sql().replace("JOIN stg_customers sc ON",
                               "  JOIN stg_customers sc ON")
    assert "  JOIN stg_customers" in sql, "test SQL must be indented"
    result = find_sql_range({"edge_type": "JOIN"}, sql)
    assert result is not None
    assert result[1] == 3, f"JOIN keyword should start at col 3, got {result}"


# ══════════════════════════════════════════════════════════════════════
# L2 graph cache: alias_map
# ══════════════════════════════════════════════════════════════════════

def test_alias_map_in_graph_cache(multi_workflow_ws):
    """The L2 graph cache written for step3 must carry a top-level
    alias_map (alias → canonical table), e.g. sc → stg_customers."""
    _step3_l2_graph(multi_workflow_ws)
    cache_dir = get_workspace_dir(multi_workflow_ws) / "cache"
    cached_paths = sorted(cache_dir.glob("graph_*.json"))
    assert cached_paths, "L2 build must write a graph cache file"
    cached = json.loads(cached_paths[0].read_text())
    assert "alias_map" in cached, "cached graph must have alias_map key"
    assert cached["alias_map"], "alias_map must not be empty"
    assert cached["alias_map"].get("sc") == "stg_customers", \
        f"alias_map must resolve sc → stg_customers, got {cached['alias_map']}"


# ══════════════════════════════════════════════════════════════════════
# CW4 (C1): phase split — phase functions compose to the same graph
# ══════════════════════════════════════════════════════════════════════

def test_l2_phases_compose_to_same_graph(multi_workflow_ws):
    """CW4: calling the named phase functions in orchestrator order must
    produce a byte-identical graph JSON to the slim _build_l2_graph
    orchestrator (structural split — no behavior reordering)."""
    from app.services import l2_builder as l2b

    ws_id = multi_workflow_ws
    sql = _step3_sql()
    expected = _step3_l2_graph(ws_id)

    full_graph, table_schemas = l2b._load_or_build_graph(ws_id, STEP3, sql)
    graph_data = l2b._apply_relevance_filter(full_graph, TARGET_TABLE,
                                             TARGET_FIELD, table_schemas,
                                             relevance_filter=True)
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    target_node_ids, direct_ids = l2b._compute_target_and_direct_ids(
        nodes, edges, TARGET_TABLE, TARGET_FIELD)
    table_nodes, field_nodes, other_nodes, alias_map = l2b._classify_compound_nodes(
        nodes, full_graph, STEP3, target_node_ids, direct_ids)
    id_map = l2b._build_id_map(table_nodes, field_nodes, other_nodes)
    target_mapped, direct_mapped = l2b._map_search_target_ids(
        field_nodes, table_nodes, target_node_ids, direct_ids, id_map)
    new_edges, node_labels = l2b._build_edge_list(edges, nodes, id_map, sql)
    new_edges = l2b._combine_edges(new_edges)
    new_edges = l2b._promote_field_edges(new_edges, field_nodes)
    new_edges = l2b._survive_join_edges(new_edges, full_graph, id_map,
                                        table_nodes, field_nodes,
                                        node_labels, sql)
    new_edges, dml_pairs = l2b._simplify_dml_edges(new_edges, full_graph,
                                                   id_map, table_nodes)
    new_edges = l2b._dedup_edges(new_edges)
    l2b._sync_alias_and_dml_fields(field_nodes, table_nodes, alias_map,
                                   dml_pairs, full_graph, nodes)
    phased = l2b._assemble_output(table_nodes, field_nodes, new_edges, nodes,
                                  sql, STEP3, f"{TARGET_TABLE}.{TARGET_FIELD}")
    # Issue a: the orchestrator stamps search_matched on the result dict
    # (False only when a filter was requested and nothing matched — here
    # relevance_filter=True, so it is exactly bool(target or direct)).
    phased["search_matched"] = bool(target_mapped or direct_mapped)

    assert json.dumps(phased, sort_keys=True) == \
        json.dumps(expected, sort_keys=True)


# ══════════════════════════════════════════════════════════════════════
# C2: L1 field pairs are covered by the prebuilt P4 table_fields
# ══════════════════════════════════════════════════════════════════════

def test_l1_pairs_covered_by_table_fields(multi_workflow_ws):
    """C2: every L1 lineage_field_pair must be covered by the prebuilt P4
    table_fields — both from fresh on-the-fly analysis (no disk cache) and
    from the graph caches written by index_scripts (cached path). L1 must
    produce the same pairs with and without the disk caches."""
    from app.services.multi_script_service import analyze_multiple_scripts
    from app.services.folder_index_service import index_scripts

    ws_id = multi_workflow_ws
    script_names = sorted(f.name for f in WORKFLOW_DIR.glob("step*.sql"))
    sql_by_name = {n: (WORKFLOW_DIR / n).read_text() for n in script_names}

    # Fresh run: no disk caches exist yet — the on-the-fly P4 absorption
    # (build_graph_data table_fields) must cover the pairs.
    l1 = _build_l1_graph(ws_id, script_names, TARGET_TABLE, TARGET_FIELD)
    pairs = {tuple(p) for p in l1.get("lineage_field_pairs", [])}
    assert pairs == {
        ("stg_customers", "customer_id"),
        ("crm_customers", "customer_id"),
    }

    fresh = analyze_multiple_scripts([(n, sql_by_name[n]) for n in script_names])
    fresh_tf = set()
    for s in fresh.get("scripts", []):
        for tbl, flds in (s.get("graph", {}).get("table_fields", {}) or {}).items():
            for fn in flds:
                fresh_tf.add((tbl, fn))
    assert pairs <= fresh_tf, \
        f"pairs {pairs - fresh_tf} missing from fresh-analysis table_fields"

    # Cached run: index leaves post-S4b analysis caches (C-2 invalidates
    # index-time graph caches — they'd be pre-S4b and stale). Rebuild
    # graph_data from the analysis caches exactly as the L2 miss path does;
    # the P4 table_fields absorption must cover the same pairs, and L1 must
    # still produce the identical pair set.
    index_scripts(ws_id, script_names)
    from app.services.graph_service import build_graph_data
    cached_tf = set()
    for ac_path in sorted(get_workspace_dir(ws_id).glob("cache/analysis_*.json")):
        gdata = build_graph_data(json.loads(ac_path.read_text()))
        for tbl, flds in (gdata.get("table_fields", {}) or {}).items():
            for fn in flds:
                cached_tf.add((tbl, fn))
    assert pairs <= cached_tf, \
        f"pairs {pairs - cached_tf} missing from analysis-cache table_fields"

    l1_cached = _build_l1_graph(ws_id, script_names, TARGET_TABLE, TARGET_FIELD)
    assert {tuple(p) for p in l1_cached.get("lineage_field_pairs", [])} == pairs


# ══════════════════════════════════════════════════════════════════════
# B2/CW9: source_columns match the field part only — not the alias/table part
# ══════════════════════════════════════════════════════════════════════

def test_detect_role_no_table_part_false_match():
    """B2/CW9: detect_role must not match the alias/table part of a qualified
    source_column — target_field="item" vs "item.i_brand" must not match.
    The old word-boundary regex matched "item" inside "item.i_brand" and
    attributed roles to the wrong field. The field part still matches."""
    from app.services.l1_builder import detect_role

    graph_data = {
        "nodes": [{"data": {
            "id": "v1",
            "label": "x.i_brand",
            "name": "x.i_brand",
            "variable_type": "column",
            "defined_in": "SELECT",
            "is_output": True,
            "source_columns": ["item.i_brand"],
        }}],
        "edges": [],
    }
    # target_field="item" is the table part of "item.i_brand" — no role
    assert detect_role(graph_data, "store", "item") == []
    # field part still matches — positive path intact
    assert detect_role(graph_data, "item", "i_brand") == ["REF"]


def test_target_field_sc_matches_field_part_only():
    """B2/CW9: _target_field_sc compares only the field part (after the last
    dot) of a source_column — the old word-boundary regex matched the
    alias/table part ("item" inside "item.i_brand")."""
    from app.services.l2_builder import _target_field_sc

    assert _target_field_sc("item.i_brand", "item") is False
    assert _target_field_sc("item.i_brand", "i_brand") is True
    assert _target_field_sc("customer_id", "customer_id") is True
    assert _target_field_sc("sc.customer_id", "customer_id") is True
    assert _target_field_sc("sc.customer_id_x", "customer_id") is False


# ══════════════════════════════════════════════════════════════════════
# G2/Bug 37: SCHEMA directionality invariant (shared L1/L2 BFS semantics)
# ══════════════════════════════════════════════════════════════════════

def test_lineage_bfs_schema_directionality_invariant():
    """G2/Bug 37 (pinned): the SCHEMA directionality semantics are shared by
    L1 (edge_filter=PRODUCTION_EDGES | {"SCHEMA"}) and the unfiltered BFS —
    reverse (column→table) always follows; forward (table→column) only for
    columns with a production path back to the lineage set."""
    from app.extractor.lineage import compute_field_lineage, PRODUCTION_EDGES

    graph = {
        "nodes": [
            {"data": {"id": "T", "label": "customers", "variable_type": "table"}},
            {"data": {"id": "c1", "label": "customers.id", "variable_type": "column"}},
            {"data": {"id": "c2", "label": "customers.name", "variable_type": "column"}},
            {"data": {"id": "c3", "label": "customers.email", "variable_type": "column"}},
        ],
        "edges": [
            {"data": {"source": "T", "target": "c1", "edge_type": "SCHEMA"}},
            {"data": {"source": "T", "target": "c2", "edge_type": "SCHEMA"}},
            {"data": {"source": "T", "target": "c3", "edge_type": "SCHEMA"}},
            {"data": {"source": "c1", "target": "c2", "edge_type": "REF"}},
        ],
    }
    constrained = compute_field_lineage(graph, "customers", "id",
                                        edge_filter=PRODUCTION_EDGES | {"SCHEMA"})
    unconstrained = compute_field_lineage(graph, "customers", "id")
    assert constrained == unconstrained
    assert {"c1", "T"} <= constrained
    assert "c2" in constrained    # SCHEMA forward: has a production path back to R
    assert "c3" not in constrained  # SCHEMA forward: no production path — filtered
