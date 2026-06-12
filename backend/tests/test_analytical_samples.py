"""Tests for analytical SQL patterns inspired by real-world data analysis repos."""

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


# ── Cohort Retention (TheLook Ecommerce inspired) ────────────────────

class TestMerchantCohortRetention:
    """fin_query11: monthly cohort retention with month_number, DATE_DIFF, PERIOD_DIFF."""

    @pytest.fixture
    def sql(self):
        return _read("financial/fin_query11_merchant_cohort_retention.sql")

    def test_produces_variables(self, sql):
        result = extract_variables_from_sql(sql, "fin_query11")
        assert len(result.variables) >= 60, f"Got {len(result.variables)} vars"

    def test_has_cohort_month_field(self, sql):
        """Cohort month identifier should appear as a table_column."""
        result = extract_variables_from_sql(sql, "fin_query11")
        cohort_vars = [v for v in result.variables if "cohort_month" in v.name]
        assert len(cohort_vars) >= 2, f"Got cohort vars: {[v.name for v in cohort_vars]}"

    def test_has_retention_rate(self, sql):
        """Retention rate percentage should be computed."""
        result = extract_variables_from_sql(sql, "fin_query11")
        retention_vars = [v for v in result.variables if "retention_rate" in v.name]
        assert len(retention_vars) >= 1, f"Got retention rate vars: {[v.name for v in retention_vars]}"

    def test_has_month_number(self, sql):
        """Month offset from cohort should be computed."""
        result = extract_variables_from_sql(sql, "fin_query11")
        month_vars = [v for v in result.variables if "month_number" in v.name]
        assert len(month_vars) >= 1

    def test_has_lag_for_volume_change(self, sql):
        """LAG window function for MoM volume change should be detected."""
        result = extract_variables_from_sql(sql, "fin_query11")
        window_vars = [v for v in result.variables if v.variable_type == VariableType.WINDOW]
        assert len(window_vars) >= 1, f"Should have LAG window, got {len(window_vars)}"


# ── Revenue Waterfall (SaaS MRR inspired) ─────────────────────────────

class TestRevenueWaterfall:
    """fin_query12: MRR waterfall with expansion/contraction/churn/reactivation."""

    @pytest.fixture
    def sql(self):
        return _read("financial/fin_query12_revenue_waterfall.sql")

    def test_produces_variables(self, sql):
        result = extract_variables_from_sql(sql, "fin_query12")
        assert len(result.variables) >= 50, f"Got {len(result.variables)} vars"

    def test_has_mrr_components(self, sql):
        """Should detect expansion_mrr, contraction_mrr, churned_mrr, new_mrr, reactivation_mrr."""
        result = extract_variables_from_sql(sql, "fin_query12")
        mrr_vars = [v for v in result.variables if "_mrr" in v.name]
        component_names = {v.name for v in mrr_vars}
        expected = {"expansion_mrr", "contraction_mrr", "churned_mrr", "new_mrr", "reactivation_mrr", "mrr"}
        found = expected & component_names
        assert len(found) >= 5, f"Missing MRR components: {expected - found}, got: {sorted(component_names)}"

    def test_has_retention_rates(self, sql):
        """Should compute net_revenue_retention_pct and gross_revenue_retention_pct."""
        result = extract_variables_from_sql(sql, "fin_query12")
        retention_vars = [v for v in result.variables if "retention_pct" in v.name]
        assert len(retention_vars) >= 2, f"Got retention vars: {[v.name for v in retention_vars]}"

    def test_has_yoy_lag(self, sql):
        """YoY comparison should use LAG(,12) window function."""
        result = extract_variables_from_sql(sql, "fin_query12")
        yoy_vars = [v for v in result.variables
                    if "LAG(" in v.sql_expression.upper() and ", 12)" in v.sql_expression]
        assert len(yoy_vars) >= 1, f"Should have LAG(,12) for YoY, got {len(yoy_vars)}"

    def test_has_date_add(self, sql):
        """DATE_ADD with INTERVAL for calendar navigation should be detected."""
        result = extract_variables_from_sql(sql, "fin_query12")
        dateadd_vars = [v for v in result.variables if "DATE_ADD" in v.sql_expression.upper()]
        assert len(dateadd_vars) >= 2, f"Got DATE_ADD vars: {len(dateadd_vars)}"


# ── RFM Segmentation ──────────────────────────────────────────────────

