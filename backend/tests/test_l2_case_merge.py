"""#288 (T1) case-insensitive physical-table merge + #289 (T2) INSERT
write-alias columns land on the write target.

Team C (2026-08-24), backend only:

* T1 (#288): a physical table referenced with different cases
  (east5_stzfxxb vs EAST5_STZFXXB) must render as ONE compound node —
  the physical-table merge key is case-folded (one keeper, merged-away
  nids re-point through occ_to_id). Aliases/subqueries/CTEs STAY
  case-sensitive: a genuinely distinct case-twin alias (A vs a) is still
  a DIFFERENT alias node.
* T2 (#289): INSERT SELECT-projection columns the extractor sourced to a
  phantom alias (no real model owner) render ON the write target table
  node. The physical model is the independent truth: a projection sourced
  to a real table/CTE/alias renders on that source (its model owner), NOT
  on the write target — the write-target routing is a fallback for
  columns with no visible source parent. DML ⟐-output routing is
  untouched (no qo_ nodes, write legs still hang off each statement's own
  output VT).
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

EAST5 = "EAST5_STZFXXB_M.sql"
EAST5_PATH = BACKEND_DIR.parent / "samples" / "sql_sample_v1" / EAST5
# The east5_stzfxxb keeper compound id (md5 of the first table occurrence's
# var id) — probe-verified; the case-split twin EAST5_STZFXXB currently
# renders as l2_tbl_36f606a08d.
EAST5_KEEPER = "l2_tbl_cc4dd6d92c"


@pytest.fixture
def east5_ws():
    sql = EAST5_PATH.read_text()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(EAST5, sql)
    ws_id = create_workspace(buf.getvalue())
    yield ws_id
    delete_workspace(ws_id)


def _make_ws(script_name, sql):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(script_name, sql)
    ws_id = create_workspace(buf.getvalue())
    return ws_id


@pytest.fixture
def twin_ws():
    """A physical table with a case-twin occurrence and two case-twin
    aliases (A / a) — the aliases must NOT fold."""
    sql = "SELECT A.c1 FROM tab_a AS A;\nSELECT a.c2 FROM TAB_A AS a;"
    ws_id = _make_ws("case_twin.sql", sql)
    yield ws_id
    delete_workspace(ws_id)


def _nodes_by(graph):
    return {n["data"]["id"]: n["data"] for n in graph["nodes"]}


def _kids(nodes, parent_id):
    return {n["label"] for n in nodes.values() if n.get("parent") == parent_id}


# ── T1 (#288): physical tables merge case-insensitively ──────────────

def test_t1_case_insensitive_physical_merge(east5_ws):
    """#288: east5_stzfxxb and EAST5_STZFXXB render as ONE compound node
    (the case-split twin merges into the keeper)."""
    res = _build_l2_graph(east5_ws, EAST5, EAST5_PATH.read_text(),
                          "", "", False)
    nodes = _nodes_by(res)
    east5 = [n for n in nodes.values()
             if n.get("table_name", "").lower() == "east5_stzfxxb"]
    assert len(east5) == 1, \
        f"east5_stzfxxb must render as ONE node, got {len(east5)}: " \
        f"{[(n['id'], n.get('table_name')) for n in east5]}"
    keep = east5[0]
    assert keep["id"] == EAST5_KEEPER
    assert keep["type"] == "source_table", keep["type"]
    # the merged node carries the uppercase occurrence's read field (p_dt)
    assert "p_dt" in _kids(nodes, keep["id"]), \
        "the merged east5 node must carry p_dt (the EAST5_STZFXXB read)"


def test_t1_alias_case_twin_not_folded(twin_ws):
    """#288 guard: a case-twin ALIAS is a DIFFERENT alias — the physical
    table folds, the aliases A and a stay two distinct alias nodes."""
    res = _build_l2_graph(twin_ws, "case_twin.sql",
                          "SELECT A.c1 FROM tab_a AS A;\n"
                          "SELECT a.c2 FROM TAB_A AS a;",
                          "", "", False)
    nodes = _nodes_by(res)
    physical = [n for n in nodes.values()
                if n.get("type") == "source_table"
                and n.get("table_name", "").lower() == "tab_a"]
    assert len(physical) == 1, \
        f"tab_a/TAB_A must fold into ONE physical node, got {len(physical)}: " \
        f"{[(n['id'], n.get('table_name')) for n in physical]}"
    aliases = [n for n in nodes.values() if n.get("type") == "alias_table"]
    assert len(aliases) == 2, \
        f"case-twin aliases must NOT fold, got {len(aliases)}: " \
        f"{[n.get('label') for n in aliases]}"
    labels = {n.get("label") for n in aliases}
    assert "A@1" in labels and "a@2" in labels, labels


# ── T2 (#289): INSERT write columns land on the write target ──────────

def test_t2_insert_write_columns_on_target(east5_ws):
    """#289: the phantom-sourced INSERT SELECT projections render ON the
    east5 target; columns the extractor sourced to a real table render on
    their model owner (bdm_acc_loan_info), not on east5."""
    res = _build_l2_graph(east5_ws, EAST5, EAST5_PATH.read_text(),
                          "", "", False)
    nodes = _nodes_by(res)
    kids = _kids(nodes, EAST5_KEEPER)
    bdm_id = next(n["id"] for n in nodes.values()
                  if n.get("table_name") == "bdm_acc_loan_info")
    bdm_kids = _kids(nodes, bdm_id)
    for wc in ("dis_bank_id", "bz", "TAG_COUNTRY", "TAG_ENTITY",
               "TAG_BRANCH", "TAG_GBGF", "TAG_RESERVE",
               "TAG_PRIMARY_ACCOUNTABLE_PARTY", "TAG_RESPONSIBLE_PARTY",
               "CHARGE_DEPARTMENT", "COM_RESERVED_1",
               "RESERVED_2", "RESERVED_4", "RESERVED_6",
               "PRIMARY_SRC_SYSTEM"):
        assert wc in kids, \
            f"write column {wc} must land on the east5 target node"
    # model-aligned: the model attributes nbjgh/xdhth/xdjjh/dkje to
    # bdm_acc_loan_info (not east5) — the display must follow the model.
    for wc in ("nbjgh", "xdhth", "xdjjh", "dkje"):
        assert wc not in kids, \
            f"{wc} is sourced to bdm_acc_loan_info — must NOT land on east5"
        assert wc in bdm_kids, \
            f"{wc} must land on bdm_acc_loan_info (its model owner)"


def test_t2_write_target_parent_at_classification(east5_ws):
    """#289: the phantom-sourced write-column → write-target association is
    made in _classify_compound_nodes (parent == write-target keeper); a
    column with a real model owner (nbjgh → bdm_acc_loan_info) keeps that
    owner."""
    import app.services.l2_builder as l2b
    sql = EAST5_PATH.read_text()
    full_graph, _, pm = l2b._load_or_build_graph(east5_ws, EAST5, sql)
    nodes = full_graph.get("nodes", [])
    target_ids, direct_ids = l2b._compute_target_and_direct_ids(
        nodes, full_graph.get("edges", []), "", "", physical_model=pm)
    table_nodes, field_nodes, _alias_map, _occ = _classify_compound_nodes(
        nodes, full_graph, EAST5, target_ids, direct_ids, None, pm)
    for probe in ("dis_bank_id", "bz", "TAG_COUNTRY", "RESERVED_2"):
        got = [fn for fn in field_nodes
               if fn.get("label") == probe
               and fn.get("parent") == EAST5_KEEPER]
        assert got, \
            f"{probe} must be a field node parented to the east5 keeper"
    # model-aligned: nbjgh is attributed to bdm_acc_loan_info, not east5
    bdm_id = next(tn["id"] for tn in table_nodes.values()
                  if tn["table_name"] == "bdm_acc_loan_info")
    nbjgh = [fn for fn in field_nodes if fn.get("label") == "nbjgh"]
    assert nbjgh, "nbjgh not found as a field node"
    assert nbjgh[0].get("parent") == bdm_id, \
        f"nbjgh field parent must be bdm_acc_loan_info, " \
        f"got {nbjgh[0].get('parent')}"


def test_t2_dml_qo_routing_untouched(east5_ws):
    """#289: DML write legs still route through each statement's own ⟐
    output VT — no qo_ nodes, no synthetic edges."""
    res = _build_l2_graph(east5_ws, EAST5, EAST5_PATH.read_text(),
                          "", "", False)
    nodes = _nodes_by(res)
    assert not any(n["id"].startswith("qo_") for n in nodes.values()), \
        "no qo_ intermediate nodes may exist"
    east5_id = next(n["id"] for n in nodes.values()
                    if n.get("table_name") == "east5_stzfxxb")
    write_legs = [e["data"] for e in res["edges"]
                  if e["data"].get("id", "").endswith("_dml_out")
                  and e["data"].get("target") == east5_id]
    assert write_legs, "east5 must have a DML write leg"
    for ed in write_legs:
        src = nodes.get(ed["source"])
        assert src is not None and (src.get("table_name") or "").startswith("⟐ "), \
            f"write leg into east5 must route through a ⟐ output VT, got {ed}"
