"""Tests for the 3 new complex GPS financial SQL samples + edge case coverage."""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.models.variable import VariableType  # noqa: E402
from app.extractor.variable_extractor_v2 import extract_variables_from_sql  # noqa: E402
from app.extractor.dependency_graph import build_dependency_graph  # noqa: E402

SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples"


def _read(filename: str) -> str:
    path = SAMPLES_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Sample not found: {path}")
    return path.read_text()


# ── New Complex Sample Tests ────────────────────────────────────────────

class TestChargebackAnalysis:
    """fin_query6: chargeback analysis with scalar subqueries, multi-level CASE, EXISTS."""

    @pytest.fixture
    def sql(self):
        return _read("financial/fin_query6_chargeback_analysis.sql")

    def test_produces_variables(self, sql):
        result = extract_variables_from_sql(sql, "fin_query6")
        assert len(result.variables) >= 50, f"Expected >=50 vars, got {len(result.variables)}"

    def test_has_subquery_results(self, sql):
        """Scalar subqueries with aliases should produce SUBQUERY_RESULT type."""
        result = extract_variables_from_sql(sql, "fin_query6")
        subquery_vars = [v for v in result.variables
                         if v.variable_type == VariableType.SUBQUERY_RESULT]
        assert len(subquery_vars) >= 1, f"Should have subquery_result vars, got {len(subquery_vars)}"

    def test_has_case_results(self, sql):
        """Nested CASE expressions should produce CASE_RESULT type."""
        result = extract_variables_from_sql(sql, "fin_query6")
        case_vars = [v for v in result.variables
                     if v.variable_type == VariableType.CASE_RESULT]
        assert len(case_vars) >= 3, f"Should have >=3 case_result vars, got {len(case_vars)}"

    def test_has_cte_tables(self, sql):
        result = extract_variables_from_sql(sql, "fin_query6")
        ctes = [v for v in result.variables if v.variable_type == VariableType.CTE_TABLE]
        cte_names = [v.name for v in ctes]
        assert "merchant_chargeback_stats" in cte_names
        assert "risk_categorized" in cte_names

    def test_cte_columns_preserve_types(self, sql):
        """CTE columns should keep their detailed types (not all collapsed to cte_column)."""
        result = extract_variables_from_sql(sql, "fin_query6")
        types_in_cte_context = set()
        for v in result.variables:
            if v.defined_in and v.defined_in.startswith("CTE:"):
                types_in_cte_context.add(v.variable_type)
        # Should have more than just CTE_COLUMN — windows, aggregates, etc. should be preserved
        assert len(types_in_cte_context) >= 3, \
            f"CTE context should have diverse types, got: {types_in_cte_context}"


class TestInterchangeOptimization:
    """fin_query7: interchange fee optimization with window frames, self-joins, JSON extraction."""

    @pytest.fixture
    def sql(self):
        return _read("financial/fin_query7_interchange_optimization.sql")

    def test_produces_variables(self, sql):
        result = extract_variables_from_sql(sql, "fin_query7")
        assert len(result.variables) >= 80, f"Expected >=80 vars, got {len(result.variables)}"

    def test_has_window_results(self, sql):
        """Window functions (ROW_NUMBER, AVG OVER, LAG, LEAD) should be detected."""
        result = extract_variables_from_sql(sql, "fin_query7")
        window_vars = [v for v in result.variables
                       if v.variable_type == VariableType.WINDOW_RESULT]
        assert len(window_vars) >= 5, \
            f"Should have >=5 window_result vars, got {len(window_vars)}"

    def test_has_function_results(self, sql):
        """JSON_EXTRACT, CAST operations should produce FUNCTION_RESULT."""
        result = extract_variables_from_sql(sql, "fin_query7")
        func_vars = [v for v in result.variables
                     if v.variable_type == VariableType.FUNCTION_RESULT]
        assert len(func_vars) >= 8, \
            f"Should have >=8 function_result vars, got {len(func_vars)}"

    def test_has_aggregate_in_window(self, sql):
        """Aggregates used in window functions should be AGGREGATE type."""
        result = extract_variables_from_sql(sql, "fin_query7")
        agg_vars = [v for v in result.variables
                    if v.variable_type == VariableType.AGGREGATE]
        assert len(agg_vars) >= 3, \
            f"Should have >=3 aggregate vars, got {len(agg_vars)}"

    def test_dependency_graph_has_edges(self, sql):
        result = extract_variables_from_sql(sql, "fin_query7")
        deps = build_dependency_graph(result, sql)
        assert len(deps) >= 10, f"Should have >=10 dependencies, got {len(deps)}"


