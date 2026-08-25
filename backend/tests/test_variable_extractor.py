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


# ── ISSUE-4: case-insensitive physical-table identity ───────────────────

class TestCaseSensitivePhysicalTableIdentity:
    """Physical table names are script-global and case-insensitive; the
    canonical spelling is the majority spelling of the source's identifier
    tokens (ties → lowercase, then first-seen). Alias/CTE/derived handles
    stay scope-local and are never folded globally."""

    def test_mixed_case_table_folds_to_majority_spelling(self):
        """`east5_stzfxxb` vs `EAST5_STZFXXB` → one canonical lowercase node.

        The token stream sees 3 lowercase (INSERT target + ALTER + op-log
        FROM) vs 1 uppercase (op-log column qualifier), so lowercase is the
        genuine majority spelling — not a tie-break fallback.
        """
        sql = (
            "INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)')\n"
            "SELECT a.ccy_code FROM bdm_acc_entrusted_payment a;\n"
            "ALTER TABLE east5_stzfxxb ADD PARTITION (p_dt='x');\n"
            "INSERT INTO TABLE rrcdm_job_log "
            "SELECT EAST5_STZFXXB.p_dt FROM east5_stzfxxb;"
        )
        r = extract_variables_from_sql(sql, "case_mixed")
        table_names = {
            v.name for v in r.variables
            if v.variable_type == VariableType.TABLE
        }
        # The uppercase spelling must be folded away everywhere.
        assert "EAST5_STZFXXB" not in table_names, table_names
        assert "east5_stzfxxb" in table_names, table_names
        # Column qualifier + schema evidence also carry the canonical case.
        column_names = {
            v.name for v in r.variables
            if v.variable_type == VariableType.COLUMN
        }
        assert "east5_stzfxxb.p_dt" in column_names, column_names
        assert not any(n.startswith("EAST5_STZFXXB.") for n in column_names), column_names
        schemas = r.resolution_stats["script_schemas"]
        assert "east5_stzfxxb" in schemas, schemas
        assert "EAST5_STZFXXB" not in schemas, schemas

    def test_mixed_case_tie_prefers_lowercase(self):
        """A 1:1 case tie falls back to the lowercase spelling."""
        sql = (
            "INSERT OVERWRITE TABLE my_tbl SELECT x FROM src;\n"
            "SELECT * FROM MY_TBL;"
        )
        r = extract_variables_from_sql(sql, "case_tie")
        table_names = {v.name for v in r.variables
                       if v.variable_type == VariableType.TABLE}
        assert "my_tbl" in table_names, table_names
        assert "MY_TBL" not in table_names, table_names

    def test_alias_case_folds_within_scope_only(self):
        """Alias `a` vs `A` is case-insensitive WITHIN a statement, but an
        alias `a` bound to a different table in another statement never
        merges (scope-locality — the two `a` handles stay distinct)."""
        sql = "SELECT a.x, A.y FROM t1 a;\nSELECT a.z FROM t2 a;"
        r = extract_variables_from_sql(sql, "case_alias")
        cols = {v.name: v for v in r.variables
                if v.variable_type == VariableType.COLUMN}
        # Same scope + different case → same physical table attribution.
        assert cols["a.x"].source_tables == ["t1"], cols["a.x"]
        assert cols["A.y"].source_tables == ["t1"], cols["A.y"]
        # Different scope + same alias spelling → the OTHER physical table.
        assert cols["a.z"].source_tables == ["t2"], cols["a.z"]

    def test_alias_colliding_with_physical_table_not_folded(self):
        """An alias whose spelling case-collides with a physical table keeps
        its own scope-local case — it is never folded to the physical
        majority spelling (R-1)."""
        sql = (
            "SELECT * FROM EAST5_STZFXXB AS east5_stzfxxb;\n"
            "SELECT * FROM EAST5_STZFXXB;"
        )
        r = extract_variables_from_sql(sql, "case_alias_collide")
        tables = {v.name: v for v in r.variables
                  if v.variable_type == VariableType.TABLE}
        # the alias (alias_of set) keeps its lowercase spelling — NOT folded
        # to the physical majority spelling EAST5_STZFXXB
        alias_names = {n for n, v in tables.items() if v.alias_of is not None}
        assert alias_names == {"east5_stzfxxb"}, alias_names
        # the physical table folds to its uppercase majority spelling
        physical = {n for n, v in tables.items() if v.alias_of is None}
        assert physical == {"EAST5_STZFXXB"}, physical

    def test_synthetic_alias_colliding_with_physical_table_not_folded(self):
        """A LATERAL/VALUES/UNNEST alias whose spelling collides with a
        physical table keeps its own case — it never folds to the physical
        majority spelling (R-1 synthetic-alias path)."""
        sql = (
            "SELECT * FROM V;\n"
            "SELECT * FROM V;\n"
            "SELECT * FROM (VALUES (1,2)) AS v;"
        )
        r = extract_variables_from_sql(sql, "case_values_collide")
        tables = {v.name: v for v in r.variables
                  if v.variable_type == VariableType.TABLE}
        alias_names = {n for n, v in tables.items() if v.is_alias_handle}
        assert alias_names == {"v"}, alias_names
        # the VALUES alias keeps its own lowercase spelling — not folded to V
        assert tables["v"].source_tables == ["⟐ values"], tables["v"].source_tables

    def test_insert_target_alias_colliding_with_physical_table_not_folded(self):
        """An INSERT-target alias whose spelling collides with a physical
        table keeps its own case (R-1 INSERT-alias path)."""
        sql = "SELECT * FROM V; SELECT * FROM V; INSERT INTO T AS v SELECT 1;"
        r = extract_variables_from_sql(sql, "case_insert_alias_collide")
        tables = {v.name: v for v in r.variables
                  if v.variable_type == VariableType.TABLE}
        alias_names = {n for n, v in tables.items() if v.is_alias_handle}
        assert alias_names == {"v"}, alias_names
        # the INSERT alias keeps its own spelling, sourced to its target T
        assert tables["v"].source_tables == ["T"], tables["v"].source_tables
