"""Team V4 — the walker-semantics batch of v3.3.195.

Four items, one file:

  R46c — the value-cone admission gate inside `compute_field_flow`
      (AD3 §Q2, the adjudicated R-GATE). Chips admitted = seed ∪ same-name
      chips on admitted boxes ∪ forward chip-cone over CONE_EDGES ∪ the
      write-slot's direct producers; boxes = owners of admitted chips +
      the box endpoints of FIELD-JUSTIFIED legs (D2 write-leg / R29 carry /
      W6b nested-VT context / W3 alias / W4 own-line predicate), decided on
      MODEL facts — never on the display `reason` string. Foreign
      statement trunks and co-written projection chips drop with their
      edges; the chain boxes stay.

  FSC-1 — the J12-9 owner-agnostic seed. A bare column in a multi-table
      FROM has no model owner, so no PhysicalField named it, so W1 found no
      seed and the pair was dead at L2. The seed is now the occurrence.

  R46e — the casing-invariant closure (H7 §4). `_fold` (`.lower()`) on
      BOTH sides of every identity comparison in the walker, in
      `l1_builder.detect_role` and in
      `dataflow_service._filter_l1_by_lineage`. The dead-legacy
      `compute_field_lineage` / `filter_relevant` pair stays unfixed on
      purpose (H7 §7-3).

  L206 — the cross-check residual, adjudicated in-passing (see
      `test_l206_join_predicate_residual`).

Every before/after assertion flips `lineage._VALUE_CONE_GATE` (the gate's
own switch — the switch IS the feature, mirror of `_ALIAS_SEED_EXPANSION`)
or `lineage._fold` (identity ⇒ the pre-R46e exact-comparison engine), so
the "before" side is the real previous engine, never a re-implementation.
"""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.extractor import lineage  # noqa: E402
from app.extractor.physical_model import build_physical_model  # noqa: E402
from app.extractor.variable_extractor_v2 import (  # noqa: E402
    extract_variables_from_sql,
)
from app.extractor.dependency_graph import build_dependency_graph  # noqa: E402
from app.services.l2_builder import (  # noqa: E402
    _build_l2_graph,
    _drop_partition_ddl_frames,
    _load_or_build_graph,
)

SAMPLES = BACKEND_DIR.parent / "samples" / "sql_sample_v1"
TPCDS = BACKEND_DIR.parent / "samples" / "tpcds_qualified"

EAST5 = "EAST5_STZFXXB_M.sql"
SUP_M = "BDM_ACC_LOAN_INFO_SUP_M.sql"
PL = "BDM_ACC_LOAN_INFO_PL.sql"
DL = "BDM_ACC_LOAN_INFO_Digitallending.sql"
RFN = "BDM_ACC_LOAN_INFO_RFN.sql"


# ── harness ─────────────────────────────────────────────────────────────

def _served(script, table, field, gate=True):
    """The served L2 flow view for one (table, field) — the same
    `_build_l2_graph(relevance_filter=True)` path the response and the
    jaccard benchmark use. `gate=False` runs the pre-R46c engine."""
    real = lineage._VALUE_CONE_GATE
    lineage._VALUE_CONE_GATE = gate
    try:
        sql = (SAMPLES / script).read_text(encoding="utf-8")
        result = _build_l2_graph("v4", script, sql, table, field,
                                 True, "downstream")
    finally:
        lineage._VALUE_CONE_GATE = real
    graph = result.get("graph") if isinstance(result.get("graph"), dict) else result
    nodes = {n["data"]["id"]: n["data"] for n in graph["nodes"]}
    edges = [e["data"] for e in graph["edges"]]
    return result, nodes, edges


def _model(script):
    """(full_graph, physical_model) on the SERVED model — the graph-cache
    path `_build_l2_graph` itself uses, never a second extraction."""
    sql = (SAMPLES / script).read_text(encoding="utf-8")
    full_graph, _schemas, pm = _load_or_build_graph("v4cov", script, sql)
    return _drop_partition_ddl_frames(full_graph, sql), pm


