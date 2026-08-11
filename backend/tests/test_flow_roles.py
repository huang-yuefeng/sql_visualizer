"""R19.1 / R19.2 / R19.5 — flow source, flow targets, net-flow roles (Team F).

Pure helpers under test (app/extractor/lineage.py, additive — the Jaccard
gate keys id/source/target/edge_type/highlight_line are untouched):

  - flow_source_id()    R19.1 exposure: the searched seed's physical
                        table node. The filtered L2 flow view has exactly
                        one flow source = the searched table.field — a
                        USER-DEFINED source (the search), never inferred
                        (v3.3.140 seed semantics); this helper only
                        exposes the node for display.
  - flow_targets()      R19.2 decision procedure: T is a flow target iff
                        (a) T is a DML statement's write target
                        (extraction-time DML attribution) AND (b) T's
                        write leg `output → T` is in the seed's flow
                        closure (reachability walk).
  - classify_flow_roles()  R19.5 full-view (no search) table roles:
                        net-flow classification over FLOW edges only
                        (every edge type EXCEPT the non-flow family
                        ALIAS/SCHEMA/SUBSET — identity/containment/
                        padding; TABLE_FLOW IS flow — R19.4 SCHEMA is
                        not; self-loops excluded): out > in → source,
                        in > out → target, balanced → waypoint (both
                        roles, e.g. sup).

Evidence pinned here (samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql):
  - seed bdm_acc_loan_info.data_dt → flow targets
    {bdm_acc_loan_info_sup (sup@160), rrcdm_job_log_exec_par (rrcdm@211)}
    (raw DML write legs: ⟐ output@160[TOP0] → sup@160 and
     ⟐ output@211[TOP1] → rrcdm@211, both endpoints in the closure)
  - full view (no search): bdm_acc_loan_info = source (read-only, flow
    out dominates), bdm_acc_loan_info_sup = waypoint (balanced), and
    rrcdm_job_log_exec_par = target (flow in dominates — the write leg).
"""
import io
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = BACKEND_DIR.parent / "samples"

from app.extractor.lineage import (
    classify_flow_roles,
    flow_source_id,
    flow_targets,
)
from app.extractor.adapter import run_full_analysis
from app.extractor.physical_model import build_physical_model
from app.services.graph_service import build_graph_data
from app.services.l2_builder import _build_l2_graph
from app.services.workspace_service import create_workspace, delete_workspace

LOAN_INFO = SAMPLES_DIR / "sql_sample_v1" / "BDM_ACC_LOAN_INFO_SUP_M.sql"
LOAN_INFO_NAME = "BDM_ACC_LOAN_INFO_SUP_M.sql"

# Compound table node types of the L2 assembly (the node set the wiring
# recipe passes to classify_flow_roles in the full view).
COMPOUND_TABLE_TYPES = {
    "source_table", "intermediate_table", "output_table",
    "cte_table", "alias_table",
}


@pytest.fixture
def loan_ws():
    """Workspace with the real BDM_ACC_LOAN_INFO_SUP_M.sql (zip-upload path)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(LOAN_INFO_NAME, LOAN_INFO.read_text())
    ws_id = create_workspace(buf.getvalue())
    yield ws_id
    delete_workspace(ws_id)


def _raw_graph(sql: str, name: str) -> tuple:
    """Run the extraction pipeline and return (raw full graph, physical
    model) — the flow helpers consume the model (J12-10 stage 3: model
    entities replace the label-scanned reconstruction)."""
    result = run_full_analysis(sql, name)
    graph = build_graph_data(result)
    model = build_physical_model(result, script_name=name)
    return graph, model


# ══════════════════════════════════════════════════════════════════════
# classify_flow_roles — R19.5 net-flow classification (unit level)
# ══════════════════════════════════════════════════════════════════════

def _ed(src: str, tgt: str, etype: str, category: str | None = None) -> dict:
    d = {"source": src, "target": tgt, "edge_type": etype}
    if category is not None:
        d["category"] = category
    return d


def test_roles_direction_dominance():
    """Out > in → source, in > out → target, equal → waypoint (incl. 0-0)."""
    edges = [
        _ed("a", "b", "REF"),        # a out / b in
        _ed("c", "a", "DML"),        # c out / a in
        _ed("a", "d", "FILTER"),     # a out / d in
        _ed("x", "y", "REF"),        # x out / y in  (balanced pair)
        _ed("y", "x", "JOIN"),       # y out / x in  (balanced pair)
    ]
    roles = classify_flow_roles(edges, {"a", "b", "c", "d", "x", "y", "iso"})
    assert roles["a"] == "source"     # 2 out, 1 in
    assert roles["b"] == "target"     # 0 out, 1 in
    assert roles["c"] == "source"     # 1 out, 0 in
    assert roles["d"] == "target"     # 0 out, 1 in
    assert roles["x"] == "waypoint"   # 1 out, 1 in — balanced = both roles
    assert roles["y"] == "waypoint"   # 1 out, 1 in
    assert roles["iso"] == "waypoint"  # 0-0 is balanced


def test_roles_non_flow_edges_excluded():
    """ALIAS/SCHEMA/SUBSET are never flow; TABLE_FLOW IS flow."""
    edges = [
        _ed("a", "b", "ALIAS"),       # identity hop — not flow
        _ed("a", "b", "SCHEMA"),      # ownership — not flow (R19.4)
        _ed("a", "b", "SUBSET"),      # connectivity padding — not flow
        _ed("a", "b", "TABLE_FLOW"),  # table-to-table flow — COUNTS
        _ed("a", "b", "REF"),         # flow
    ]
    roles = classify_flow_roles(edges, {"a", "b"})
    assert roles["a"] == "source"   # TABLE_FLOW + REF out
    assert roles["b"] == "target"   # TABLE_FLOW + REF in


def test_roles_raw_shape_edge_type_decides():
    """Raw edges carry no category — the edge type decides flow-ness."""
    edges = [
        _ed("a", "b", "SCHEMA"),
        _ed("a", "b", "TABLE_FLOW"),
        _ed("a", "b", "DML"),
    ]
    roles = classify_flow_roles(edges, {"a", "b"})
    assert roles["a"] == "source"   # TABLE_FLOW + DML are flow, SCHEMA is not
    assert roles["b"] == "target"


def test_roles_table_flow_read_and_write_legs_count():
    """The L2 write leg (TABLE_FLOW, re-typed from DML) is flow-in; the
    read-into-output TABLE_FLOW is flow-out — sup's two legs balance."""
    edges = [
        _ed("out1", "sup", "TABLE_FLOW"),   # write leg — flow in to sup
        _ed("sup", "out2", "TABLE_FLOW"),   # read into output — flow out
    ]
    roles = classify_flow_roles(edges, {"sup"})
    assert roles["sup"] == "waypoint"   # 1 in / 1 out — both roles


