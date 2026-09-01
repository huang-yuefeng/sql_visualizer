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

  Class 4 — THE SEED-ENDPOINT EXEMPTION IS AN OCCURRENCE IDENTITY (F1,
    2026-09-02, post-ruling 17-field audit of EAST5_STZFXXB_M.sql). The
    exemption used to be a NAME match that ran BEFORE the Class-3 drop, so
    a sibling sharing the searched field's name was admitted as "seed
    endpoint" and the 3a drop was unreachable for it: searching
    `east5_stzfxxb.charge_department` served the source table's OWN
    `charge_department` belongs-to edges (one per read line) as if they
    were the searched chip's. The exemption now requires the belongs-to
    TARGET's resolved owner (`_tgt_canon` — the extractor's own I2
    source-table resolution) to be the SEARCHED table; a same-named chip
    owned elsewhere stays a sibling's belongs-to and reaches the Class-3
    drop — UNLESS it is not a written column of its own, in which case it
    is the searched value carried through a container (a CTE/VT/derived
    column) and its belongs-to is the searched field's structural fact.

  Class 5 — THE SEARCHED FIELD'S OWN VALUE LEG ROUTED THROUGH AN AS-ALIAS
    (F2, same audit). When a source field's value is written out under an
    aliased output column (`REPLACE(a.entd_paym_dt,"_","") As stzfrq`), the
    alias's ⟐output legs — the write value leg `alias → ⟐output` and the
    membership `⟐output → alias` — used to drop as "a sibling's value leg"
    (Class 2), leaving the audited TRANSFORM field→alias … hole … DML
    shape. They are the SEARCHED field's own value legs when three carried
    facts hold: PROVENANCE (a value-carrying edge runs from the searched
    field's own chip into the frame), the frame is the WRITE TARGET'S own
    column, and the statement does not also write a column of the searched
    field's own on the written box (the §7-A boundary — EAST5's
    `PARTITION(…, charge_department)`). A sibling's frame satisfies none of
    the three together, so `reserved_field8`'s legs stay dropped.
"""

import contextlib
import io
import sys
import zipfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.services.l2_builder as LB  # noqa: E402
from app.services.l2_builder import (  # noqa: E402
    _apply_field_involvement,
    _build_l2_graph,
)
from app.services.workspace_service import (  # noqa: E402
    create_workspace,
    delete_workspace,
)

SAMPLES = BACKEND_DIR.parent / "samples" / "sql_sample_v1"
FLAGSHIP = SAMPLES / "BDM_ACC_LOAN_INFO_SUP_M.sql"
FLAGSHIP_NAME = "BDM_ACC_LOAN_INFO_SUP_M.sql"
EAST5 = SAMPLES / "EAST5_STZFXXB_M.sql"
EAST5_NAME = "EAST5_STZFXXB_M.sql"

# The L82 / L163 anchors of the two mis-anchored JOIN carriers, and the
# sibling write zone (L183 the write projection, L198 the alias instance
# the sibling's value is read through). Real join sites for contrast.
CASE_READ_LINE = 82
WRITE_PROJECTION_LINE = 163
SIBLING_WRITE_LINE = 183
SIBLING_READ_LINE = 198
REAL_JOIN_SITES = (41, 95, 117, 150, 156, 201)


@contextlib.contextmanager
def _ws(sql_text, script_name):
    """A throwaway workspace holding ONE script, deleted on exit.

    REVIEW F6 hygiene (R2.3/R4-M adjudicated class): the harness's
    create-over-a-zip + delete-in-finally pattern with a UNIQUE id per
    call — never a fabricated shared id, which leaks a cache directory
    into the production container and shares cache state across tests.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(script_name, sql_text)
    ws_id = create_workspace(buf.getvalue())
    try:
        yield ws_id
    finally:
        delete_workspace(ws_id)


