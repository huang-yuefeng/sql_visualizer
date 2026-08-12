"""D2 (CODE_REVIEW_2026-08-06, Team L) — field-aware DML admit.

The forward DML admit in compute_field_flow was field-blind: a
statement's DML target joined every closure whose chain contained the
statement's FROM-alias identity, even when the statement's write
carried none of the searched fields. Measured on
BDM_ACC_LOAN_INFO_SUP_M.sql: seeds (bdm_acc_loan_info_sup,
charge_department) and (sup, lending_ref) pulled the
rrcdm_job_log_exec_par@211 node into the served L2 closure, but stmt 211
(`INSERT INTO rrcdm_job_log_exec_par(data_dt, object_domain, ...,
remarks)`) writes none of those fields. The same leak also ran through
the Phase-1c-extra TABLE_FLOW twin (sup@223 -> rrcdm@211, op='INSERT' —
the table-level write leg) under the W6 identity-in-chain rule.

Fix (2026-08-12): the DML admit is gated on the statement's write leg —
the sources of the non-WRITE_READ DML edges into the target carry the
written column names (Phase-1c select-list columns and Phase-8 bridge
rule (b) write-leg vars; PARTITION columns arrive in the SQL's own
casing → matched case-insensitively). The write→read link (WRITE_READ)
admits only when the reader statement references the searched field.
TABLE_FLOW edges whose operation is a DML keyword (the table-level write
legs) use the same write-leg rule.

Jaccard constraint: rrcdm@211 must STAY in the (sup, data_dt) closure
(canonical rows 16/17 — stmt 211 writes data_dt) and must LEAVE the
(sup, charge_department) / (sup, lending_ref) closures.
"""

import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.adapter import run_full_analysis
from app.extractor.lineage import compute_field_flow
from app.extractor.physical_model import build_physical_model
from app.services.graph_service import build_graph_data
from app.services.l2_builder import _build_l2_graph

SQL_NAME = "BDM_ACC_LOAN_INFO_SUP_M.sql"
SAMPLE = (REPO_ROOT / "samples" / "sql_sample_v1" / SQL_NAME)

# ── helpers ──────────────────────────────────────────────────────────


def _rrcdm_in_walker(graph_data, pm, field):
    cl = compute_field_flow(graph_data, "bdm_acc_loan_info_sup", field,
                            physical_model=pm)
    occ = pm.occurrence
    return [nid for nid in cl
            if (occ(nid) or {}).get("name") == "rrcdm_job_log_exec_par"]


def _rrcdm_in_served(field):
    ws = f"d2-{field}-{uuid.uuid4().hex[:8]}"
    l2 = _build_l2_graph(ws, SQL_NAME, SAMPLE.read_text(encoding="utf-8"),
                         "bdm_acc_loan_info_sup", field)
    return [n.get("data", n).get("label") for n in l2["nodes"]
            if "rrcdm" in (n.get("data", n).get("label") or "")]


def _closure(graph_data, pm, table, field):
    return compute_field_flow(graph_data, table, field, physical_model=pm)


# ── real sample (the review's measured evidence) ─────────────────────

def _sample_flow():
    sql = SAMPLE.read_text(encoding="utf-8")
    analysis = run_full_analysis(sql, script_name=SQL_NAME)
    graph = build_graph_data(analysis)
    pm = build_physical_model(analysis)
    return graph, pm


def test_real_sample_phantom_rrcdm_excluded_from_served_l2():
    """Seeds whose field stmt 211 does NOT write must not render the
    rrcdm table node (the review's probe: served L2 6/6/7 pre-fix →
    5/5/7 post-fix)."""
    for field in ("charge_department", "lending_ref"):
        served = _rrcdm_in_served(field)
        assert not served, \
            f"(sup, {field}) served L2 still renders rrcdm: {served}"