def _closure(script, table, field, gate=True, fold=None):
    """The walker's node closure on the served model, with the gate and the
    fold independently switchable (the two switches ARE the features)."""
    full_graph, pm = _model(script)
    real_gate, real_fold = lineage._VALUE_CONE_GATE, lineage._fold
    lineage._VALUE_CONE_GATE = gate
    if fold is not None:
        lineage._fold = fold
    try:
        return lineage.compute_field_flow(full_graph, table, field,
                                          physical_model=pm)
    finally:
        lineage._VALUE_CONE_GATE = real_gate
        lineage._fold = real_fold


def _coverage_lines(script, table, field):
    """(own_lines, covered_lines) for one pair on the served model.

    An own occurrence = a field-like occurrence carrying the searched field
    part whose owning entity is an entity of the searched table (the W1
    seed rule, R46a's seed-claim set) — the model's own occurrences, never
    the display's merged chips and never the index.

    An own occurrence line is COVERED when the served closure anchors it:
    either an own chip sits on the line, or a served edge (both endpoints
    in the closure) is anchored there and touches an own chip. That is the
    honest R44.2 metric — own-EDGE anchoring, not line overlap with other
    fields' edges.
    """
    full_graph, pm = _model(script)
    own = []
    for key, tbl in pm.tables.items():
        if lineage._fold(tbl.name) != lineage._fold(table):
            continue
        for fname, fld in tbl.fields.items():
            if lineage._fold(fname) != lineage._fold(field):
                continue
            for vid in fld.occurrence_ids:
                o = pm.occurrence(vid)
                if o is None or o.get("variable_type") not in lineage.FIELD_LIKE:
                    continue
                if o.get("line_start"):
                    own.append((o["line_start"], vid))
    own_lines = {line for line, _vid in own}
    own_chips = {vid for _line, vid in own}
    closure = lineage.compute_field_flow(full_graph, table, field,
                                        physical_model=pm)
    covered = set(own_lines) & {line for line, vid in own if vid in closure}
    for E in pm.edges:
        if E.containment or not E.highlight_line:
            continue
        if E.source_id in closure and E.target_id in closure:
            if E.source_id in own_chips or E.target_id in own_chips:
                covered.add(E.highlight_line)
    return own_lines, covered


# ═══════════════════════════════════════════════════════════════════════
# 1. R46c — the cross-check's wrong-covered lines drop
# ═══════════════════════════════════════════════════════════════════════

def test_east5_foreign_partition_predicates_uncovered():
    """`bdm_acc_loan_info.data_dt` in EAST5 covered the OTHER tables'
    partition predicates too — `c.data_dt` @146 and @149 (bdm_pub_branch,
    joined twice), `e.DATA_DT` @154 (BDM_ACC_INTERNAL_COUNTERPARTY) and
    `a.data_dt` @159 (bdm_acc_entrusted_payment). Those are other tables'
    row-selections; the searched field never occurs on those lines, so
    their predicates are not the searched field's row-selection and the
    gate drops them."""
    _, _nodes, edges = _served(EAST5, "bdm_acc_loan_info", "data_dt")
    covered = {e.get("highlight_line") for e in edges}
    for line in (146, 149, 154, 159):
        assert line not in covered, (
            f"L{line} is another table's data_dt predicate; it must not be "
            f"covered by the bdm_acc_loan_info.data_dt closure (edges at "
            f"that line: {[e['id'] for e in edges if e.get('highlight_line') == line]})")
    # and the searched field's OWN join predicate at L143 stays covered
    assert 143 in covered
    # ... and the pre-gate engine did cover the foreign lines (the
    # assertion means something)
    _, _nodes0, edges0 = _served(EAST5, "bdm_acc_loan_info", "data_dt",
                                 gate=False)
    covered0 = {e.get("highlight_line") for e in edges0}
    for line in (146, 149, 154, 159):
        assert line in covered0, f"L{line} was covered before the gate"


