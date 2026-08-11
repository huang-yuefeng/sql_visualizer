"""J12-10 Stage 4 — L1 builds on the physical model (display = projection).

These tests pin the model-backed L1 behavior:
  * per-script PhysicalModels are built from the analysis cache or the
    inline extraction pipeline — never from graph data (the graph-data
    form of build_physical_model cannot read edges: graph edges carry
    source/target while the model's Pass 3 reads source_id/target_id, so
    graph-backed models lose every edge and L1's direct/indirect
    classification diverged between fresh and cached workspaces);
  * lineage_field_pairs are identical fresh vs cached;
  * L1 field children are a pure projection of PhysicalTable/PhysicalField
    (one field node per (table, field) — no V3.2.6 propagation copies);
  * _absorb_p4 (raw-node-scan reconstruction) is deleted.
"""
import io
import json
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
    get_workspace_dir,
)
from app.services import l1_builder

SAMPLES_DIR = BACKEND_DIR.parent / "samples"
WORKFLOW_DIR = SAMPLES_DIR / "multi_workflow"
TARGET_TABLE = "stg_customers"
TARGET_FIELD = "customer_id"
LOAN_INFO_SCRIPT = SAMPLES_DIR / "sql_sample_v1" / "BDM_ACC_LOAN_INFO_SUP_M.sql"
LOAN_INFO_NAME = "BDM_ACC_LOAN_INFO_SUP_M.sql"


@pytest.fixture
def multi_workflow_ws():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(WORKFLOW_DIR.glob("step*.sql")):
            zf.write(f, f.name)
    ws_id = create_workspace(buf.getvalue())
    yield ws_id
    delete_workspace(ws_id)


def _l1(ws_id, indexed=False):
    script_names = sorted(f.name for f in WORKFLOW_DIR.glob("step*.sql"))
    if indexed:
        index_scripts(ws_id, script_names)
    return _build_l1_graph(ws_id, script_names, TARGET_TABLE, TARGET_FIELD)


def _l1_sig(l1):
    """Node/edge signature stable under layout-coordinate changes."""
    nodes = sorted(
        (d["data"]["id"], d["data"].get("label"), d["data"].get("type"),
         d["data"].get("parent", ""), d["data"].get("table_name", ""),
         d["data"].get("field_name", ""), d["data"].get("field_group", ""),
         bool(d["data"].get("is_target")))
        for d in l1["nodes"])
    edges = sorted(
        (d["data"]["id"], d["data"].get("edge_type"),
         d["data"].get("source"), d["data"].get("target"))
        for d in l1["edges"])
    return nodes, edges


def _field_children(l1, table_name):
    tbl_ids = {n["data"]["id"] for n in l1["nodes"]
               if n["data"].get("table_name") == table_name
               and n["data"].get("type") != "field"}
    return {n["data"].get("field_name")
            for n in l1["nodes"]
            if n["data"].get("type") == "field"
            and n["data"].get("parent") in tbl_ids}


def _field_group(l1, table_name, field_name):
    for n in l1["nodes"]:
        d = n["data"]
        if (d.get("type") == "field" and d.get("table_name") == table_name
                and d.get("field_name") == field_name):
            return d.get("field_group")
    return None


# ══════════════════════════════════════════════════════════════════════
# Fresh vs cached: identical L1 output (the graph-data-fallback regression)
# ══════════════════════════════════════════════════════════════════════

def test_l1_fresh_and_cached_identical(multi_workflow_ws):
    """Fresh (inline-pipeline models, no disk cache) and cached
    (analysis-cache models) L1 runs must be identical — node set, edges,
    field groups, pairs. A graph-data-backed model lost every edge
    (source/target vs source_id/target_id), so the fresh run classified
    fields 'indirect' that the cached run classified 'direct' — the bug
    this pins."""
    fresh = _l1(multi_workflow_ws, indexed=False)
    cached = _l1(multi_workflow_ws, indexed=True)
    assert _l1_sig(fresh) == _l1_sig(cached)
    assert {tuple(p) for p in fresh.get("lineage_field_pairs", [])} == \
        {tuple(p) for p in cached.get("lineage_field_pairs", [])}
    assert fresh.get("degraded") is False


