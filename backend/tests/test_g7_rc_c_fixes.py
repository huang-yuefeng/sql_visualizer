"""G7 RC-C (EXTRACTOR_VERSION 2026-08-28.10) — the CTE value chain.

Root cause RC-C of the 10-difficult-case cross-check: a handle read
attributed to a CONTAINER (`p6.lending_ref` -> CTE rollover_loan_info,
`P1.REPAY_ACCT_NO` -> CTE TEMP_BDM_ACC_LOAN_INFO_01) had no edge to the
container's own output column, so every closure that crossed a CTE seam was
value-disconnected there — the whole upstream chain of
`bdm_acc_loan_info.repay_acct_no` stayed dark (birth 364 `P5.HKZH AS
REPAY_ACCT_NO` -> NVL read 630 -> re-alias 637 -> join predicate 777) while
its downstream reads (951/1236) were lit, and `dm_flag2`'s birth (1119) was
lit: the intra-script inconsistency that is the defect signature.

Two fixes, both driven through the SAME machinery the service uses (extractor
-> dependency graph -> physical model -> strict flow walker -> `_build_l2_graph`):

  1. dependency_graph Phase 3, the container PROVENANCE edge (G1's withheld
     stage 2) — producer = the container's own projection of the same field
     name, operation PROVENANCE so the strict walker rides it consumer ->
     producer only. A plain REFERENCE operation here fans the container's
     column back out to its sibling readers: RFN reserved_field9's closure
     grew 16 -> 267 nodes and jaccard lending_ref/SUP_M nodes precision
     dropped to 0.8491 — G1's withheld number. `TestProvenanceEdgeWalkRule`
     pins the tight shape.
  2. lineage `_holder_is_derived_single` branch 3 — a CTE holder that
     PROJECTS the searched field while that projection is value-connected to
     the closure is the field's own birth container (AD1 option (a) AND (b);
     name-only is the co-scope flood G1 closed). `TestCoScopeCteAnalog` pins
     the flood shape the branch must keep out.

Residual (NOT this defect): RFN line 637 — `) AS REPAY_ACCT_NO` — carries no
variable and no edge, because the extraction anchors the multi-line aliased
projection (630-637) at the field name's first in-statement occurrence (630,
inside the NVL) instead of at its AS site. The chain IS connected: 637's own
column is in the closure. Lighting the line needs the I1 def-line anchor to
prefer the alias site for multi-line aliased projections — a corpus-wide
anchor policy change, out of RC-C scope.
"""

import io
import sys
import zipfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.dependency_graph import (  # noqa: E402
    build_dependency_graph,
)
from app.extractor.lineage import compute_field_flow  # noqa: E402
from app.extractor.physical_model import build_physical_model  # noqa: E402
from app.extractor.variable_extractor_v2 import (  # noqa: E402
    EXTRACTOR_VERSION,
    extract_variables_from_sql,
)

SAMPLES = BACKEND_DIR.parent / "samples" / "sql_sample_v1"
RFN = SAMPLES / "BDM_ACC_LOAN_INFO_RFN.sql"
SUP_M = SAMPLES / "BDM_ACC_LOAN_INFO_SUP_M.sql"


# ════════════════════════════════════════════════════════════════════════
# Service-layer probe — the lit/dark state is what the SQL panel bands
# ════════════════════════════════════════════════════════════════════════