def test_gate_shrinks_and_never_grows_the_served_closure():
    """The gate is an admission gate: for every flagship pair the served
    closure is a SUBSET of the pre-gate one — nodes, edges and highlight
    lines. (AD3's measured blast radius is the shrink; a single addition
    would mean the gate re-admits, which it has no rule for.)"""
    for script, table, field in (
            (EAST5, "east5_stzfxxb", "p_dt"),
            (EAST5, "bdm_acc_loan_info", "data_dt"),
            (SUP_M, "bdm_acc_loan_info", "lending_ref"),
            (SUP_M, "bdm_acc_loan_info", "data_dt"),
            (PL, "bdm_acc_loan_info", "data_dt"),
            (DL, "bdm_acc_loan_info", "data_dt"),
    ):
        result1, nodes1, edges1 = _served(script, table, field, gate=True)
        result0, nodes0, edges0 = _served(script, table, field, gate=False)
        assert set(nodes1) <= set(nodes0), (script, table, field)
        # Compare CONTENT (type + endpoints + anchor line), not raw ids:
        # an l2e_* id is the md5 of a raw var/carrier base, so
        # _combine_edges re-derives it when the carrier order changes —
        # the V8 canonical walk order (2026-09-02) does exactly that,
        # same edge content under a different id (measured EAST5 ×
        # data_dt: gate-on 10 content keys ⊆ gate-off 31; the flagged
        # `l2e_a444ae6b4255_dml_out` == gate-off's
        # `l2e_049021fa3ec2_dml_out`).
        content = lambda e: (e.get("edge_type"), e.get("source"),
                             e.get("target"), e.get("highlight_line"))
        c1 = {content(e) for e in edges1}
        c0 = {content(e) for e in edges0}
        assert c1 <= c0, \
            (script, table, field,
             [e for e in edges1 if content(e) not in c0])
        assert result1.get("search_matched", True), (script, table, field)


# ═══════════════════════════════════════════════════════════════════════
# 2. the RECALL GUARD — own-occurrence anchoring per flagship
# ═══════════════════════════════════════════════════════════════════════

# The honest R44.2 floor per flagship: the share of the searched field's
# OWN occurrence lines the served closure must anchor. Measured on this
# tree (all four flagships AND RFN anchor 100% of their own occurrences,
# gate on and off) — a drop below the floor means the gate started eating
# the very occurrences flow-only exists to show.
OWN_EDGE_FLOORS = {
    EAST5: 1.0,
    PL: 1.0,
    SUP_M: 1.0,
    DL: 1.0,
    RFN: 1.0,
}


@pytest.mark.parametrize("script", sorted(OWN_EDGE_FLOORS))
def test_occurrence_coverage_own_edge(script):
    floor = OWN_EDGE_FLOORS[script]
    own_lines, covered = _coverage_lines(script, *_seed_of(script))
    assert own_lines, f"no own occurrences found in {script}"
    share = len(covered) / len(own_lines)
    assert share >= floor, (
        f"{script}: own-occurrence anchor coverage {len(covered)}/"
        f"{len(own_lines)} = {share:.4f} < floor {floor:.4f}; missing "
        f"lines {sorted(own_lines - covered)[:8]}")


def _seed_of(script):
    """The (table, field) each flagship's own-occurrence floor is measured
    on — the seed whose closure the audits walked."""
    return {
        EAST5: ("bdm_acc_loan_info", "data_dt"),
        PL: ("bdm_acc_loan_info", "data_dt"),
        SUP_M: ("bdm_acc_loan_info", "lending_ref"),
        DL: ("bdm_acc_loan_info", "data_dt"),
        RFN: ("bdm_acc_loan_info", "repay_acct_no"),
    }[script]