class TestMultiPartySettlement:
    """fin_query8: multi-party settlement with UNION ALL, complex MERGE, 5-table JOINs."""

    @pytest.fixture
    def sql(self):
        return _read("financial/fin_query8_multi_party_settlement.sql")

    def test_produces_variables(self, sql):
        result = extract_variables_from_sql(sql, "fin_query8")
        assert len(result.variables) >= 80, f"Expected >=80 vars, got {len(result.variables)}"

    def test_has_union_branches(self, sql):
        """UNION ALL branches should produce UNION_BRANCH type."""
        result = extract_variables_from_sql(sql, "fin_query8")
        union_vars = [v for v in result.variables
                      if v.variable_type == VariableType.UNION_BRANCH]
        assert len(union_vars) >= 1, \
            f"Should have >=1 union_branch vars, got {len(union_vars)}"

    def test_has_literal_variables(self, sql):
        """String literals in SELECT should produce LITERAL type."""
        result = extract_variables_from_sql(sql, "fin_query8")
        literal_vars = [v for v in result.variables
                        if v.variable_type == VariableType.LITERAL]
        assert len(literal_vars) >= 3, \
            f"Should have >=4 literal vars (leg types), got {len(literal_vars)}"

    def test_has_window_and_aggregate(self, sql):
        """Should have both window_result and aggregate types in one query."""
        result = extract_variables_from_sql(sql, "fin_query8")
        types = set(v.variable_type for v in result.variables)
        assert VariableType.WINDOW_RESULT in types, "Should have window_result"
        assert VariableType.AGGREGATE in types, "Should have aggregate"

    def test_subquery_result_present(self, sql):
        """Correlated scalar subqueries should appear."""
        result = extract_variables_from_sql(sql, "fin_query8")
        sub_vars = [v for v in result.variables
                    if v.variable_type == VariableType.SUBQUERY_RESULT]
        assert len(sub_vars) >= 1, \
            f"Should have subquery_result vars from FX lookups, got {len(sub_vars)}"


# ── Edge Case Tests ──────────────────────────────────────────────────────

class TestEdgeCases:
    """Tests for edge cases fixed during extractor improvements."""

    def test_unaliased_aggregate_extracted(self):
        """SUM(amount) without AS alias should still create a variable."""
        sql = "SELECT SUM(t.amount) FROM gps_transactions t GROUP BY t.settlement_batch_id"
        result = extract_variables_from_sql(sql, "test")
        aggs = [v for v in result.variables if v.variable_type == VariableType.AGGREGATE]
        assert len(aggs) >= 1, f"Un-aliased aggregate should be extracted, got: {[v.name for v in aggs]}"

    def test_unaliased_bare_column_extracted(self):
        """SELECT col (no alias) should create a TABLE_COLUMN variable."""
        sql = "SELECT settlement_batch_id, amount FROM gps_transactions"
        result = extract_variables_from_sql(sql, "test")
        cols = [v for v in result.variables if v.variable_type == VariableType.TABLE_COLUMN]
        assert len(cols) >= 2, f"Bare columns should be extracted, got {len(cols)}: {[v.name for v in cols]}"

    def test_subquery_not_double_classified(self):
        """A scalar subquery should be SUBQUERY_RESULT, not also AGGREGATE."""
        sql = "SELECT (SELECT MAX(amount) FROM gps_transactions WHERE account_id = a.account_id) AS max_txn FROM gps_accounts a"
        result = extract_variables_from_sql(sql, "test")
        sub_vars = [v for v in result.variables if v.variable_type == VariableType.SUBQUERY_RESULT]
        agg_vars = [v for v in result.variables if v.variable_type == VariableType.AGGREGATE]
        # The subquery result should not also be classified as aggregate
        sub_ids = {v.id for v in sub_vars}
        agg_ids = {v.id for v in agg_vars}
        overlap = sub_ids & agg_ids
        assert len(overlap) == 0, \
            f"No variable should be both SUBQUERY_RESULT and AGGREGATE, overlap: {overlap}"

    def test_string_literals_in_insert_select(self):
        """String literals in INSERT INTO ... SELECT should be LITERAL type."""
        sql = _read("financial/fin_query4_merge_upsert.sql")
        result = extract_variables_from_sql(sql, "test")
        literals = [v for v in result.variables if v.variable_type == VariableType.LITERAL]
        # INSERT INTO ... SELECT has literal strings like 'ACCOUNT', 'BALANCE_UPDATE'
        assert len(literals) >= 2, f"Should find string literals in INSERT SELECT, got {len(literals)}"

    def test_merge_target_detected(self):
        """MERGE INTO target table should be MERGE_TARGET type."""
        sql = _read("financial/fin_query4_merge_upsert.sql")
        result = extract_variables_from_sql(sql, "test")
        merge_targets = [v for v in result.variables if v.variable_type == VariableType.MERGE_TARGET]
        target_names = [v.name for v in merge_targets]
        assert "gps_accounts" in target_names, \
            f"Should find gps_accounts as MERGE_TARGET, got: {target_names}"