def _run(sql_text, script_name, table, field, disable_rule=False,
         relevance_filter=True):
    """The served closure for one search, in a throwaway workspace."""
    with _ws(sql_text, script_name) as ws_id:
        if disable_rule:
            real = LB._apply_field_involvement
            LB._apply_field_involvement = _passthrough
            try:
                result = _build_l2_graph(ws_id, script_name, sql_text, table,
                                         field, relevance_filter=relevance_filter,
                                         direction="downstream")
            finally:
                LB._apply_field_involvement = real
        else:
            result = _build_l2_graph(ws_id, script_name, sql_text, table, field,
                                     relevance_filter=relevance_filter,
                                     direction="downstream")
    graph = result.get("graph") if isinstance(result.get("graph"), dict) else result
    nodes = {n["data"]["id"]: n["data"] for n in graph["nodes"]}
    edges = [e["data"] for e in graph["edges"]]
    return nodes, edges


def _passthrough(new_edges, field, relevance_filter, physical_model=None,
                 sql_text="", table=""):
    """The pre-rule engine (the rule disabled) for before/after asserts."""
    return new_edges


def _build(table, field, disable_rule=False):
    """Served SUP_M × lending_ref closure; optionally with the admission
    rule disabled (the pre-rule engine) for before/after assertions."""
    return _run(FLAGSHIP.read_text(encoding="utf-8"), FLAGSHIP_NAME,
                table, field, disable_rule=disable_rule)


