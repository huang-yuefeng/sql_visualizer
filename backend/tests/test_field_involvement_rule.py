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

  Class 3 — SIBLING BELONGS-TO + ORPHAN SIBLING CHIPS (USER RULING
    2026-09-01, rule 3a reversed, full variant confirmed). The sibling
    chip's belongs-to SCHEMA edge — the old accepted "skeleton" — is NOT
    the searched field's flow either, and on write-heavy statements it
    drags every co-written column's chip into the closure as clutter.
    DROPPED. The sibling chips it leaves floating edge-less are pruned
    too (`_prune_orphan_sibling_chips`) — the user: "If the sibling
    chips, which is not [the] searched target field, and doesn't have
    any edge, they are not contributing to the data flow. I think they
    should be removed." A chip the searched field's own flow still feeds
    survives. The TABLE/VT skeleton (ALIAS hops, CTE chains) stays; the
    searched chip's own belongs-to / Reappears class is untouched; "this
    column exists on this box" becomes a full-view fact.

The 6 over-included edges this rule removes on the cross-check corpus
(SUP_M × lending_ref, G9's ledger):
  l2e_c1f940d2eb0f      JOIN lending_ref@82   -> loan_final@64  @82   (C1)
  l2e_9a0b140bd2cc      JOIN lending_ref@163  -> output@160     @163  (C1)
  l2e_43563f4fce74      SCHEMA output@160     -> reserved_field8 @183 (C2)
  l2e_c25f32314a53_value TABLE_FLOW reserved_field8 -> output@160   @183 (C2; id re-derived by the V8 walk-order fix, 2026-09-02)
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
    # the l2e id re-derived 2026-09-02: _combine_edges rehashes a colliding
    # raw base by its carrier order, which the V8 canonical walk order
    # changed — same edge (reserved_field8 → output, TABLE_FLOW @183, write)
    assert len(_by_id(edges0, "l2e_c25f32314a53_value")) == 1
    assert len(_by_id(edges0, "l2e_95a6f49b4f2e")) == 1
    assert len(_by_id(edges0, "l2e_1eb5aca70da6")) == 1


def test_sibling_belong_to_dropped_skeleton_stays():
    """USER RULING 2026-09-01 (rule 3a reversed): a sibling field's
    belongs-to SCHEMA edge is NOT the searched field's flow — it is
    dropped, and the sibling chip leaves the view with it (an edge-less
    sibling chip is exactly the clutter the ruling removes). The TABLE
    skeleton stays: ALIAS identity hops and the CTE-consumption
    TABLE_FLOW. The searched chip's own belongs-to / Reappears class is
    untouched (seed-endpoint edges never reach the filter)."""
    nodes, edges = _build("bdm_acc_loan_info", "lending_ref")

    # LFS135 — the sibling belongs-to @82 is GONE
    own = [e for e in edges
           if e.get("edge_type") == "SCHEMA"
           and e.get("highlight_line") == 82
           and _label(nodes, e, "target") == "reserved_field8"]
    assert not own, "the sibling chip's belongs-to SCHEMA @82 is still served"
    # LFS143/144/145 — the L183 belongs-to trio is GONE
    own183 = [e for e in edges
              if e.get("edge_type") == "SCHEMA"
              and e.get("highlight_line") == 183
              and _label(nodes, e, "target") == "reserved_field8"]
    assert not own183, "the sibling chip's belongs-to SCHEMA @183 is still served"
    # the sibling chip SURVIVES here — the seed's own L82 COMPUTED feeds
    # it, and the confirmed prune keeps every chip the searched field's
    # own flow still touches. (USER RULING 2026-09-01: only chips with NO
    # edge are removed.)
    assert "reserved_field8" in {n.get("label") for n in nodes.values()}
    # the TABLE skeleton stays: ALIAS hops (LFS128/LFS131) and the
    # CTE-consumption hop (LFS137)
    alias = [(_label(nodes, e, "source"), _label(nodes, e, "target"))
             for e in edges if e.get("edge_type") == "ALIAS"]
    assert ("rollover_loan_info", "p6@155") in alias
    assert ("loan_final", "p1@198") in alias
    assert any(_label(nodes, e, "source") == "p6@155"
               and _label(nodes, e, "target") == "loan_final"
               for e in edges if e.get("edge_type") == "TABLE_FLOW")
    # the SEARCHED field's own chips all stay
    assert "lending_ref" in {n.get("label") for n in nodes.values()}


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
    # (L183 is the SIBLING's write-projection line — it was lit only by
    # the sibling's belongs-to edges the 2026-09-01 ruling dropped, so it
    # legitimately goes dark; the seed's own write projection is L163.)
    for line in (13, 19, 48, 59, 82, 95, 117, 150, 156, 163, 198, 201):
        assert line in hl, f"the searched field's occurrence line L{line} went dark"


# ═══════════════════════════════════════════════════════════════════════
# the rule's contract: display-only, deterministic, no-change property
# ═══════════════════════════════════════════════════════════════════════

def test_chip_prune_removes_only_orphan_siblings():
    """USER RULING 2026-09-01, confirmed full variant: sibling chips with
    NO edge are removed. Tables and the searched field's chips are all
    intact; every surviving field chip touches a kept edge or is the
    seed's; the node set is a strict subset of the disabled-rule node
    set (the rule only ever removes)."""
    nodes_a, edges_a = _build("bdm_acc_loan_info", "lending_ref")
    nodes_b, edges_b = _build("bdm_acc_loan_info", "lending_ref", disable_rule=True)

    tables_b = {n["id"] for n in nodes_b.values()
                if str(n.get("id", "")).startswith("l2_tbl_")}
    tables_a = {n["id"] for n in nodes_a.values()
                if str(n.get("id", "")).startswith("l2_tbl_")}
    assert tables_a == tables_b, "a table compound was pruned"
    seed_b = {n["id"] for n in nodes_b.values() if n.get("label") == "lending_ref"}
    seed_a = {n["id"] for n in nodes_a.values() if n.get("label") == "lending_ref"}
    assert seed_a == seed_b and seed_a, "a searched-field chip was pruned"
    endpoint_ids = set()
    for e in edges_a:
        endpoint_ids.add(e.get("source"))
        endpoint_ids.add(e.get("target"))
    for n in nodes_a.values():
        assert n["id"] in endpoint_ids or n["id"] in tables_a, \
            f"orphan node survived the prune: {n.get('label')}"
    # the rule only ever removes
    assert set(nodes_a) <= set(nodes_b)
    assert {e["highlight_line"] for e in edges_a} <= {e["highlight_line"] for e in edges_b}


def test_chip_prune_unit_survivor_rules():
    """The prune's exact survivor rules, unit-tested on synthetic nodes so
    the flagship payload's shape cannot mask a regression: a chip the
    searched field's own edge feeds survives; an edge-less non-seed chip
    is removed; the seed's own chip is never pruned even edge-less."""
    fn = lambda i, label: {"id": i, "label": label}
    nodes = [fn("f_seed", "lending_ref"), fn("f_live", "kept_sibling"),
             fn("f_orphan", "orphan_sibling")]
    edges = [{"source": "f_seed", "target": "f_live"}]

    kept = LB._prune_orphan_sibling_chips(nodes, edges, "lending_ref")
    assert [n["id"] for n in kept] == ["f_seed", "f_live"]

    kept2 = LB._prune_orphan_sibling_chips(nodes, [], "lending_ref")
    assert [n["id"] for n in kept2] == ["f_seed"]


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
                         op="TABLE_COLUMN", line=183)), (
        "a SIBLING's belongs-to SCHEMA is dropped (USER RULING 2026-09-01, "
        "rule 3a reversed) — only a seed-endpoint belongs-to stays")
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


