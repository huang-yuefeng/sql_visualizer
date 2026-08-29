"""Tests for variable_extractor.py — extract and classify variables from SQL AST."""

import re
import sys
from pathlib import Path

import pytest

# Ensure backend/ is on the path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.models.variable import VariableType  # noqa: E402
from app.extractor.variable_extractor_v2 import (  # noqa: E402
    _binding_scope,
    _ctx_segments,
    _ctx_within,
    extract_variables_from_sql,
)

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

    def test_alias_qualifier_not_folded_to_physical_spelling(self):
        """A qualified column whose qualifier is a scope-local ALIAS keeps
        its own spelling — it is never folded to a colliding physical
        table's majority spelling (M-E3b)."""
        sql = ("SELECT a.x FROM t1 a;\n"
               "SELECT * FROM A;\n"
               "SELECT * FROM A;\n"
               "SELECT * FROM A;")
        r = extract_variables_from_sql(sql, "case_alias_qual")
        cols = {v.name for v in r.variables
                if v.variable_type == VariableType.COLUMN}
        # a.x keeps the alias spelling; it is NOT folded to A.x
        assert "a.x" in cols, cols
        assert "A.x" not in cols, cols


class TestDerivedReadTwinScope:
    """M2 (2026-08-28): derived-read twins follow lexical scope rules.

    A derived alias is visible from its binding scope AND from any scope
    nested inside it; it is NOT visible across a CTE boundary. The old
    check compared the read against the SUB VAR's own context path, so a
    `p2.col` reference inside a nested scalar subquery never twinned; the
    naive `_scope_top` repair over-matches instead (a CTE-local derived
    `p2` would twin the statement-level JOIN alias `p2` in SUP_M).
    `_binding_scope`/`_ctx_within` give the middle ground.
    """

    NESTED = (
        "INSERT INTO tgt\n"
        "SELECT a.k,\n"
        "       (SELECT MAX(p2.poctcd) FROM ods_hub_lsacmsp z"
        " WHERE z.k = a.k) AS mx\n"
        "FROM (SELECT poctcd, k FROM ods_hub_lsacmsp) p2\n"
        "JOIN src a ON a.k = p2.k;\n"
    )

    CTE_BOUNDARY = (
        "WITH c AS (SELECT k FROM (SELECT k FROM phys_t) p2)\n"
        "INSERT INTO tgt\n"
        "SELECT p2.k, p2.poctcd FROM src_t p2;\n"
    )

    @staticmethod
    def _twins(result):
        """Derived-read twins: qualified COLUMN, non-output, carrying the
        single dotted read it copies (family 2's own registration shape)."""
        return {v.name: v for v in result.variables
                if v.variable_type == VariableType.COLUMN and not v.is_output
                and "." in v.name
                and v.source_columns and len(v.source_columns) == 1
                and "." in v.source_columns[0]}

    def test_deeper_nested_read_still_twins(self):
        """`p2.poctcd` inside the scalar subquery resolves to the derived
        alias bound one scope up (pre-M2 this produced NO twin)."""
        r = extract_variables_from_sql(self.NESTED, "m2_nested")
        twins = self._twins(r)
        assert "ods_hub_lsacmsp.poctcd" in twins, sorted(twins)
        t = twins["ods_hub_lsacmsp.poctcd"]
        assert t.source_columns == ["p2.poctcd"], t.source_columns
        assert t.source_tables == ["ods_hub_lsacmsp"], t.source_tables
        # the twin anchors at the read that produced it
        assert t.line_start > 0

    def test_cte_bound_alias_does_not_leak_to_statement_scope(self):
        """A `p2` derived inside the CTE body must not twin the
        statement-level physical alias `p2` (the _scope_top failure)."""
        r = extract_variables_from_sql(self.CTE_BOUNDARY, "m2_cte_boundary")
        twins = self._twins(r)
        assert not twins, twins

    def test_statement_level_alias_join_still_twins(self):
        """The flagship shape keeps its twins: a JOIN-position derived `p2`
        read from its own FROM scope twins onto the single physical source."""
        sql = ("INSERT INTO tgt\n"
               "SELECT p2.poctcd FROM bdm_x p1\n"
               "JOIN (SELECT poctcd FROM ods_hub_lsacmsp) p2"
               " ON p2.poctcd = p1.k;\n")
        r = extract_variables_from_sql(sql, "m2_join_scope")
        twins = self._twins(r)
        assert "ods_hub_lsacmsp.poctcd" in twins, sorted(twins)


