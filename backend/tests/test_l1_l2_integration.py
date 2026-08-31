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
  4. The L2 graph cache carries a top-level alias_map.
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
# L1 (R29): the queried field's directional flow — scripts + tables only
# ══════════════════════════════════════════════════════════════════════

def test_l1_field_query_shape_stg_customers(multi_workflow_ws):
    """L1 over the 5-step workflow under R29: stg_customers.customer_id
    projects the strict walker's directional closure — scripts + tables
    only, no field nodes, no lineage_field_pairs (superseded), and every
    edge is a reads_from/writes_to restricted to participating nodes (no
    script→script edges)."""
    script_names = sorted(f.name for f in WORKFLOW_DIR.glob("step*.sql"))
    l1 = _build_l1_graph(multi_workflow_ws, script_names,
                         TARGET_TABLE, TARGET_FIELD)
    assert l1.get("flow_empty") is False, l1
    assert "lineage_field_pairs" not in l1, \
        "R29 supersedes the lineage_field_pairs path for field queries"
    assert all(n["data"].get("type") != "field" for n in l1["nodes"])
    types = {n["data"]["type"] for n in l1["nodes"]}
    assert "script_node" in types
    assert types & {"source_table", "intermediate_table", "output_table"}
    type_map = {n["data"]["id"]: n["data"]["type"] for n in l1["nodes"]}
    for e in l1["edges"]:
        ed = e["data"]
        assert ed["edge_type"] in ("reads_from", "writes_to"), ed
        assert not (type_map.get(ed["source"]) == "script_node"
                    and type_map.get(ed["target"]) == "script_node"), ed


# ══════════════════════════════════════════════════════════════════════
# L2 step3: JOIN edges survive relevance filtering
# ══════════════════════════════════════════════════════════════════════

def test_l2_step3_join_edges_survive(multi_workflow_ws):
    """Step3 has two JOIN keys (so.customer_id, sc.customer_id). Under the
    strict table.field flow (v3.3.140) only the SEED side's JOIN edge
    survived — the mirror key column (a different field instance) and its
    JOIN edge were dropped. R44 (2026-08-28, user ruling "covering all
    occurrences of the target field is the PURPOSE of flow-only") admits
    BOTH key instances of the join: the derived-product round covers
    alias reads co-scoped with the searched table's read, so the mirror
    so.customer_id joins the closure (distinct field instance + distinct
    model edge — NOT a duplicate of the seed side's edge) and the join
    occurrence renders complete: both key pairs land on the ⟐ output
    table, same join condition line."""
    graph = _step3_l2_graph(multi_workflow_ws)
    table_by_id = _table_name_by_id(graph)
    joins = [e["data"] for e in graph["edges"]
             if e["data"].get("edge_type") == "JOIN"]
    assert len(joins) == 2, \
        f"Expected both join-key edges (R44 occurrence coverage), got {len(joins)}: {joins}"
    # "distinct field instance + distinct model edge — NOT a duplicate of
    # the seed side's edge" (the docstring claim this test pins): the two
    # edges must come from TWO different source nodes, not two copies of
    # one edge.
    assert len({e["source"] for e in joins}) == 2, joins
    for e in joins:
        assert table_by_id.get(e["target"]) == OUTPUT_TABLE, \
            f"JOIN edge must feed the output table, got target {e['target']}"
    # both edges anchor at the join condition — the line is derived from
    # the SQL text (the ON clause), never hard-coded, and a missing
    # highlight_line fails as a mismatch rather than as a KeyError.
    join_line = next(i for i, ln in enumerate(_step3_sql().splitlines(), 1)
                     if "ON so.customer_id = sc.customer_id" in ln)
    assert {e.get("highlight_line") for e in joins} == {join_line}, joins


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

    # J12-10 stage 2/3: phase 1 returns the physical model; the node-construction
    # phases consume it (keeper selection + filter/matcher inputs) — pass it
    # through in orchestrator order exactly like _build_l2_graph.
    full_graph, table_schemas, physical_model = l2b._load_or_build_graph(
        ws_id, STEP3, sql)
    graph_data = l2b._apply_relevance_filter(full_graph, TARGET_TABLE,
                                             TARGET_FIELD, table_schemas,
                                             relevance_filter=True,
                                             physical_model=physical_model)
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    target_node_ids, direct_ids = l2b._compute_target_and_direct_ids(
        nodes, edges, TARGET_TABLE, TARGET_FIELD,
        physical_model=physical_model)
    # J12-10 stage 4: the classification returns (table_nodes,
    # field_nodes, alias_map, occ_to_id) — occ_to_id IS the id_map (the
    # old _build_id_map is gone).
    table_nodes, field_nodes, alias_map, occ_to_id = l2b._classify_compound_nodes(
        nodes, full_graph, STEP3, target_node_ids, direct_ids, TARGET_TABLE,
        physical_model)
    id_map = occ_to_id
    # R11-3: the orchestrator carries compound-node lines right after
    # classification (line_start/line_end/defined_in from the model's
    # occurrence index).
    l2b._carry_node_lines(table_nodes, physical_model)
    target_mapped, direct_mapped = l2b._map_search_target_ids(
        field_nodes, table_nodes, target_node_ids, direct_ids, id_map)
    new_edges, node_labels = l2b._build_edge_list(edges, nodes, id_map, sql)
    # J12-16: the DML simplification runs BEFORE the combine (mirror of
    # the orchestrator order) — rule 2's retarget must diverge a folded
    # field compound's per-statement edge instances into distinct targets
    # before _combine_edges' (source, target, edge_type) key collapses
    # them into one.
    new_edges = l2b._simplify_dml_edges(new_edges, full_graph, id_map,
                                        table_nodes,
                                        physical_model=physical_model)
    new_edges = l2b._combine_edges(new_edges)
    new_edges = l2b._promote_field_edges(new_edges, field_nodes)
    new_edges = l2b._survive_join_edges(new_edges, full_graph, id_map,
                                        table_nodes, field_nodes,
                                        node_labels, sql)
    new_edges = l2b._dedup_edges(new_edges)
    l2b._attach_flow_payload(new_edges, field_nodes, table_nodes=table_nodes)
    # Wave 2 (R19.1/R19.2): flow-role phase — the orchestrator calls it
    # before assembly (mirror for identity).
    l2b._attach_flow_roles(new_edges, table_nodes, id_map, full_graph,
                           TARGET_TABLE, TARGET_FIELD, True,
                           physical_model=physical_model)
    # R46a (2026-08-31): the display scoping of the seed claim — mirror of
    # the orchestrator, which runs it after every edge consumer has read
    # the flag and before assembly.
    l2b._scope_target_stamp(field_nodes, table_nodes, TARGET_TABLE,
                            TARGET_FIELD, physical_model)
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

