"""B-series L2-builder tests.

  - B4: no " ↻" twin stamps — the field dedup key uses the UNDECORATED
    label, so same-named computed fields under one parent merge instead
    of twinning (measured on the sample script: 27 twin fields → 0).
  - B3: parentless fields — a field with no source_tables resolves its
    parent via the alias/derived-table scope that DEFINES it (the CTE or
    subquery owning its context), falling back to the enclosing scope
    (measured on the sample script: 15 parentless → 0; the loan_final
    CTE output columns parent under the loan_final CTE node).
  - C-9: per-statement dedup — the L2 field dedup key is
    (parent, undecorated_label, stmt_idx): same-named fields from
    DIFFERENT top-level statements stay distinct.
  - C-10: the dataflow_service miss path writes the versioned GRAPH cache
    ({GRAPH_CACHE_PREFIX}_{cache_key}.json, format_version 3) — it
    previously only wrote the schemas cache, so every on-demand build
    re-ran the full analysis.
  - C-2(b): both L2 miss paths prefer analysis_{cache_key}.json (the
    folder-index cache) over re-running the full analysis pipeline.
"""

import io
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.workspace_service import (
    create_workspace,
    delete_workspace,
    get_workspace_dir,
)
from app.services.l2_builder import _build_l2_graph
from app.services.dataflow_service import get_level2_graph
from app.services.cache_keys import GRAPH_CACHE_PREFIX
from app.extractor.variable_extractor_v2 import extract_variables_from_sql

SAMPLE_PATH = (BACKEND_DIR.parent / "samples" / "sql_sample_v1"
               / "BDM_ACC_LOAN_INFO_SUP_M.sql")

TABLE = "bdm_acc_loan_info"


def _ws_for(sql: str, name: str = "script.sql") -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, sql)
    return create_workspace(buf.getvalue())


def _fields_of_parent(graph: dict, parent_label: str) -> list:
    by_id = {n["data"]["id"]: n["data"] for n in graph["nodes"]}
    return [n["data"] for n in graph["nodes"]
            if n["data"].get("variable_type") == "field"
            and by_id.get(n["data"].get("parent"), {}).get("label")
            == parent_label]


@pytest.fixture
def sample_ws():
    """Workspace with the real sql_sample_v1 repro script."""
    if not SAMPLE_PATH.exists():
        pytest.skip(f"sample script not found: {SAMPLE_PATH}")
    sql = SAMPLE_PATH.read_text()
    ws_id = _ws_for(sql, "BDM_ACC_LOAN_INFO_SUP_M.sql")
    yield ws_id, sql
    delete_workspace(ws_id)


# ── B4: no twin stamps ──────────────────────────────────────────────────

def test_b4_no_twin_stamps(sample_ws):
    """The full sample graph shows no " ↻"-stamped fields (27 before B4)."""
    ws_id, sql = sample_ws
    graph = _build_l2_graph(ws_id, "BDM_ACC_LOAN_INFO_SUP_M.sql", sql,
                            TABLE, "lending_ref", relevance_filter=False)
    twins = [n["data"]["label"] for n in graph["nodes"]
             if n["data"].get("variable_type") == "field"
             and "↻" in n["data"].get("label", "")]
    assert not twins, f"twin-stamped fields remain: {twins}"


def test_b4_no_twin_stamps_filtered(sample_ws):
    """Same invariant on the relevance-filtered graph (the user-facing
    path through get_level2_graph)."""
    ws_id, sql = sample_ws
    graph = _build_l2_graph(ws_id, "BDM_ACC_LOAN_INFO_SUP_M.sql", sql,
                            TABLE, "lending_ref", relevance_filter=True)
    twins = [n["data"]["label"] for n in graph["nodes"]
             if n["data"].get("variable_type") == "field"
             and "↻" in n["data"].get("label", "")]
    assert not twins, f"twin-stamped fields remain: {twins}"


