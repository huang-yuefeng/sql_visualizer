"""F-E2 (R45 Fixes C–G + K3, EXTRACTOR_VERSION 2026-08-28.8) — the family-3
occurrence-twin pass stays inside its own group's scope, qualifier and
clause, and never promotes an expression fragment to a field identity.

Defects fixed (SUP_M / RFN evidence):

* Fix D — WRONG OWNER: `_base_var_for` matched on the LAST dot-part only, so
  every same-field group in a scope resolved to the FIRST surviving var with
  that field part. SUP_M's INSERT names `CHARGE_DEPARTMENT` as a dynamic
  PARTITION column @160 (owner bdm_acc_loan_info_sup) BEFORE the projections,
  so both `p1.charge_department` occurrences (@182 CASE arm, @196 the
  partition feed — p1 = loan_final, FROM@198) minted twins owned by the write
  target. F-D adjudicated both wrong and refused to canonicalize them.
* Fix C/G — WRONG SCOPE: the occurrence-line search ran to "the next
  non-nested anchor", so a nested body's range ran past its own `)`. SUP_M's
  NOT-IN subquery (closes @58) grabbed the enclosing subquery's
  `GROUP BY lending_ref` @59 and minted `bdm_evt_loan_trans.lending_ref`@59 —
  but that GROUP BY belongs to the enclosing scope, whose only source is
  bdm_acc_loan_info.
* Fix E/F — PHANTOM PAIRING: `_add` records collapses in walk order while the
  lines are textual; a group's duplicate registration of an already-anchored
  occurrence stole the free line a genuine occurrence needed (RFN: the
  `p_dt <= TO_DATE(...)` predicate @831 stayed dark).
* K3 — FRAGMENT FIELD: the unrepaired RFN (missing `)`) recovered a partial
  tree whose alias render spans a paren, and `lending_ref, 4, 5)` reached the
  field namespace. The var stays (its line/expression/edges are real) but is
  stamped as an auto-named fragment so no write-side twin is minted from it.
"""

import io
import sys
import zipfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.dependency_graph import (  # noqa: E402
    _OCCURRENCE_PREFIX,
    build_dependency_graph,
)
from app.extractor.variable_extractor_v2 import (  # noqa: E402
    ExtractionResult,
    extract_variables_from_sql,
)
from app.models.variable import VariableType  # noqa: E402

SAMPLES_DIR = BACKEND_DIR.parent / "samples" / "sql_sample_v1"
SUP_M = SAMPLES_DIR / "BDM_ACC_LOAN_INFO_SUP_M.sql"
RFN = SAMPLES_DIR / "BDM_ACC_LOAN_INFO_RFN.sql"


def _extract(path: Path, name: str):
    sql = path.read_text(encoding="utf-8")
    return extract_variables_from_sql(sql, name)


def _twins(res, field: str, line=None):
    """Family-3 occurrence twins whose name's FIELD part is `field`."""
    out = []
    for v in res.variables:
        di = (v.defined_in or "").strip().upper()
        if not di.startswith(_OCCURRENCE_PREFIX):
            continue
        if v.variable_type != VariableType.COLUMN:
            continue
        if v.name.rsplit(".", 1)[-1].casefold() != field.casefold():
            continue
        if line is not None and v.line_start != line:
            continue
        out.append(v)
    return out


class TestSupMOwnerScope:
    """Item 1 — the two wrong-owner twins F-D refused to canonicalize."""

    def test_charge_department_twins_are_owned_by_loan_final(self):
        res = _extract(SUP_M, "BDM_ACC_LOAN_INFO_SUP_M")
        twins = _twins(res, "charge_department")
        assert twins, "expected occurrence twins for charge_department in TOP0"
        for twin in twins:
            assert twin.source_tables == ["loan_final"], (
                f"L{twin.line_start} twin owned by {twin.source_tables}: the "
                "PARTITION column @160 (owner bdm_acc_loan_info_sup) must "
                "never lend its owner to the p1 = loan_final occurrences")

    def test_no_town_outside_the_not_in_subquery_scope(self):
        """The NOT-IN body (closes @58) must not claim @59's GROUP BY."""
        res = _extract(SUP_M, "BDM_ACC_LOAN_INFO_SUP_M")
        # R4 L (2026-08-29): the negative loop below is vacuous when no twin
        # exists at all — a broken extractor that mints nothing would pass.
        twins = _twins(res, "lending_ref")
        assert twins, "no lending_ref occurrence twins — the guard is vacuous"
        for twin in twins:
            assert not (
                twin.source_tables
                and twin.source_tables[0].casefold() == "bdm_evt_loan_trans"
                and twin.line_start == 59
            ), ("bdm_evt_loan_trans lent its owner to the enclosing "
                "subquery's GROUP BY lending_ref @59")
        # …and the enclosing scope's own GROUP BY occurrence is anchored at
        # its own line by a bdm_acc_loan_info instance (LFS106's fact).
        groupby = [v for v in res.variables
                   if v.name.casefold() == "bdm_acc_loan_info.lending_ref"
                   and v.line_start == 59
                   and (v.context or "").endswith("subq1/subq")]
        assert groupby, "no bdm_acc_loan_info.lending_ref var at the GROUP BY"

    def test_sup_partition_slot_feed_is_the_partition_tables_own_column(self):
        """Every twin's owner must be a table whose FROM/JOIN line the twin's
        scope actually declares — the same-owner contract family 3 states."""
        res = _extract(SUP_M, "BDM_ACC_LOAN_INFO_SUP_M")
        bad = [v for v in res.variables
               if (v.defined_in or "").strip().upper().startswith(
                   _OCCURRENCE_PREFIX)
               and v.variable_type == VariableType.COLUMN
               and v.source_tables
               and v.name.rsplit(".", 1)[0].casefold()
               != v.source_tables[0].casefold()]
        assert not bad, (
            "occurrence twins whose qualifier names another table: "
            f"{[(v.name, v.source_tables, v.line_start) for v in bad]}")


