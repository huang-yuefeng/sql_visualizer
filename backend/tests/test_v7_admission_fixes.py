"""Team V7 — the two opposite-direction admission failures of the walker
region (v3.3.195 tree), both fixed inside the R-GATE
(`lineage._value_cone_gate`) and both reproducible in isolation.

Fix 1 — OVER-INCLUSION (the G1 adjudicated residual, retired).  A same-name
    REFERENCE edge between two field chips on DIFFERENT owner entities is the
    extractor's co-scope wiring (`build_dependency_graph` Phase 3: the
    last-writer-wins `full_col_index` pick and its bare-name fallback), not a
    value fact — the two endpoints are different FIELDS.  Read as a PRODUCER
    claim ("the searched field's value comes from that foreign same-named
    column") it is false by construction, yet the cone crossed it twice: rule
    4 admitted the foreign chip as the seed's producer, and rule 6 then
    admitted the foreign chip's BOX, where rule 2 swept the chip in anyway.
    Both crossings are gated (`_PHANTOM_COPY_GATE`), so src_b's `dt` no
    longer joins src_a.dt's closure.  USER RULE: "only the field involved
    into the data flow is shown".

Fix 2 — OVER-FILTERING (the D2 write→read reader).  A WRITE_READ edge is the
    READER statement's only leg and carries no write of its own, so no
    clause of `_leg_justified_b` justified it: rule 6 could not admit the
    reader box the closure fixpoint had already admitted, and the reader that
    references the searched field fell out of the served closure.  The
    reader-statement clause now mirrors the walker's own forward WRITE_READ
    admit (`_tf in _stmt_field_parts`), so a reader that consumes the field
    joins and a reader that never touches it stays out.

Blast radius (measured, `test_flagship_closures_are_unchanged`): the
flagship corpus is UNCHANGED by the two switches — no canonical closure
shrinks (the jaccard benchmark stays 1.0000/1.0000 on all 20 cases) and none
grows.  In-test that is pinned as a full physical-pair sweep of EAST5; the
landing report measured the same equality over all five flagships' 1277
physical pairs and over the 108-script L2 snapshot corpus (41 expected-RED
snapshots before and after — no new shift).  Every before/after assertion
here flips the gate's OWN switches (the switch IS the feature, mirror of
`_VALUE_CONE_GATE`), so the "before" side is the real previous engine, never
a re-implementation.
"""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.extractor import lineage  # noqa: E402
from app.extractor.dependency_graph import build_dependency_graph  # noqa: E402
from app.extractor.physical_model import build_physical_model  # noqa: E402
from app.extractor.variable_extractor_v2 import (  # noqa: E402
    extract_variables_from_sql,
)
from app.services.l2_builder import _load_or_build_graph  # noqa: E402

SAMPLES = BACKEND_DIR.parent / "samples" / "sql_sample_v1"

EAST5 = "EAST5_STZFXXB_M.sql"
SUP_M = "BDM_ACC_LOAN_INFO_SUP_M.sql"
PL = "BDM_ACC_LOAN_INFO_PL.sql"
DL = "BDM_ACC_LOAN_INFO_Digitallending.sql"
RFN = "BDM_ACC_LOAN_INFO_RFN.sql"

# G1's adjudicated two-source fixture (team V3's file owns the original
# repro; this copy is the switchable before/after pin).
SRC_A_SRC_B = """
INSERT INTO tgt
SELECT k.dt
FROM (
    SELECT s1.dt, s2.dt AS dt2
    FROM (SELECT dt, k FROM src_a) s1
    JOIN (SELECT dt, k FROM src_b) s2 ON s1.k = s2.k
) k;
"""

# The D2 write→read shape: stmt 0 writes x into `writer`; stmt 1 reads it
# (`WRITE_READ`).  Whether the READER box joins is what the two D2 tests pin.
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


# ── harness ─────────────────────────────────────────────────────────────

def _build_sql(sql, name="v7probe"):
    """extractor → dependency graph → physical model → walker graph.  The
    same chain the service runs (keyword-correct `build_physical_model`
    call — the positional trap V3 repaired in test_g1_adjudicated_fixes)."""
    res = extract_variables_from_sql(sql, name)
    deps = build_dependency_graph(res, sql)
    pm = build_physical_model(res, script_name=name, dependencies=deps)
    graph = {
        "nodes": [{"data": {"id": v.id, "label": v.name}}
                  for v in res.variables],
        "edges": [{"data": {"source": d.source_id, "target": d.target_id,
                            "edge_type": d.relationship,
                            "operation": d.operation,
                            "containment": d.containment}} for d in deps],
    }
    return res, deps, pm, graph