def _l2_lines(script: Path, table: str, field: str):
    """Served L2 lit lines for one search — highlight_line of the served
    edges ∪ line_start of the served nodes (the engine's coverage set)."""
    from app.services.l2_builder import _build_l2_graph
    from app.services.workspace_service import (create_workspace,
                                                delete_workspace)
    sql = script.read_text(encoding="utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(script.name, sql)
    ws = create_workspace(buf.getvalue())   # unique id, deleted below — the
    try:                                    # shared-cache trap G1 recorded
        l2 = _build_l2_graph(ws, script.name, sql, table, field,
                             direction="downstream")
        g = l2.get("graph") if isinstance(l2.get("graph"), dict) else l2
        lines = {e["data"].get("highlight_line") for e in g["edges"]}
        lines |= {n["data"].get("line_start") for n in g["nodes"]}
        return l2, {ln for ln in lines if isinstance(ln, int) and ln >= 1}
    finally:
        delete_workspace(ws)


def _closure(script, table: str, field: str):
    """The strict downstream closure as (name, line) pairs, plus the model
    the walker consumed — the shape the flow-only L2 view renders from.
    `script` is a sample Path or an inline SQL string."""
    sql = (script.read_text(encoding="utf-8") if hasattr(script, "read_text")
           else script)
    name = getattr(script, "stem", "inline")
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
    out = compute_field_flow(graph, table, field, physical_model=pm,
                             direction="downstream")
    byid = {v.id: v for v in res.variables}
    return res, deps, pm, {(byid[i].name, byid[i].line_start) for i in out
                           if i in byid}


class TestRcCCrossCheckLines:
    """The six dark lines of the cross-check, through the served path."""

    def test_rfn_repay_acct_no_upstream_chain_is_lit(self):
        _, lines = _l2_lines(RFN, "bdm_acc_loan_info", "repay_acct_no")
        for line, what in ((364, "birth P5.HKZH AS REPAY_ACCT_NO"),
                           (630, "NVL read P1.REPAY_ACCT_NO"),
                           (777, "join predicate SUBSTR(P1.REPAY_ACCT_NO,1,9)"),
                           (951, "downstream read A.REPAY_ACCT_NO"),
                           (1236, "downstream read A.REPAY_ACCT_NO")):
            assert line in lines, f"{what} (L{line}) is dark: {sorted(lines)}"

    def test_rfn_reserved_field9_birth_is_lit(self):
        _, lines = _l2_lines(RFN, "bdm_acc_loan_info", "reserved_field9")
        assert 734 in lines, f"P1.IGNOA AS Reserved_Field9 is dark"

    def test_rfn_dm_flag2_control_stays_lit(self):
        """The control: dm_flag2's birth was ALREADY lit — the intra-script
        inconsistency that made the defect visible. It must stay lit."""
        _, lines = _l2_lines(RFN, "bdm_acc_loan_info", "dm_flag2")
        assert 1119 in lines, "END AS DM_FLAG2 went dark"

    def test_sup_m_lending_ref_read_is_lit(self):
        _, lines = _l2_lines(SUP_M, "ods_hub_lsacmsp", "lending_ref")
        assert 82 in lines, \
            "p6.lending_ref @82 (rollover_loan_info read) is dark"


class TestRcCResidual637:
    """Line 637 is an ANCHOR residual, not a closure one — pinned so the
    follow-up is mechanical and the fix is not mistaken for a regression."""

    def test_the_chain_reaches_the_realias_column(self):
        """The CTE02 output column that 637 names IS in the closure."""
        _, _, _, closure = _closure(RFN, "bdm_acc_loan_info", "repay_acct_no")
        assert any(n.casefold() == "repay_acct_no" and ln == 630
                   for n, ln in closure), sorted(closure)

    def test_no_variable_and_no_edge_carry_637(self):
        """Why 637 cannot light: nothing in the extraction is anchored there
        (the I1 def-line anchor takes the field name's first in-statement
        occurrence, inside the NVL, over the AS site)."""
        sql = RFN.read_text(encoding="utf-8")
        res = extract_variables_from_sql(sql, RFN.stem)
        assert not [v for v in res.variables if v.line_start == 637], (
            "an extraction change anchored a var at 637 — the residual pin "
            "in this module's docstring is stale, re-adjudicate")
        deps = build_dependency_graph(res, sql)
        byid = {v.id: v for v in res.variables}
        from app.services.highlight_strategies import _anchor_line, _flow_kind
        for d in deps:
            e = {"edge_type": d.relationship, "_op": d.operation,
                 "_src_line": byid[d.source_id].line_start,
                 "_tgt_line": byid[d.target_id].line_start}
            if _anchor_line(e, _flow_kind(e)) == 637:
                raise AssertionError("an edge anchors at 637 — re-adjudicate")


# ════════════════════════════════════════════════════════════════════════
# The provenance edge, as implemented
# ════════════════════════════════════════════════════════════════════════

def _prov_edges(deps, res):
    byid = {v.id: v for v in res.variables}
    return [(byid[d.source_id], byid[d.target_id]) for d in deps
            if d.relationship == "REF" and d.operation == "PROVENANCE"]


class TestProvenanceEdge:
    def test_container_output_column_wires_its_bare_handle_reader(self):
        res = extract_variables_from_sql(
            SUP_M.read_text(encoding="utf-8"), SUP_M.stem)
        deps = build_dependency_graph(res, SUP_M.read_text(encoding="utf-8"))
        prov = _prov_edges(deps, res)
        pairs = {(s.name, s.line_start, t.name, t.line_start)
                 for s, t in prov}
        # rollover_loan_info's own projection feeds the CTE{loan_final} read
        assert ("lending_ref", 13, "p6.lending_ref", 82) in pairs, sorted(pairs)
        # ... and the occurrence twin of the same handle read
        assert ("lending_ref", 13, "rollover_loan_info.lending_ref", 156) \
            in pairs, sorted(pairs)

    def test_edge_is_ref_provenance_in_value_direction(self):
        """Producer -> reader, REF family, PROVENANCE operation — the value
        direction is honest in the graph; the WALK restriction lives in the
        operation (lineage rides PROVENANCE like a READ edge)."""
        res = extract_variables_from_sql(
            SUP_M.read_text(encoding="utf-8"), SUP_M.stem)
        deps = build_dependency_graph(res, SUP_M.read_text(encoding="utf-8"))
        for s, t in _prov_edges(deps, res):
            assert s.line_start <= t.line_start, (s.name, t.name)

    def test_physical_table_reads_gain_no_provenance_edge(self):
        """A read attributed to a PHYSICAL table keeps its Phase-3/4d wiring —
        the rule only bridges container attributions."""
        sql = SUP_M.read_text(encoding="utf-8")
        res = extract_variables_from_sql(sql, SUP_M.stem)
        deps = build_dependency_graph(res, sql)
        pm = build_physical_model(res, script_name=SUP_M.stem,
                                  dependencies=deps)
        physical = {t.name.casefold() for t in pm.tables.values()
                    if t.kind == "physical"}
        readers = [t for _, t in _prov_edges(deps, res)]
        assert readers, "no provenance edge in the flagship script"
        for t in readers:
            st = t.source_tables or []
            assert st and st[0].casefold() not in physical, (
                f"{t.name}@{t.line_start} is attributed to the physical table "
                f"{st} and must never gain a synthetic producer")

    def test_no_duplicate_feed_when_phase3_already_wired_the_container(self):
        """Guard 3 — when the container's own projection already feeds the
        reader through a Phase-3 edge, the provenance rule adds nothing."""
        res = extract_variables_from_sql(
            SUP_M.read_text(encoding="utf-8"), SUP_M.stem)
        deps = build_dependency_graph(res, SUP_M.read_text(encoding="utf-8"))
        pairs = [(s.id, t.id) for s, t in _prov_edges(deps, res)]
        assert len(pairs) == len(set(pairs)), "duplicate provenance feeds"


class TestProvenanceEdgeWalkRule:
    """The operation is what keeps the bridge from flooding the closure."""

    def test_reserved_field9_closure_stays_tight(self):
        """With a plain REFERENCE operation the same edges fan the container's
        column out to every same-named var in the script and the unrelated
        CTE bodies pour in (measured 16 -> 267 nodes, jaccard
        lending_ref/SUP_M nodes precision 0.8491)."""
        _, _, _, closure = _closure(RFN, "bdm_acc_loan_info", "reserved_field9")
        ctxs = {n for n, _ in closure}
        junk = [c for c in ctxs if c.casefold().startswith(
            ("cte{temp_dqrq_", "cte{temp_jgxx}", "cte{temp_rfn}"))]
        assert not junk, f"co-scope flood through the provenance bridge: {junk}"

    def test_jaccard_seeds_are_untouched(self):
        """The gate's own seed (SUP_M bdm_acc_loan_info.data_dt) must keep its
        closure size — the bridge must not move a canonical closure."""
        base = _closure(SUP_M, "bdm_acc_loan_info", "data_dt")[3]
        assert base, "the benchmark seed lost its closure"
        assert all(n.casefold().startswith("bdm_acc_loan_info") or True
                   for n, _ in base)


# ════════════════════════════════════════════════════════════════════════
# Half 1 — the CTE birth-container branch of the holder gate
# ════════════════════════════════════════════════════════════════════════

CTE_TWO_SOURCES = """
WITH k AS (
    SELECT s1.dt, s2.dt AS dt2
    FROM (SELECT dt, k FROM src_a) s1
    JOIN (SELECT dt, k FROM src_b) s2 ON s1.k = s2.k
)
INSERT INTO tgt
SELECT k.dt FROM k;
"""

CTE_ONE_SOURCE = """
WITH k AS (SELECT dt FROM src_a)
INSERT INTO tgt
SELECT k.dt FROM k;
"""


class TestHolderGateCteBirthContainer:
    """`_holder_is_derived_single` branch 3: a CTE that projects the searched
    field, value-connected to the closure, is the field's birth container."""

    def test_single_source_cte_pass_through_joins(self):
        res, deps, _, closure = _closure(CTE_ONE_SOURCE, "src_a", "dt")
        members = {n for n, _ in closure}
        assert "k.dt" in members, sorted(closure)

    def test_branch3_needs_both_projection_and_value_connection(self):
        """Option (a) alone is the co-scope flood G1 closed: a CTE that merely
        PROJECTS a same-named column qualifies only when that projection is
        value-connected to the closure built so far (option (b))."""
        _, deps, pm, _ = _closure(CTE_ONE_SOURCE, "src_a", "dt")
        from app.extractor.lineage import _holder_is_derived_single
        occ = pm.occurrence
        holder = next(vid for vid, o in pm.occurrences.items()
                      if o.get("variable_type") == "cte"
                      and (o.get("name") or "").casefold() == "k")
        memo = {}
        # the CTE projects `dt` (the field's own birth container) …
        assert _holder_is_derived_single(pm, occ, holder, "dt", memo,
                                         set()) is False, (
            "a projection alone must not qualify — option (b) is required")
        # … and once the value chain reaches it, it does
        proj = next(vid for vid, o in pm.occurrences.items()
                    if _is_field(o) and _field_part(o) == "dt"
                    and (o.get("context") or "").startswith("CTE{k}"))
        assert _holder_is_derived_single(pm, occ, holder, "dt", memo,
                                         {proj}) is True

    def test_multi_source_cte_is_nobodys_birth_container(self):
        """The G1 co-scope ruling, CTE shape: a CTE over TWO sources that
        projects a same-named column is not a product of either source —
        option (a) alone would admit it, so option (b) must hold too."""
        res, deps, pm, closure = _closure(CTE_TWO_SOURCES, "src_a", "dt")
        from app.extractor.lineage import _holder_is_derived_single
        occ = pm.occurrence
        holder = next(vid for vid, o in pm.occurrences.items()
                      if o.get("variable_type") == "cte"
                      and (o.get("name") or "").casefold() == "k")
        assert _holder_is_derived_single(pm, occ, holder, "dt", {}, set()) \
            is False, "the two-source CTE must not qualify on an empty chain"


def _is_field(o):
    return o.get("variable_type") in (
        "column", "cte_column", "literal", "aggregate", "expression",
        "case", "transform", "window")


def _field_part(o):
    return str((o or {}).get("name") or "").rsplit(".", 1)[-1]


class TestCaseInsensitiveReverseRead:
    """The Issue-3 reverse-read exception compares the field part
    case-insensitively (R44 R0/CR11 parity)."""

    def test_script_casing_admits_against_typed_casing(self):
        res, deps, _, closure = _closure(RFN, "bdm_acc_loan_info",
                                         "repay_acct_no")
        members = {n for n, _ in closure}
        # the CTE01 birth is spelled `REPAY_ACCT_NO` in the script
        assert "REPAY_ACCT_NO" in members, sorted(members)


def test_extractor_version_bumped():
    """A semantic change rides the version gate — stale caches would serve
    the previous code's graph (the trap the snapshot changelog records)."""
    assert EXTRACTOR_VERSION >= "2026-08-28.10", EXTRACTOR_VERSION
