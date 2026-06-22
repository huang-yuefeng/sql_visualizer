"""Tests for variable_extractor.py — extract and classify variables from SQL AST."""

import sys
from pathlib import Path

import pytest

# Ensure backend/ is on the path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.models.variable import VariableType  # noqa: E402
from app.extractor.variable_extractor_v2 import extract_variables_from_sql  # noqa: E402

TEST_DATA_DIR = Path(__file__).resolve().parent / "test_data"
SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples"


def read_sql(filename: str) -> str:
    """Read a SQL test fixture file (checks test_data/ first, then samples/)."""
    for base in [TEST_DATA_DIR, SAMPLES_DIR]:
        path = base / filename
        if path.exists():
            return path.read_text()
    raise FileNotFoundError(f"SQL fixture not found: {filename}")


# ── Test Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def sql_simple():
    return read_sql("sample_variable_simple.sql")


@pytest.fixture
def sql_cte_chain():
    return read_sql("sample_cte_chain.sql")


@pytest.fixture
def sql_window():
    return read_sql("sample_window_funcs.sql")


@pytest.fixture
def sql_merge():
    return read_sql("sample_merge.sql")


@pytest.fixture
def sql_union():
    return read_sql("sample_union.sql")


@pytest.fixture
def sql_case_nested():
    return read_sql("sample_case_nested.sql")


# ── Simple Variable Extraction ─────────────────────────────────────────

class TestSimpleVariableExtraction:
    """Test basic variable extraction from a simple SELECT."""

    def test_extract_database_tables(self, sql_simple):
        """Physical database tables should be identified."""
        result = extract_variables_from_sql(sql_simple, "test_simple")
        tables = [v for v in result.variables if v.variable_type == VariableType.TABLE]
        table_names = [t.name for t in tables]
        assert "gps_settlement_batches" in table_names, \
            f"Should find gps_settlement_batches, got: {table_names}"

    def test_extract_intermediate_aliases(self, sql_simple):
        """Aliased column references should be TABLE_COLUMN; computed expressions are INTERMEDIATE."""
        result = extract_variables_from_sql(sql_simple, "test_simple")
        # 'batch_total_amount' = sb.total_amount AS batch_total_amount → TABLE_COLUMN (bare column alias)
        # 'record_type' = 'SETTLEMENT' AS record_type → LITERAL
        columns = [v for v in result.variables if v.variable_type == VariableType.COLUMN]
        col_names = [v.name for v in columns]
        assert "batch_total_amount" in col_names, \
            f"Should find 'batch_total_amount' as TABLE_COLUMN, got: {col_names}"

    def test_variable_ids_are_unique(self, sql_simple):
        """Every variable should have a unique ID."""
        result = extract_variables_from_sql(sql_simple, "test_simple")
        ids = [v.id for v in result.variables]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {len(ids)} != {len(set(ids))}"

    def test_all_variables_have_valid_type(self, sql_simple):
        """Every variable should have a valid VariableType."""
        result = extract_variables_from_sql(sql_simple, "test_simple")
        assert len(result.variables) > 0, "Should extract at least some variables"
        for v in result.variables:
            assert v.variable_type in VariableType, \
                f"Invalid type for {v.id}: {v.variable_type}"

    def test_variables_have_source_info(self, sql_simple):
        """Intermediate variables should carry source column info."""
        result = extract_variables_from_sql(sql_simple, "test_simple")
        intermediate = next(
            (v for v in result.variables if v.name == "batch_total_amount"), None
        )
        if intermediate:
            assert len(intermediate.source_columns) > 0 or len(intermediate.source_tables) > 0, \
                f"Variable 'batch_total_amount' should have source info"


# ── CTE Variable Extraction ────────────────────────────────────────────

class TestCTEVariableExtraction:
    """Test extraction of CTE-related variables."""

    def test_extract_cte_tables(self, sql_cte_chain):
        """CTE aliases should be identified as CTE_TABLE type."""
        result = extract_variables_from_sql(sql_cte_chain, "test_cte")
        cte_tables = [v for v in result.variables if v.variable_type == VariableType.CTE]
        cte_names = [v.name for v in cte_tables]
        assert "batch_summary" in cte_names, f"Got CTE tables: {cte_names}"
        assert "recon_data" in cte_names, f"Got CTE tables: {cte_names}"

    def test_extract_cte_columns(self, sql_cte_chain):
        """Variables defined inside a CTE should appear with CTE context.
        They keep their detailed type (table_column, aggregate, etc.) rather
        than all being collapsed to CTE_COLUMN."""
        result = extract_variables_from_sql(sql_cte_chain, "test_cte")
        # Variables inside CTE context should exist — check by name regardless of type
        cte_context_vars = [v for v in result.variables
                            if v.defined_in and v.defined_in.startswith("CTE{")]
        cte_var_names = [v.name for v in cte_context_vars]
        assert "batch_total_amount" in cte_var_names, \
            f"Should find 'batch_total_amount' in CTE context, got: {cte_var_names}"
        assert "actual_txn_count" in cte_var_names, \
            f"Should find 'actual_txn_count' in CTE context, got: {cte_var_names}"
        # CTE columns should have diverse types, not all cte_column
        cte_types = set(v.variable_type for v in cte_context_vars)
        assert len(cte_types) >= 2, \
            f"CTE context should have multiple variable types, got: {cte_types}"


