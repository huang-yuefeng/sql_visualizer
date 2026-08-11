"""J12-10 stage 4 — model-driven L2 display + J12-15 per-statement DML trunk.

Stage 4 pins (Team S4, 2026-08-11):

* J12-15 (per-statement DML trunk): every statement's write/read legs
  route through that statement's OWN ⟐ output VT — the flagship filtered
  view's rrcdm write leg hangs off output@211 (l2_tbl_236587aa4c), never
  output@L160 (l2_tbl_7b217fb63a), and the rrcdm value edge targets
  output@211.
* No keeper-merge remnants: `merged_original_ids` / `_build_id_map` are
  gone — the classification returns occ_to_id and nothing leaks.
* Model-driven alias rendering: aliasness is the model's alias truth
  (alias_by_var_id) — p2@40/p2@116 (derived-subquery aliases) render as
  intermediate `p2`, p2@199 (JOIN alias) stays an alias compound; the
  display labels (p1@29, …) stay stable.
* graph_service payload keys: alias_map (alias label → canonical name)
  and table_fields (per-entity field sets + alias-label keys) are
  model projections with the same keys as before.
"""

import io
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(BACKEND_DIR))

from app.services.workspace_service import create_workspace, delete_workspace
from app.services.l2_builder import _build_l2_graph, _classify_compound_nodes
from app.services.graph_service import build_graph_data

FLAGSHIP = "BDM_ACC_LOAN_INFO_SUP_M.sql"
FLAGSHIP_PATH = BACKEND_DIR.parent / "samples" / "sql_sample_v1" / FLAGSHIP

# The two ⟐ output VTs of the flagship (probe-verified 2026-08-11):
# output@TOP0 (statement 0: INSERT INTO bdm_acc_loan_info_sup at L160)
# and output@TOP1 (statement 1: INSERT INTO rrcdm_job_log_exec_par at
# L211). Compound ids are md5(raw var id)[:10].
OUTPUT_TOP0 = "l2_tbl_7b217fb63a"
OUTPUT_TOP1 = "l2_tbl_236587aa4c"


@pytest.fixture
def flagship_ws():
    sql = FLAGSHIP_PATH.read_text()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(FLAGSHIP, sql)
    ws_id = create_workspace(buf.getvalue())
    yield ws_id
    delete_workspace(ws_id)


def _nodes_by(graph):
    return {n["data"]["id"]: n["data"] for n in graph["nodes"]}


def test_j1215_per_statement_trunk_flagship(flagship_ws):
    """J12-15: the filtered view's write leg output→rrcdm hangs off the
    statement-1 output (output@211), and the rrcdm value edge targets it —
    output@L160 keeps statement-0 edges only (sup)."""
    res = _build_l2_graph(flagship_ws, FLAGSHIP, FLAGSHIP_PATH.read_text(),
                          "bdm_acc_loan_info", "data_dt", True)
    rrcdm = next(n["data"]["id"] for n in res["nodes"]
                 if n["data"].get("table_name") == "rrcdm_job_log_exec_par")
    dml_out = [e for e in res["edges"]
               if e["data"]["id"].endswith("_dml_out")
               and e["data"]["target"] == rrcdm]
    assert len(dml_out) == 1, f"expected 1 rrcdm write leg, got {len(dml_out)}"
    ed = dml_out[0]["data"]
    assert ed["source"] == OUTPUT_TOP1, \
        f"rrcdm write leg must hang off output@211 ({OUTPUT_TOP1}), got {ed['source']}"
    assert ed["highlight_line"] == 211
    # the value edge (data_dt@213) feeds the owning statement's output —
    # it targets output@211, never output@L160
    value = [e["data"] for e in res["edges"]
             if e["data"]["id"].endswith("_value")
             and e["data"]["target"] == OUTPUT_TOP1]
    assert value, "statement-1 must have a value edge into output@211"
    # output@L160 keeps ONLY statement-0's own write legs (hl=160) — the
    # statement-1 value edge (data_dt@213) must NOT be rerouted there
    top0_values = [e["data"] for e in res["edges"]
                   if e["data"]["id"].endswith("_value")
                   and e["data"]["target"] == OUTPUT_TOP0]
    assert top0_values and all(e["highlight_line"] == 160
                               for e in top0_values), \
        f"output@L160 must keep only statement-0's own value edge(s), " \
        f"got {top0_values}"
    # output@L160 must NOT carry any rrcdm leg
    wrong = [e["data"] for e in res["edges"]
             if e["data"]["source"] == OUTPUT_TOP0
             and e["data"]["target"] == rrcdm]
    assert not wrong, f"output@L160 must lose the rrcdm leg, got {wrong}"
    # statement-0's own write leg (output@L160 → sup) stays
    sup = next(n["data"]["id"] for n in res["nodes"]
               if n["data"].get("table_name") == "bdm_acc_loan_info_sup")
    sup_leg = [e["data"] for e in res["edges"]
               if e["data"]["id"].endswith("_dml_out")
               and e["data"]["target"] == sup]
    assert sup_leg and sup_leg[0]["source"] == OUTPUT_TOP0, \
        f"sup write leg must hang off output@L160, got {sup_leg}"