def _closure(graph, pm, table, field, phantom=True, derived=True):
    """The strict downstream closure with the two V7 switches set."""
    real = (lineage._PHANTOM_COPY_GATE, lineage._DERIVED_CONTAINER_CHIPS)
    lineage._PHANTOM_COPY_GATE = phantom
    lineage._DERIVED_CONTAINER_CHIPS = derived
    try:
        return lineage.compute_field_flow(graph, table, field,
                                          physical_model=pm,
                                          direction="downstream")
    finally:
        lineage._PHANTOM_COPY_GATE, lineage._DERIVED_CONTAINER_CHIPS = real


def _closure_sql(sql, table, field):
    res, _deps, pm, graph = _build_sql(sql)
    out = _closure(graph, pm, table, field)
    byid = {v.id: v for v in res.variables}
    return pm, {(byid[i].name, byid[i].line_start) for i in out if i in byid}


def _synth(nodes, edges):
    """A physical model straight from a raw graph dict (the D2 harness)."""
    g = {"nodes": nodes, "edges": edges}
    return g, build_physical_model(g)


def _model(script):
    """(full_graph, physical_model) on the SERVED model — the graph-cache
    path `_build_l2_graph` itself uses, never a second extraction."""
    sql = (SAMPLES / script).read_text(encoding="utf-8")
    full_graph, _schemas, pm = _load_or_build_graph("v7", script, sql)
    return full_graph, pm


# ── Fix 1: the cross-owner same-name producer is not admitted ───────────

class TestCrossOwnerSameNameProducer:
    """`src_b.dt` is a DIFFERENT field (same name, other table): its flow
    must not appear in `src_a.dt`'s closure."""

    def test_foreign_same_name_field_is_excluded(self):
        pm, closure = _closure_sql(SRC_A_SRC_B, "src_a", "dt")
        # the searched side keeps its own occurrences
        assert {("dt", 6), ("s1", 6), ("src_a", 6)} <= closure, closure
        # the container's output column still arrives by value
        assert ("k.dt", 3) in closure, closure
        assert not any(n == "k" for n, _ in closure), closure
        # THE FIX: src_b's same-named `dt` — chip, table handle and trunk
        assert ("dt", 7) not in closure, closure
        assert ("src_b", 7) not in closure, closure
        assert ("⟐ s2", 7) not in closure, closure

    def test_extraction_fact_is_untouched(self):
        """The exclusion is a WALKER decision: the co-scope REFERENCE edge
        is still in the dependency graph (V3's residual note stays true)."""
        res, deps, _pm, _graph = _build_sql(SRC_A_SRC_B)
        _id = {v.id: (v.name, v.line_start) for v in res.variables}
        phantom = [d for d in deps
                   if d.relationship == "REF"
                   and d.operation == "REFERENCE"
                   and _id.get(d.source_id) == ("dt", 7)
                   and _id.get(d.target_id) == ("dt", 6)]
        assert phantom, "the extractor's same-name REFERENCE edge vanished"

    def test_switch_off_restores_the_over_inclusion(self):
        """Before/after: `_PHANTOM_COPY_GATE = False` is the previous
        engine, and it is the one that admitted the foreign field."""
        res, _deps, pm, graph = _build_sql(SRC_A_SRC_B)
        byid = {v.id: v for v in res.variables}
        names = lambda cl: {(byid[i].name, byid[i].line_start)
                            for i in cl if i in byid}
        after = names(_closure(graph, pm, "src_a", "dt", phantom=True))
        before = names(_closure(graph, pm, "src_a", "dt", phantom=False))
        assert after <= before, (before, after)
        assert ("dt", 7) in before and ("dt", 7) not in after
        assert ("src_b", 7) in before and ("src_b", 7) not in after

    def test_same_owner_same_name_copy_still_traverses(self):
        """The P1 MOVE→COPY convention is untouched: two same-named chips on
        ONE owner entity are that entity's own columns — the copy joins."""
        nodes = [
            {"id": "s", "label": "src", "variable_type": "table",
             "table_name": "src", "context": "TOP0",
             "source_tables": ["src"]},
            {"id": "x1", "label": "x", "variable_type": "column",
             "context": "TOP0", "source_tables": ["src"]},
            {"id": "x2", "label": "x", "variable_type": "column",
             "context": "TOP0", "source_tables": ["src"]},
            {"id": "o", "label": "out", "variable_type": "table",
             "table_name": "out", "context": "TOP0",
             "source_tables": ["out"]},
        ]
        edges = [
            {"source": "x1", "target": "s", "edge_type": "REF"},
            {"source": "x2", "target": "s", "edge_type": "REF"},
            {"source": "x1", "target": "x2", "edge_type": "REF",
             "operation": "REFERENCE"},
            {"source": "x1", "target": "o", "edge_type": "DML",
             "operation": "INSERT"},
        ]
        g, pm = _synth(nodes, edges)
        cl = _closure(g, pm, "src", "x")
        assert {"x1", "x2"} <= cl, cl

    def test_consumer_direction_still_traverses(self):
        """The CONSUMER half of a cross-owner same-name REFERENCE is the
        searched field's own value flow and keeps crossing: this is exactly
        the canonical lending_ref↓SUP_M shape (`DISTINCT lending_ref`@50 in
        the NOT-IN subquery, reached from the rollover chip@22), which the
        jaccard canonical realises as rows LFS39/LFS104."""
        full_graph, pm = _model(SUP_M)
        cl = _closure(full_graph, pm, "bdm_acc_loan_info", "lending_ref")
        occ = pm.occurrence
        at50 = [v for v in cl
                if (occ(v) or {}).get("name") == "lending_ref"
                and (occ(v) or {}).get("line_start") == 50]
        assert at50, "the NOT-IN subquery's lending_ref@50 dropped"
        tables = {(occ(v) or {}).get("name") for v in cl}
        assert "bdm_evt_loan_trans" in tables, sorted(tables)[:12]