# ═══════════════════════════════════════════════════════════════════════
# USER RULING 2026-09-01, rule 7-A — "write leg only"
# ═══════════════════════════════════════════════════════════════════════
#
# "when the SEARCHED field is the column being WRITTEN by a statement,
#  its write edge SHOWS in the flow-only closure — even when the value
#  written is a constant/literal."  Boundary (write leg only): the
#  statement's OTHER literal columns stay out (siblings written with
#  constants — the 3a/chip-prune ruling drops them), the FROM-read of the
#  searched table does not drag the searched field's upstream closure
#  into the statement, and no other statement machinery shows.
#
# Corollary: for fields the statement does NOT write, NOTHING shows —
# the old R29 "always continue through the log-write" behavior is dead.
#
# Sample site: SUP_M's job-log statement —
#   L211 INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt, object_domain, …)
#   L213     '$(load_date)' AS data_dt      ← the constant projection
#   L214-221 object_domain / COUNT(1) / …   ← the sibling literal columns
#   L222 FROM bdm_acc_loan_info_sup         ← the searched table's read
#   L225 WHERE data_dt = '$(load_date)'     ← the row-selection filter
# The write leg is served through the statement's ⟐output frame (the R44
# R1 write-completion admission admits the constant projection's output VT
# upstream; the admission condition in `_apply_field_involvement` that
# keeps the leg served is the SKELETON rule — a write leg carries no field
# endpoint beyond the searched one, so it is never a sibling's value leg —
# plus the seed-endpoint check on the searched chip's own legs). These
# tests PIN that admission: tighten the skeleton rule without a write-leg
# carve-out and they go red.