class TestRfnPredicateLine:
    """The `MAX(p_dt)` scalar subquery: the inner predicate keeps its line."""

    def test_inner_pdt_predicate_twin_sits_on_its_own_line(self):
        res = _extract(RFN, "BDM_ACC_LOAN_INFO_RFN")
        subq4 = "CTE{TEMP_BDM_ACC_LOAN_INFO_02}:join:KM/subq/tmp_km/subq3/subq4"
        twins = [v for v in res.variables
                 if v.name.casefold() == "ods_cdp_gdc_table_coa_list.p_dt"
                 and (v.context or "") == subq4
                 and (v.defined_in or "").strip().upper().startswith(
                     _OCCURRENCE_PREFIX)]
        assert twins, "no occurrence twin for the MAX(p_dt) subquery's p_dt"
        # The genuine occurrence set is {827, 828, 831}; the twin is the
        # inner predicate @831 — never the enclosing scope's lines.
        assert [t.line_start for t in twins] == [831], (
            f"expected the @831 predicate occurrence, got "
            f"{[t.line_start for t in twins]}")


class TestRfnBirthLines:
    """Item 2 — a CTE-internal derivation's own line stays in its closure."""

    def test_birth_lines_reach_the_flow_closure(self):
        from app.services.l2_builder import _build_l2_graph
        from app.services.workspace_service import (
            create_workspace,
            delete_workspace,
        )
        sql = RFN.read_text(encoding="utf-8")
        res = extract_variables_from_sql(sql, RFN.stem)
        build_dependency_graph(res, sql)
        # R4 M (2026-08-29): this used to call `_build_l2_graph("probe", …)`
        # — a workspace id that never existed, so the builder wrote its
        # graph caches into the SHARED /tmp/workspaces/probe and left them
        # there forever: every run of the suite reused whatever the first
        # run had written, and every concurrent test/reader of that
        # directory saw them. A unique id, deleted in `finally`, keeps the
        # fixture self-contained (the `_ws` pattern the sibling tests use).
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(RFN.name, sql)
        ws_id = create_workspace(buf.getvalue())
        try:
            for field, line in (("repay_acct_no", 364),       # column rename birth
                                ("is_internet_loan", 687),    # derived passthrough
                                ("tag_branch", 721)):         # expression birth
                    l2 = _build_l2_graph(ws_id, RFN.name, sql,
                                         "TEMP_BDM_ACC_LOAN_INFO_02", field,
                                         direction="downstream")
                    g = l2.get("graph") if isinstance(l2.get("graph"), dict) else l2
                    lines = {e["data"].get("highlight_line") for e in g["edges"]}
                    assert line in lines, (
                        f"{field}'s derivation line {line} is dark: "
                        f"{sorted(l for l in lines if isinstance(l, int) and abs(l - line) <= 6)}")
        finally:
            delete_workspace(ws_id)


class TestFragmentFieldGuard:
    """K3 — a field whose NAME is not an identifier is a fragment, and the
    twin machinery must never mint a physical field from it."""

    def test_fragment_named_column_is_stamped_auto_named(self):
        from app.extractor.variable_extractor_v2 import _RoleBasedExtractor
        ex = _RoleBasedExtractor(ExtractionResult(script_name="FRAG"), "FRAG",
                                 "SELECT a FROM b")
        var = ex._add("lending_ref, 4, 5)", VariableType.COLUMN,
                      defined_in="SELECT expr", context="TOP0",
                      source_tables=["b"])
        assert var is not None
        assert var.id in ex._auto_named_outputs, (
            "a fragment-named field must carry the auto-named stamp so the "
            "write-side twin pass never mints a physical field from it")

    def test_real_field_is_not_stamped(self):
        from app.extractor.variable_extractor_v2 import _RoleBasedExtractor
        ex = _RoleBasedExtractor(ExtractionResult(script_name="REAL"), "REAL",
                                 "SELECT a FROM b")
        var = ex._add("lending_ref", VariableType.COLUMN,
                      defined_in="SELECT expr", context="TOP0",
                      source_tables=["b"])
        assert var is not None
        assert var.id not in ex._auto_named_outputs