def test_real_sample_rrcdm_kept_for_written_field():
    """data_dt IS written by stmt 211 (canonical rows 16/17) — rrcdm
    must stay in the served L2 and in the walker closure."""
    served = _rrcdm_in_served("data_dt")
    assert served, "(sup, data_dt) served L2 lost the rrcdm node"


def test_real_sample_walker_closures():
    graph, pm = _sample_flow()
    assert not _rrcdm_in_walker(graph, pm, "charge_department"), \
        "(sup, charge_department) walker closure still admits rrcdm"
    assert not _rrcdm_in_walker(graph, pm, "lending_ref"), \
        "(sup, lending_ref) walker closure still admits rrcdm"
    assert _rrcdm_in_walker(graph, pm, "data_dt"), \
        "(sup, data_dt) walker closure lost rrcdm (canonical rows 16/17)"


# ── synthetic: DML write-leg gate ────────────────────────────────────

# stmt 0: INSERT INTO mid SELECT ... x ... FROM src          (writes x)
# stmt 1: INSERT INTO out(z) SELECT 1 FROM mid               (writes z,
#         reads mid — the write→read link; reader stmt refs only z)
_SYNTH_WRITE_LEG = {
    "nodes": [
        {"id": "s1", "label": "src", "variable_type": "table",
         "table_name": "src", "context": "TOP0", "source_tables": ["src"]},
        {"id": "x1", "label": "x", "variable_type": "column",
         "context": "TOP0", "source_tables": ["src"]},
        {"id": "mid", "label": "mid", "variable_type": "table",
         "table_name": "mid", "context": "TOP0", "source_tables": ["mid"]},
        {"id": "y1", "label": "y", "variable_type": "column",
         "context": "TOP0", "source_tables": ["mid"]},
        {"id": "out", "label": "out", "variable_type": "table",
         "table_name": "out", "context": "TOP1", "source_tables": ["out"]},
        {"id": "z1", "label": "z", "variable_type": "column",
         "context": "TOP1", "source_tables": ["out"]},
    ],
    "edges": [
        {"source": "x1", "target": "s1", "edge_type": "REF"},
        {"source": "y1", "target": "mid", "edge_type": "REF"},
        {"source": "z1", "target": "out", "edge_type": "REF"},
        {"source": "x1", "target": "mid", "edge_type": "DML",
         "operation": "INSERT"},
        {"source": "y1", "target": "mid", "edge_type": "DML",
         "operation": "INSERT"},
        {"source": "z1", "target": "out", "edge_type": "DML",
         "operation": "INSERT"},
        {"source": "s1", "target": "mid", "edge_type": "TABLE_FLOW",
         "operation": "INSERT"},
        {"source": "s1", "target": "out", "edge_type": "TABLE_FLOW",
         "operation": "INSERT"},   # 1c-extra twin of the phantom path
        {"source": "mid", "target": "out", "edge_type": "DML",
         "operation": "WRITE_READ"},
    ],
}


def test_synthetic_dml_write_leg_gate():
    """DML fwd admits a target only when the target's write leg carries
    the searched field (mid writes x → in; out writes only z → out)."""
    g = _SYNTH_WRITE_LEG
    pm = build_physical_model(g)
    cl = _closure(g, pm, "src", "x")
    assert "mid" in cl, "target whose write leg carries the field must admit"
    assert "out" not in cl, \
        "target whose write leg lacks the field must NOT admit (DML fwd)"
    assert "z1" not in cl, "unadmitted target's write-leg field must not enter"


def test_synthetic_table_flow_write_leg_twin():
    """The Phase-1c-extra TABLE_FLOW twin (op = the DML keyword, the
    table-level write leg) uses the same write-leg rule — the leak path
    measured on the real sample (sup@223 -> rrcdm@211, op='INSERT')."""
    g = dict(_SYNTH_WRITE_LEG)
    # strip the DML edges so the TABLE_FLOW twin is the only write-leg
    # route into 'out'
    g = {
        "nodes": _SYNTH_WRITE_LEG["nodes"],
        "edges": [e for e in _SYNTH_WRITE_LEG["edges"]
                  if not (e.get("edge_type") == "DML"
                          and e.get("target") == "out")],
    }
    pm = build_physical_model(g)
    cl = _closure(g, pm, "src", "x")
    assert "mid" in cl
    assert "out" not in cl, \
        "TABLE_FLOW write leg must not admit a target whose write leg " \
        "lacks the searched field"
    cl_dt = _closure(g, pm, "mid", "y")
    assert "out" not in cl_dt  # out's write leg = {z}; y not written