# ── B3: scope-based parent resolution ───────────────────────────────────

def test_b3_zero_parentless_fields(sample_ws):
    """No field node lacks a compound parent in the full sample graph
    (15 parentless before B3)."""
    ws_id, sql = sample_ws
    graph = _build_l2_graph(ws_id, "BDM_ACC_LOAN_INFO_SUP_M.sql", sql,
                            TABLE, "lending_ref", relevance_filter=False)
    container_ids = {n["data"]["id"] for n in graph["nodes"]
                     if n["data"].get("variable_type") in
                     ("table", "view", "cte", "virtual_table", "subquery",
                      "merge_target")}
    parentless = [n["data"]["label"] for n in graph["nodes"]
                  if n["data"].get("variable_type") == "field"
                  and n["data"].get("parent") not in container_ids]
    assert not parentless, f"parentless fields remain: {parentless}"


def test_b3_cte_output_columns_parent_under_cte(sample_ws):
    """The loan_final CTE output columns (branch_code_sk,
    limit_contract_no, abnormal_issue_flag, internal_key, interest_type,
    reserved_field8 — SCHEMA-edged to the CTE, no source_tables) parent
    under the loan_final CTE compound node, not the first table."""
    ws_id, sql = sample_ws
    graph = _build_l2_graph(ws_id, "BDM_ACC_LOAN_INFO_SUP_M.sql", sql,
                            TABLE, "lending_ref", relevance_filter=False)
    by_id = {n["data"]["id"]: n["data"] for n in graph["nodes"]}
    cte_nodes = [n["data"] for n in graph["nodes"]
                 if n["data"].get("variable_type") == "cte"
                 and n["data"].get("label") == "loan_final"]
    assert len(cte_nodes) == 1, \
        f"expected exactly one loan_final CTE node: {cte_nodes}"
    cte_id = cte_nodes[0]["id"]
    cte_fields = {n["data"]["label"] for n in graph["nodes"]
                  if n["data"].get("parent") == cte_id}
    assert {"branch_code_sk", "limit_contract_no", "abnormal_issue_flag",
            "internal_key", "interest_type", "reserved_field8"} <= cte_fields, \
        f"loan_final CTE fields missing: {cte_fields}"


def test_b3_subquery_scope_field_parents_under_its_subquery(sample_ws):
    """The rollover subquery's output columns (loan_maturity_dt in the
    subq1/subq3 scopes) parent under the matching subquery compound
    nodes — the scope owning their context."""
    ws_id, sql = sample_ws
    graph = _build_l2_graph(ws_id, "BDM_ACC_LOAN_INFO_SUP_M.sql", sql,
                            TABLE, "lending_ref", relevance_filter=False)
    by_id = {n["data"]["id"]: n["data"] for n in graph["nodes"]}
    # the subquery output containers are VIRTUAL_TABLE / SUBQUERY compound
    # nodes carrying their scope context
    sq = [n["data"] for n in graph["nodes"]
          if n["data"].get("variable_type") in ("subquery", "virtual_table")]
    ctx_to_id = {n.get("context"): n["id"] for n in sq if n.get("context")}
    # the /subq1/subq and /subq3 scopes exist as scope-bearing compound nodes
    assert any(c and c.endswith("/subq1/subq") for c in ctx_to_id), ctx_to_id
    assert any(c and c.endswith("/subq3") for c in ctx_to_id), ctx_to_id
    for c, nid in ctx_to_id.items():
        kids = {n["data"]["label"] for n in graph["nodes"]
                if n["data"].get("parent") == nid}
        assert kids, f"subquery node {c} has no fields"


# ── C-9: per-statement dedup ────────────────────────────────────────────

TWO_STMT_SQL = """-- same bare read in TWO top-level statements
SELECT loan_id FROM bdm_acc_loan_info WHERE data_dt = '2026-01-01';
SELECT loan_id, loan_bal FROM bdm_acc_loan_info WHERE loan_bal > 0;"""