# ══════════════════════════════════════════════════════════════════════
# Pair extraction: model-backed, unchanged pair set
# ══════════════════════════════════════════════════════════════════════

def test_l1_lineage_pairs_model_backed(multi_workflow_ws):
    """The pair set is unchanged by the model adoption: stg_customers +
    crm_customers only (no raw_orders/stg_orders leakage via the step3
    JOIN), identically on the fresh and the cached run."""
    fresh = _l1(multi_workflow_ws, indexed=False)
    cached = _l1(multi_workflow_ws, indexed=True)
    expected = {("stg_customers", "customer_id"), ("crm_customers", "customer_id")}
    assert {tuple(p) for p in fresh.get("lineage_field_pairs", [])} == expected
    assert {tuple(p) for p in cached.get("lineage_field_pairs", [])} == expected


def test_l1_pairs_covered_by_model_fields(multi_workflow_ws):
    """Every L1 pair is an actual PhysicalField of the owning script's
    model — built from the inline pipeline (fresh) and from the analysis
    cache (cached). The model is the extraction-time truth L1 projects."""
    from app.extractor.physical_model import build_physical_model
    from app.extractor.adapter import run_full_analysis

    script_names = sorted(f.name for f in WORKFLOW_DIR.glob("step*.sql"))
    sql_by_name = {n: (WORKFLOW_DIR / n).read_text() for n in script_names}

    l1 = _l1(multi_workflow_ws, indexed=False)
    pairs = {tuple(p) for p in l1.get("lineage_field_pairs", [])}
    assert pairs, "the workflow must produce pairs"

    # Inline-pipeline models (the fresh path).
    inline_fields = set()
    for name, sql in sql_by_name.items():
        m = build_physical_model(run_full_analysis(sql, name), script_name=name)
        inline_fields |= {(tbl.name, fld.name)
                          for tbl in m.tables.values() for fld in tbl.fields.values()}
    assert pairs <= inline_fields, \
        f"pairs {pairs - inline_fields} missing from inline model fields"

    # Analysis-cache models (the cached path) — same field sets.
    index_scripts(multi_workflow_ws, script_names)
    cache_fields = set()
    for ac_path in sorted(get_workspace_dir(multi_workflow_ws)
                          .glob("cache/analysis_*.json")):
        m = build_physical_model(json.loads(ac_path.read_text()),
                                 script_name=ac_path.stem)
        cache_fields |= {(tbl.name, fld.name)
                         for tbl in m.tables.values()
                         for fld in tbl.fields.values()}
    assert pairs <= cache_fields, \
        f"pairs {pairs - cache_fields} missing from cache-backed model fields"
    assert inline_fields == cache_fields, \
        "inline and cached models must expose identical field sets"


# ══════════════════════════════════════════════════════════════════════
# Field children: pure model projection, no V3.2.6 propagation copies
# ══════════════════════════════════════════════════════════════════════

def test_l1_field_children_direct_indirect_pinned(multi_workflow_ws):
    """Direct/indirect classification comes from the model BFS (seeded
    from every occurrence of any field named `field`, walked over the
    model's edges). Pinned: the customer_id closure reaches the
    customer/order pipeline; the downstream aggregation tables are
    off-path."""
    l1 = _l1(multi_workflow_ws, indexed=False)

    assert _field_group(l1, "stg_customers", "customer_id") == "direct"
    assert _field_group(l1, "crm_customers", "customer_id") == "direct"
    assert _field_group(l1, "raw_orders", "order_id") == "direct"
    assert _field_group(l1, "stg_orders", "amount") == "direct"
    # off-path tables: aggregation outputs
    assert _field_group(l1, "daily_summary", "total") == "indirect"
    assert _field_group(l1, "analytics_orders", "region") == "indirect"
    for d in l1["nodes"]:
        if d["data"].get("type") == "field":
            assert d["data"].get("field_group") in ("direct", "indirect")


