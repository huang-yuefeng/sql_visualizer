"""#386 CTE-scope ruling — a CTE's name is statement-scoped (SQL standard).

A CTE defined in one statement is invisible to LATER statements, so a
later statement's bare `FROM tmp_loan` reference names a PHYSICAL table,
not the CTE. In-scope references (the CTE's own statement) keep folding
onto the cte_table entity.

Three levels are pinned:
  (a) extractor — the out-of-scope ref registers a PHYSICAL TABLE var;
  (b) extractor — the in-scope ref still folds (no TABLE var, CTE only);
  (c) L2 display — the same name renders as TWO distinct compounds
      (cte_table for the in-scope read, source_table for the out-of-scope
      read) and each statement's columns land on the correct one.
"""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.models.variable import VariableType  # noqa: E402
from app.extractor.variable_extractor_v2 import extract_variables_from_sql  # noqa: E402
from app.extractor.dependency_graph import build_dependency_graph  # noqa: E402
from app.extractor.physical_model import build_physical_model  # noqa: E402
from app.services.graph_service import build_graph_data  # noqa: E402
from app.services.l2_builder import _classify_compound_nodes  # noqa: E402

TWO_STATEMENT = (
    "WITH tmp_loan AS (SELECT a.loan_id, a.amt FROM loans a) "
    "SELECT l.loan_id, l.amt FROM tmp_loan l; "
    "SELECT x.loan_id, x.amt FROM tmp_loan x;"
)

IN_SCOPE_ONLY = (
    "WITH tmp_loan AS (SELECT a.loan_id, a.amt FROM loans a) "
    "SELECT l.loan_id, l.amt FROM tmp_loan l;"
)


def _classify(sql):
    """Build the L2 compound classification for `sql` (no workspace/cache)."""
    from app.extractor.adapter import run_full_analysis
    ana = run_full_analysis(sql, "cte_scope_test")
    graph = build_graph_data(ana)
    model = build_physical_model(ana, script_name="cte_scope_test")
    table_nodes, field_nodes, _alias_map, _occ_to_id = _classify_compound_nodes(
        graph["nodes"], graph, "cte_scope_test", set(), set(), None, model)
    return table_nodes, field_nodes, model


class TestCteScopeExtractor:
    """(a)+(b) — the extractor's `_add` CTE-merge is scope-aware."""

    def test_out_of_scope_ref_is_physical_table(self):
        """A later statement's bare ref to a CTE's name is a PHYSICAL read."""
        r = extract_variables_from_sql(TWO_STATEMENT, "test")
        ctes = [v for v in r.variables
                if v.variable_type == VariableType.CTE and v.name.lower() == "tmp_loan"]
        tables = [v for v in r.variables
                  if v.variable_type == VariableType.TABLE and v.name.lower() == "tmp_loan"]
        assert len(ctes) == 1, f"one CTE tmp_loan, got {[(v.name, v.context) for v in ctes]}"
        # The out-of-scope read is a TABLE var in the LATER statement (TOP1),
        # not swallowed by the any-context CTE merge.
        assert tables, "the out-of-scope ref must register a physical TABLE var"
        assert any(v.context == "TOP1" for v in tables), \
            f"physical ref should be in TOP1, got {[(v.name, v.context) for v in tables]}"

    def test_in_scope_ref_still_folds(self):
        """In the CTE's own statement the ref keeps folding (no TABLE var)."""
        r = extract_variables_from_sql(IN_SCOPE_ONLY, "test")
        tables = [v for v in r.variables
                  if v.variable_type == VariableType.TABLE and v.name.lower() == "tmp_loan"]
        ctes = [v for v in r.variables
                if v.variable_type == VariableType.CTE and v.name.lower() == "tmp_loan"]
        assert len(ctes) == 1
        assert not tables, \
            f"in-scope ref must fold onto the CTE (no TABLE var), got {tables}"


class TestCteScopeL2:
    """(c) — same-name CTE vs physical table render as DISTINCT compounds."""

    def test_same_name_cte_and_physical_are_distinct_compounds(self):
        table_nodes, _field_nodes, _model = _classify(TWO_STATEMENT)
        by_label = {}
        for tn in table_nodes.values():
            if (tn.get("table_name") or "").lower() == "tmp_loan":
                by_label.setdefault(tn.get("type"), []).append(tn)
        # One cte_table (TOP0 definition) and one source_table (TOP1 read).
        cte_nodes = by_label.get("cte_table", [])
        phys_nodes = by_label.get("source_table", [])
        assert len(cte_nodes) == 1, f"one cte_table tmp_loan, got {cte_nodes}"
        assert len(phys_nodes) == 1, f"one source_table tmp_loan, got {phys_nodes}"
        cte_ctx = (cte_nodes[0].get("context") or "").split(":join:")[0].split("/")[0]
        phys_ctx = (phys_nodes[0].get("context") or "").split(":join:")[0].split("/")[0]
        assert cte_ctx == "TOP0"
        assert phys_ctx == "TOP1"

    def test_columns_land_on_the_right_compound(self):
        table_nodes, field_nodes, _model = _classify(TWO_STATEMENT)
        # Map compound type → id for the two tmp_loan compounds.
        cte_id = phys_id = None
        for tn in table_nodes.values():
            if (tn.get("table_name") or "").lower() != "tmp_loan":
                continue
            if tn.get("type") == "cte_table":
                cte_id = tn["id"]
            elif tn.get("type") == "source_table":
                phys_id = tn["id"]
        assert cte_id and phys_id

        # Every tmp_loan field chip must be parented to one of the two —
        # the in-scope read (l.loan_id, TOP0) on the cte_table, the
        # out-of-scope read (x.loan_id, TOP1) on the source_table. Both
        # field chips carry the bare label "loan_id", so distinguish by the
        # parent compound.
        loan_fields = [f for f in field_nodes if f.get("label") == "loan_id"]
        parents = {f.get("parent") for f in loan_fields}
        assert cte_id in parents, \
            f"in-scope read's loan_id must be on the cte_table, parents={parents}"
        assert phys_id in parents, \
            f"out-of-scope read's loan_id must be on the source_table, parents={parents}"

    def test_in_scope_only_has_single_compound(self):
        table_nodes, field_nodes, _model = _classify(IN_SCOPE_ONLY)
        tmp_nodes = [tn for tn in table_nodes.values()
                     if (tn.get("table_name") or "").lower() == "tmp_loan"]
        # No physical tmp_loan exists — only the cte_table compound.
        assert [tn.get("type") for tn in tmp_nodes] == ["cte_table"], \
            f"in-scope-only should render a single cte_table, got {[tn.get('type') for tn in tmp_nodes]}"
        cte_id = tmp_nodes[0]["id"]
        # The OUTER read (l.loan_id) folds onto the cte_table. The other
        # loan_id chip is the CTE body's own inner read on `loans` — that is
        # unrelated and stays on its physical table.
        assert any(f.get("label") == "loan_id" and f.get("parent") == cte_id
                   for f in field_nodes), \
            "the in-scope outer read's loan_id must fold onto the cte_table"