def test_roles_self_loops_excluded_and_wrapped_shape():
    """Self-loops never count; {"data": {...}} wrapped edges work."""
    edges = [
        {"data": _ed("a", "a", "REF")},       # self-loop — excluded
        {"data": _ed("a", "b", "REF")},       # a out / b in
    ]
    roles = classify_flow_roles(edges, {"a", "b"})
    assert roles["a"] == "source"
    assert roles["b"] == "target"


def test_roles_empty_inputs():
    assert classify_flow_roles([], set()) == {}
    assert classify_flow_roles([], {"a"}) == {"a": "waypoint"}


# ══════════════════════════════════════════════════════════════════════
# flow_targets — R19.2 decision procedure (unit level, real pipeline)
# ══════════════════════════════════════════════════════════════════════

def test_flow_targets_minimal_dml_pipeline():
    """One INSERT...SELECT: the seed's read reaches the write target → the
    write target is a flow target (write leg output→T in the closure)."""
    sql = (
        "INSERT OVERWRITE TABLE stg_a PARTITION(data_dt='$(load_date)')\n"
        "SELECT c1 FROM bdm_a WHERE data_dt = '$(load_date)';\n"
    )
    g, pm = _raw_graph(sql, "min_dml.sql")
    node_by_id = {n["data"]["id"]: n["data"] for n in g["nodes"]}
    targets = flow_targets(g, "bdm_a", "data_dt", physical_model=pm)
    assert targets, "the seed must reach at least one DML target"
    assert {node_by_id[i]["label"] for i in targets} == {"stg_a"}


def test_flow_targets_pure_select_no_dml_target():
    """Pure SELECT: no DML write targets → the flow target set is empty."""
    sql = "SELECT c1 FROM bdm_a WHERE data_dt = '$(load_date)';\n"
    g, pm = _raw_graph(sql, "pure_select.sql")
    assert flow_targets(g, "bdm_a", "data_dt", physical_model=pm) == set()


def test_flow_source_id_unit():
    """R19.1: the seed's physical table node is exposed by label."""
    sql = "SELECT c1 FROM bdm_a WHERE data_dt = '$(load_date)';\n"
    g, pm = _raw_graph(sql, "source_id.sql")
    nid = flow_source_id(g, "bdm_a", physical_model=pm)
    assert nid is not None
    nd = next(n["data"] for n in g["nodes"] if n["data"]["id"] == nid)
    assert nd["label"] == "bdm_a"
    assert nd["variable_type"] == "table"
    assert flow_source_id(g, "no_such_table", physical_model=pm) is None
    assert flow_source_id(g, "", physical_model=pm) is None


# ══════════════════════════════════════════════════════════════════════
# Evidence — BDM_ACC_LOAN_INFO_SUP_M.sql (user ruling 2026-08-11)
# ══════════════════════════════════════════════════════════════════════

