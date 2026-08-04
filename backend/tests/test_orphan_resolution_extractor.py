"""R20: extractor-side orphan resolution (S1/S2/S3/S5/S6) + resolution_stats.

The extractor attributes every column it can understand:
  S1 plain_alias  — `t.col AS x` → x inherits the source column's table
  S2 expr_alias   — CTE body outputs + expression outputs (→ ⟐ output)
  S3 scope        — bare column, exactly ONE physical table in nearest scope
  S5 sys          — system schemas (INFORMATION_SCHEMA…) → ⟐system sentinel
  S6 other        — pseudocolumns (LEVEL, ROWNUM, new/old) → expected, excluded

`resolution_stats` must ride along in run_full_analysis and in the cached
analysis JSON written by index_scripts.
"""

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import (
    SYSTEM_TABLE_SENTINEL,
    extract_variables_from_sql,
)
from app.extractor.adapter import run_full_analysis
from app.models.variable import VariableType
from app.services.workspace_service import (
    create_workspace,
    delete_workspace,
    get_workspace_dir,
)
from app.services.folder_index_service import index_scripts


def _col_vars(result):
    return [v for v in result.variables if v.variable_type == VariableType.COLUMN]


def _find(result, name, var_type=VariableType.COLUMN):
    hits = [v for v in result.variables
            if v.name == name and v.variable_type == var_type]
    assert hits, f"no {var_type.value} var named {name!r} in {[v.name for v in result.variables]}"
    return hits[0]


# ── S1: plain alias of a qualified column ────────────────────────────────

def test_s1_plain_alias_inherits_source_table():
    """sb.total_amount AS batch_total → batch_total attributed to settlement_batch."""
    r = extract_variables_from_sql(
        "SELECT sb.total_amount AS batch_total FROM settlement_batch sb", "s1")
    batch_total = _find(r, "batch_total")
    assert batch_total.source_tables == ["settlement_batch"], batch_total
    assert r.resolution_stats["resolved_by"]["plain_alias"] == 1, r.resolution_stats
    assert "batch_total" not in r.resolution_stats["unresolved"]


def test_s1_dotted_qualifier_takes_table_part():
    """db.t.amount AS amt → amt attributed to t (not db.t)."""
    r = extract_variables_from_sql(
        "SELECT db.t.amount AS amt FROM db.t", "s1d")
    assert _find(r, "amt").source_tables == ["t"]
    assert r.resolution_stats["resolved_by"]["plain_alias"] == 1


def test_s1_plain_qualified_column_unchanged():
    """No-alias qualified refs keep the historical prefix behavior."""
    r = extract_variables_from_sql(
        "SELECT sb.total_amount FROM settlement_batch sb", "s1b")
    assert _find(r, "sb.total_amount").source_tables == []
    assert r.resolution_stats["resolved_by"]["plain_alias"] == 0


# ── S2: expression output attribution ────────────────────────────────────

def test_s2_cte_output_column_resolves_downstream_ref():
    """WITH c AS (SELECT SUM(a) AS s FROM t) SELECT s FROM c → s attributed to CTE c."""
    sql = "WITH c AS (SELECT SUM(a) AS s FROM t) SELECT s FROM c"
    r = extract_variables_from_sql(sql, "s2c")
    s = _find(r, "s")  # the bare downstream reference in TOP context
    assert s.source_tables == ["c"], s
    assert s.context == "TOP", s
    assert r.resolution_stats["resolved_by"]["expr_alias"] == 1, r.resolution_stats
    assert r.resolution_stats["unresolved"] == [], r.resolution_stats


def test_s2_expression_output_attributed_to_output_table():
    """SELECT SUM(x) AS total FROM t → total attributed to ⟐ output."""
    r = extract_variables_from_sql("SELECT SUM(x) AS total FROM t", "s2o")
    total = _find(r, "total", VariableType.AGGREGATE)
    assert total.source_tables == ["⟐ output"], total
    assert r.resolution_stats["resolved_by"]["expr_alias"] == 1, r.resolution_stats
    assert "total" not in r.resolution_stats["unresolved"]


def test_s2_aggregate_var_creation_unchanged():
    """Computed vars keep their type — only attribution is added."""
    r = extract_variables_from_sql("SELECT SUM(x) AS total FROM t", "s2t")
    totals = [v for v in r.variables if v.name == "total"]
    assert len(totals) == 1
    assert totals[0].variable_type == VariableType.AGGREGATE, totals[0]
    assert totals[0].source_columns == ["x"], totals[0]


# ── S3: nearest-scope resolution ─────────────────────────────────────────

def test_s3_single_physical_table_scope():
    """SELECT order_amount FROM orders → attributed to orders (scope count 1)."""
    r = extract_variables_from_sql("SELECT order_amount FROM orders", "s3")
    assert _find(r, "order_amount").source_tables == ["orders"]
    assert r.resolution_stats["resolved_by"]["scope"] == 1, r.resolution_stats
    assert r.resolution_stats["unresolved"] == []