def test_l1_projection_identical_fresh_and_cached(multi_workflow_ws):
    """C2 (R29 shape): the directional projection must be identical with
    and without the disk caches — fresh on-the-fly analysis (no cache)
    and the analysis caches written by index_scripts produce the same
    script + table projection (the models are built from the same
    deterministic pipeline either way)."""
    from app.services.folder_index_service import index_scripts

    ws_id = multi_workflow_ws
    script_names = sorted(f.name for f in WORKFLOW_DIR.glob("step*.sql"))

    def _projection():
        l1 = _build_l1_graph(ws_id, script_names, TARGET_TABLE, TARGET_FIELD)
        scripts = sorted(n["data"]["label"] for n in l1["nodes"]
                         if n["data"]["type"] == "script_node")
        tables = sorted(n["data"].get("table_name", "") for n in l1["nodes"]
                        if n["data"].get("table_name"))
        edges = sorted((e["data"]["id"], e["data"]["edge_type"])
                       for e in l1["edges"])
        return scripts, tables, edges, l1.get("flow_empty")

    fresh = _projection()
    index_scripts(ws_id, script_names)
    cached = _projection()
    assert fresh == cached, (fresh, cached)


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
    """B2/CW9 + J12-9: the seed matcher compares only the field part (after
    the last dot) of a label or source_column — the old word-boundary regex
    matched the alias/table part ("item" inside "item.i_brand"). The retired
    _target_field_sc helper is inlined in _compute_target_and_direct_ids as
    the unified rsplit predicate (J12-9 ruling 2026-08-11)."""
    from app.services.l2_builder import _compute_target_and_direct_ids

    def _targets(label, variable_type, source_columns, field):
        nodes = [{"data": {"id": "v1", "label": label,
                           "variable_type": variable_type,
                           "source_columns": source_columns}}]
        ids, _ = _compute_target_and_direct_ids(nodes, [], "store", field)
        return ids

    # the alias/table part of a qualified column never matches (B2/CW9) —
    # and short names never match inside longer ones (R4, no substring)
    assert _targets("x.i_brand", "column", ["item.i_brand"], "item") == set()
    assert _targets("x.i_brand", "column", ["sc.customer_id_x"],
                    "customer_id") == set()
    # field part still matches — positive paths intact
    assert "v1" in _targets("x.i_brand", "column", ["item.i_brand"], "i_brand")
    assert "v1" in _targets("customer_id", "column", [], "customer_id")
    assert "v1" in _targets("sc.customer_id", "column", [], "customer_id")
    # J12-9 kept semantics: alias-qualified labels match by suffix (the
    # alias-copy seed `p1.data_dt` matching `bdm_acc_loan_info.data_dt`)
    assert "v1" in _targets("p1.data_dt", "column", [], "data_dt")


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