def test_flow_targets_bdm_seed_evidence(loan_ws):
    """R19.2 evidence: seed bdm_acc_loan_info.data_dt must reach exactly
    sup (bdm_acc_loan_info_sup@160) AND rrcdm (rrcdm_job_log_exec_par@211).

    Raw write legs (dependency_graph Phase 1c-extra2):
      ⟐ output@160[TOP0] --DML/INSERT--> bdm_acc_loan_info_sup@160[TOP0]
      ⟐ output@211[TOP1] --DML/INSERT--> rrcdm_job_log_exec_par@211[TOP1]
    both with both endpoints in the bdm.data_dt flow closure.
    """
    g, pm = _raw_graph(LOAN_INFO.read_text(), LOAN_INFO_NAME)
    node_by_id = {n["data"]["id"]: n["data"] for n in g["nodes"]}
    targets = flow_targets(g, "bdm_acc_loan_info", "data_dt", physical_model=pm)
    labels = sorted({node_by_id[i]["label"] for i in targets})
    assert labels == ["bdm_acc_loan_info_sup", "rrcdm_job_log_exec_par"], \
        f"bdm seed flow targets = {labels}"

    # both targets carry the extraction-time DML attribution (a)
    for i in targets:
        nd = node_by_id[i]
        assert (nd["variable_type"] == "table"
                and "INSERT" in (nd.get("defined_in") or "").upper()), nd


def test_flow_targets_sup_seed_evidence(loan_ws):
    """R19.2 evidence (sup seed): the sup data_dt seed reaches rrcdm — and
    sup itself is a DML write target whose write leg is also in the sup
    closure (roles are per-edge/path; sup is BOTH target and waypoint)."""
    g, pm = _raw_graph(LOAN_INFO.read_text(), LOAN_INFO_NAME)
    node_by_id = {n["data"]["id"]: n["data"] for n in g["nodes"]}
    targets = flow_targets(g, "bdm_acc_loan_info_sup", "data_dt", physical_model=pm)
    labels = sorted({node_by_id[i]["label"] for i in targets})
    assert labels == ["bdm_acc_loan_info_sup", "rrcdm_job_log_exec_par"], \
        f"sup seed flow targets = {labels}"


def test_full_view_roles_evidence(loan_ws):
    """R19.5 evidence: full-view (no search) net-flow roles.

    bdm_acc_loan_info     → source   (read-only; flow out dominates:
                           out = TABLE_FLOW + COMPUTED + 2 REF + 2 FILTER
                           + 4 JOIN = 10 vs in = 2 REF)
    bdm_acc_loan_info_sup → source   (J12-16 FIXED payload: the
                           DML-simplification retarget now runs BEFORE
                           the field promotion — the orchestrator order
                           the per-statement edge instances need to
                           diverge before the (source, target, edge_type)
                           combine collapses them — so the sup write
                           statement's column-read bypass REF (L160) is
                           redirected through its ⟐ output BEFORE its
                           field source promotes to sup; it survives as
                           sup→output REF@160 instead of being dropped as
                           a sup→sup self-loop. out = TABLE_FLOW read-leg
                           + REF@160 + REF@199 + JOIN = 4 vs
                           in = write leg + 2 COMPUTED = 3)
    rrcdm_job_log_exec_par → target  (flow in dominates — the write leg:
                           0 out vs 1 in)
    """
    sql = LOAN_INFO.read_text()
    l2 = _build_l2_graph(loan_ws, LOAN_INFO_NAME, sql, "", "",
                         relevance_filter=False)
    table_ids = {n["data"]["id"] for n in l2["nodes"]
                 if n["data"].get("type") in COMPOUND_TABLE_TYPES}
    roles = classify_flow_roles(l2["edges"], table_ids)
    label_of = {n["data"]["id"]: n["data"].get("table_name")
                or n["data"].get("label")
                for n in l2["nodes"]}
    by_label = {}
    for nid, lab in label_of.items():
        by_label.setdefault(lab, []).append(nid)

    assert roles[by_label["bdm_acc_loan_info"][0]] == "source"
    assert roles[by_label["bdm_acc_loan_info_sup"][0]] == "source"
    assert roles[by_label["rrcdm_job_log_exec_par"][0]] == "target"

    # every compound table node got exactly one role
    assert set(roles) == table_ids
    assert set(roles.values()) <= {"source", "target", "waypoint"}


def test_flow_source_id_evidence(loan_ws):
    """R19.1 evidence: the searched seed's table node is exposed; the
    filtered view's flow source is the seed (single, user-defined)."""
    sql = LOAN_INFO.read_text()
    g, pm = _raw_graph(sql, LOAN_INFO_NAME)
    nid = flow_source_id(g, "bdm_acc_loan_info", physical_model=pm)
    assert nid is not None
    nd = next(n["data"] for n in g["nodes"] if n["data"]["id"] == nid)
    assert nd["label"] == "bdm_acc_loan_info"
    # several raw instances exist (line 16 CTE read, line 29 subquery
    # read, line 84 loan_final read); the helper returns one of them —
    # all merge into the single label-keyed L2 keeper via id_map.
    matches = [n["data"]["id"] for n in g["nodes"]
               if n["data"].get("variable_type") in ("table", "view")
               and n["data"].get("label") == "bdm_acc_loan_info"]
    assert len(matches) >= 1
    assert nid in matches