def test_s3_scope_aliases_count_once():
    """FROM orders o1 JOIN orders o2 → one physical table, still resolvable."""
    r = extract_variables_from_sql(
        "SELECT amount FROM orders o1 JOIN orders o2 ON o1.id = o2.id", "s3a")
    assert _find(r, "amount").source_tables == ["orders"]
    assert r.resolution_stats["resolved_by"]["scope"] == 1


def test_s3_multi_table_scope_left_unresolved():
    """SELECT id FROM a JOIN b ON a.id=b.id → id unresolved (scope ≥2)."""
    r = extract_variables_from_sql("SELECT id FROM a JOIN b ON a.id=b.id", "s3m")
    assert _find(r, "id").source_tables == []
    assert r.resolution_stats["resolved_by"]["scope"] == 0
    assert r.resolution_stats["unresolved"] == ["id"], r.resolution_stats


def test_s3_where_uses_nearest_scope():
    """WHERE/HAVING columns resolve against the outer SELECT's tables."""
    r = extract_variables_from_sql(
        "SELECT amount FROM orders WHERE amount > 100", "s3w")
    assert _find(r, "amount").source_tables == ["orders"]
    assert r.resolution_stats["unresolved"] == []


def test_s3_subquery_inner_column_not_attributed_to_outer_scope():
    """A column inside a subquery must not be attributed to outer tables."""
    r = extract_variables_from_sql(
        "SELECT (SELECT MAX(x) FROM t2) AS m FROM t1", "s3sub")
    inner_x = [v for v in _col_vars(r) if v.name == "x" and v.context.startswith("TOP/subq")]
    assert inner_x and inner_x[0].source_tables == ["t2"], inner_x
    # the outer-context phantom copy stays unattributed (never guessed)
    outer_x = [v for v in _col_vars(r) if v.name == "x" and v.context == "TOP"]
    assert outer_x and outer_x[0].source_tables == [], outer_x


# ── S5: system schema columns ────────────────────────────────────────────