def test_gate_preserves_own_occurrence_anchor_lines():
    """The guard itself: the gate keeps a per-closure set of own-occurrence
    anchor lines and refuses to lose one. Walk every physical pair of the
    two smallest flagships and require the gated closure to anchor the
    same own lines the pre-gate closure did."""
    for script in (EAST5, PL):
        full_graph, pm = _model(script)
        pairs = [(tbl.name, fname) for tbl in pm.tables.values()
                 if tbl.kind == "physical" for fname in tbl.fields]
        checked = 0
        for table, field in pairs:
            pre = lineage._VALUE_CONE_GATE
            lineage._VALUE_CONE_GATE = False
            try:
                before = lineage.compute_field_flow(full_graph, table, field,
                                                    physical_model=pm)
            finally:
                lineage._VALUE_CONE_GATE = pre
            own_chips = set()
            for key, tbl in pm.tables.items():
                if lineage._fold(tbl.name) != lineage._fold(table):
                    continue
                for fname, fld in tbl.fields.items():
                    if lineage._fold(fname) != lineage._fold(field):
                        continue
                    own_chips |= set(fld.occurrence_ids)
            own_lines = {pm.occurrence(v).get("line_start") for v in own_chips
                         if v in before and pm.occurrence(v)
                         and pm.occurrence(v).get("variable_type")
                         in lineage.FIELD_LIKE
                         and pm.occurrence(v).get("line_start")}
            if not own_lines:
                continue
            after = lineage.compute_field_flow(full_graph, table, field,
                                               physical_model=pm)
            kept = {pm.occurrence(v).get("line_start") for v in own_chips
                    if v in after and pm.occurrence(v)
                    and pm.occurrence(v).get("variable_type")
                    in lineage.FIELD_LIKE
                    and pm.occurrence(v).get("line_start")}
            assert own_lines <= kept, (
                f"{script} {table}.{field}: the gate dropped the anchor of "
                f"{sorted(own_lines - kept)[:5]}")
            checked += 1
        assert checked >= 20, f"{script}: only {checked} pairs exercised"


# ═══════════════════════════════════════════════════════════════════════
# 3. R46c — the co-written projection exclusion
# ═══════════════════════════════════════════════════════════════════════

def test_cowritten_projection_value_legs_and_belongs_to_drop():
    """`reserved_field8` is co-written with `lending_ref` in loan_final's
    projection list (SUP_M @82/@183). NOTHING of the sibling anchors it in
    the searched field's flow view any more — USER RULING 2026-09-01: its
    belongs-to SCHEMA facts are DROPPED (rule 3a reversed; was ✅
    "skeleton"), its value legs were already dropped by the field-
    involvement gate, and the edge-less chip prune removes any sibling
    chip left floating. What survives is exactly the value-cone edge the
    SEARCHED field feeds (`lending_ref → reserved_field8` COMPUTED @82) —
    which is also the only reason the chip is still in the closure at all
    (a chip survives while a kept edge of the searched field's own flow
    touches it). Nothing is SUPPRESSED in the full view: there the
    sibling keeps all of its own edges."""
    _r, nodes, edges = _served(SUP_M, "bdm_acc_loan_info", "lending_ref")
    sib = [e for e in edges
           if "reserved_field8" in (nodes.get(e["source"], {}).get("label")
                                    or "").lower()
           or "reserved_field8" in (nodes.get(e["target"], {}).get("label")
                                    or "").lower()]
    assert sib, "the sibling chip vanished from the closure entirely"
    # belongs-to facts are GONE from the flow view (ruling 2026-09-01) …
    assert not any(e["edge_type"] == "SCHEMA" for e in sib), sib
    # … the value-cone edge the searched field feeds stays — the chip's
    # only surviving anchor …
    assert any(e["edge_type"] == "COMPUTED"
               and e.get("highlight_line") == 82 for e in sib), sib
    # … and no value leg OF the sibling is served: nothing sourced BY it,
    # no DML/TABLE_FLOW carrier on its behalf.
    value_legs = [e for e in sib if e["edge_type"] in ("DML", "TABLE_FLOW", "REF")]
    assert not value_legs, (
        f"the co-written sibling still carries value legs: {value_legs}")
    # no suppression machinery: in the FULL build (View 2) the sibling's
    # own legs are still served — they only lose the flow view, because the
    # gate stops admitting the sibling, and `filter_by_field_flow` drops an
    # edge whose endpoint is gone.
    sql = (SAMPLES / SUP_M).read_text(encoding="utf-8")
    full_build = _build_l2_graph("v4", SUP_M, sql, "bdm_acc_loan_info",
                                 "lending_ref", False, "downstream")
    fg = full_build.get("graph") if isinstance(full_build.get("graph"), dict) else full_build
    fnodes = {n["data"]["id"]: n["data"] for n in fg["nodes"]}
    sib_full = [e["data"] for e in fg["edges"]
                if "reserved_field8" in (fnodes.get(e["data"]["source"], {}).get("label")
                                         or "").lower()]
    assert sib_full, "the full build lost the sibling chip's edges too"
    assert any(e["edge_type"] == "TABLE_FLOW" for e in sib_full), sib_full[:4]


