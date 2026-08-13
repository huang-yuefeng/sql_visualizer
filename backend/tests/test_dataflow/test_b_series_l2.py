"""B-series L2-builder tests.

  - B4: no " ↻" twin stamps — the field dedup key uses the UNDECORATED
    label, so same-named computed fields under one parent merge instead
    of twinning (measured on the sample script: 27 twin fields → 0).
  - B3: parentless fields — a field with no source_tables resolves its
    parent via the alias/derived-table scope that DEFINES it (the CTE or
    subquery owning its context), falling back to the enclosing scope
    (measured on the sample script: 15 parentless → 0; the loan_final
    CTE output columns parent under the loan_final CTE node).
  - C-9: per-statement fold (J12-16 user ruling, 2026-08-11) — the L2
    field dedup key is (parent, undecorated_label) WITHOUT stmt_idx:
    same-named fields from DIFFERENT top-level statements fold into ONE
    display field per physical table (the keeper = the first occurrence).
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
from app.extractor.variable_extractor_v2 import (
    extract_variables_from_sql, EXTRACTOR_VERSION,
)

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
    """Extraction-attributed field ownership under the subquery VTs
    (unfiltered L2, seed bdm_acc_loan_info/lending_ref). Pin updated
    2026-08-10 per extraction-attributed ownership (Team A probe): the
    old assertion (every subquery node carries fields) only passed via the
    deleted Bug-31 SCHEMA bulk injection. Actual ownership:
      - ⟐ subq1 -> {lending_ref} (its SELECT output column)
      - ⟐ accu/subq3 -> {data_dt}, ⟐ branch/subq4 -> {MAXp_dt}
        (the nested WHERE-subquery outputs)
      - ⟐ subq / ⟐ subq2 / ⟐ p2 -> no fields: their outputs resolved to
        the physical bdm_acc_loan_info at extraction (I2 exact
        source_tables), so the derived-table columns parent under the
        physical compound, not under the VT
      - the rollover CTE's loan_maturity_dt parents under the
        bdm_acc_loan_info compound node.
    #223 (2026-08-13): subquery-output VTs display as `output(X)` — the
    `label` matches carry the display label (`output(subq1)`), while
    `table_name` keeps the internal `⟐ X` (unchanged)."""
    ws_id, sql = sample_ws
    graph = _build_l2_graph(ws_id, "BDM_ACC_LOAN_INFO_SUP_M.sql", sql,
                            TABLE, "lending_ref", relevance_filter=False)
    nodes = [n["data"] for n in graph["nodes"]]

    def kids_of(nid):
        return {n["label"] for n in nodes if n.get("parent") == nid}

    sq = [n for n in nodes
          if n.get("variable_type") in ("subquery", "virtual_table")]
    ctx_to_id = {n.get("context"): n["id"] for n in sq if n.get("context")}
    # the /subq1/subq and /subq3 scopes exist as scope-bearing compound nodes
    assert any(c and c.endswith("/subq1/subq") for c in ctx_to_id), ctx_to_id
    assert any(c and c.endswith("/subq3") for c in ctx_to_id), ctx_to_id

    def vt(label, ctx_suffix):
        hits = [n for n in sq
                if n.get("variable_type") == "virtual_table"
                and n.get("label") == label
                and (n.get("context") or "").endswith(ctx_suffix)]
        assert len(hits) == 1, \
            f"expected exactly one VT {label!r} ctx *{ctx_suffix}: {hits}"
        return hits[0]

    # exact extraction-attributed ownership (Team A probe, 2026-08-10);
    # labels carry the #223 display form `output(X)` for ⟐ VTs
    assert kids_of(vt("output(subq1)", "/subq1")["id"]) == {"lending_ref"}, \
        kids_of(vt("output(subq1)", "/subq1")["id"])
    assert kids_of(vt("output(accu/subq3)", ":join:accu/subq3")["id"]) == {"data_dt"}, \
        kids_of(vt("output(accu/subq3)", ":join:accu/subq3")["id"])
    assert kids_of(vt("output(branch/subq4)", ":join:branch/subq4")["id"]) == {"MAXp_dt"}, \
        kids_of(vt("output(branch/subq4)", ":join:branch/subq4")["id"])
    # subq / subq2 / the p2 VTs carry NO fields (their outputs resolved to
    # the physical bdm_acc_loan_info at extraction -- I2 source_tables)
    for label, suffix in (("output(subq)", "/subq1/subq"),
                          ("output(subq2)", "/subq/subq2"),
                          ("output(p2)", ":join:p2")):
        for v in [n for n in sq
                  if n.get("variable_type") == "virtual_table"
                  and n.get("label") == label
                  and (n.get("context") or "").endswith(suffix)]:
            assert not kids_of(v["id"]), \
                f"VT {v['label']!r} ({v.get('context')}) should carry no fields: {kids_of(v['id'])}"
    # the rollover CTE's loan_maturity_dt parents under the physical table
    bdm = [n for n in nodes if n.get("variable_type") == "table"
           and n.get("label") == "bdm_acc_loan_info"]
    assert len(bdm) == 1, bdm
    assert "loan_maturity_dt" in kids_of(bdm[0]["id"]), \
        f"loan_maturity_dt not under bdm_acc_loan_info: {kids_of(bdm[0]['id'])}"


# ── C-9: per-statement dedup ────────────────────────────────────────────

TWO_STMT_SQL = """-- same bare read in TWO top-level statements
SELECT loan_id FROM bdm_acc_loan_info WHERE data_dt = '2026-01-01';
SELECT loan_id, loan_bal FROM bdm_acc_loan_info WHERE loan_bal > 0;"""


def test_c9_per_statement_dedup():
    """J12-16 (user ruling 2026-08-11, binding): the field dedup key
    drops stmt_idx — same-named fields from DIFFERENT top-level
    statements FOLD into ONE display field per physical table. loan_id
    appears ONCE (the keeper = the first occurrence, stmt TOP0); the
    FIXED payload pins the single folded field and its keeper context.
    (Pre-ruling the payload was TWO fields, TOP0 + TOP1.)"""
    ws_id = _ws_for(TWO_STMT_SQL, "two_stmt.sql")
    try:
        graph = _build_l2_graph(ws_id, "two_stmt.sql", TWO_STMT_SQL,
                                TABLE, "loan_id", relevance_filter=False)
        fields = _fields_of_parent(graph, TABLE)
        loan_ids = [f for f in fields if f["label"] == "loan_id"]
        assert len(loan_ids) == 1, \
            f"expected 1 folded loan_id field (J12-16), got {len(loan_ids)}"

        # the single folded field keeps the FIRST occurrence's identity
        # (the keeper — the TOP0 statement's extraction context)
        res = extract_variables_from_sql(TWO_STMT_SQL, "two_stmt.sql")
        id_to_ctx = {v.id: v.context for v in res.variables}
        ctx = id_to_ctx.get(loan_ids[0]["original_id"])
        assert ctx == "TOP0", f"keeper ctx {ctx!r}, expected 'TOP0'"
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

        # #197: versioned analysis-key contract — md5 over
        # (EXTRACTOR_VERSION, script_name, sql_text), identical to
        # folder_index_service's write side and the L2 read sides.
        cache_key = hashlib.md5(
            (EXTRACTOR_VERSION + "|" + "two_stmt.sql" + TWO_STMT_SQL)
            .encode()).hexdigest()[:12]
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
        # #197: versioned analysis-key contract — md5 over
        # (EXTRACTOR_VERSION, script_name, sql_text), identical to
        # folder_index_service's write side and the L2 read sides.
        cache_key = hashlib.md5(
            (EXTRACTOR_VERSION + "|" + "two_stmt.sql" + TWO_STMT_SQL)
            .encode()).hexdigest()[:12]
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

        # #197: versioned analysis-key contract — md5 over
        # (EXTRACTOR_VERSION, script_name, sql_text), identical to
        # folder_index_service's write side and the L2 read sides.
        cache_key = hashlib.md5(
            (EXTRACTOR_VERSION + "|" + "two_stmt.sql" + TWO_STMT_SQL)
            .encode()).hexdigest()[:12]
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
