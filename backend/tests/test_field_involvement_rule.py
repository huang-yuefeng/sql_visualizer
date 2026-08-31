"""Field-involvement admission rule (fix team J1, 2026-08-31).

USER RULING: "only edges where the searched field is involved in the data
flow are shown."

Two admission classes land in `l2_builder._apply_field_involvement` (the
served closure, after the payload phase — the walker's NODE closure is
untouched, so occurrence coverage can never regress):

  Class 1 — JOIN OWN-SITE. A JOIN carrier is served only when its anchor
    line IS a JOIN-ON line. A collapsed carrier's `defined_in` names the
    GROUP's clause while the line it carries was handed out in stream
    order (R45 Fix B / F-E1), so a projection/read line can inherit the
    group's join-key edge — the ledgered PROJECTION-TWIN-INHERITS-JOIN
    class (SUP_M lending_ref: the L82 CASE read and the L163 write
    projection; the LFS123 doctrine).

  Class 2 — SIBLING-FIELD VALUE LEGS. A value leg of a NON-searched field
    is that sibling's own flow, not the searched field's: its DML write
    value leg, its ⟐output-frame membership, its write-projection read
    leg, and the chain leg into the output frame that its write drives.
    The belongs-to/structural facts of a sibling chip and the whole
    table/VT skeleton stay (the accepted FSB/G9 classes).

The 6 over-included edges this rule removes on the cross-check corpus
(SUP_M × lending_ref, G9's ledger):
  l2e_c1f940d2eb0f      JOIN lending_ref@82   -> loan_final@64  @82   (C1)
  l2e_9a0b140bd2cc      JOIN lending_ref@163  -> output@160     @163  (C1)
  l2e_43563f4fce74      SCHEMA output@160     -> reserved_field8 @183 (C2)
  l2e_3e806f355c16_value TABLE_FLOW reserved_field8 -> output@160   @183 (C2)
  l2e_95a6f49b4f2e      REF reserved_field8@82 -> p1@198        @198  (C2)
  l2e_1eb5aca70da6      TABLE_FLOW p1@198      -> output@160    @198  (C2)
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.services.l2_builder as LB  # noqa: E402
from app.services.l2_builder import (  # noqa: E402
    _apply_field_involvement,
    _build_l2_graph,
)

SAMPLES = BACKEND_DIR.parent / "samples" / "sql_sample_v1"
FLAGSHIP = SAMPLES / "BDM_ACC_LOAN_INFO_SUP_M.sql"

# The L82 / L163 anchors of the two mis-anchored JOIN carriers, and the
# sibling write zone (L183 the write projection, L198 the alias instance
# the sibling's value is read through). Real join sites for contrast.
CASE_READ_LINE = 82
WRITE_PROJECTION_LINE = 163
SIBLING_WRITE_LINE = 183
SIBLING_READ_LINE = 198
REAL_JOIN_SITES = (41, 95, 117, 150, 156, 201)


def _build(table, field, disable_rule=False):
    """Served SUP_M × lending_ref closure; optionally with the admission
    rule disabled (the pre-rule engine) for before/after assertions."""
    sql = FLAGSHIP.read_text(encoding="utf-8")
    if disable_rule:
        real = LB._apply_field_involvement
        LB._apply_field_involvement = (
            lambda new_edges, field, relevance_filter, physical_model=None,
            sql_text="": new_edges)
        try:
            result = _build_l2_graph("j1", "BDM_ACC_LOAN_INFO_SUP_M.sql", sql,
                                     table, field, direction="downstream")
        finally:
            LB._apply_field_involvement = real
    else:
        result = _build_l2_graph("j1", "BDM_ACC_LOAN_INFO_SUP_M.sql", sql,
                                 table, field, direction="downstream")
    graph = result.get("graph") if isinstance(result.get("graph"), dict) else result
    nodes = {n["data"]["id"]: n["data"] for n in graph["nodes"]}
    edges = [e["data"] for e in graph["edges"]]
    return nodes, edges


def _label(nodes, edge, side):
    return nodes.get(edge[side], {}).get("label")


def _find(edges, etype, src_label, dst_label, line):
    return [e for e in edges
            if e.get("edge_type") == etype
            and e.get("highlight_line") == line
            and e.get("_src_label", e.get("id", "")).rsplit(".", 1)[-1] == src_label
            or False]


def _edges_of(edges, etype, line):
    return [e for e in edges
            if e.get("edge_type") == etype and e.get("highlight_line") == line]


def _by_id(edges, prefix):
    return [e for e in edges if (e.get("id") or "").startswith(prefix)]


# ═══════════════════════════════════════════════════════════════════════
# Class 1 — a JOIN carrier may not anchor at a projection/read line
# ═══════════════════════════════════════════════════════════════════════

def test_projection_line_join_carriers_are_dropped():
    """L82 (`CASE WHEN NVL(p6.lending_ref,'') …`) and L163
    (`,p1.lending_ref`) are projection/read lines for lending_ref — no
    join happens there — so the group's join-key edge is no longer served
    under those anchors."""
    nodes, edges = _build("bdm_acc_loan_info", "lending_ref")
    for line in (CASE_READ_LINE, WRITE_PROJECTION_LINE):
        joins = _edges_of(edges, "JOIN", line)
        assert not joins, (
            f"JOIN carrier(s) still anchored at the projection/read line "
            f"L{line}: {[(e['id'], _label(nodes, e, 'source'), _label(nodes, e, 'target')) for e in joins]}")
    # and the pre-rule engine did serve them (the assertion means something)
    nodes0, edges0 = _build("bdm_acc_loan_info", "lending_ref", disable_rule=True)
    assert any(e.get("highlight_line") == CASE_READ_LINE
               for e in _edges_of(edges0, "JOIN", CASE_READ_LINE))
    assert any(e.get("highlight_line") == WRITE_PROJECTION_LINE
               for e in _edges_of(edges0, "JOIN", WRITE_PROJECTION_LINE))


def test_real_join_sites_stay_served():
    """The searched field's own join admissions at genuine ON lines stay:
    L156 (`ON p6.lending_ref = p1.lending_ref`) serves BOTH occurrence
    identities (LFS117 p6-side + LFS138 p1-side), and the other cross-check
    join sites (41/95/117/150/201) stay dark-line-free."""
    nodes, edges = _build("bdm_acc_loan_info", "lending_ref")
    joins_156 = _edges_of(edges, "JOIN", 156)
    assert len(joins_156) == 2, (
        f"the L156 join site must keep both occurrence identities, got "
        f"{[(e['id'], _label(nodes, e, 'source')) for e in joins_156]}")
    anchors = {e["highlight_line"] for e in edges if e.get("edge_type") == "JOIN"}
    assert set(REAL_JOIN_SITES) <= anchors, (
        f"a real join site went dark: {sorted(REAL_JOIN_SITES - anchors)}")


# ═══════════════════════════════════════════════════════════════════════
# Class 2 — a sibling field's value legs are not this seed's flow
# ═══════════════════════════════════════════════════════════════════════

def test_sibling_value_legs_are_dropped():
    """reserved_field8 IS a closure member (computed FROM lending_ref at
    L82), but its own VALUE chain through the write is not this seed's
    flow — the searched field is on neither endpoint of any of the four:
    the ⟐output membership, the write value leg, the read leg, the chain
    into the output frame."""
    nodes, edges = _build("bdm_acc_loan_info", "lending_ref")

    membership = [e for e in _edges_of(edges, "SCHEMA", SIBLING_WRITE_LINE)
                  if _label(nodes, e, "source") == "output"
                  and _label(nodes, e, "target") == "reserved_field8"]
    assert not membership, f"⟐output membership of the sibling still served: {membership}"

    write_leg = [e for e in _edges_of(edges, "TABLE_FLOW", SIBLING_WRITE_LINE)
                 if _label(nodes, e, "source") == "reserved_field8"
                 and _label(nodes, e, "target") == "output"]
    assert not write_leg, f"sibling write value leg still served: {write_leg}"

    read_leg = [e for e in _edges_of(edges, "REF", SIBLING_READ_LINE)
                if _label(nodes, e, "source") == "reserved_field8"
                and _label(nodes, e, "target", ) == "p1@198"]
    assert not read_leg, f"sibling write-value read leg still served: {read_leg}"

    chain = [e for e in _edges_of(edges, "TABLE_FLOW", SIBLING_READ_LINE)
             if _label(nodes, e, "source") == "p1@198"
             and _label(nodes, e, "target") == "output"]
    assert not chain, f"sibling-driven chain into the output frame still served: {chain}"

    # the pre-rule engine served all four
    nodes0, edges0 = _build("bdm_acc_loan_info", "lending_ref", disable_rule=True)
    assert len(_by_id(edges0, "l2e_43563f4fce74")) == 1
    assert len(_by_id(edges0, "l2e_3e806f355c16_value")) == 1
    assert len(_by_id(edges0, "l2e_95a6f49b4f2e")) == 1
    assert len(_by_id(edges0, "l2e_1eb5aca70da6")) == 1


def test_sibling_belong_to_and_skeleton_stay():
    """The structural facts G9 pinned stay: the sibling chip's belongs-to
    SCHEMA edges (LFS135 @82 / LFS143-145 @183), the ALIAS identity hops,
    the CTE-consumption TABLE_FLOW, and the ⟐output membership of the
    SEARCHED field."""
    nodes, edges = _build("bdm_acc_loan_info", "lending_ref")
    by_line = {}
    for e in edges:
        by_line.setdefault((e.get("edge_type"), e.get("highlight_line")), []).append(e)

    # LFS135 — loan_final owns the sibling chip the L82 line defines
    own = [e for e in by_line.get(("SCHEMA", 82), [])
           if _label(nodes, e, "source") == "loan_final"
           and _label(nodes, e, "target") == "reserved_field8"]
    assert own, "the sibling chip's belongs-to SCHEMA @82 went dark (LFS135)"
    # LFS143/144/145 — one belongs-to per p1 instance for the L183 read
    own183 = [e for e in by_line.get(("SCHEMA", 183), [])
              if _label(nodes, e, "target") == "reserved_field8"]
    assert len(own183) == 3, f"expected 3 p1-instance belongs-to, got {len(own183)}"
    # ALIAS hops (identity) stay: rollover→p6@155 (LFS128), loan_final→p1@198 (LFS131)
    alias = [( _label(nodes, e, "source"), _label(nodes, e, "target"))
             for e in edges if e.get("edge_type") == "ALIAS"]
    assert ("rollover_loan_info", "p6@155") in alias
    assert ("loan_final", "p1@198") in alias
    # LFS137 — the CTE-consumption hop p6@155 -> loan_final stays
    assert any(_label(nodes, e, "source") == "p6@155"
               and _label(nodes, e, "target") == "loan_final"
               for e in edges if e.get("edge_type") == "TABLE_FLOW")


def test_own_field_everything_stays():
    """The searched field's own everything is untouched: its L82 COMPUTED
    into the sibling (LFS133), its value copy from the CTE projection
    (LFS129), its belongs-to twins, its read legs, its filters and its
    ⟐output membership."""
    nodes, edges = _build("bdm_acc_loan_info", "lending_ref")
    assert _edges_of(edges, "COMPUTED", 82), "LFS133 went dark"
    assert any(_label(nodes, e, "source") == "lending_ref"
               and _label(nodes, e, "target") == "lending_ref"
               and e.get("highlight_line") == 13
               for e in edges if e.get("edge_type") == "REF"), "LFS129 went dark"
    # LFS146 — the searched field's own read leg onto p1@198, same line the
    # sibling's read leg used to share
    own_read = [e for e in _edges_of(edges, "REF", SIBLING_READ_LINE)
                if _label(nodes, e, "source") == "lending_ref"]
    assert own_read, "the searched field's own read leg @198 went dark (LFS146)"
    # the searched field's own occurrence lines all stay highlighted
    hl = {e["highlight_line"] for e in edges}
    for line in (13, 19, 48, 59, 82, 95, 117, 150, 156, 163, 183, 198, 201):
        assert line in hl, f"the searched field's occurrence line L{line} went dark"


# ═══════════════════════════════════════════════════════════════════════
# the rule's contract: display-only, deterministic, no-change property
# ═══════════════════════════════════════════════════════════════════════

def test_rule_is_edge_only_nodes_never_change():
    """The closure's NODE set is the walker's — the admission filters EDGES
    only, so occurrence coverage cannot regress (R44)."""
    nodes_a, edges_a = _build("bdm_acc_loan_info", "lending_ref")
    nodes_b, edges_b = _build("bdm_acc_loan_info", "lending_ref", disable_rule=True)
    assert {n["id"] for n in nodes_a.values()} == {n["id"] for n in nodes_b.values()}
    assert {(n["label"], n.get("line_start")) for n in nodes_a.values()} == \
           {(n["label"], n.get("line_start")) for n in nodes_b.values()}
    # the served anchor set can only shrink
    assert {e["highlight_line"] for e in edges_a} <= {e["highlight_line"] for e in edges_b}


def test_simple_field_closure_change_is_surgical():
    """The no-change property on a simple closure: every edge except the
    one Class-1 defect is served identically. The fixture's single
    violation is the CTE's own projection line L2 (`SELECT p1.acct_no`)
    inheriting the group's join-key edge — the same projection-twin class
    the G8 fold note records — and the rule removes exactly that."""
    sql = """WITH loan_final AS (
    SELECT p1.acct_no
           ,p2.k1
    FROM bdm_main p1
    LEFT JOIN dim_a p2
        ON p1.acct_no = p2.k1
)
INSERT OVERWRITE TABLE bdm_out PARTITION(data_dt = '$(load_date)')
SELECT acct_no FROM loan_final;
"""
    real = LB._apply_field_involvement
    LB._apply_field_involvement = (
        lambda new_edges, field, relevance_filter, physical_model=None,
        sql_text="": new_edges)
    try:
        r0 = _build_l2_graph("j1simple", "j1_simple.sql", sql, "bdm_main", "acct_no")
    finally:
        LB._apply_field_involvement = real
    r1 = _build_l2_graph("j1simple", "j1_simple.sql", sql, "bdm_main", "acct_no")
    g0 = r0.get("graph") if isinstance(r0.get("graph"), dict) else r0
    g1 = r1.get("graph") if isinstance(r1.get("graph"), dict) else r1
    e0 = {e["data"]["id"]: e["data"] for e in g0["edges"]}
    e1 = {e["data"]["id"]: e["data"] for e in g1["edges"]}
    dropped = set(e0) - set(e1)
    assert set(e1) <= set(e0), f"the rule must never add an edge: {set(e1) - set(e0)}"
    assert len(dropped) == 1, f"expected exactly the mis-anchored JOIN, got {dropped}"
    dropped_edge = e0[dropped.pop()]
    assert dropped_edge["edge_type"] == "JOIN", dropped_edge
    assert dropped_edge["highlight_line"] == 2, (
        f"the removed JOIN must be the L2 projection carrier: {dropped_edge}")
    # the real join site (L6) and every other edge stay served
    assert any(e["highlight_line"] == 6 and e["edge_type"] == "JOIN"
               for e in e1.values())


def test_rule_is_deterministic():
    """The same build twice serves the same edge ids in the same order."""
    _, a = _build("bdm_acc_loan_info", "lending_ref")
    _, b = _build("bdm_acc_loan_info", "lending_ref")
    assert [e["id"] for e in a] == [e["id"] for e in b]


def test_full_view_is_never_filtered():
    """No search filter ⇒ the rule is a no-op: the full view keeps every
    edge (there is no searched field to be 'involved')."""
    sql = FLAGSHIP.read_text(encoding="utf-8")
    real = LB._apply_field_involvement
    seen = []

    def spy(new_edges, field, relevance_filter, physical_model=None, sql_text=""):
        seen.append(relevance_filter)
        return real(new_edges, field, relevance_filter,
                    physical_model=physical_model, sql_text=sql_text)

    LB._apply_field_involvement = spy
    try:
        _build_l2_graph("j1full", "BDM_ACC_LOAN_INFO_SUP_M.sql", sql,
                        "bdm_acc_loan_info", "lending_ref", relevance_filter=False)
    finally:
        LB._apply_field_involvement = real
    assert seen and not any(seen), "the rule must not run on the full view"


# ═══════════════════════════════════════════════════════════════════════
# the predicate in isolation (each class, on hand-carried extraction info)
# ═══════════════════════════════════════════════════════════════════════

class _StubModel:
    """Just the occurrence index the rule reads: (label, line) → kind."""

    def __init__(self, occ):
        self.occurrences = occ


def _model():
    return _StubModel({
        ("p1.reserved_field8", 183): {"name": "p1.reserved_field8",
                                      "line_start": 183, "variable_type": "column"},
        ("p2.lending_ref", 201): {"name": "p2.lending_ref", "line_start": 201,
                                  "variable_type": "column"},
        ("p6.lending_ref", 82): {"name": "p6.lending_ref", "line_start": 82,
                                 "variable_type": "column"},
        ("bdm_acc_loan_info_sup", 160): {"name": "bdm_acc_loan_info_sup",
                                         "line_start": 160,
                                         "variable_type": "table"},
        ("⟐ output", 160): {"name": "⟐ output", "line_start": 160,
                            "variable_type": "virtual_table"},
    })


def _carrier(et="REF", src="p1.other", tgt="p1", line=10, op="READ",
             defined_in="SELECT expr", value_edge=None, tgt_output=False,
             own_seg=0, hops=None, anchor=None):
    return {
        "id": "l2e_test", "source": "s", "target": "t", "edge_type": et,
        "highlight_line": anchor if anchor is not None else line,
        "_src_label": src, "_tgt_label": tgt, "_src_line": line, "_tgt_line": line,
        "_op": op, "_value_edge": value_edge, "_tgt_output": tgt_output,
        "_own_seg_idx": own_seg, "_path_hops": hops or [],
        "_src_defined_in": defined_in, "_tgt_defined_in": "",
    }


def test_predicate_class_decisions():
    MODEL = _model()
    admit = lambda e: _apply_field_involvement(
        [e], "lending_ref", True, physical_model=MODEL) == [e]
    drop = lambda e: _apply_field_involvement(
        [e], "lending_ref", True, physical_model=MODEL) == []

    # the seed chip / a same-name copy is always involved
    assert admit(_carrier(src="p1.lending_ref", op="READ", defined_in="JOIN ON"))
    # a sibling's ⟐output membership, write value leg, write-projection
    # read leg and output-frame chain are the SIBLING's flow
    assert drop(_carrier(et="SCHEMA", src="⟐ output", tgt="reserved_field8",
                         op="OUTPUT", line=183))
    assert admit(_carrier(et="SCHEMA", src="⟐ output", tgt="lending_ref",
                          op="OUTPUT", line=22)), "the seed's own membership"
    assert drop(_carrier(et="SCHEMA", src="⟐ output", tgt="reserved_field8",
                         op="TABLE_COLUMN", line=183)) is False, (
        "a belongs-to SCHEMA is structure, never a value leg")
    assert drop(_carrier(et="TABLE_FLOW", src="reserved_field8", tgt="⟐ output",
                         op="INSERT", value_edge=True, line=183))
    assert drop(_carrier(et="REF", src="p1.reserved_field8", tgt="p1", op="READ",
                         defined_in="SELECT expr", line=183))
    assert admit(_carrier(et="REF", src="p2.charge_department", tgt="p2",
                          op="READ", defined_in="JOIN ON", line=203)), (
        "a row-selection sibling's read leg is structure")
    assert drop(_carrier(et="TABLE_FLOW", src="p1", tgt="⟐ output", op="FROM",
                         line=198, tgt_output=True, own_seg=1,
                         hops=[("p1.reserved_field8", 183)]))
    assert admit(_carrier(et="TABLE_FLOW", src="p2", tgt="⟐ output", op="FROM",
                          line=199, tgt_output=True, own_seg=1,
                          hops=[("p2.lending_ref", 201)])), "the seed's own chain"
    # the chain test never fires off the output frame, nor on a
    # row-selection/identity type, nor when the hop is a table chip
    assert admit(_carrier(et="TABLE_FLOW", src="p6", tgt="loan_final", op="FROM",
                          line=155, tgt_output=False, own_seg=1,
                          hops=[("p6.lending_ref", 82)]))
    assert admit(_carrier(et="FILTER", src="rn", tgt="temp_kmbh_gl", op="CONDITION",
                          line=76, tgt_output=False, own_seg=1,
                          hops=[("p2.rn", 76)]))
    assert admit(_carrier(et="TABLE_FLOW", src="A", tgt="⟐ output", op="FROM",
                          line=223, tgt_output=True, own_seg=3,
                          hops=[("reserved_field8", 183), ("⟐ output", 160),
                                ("bdm_acc_loan_info_sup", 160)])), (
        "a table-chip hop is the skeleton's own leg, not a sibling value leg")


def test_predicate_noop_without_search():
    """No field / no filter ⇒ byte-identical passthrough."""
    e = _carrier(src="reserved_field8", op="OUTPUT", et="SCHEMA", line=183)
    assert _apply_field_involvement([e], "", True) == [e]
    assert _apply_field_involvement([e], "lending_ref", False) == [e]


def test_predicate_admits_when_the_model_is_silent():
    """Safety direction: without the occurrence index the hop carrier
    cannot be resolved to a FIELD, so the edge is ADMITTED — the rule
    never drops on missing extraction-time evidence."""
    e = _carrier(et="TABLE_FLOW", src="p1", tgt="⟐ output", op="FROM", line=198,
                 tgt_output=True, own_seg=1, hops=[("p1.reserved_field8", 183)])
    assert _apply_field_involvement([e], "lending_ref", True) == [e]