def test_c9_per_statement_dedup():
    """Same-named fields from DIFFERENT top-level statements stay distinct
    under the same keeper: loan_id appears TWICE (stmt TOP0 + TOP1)."""
    ws_id = _ws_for(TWO_STMT_SQL, "two_stmt.sql")
    try:
        graph = _build_l2_graph(ws_id, "two_stmt.sql", TWO_STMT_SQL,
                                TABLE, "loan_id", relevance_filter=False)
        fields = _fields_of_parent(graph, TABLE)
        loan_ids = [f for f in fields if f["label"] == "loan_id"]
        assert len(loan_ids) == 2, \
            f"expected 2 per-statement loan_id fields, got {len(loan_ids)}"

        # the two fields trace back to the two statements' extraction contexts
        res = extract_variables_from_sql(TWO_STMT_SQL, "two_stmt.sql")
        id_to_ctx = {v.id: v.context for v in res.variables}
        ctxs = sorted({id_to_ctx[f["original_id"]] for f in loan_ids})
        assert ctxs == ["TOP0", "TOP1"], ctxs
    finally:
        delete_workspace(ws_id)


def test_c9_same_statement_still_merges():
    """The same bare read in ONE statement still produces ONE field (the
    per-statement dedup does not duplicate within a statement)."""
    sql = ("SELECT loan_id FROM bdm_acc_loan_info WHERE data_dt = '2026-01-01';\n"
           "SELECT loan_bal FROM bdm_acc_loan_info WHERE loan_bal > 0;")
    ws_id = _ws_for(sql, "one_stmt.sql")
    try:
        graph = _build_l2_graph(ws_id, "one_stmt.sql", sql,
                                TABLE, "loan_id", relevance_filter=False)
        fields = _fields_of_parent(graph, TABLE)
        by_name = {}
        for f in fields:
            by_name.setdefault(f["label"], []).append(f)
        assert len(by_name["loan_id"]) == 1
        assert len(by_name["loan_bal"]) == 1
    finally:
        delete_workspace(ws_id)


# ── C-10: the miss path writes the versioned graph cache ────────────────

def test_c10_miss_path_writes_graph_cache():
    """get_level2_graph's miss path writes {GRAPH_CACHE_PREFIX}_{key}.json
    with format_version 4 (v3.3.140: node data carries line_start/line_end
    for strict-flow highlights)."""
    ws_id = _ws_for(TWO_STMT_SQL, "two_stmt.sql")
    try:
        cache_dir = get_workspace_dir(ws_id) / "cache"
        if cache_dir.exists():
            for f in cache_dir.glob("*"):
                f.unlink()
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_key = hashlib.md5(
            ("two_stmt.sql" + TWO_STMT_SQL).encode()).hexdigest()[:12]
        out = get_level2_graph(ws_id, ws_id, "two_stmt.sql",
                               TABLE, "loan_id")
        assert "error" not in out, out

        graph_cache = cache_dir / f"{GRAPH_CACHE_PREFIX}_{cache_key}.json"
        assert graph_cache.exists(), \
            f"graph cache not written on miss: {graph_cache}"
        cached = json.loads(graph_cache.read_text())
        assert cached.get("format_version") == 4, cached.get("format_version")
        assert cached.get("nodes"), "cache has no nodes"
    finally:
        delete_workspace(ws_id)


# ── C-2(b): analysis cache preferred on the miss path ───────────────────

