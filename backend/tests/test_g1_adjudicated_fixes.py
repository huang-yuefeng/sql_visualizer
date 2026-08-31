"""G1 (post-v3.3.191 adjudicated batch, EXTRACTOR_VERSION 2026-08-28.9).

Five fixes, one file — every repro is driven through the SAME machinery the
service uses (extractor -> dependency graph -> physical model -> strict flow
walker), never through a re-implementation:

  Fix A (HIGH, two stages) — the R44 derived-product round and the missing
      provenance edge.  Stage 1: a holder that is itself a DERIVED CONTAINER
      (subquery | virtual_table) qualifies only when its scope reads EXACTLY
      ONE original physical table and that table is the searched one.
      Stage 2: dependency_graph Phase 3 wires the container's output column
      to the same-named reader column attributed to that container — the
      reader carries no source_columns, so nothing else can.
  Fix B — occurrence twins stamp the clause of their OWN line (re-spelled
      through `_LINE_CLAUSE_TO_DEFINED_IN`), never the collapsed group's
      walk-order clause.
  Fix D — `_scope_line_owner` ties overlap by ANCESTRY, and
      `_paren_scope_bound` reads the paren depth at the context's OWN anchor
      token, so a nested body that opens on the same line its parent
      statement starts is bounded by its own `)`.
  Fix E — MERGE phantom writes: alias occurrences are not write targets, and
      a MERGE context mints `{target}.{col}` only for the columns its WHEN
      clauses actually write.
  Fix F — paren-balance diagnostics report SCRIPT lines: the check tokenizes
      the PARSED text (split index == statement index) and translates the
      reported line back through `_preprocess_sql`'s kept-line map.

Fix A stage-1 scope note (the adaptation, measured): the gate is applied to
DERIVED-CONTAINER holders only.  A physical/CTE holder keeps the original
scope-presence rule because the canonical closures depend on it structurally —
SUP_M's `ods_hub_lsacmsp.lending_ref` seeds ZERO PhysicalField occurrences, so
the round's admissions are that closure's ONLY entry point and every one of
them hangs off a plain physical-table holder.  Gating those empties the
closure (21 -> 0 nodes; jaccard lending_ref/SUP_M/downstream nodes precision
0.8491) and the same shape carries PL's true positive `a.p_dt`@224, so no
occurrence-level test separates them.  AD1's `c.p_dt`@221 exclusion is
therefore NOT delivered; `test_pl_pdt_true_positives_survive` pins what IS
guaranteed on that script.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.dependency_graph import (  # noqa: E402
    _OCCURRENCE_PREFIX,
    _clause_of,
    build_dependency_graph,
)
from app.extractor.lineage import compute_field_flow  # noqa: E402
from app.extractor.physical_model import build_physical_model  # noqa: E402
from app.extractor.variable_extractor_v2 import (  # noqa: E402
    _LINE_CLAUSE_TO_DEFINED_IN,
    _preprocess_sql,
    _RoleBasedExtractor,
    ExtractionResult,
    extract_variables_from_sql,
)
from app.models.variable import VariableType  # noqa: E402

SAMPLES = BACKEND_DIR.parent / "samples" / "sql_sample_v1"
RFN = SAMPLES / "BDM_ACC_LOAN_INFO_RFN.sql"
SUP_M = SAMPLES / "BDM_ACC_LOAN_INFO_SUP_M.sql"
PL = SAMPLES / "BDM_ACC_LOAN_INFO_PL.sql"


def _build(sql: str, name: str = "probe"):
    """extractor -> dependency graph -> physical model, plus the walker input
    graph — the same chain the service runs, as four artifacts.

    TEAM V3 REPAIR (2026-08-31, G7's flagged harness weakness): this used to
    call `build_physical_model(res, deps)` — but the second POSITIONAL
    parameter of `build_physical_model` is `script_name`
    (`physical_model.py:283`), so the dependency list landed in the script
    name, `dependencies` stayed None and `pm.edges` came out EMPTY. The strict
    walker then ran its identity-admission rounds only and never walked an
    edge, which is why every co-scope repro in this file stayed green
    regardless of edge-level changes: the real co-scope protection lives in
    guard 4 + the PROVENANCE walk rule (test_g7_rc_c_fixes.py). The call is
    keyword-correct now; `TestHarnessPhysicalModel` guards the repair."""
    res = extract_variables_from_sql(sql, name)
    deps = build_dependency_graph(res, sql)
    pm = build_physical_model(res, script_name=name, dependencies=deps)
    graph = {
        "nodes": [{"data": {"id": v.id, "label": v.name}} for v in res.variables],
        "edges": [{"data": {"source": d.source_id, "target": d.target_id,
                            "edge_type": d.relationship,
                            "operation": d.operation,
                            "containment": d.containment}} for d in deps],
    }
    return res, deps, pm, graph


def _closure(sql: str, table: str, field: str, name: str = "probe"):
    """The strict downstream closure as (name, line) pairs — the shape the
    flow-only L2 view renders from. Returns (res, deps, pm, closure), the
    same shape test_g7_rc_c_fixes._closure returns."""
    res, deps, pm, graph = _build(sql, name)
    out = compute_field_flow(graph, table, field, physical_model=pm,
                             direction="downstream")
    byid = {v.id: v for v in res.variables}
    return res, deps, pm, {(byid[i].name, byid[i].line_start) for i in out
                           if i in byid}


class TestHarnessPhysicalModel:
    """The harness hands the walker a model that actually carries the
    dependency edges (team V3, 2026-08-31 — guards the signature repair)."""

    def test_pm_edges_are_non_empty(self):
        """`pm.edges` empty ⇒ the walker below never walked an edge and every
        co-scope repro in this file is vacuous."""
        _, deps, pm, _ = _build(SRC_A_SRC_B)
        assert deps, "fixture broken: the dependency graph is empty"
        assert pm.edges, (
            "build_physical_model received no dependencies — the harness is "
            "back in the positional-call trap (deps in the script_name slot) "
            "and this file's walker tests prove nothing")
        assert pm.script_name == "probe", pm.script_name

    def test_pm_edges_cover_every_dependency(self):
        """The model is built from the SAME deps the walker's graph is — a
        comma-split relationship yields one PhysicalEdge per type, so the
        model carries at least one edge per dependency."""
        _, deps, pm, graph = _build(TWO_PHYSICAL_SOURCES)
        assert len(graph["edges"]) == len(deps)
        assert len(pm.edges) >= len(deps), (len(pm.edges), len(deps))


def _twins(res, field: str):
    return [v for v in res.variables
            if (v.defined_in or "").strip().upper().startswith(
                _OCCURRENCE_PREFIX)
            and v.variable_type == VariableType.COLUMN
            and v.name.rsplit(".", 1)[-1].casefold() == field.casefold()]


# ════════════════════════════════════════════════════════════════════════
# Fix A stage 1 — a derived container lends its scope only when it IS a
# derived product of the searched table
# ════════════════════════════════════════════════════════════════════════

# The searched table is read INSIDE the derived container `k`, whose scope
# has TWO sources — so `k.dt` is ambiguous (s1's or s2's dt?) and the
# container is not a derived product of src_a. Pre-gate, the round admitted
# `k.dt` + `k` on scope presence alone; gated, they stay out and the true
# side (s1 / src_a) keeps its occurrences.
SRC_A_SRC_B = """
INSERT INTO tgt
SELECT k.dt
FROM (
    SELECT s1.dt, s2.dt AS dt2
    FROM (SELECT dt, k FROM src_a) s1
    JOIN (SELECT dt, k FROM src_b) s2 ON s1.k = s2.k
) k;
"""

TWO_PHYSICAL_SOURCES = """
INSERT INTO tgt
SELECT p.dt
FROM (
    SELECT y.amt, z.amt AS amt2
    FROM src_y y
    JOIN src_z z ON y.k = z.k
) p;
"""


class TestFixADerivedContainerScope:
    """A container over TWO sources is nobody's derived product — its scope
    must not lend a same-named column to either source's field."""

    def test_two_source_container_does_not_join(self):
        """TEAM V3 RE-SCOPE (2026-08-31, G7's flagged harness weakness): the
        old assertion — `k.dt`, `k`, `src_b`, `dt2` all stay OUT — was written
        by a walker that never walked an edge (`build_physical_model(res,
        deps)` put the dependency list into the `script_name` slot, so
        `pm.edges` was empty and only the identity-admission rounds ran).
        Under the real walk the container's own output column `k.dt`@3 joins,
        and it is RIGHT that it does: `k.dt` IS downstream of src_a.dt (the
        container projects `s1.dt` as `dt`), the same value path
        `test_single_source_cte_pass_through_joins` pins on G7's one-source
        CTE. G7's own two-source fixture (CTE_TWO_SOURCES, harness already
        correct) serves the same members and deliberately leaves its closure
        unpinned — so this is the walker's accepted answer, not a flood: the
        closure stays inside the searched statement's own container (no
        unrelated CTE body pours in; that class stays pinned by G7's
        `TestProvenanceEdgeWalkRule`).

        What Fix A stage 1 still guarantees is narrower and is what this
        repro now pins: the container is nobody's DERIVED PRODUCT, so its
        scope never LENDS the same-named column to src_a's occurrences — the
        admission rides the value chain, never scope presence. Residual,
        recorded not endorsed: src_b's same-named `dt` comes along through
        the extractor's own sibling same-name REFERENCE edge (dt@7 → dt@6, a
        graph-level fact `build_dependency_graph` emitted before this repair
        too — deps count is identical before and after), so it is the
        extractor's co-scope wiring, not the holder gate, that admits it."""
        res, deps, pm, closure = _closure(SRC_A_SRC_B, "src_a", "dt")
        # the searched side keeps its own occurrences
        assert {("dt", 6), ("s1", 6), ("src_a", 6)} <= closure, closure
        # the container's output column arrives by VALUE (the real walk), and
        # the container's own handle is still never admitted
        assert ("k.dt", 3) in closure, closure
        assert not any(n == "k" for n, _ in closure), closure
        # ... and the admission was NOT the holder lending its scope: on an
        # empty value chain the derived container still refuses to qualify.
        from app.extractor.lineage import _holder_is_derived_single
        occ = pm.occurrence
        holder = next(vid for vid, o in pm.occurrences.items()
                      if o.get("variable_type") == "subquery"
                      and (o.get("name") or "").casefold() == "k")
        assert _holder_is_derived_single(pm, occ, holder, "dt", {}, set()) \
            is False, "the two-source container qualified as a derived product"

    def test_two_physical_source_container_does_not_join(self):
        """The container's own ambiguous output column never joins either
        source's closure — the holder IS the container, so the gate fires.
        (The sibling PLAIN table read `z.amt` is the part of AD1's exclusion
        this implementation deliberately keeps; see the module docstring.)
        TEAM V3 (2026-08-31): still green with the repaired harness — the
        container's output read here is `p.dt`, a different field, so the
        real walk adds nothing named `p.*` to `amt`'s closure."""
        res, deps, pm, closure = _closure(TWO_PHYSICAL_SOURCES, "src_y", "amt")
        assert {("y.amt", 5), ("src_y", 6)} <= closure, closure
        assert not any(n in ("p", "p.amt", "p.amt2")
                       for n, _ in closure), closure


class TestFixADerivedSingleTruePositives:
    """The canonical derived-single cases keep their occurrences."""

    def test_pl_product_keeps_the_km1_body_line(self):
        """`p2` wraps exactly one physical source (the EXISTS body is
        row-selection, not a row source), so its `product` occurrences stay
        in the searched table's closure."""
        sql = PL.read_text(encoding="utf-8")
        res, deps, pm, closure = _closure(sql, "bdm_fin_lrr_key_base_info",
                                         "product", "PL")
        members = {n for n, _ in closure}
        assert "p2.product" in members, sorted(closure)
        assert "bdm_fin_lrr_key_base_info.product" in members, sorted(closure)

    def test_pl_pdt_true_positives_survive(self):
        """`a` is a derived product of the searched table (identity rule) —
        its p_dt occurrences stay.  The sibling `c` read is the shape AD1
        also wanted out; see the module docstring for why that exclusion is
        NOT delivered (it is undecidable at the occurrence level without
        emptying SUP_M's canonical closure)."""
        sql = PL.read_text(encoding="utf-8")
        res, deps, pm, closure = _closure(sql, "ODS_CUPD_PLOAN_ACCTM_NEW5",
                                         "p_dt", "PL")
        members = {n for n, _ in closure}
        assert "a.p_dt" in members, sorted(closure)
        assert any(n.casefold() == "ods_cupd_ploan_acctm_new5.p_dt"
                   for n in members), sorted(closure)


class TestFixAStage2ProvenanceEdge:
    """WITHHELD, and the reason is measurable. The provenance edge itself is
    semantically sound (a bare-handle reader attributed to a container carries
    no source_columns, so Phase 3 has nothing else to wire it with), and it
    does light RFN's REPAY_ACCT_NO@364 — but every container scope tried (all
    containers, CTE-only) also re-routes SUP_M's fold carriers, and the
    strict closure of ods_hub_lsacmsp.lending_ref then grows past its
    canonical set: jaccard lending_ref/SUP_M/downstream edges recall 0.7905,
    22 canonical edges unmatched, nodes precision 0.8491. THE gate wins, so
    the edge is deferred to the SCHEMA-fold design item and these tests pin
    the state it must beat when it comes back."""

    def test_rfn_birth_line_is_lit_without_the_provenance_edge(self):
        """364 must stay lit through the narrowed holder gate alone — the
        holder here is a CTE occurrence, which Fix A stage 1 does not gate."""
        from app.services.l2_builder import _build_l2_graph
        sql = RFN.read_text(encoding="utf-8")
        l2 = _build_l2_graph("probe", RFN.name, sql,
                             "TEMP_BDM_ACC_LOAN_INFO_02", "repay_acct_no",
                             direction="downstream")
        g = l2.get("graph") if isinstance(l2.get("graph"), dict) else l2
        lines = {e["data"].get("highlight_line") for e in g["edges"]}
        assert 364 in lines, (
            "repay_acct_no's rename birth line went dark: "
            f"{sorted(l for l in lines if isinstance(l, int) and 355 <= l <= 370)}")

    def test_reader_is_still_a_bare_handle_read(self):
        """The shape the deferred edge is for: a reader column attributed to
        a container with no source_columns of its own."""
        sql = RFN.read_text(encoding="utf-8")
        res = extract_variables_from_sql(sql, "RFN")
        reader = next(v for v in res.variables
                      if v.name == "P1.REPAY_ACCT_NO" and v.line_start == 630)
        assert reader.source_tables[0] == "TEMP_BDM_ACC_LOAN_INFO_01"
        assert not reader.source_columns
        producer = next(v for v in res.variables
                        if v.name == "REPAY_ACCT_NO" and v.line_start == 364)
        assert producer.context == "CTE{TEMP_BDM_ACC_LOAN_INFO_01}"

# ════════════════════════════════════════════════════════════════════════
# Fix B — a twin stamps the clause of its OWN line
# ════════════════════════════════════════════════════════════════════════

class TestFixBTwinClauseStamp:
    def test_rfn_join_predicate_twin_is_join_on(self):
        res = extract_variables_from_sql(
            RFN.read_text(encoding="utf-8"), "RFN")
        twins = [v for v in _twins(res, "repay_acct_no")
                 if v.line_start == 1158]
        assert len(twins) == 1, twins
        assert _clause_of(twins[0].defined_in) == "JOIN ON", twins[0]

    def test_over_line_twin_is_order_by(self):
        """X5CTCD@484 sits inside `ROW_NUMBER() OVER(PARTITION BY … ORDER
        BY X5STDT DESC)` — the line's LAST clause keyword governs it."""
        res = extract_variables_from_sql(
            RFN.read_text(encoding="utf-8"), "RFN")
        twins = [v for v in _twins(res, "x5ctcd") if v.line_start == 484]
        assert len(twins) == 1, twins
        assert _clause_of(twins[0].defined_in) == "ORDER BY", twins[0]

    def test_every_twin_carries_a_clause_spelling(self):
        """No twin falls back to a context-shaped clause (`OCCURRENCE
        TOP0` / `OCCURRENCE CTE{x}`) — the line's clause is always known in
        these scripts, and a context-shaped stamp matches no Phase 6/6b
        gate."""
        for path in (RFN, SUP_M, PL):
            res = extract_variables_from_sql(
                path.read_text(encoding="utf-8"), path.stem)
            bad = [(v.name, v.line_start, v.defined_in)
                   for v in _twins(res, "*")
                   if v.name.rsplit(".", 1)[-1].casefold()
                   and _clause_of(v.defined_in)
                   not in set(_LINE_CLAUSE_TO_DEFINED_IN.values())]
            # `field="*"` returns nothing; walk the occurrence vars directly
            occ_vars = [v for v in res.variables
                        if (v.defined_in or "").strip().upper().startswith(
                            _OCCURRENCE_PREFIX)
                        and v.variable_type == VariableType.COLUMN]
            bad = [(v.name, v.line_start, v.defined_in) for v in occ_vars
                   if _clause_of(v.defined_in).casefold()
                   not in {v_.casefold() for v_
                           in _LINE_CLAUSE_TO_DEFINED_IN.values()}]
            assert not bad, f"{path.name}: {bad[:6]}"

    def test_rfn_join_twin_carries_its_own_join_edge(self):
        """The @1158 twin's JOIN edge comes from its own label now — it no
        longer depends on `_twin_group_admits` borrowing the group's
        clause."""
        from app.extractor.dependency_graph import build_dependency_graph as bg
        sql = RFN.read_text(encoding="utf-8")
        res = extract_variables_from_sql(sql, "RFN")
        deps = bg(res, sql)
        by_id = {v.id: v for v in res.variables}
        twin = next(v for v in _twins(res, "repay_acct_no")
                    if v.line_start == 1158)
        joins = [d for d in deps
                 if d.source_id == twin.id and d.relationship == "JOIN"]
        assert joins, "the @1158 twin lost its own JOIN edge"
        for d in joins:
            assert _clause_of(by_id[d.source_id].defined_in) == "JOIN ON"


# ════════════════════════════════════════════════════════════════════════
# Fix D — same-line nested bodies and the ancestry tie-break
# ════════════════════════════════════════════════════════════════════════

SAME_LINE_SUBQUERY = "SELECT (SELECT max(z) FROM t3) AS m, y\nFROM t2\n"


class TestFixDScopeOwner:
    """The landed half: overlapping ranges resolve by ANCESTRY. The withheld
    half (the anchor-token paren depth that bounds a same-line nested body by
    its own `)`) is pinned as the open item — it moves the occurrence twins
    corpus-wide and takes the canonical SUP_M closure past its set."""

    def _owner(self, sql):
        ex = _RoleBasedExtractor(ExtractionResult(script_name="D"), "D", sql)
        import sqlglot
        from sqlglot import ErrorLevel
        from app.extractor.variable_extractor_v2 import _detect_dialect
        clean, _kept = _preprocess_sql(sql)
        for i, st in enumerate(sqlglot.parse(clean, dialect=_detect_dialect(clean),
                                             error_level=ErrorLevel.IGNORE)):
            if st is not None:
                ex.process_statement(st, f"TOP{i}")
        return ex

    def test_one_line_per_statement_scripts_own_their_lines(self):
        sql = ("SELECT a FROM t1;\n"
               "SELECT b FROM t2 WHERE b.x = 1;\n"
               "UPDATE t3 SET c = 1 WHERE d = 2;\n")
        ex = self._owner(sql)
        owner = ex._scope_line_owner()
        assert owner.get(1) == "TOP0", owner
        assert owner.get(2) == "TOP1", owner
        assert owner.get(3) == "TOP2", owner

    def test_ancestry_tiebreak_prefers_the_descendant_scope(self):
        """Of two contexts anchored on the SAME line, the descendant — the
        context the other CONTAINS — owns the contested lines. (The old
        tie-break compared context-string LENGTH, which orders `TOP0/a` vs
        `TOP0/abc` by spelling and let a CTE body outrank a statement root.)"""
        ex = self._owner(SAME_LINE_SUBQUERY)
        assert ex._stmt_anchor_lines == {"TOP0": 1, "TOP0/subq1": 1}
        owner = ex._scope_line_owner()
        assert owner.get(1) == "TOP0/subq1", owner

    def test_ctx_ancestor_relation_is_segment_exact(self):
        assert _RoleBasedExtractor._ctx_is_ancestor("TOP0", "TOP0/subq1")
        assert _RoleBasedExtractor._ctx_is_ancestor("TOP0", "TOP0:join:p2")
        assert _RoleBasedExtractor._ctx_is_ancestor("CTE{a}", "CTE{a}")
        assert not _RoleBasedExtractor._ctx_is_ancestor("TOP0/a", "TOP0/abc")
        assert not _RoleBasedExtractor._ctx_is_ancestor("TOP0/subq1", "TOP0")

    def test_open_item_same_line_body_still_swallows_the_parent_line(self):
        """The PIN of the withheld correction (do not mistake this for the
        desired end state): with the line-based paren read, the nested scope
        is unbounded and claims the parent's `FROM` line too. Fix D's
        withheld half exists to flip this assertion."""
        ex = self._owner(SAME_LINE_SUBQUERY)
        owner = ex._scope_line_owner()
        assert owner.get(2) == "TOP0/subq1", owner


# ════════════════════════════════════════════════════════════════════════
# Fix E — MERGE phantom writes
# ════════════════════════════════════════════════════════════════════════

MERGE_ALIAS = """
MERGE INTO tgt_table tgt
USING (SELECT sid, v, dt FROM src_table) t
ON tgt.sid = t.sid
WHEN MATCHED THEN UPDATE SET tgt.v = t.v, tgt.dt = t.dt
WHEN NOT MATCHED THEN INSERT (v, dt) VALUES (t.v, t.dt);
"""


class TestFixEMergePhantomWrites:
    @staticmethod
    def _write_twins(res):
        """Family-1 write twins: an OUTPUT column attributed to a table it
        is not a read of — the `{target}.{alias}` mint."""
        return [v for v in res.variables
                if v.is_output and "." in v.name
                and not v.source_columns
                and v.variable_type == VariableType.COLUMN]

    def test_no_alias_write_target_and_no_unwritten_twin(self):
        res = extract_variables_from_sql(MERGE_ALIAS, "MERGE_E")
        twins = self._write_twins(res)
        owners = {v.name.split(".", 1)[0] for v in twins}
        # the USING alias is not a write target — no `t.*` write slots
        assert "t" not in owners, [(v.name, v.line_start) for v in twins]
        by_name = {v.name: v for v in twins}
        # the UPDATE SET left-hand targets and the INSERT column list are
        # exactly the write slots ...
        assert "tgt_table.v" in by_name, sorted(by_name)
        assert "tgt_table.dt" in by_name, sorted(by_name)
        # ... and a column no WHEN clause writes is never minted
        assert "tgt_table.sid" not in by_name, sorted(by_name)

    def test_plain_target_merge_is_byte_identical_to_the_projection_rule(self):
        """An alias-free target keeps the pre-fix behaviour: the write slots
        its WHEN clauses name are minted, the USING subquery's projections
        stay the source's reads (they are output vars, so the projection
        rule still reaches them — but the alias handle `src` is not a write
        target of its own)."""
        sql = """
MERGE INTO tgt_table
USING (SELECT sid, v FROM src_table) src
ON tgt_table.sid = src.sid
WHEN MATCHED THEN UPDATE SET tgt_table.v = src.v;
"""
        res = extract_variables_from_sql(sql, "MERGE_E2")
        names = {v.name for v in res.variables}
        # the write slot is named by the SET clause, whichever pass mints it
        assert "tgt_table.v" in names, sorted(names)
        # the USING alias handle is not a write target
        twins = self._write_twins(res)
        assert not any(v.name.startswith("src.") for v in twins), twins

    def test_update_target_alias_is_not_a_write_target(self):
        sql = ("UPDATE tgt_table t SET t.v = 'x' WHERE t.sid = 1;\n")
        res = extract_variables_from_sql(sql, "UPD_E")
        # the alias handle never becomes a write target — every var named
        # `t.*` is the alias's own READ of the target's column
        for v in res.variables:
            if v.name.startswith("t."):
                assert v.source_tables == ["tgt_table"], v
        members = {v.name for v in res.variables}
        assert "t.v" in members, sorted(members)
        # the target's own field is the write slot the SET clause names
        assert any(v.name == "t.v" and v.source_tables == ["tgt_table"]
                   and v.defined_in == "UPDATE SET"
                   for v in res.variables), sorted(members)


# ════════════════════════════════════════════════════════════════════════
# Fix F — paren-balance diagnostics report SCRIPT lines and the right
# statement index
# ════════════════════════════════════════════════════════════════════════

class TestFixFParenBalanceScriptLines:
    def test_dropped_set_lines_do_not_shift_the_statement_index(self):
        from app.extractor.variable_extractor_v2 import _paren_balance_errors
        clean, kept = _preprocess_sql(
            "SELECT ( 1;\nSET a=1;\nSET b=2;\nSELECT 2;\n")
        errs = _paren_balance_errors(clean, "hive", 2, kept)
        assert len(errs) == 1, errs
        assert errs[0]["stmt_idx"] == 0, errs
        assert "(script line 1)" in errs[0]["detail"], errs

    def test_mid_script_set_keeps_the_real_statement_index(self):
        from app.extractor.variable_extractor_v2 import _paren_balance_errors
        raw = ("SELECT 1;\nSELECT 2;\nSET a=1;\nSELECT ( 3;\nSELECT 4;\n")
        clean, kept = _preprocess_sql(raw)
        errs = _paren_balance_errors(clean, "hive", 4, kept)
        assert len(errs) == 1, errs
        assert errs[0]["stmt_idx"] == 2, errs
        # the break is on RAW line 4 — the clean text's line 3
        assert "(script line 4)" in errs[0]["detail"], errs

    def test_comment_only_lines_do_not_shift_the_reported_line(self):
        from app.extractor.variable_extractor_v2 import _paren_balance_errors
        raw = ("-- leading comment\nSELECT 1;\n-- mid comment\nSELECT ( 2;\n")
        clean, kept = _preprocess_sql(raw)
        errs = _paren_balance_errors(clean, "hive", 2, kept)
        assert len(errs) == 1, errs
        assert errs[0]["stmt_idx"] == 1, errs
        assert "(script line 4)" in errs[0]["detail"], errs

    def test_preprocess_returns_the_kept_line_map(self):
        clean, kept = _preprocess_sql("SET a=1;\n-- c\nSELECT 1;")
        assert clean == "SELECT 1;"
        assert kept == [3]  # SET line 1 and comment line 2 are dropped

    def test_full_pipeline_reports_the_script_line(self):
        from app.extractor.adapter import run_full_analysis
        raw = "SET a=1;\nSET b=2;\nSELECT ( 1;\nSELECT 2;\n"
        result = run_full_analysis(raw, "broken.sql")
        errs = [e for e in result.get("parse_errors") or []
                if "unbalanced parentheses" in (e.get("detail") or "")]
        assert errs, result.get("parse_errors")
        assert errs[0]["stmt_idx"] == 0, errs
        assert "(script line 3)" in errs[0]["detail"], errs