# ══════════════════════════════════════════════════════════════════════
# D1/D2: highlight line mapping — comment lines and (0,0) placeholders
# ══════════════════════════════════════════════════════════════════════

def test_d1_table_var_maps_to_from_line_not_comment():
    """D1: a table variable whose name appears in the header comment must
    map to its real FROM line — never the comment line."""
    from app.extractor.sql_line_mapper import map_variables_to_lines

    sql = (
        "-- 源表名：ODS [ods_hub_lsacmsp] BDM [bdm_acc_loan_info]\n"
        "-- 创建时间：2025-11-11\n"
        "SELECT loan_id\n"
        "FROM bdm_acc_loan_info\n"
        "WHERE data_dt = '2026-01-01';\n"
    )
    line_map = map_variables_to_lines(
        [{"id": "t1", "sql_expression": "bdm_acc_loan_info"},
         {"id": "c1", "sql_expression": "data_dt = '2026-01-01'"}],
        sql)
    assert line_map["t1"] == (4, 4), line_map   # FROM line, not comment line 1
    assert line_map["c1"] == (5, 5), line_map


def test_d2_highlights_never_zero_or_comment_lines():
    """D2: node-carried lines only — (0,0) placeholders never reach the
    payload and comment positions never occur (the extractor's line lookup
    skips comment lines, so node lines are real code lines).

    R25: highlights are per-edge single lines (highlight_line), derived at
    L2 build time — the response-level highlights list and the
    line_map-based _compute_highlight_ranges are gone. Every final edge
    carries highlight_line/flow_kind/reason; highlight_line is a real code
    line (>= 1, never the header comment line 1)."""
    sql = ("-- 源表名：bdm_acc_loan_info\n"
           "SELECT loan_id FROM bdm_acc_loan_info WHERE data_dt = '2026-01-01';")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("d2_min.sql", sql)
    ws_id = create_workspace(buf.getvalue())
    try:
        graph = _build_l2_graph(ws_id, "d2_min.sql", sql,
                                "bdm_acc_loan_info", "data_dt",
                                relevance_filter=True)
        edges = [e["data"] for e in graph["edges"]]
        assert edges, "the D2 script must produce edges"
        for e in edges:
            assert isinstance(e.get("highlight_line"), int) \
                and e["highlight_line"] >= 1, e
            assert e.get("flow_kind"), e
            assert e.get("reason"), e
            assert e["highlight_line"] != 1, e  # comment line 1
        # the predicate line 2 (WHERE data_dt = ...) is covered by the
        # field-flow payload
        assert any(e["highlight_line"] == 2 for e in edges), \
            [e["highlight_line"] for e in edges]
    finally:
        delete_workspace(ws_id)


# ══════════════════════════════════════════════════════════════════════
# L2 data_dt investigation — real script (samples/sql_sample_v1)
# ══════════════════════════════════════════════════════════════════════

LOAN_INFO_SCRIPT = SAMPLES_DIR / "sql_sample_v1" / "BDM_ACC_LOAN_INFO_SUP_M.sql"
LOAN_INFO_NAME = "BDM_ACC_LOAN_INFO_SUP_M.sql"


