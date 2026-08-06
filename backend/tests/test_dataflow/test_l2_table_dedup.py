"""Issue a: L2 table-node dedup — one physical table → exactly ONE L2 node.

The extractor emits one TABLE variable per scope, so a table read/written
by N contexts (CTE FROM, JOIN, subquery, ...) used to produce N compound
table nodes. Requirement: the data flow may pass through a table multiple
times, but the graph must show exactly one node — all contexts' edges
re-point to it. Aliases/subqueries/CTEs keep per-context semantics.

Coverage:
  a. one table, 4 contexts (2 bare FROM + JOIN alias + subquery alias) →
     exactly one L2 table node; all context edges present and pointing at
     that one node; zero dangling ids (every edge endpoint is a node).
  b. same-field-name dedup: the merged table shows each field once; fields
     of all merged contexts re-parent to the keeper.
  c. search_matched: False only when filtering with a field absent from the
     script; True when present; True when no filter was requested.
  d. merged_original_ids (builder-internal merge record) never leaks into
     the output graph.
"""

import io
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
import sys
sys.path.insert(0, str(BACKEND_DIR))

from app.services.workspace_service import create_workspace, delete_workspace
from app.services.l2_builder import _build_l2_graph, _classify_compound_nodes

TABLE = "bdm_acc_loan_info"

# Same physical table used in 4 contexts:
#   1. CTE `rollover`:   FROM bdm_acc_loan_info            (no alias)
#   2. CTE `active`:     FROM bdm_acc_loan_info            (no alias)
#   3. main JOIN:        JOIN bdm_acc_loan_info p          (alias)
#   4. subquery:         FROM bdm_acc_loan_info s          (alias)
MULTI_CTX_SQL = """-- same physical table in 4 contexts
WITH rollover AS (
    SELECT loan_id, amount FROM bdm_acc_loan_info WHERE data_dt = '2026-01-01'
),
active AS (
    SELECT loan_id, loan_bal FROM bdm_acc_loan_info WHERE loan_bal > 0
)
SELECT r.loan_id, r.amount, a.loan_bal, p.name
FROM rollover r
JOIN active a ON a.loan_id = r.loan_id
JOIN bdm_acc_loan_info p ON p.loan_id = r.loan_id
WHERE r.loan_id IN (
    SELECT s.loan_id FROM bdm_acc_loan_info s WHERE s.charge_department = 'OPS_CDT'
);"""