# ── Global Type Coverage ────────────────────────────────────────────────

class TestGlobalTypeCoverage:
    """Verify all 13 variable types appear across the 8 GPS financial samples."""

    ALL_TYPES = {
        VariableType.DATABASE_TABLE,
        VariableType.TABLE_COLUMN,
        VariableType.CTE_TABLE,
        VariableType.CTE_COLUMN,
        VariableType.INTERMEDIATE,
        VariableType.WINDOW_RESULT,
        VariableType.AGGREGATE,
        VariableType.CASE_RESULT,
        VariableType.FUNCTION_RESULT,
        VariableType.LITERAL,
        VariableType.MERGE_TARGET,
        VariableType.UNION_BRANCH,
        VariableType.SUBQUERY_RESULT,
    }

    def test_all_types_covered(self):
        """After processing all 8 samples, every VariableType should appear at least once."""
        all_queries = [
            "financial/fin_query1_reconciliation.sql",
            "financial/fin_query2_fee_calculation.sql",
            "financial/fin_query3_account_balance.sql",
            "financial/fin_query4_merge_upsert.sql",
            "financial/fin_query5_union_risk_report.sql",
            "financial/fin_query6_chargeback_analysis.sql",
            "financial/fin_query7_interchange_optimization.sql",
            "financial/fin_query8_multi_party_settlement.sql",
        ]

        global_types = set()
        for fname in all_queries:
            sql = _read(fname)
            result = extract_variables_from_sql(sql, fname)
            global_types.update(v.variable_type for v in result.variables)

        missing = self.ALL_TYPES - global_types
        assert not missing, \
            f"Missing types across 8 samples: {[m.value for m in missing]}\nFound: {sorted(t.value for t in global_types)}"

    def test_every_query_has_multiple_types(self):
        """Every query should have at least 4 different variable types."""
        all_queries = [
            "financial/fin_query1_reconciliation.sql",
            "financial/fin_query2_fee_calculation.sql",
            "financial/fin_query3_account_balance.sql",
            "financial/fin_query4_merge_upsert.sql",
            "financial/fin_query5_union_risk_report.sql",
            "financial/fin_query6_chargeback_analysis.sql",
            "financial/fin_query7_interchange_optimization.sql",
            "financial/fin_query8_multi_party_settlement.sql",
        ]
        for fname in all_queries:
            sql = _read(fname)
            result = extract_variables_from_sql(sql, fname)
            types = set(v.variable_type for v in result.variables)
            assert len(types) >= 4, \
                f"{fname}: should have >=4 types, got {len(types)}: {sorted(t.value for t in types)}"

    def test_total_variable_count(self):
        """All 8 queries combined should produce >=500 variables."""
        all_queries = [
            "financial/fin_query1_reconciliation.sql",
            "financial/fin_query2_fee_calculation.sql",
            "financial/fin_query3_account_balance.sql",
            "financial/fin_query4_merge_upsert.sql",
            "financial/fin_query5_union_risk_report.sql",
            "financial/fin_query6_chargeback_analysis.sql",
            "financial/fin_query7_interchange_optimization.sql",
            "financial/fin_query8_multi_party_settlement.sql",
        ]
        total = 0
        for fname in all_queries:
            sql = _read(fname)
            result = extract_variables_from_sql(sql, fname)
            total += len(result.variables)
        assert total >= 500, f"Total variables across 8 scripts should be >=500, got {total}"