def test_c2b_analysis_cache_preferred(monkeypatch):
    """Both L2 miss paths read analysis_{key}.json instead of re-running
    run_full_analysis. A marker variable injected into the analysis cache
    must show up in the graph built by the miss path."""
    ws_id = _ws_for(TWO_STMT_SQL, "two_stmt.sql")
    try:
        cache_dir = get_workspace_dir(ws_id) / "cache"
        if cache_dir.exists():
            for f in cache_dir.glob("*"):
                f.unlink()
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Fabricate an analysis cache carrying a marker var
        cache_key = hashlib.md5(
            ("two_stmt.sql" + TWO_STMT_SQL).encode()).hexdigest()[:12]
        from app.extractor.adapter import run_full_analysis
        analysis = run_full_analysis(TWO_STMT_SQL, "two_stmt.sql")
        analysis["variables"].append({
            "id": "c2b_marker_id_1", "name": "__c2b_marker__",
            "variable_type": "table", "sql_expression": "",
            "defined_in": "FROM", "is_output": False,
            "source_tables": [], "source_columns": [], "context": "TOP0",
        })
        (cache_dir / f"analysis_{cache_key}.json").write_text(
            json.dumps(analysis, default=str))

        # If the miss path re-ran the analysis, the marker would vanish —
        # and the real analysis call is blocked so any fallthrough fails.
        import app.extractor.adapter
        import app.services.l2_builder as l2_builder_mod

        def _boom(*a, **k):
            raise AssertionError("run_full_analysis called — analysis "
                                 "cache not preferred")
        monkeypatch.setattr(app.extractor.adapter, "run_full_analysis", _boom)
        monkeypatch.setattr(l2_builder_mod, "run_full_analysis", _boom)

        out = get_level2_graph(ws_id, ws_id, "two_stmt.sql",
                               TABLE, "loan_id")
        assert "error" not in out, out

        # The graph cache written by the miss path was built FROM the
        # analysis cache — the marker survived.
        graph_cache = cache_dir / f"{GRAPH_CACHE_PREFIX}_{cache_key}.json"
        assert graph_cache.exists()
        assert "__c2b_marker__" in graph_cache.read_text(), \
            "marker missing — analysis cache was not the build source"
    finally:
        delete_workspace(ws_id)


def test_c2b_l2_builder_analysis_cache_preferred(monkeypatch):
    """_build_l2_graph's own miss path (_load_or_build_graph) prefers the
    analysis cache the same way."""
    ws_id = _ws_for(TWO_STMT_SQL, "two_stmt.sql")
    try:
        cache_dir = get_workspace_dir(ws_id) / "cache"
        if cache_dir.exists():
            for f in cache_dir.glob("*"):
                f.unlink()
        cache_dir.mkdir(parents=True, exist_ok=True)

        cache_key = hashlib.md5(
            ("two_stmt.sql" + TWO_STMT_SQL).encode()).hexdigest()[:12]
        from app.extractor.adapter import run_full_analysis
        analysis = run_full_analysis(TWO_STMT_SQL, "two_stmt.sql")
        analysis["variables"].append({
            "id": "c2b_marker_id_2", "name": "__c2b_marker__",
            "variable_type": "table", "sql_expression": "",
            "defined_in": "FROM", "is_output": False,
            "source_tables": [], "source_columns": [], "context": "TOP0",
        })
        (cache_dir / f"analysis_{cache_key}.json").write_text(
            json.dumps(analysis, default=str))

        import app.extractor.adapter
        import app.services.l2_builder as l2_builder_mod

        def _boom(*a, **k):
            raise AssertionError("run_full_analysis called — analysis "
                                 "cache not preferred")
        monkeypatch.setattr(app.extractor.adapter, "run_full_analysis", _boom)
        monkeypatch.setattr(l2_builder_mod, "run_full_analysis", _boom)

        graph = _build_l2_graph(ws_id, "two_stmt.sql", TWO_STMT_SQL,
                                TABLE, "loan_id", relevance_filter=False)
        assert graph.get("nodes")
        graph_cache = cache_dir / f"{GRAPH_CACHE_PREFIX}_{cache_key}.json"
        assert graph_cache.exists()
        assert "__c2b_marker__" in graph_cache.read_text()
    finally:
        delete_workspace(ws_id)
