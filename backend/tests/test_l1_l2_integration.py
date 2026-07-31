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