LOG_WRITE_LINE = 211
LOG_STMT_LINES = frozenset(range(211, 226))
# the log's OTHER projection lines — L213 is the searched column's own
# constant projection (`'$(load_date)' AS data_dt`) and stays served.
LOG_LITERAL_PROJECTION_LINES = frozenset(range(214, 222))
# the log's literal/co-written columns — never the searched data_dt itself
LOG_SIBLING_COLUMNS = frozenset({
    "object_domain", "sub_src_system", "table_name", "job_name",
    "total_rows", "load_time", "status", "remarks",
})


def _seed_chip_labels(nodes):
    return {n.get("label", "").rsplit(".", 1)[-1].casefold()
            for n in nodes.values()}


def _build_lines(table, field, full_view=False):
    """The served closure's highlight-line set, in either view — the
    flow-only closure by default, the unfiltered FULL view with
    full_view=True (relevance_filter=False is the no-search contract)."""
    sql = FLAGSHIP.read_text(encoding="utf-8")
    result = _build_l2_graph("j1", "BDM_ACC_LOAN_INFO_SUP_M.sql", sql,
                             table, field, relevance_filter=not full_view,
                             direction="downstream")
    graph = result.get("graph") if isinstance(result.get("graph"), dict) else result
    return {e["data"]["highlight_line"] for e in graph["edges"]}


def test_ruling_7a_write_leg_shows_for_the_written_column():
    """Searching bdm_acc_loan_info_sup.data_dt on SUP_M: the job-log
    statement writes the data_dt column (@211 column list, @213
    `'$(load_date)' AS data_dt`), so its write leg IS served — exactly
    ONE edge at the INSERT line, the routed DML write leg from the
    statement's ⟐output frame into rrcdm_job_log_exec_par."""
    nodes, edges = _build("bdm_acc_loan_info_sup", "data_dt")
    at_write = _edges_of(edges, "TABLE_FLOW", LOG_WRITE_LINE)
    assert len(at_write) == 1, (
        f"expected exactly one write-leg edge @L{LOG_WRITE_LINE}, got "
        f"{[(e['edge_type'], e.get('flow_kind')) for e in at_write]}")
    leg = at_write[0]
    assert _label(nodes, leg, "target") == "rrcdm_job_log_exec_par"
    assert leg.get("flow_kind") == "write", leg
    assert "output" in (_label(nodes, leg, "source") or "").casefold(), (
        "the write leg must route through the statement's ⟐output frame")
    # the written column's own value legs ride with it: the constant
    # projection's chip → ⟐output value edge and the ⟐output membership
    assert _edges_of(edges, "TABLE_FLOW", 213), \
        "the constant projection's value edge @213 went dark"
    assert _edges_of(edges, "SCHEMA", 213), \
        "the ⟐output membership of the written column @213 went dark"
    # and the write target's box joins the closure
    assert any(n.get("table_name") == "rrcdm_job_log_exec_par"
               for n in nodes.values()), "the log's write target box is gone"


def test_ruling_7a_write_leg_carries_a_real_highlight_line():
    """INV-2: every closure edge carries a SQL line. The write leg's
    anchor IS the INSERT/SELECT statement's own line — never 0/absent —
    otherwise the edge would be unclickable and unhighlightable."""
    _, edges = _build("bdm_acc_loan_info_sup", "data_dt")
    for e in edges:
        assert isinstance(e.get("highlight_line"), int) and e["highlight_line"] >= 1, e
    leg = _edges_of(edges, "TABLE_FLOW", LOG_WRITE_LINE)
    assert leg and leg[0]["highlight_line"] == LOG_WRITE_LINE