def test_l1_field_children_no_propagation_copies(multi_workflow_ws):
    """V3.2.6 field propagation is deleted (J12-10 stage 4): a zero-field
    table is no longer filled with copied upstream fields. daily_summary
    renders exactly its 7 real fields — no customer_id/name/segment
    copies from the stg_customers pipeline."""
    l1 = _l1(multi_workflow_ws, indexed=False)
    daily = _field_children(l1, "daily_summary")
    assert daily == {"cnt", "dt", "region", "report_date", "total",
                     "total_amount", "total_orders"}
    assert "customer_id" not in daily
    assert "name" not in daily
    assert "order_id" not in daily
    assert "email" not in daily
    # every rendered field child is one (table, field) pair of the model
    rendered = {(n["data"].get("table_name"), n["data"].get("field_name"))
                for n in l1["nodes"]
                if n["data"].get("type") == "field"}
    assert len(rendered) == 29, \
        f"expected 29 (table, field) children, got {len(rendered)}"
    assert all(t in ("stg_orders", "stg_customers", "raw_orders",
                     "crm_customers", "daily_summary", "analytics_orders")
               for t, _ in rendered), "no field child outside the real tables"


# ══════════════════════════════════════════════════════════════════════
# Aliases: model alias_views truth (no label heuristics)
# ══════════════════════════════════════════════════════════════════════

def test_l1_alias_resolution_from_model_views(multi_workflow_ws):
    """Aliases come from PhysicalTable.alias_views — the model's
    extraction-time truth (I4 alias_of). step3's so/sc resolve to
    stg_orders/stg_customers, and L1 emits the canonical table names
    (the pairs carry stg_customers.customer_id, never sc.customer_id)."""
    from app.extractor.physical_model import build_physical_model
    from app.extractor.adapter import run_full_analysis

    step3 = WORKFLOW_DIR / "step3_join_orders_customers.sql"
    m = build_physical_model(run_full_analysis(step3.read_text(),
                                               step3.name),
                             script_name=step3.name)
    views = {av["label"]: m.tables[av["canonical_key"]].name
             for tbl in m.tables.values() for av in tbl.alias_views}
    assert views.get("so") == "stg_orders"
    assert views.get("sc") == "stg_customers"

    l1 = _l1(multi_workflow_ws, indexed=False)
    pairs = {tuple(p) for p in l1.get("lineage_field_pairs", [])}
    assert ("stg_customers", "customer_id") in pairs
    assert not any(p[0].startswith("sc.") or p[0] == "sc" for p in pairs), \
        "alias labels must never leak into pairs"


# ══════════════════════════════════════════════════════════════════════
# Reconstruction machinery deleted
# ══════════════════════════════════════════════════════════════════════

def test_l1_absorb_p4_deleted():
    """The raw-node-scan reconstruction (_absorb_p4 + graph-cache P4
    absorption) is deleted — L1 reads the model, not node dicts."""
    assert not hasattr(l1_builder, "_absorb_p4")
    assert not hasattr(l1_builder, "_absorb_p4_table_fields")


# ══════════════════════════════════════════════════════════════════════
# Flagship single-script workspace (R24 inline path)
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def loan_info_ws():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(LOAN_INFO_NAME, LOAN_INFO_SCRIPT.read_text())
    ws_id = create_workspace(buf.getvalue())
    yield ws_id
    delete_workspace(ws_id)


def test_l1_single_script_flagship_model_backed(loan_info_ws):
    """The single-script (R24) path builds its model from the inline
    extraction and must be fully functional: script node + tables +
    edges + the bdm_acc_loan_info.lending_ref pair, model-backed field
    children on the searched table."""
    l1 = _build_l1_graph(loan_info_ws, [LOAN_INFO_NAME],
                         "bdm_acc_loan_info", "lending_ref")
    assert l1.get("degraded") is False
    assert {tuple(p) for p in l1.get("lineage_field_pairs", [])} == \
        {("bdm_acc_loan_info", "lending_ref")}
    assert any(n["data"].get("type") == "script_node"
               for n in l1["nodes"]), "script node must exist (clickable L2)"
    assert any(n["data"].get("type") == "output_table"
               for n in l1["nodes"]), "output table node must exist"
    assert _field_group(l1, "bdm_acc_loan_info", "lending_ref") == "direct"