# ── Window Function Extraction ─────────────────────────────────────────

class TestWindowFunctionExtraction:
    """Test extraction of window function variables."""

    def test_extract_window_results(self, sql_window):
        """Window functions should create WINDOW_RESULT variables."""
        result = extract_variables_from_sql(sql_window, "test_window")
        windows = [v for v in result.variables if v.variable_type == VariableType.WINDOW]
        window_names = [v.name for v in windows]
        for name in ["txn_row_num", "cumulative_amount", "prev_amount", "next_amount", "amount_rank"]:
            assert name in window_names, f"Should find '{name}' in {window_names}"


# ── CASE Expression Extraction ─────────────────────────────────────────

class TestCaseExtraction:
    """Test extraction of CASE expression variables."""

    def test_extract_case_results(self, sql_case_nested):
        """CASE expressions should create CASE_RESULT variables."""
        result = extract_variables_from_sql(sql_case_nested, "test_case")
        cases = [v for v in result.variables if v.variable_type == VariableType.CASE]
        case_names = [v.name for v in cases]
        assert "risk_category" in case_names, f"Got CASE results: {case_names}"


# ── Function Result Extraction ─────────────────────────────────────────

class TestFunctionResultExtraction:
    """Test extraction of function call variables."""

    def test_extract_function_results(self, sql_case_nested):
        """COALESCE/CAST/JSON_EXTRACT should create FUNCTION_RESULT variables."""
        result = extract_variables_from_sql(sql_case_nested, "test_case")
        funcs = [v for v in result.variables if v.variable_type == VariableType.TRANSFORM]
        func_names = [v.name for v in funcs]
        assert "aml_review_status" in func_names, f"Got function results: {func_names}"


# ── MERGE Statement Extraction ─────────────────────────────────────────

class TestMergeExtraction:
    """Test extraction from MERGE statements."""

    def test_merge_produces_variables(self, sql_merge):
        """MERGE statements should be handled without error and produce variables."""
        result = extract_variables_from_sql(sql_merge, "test_merge")
        assert len(result.variables) > 0, "Should extract variables from MERGE"


# ── UNION Extraction ───────────────────────────────────────────────────

class TestUnionExtraction:
    """Test extraction from UNION statements."""

    def test_union_produces_variables(self, sql_union):
        """UNION ALL statements should be handled without error."""
        result = extract_variables_from_sql(sql_union, "test_union")
        assert len(result.variables) > 0, "Should extract variables from UNION query"
        cte_tables = [v for v in result.variables if v.variable_type == VariableType.CTE]
        cte_names = [v.name for v in cte_tables]
        assert "merchant_activity" in cte_names or "combined_activity" in cte_names, \
            f"Should find CTEs, got: {cte_names}"


# ── Integration Tests ──────────────────────────────────────────────────

class TestVariableExtractorIntegration:
    """End-to-end tests against GPS financial samples."""

    def test_fin_query1_produces_variables(self, request):
        """Should extract variables from reconciliation query."""
        sql = read_sql("financial/fin_query1_reconciliation.sql")
        result = extract_variables_from_sql(sql, "fin_query1")
        assert len(result.variables) > 0, "Should extract variables"
        types = set(v.variable_type for v in result.variables)
        assert len(types) >= 3, f"Should have >=3 variable types, got {len(types)}: {types}"

    def test_fin_query2_produces_variables(self, request):
        """Should handle complex fee calculation query."""
        sql = read_sql("financial/fin_query2_fee_calculation.sql")
        result = extract_variables_from_sql(sql, "fin_query2")
        assert len(result.variables) > 0, "Should extract variables"

    def test_fin_query3_produces_variables(self, request):
        """Should handle account balance query."""
        sql = read_sql("financial/fin_query3_account_balance.sql")
        result = extract_variables_from_sql(sql, "fin_query3")
        assert len(result.variables) > 0, "Should extract variables"

    def test_fin_query5_produces_variables(self, request):
        """Should handle union risk report query."""
        sql = read_sql("financial/fin_query5_union_risk_report.sql")
        result = extract_variables_from_sql(sql, "fin_query5")
        assert len(result.variables) > 0, "Should extract variables"

    def test_variable_count_reasonable(self, request):
        """Variable count should be reasonable (not empty, not excessive)."""
        sql = read_sql("financial/fin_query1_reconciliation.sql")
        result = extract_variables_from_sql(sql, "fin_query1")
        assert 5 <= len(result.variables) <= 500, \
            f"Variable count {len(result.variables)} should be between 5 and 500"