def test_s5_system_schema_marked_sys():
    """SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES → sys, not unresolved."""
    r = extract_variables_from_sql(
        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES", "s5")
    tn = _find(r, "TABLE_NAME")
    assert tn.source_tables == [SYSTEM_TABLE_SENTINEL], tn
    assert r.resolution_stats["resolved_by"]["sys"] == 1, r.resolution_stats
    assert "TABLE_NAME" not in r.resolution_stats["unresolved"]
    assert r.resolution_stats["resolved_by"]["scope"] == 0  # S5 wins over S3


# ── S6: pseudocolumns ────────────────────────────────────────────────────

def test_s6_pseudocolumn_marked_other():
    """SELECT LEVEL FROM dual CONNECT BY LEVEL <= 10 → other, not unresolved."""
    r = extract_variables_from_sql(
        "SELECT LEVEL FROM dual CONNECT BY LEVEL <= 10", "s6")
    level = _find(r, "LEVEL")
    assert level.source_tables == ["⟐pseudo"], level  # sentinel mark, no real table
    assert r.resolution_stats["resolved_by"]["other"] == 1, r.resolution_stats
    assert "LEVEL" not in r.resolution_stats["unresolved"]


def test_s6_rownum_and_trigger_vars():
    r = extract_variables_from_sql(
        "SELECT ROWNUM FROM dual WHERE ROWNUM <= 5; "
        "SELECT new, old FROM trigger_table", "s6b")
    assert r.resolution_stats["resolved_by"]["other"] >= 1, r.resolution_stats
    assert "ROWNUM" not in r.resolution_stats["unresolved"], r.resolution_stats


def test_s6_new_old_only_in_row_to_json():
    """E4: bare new/old are REAL columns (S3-attributed); only the
    row_to_json(new/old) trigger idiom is a pseudocolumn."""
    r = extract_variables_from_sql(
        "SELECT new, old FROM trigger_table; "
        "SELECT row_to_json(new), row_to_json(old) FROM t;", "s6c")
    assert r.resolution_stats["resolved_by"]["other"] >= 2, r.resolution_stats
    # row_to_json idiom vars are sentinel-marked, not attributed to t
    marked = [v for v in r.variables
              if v.name == "new" and v.source_tables == ["⟐pseudo"]]
    assert marked, "row_to_json(new) var should be sentinel-marked"
    # bare new/old resolve to trigger_table via S3 — not unresolved, not other
    assert "new" not in r.resolution_stats["unresolved"], r.resolution_stats
    assert "old" not in r.resolution_stats["unresolved"], r.resolution_stats


# ── resolution_stats shape & counters ────────────────────────────────────

def test_resolution_stats_shape_and_totals():
    """total_columns counts every COLUMN var created; keys always present."""
    r = extract_variables_from_sql(
        "SELECT sb.total_amount AS batch_total FROM settlement_batch sb", "shape")
    stats = r.resolution_stats
    assert set(stats) == {"total_columns", "resolved_by", "unresolved"}, stats
    assert set(stats["resolved_by"]) == {"plain_alias", "expr_alias", "scope",
                                         "schema", "sys", "other"}, stats
    assert stats["total_columns"] == len(_col_vars(r)) == 2, stats
    assert stats["resolved_by"]["schema"] == 0  # S4 runs at index time only


def test_resolution_stats_in_full_analysis_result():
    """run_full_analysis returns resolution_stats as a top-level key."""
    result = run_full_analysis(
        "SELECT order_amount FROM orders", "full.sql")
    stats = result["resolution_stats"]
    assert stats["total_columns"] == 1, stats
    assert stats["resolved_by"]["scope"] == 1, stats
    assert stats["unresolved"] == [], stats


def _make_ws(sql: str, script_name: str = "t.sql") -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(script_name, sql)
    return create_workspace(buf.getvalue())


@pytest.fixture
def small_ws():
    ws_id = _make_ws(
        "SELECT sb.total_amount AS batch_total FROM settlement_batch sb;\n"
        "SELECT order_amount FROM orders;\n")
    yield ws_id
    delete_workspace(ws_id)


def test_resolution_stats_in_cached_analysis_json(small_ws):
    """index_scripts persists resolution_stats into cache/analysis_*.json."""
    index_scripts(small_ws, ["t.sql"])
    cache_dir = get_workspace_dir(small_ws) / "cache"
    analysis_files = list(cache_dir.glob("analysis_*.json"))
    assert analysis_files, "analysis cache files should exist"
    for fp in analysis_files:
        data = json.loads(fp.read_text())
        assert "resolution_stats" in data, fp
        stats = data["resolution_stats"]
        assert set(stats) == {"total_columns", "resolved_by", "unresolved"}, stats
        assert stats["resolved_by"]["plain_alias"] >= 1, stats
        assert stats["resolved_by"]["scope"] >= 1, stats
        assert stats["unresolved"] == [], stats


# ── Sanity: qualified-only multi-workflow scripts ────────────────────────

# mirrors samples/mock_sql_test — qualified-only workflow
_MWF_SCRIPTS = {
    "step1_load_orders.sql": (
        "INSERT INTO stg_orders (order_id, customer_id, amount, order_date, status)\n"
        "SELECT o.order_id, o.customer_id, o.amount, o.order_date, o.status\n"
        "FROM raw_orders o\n"
        "WHERE o.order_date >= '2024-01-01' AND o.status IN ('completed', 'pending');\n"
    ),
    "step2_enrich_customers.sql": (
        "INSERT INTO stg_customers (customer_id, name, segment, region)\n"
        "SELECT c.customer_id, c.full_name, c.segment, c.region\n"
        "FROM crm_customers c\n"
        "WHERE c.is_active = 1 AND c.region IN ('NA', 'EMEA', 'APAC');\n"
    ),
    "step3_join_orders_customers.sql": (
        "INSERT INTO analytics_orders (order_id, customer_name, amount, segment, region, order_date)\n"
        "SELECT so.order_id, sc.name, so.amount, sc.segment, sc.region, so.order_date\n"
        "FROM stg_orders so JOIN stg_customers sc ON so.customer_id = sc.customer_id\n"
        "WHERE so.status = 'completed';\n"
    ),
    "step4_aggregate_daily.sql": (
        "INSERT INTO daily_summary (report_date, region, total_orders, total_amount)\n"
        "SELECT DATE(ao.order_date) AS dt, ao.region, COUNT(*) AS cnt, SUM(ao.amount) AS total\n"
        "FROM analytics_orders ao GROUP BY DATE(ao.order_date), ao.region;\n"
    ),
    "step5_final_report.sql": (
        "SELECT ds.report_date, ds.region, ds.total_orders, ds.total_amount,\n"
        "       ROUND(ds.total_amount / NULLIF(ds.total_orders, 0), 2) AS avg_order_value\n"
        "FROM daily_summary ds\n"
        "WHERE ds.report_date >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)\n"
        "ORDER BY ds.report_date DESC, ds.total_amount DESC;\n"
    ),
}


@pytest.mark.parametrize("name,sql", sorted(_MWF_SCRIPTS.items()))
def test_multi_workflow_qualified_only_no_orphans(name, sql):
    """Qualified-only scripts: unresolved == 0, no behavior change in variables.

    Every COLUMN var is either prefix-qualified or attributed; total_columns
    matches the column var count; computed/table vars keep their types.
    """
    r = extract_variables_from_sql(sql, name)
    stats = r.resolution_stats
    assert stats["unresolved"] == [], stats
    assert stats["total_columns"] == len(_col_vars(r)), stats
    # all column vars carry attribution (prefix or source_tables)
    for v in _col_vars(r):
        assert "." in v.name or v.source_tables, (name, v.name, v.source_tables)
