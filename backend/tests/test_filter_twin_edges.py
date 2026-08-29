"""F-E1 (R45, 2026-08-28) — filter-predicate occurrence twins carry an
own-line flow edge.

Defect (simulation class 2, "filter-predicate lines unreachable"): the
extractor's family-3 occurrence twins mint at the right LINE, but
dependency_graph emitted no edge anchored AT that line, so the line never
entered the flow-only closure:

* BDM_ACC_LOAN_INFO_SUP_M.sql L37 / L113 — `AND podtao <> pofddt`, the
  live FILTER predicate in two parallel derived-body copies (the twins are
  `ods_hub_lsacmsp.podtao` in CTE{rollover_loan_info}/subq1/subq:join:p2
  and CTE{loan_final}:join:p2).
* BDM_ACC_LOAN_INFO_RFN.sql — the `p_dt` predicate lines of the
  `MAX(p_dt)` scalar subquery (L827 outer `P_dt = (SELECT`, L831 inner
  `p_dt <= TO_DATE(...)`), target `ods_cdp_gdc_table_coa_list.p_dt`.

Why the edges were missing (traced end-to-end on SUP_M, twin
`ods_hub_lsacmsp.podtao`@L37):

1. `_add` records a collapsed occurrence in WALK order (the JOIN-key
   operand pass runs before the WHERE pass) while `_occurrence_lines`
   hands out the twin LINES in textual order — so inside one twin group
   the (line, clause) pairing is crossed: the L37 twin carries the
   join-key collapse's "SELECT expr" and the L41 twin carries "WHERE".
2. The twin's own edges could not surface its line anyway:
   * the belongs-to SCHEMA edge (Phase 4a / 4d-gb) anchors at the MEMBER
     (kind "structure" → the member's line) but folds in the L2
     line-merged pass — one edge per (source, target, edge_type), first
     carrier wins, and an earlier var of the same field node already
     holds the pair;
   * the Phase-4d REF/READ anchors at the READ target's line (kind
     "read" → the alias/FROM line), i.e. the owner table's line, never
     the twin's.
3. The only own-line-anchored edge a field occurrence can carry is the
   predicate edge to its scope's ⟐ output anchor (Phase 6/6b: kind
   "field flow" → the SOURCE's line) — and Phase 6's
   `_clause_of(defined_in) in {"WHERE", "HAVING", "QUALIFY"}` gate
   rejected the crossed twin.

Fix: Phase 6/6b admit an occurrence twin whose GROUP (same context +
casefolded `owner.field` — never a bare-column match) collected a
predicate/JOIN collapse. The group's clause MULTISET is a fact of the
SQL; only the per-line pairing is not. Grouping is owner-scoped, so a
DIFFERENT table's same-named field (the DigL `D.DATA_DT` hazard) can
never lend its clause — pinned by `TestTwinGroupOwnerGuard`.
"""

import io
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.dependency_graph import (  # noqa: E402
    _OCCURRENCE_PREFIX,
    _clause_of,
    build_dependency_graph,
)
from app.extractor.variable_extractor_v2 import (  # noqa: E402
    ExtractionResult,
    extract_variables_from_sql,
)
from app.models.variable import VariableDefinition, VariableType  # noqa: E402

SAMPLES_DIR = BACKEND_DIR.parent / "samples" / "sql_sample_v1"
SUP_M = SAMPLES_DIR / "BDM_ACC_LOAN_INFO_SUP_M.sql"
RFN = SAMPLES_DIR / "BDM_ACC_LOAN_INFO_RFN.sql"
DIGL = SAMPLES_DIR / "BDM_ACC_LOAN_INFO_Digitallending.sql"

FILTER_CLAUSES = {"WHERE", "HAVING", "QUALIFY"}
JOIN_CLAUSES = {"JOIN ON"}


def _extract(path: Path, name: str):
    sql = path.read_text(encoding="utf-8")
    res = extract_variables_from_sql(sql, name)
    deps = build_dependency_graph(res, sql)
    return res, deps


def _twins(res, name: str, line: int) -> list:
    """The family-3 occurrence twins named `name` at `line`."""
    return [v for v in res.variables
            if v.name == name and v.line_start == line
            and (v.defined_in or "").upper().startswith(_OCCURRENCE_PREFIX)]


def _out_edges(deps, var_id: str, rel: str) -> list:
    return [d for d in deps
            if d.source_id == var_id and d.relationship == rel]


def _var(res, var_id: str):
    return next(v for v in res.variables if v.id == var_id)