def test_j1215_truthful_reason_strings(flagship_ws):
    """J12-15: the write leg's R20 continuation starts at the statement's
    own output — the reason path mentions output@211 (⟐output@211), not
    output@L160."""
    res = _build_l2_graph(flagship_ws, FLAGSHIP, FLAGSHIP_PATH.read_text(),
                          "bdm_acc_loan_info", "data_dt", True)
    rrcdm = next(n["data"]["id"] for n in res["nodes"]
                 if n["data"].get("table_name") == "rrcdm_job_log_exec_par")
    leg = next(e["data"] for e in res["edges"]
               if e["data"]["id"].endswith("_dml_out")
               and e["data"]["target"] == rrcdm)
    reason = leg.get("reason", "")
    assert leg.get("flow_kind") == "write", leg.get("flow_kind")
    # the write leg's carried target is the rrcdm write line (211)
    assert "211" in reason, f"reason must anchor the write line: {reason}"


def test_no_keeper_merge_remnants(flagship_ws):
    """Stage 4: no merged_original_ids anywhere in the classification or
    the served output; _build_id_map is gone (occ_to_id replaces it)."""
    import app.services.l2_builder as l2b
    assert not hasattr(l2b, "_build_id_map"), "_build_id_map must be deleted"
    sql = FLAGSHIP_PATH.read_text()
    full_graph, _, physical_model = l2b._load_or_build_graph(flagship_ws, FLAGSHIP, sql)
    nodes = full_graph.get("nodes", [])
    target_ids, direct_ids = l2b._compute_target_and_direct_ids(
        nodes, full_graph.get("edges", []), "bdm_acc_loan_info", "data_dt",
        physical_model=physical_model)
    table_nodes, field_nodes, _alias_map, occ_to_id = _classify_compound_nodes(
        nodes, full_graph, FLAGSHIP, target_ids, direct_ids, None,
        physical_model)
    for tn in table_nodes.values():
        assert "merged_original_ids" not in tn
    for fn in field_nodes:
        assert "merged_original_ids" not in fn
    # every compound maps through occ_to_id
    for tn in table_nodes.values():
        assert occ_to_id[tn["original_id"]] == tn["id"]
    for fn in field_nodes:
        assert occ_to_id[fn["original_id"]] == fn["id"]
    res = _build_l2_graph(flagship_ws, FLAGSHIP, sql,
                          "bdm_acc_loan_info", "data_dt", False)
    for n in res["nodes"]:
        assert "merged_original_ids" not in n["data"]
        assert "occ_to_id" not in n["data"]


def test_model_driven_alias_rendering(flagship_ws):
    """Stage 4: aliasness is the model's alias truth — p2@40/p2@116
    (derived-subquery aliases) render as intermediate `p2`, p2@199 (JOIN
    alias of bdm_acc_loan_info_sup) stays an alias compound; p1@29-style
    display labels stay stable."""
    res = _build_l2_graph(flagship_ws, FLAGSHIP, FLAGSHIP_PATH.read_text(),
                          "bdm_acc_loan_info", "data_dt", False)
    nodes = _nodes_by(res)
    alias_labels = sorted({n["label"] for n in nodes.values()
                           if n.get("type") == "alias_table"})
    # exactly the model's alias view labels — the derived-subquery aliases
    # are gone, the JOIN alias and the canonical-scope aliases remain
    assert "p2@40" not in alias_labels, alias_labels
    assert "p2@116" not in alias_labels, alias_labels
    assert "p2@199" in alias_labels, alias_labels
    assert "p1@29" in alias_labels, alias_labels
    assert "p1@84" in alias_labels, alias_labels
    # the derived-subquery aliases are now intermediate `p2` compounds
    p2_inters = [n for n in nodes.values()
                 if n.get("type") == "intermediate_table"
                 and n.get("table_name") == "p2"]
    assert p2_inters, "p2 derived-subquery aliases must render as intermediate p2"
    # display labels keep the @line form for real aliases
    assert all("@" in lbl for lbl in alias_labels), alias_labels


def test_graph_service_model_projection(flagship_ws):
    """Stage 4: build_graph_data's alias_map / table_fields are model
    projections with the same payload keys (alias label → canonical name;
    per-entity field sets + alias-label keys carrying the canonical
    fields)."""
    from app.extractor.adapter import run_full_analysis
    analysis = run_full_analysis(FLAGSHIP_PATH.read_text(), FLAGSHIP)
    gdata = build_graph_data(analysis)
    alias_map = gdata.get("alias_map", {})
    assert alias_map.get("p2") == "bdm_acc_loan_info_sup", \
        f"p2 (JOIN alias of sup) must resolve to the sup entity, got {alias_map.get('p2')}"
    # p1 aliases bdm_acc_loan_info (L29/L84) AND loan_final (L198 — the
    # final statement's FROM loan_final p1): the model projection is
    # last-writer-wins, so the last alias view's canonical wins.
    assert alias_map.get("p1") == "loan_final", \
        f"p1's last alias view (FROM loan_final p1 @198) must win, " \
        f"got {alias_map.get('p1')}"
    tf = gdata.get("table_fields", {})
    # canonical entity keys carry their field sets
    assert "bdm_acc_loan_info" in tf, list(tf)
    assert "data_dt" in tf.get("bdm_acc_loan_info", []), \
        tf.get("bdm_acc_loan_info")
    # DML INSERT columns land on the target entity's fields (P4-ext)
    assert "STATUS" in tf.get("rrcdm_job_log_exec_par", []), \
        tf.get("rrcdm_job_log_exec_par")
    # alias-label keys carry the union over ALL alias views of that label
    # (p1 has three views: bdm_acc_loan_info x2 + loan_final)
    assert "p1" in tf, "alias-label table_fields key must exist"
    assert set(tf.get("p1", [])) == set(tf["bdm_acc_loan_info"]) | set(
        tf["loan_final"]), \
        "alias-label fields must be the union of all alias views' " \
        "canonical fields"