# ── Fix 1 (half 2): the derived container that DOES deliver the value ───

class TestDerivedContainerChips:
    """`_DERIVED_CONTAINER_CHIPS`: a visited chip carrying the searched
    field part whose OWNER entity is a subquery/VT container that delivers
    the SEARCHED table's value is an occurrence of the searched field — so
    the chip AND the alias handle that names it stay served."""

    def test_derived_container_projection_and_alias_join(self):
        pm, closure = _closure_sql(SRC_A_SRC_B, "src_a", "dt")
        # the container's projection read and the alias handle naming it
        assert ("s1.dt", 5) in closure, closure
        assert ("s1", 6) in closure, closure

    def test_switch_off_drops_both(self):
        res, _deps, pm, graph = _build_sql(SRC_A_SRC_B)
        byid = {v.id: v for v in res.variables}
        names = lambda cl: {(byid[i].name, byid[i].line_start)
                            for i in cl if i in byid}
        on = names(_closure(graph, pm, "src_a", "dt", derived=True))
        off = names(_closure(graph, pm, "src_a", "dt", derived=False))
        assert ("s1", 6) in on and ("s1", 6) not in off, (on, off)
        assert ("s1.dt", 5) in on and ("s1.dt", 5) not in off, (on, off)

    def test_two_source_container_still_lends_nothing(self):
        """A container over TWO sources never qualifies — the s2 half of G1
        (`_holder_is_derived_single` counts src_b, not src_a), so the
        ambiguous projection read and the s2 alias handle stay out."""
        pm, closure = _closure_sql(SRC_A_SRC_B, "src_a", "dt")
        assert ("s2.dt", 5) not in closure, closure
        assert ("s2", 7) not in closure, closure
        assert ("dt2", 5) not in closure, closure


# ── Fix 2: the WRITE_READ reader joins when it references the field ─────