class TestRFMSegmentation:
    """fin_query13: RFM segmentation with NTILE, CONCAT, PERCENT_RANK."""

    @pytest.fixture
    def sql(self):
        return _read("financial/fin_query13_rfm_segmentation.sql")

    def test_produces_variables(self, sql):
        result = extract_variables_from_sql(sql, "fin_query13")
        assert len(result.variables) >= 50, f"Got {len(result.variables)} vars"

    def test_has_ntile_scores(self, sql):
        """NTILE(5) should appear as WINDOW_RESULT for R, F, M scores."""
        result = extract_variables_from_sql(sql, "fin_query13")
        ntile_vars = [v for v in result.variables if "NTILE" in v.sql_expression.upper()]
        assert len(ntile_vars) >= 3, \
            f"Should have NTILE for r_score, f_score, m_score, got {len(ntile_vars)}: {[v.name for v in ntile_vars]}"

    def test_has_concat_rfm_score(self, sql):
        """CONCAT for combined RFM score should be detected."""
        result = extract_variables_from_sql(sql, "fin_query13")
        concat_vars = [v for v in result.variables if "CONCAT" in v.sql_expression.upper()]
        assert len(concat_vars) >= 1, f"Should have CONCAT for rfm_score, got {len(concat_vars)}"

    def test_has_rfm_segments(self, sql):
        """RFM segment labels (CHAMPIONS, LOYAL, AT_RISK, etc.) should be CASE_RESULT."""
        result = extract_variables_from_sql(sql, "fin_query13")
        case_vars = [v for v in result.variables if v.variable_type == VariableType.CASE]
        assert len(case_vars) >= 3, \
            f"Should have rfm_segment + churn_risk + revenue_tier CASEs, got {len(case_vars)}"

    def test_has_percent_rank(self, sql):
        """PERCENT_RANK within segment should be detected."""
        result = extract_variables_from_sql(sql, "fin_query13")
        pct_rank_vars = [v for v in result.variables if "PERCENT_RANK" in v.sql_expression.upper()]
        assert len(pct_rank_vars) >= 1, f"Should have PERCENT_RANK, got {len(pct_rank_vars)}"

    def test_has_recency_frequency_monetary(self, sql):
        """Should have recency_days, frequency, monetary_volume variables."""
        result = extract_variables_from_sql(sql, "fin_query13")
        rfm_vars = [v for v in result.variables
                    if v.name in ("recency_days", "frequency", "monetary_volume")]
        assert len(rfm_vars) >= 3, f"Got RFM vars: {[v.name for v in rfm_vars]}"


# ── Cross-Pattern Coverage ─────────────────────────────────────────────

class TestAnalyticalConstructs:
    """Verify new SQL constructs from analytical patterns are handled."""

    def test_ntile_parsed_as_window(self):
        """NTILE(N) should be classified as WINDOW_RESULT."""
        sql = _read("financial/fin_query13_rfm_segmentation.sql")
        result = extract_variables_from_sql(sql, "test")
        ntile_vars = [v for v in result.variables
                      if "NTILE" in v.sql_expression.upper()
                      and v.variable_type == VariableType.WINDOW]
        assert len(ntile_vars) >= 3

    def test_date_add_parsed_as_function(self):
        """DATE_ADD() with INTERVAL should be classified."""
        sql = _read("financial/fin_query12_revenue_waterfall.sql")
        result = extract_variables_from_sql(sql, "test")
        dateadd_vars = [v for v in result.variables if "DATE_ADD" in v.sql_expression.upper()]
        assert len(dateadd_vars) >= 2

    def test_period_diff_detected(self):
        """PERIOD_DIFF for month offset should be detected."""
        sql = _read("financial/fin_query11_merchant_cohort_retention.sql")
        result = extract_variables_from_sql(sql, "test")
        period_vars = [v for v in result.variables if "PERIOD_DIFF" in v.sql_expression.upper()]
        assert len(period_vars) >= 1

    def test_yoy_lag_12_detected(self):
        """LAG(column, 12) for year-over-year comparison should be detected."""
        sql = _read("financial/fin_query12_revenue_waterfall.sql")
        result = extract_variables_from_sql(sql, "test")
        yoy_vars = [v for v in result.variables
                    if v.variable_type == VariableType.WINDOW
                    and ", 12)" in v.sql_expression]
        assert len(yoy_vars) >= 1