def test_ruling_7a_sibling_literal_columns_stay_out():
    """Boundary (write leg only): the INSERT's OTHER literal columns —
    object_domain, the COUNT(1) aggregate, … — are siblings written with
    constants, so neither their chips nor any of their legs show."""
    nodes, edges = _build("bdm_acc_loan_info_sup", "data_dt")
    present = _seed_chip_labels(nodes)
    assert not (present & LOG_SIBLING_COLUMNS), (
        f"sibling literal column chips leaked into the closure: "
        f"{sorted(present & LOG_SIBLING_COLUMNS)}")
    leaked = [e for e in edges
              if e.get("highlight_line") in LOG_LITERAL_PROJECTION_LINES]
    assert not leaked, (
        f"the log's other projection lines are lit: "
        f"{[(e['edge_type'], e['highlight_line']) for e in leaked]}")
    # the whole log statement contributes exactly ONE edge (the write leg)
    # plus the searched column's own two legs (@213) — nothing else of the
    # statement's projection machinery is in the closure.
    in_stmt = [e for e in edges
               if e.get("highlight_line") in LOG_STMT_LINES
               and e.get("highlight_line") not in (223, 225)]
    assert sorted(e["highlight_line"] for e in in_stmt) == [211, 213, 213]


def test_ruling_7a_log_unwritten_field_gets_nothing():
    """Corollary: for a field the log does NOT write, NOTHING of the log
    statement shows — the old R29 "always continue through the log-write"
    behavior is dead. lending_ref (read by the sup-write statement, never
    written by the log) and iiapty (the join key) both end at the sup
    write: no log anchor, no rrcdm box."""
    for table, field in (("bdm_acc_loan_info", "lending_ref"),
                         ("ods_hie_ipacmsp", "iiapty")):
        nodes, edges = _build(table, field)
        anchors = {e["highlight_line"] for e in edges} & LOG_STMT_LINES
        assert not anchors, (
            f"{field}: the log statement still shows in the closure at "
            f"L{sorted(anchors)}")
        assert not any(n.get("table_name") == "rrcdm_job_log_exec_par"
                       for n in nodes.values()), (
            f"{field}: the log's write target box still shows")
        # the sup-write statement itself is untouched — the chain still
        # ends at the seed's own sup write leg
        assert _edges_of(edges, "TABLE_FLOW", 160), (
            f"{field}: the sup write leg @160 went dark")


def test_ruling_7a_constant_write_leg_renders():
    """'even when the value written is a constant/literal' — the other
    site of the same rule on the same sample: the sup-write statement's
    constant columns (`NULL AS reserved_field8` class @183). The seed IS
    the written column, so its write value leg (@183) and the DML write
    leg into the target box (@160) render; the co-written constant
    siblings (reserved_field6/7) stay out."""
    nodes, edges = _build("bdm_acc_loan_info_sup", "reserved_field8")
    value_legs = [e for e in _edges_of(edges, "TABLE_FLOW", SIBLING_WRITE_LINE)
                  if _label(nodes, e, "source") == "reserved_field8"]
    assert value_legs, "the constant projection's write value leg went dark"
    # the DML-routing value edge is the one whose id carries the engine's
    # `_value` suffix (the carried `_value_edge` flag is not served)
    assert any((e.get("id") or "").endswith("_value") for e in value_legs), (
        [(e.get("id"), e.get("highlight_line")) for e in value_legs])
    # the constant write renders as the routed leg: the seed's chip feeds
    # the statement's ⟐output frame (@183) and THAT frame's write leg
    # lands on the target box (@160, flow_kind='write') — the R19.3 chain,
    # served for a literal projection exactly as for a real field chain
    write_legs = [e for e in edges
                  if e.get("flow_kind") == "write"
                  and _label(nodes, e, "target") == "bdm_acc_loan_info_sup"
                  and (e.get("id") or "").endswith("_dml_out")]
    assert write_legs, "the constant write's DML leg into the target went dark"
    for e in write_legs:
        assert e["highlight_line"] >= 1, e
        assert "output" in (_label(nodes, e, "source") or "").casefold()
    present = _seed_chip_labels(nodes)
    assert not (present & {"reserved_field6", "reserved_field7"}), (
        f"co-written constant siblings leaked into the closure: "
        f"{sorted(present & {'reserved_field6', 'reserved_field7'})}")


def test_ruling_7a_full_view_is_unchanged():
    """The rule is flow-only: the FULL view (no search filter) keeps the
    whole job-log statement — the write leg @211, every literal
    projection line @213-221, the FROM read @223 and the filter @225 —
    exactly as it was before the ruling."""
    full = _build_lines("bdm_acc_loan_info_sup", "data_dt", full_view=True)
    assert LOG_WRITE_LINE in full, "the full view lost the log write leg"
    assert full >= {211, 213, 214, 215, 216, 217, 218, 219, 220, 221, 223, 225}, (
        f"the full view lost log-statement lines: "
        f"{sorted(LOG_STMT_LINES - full)}")
    # and the flow-only closure is a strict subset of the full view
    flow = _build_lines("bdm_acc_loan_info_sup", "data_dt")
    assert flow <= full