class TestWriteReadReader:
    """D2's write→read link is the reader statement's only leg; the gate
    needs a clause for it or the reader box falls out of the closure."""

    def test_reader_referencing_the_field_joins(self):
        g, pm = _synth(
            _WR_READ_BASE["nodes"] + [
                {"id": "xr", "label": "x", "variable_type": "column",
                 "context": "TOP1", "source_tables": ["reader"]}],
            _WR_READ_BASE["edges"] + [
                {"source": "xr", "target": "r1", "edge_type": "REF"}])
        cl = _closure(g, pm, "writer", "x")
        assert "r1" in cl, "reader box must join the closure"
        assert "xr" in cl, "the reader's own chip must join with its box"

    def test_reader_not_referencing_the_field_stays_out(self):
        g, pm = _synth(
            _WR_READ_BASE["nodes"] + [
                {"id": "e1", "label": "e", "variable_type": "column",
                 "context": "TOP1", "source_tables": ["reader"]}],
            _WR_READ_BASE["edges"] + [
                {"source": "e1", "target": "r1", "edge_type": "REF"}])
        cl = _closure(g, pm, "writer", "x")
        assert "r1" not in cl, "an unrelated reader must not join"
        assert "e1" not in cl, cl

    def test_clause_is_the_leg_justification_not_a_blanket_admit(self):
        """The reader joins BECAUSE its statement references the field: with
        the reader's column renamed, the very same WRITE_READ leg admits
        nothing — the clause mirrors the walker's own forward admit."""
        g, pm = _synth(
            _WR_READ_BASE["nodes"] + [
                {"id": "xr", "label": "x", "variable_type": "column",
                 "context": "TOP1", "source_tables": ["reader"]}],
            _WR_READ_BASE["edges"] + [
                {"source": "xr", "target": "r1", "edge_type": "REF"}])
        assert "r1" in _closure(g, pm, "writer", "x")
        # ... and the same fixture searched for a field the reader never
        # touches admits no reader box at all
        assert "r1" not in _closure(g, pm, "writer", "zzz")


# ── blast radius: the flagship corpus is unchanged ──────────────────────

def _pairs(pm):
    return [(t.name, fn) for t in pm.tables.values()
            if t.kind == "physical" for fn in t.fields]


def test_flagship_closures_are_unchanged():
    """No canonical closure shrinks AND none grows: for every physical pair
    of EAST5 the served closure with the two V7 switches on is IDENTICAL to
    the pre-V7 closure (both switches off).  The flagship corpus has no
    cross-owner same-name producer and no qualified derived container, so
    the two fixes must be invisible here — measured, not assumed."""
    full_graph, pm = _model(EAST5)
    checked = 0
    for table, field in _pairs(pm):
        before = _closure(full_graph, pm, table, field,
                          phantom=False, derived=False)
        after = _closure(full_graph, pm, table, field)
        assert after == before, (
            f"{table}.{field}: the V7 switches changed the closure "
            f"(+{sorted(set(after) - set(before))[:4]} / "
            f"-{sorted(set(before) - set(after))[:4]})")
        checked += 1
    assert checked >= 100, f"only {checked} pairs exercised"


@pytest.mark.parametrize("script,seed", [
    (EAST5, ("bdm_acc_loan_info", "data_dt")),
    (PL, ("bdm_acc_loan_info", "data_dt")),
    (SUP_M, ("bdm_acc_loan_info", "lending_ref")),
    (DL, ("bdm_acc_loan_info", "data_dt")),
    (RFN, ("bdm_acc_loan_info", "repay_acct_no")),
])
def test_flagship_own_occurrence_floors_hold(script, seed):
    """The RECALL GUARD's property, re-measured on this tree: the served
    closure anchors 100% of the searched field's own occurrence lines (V4's
    own-occurrence floor, 1.0 everywhere)."""
    full_graph, pm = _model(script)
    table, field = seed
    own = {}
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
                    own.setdefault(o["line_start"], set()).add(vid)
    assert own, f"no own occurrences found for {script} {table}.{field}"
    cl = _closure(full_graph, pm, table, field)
    own_chips = {v for vids in own.values() for v in vids}
    covered = {ln for ln, vids in own.items() if vids & cl}
    for e in pm.edges:
        if e.containment or not e.highlight_line:
            continue
        if e.source_id in cl and e.target_id in cl and (
                e.source_id in own_chips or e.target_id in own_chips):
            covered.add(e.highlight_line)
    share = len(covered) / len(own)
    assert share >= 1.0, (
        f"{script} {table}.{field}: own-occurrence anchor coverage "
        f"{len(covered)}/{len(own)} = {share:.4f}; missing "
        f"{sorted(set(own) - covered)[:8]}")