def _build_east5(table, field, disable_rule=False):
    """Served EAST5 closure — the F1/F2 audit corpus."""
    return _run(EAST5.read_text(encoding="utf-8"), EAST5_NAME,
                table, field, disable_rule=disable_rule)


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
    LB._apply_field_involvement = _passthrough
    with _ws(sql, "j1_simple.sql") as ws_id:
        try:
            r0 = _build_l2_graph(ws_id, "j1_simple.sql", sql, "bdm_main", "acct_no")
        finally:
            LB._apply_field_involvement = real
        r1 = _build_l2_graph(ws_id, "j1_simple.sql", sql, "bdm_main", "acct_no")
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

    def spy(new_edges, field, relevance_filter, physical_model=None,
            sql_text="", table=""):
        seen.append(relevance_filter)
        return real(new_edges, field, relevance_filter,
                    physical_model=physical_model, sql_text=sql_text,
                    table=table)

    LB._apply_field_involvement = spy
    try:
        with _ws(sql, FLAGSHIP_NAME) as ws_id:
            _build_l2_graph(ws_id, FLAGSHIP_NAME, sql, "bdm_acc_loan_info",
                            "lending_ref", relevance_filter=False)
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
             own_seg=0, hops=None, anchor=None, src_owner="", tgt_canon="",
             src_id="s", tgt_id="t", flow_kind=None):
    return {
        "id": "l2e_test", "source": src_id, "target": tgt_id, "edge_type": et,
        "highlight_line": anchor if anchor is not None else line,
        "_src_label": src, "_tgt_label": tgt, "_src_line": line, "_tgt_line": line,
        "_op": op, "_value_edge": value_edge, "_tgt_output": tgt_output,
        "_own_seg_idx": own_seg, "_path_hops": hops or [],
        "_src_defined_in": defined_in, "_tgt_defined_in": "",
        "_src_owner": src_owner, "_tgt_canon": tgt_canon,
        "flow_kind": flow_kind,
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
    with _ws(sql, FLAGSHIP_NAME) as ws_id:
        result = _build_l2_graph(ws_id, FLAGSHIP_NAME, sql, table, field,
                                 relevance_filter=not full_view,
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


# ═══════════════════════════════════════════════════════════════════════
# Class 4 (F1, 2026-09-02) — the seed-endpoint exemption is an OCCURRENCE
# identity; Class 5 (F2) — the searched field's own value leg routed
# through an AS-alias. Audit corpus: EAST5_STZFXXB_M.sql.
# ═══════════════════════════════════════════════════════════════════════

F1_SEED = ("east5_stzfxxb", "charge_department")
# The audited 9: the source table's OWN charge_department belongs-to edges —
# one pair at the first read (@51, both casings) and one per CASE-WHEN read
# (@54/@55/@56/@66/@68/@70), plus the write projection's (@86). Every one of
# them belongs to `bdm_acc_entrusted_payment.charge_department`, a DIFFERENT
# occurrence of the searched NAME.
F1_SIBLING_LINES = (51, 54, 55, 56, 66, 68, 70, 86)
F1_SIBLING_SOURCES = ("bdm_acc_entrusted_payment", "a@141")
# the searched chip's own anchors that must stay lit (the audit's "5 true"
# core): the PARTITION write chain @41 and the seed's own Reappears @86.
F1_OWN_LINES = (41, 86, 141)


def _belongs_to(nodes, edges, line, src_contains=""):
    """Served belongs-to SCHEMA edges at `line` (never the ⟐output
    membership form, which is Class 2's business)."""
    return [e for e in edges
            if e.get("edge_type") == "SCHEMA"
            and e.get("highlight_line") == line
            and "output" not in (_label(nodes, e, "source") or "").casefold()
            and src_contains in (_label(nodes, e, "source") or "")]


def test_f1_sibling_belongs_to_same_name_is_dropped():
    """F1: searching `east5_stzfxxb.charge_department` serves NO belongs-to
    of the source table's own `charge_department` occurrence. The
    seed-endpoint exemption used to be a NAME match that ran before the
    Class-3 drop, so all 9 were admitted as "seed endpoint" — the 3a drop
    was unreachable for a same-named sibling."""
    nodes, edges = _build_east5(*F1_SEED)
    for line in F1_SIBLING_LINES:
        leaked = [e for e in _belongs_to(nodes, edges, line)
                  if any(s in (_label(nodes, e, "source") or "")
                         for s in F1_SIBLING_SOURCES)]
        assert not leaked, (
            f"the sibling belongs-to @L{line} is still served (F1): "
            f"{[(_label(nodes, e, 'source'), _label(nodes, e, 'target')) for e in leaked]}")


def test_f1_searched_chip_own_anchors_stay():
    """F1's boundary: the SEARCHED chip's own belongs-to / Reappears class
    is untouched — `east5_stzfxxb → charge_department` @86 (the INSERT
    projection's own occurrence) stays, and so does the searched chip's own
    write chain (@41) and its read (@141)."""
    nodes, edges = _build_east5(*F1_SEED)
    own = [e for e in _belongs_to(nodes, edges, 86)
           if _label(nodes, e, "source") == "east5_stzfxxb"]
    assert own, "the searched chip's own belongs-to @86 went dark (F1 over-drop)"
    assert all(_label(nodes, e, "target").casefold() == "charge_department"
               for e in own)
    hl = {e["highlight_line"] for e in edges}
    for line in F1_OWN_LINES:
        assert line in hl, f"the searched chip's own anchor L{line} went dark"
    # the write chain is intact: the seed's own value leg into the ⟐output
    # frame and the routed DML leg into the written box, both @41
    assert _edges_of(edges, "TABLE_FLOW", 41), "the @41 write chain went dark"
    write = [e for e in edges
             if e.get("flow_kind") == "write"
             and _label(nodes, e, "target") == "east5_stzfxxb"]
    assert write, "the DML write leg into east5_stzfxxb went dark"


def test_f1_truth_rate_on_the_audited_closure_improves():
    """The audit's measurement: 47 served / 5 true before, because 9 of them
    were the sibling's belongs-to edges. After F1 the closure is exactly the
    pre-rule set minus the rule's drops — the 9 belongs-to among them — and
    nothing else moves (the rule only ever removes)."""
    _, edges = _build_east5(*F1_SEED)
    _, edges0 = _build_east5(*F1_SEED, disable_rule=True)
    assert len(edges) == 38, (
        f"the audited closure moved: {len(edges)} served (audit: 38 after the "
        f"9 sibling belongs-to and the Class-2 drops, from {len(edges0)} pre-rule)")
    assert len(edges) < len(edges0), "the rule must only ever remove"


def test_f1_predicate_occurrence_identity_not_name():
    """The Class-3 exemption in isolation: a belongs-to whose target's
    RESOLVED OWNER (`_tgt_canon`) is the searched table is the searched
    field's own; the same NAME owned by another table is a sibling's
    belongs-to and drops — unless that chip carries no write of its own (a
    container's column: the searched value flowing through)."""
    admit_own = _apply_field_involvement(
        [_carrier(et="SCHEMA", src="east5_stzfxxb", tgt="east5_stzfxxb.charge_department",
                  op="TABLE_COLUMN", line=86, tgt_canon="east5_stzfxxb",
                  tgt_id="chip_a")],
        "charge_department", True, table="east5_stzfxxb") == [_carrier(
            et="SCHEMA", src="east5_stzfxxb", tgt="east5_stzfxxb.charge_department",
            op="TABLE_COLUMN", line=86, tgt_canon="east5_stzfxxb", tgt_id="chip_a")]
    assert admit_own, "the searched table's own belongs-to dropped"

    # …but the same-named chip that carries no write of its own is the
    # searched value inside a container, and its belongs-to stays (the
    # canonical's CTE/VT belongs-to rows: SUP_M LFS8/9/38/74/104/134/139-142)
    container = _carrier(et="SCHEMA", src="rollover_loan_info",
                         tgt="rollover_loan_info.lending_ref",
                         op="TABLE_COLUMN", line=156,
                         tgt_canon="rollover_loan_info", tgt_id="chip_c")
    assert _apply_field_involvement(
        [container], "lending_ref", True,
        table="bdm_acc_loan_info") == [container]
    # …and a WRITTEN same-named chip is a second column of that name: a
    # sibling — its belongs-to drops with it (F1), while its write leg is
    # the sibling's own flow and drops too
    written = _carrier(et="SCHEMA", src="bdm_acc_entrusted_payment",
                       tgt="bdm_acc_entrusted_payment.charge_department",
                       op="TABLE_COLUMN", line=86,
                       tgt_canon="bdm_acc_entrusted_payment", tgt_id="chip_b")
    written_leg = _carrier(et="TABLE_FLOW",
                           src="bdm_acc_entrusted_payment.charge_department",
                           tgt="⟐ output", op="INSERT", line=86, value_edge=True,
                           tgt_output=True, src_id="chip_b", tgt_id="out")
    served = _apply_field_involvement([written, written_leg], "charge_department",
                                      True, table="east5_stzfxxb")
    assert served == [written_leg], (
        "a WRITTEN same-named chip's belongs-to is the sibling's own fact (F1); "
        f"got {[(e['edge_type'], e.get('_src_label')) for e in served]}")


# the audit's five over-removals: the searched field's value written out
# under an aliased output column, whose ⟐output legs Class 2 used to cut
F2_CASES = (
    ("bdm_acc_entrusted_payment", "entd_paym_dt", "stzfrq", 50,
     "L50 REPLACE(a.entd_paym_dt,\"_\",\"\") As stzfrq"),
    ("bdm_acc_entrusted_payment", "entd_opp_acct_name", "stzfdxhm", 65,
     "L65 … END AS stzfdxhm"),
    ("bdm_acc_entrusted_payment", "entd_opp_acct_no", "stzfdxzh", 53,
     "L53 … END As stzfdxzh"),
    ("bdm_acc_entrusted_payment", "reserved_field15", "RESERVED_9", 117,
     "L117 … END AS RESERVED_9"),
    ("bdm_pub_branch", "org_no_cbrc", "jrxkzh", 43,
     "L43 NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh"),
)
EAST5_DML_LINE = 41


def test_f2_own_alias_output_legs_are_served():
    """F2: the AS-alias frame's ⟐output pair is the SEARCHED field's own
    value chain — the write value leg `alias → ⟐output` and the membership
    `⟐output → alias` are served again, so the closure runs
    field → alias → ⟐output → DML without the audited hole."""
    for table, field, frame, line, site in F2_CASES:
        nodes, edges = _build_east5(table, field)
        legs = [e for e in edges
                if e.get("highlight_line") == line
                and frame.casefold() in (_label(nodes, e, "source") or "").casefold()
                + (_label(nodes, e, "target") or "").casefold()
                and e["edge_type"] in ("SCHEMA", "TABLE_FLOW")]
        kinds = sorted(e["edge_type"] for e in legs)
        assert kinds == ["SCHEMA", "TABLE_FLOW"], (
            f"{field}: the {frame} ⟐output pair @L{line} is {kinds} — F2 "
            f"re-removed it ({site})")
        value_leg = [e for e in legs if e["edge_type"] == "TABLE_FLOW"]
        assert any((e.get("id") or "").endswith("_value") for e in value_leg), (
            f"{field}: the frame's write value leg lost its DML routing ({site})")
        assert any(e.get("flow_kind") == "write" and e.get("highlight_line") == EAST5_DML_LINE
                   for e in edges), (
            f"{field}: the chain never reaches the DML @L{EAST5_DML_LINE}")


def test_f2_own_alias_frame_is_the_write_targets_column():
    """F2's frame fact, pinned per case: every admitted frame is a column of
    the box the statement writes (`east5_stzfxxb`), and the searched field's
    own chip feeds it — the two facts that make the alias's value the
    searched field's own."""
    for table, field, frame, line, site in F2_CASES:
        nodes, edges = _build_east5(table, field)
        feed = [e for e in edges
                if e["edge_type"] in ("TRANSFORM", "COMPUTED")
                and frame.casefold() in (_label(nodes, e, "target") or "").casefold()]
        assert feed, f"{field}: no producing edge into {frame} ({site})"
        assert any(_label(nodes, e, "source").casefold() == field.casefold()
                   for e in feed), (
            f"{field}: {frame} is not fed by the searched field's own chip ({site})")


def test_f2_boundary_written_own_column_stays_out():
    """The §7-A boundary that keeps F2 honest: when the statement writes a
    column of the searched field's own on the written box (EAST5's
    `PARTITION(p_dt, charge_department)` @41), the statement's OTHER
    aliased columns stay the sibling's flow — searching charge_department
    serves no stzfdxhm ⟐output leg even though its CASE reads the field."""
    nodes, edges = _build_east5(*F1_SEED)
    leaked = [e for e in edges
              if (e.get("_tgt_label") or "").casefold() in ("stzfdxhm", "stzfdxzh")
              or (e.get("_src_label") or "").casefold() in ("stzfdxhm", "stzfdxzh")]
    assert not leaked, (
        "the statement's other aliased columns leaked into the "
        "charge_department closure: "
        f"{[(e['edge_type'], e.get('_src_label'), e.get('_tgt_label'), e.get('highlight_line')) for e in leaked]}")


def test_f2_predicate_provenance_and_write_target():
    """F2 in isolation: the ⟐output pair of a frame is admitted only when
    the searched field's own chip feeds it (provenance) AND the frame is the
    write target's own column; a sibling's frame never is."""
    feed = _carrier(et="TRANSFORM", src="a.entd_paym_dt", tgt="stzfrq",
                    op="REFERENCE", line=50, src_owner="bdm_acc_entrusted_payment",
                    tgt_canon="east5_stzfxxb", src_id="seed", tgt_id="frame")
    membership = _carrier(et="SCHEMA", src="⟐ output", tgt="stzfrq", op="OUTPUT",
                          line=50, tgt_canon="east5_stzfxxb",
                          src_id="out", tgt_id="frame")
    value = _carrier(et="TABLE_FLOW", src="stzfrq", tgt="⟐ output", op="INSERT",
                     line=50, value_edge=True, tgt_output=True,
                     src_owner="east5_stzfxxb", src_id="frame", tgt_id="out")
    # the routed DML leg that names the WRITE TARGET the frame belongs to
    dml = _carrier(et="TABLE_FLOW", src="⟐ output", tgt="east5_stzfxxb",
                   op="INSERT", line=41, tgt_output=False, flow_kind="write",
                   src_owner="east5_stzfxxb", src_id="out", tgt_id="box")
    served = _apply_field_involvement([feed, membership, value, dml],
                                      "entd_paym_dt", True,
                                      table="bdm_acc_entrusted_payment")
    assert len(served) == 4, (
        f"the own frame's ⟐output pair must ride with the provenance edge, "
        f"got {[(e['edge_type'], e.get('_src_label')) for e in served]}")
    # a sibling's frame: fed by the searched field but NOT the write target's
    # own column (SUP_M's reserved_field8 lives on the loan_final CTE)
    sib_frame = _carrier(et="COMPUTED", src="p6.lending_ref", tgt="reserved_field8",
                         op="REFERENCE", line=82, src_owner="bdm_acc_loan_info",
                         tgt_canon="loan_final", src_id="seed", tgt_id="sibframe")
    sib_value = _carrier(et="TABLE_FLOW", src="reserved_field8", tgt="⟐ output",
                         op="INSERT", line=183, value_edge=True, tgt_output=True,
                         src_owner="loan_final", src_id="sibframe", tgt_id="out")
    assert _apply_field_involvement([sib_frame, sib_value], "lending_ref", True,
                                    table="bdm_acc_loan_info") == [sib_frame], (
        "the sibling frame's write leg was admitted (F2 must stay off)")