def test_synthetic_write_leg_keeps_written_target():
    """The gate must not starve legit targets: an INSERT that writes the
    searched field keeps its DML and TABLE_FLOW admits."""
    g = {
        "nodes": [
            {"id": "s1", "label": "src", "variable_type": "table",
             "table_name": "src", "context": "TOP0",
             "source_tables": ["src"]},
            {"id": "x1", "label": "x", "variable_type": "column",
             "context": "TOP0", "source_tables": ["src"]},
            {"id": "out", "label": "out", "variable_type": "table",
             "table_name": "out", "context": "TOP1",
             "source_tables": ["out"]},
            {"id": "xw", "label": "x", "variable_type": "column",
             "context": "TOP1", "source_tables": ["out"]},
        ],
        "edges": [
            {"source": "x1", "target": "s1", "edge_type": "REF"},
            {"source": "xw", "target": "out", "edge_type": "REF"},
            {"source": "x1", "target": "out", "edge_type": "DML",
             "operation": "INSERT"},
            {"source": "s1", "target": "out", "edge_type": "TABLE_FLOW",
             "operation": "INSERT"},
        ],
    }
    pm = build_physical_model(g)
    cl = _closure(g, pm, "src", "x")
    assert "out" in cl, \
        "INSERT that writes the searched field must admit its target"


# ── synthetic: WRITE_READ reader-statement gate ──────────────────────

_WR_READ_BASE = {
    "nodes": [
        {"id": "w1", "label": "writer", "variable_type": "table",
         "table_name": "writer", "context": "TOP0",
         "source_tables": ["writer"]},
        {"id": "x1", "label": "x", "variable_type": "column",
         "context": "TOP0", "source_tables": ["writer"]},
        {"id": "r1", "label": "reader", "variable_type": "table",
         "table_name": "reader", "context": "TOP1",
         "source_tables": ["reader"]},
    ],
    "edges": [
        {"source": "x1", "target": "w1", "edge_type": "REF"},
        {"source": "x1", "target": "w1", "edge_type": "DML",
         "operation": "INSERT"},
        {"source": "w1", "target": "r1", "edge_type": "DML",
         "operation": "WRITE_READ"},
    ],
}


def test_synthetic_write_read_reader_references_field():
    """The write→read link admits only when the reader statement
    references the searched field."""
    g = {
        "nodes": _WR_READ_BASE["nodes"] + [
            {"id": "xr", "label": "x", "variable_type": "column",
             "context": "TOP1", "source_tables": ["reader"]},
        ],
        "edges": _WR_READ_BASE["edges"] + [
            {"source": "xr", "target": "r1", "edge_type": "REF"},
        ],
    }
    pm = build_physical_model(g)
    cl = _closure(g, pm, "writer", "x")
    assert "r1" in cl, \
        "reader statement referencing the field must join the closure"


def test_synthetic_write_read_reader_not_referencing_rejected():
    """The write→read link must NOT admit a reader statement that never
    references the searched field."""
    g = {
        "nodes": _WR_READ_BASE["nodes"] + [
            {"id": "e1", "label": "e", "variable_type": "column",
             "context": "TOP1", "source_tables": ["reader"]},
        ],
        "edges": _WR_READ_BASE["edges"] + [
            {"source": "e1", "target": "r1", "edge_type": "REF"},
        ],
    }
    pm = build_physical_model(g)
    cl = _closure(g, pm, "writer", "x")
    assert "r1" not in cl, \
        "reader statement not referencing the field must NOT admit"