class TestWriteTwinAliasNaming:
    """L4 part 2 (2026-08-28): write-side twins never mint a physical field
    identity from an unaliased projection's auto-name.

    An unaliased expression/literal projection auto-names from a truncated
    SQL-text fragment (`CONCAT'price=',_p.price`, `NULL`, `1`) — not a
    column name. The INSERT column list that WOULD name the write slot is
    not positionally recoverable in the post-walk twin pass (projection
    outputs do not register 1:1 in source order), so such twins are skipped
    rather than fabricated. Aliased projections keep their twins.
    """

    SQL = (
        "INSERT INTO logs (table_name, operation, record_id, old_value,"
        " new_value, changed_by)\n"
        "SELECT 'products', 'UPDATE', p.product_id,\n"
        "       CONCAT('price=', p.price, ',stock=', p.stock),\n"
        "       CONCAT('price=', p.price * 1.1, ',stock=', p.stock - 5),\n"
        "       1\n"
        "FROM products p;\n"
        "INSERT INTO logs2 (a, b)\n"
        "SELECT p.product_id, 1 AS flag FROM products p;\n"
    )

    def test_no_junk_named_write_twins(self):
        r = extract_variables_from_sql(self.SQL, "l4_junk")
        ident = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
        junk = [v.name for v in r.variables
                if v.is_output and "." in v.name and not v.source_columns
                and v.source_tables
                and v.name.split(".", 1)[0] == v.source_tables[0]
                and not ident.match(v.name.rsplit(".", 1)[-1])]
        assert junk == [], junk

    def test_aliased_projections_still_twin(self):
        """A plain column read keeps its write twin; an aliased literal is
        attributed straight to the write target (no twin needed)."""
        r = extract_variables_from_sql(self.SQL, "l4_aliased")
        names = {v.name for v in r.variables
                 if v.is_output and "." in v.name and not v.source_columns
                 and v.source_tables
                 and v.name.split(".", 1)[0] == v.source_tables[0]}
        assert "logs2.product_id" in names, names
        flag = next(v for v in r.variables if v.name == "flag")
        assert flag.source_tables == ["logs2"], flag.source_tables
        assert flag.is_output

    def test_binding_scope_unit_semantics(self):
        """The context-path algebra `_binding_scope`/`_ctx_within` rely on:
        the trailing alias + its own slot marker are decoration; a scope
        segment merely NAMED `subq` is not; CTE/statement boundaries hold."""
        cases = [
            ("TOP0/subq/p2", "p2", "TOP0"),                    # FROM slot
            ("TOP0:join:p2", "p2", "TOP0"),                    # JOIN slot
            ("CTE{c}/subq/p2", "p2", "CTE{c}"),                # inside a CTE
            ("TOP0/subq1/subq:join:p2", "p2", "TOP0/subq1/subq"),
            ("TOP0", "source", "TOP0"),                        # MERGE USING
            ("CTE{merchant_chargeback_stats}", "latest_risk_score",
             "CTE{merchant_chargeback_stats}"),                # CTE reference
        ]
        for ctx, alias, want in cases:
            assert _binding_scope(ctx, alias) == want, (ctx, alias)
        assert _ctx_segments("TOP0/subq1/subq:join:p2") == \
            ["TOP0", "subq1", "subq", "join", "p2"]
        assert _ctx_within("TOP0/subq1", "TOP0")           # nested
        assert _ctx_within("CTE{c}:join:x", "CTE{c}")      # CTE-internal
        assert not _ctx_within("TOP01", "TOP0")            # distinct stmt
        assert not _ctx_within("CTE{ab}", "CTE{a}")        # distinct CTE
        assert not _ctx_within("TOP0", "CTE{c}")           # CTE boundary