# ═══════════════════════════════════════════════════════════════════════
# 4. R46c — the foreign statement-trunk exclusion
# ═══════════════════════════════════════════════════════════════════════

def test_foreign_statement_trunk_excluded():
    """TOP11 (the rrcdm job-log INSERT @179) writes `data_dt …`, never
    `ccy_code`, and its row-selection filters `p_dt` — so its write trunk
    `⟐output@179 → rrcdm_job_log_exec_par` has no field evidence for a
    `bdm_acc_entrusted_payment.ccy_code` search and must drop."""
    _r, nodes, edges = _served(EAST5, "bdm_acc_entrusted_payment", "ccy_code")
    trunk = [e for e in edges
             if e.get("highlight_line") == 179
             and nodes.get(e["target"], {}).get("label")
             == "rrcdm_job_log_exec_par"]
    assert not trunk, f"the foreign statement trunk is still served: {trunk}"
    # the searched field's own statement trunk stays (its write leg carries
    # the field)
    own_trunk = [e for e in edges
                 if e.get("highlight_line") == 41
                 and nodes.get(e["target"], {}).get("label") == "east5_stzfxxb"]
    assert own_trunk, "the searched field's own write trunk must stay"
    # … and the pre-gate engine served the foreign trunk (meaningful)
    _r0, nodes0, edges0 = _served(EAST5, "bdm_acc_entrusted_payment", "ccy_code",
                                  gate=False)
    assert any(e.get("highlight_line") == 179
               and nodes0.get(e["target"], {}).get("label")
               == "rrcdm_job_log_exec_par" for e in edges0)


def test_rrcdm_seed_keeps_its_three_edges():
    """`rrcdm ↓ EAST5` — the write-slot seed (the target column of the
    statement's own write) keeps all three edges: the write leg into the
    target table, the chip's TABLE_FLOW leg out of its statement trunk and
    the belongs-to SCHEMA edge."""
    _r, nodes, edges = _served(EAST5, "rrcdm_job_log_exec_par", "data_dt")
    assert len(edges) == 3, edges
    assert len(nodes) == 3, nodes
    assert {e["edge_type"] for e in edges} == {"DML", "TABLE_FLOW", "SCHEMA"} \
        or {e["edge_type"] for e in edges} == {"TABLE_FLOW", "SCHEMA"}, edges
    assert any(e.get("highlight_line") == 179 for e in edges)


# ═══════════════════════════════════════════════════════════════════════
# 5. FSC-1 — the owner-agnostic seed
# ═══════════════════════════════════════════════════════════════════════

# Three of the tpcds_qualified scripts that were 100% dead at L2 — every
# indexed (table, field) pair of the script returned `no_flow` — because
# their columns are bare (unqualified) inside multi-table FROMs and the
# extractor could attribute none of them. The seed is now the occurrence.
DEAD_SCRIPTS = [
    ("12.sql", "d", "d_date_sk"),
    ("13.sql", "a", "ca_address_sk"),
    ("32.sql", "all_sales", "i_manufact_id"),
]