def _twin_group_clauses(res) -> dict:
    """(context, casefolded owner.field) → the clauses its twins carry."""
    groups = defaultdict(set)
    for v in res.variables:
        di = (v.defined_in or "").strip().upper()
        if not di.startswith(_OCCURRENCE_PREFIX):
            continue
        if v.variable_type != VariableType.COLUMN or not v.source_tables:
            continue
        groups[(v.context or "TOP", v.name.casefold())].add(
            di[len(_OCCURRENCE_PREFIX):].strip())
    return groups


class TestSupMPredicateTwins:
    """SUP_M L37 / L113 — `AND podtao <> pofddt` in two parallel copies."""

    def test_predicate_line_twins_carry_own_line_filter_edge(self):
        res, deps = _extract(SUP_M, "BDM_ACC_LOAN_INFO_SUP_M")
        for ctx_tail, line in (("rollover_loan_info}/subq1/subq:join:p2", 37),
                               ("loan_final}:join:p2", 113)):
            twins = [v for v in _twins(res, "ods_hub_lsacmsp.podtao", line)
                     if (v.context or "").endswith(ctx_tail)]
            assert len(twins) == 1, (
                f"expected the L{line} occurrence twin of "
                f"ods_hub_lsacmsp.podtao in ...{ctx_tail}, got {len(twins)}")
            twin = twins[0]
            filt = _out_edges(deps, twin.id, "FILTER")
            assert filt, (f"the L{line} predicate twin has no FILTER edge — "
                          "its line stays out of the flow closure")
            anchor = _var(res, filt[0].target_id)
            assert (anchor.context or "TOP") == (twin.context or "TOP")
            assert anchor.variable_type == VariableType.VIRTUAL_TABLE, (
                f"L{line} FILTER anchor must be the scope's output anchor, "
                f"got {anchor.variable_type.value}@{anchor.line_start}")
            # Own-line anchoring: a FILTER edge is kind "field flow", so the
            # payload anchor is the SOURCE's line — the twin's own line.
            # R4 L (2026-08-29): the old closing assert
            # (`assert twin.line_start == line`) could NEVER fail — the
            # twins were selected by that very line two statements above —
            # and VariableDependency carries no anchor payload to assert
            # instead (the anchor is derived at L2 build time, not stored on
            # the edge). The claim this comment makes is pinned where the
            # payload really lives: `test_predicate_lines_reach_the_l2_
            # flow_closure` below asserts {37, 113} ⊆ the served closure's
            # highlight lines. Nothing is asserted here in its place.
            assert not filt[0].containment

    def test_predicate_lines_reach_the_l2_flow_closure(self):
        """End to end: the flow-only closure for ods_hub_lsacmsp.podtao must
        highlight the two predicate lines (37 / 113)."""
        from app.services.l2_builder import _build_l2_graph
        from app.services.workspace_service import create_workspace, \
            delete_workspace

        sql = SUP_M.read_text(encoding="utf-8")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(SUP_M.name, sql)
        ws_id = create_workspace(buf.getvalue())
        try:
            res = _build_l2_graph(ws_id, SUP_M.name, sql,
                                 "ods_hub_lsacmsp", "podtao", True)
        finally:
            delete_workspace(ws_id)
        lines = {e["data"].get("highlight_line") for e in res["edges"]}
        assert {37, 113} <= lines, (
            f"predicate lines 37/113 missing from the flow closure: "
            f"got {sorted(l for l in lines if isinstance(l, int) and 30 <= l <= 120)}")


class TestRfnMaxPdtSubquery:
    """RFN — the `p_dt` predicate lines of the `MAX(p_dt)` scalar subquery."""

    def test_pdt_predicate_occurrences_carry_own_line_edges(self):
        res, deps = _extract(RFN, "BDM_ACC_LOAN_INFO_RFN")
        subq4 = "CTE{TEMP_BDM_ACC_LOAN_INFO_02}:join:KM/subq/tmp_km/subq3/subq4"
        # L827 — the outer `AND P_dt = (SELECT ...` predicate (the scope's
        # surviving var) keeps its own FILTER edge.
        outer = [v for v in res.variables
                 if v.name.casefold() == "p_dt" and v.line_start == 827
                 and (v.context or "").endswith("tmp_km/subq3")]
        assert outer, "the L827 P_dt predicate var is gone"
        assert _out_edges(deps, outer[0].id, "FILTER"), \
            "L827 lost its own-line FILTER edge"
        # The subquery's inner predicate occurrence is a family-3 twin of
        # ods_cdp_gdc_table_coa_list.p_dt. Its line is one of the subquery's
        # genuine p_dt occurrence lines (the twin's line handout is the
        # extractor's — dependency_graph only owns the edge anchoring).
        twins = [v for v in res.variables
                 if v.name.casefold() == "ods_cdp_gdc_table_coa_list.p_dt"
                 and (v.context or "") == subq4
                 and (v.defined_in or "").upper().startswith(_OCCURRENCE_PREFIX)]
        assert twins, "no occurrence twin for the MAX(p_dt) subquery's p_dt"
        sql_lines = {827, 828, 831}
        for twin in twins:
            assert twin.line_start in sql_lines, (
                f"twin anchored off the subquery's p_dt occurrence lines: "
                f"L{twin.line_start}")
            filt = _out_edges(deps, twin.id, "FILTER")
            assert filt, (f"the p_dt twin at L{twin.line_start} has no "
                          "own-line FILTER edge")
            anchor = _var(res, filt[0].target_id)
            assert anchor.variable_type == VariableType.VIRTUAL_TABLE
            assert (anchor.context or "TOP") == subq4