@pytest.fixture
def multi_ctx_ws():
    """Workspace with the 4-context script (zip-upload path)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("multi_ctx.sql", MULTI_CTX_SQL)
    ws_id = create_workspace(buf.getvalue())
    yield ws_id
    delete_workspace(ws_id)


def _table_nodes(graph: dict) -> list:
    return [n["data"] for n in graph["nodes"]
            if n["data"].get("type") in
            ("source_table", "intermediate_table", "output_table",
             "cte_table", "alias_table")]


def _dangling_edges(graph: dict) -> list:
    ids = {n["data"]["id"] for n in graph["nodes"]}
    return [e["data"] for e in graph["edges"]
            if e["data"]["source"] not in ids or e["data"]["target"] not in ids]


def test_same_table_4_contexts_single_node(multi_ctx_ws):
    """a: 4 contexts of bdm_acc_loan_info → exactly ONE L2 table node; the
    other contexts' edges still exist and point at that one node; zero
    dangling edge endpoints."""
    graph = _build_l2_graph(multi_ctx_ws, "multi_ctx.sql", MULTI_CTX_SQL,
                            TABLE, "loan_id", relevance_filter=False)
    tables = _table_nodes(graph)
    keepers = [t for t in tables if t["table_name"] == TABLE]
    assert len(keepers) == 1, \
        f"Expected exactly 1 table node for {TABLE}, got {len(keepers)}: {keepers}"

    # Aliases/subqueries/CTEs keep per-context semantics
    names = {t["table_name"] for t in tables}
    assert {"rollover", "active", "p", "s"} <= names, names
    assert len([t for t in tables if t["table_name"] == "p"]) == 1

    keeper_id = keepers[0]["id"]
    # Statement edges of ALL contexts land on the keeper: the two bare-FROM
    # contexts feed the rollover/active CTEs (SUBSET) and the aliased
    # contexts (ALIAS) — every edge endpoint must exist.
    assert not _dangling_edges(graph), \
        f"dangling edge endpoints: {_dangling_edges(graph)[:5]}"
    touching = [e["data"] for e in graph["edges"]
                if keeper_id in (e["data"]["source"], e["data"]["target"])]
    assert len(touching) >= 3, f"context edges to keeper missing: {touching}"
    etypes = {e["edge_type"] for e in touching}
    assert "ALIAS" in etypes and "SUBSET" in etypes, etypes


def test_merged_table_fields_dedup(multi_ctx_ws):
    """b: the merged table shows each field once; fields from every merged
    context re-parent to the keeper; edges to those fields resolve."""
    graph = _build_l2_graph(multi_ctx_ws, "multi_ctx.sql", MULTI_CTX_SQL,
                            TABLE, "loan_id", relevance_filter=False)
    keeper = next(n["data"] for n in graph["nodes"]
                  if n["data"].get("table_name") == TABLE)
    fields = [n["data"] for n in graph["nodes"]
              if n["data"].get("parent") == keeper["id"]]
    by_name = {}
    for f in fields:
        by_name.setdefault(f["label"], []).append(f)
    # Fields of both bare-FROM contexts (rollover: loan_id/amount/data_dt,
    # active: loan_id/loan_bal) plus the JOIN/subquery aliased reads land
    # under the ONE keeper, each field name exactly once.
    #
    # C-9 (per-statement dedup): the field dedup key is now
    # (parent, undecorated_label, stmt_idx) — same-named fields from
    # DIFFERENT statements stay distinct. On this fixture the CTE-body
    # columns (stmt_idx=None) parent under the keeper table while the
    # main-statement projections (stmt_idx=0) parent under their own
    # alias/output nodes, so the keeper still shows each name exactly
    # once — no C-9 split here. The cross-statement split is covered in
    # test_b_series_c9.py (two bare-FROM statements → same name under the
    # same keeper at stmt_idx 0 and 1 → two distinct fields).
    assert by_name["loan_id"], fields
    for fname, nodes in by_name.items():
        assert len(nodes) == 1, \
            f"field '{fname}' duplicated under merged table: {len(nodes)}x"
    assert {"loan_id", "amount", "loan_bal", "name"} <= set(by_name), \
        f"merged contexts' fields missing: {sorted(by_name)}"

    # Edges from both contexts to that field resolve (zero dangling ids —
    # all field-level edges re-pointed to the keeper or its field).
    assert not _dangling_edges(graph), \
        f"dangling edge endpoints: {_dangling_edges(graph)[:5]}"


def test_search_matched_semantics(multi_ctx_ws):
    """c: search_matched is False ONLY when a relevance filter was requested
    and the searched field is absent from the script; True when the field is
    present; True when no filter was requested."""
    present = _build_l2_graph(multi_ctx_ws, "multi_ctx.sql", MULTI_CTX_SQL,
                              TABLE, "loan_id", relevance_filter=True)
    assert present["search_matched"] is True, present["search_matched"]

    absent = _build_l2_graph(multi_ctx_ws, "multi_ctx.sql", MULTI_CTX_SQL,
                             TABLE, "no_such_field_xyz", relevance_filter=True)
    assert absent["search_matched"] is False, absent["search_matched"]

    unfiltered = _build_l2_graph(multi_ctx_ws, "multi_ctx.sql", MULTI_CTX_SQL,
                                 TABLE, "no_such_field_xyz",
                                 relevance_filter=False)
    assert unfiltered["search_matched"] is True, unfiltered["search_matched"]

    # The absent-field signal is precisely the "not in this script" case —
    # the search target field must NOT be marked anywhere in that graph.
    targets = [n["data"] for n in absent["nodes"] if n["data"].get("is_target")]
    assert not targets, targets


def test_target_highlight_lands_on_keeper(multi_ctx_ws):
    """The searched field (loan_id) is used in bare-FROM contexts that merge
    AND in aliased contexts — every surviving occurrence must be marked
    is_target/direct after the merge (no ghost nids)."""
    graph = _build_l2_graph(multi_ctx_ws, "multi_ctx.sql", MULTI_CTX_SQL,
                            TABLE, "loan_id", relevance_filter=True)
    keeper = next(n["data"] for n in graph["nodes"]
                  if n["data"].get("table_name") == TABLE)
    keeper_loan_id = [n["data"] for n in graph["nodes"]
                      if n["data"].get("parent") == keeper["id"]
                      and n["data"].get("label") == "loan_id"]
    assert keeper_loan_id, "keeper must carry the searched field"
    assert keeper_loan_id[0]["is_target"] is True, keeper_loan_id[0]
    assert keeper_loan_id[0]["field_group"] == "direct", keeper_loan_id[0]


def test_merged_original_ids_never_leak(multi_ctx_ws):
    """d: merged_original_ids is builder-internal bookkeeping — the output
    graph must not carry it on any node."""
    graph = _build_l2_graph(multi_ctx_ws, "multi_ctx.sql", MULTI_CTX_SQL,
                            TABLE, "loan_id", relevance_filter=False)
    leaks = [n["data"] for n in graph["nodes"]
             if "merged_original_ids" in n["data"]]
    assert not leaks, f"merged_original_ids leaked: {leaks[:3]}"


def test_classify_compound_nodes_records_merged_nids(multi_ctx_ws):
    """Unit-level: the TABLE branch records merged-away context nids on the
    keeper (merged_original_ids), so _build_id_map can re-point every edge."""
    from app.services import l2_builder as l2b

    ws_id = multi_ctx_ws
    full_graph, table_schemas = l2b._load_or_build_graph(
        ws_id, "multi_ctx.sql", MULTI_CTX_SQL)
    graph_data = l2b._apply_relevance_filter(
        full_graph, TABLE, "loan_id", table_schemas, relevance_filter=False)
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    target_node_ids, direct_ids = l2b._compute_target_and_direct_ids(
        nodes, edges, TABLE, "loan_id")
    table_nodes, field_nodes, other_nodes, alias_map = _classify_compound_nodes(
        nodes, full_graph, "multi_ctx.sql", target_node_ids, direct_ids)

    keepers = [tn for tn in table_nodes.values()
               if tn["table_name"] == TABLE]
    assert len(keepers) == 1, f"expected 1 keeper, got {len(keepers)}"
    merged = keepers[0].get("merged_original_ids", [])
    # 4 contexts, 1 keeper → 3 merged-away nids (2 bare-FROM + the aliased
    # contexts read the same physical table variable per scope)
    assert merged, "keeper must record merged-away context nids"
    # Every merged nid must resolve through _build_id_map to the keeper
    id_map = l2b._build_id_map(table_nodes, field_nodes, other_nodes)
    for mnid in merged:
        assert id_map[mnid] == keepers[0]["id"], id_map[mnid]