@pytest.mark.parametrize("script,table,field", DEAD_SCRIPTS)
def test_fsc1_ownerless_seed(script, table, field):
    """A bare column with no model owner seeds the closure. Without the
    seed the pair is dead (the closure is empty → `no_flow`); with it the
    pair is searchable with an HONEST closure — the seed chip and its
    owner box, no padding."""
    sql = (TPCDS / script).read_text(encoding="utf-8")
    full_graph, _schemas, pm = _load_or_build_graph("v4fsc1", script, sql)
    full_graph = _drop_partition_ddl_frames(full_graph, sql)
    real = lineage._OWNERLESS_SEED
    try:
        lineage._OWNERLESS_SEED = False
        before = lineage.compute_field_flow(full_graph, table, field,
                                            physical_model=pm)
        lineage._OWNERLESS_SEED = True
        after = lineage.compute_field_flow(full_graph, table, field,
                                           physical_model=pm)
    finally:
        lineage._OWNERLESS_SEED = real
    assert not before, "the pair was expected to be dead without the seed"
    assert after, "the owner-agnostic seed must revive the pair"
    assert len(after) <= 6, (
        f"the revived closure is padded: {len(after)} nodes — the bare "
        f"column has no model chain, so the honest closure is the seed "
        f"chip and its box")
    # and the served L2 answers the search instead of `no_flow`
    result = _build_l2_graph("v4fsc1", script, sql, table, field, True,
                             "downstream")
    assert result.get("search_matched", True), (
        f"{script} {table}.{field} is still not searchable")
    assert result.get("nodes"), "the revived pair must serve nodes"


# ═══════════════════════════════════════════════════════════════════════
# 6. R46e — the casing-invariant closure
# ═══════════════════════════════════════════════════════════════════════

def test_casing_invariant_closure_h7_repro():
    """H7's repro: the served closure must not depend on the casing the
    caller typed. EAST5 spells its physical table 11x lowercase and 1x
    uppercase, and the walker had case-sensitive comparisons at exactly
    the sites that made `charge_department` diverge."""
    signatures = {}
    for table in ("bdm_acc_entrusted_payment", "BDM_ACC_ENTRUSTED_PAYMENT"):
        for field in ("charge_department", "CHARGE_DEPARTMENT"):
            _r, nodes, edges = _served(EAST5, table, field)
            signatures[(table, field)] = (
                frozenset(nodes),
                frozenset((e["source"], e["target"], e["edge_type"],
                           e.get("highlight_line")) for e in edges))
    assert len(set(signatures.values())) == 1, (
        f"the closure depends on the caller's casing: "
        f"{ {k: (len(v[0]), len(v[1])) for k, v in signatures.items()} }")
    # and a second seed, both directions of the casing pair
    sig2 = set()
    for table in ("east5_stzfxxb", "EAST5_STZFXXB"):
        for field in ("p_dt", "P_DT"):
            _r, nodes, edges = _served(EAST5, table, field)
            sig2.add((frozenset(nodes),
                      frozenset((e["source"], e["target"], e["edge_type"])
                                for e in edges)))
    assert len(sig2) == 1, "p_dt diverges across casings"


def test_folded_closure_is_a_superset_of_the_exact_closure():
    """The no-shrink tripwire: folding may only ever ADD. `_fold =
    identity` is exactly the pre-R46e engine (every comparison exact), so
    for an uppercase search — the case the old engine lost — the folded
    closure must contain everything the exact closure found."""
    for script, table, field in (
            (EAST5, "BDM_ACC_LOAN_INFO", "DATA_DT"),
            (EAST5, "EAST5_STZFXXB", "P_DT"),
            (SUP_M, "BDM_ACC_LOAN_INFO", "LENDING_REF"),
    ):
        folded = _closure(script, table, field, gate=True)
        exact = _closure(script, table, field, gate=True, fold=lambda s: s)
        assert exact <= folded, (
            f"{script} {table}.{field}: folding SHRANK the closure by "
            f"{len(exact - folded)} nodes")
        assert folded, "the folded closure must not be empty"


def test_l1_role_detection_is_case_insensitive():
    """`l1_builder.detect_role` (the live L1 path) folds both sides."""
    from app.services.l1_builder import detect_role
    analysis = {
        "nodes": [
            {"data": {"id": "v1", "label": "SC.CUSTOMER_ID",
                      "variable_type": "column",
                      "source_tables": ["STG_CUSTOMERS"],
                      "defined_in": "JOIN ON"}},
            {"data": {"id": "v2", "label": "stg_customers",
                      "variable_type": "table"}},
        ],
        "dependencies": [
            {"relationship": "DML", "source_id": "v1",
             "target_id": "v2"},
        ],
    }
    upper = detect_role(analysis, "STG_CUSTOMERS", "CUSTOMER_ID")
    lower = detect_role(analysis, "stg_customers", "customer_id")
    assert upper == lower, (upper, lower)
    assert upper, "the role read found nothing at all"