class TestTwinGroupOwnerGuard:
    """A twin inherits a clause only from its OWN (context, owner.field)
    group — never from a different table's same-named field (the DigL
    `D.DATA_DT` hazard: Phase 3's bare-name fallback must not be
    reproduced at the clause level)."""

    @staticmethod
    def _synthetic_result() -> ExtractionResult:
        """Two owners of `data_dt` in one scope; only ods_a's group
        collected a WHERE collapse."""

        def twin(name, owner, line, clause):
            return VariableDefinition(
                id=f"{name}@{line}", name=name, variable_type=VariableType.COLUMN,
                defined_in=f"OCCURRENCE {clause}", context="TOP0",
                source_tables=[owner], line_start=line, line_end=line,
                is_output=False,
            )

        return ExtractionResult(script_name="GUARD", variables=[
            VariableDefinition(id="ods_a", name="ods_a",
                               variable_type=VariableType.TABLE,
                               defined_in="FROM", context="TOP0",
                               line_start=2, line_end=2),
            VariableDefinition(id="ods_b", name="ods_b",
                               variable_type=VariableType.TABLE,
                               defined_in="FROM", context="TOP0",
                               line_start=3, line_end=3),
            VariableDefinition(id="out0", name="⟐ output",
                               variable_type=VariableType.VIRTUAL_TABLE,
                               defined_in="TOP0", context="TOP0",
                               line_start=1, line_end=1),
            twin("ods_a.data_dt", "ods_a", 10, "SELECT expr"),
            twin("ods_a.data_dt", "ods_a", 12, "WHERE"),
            twin("ods_b.data_dt", "ods_b", 20, "SELECT expr"),
        ])

    def test_clause_never_borrows_across_owners(self):
        res = self._synthetic_result()
        deps = build_dependency_graph(res, "")
        by_id = {v.id: v for v in res.variables}
        filt_sources = {d.source_id for d in deps if d.relationship == "FILTER"}
        assert "ods_a.data_dt@10" in filt_sources, (
            "the crossed twin of ods_a.data_dt must inherit its own group's "
            "WHERE participation")
        assert "ods_a.data_dt@12" in filt_sources
        assert "ods_b.data_dt@20" not in filt_sources, (
            "a DIFFERENT table's same-named field must not gain a phantom "
            "FILTER edge from another owner's predicate group")
        # No JOIN edge either: neither group collected a JOIN ON collapse.
        join_sources = {d.source_id for d in deps if d.relationship == "JOIN"}
        assert not join_sources & {"ods_a.data_dt@10", "ods_a.data_dt@12",
                                   "ods_b.data_dt@20"}

    def test_no_cross_owner_group_anywhere_in_the_corpus(self):
        """Every twin whose inherited edge fired shares its group with a
        twin that carries that clause itself — the borrowed clause always
        comes from a same-owner, same-scope sibling."""
        for path in (SUP_M, RFN, DIGL):
            res, deps = _extract(path, path.stem)
            groups = _twin_group_clauses(res)
            for d in deps:
                if d.relationship not in ("FILTER", "JOIN"):
                    continue
                src = _var(res, d.source_id)
                di = (src.defined_in or "").strip().upper()
                if not di.startswith(_OCCURRENCE_PREFIX):
                    continue
                own = _clause_of(di)
                needed = FILTER_CLAUSES if d.relationship == "FILTER" \
                    else JOIN_CLAUSES
                if own in needed:
                    continue  # the twin's own clause — no inheritance
                group = groups.get(((src.context or "TOP"),
                                    src.name.casefold()), set())
                assert group & needed, (
                    f"{path.name}: {src.name}@L{src.line_start} carries "
                    f"{d.relationship} without a same-group {needed} twin "
                    f"(group={sorted(group)}) — a cross-owner clause borrow")