@pytest.fixture
def loan_info_ws():
    """Workspace with the real BDM_ACC_LOAN_INFO_SUP_M.sql (zip-upload path)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(LOAN_INFO_NAME, LOAN_INFO_SCRIPT.read_text())
    ws_id = create_workspace(buf.getvalue())
    yield ws_id
    delete_workspace(ws_id)


def test_data_dt_seed_lands_on_searched_table(loan_info_ws):
    """L2 data_dt investigation (user complaint): searching
    bdm_acc_loan_info.data_dt must show the seed field on the searched
    base table's compound node — not on the first p1 alias instance.

    v3.3.140 (strict table.field flow): the seed field appears on BOTH
    the physical node and every node that carries the same field instance
    — the p1 alias copy (P1 MOVE→COPY) and the INSERT target's partition
    column — each marked is_target.

    R46a (2026-08-31, AD3 adjudication + coordinator amendment): the stamp
    is scoped to the searched table's entity set PLUS the DML write-target
    compounds that RECEIVE the field's value (the R44 family-1 write
    twins) — so the two write targets below keep their seed claim, while
    the READ-side same-name chips of join partners (the FSB phantom class)
    lose theirs (tests/test_target_scoping.py pins both halves)."""
    sql = LOAN_INFO_SCRIPT.read_text()
    graph = _build_l2_graph(loan_info_ws, LOAN_INFO_NAME, sql,
                            "bdm_acc_loan_info", "data_dt",
                            relevance_filter=True)
    keeper = next(n["data"] for n in graph["nodes"]
                  if n["data"].get("table_name") == "bdm_acc_loan_info"
                  and n["data"].get("type") == "source_table")
    seeds = [n["data"] for n in graph["nodes"] if n["data"].get("is_target")]
    assert len(seeds) >= 2, \
        f"expected the physical + write-target copy seeds, got {len(seeds)}"
    physical = [s for s in seeds if s["parent"] == keeper["id"]]
    assert len(physical) == 1, \
        f"exactly one seed must sit on the searched table node, got {physical}"
    # P1 MOVE→COPY / R44 family 1: the write targets that RECEIVE the
    # field's value carry the seed instance too.
    copies = [s for s in seeds if s["parent"] != keeper["id"]]
    assert copies, "seed copies must appear on the write-target nodes"
    write_targets = {"bdm_acc_loan_info_sup", "rrcdm_job_log_exec_par"}
    parents = {next(n["data"]["table_name"] for n in graph["nodes"]
                    if n["data"].get("id") == s["parent"])
               for s in copies}
    assert parents <= write_targets, (
        f"a READ-side foreign compound claims the seed: {parents}")

    # The seed's data flow stays visible: FILTER edges survive at field
    # level (P2 — no promotion to the alias/table node).
    seed_ids = {s["id"] for s in seeds}
    incident = [e["data"] for e in graph["edges"]
                if e["data"]["source"] in seed_ids
                or e["data"]["target"] in seed_ids]
    assert incident, "the seed fields must have incident edges"
    assert any(e["edge_type"] == "FILTER" for e in incident), \
        [e["edge_type"] for e in incident]


def test_data_dt_highlights_cover_predicate_line(loan_info_ws):
    """L2 data_dt investigation (complaint 1): the per-edge payload must
    cover the real predicate line 18 and never cover the header comment
    line 3 or line 0 — through the real get_level2_graph response path.

    R25: highlights are per-edge single lines (highlight_line), derived at
    L2 build time — the response-level `highlights` list is gone; every
    edge carries highlight_line/flow_kind/reason instead."""
    from app.services.dataflow_service import get_level2_graph

    # Real response path (relevance-filtered): no line 0, no comment
    # lines, predicate line 18 (WHERE data_dt = '$(load_date)') covered.
    out = get_level2_graph(loan_info_ws, loan_info_ws, LOAN_INFO_NAME,
                           "bdm_acc_loan_info", "data_dt")
    assert "error" not in out, out
    edges = [e["data"] for e in out["graph"]["edges"]]
    assert edges, "the flagship must produce edges"
    for e in edges:
        assert isinstance(e.get("highlight_line"), int) \
            and e["highlight_line"] >= 1, e
        assert e.get("flow_kind"), e
        assert e.get("reason"), e
        assert e["highlight_line"] != 3, e  # header comment line
    assert any(e["highlight_line"] == 18 for e in edges), \
        [e["highlight_line"] for e in edges]


def test_d1_line_map_recomputed_from_stale_cache(loan_info_ws):
    """D1: cached line_maps predate comment-line skipping — the L2 builder
    recomputes on cache read (no cache-version bump available), so cached
    workspaces behave like fresh analyses."""
    from app.services import l2_builder as l2b

    sql = LOAN_INFO_SCRIPT.read_text()
    l2b._load_or_build_graph(loan_info_ws, LOAN_INFO_NAME, sql)  # write caches
    cache_dir = get_workspace_dir(loan_info_ws) / "cache"
    graph_cache = next(cache_dir.glob("graph_*.json"))
    cached = json.loads(graph_cache.read_text())
    assert cached.get("line_map"), "cache must carry a line_map"
    cached["line_map"] = {}  # simulate a pre-D1 stale cache
    graph_cache.write_text(json.dumps(cached))

    full_graph, _, _ = l2b._load_or_build_graph(loan_info_ws, LOAN_INFO_NAME, sql)
    lm = full_graph.get("line_map", {})
    assert lm, "line_map must be recomputed on cache read"
    starts = {v[0] for v in lm.values() if v[0] >= 1}
    assert 3 not in starts, \
        f"comment line 3 must never be a mapping target, got starts {sorted(starts)[:20]}"