def test_l1_filter_is_case_insensitive():
    """`dataflow_service._filter_l1_by_lineage` folds the node's
    (table, field) against the search on both sides."""
    from app.services.dataflow_service import _filter_l1_by_lineage
    l1 = {
        "nodes": [
            {"data": {"id": "f1", "type": "field", "table_name": "STG_C",
                      "field_name": "CUSTOMER_ID", "parent": "t1"}},
            {"data": {"id": "t1", "type": "source_table"}},
        ],
        "edges": [],
        "lineage_field_pairs": {("stg_c", "customer_id")},
    }
    out = _filter_l1_by_lineage(l1, "STG_C", "CUSTOMER_ID")
    kept = {n["data"]["id"] for n in out["nodes"]}
    assert "f1" in kept, kept


# ═══════════════════════════════════════════════════════════════════════
# 7. L206 — the cross-check residual, adjudicated
# ═══════════════════════════════════════════════════════════════════════

def test_l206_join_predicate_residual():
    """ADJUDICATION (L206, in-passing): `p3.lending_ref@206` stays DARK.

    `ON p3.lending_ref = p1.lending_ref` (SUP_M TOP3, p3 =
    bdm_sys_acc_loan_info) is a join predicate on the field's NAME, not on
    the field's VALUE: the model carries `JOIN p3.lending_ref@206 →
    ⟐output@160`, but bdm_sys_acc_loan_info is not in the searched field's
    value chain — no value leg reaches it, it is never written, and the
    predicate's other side is the CTE projection (`p1`), not a chip. Under
    the R-GATE a JOIN leg is justified only by an admitted-chip endpoint
    or by an own-occurrence anchor line; `p3.lending_ref` is neither, so
    the R-GATE does NOT admit it and the residual is DOCUMENTED, pinned
    here so a later ruling starts from a failing test rather than from
    silence.

    Contrast: L201 (`p2.lending_ref = p1.lending_ref`) lights, because the
    p2 box (bdm_acc_loan_info_sup) IS in the value chain — it is written
    @160 and read @223 — so its same-name chip is admitted and the JOIN
    leg has an admitted-chip endpoint."""
    _r, nodes, edges = _served(SUP_M, "bdm_acc_loan_info", "lending_ref")
    l206 = [e for e in edges if e.get("highlight_line") == 206]
    assert not l206, (
        f"L206 is served — if a ruling admits the join partner, update "
        f"this pin and the canonical: {l206}")
    l201 = [e for e in edges if e.get("highlight_line") == 201]
    assert l201, "L201 (the value-chain join) must stay served"
    # the raw model DOES carry the L206 edge — the residual is the gate's
    # admission decision, not a missing fact.
    full_graph, pm = _model(SUP_M)
    raw_l206 = [E for E in pm.edges
                if E.edge_type == "JOIN" and E.highlight_line == 206]
    assert raw_l206, (
        "the raw model lost the L206 join edge — that would make the "
        "residual a model defect instead of an admission decision")
    assert any(pm.occurrence(E.source_id)
               and lineage._fold(lineage._occ_field_part(
                   pm.occurrence(E.source_id))) == "lending_ref"
               for E in raw_l206), raw_l206


# ═══════════════════════════════════════════════════════════════════════
# the gate is a monotone fixpoint, bounded by the walker's cap
# ═══════════════════════════════════════════════════════════════════════

def test_gate_is_idempotent_over_repeated_calls():
    """A second walk of the same (graph, table, field, direction) returns
    the same closure — the gate runs inside the walk, so a cached walker
    (the `_flow_memo` hit path) and a fresh walk must agree."""
    full_graph, pm = _model(SUP_M)
    a = lineage.compute_field_flow(full_graph, "bdm_acc_loan_info",
                                   "lending_ref", physical_model=pm)
    b = lineage.compute_field_flow(full_graph, "bdm_acc_loan_info",
                                   "lending_ref", physical_model=pm)
    assert a == b
