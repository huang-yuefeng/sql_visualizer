"""Test folder indexing and autocomplete."""
import io
import zipfile

import pytest


def _single_sql_zip(name: str, sql: str) -> bytes:
    """In-memory zip with one SQL script."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name}.sql", sql)
    return buf.getvalue()


class TestCase1Autocomplete:
    """case1: bank-ETL target columns written as non-column SELECT-output
    aliases must reach field_index + autocomplete (Fix A), and plain column
    aliases (LENDING_REF) keep indexing exactly as before (regression guard).
    """

    SQL = """\
INSERT OVERWRITE TABLE bdm_case1_target PARTITION(data_dt='2024')
SELECT
  a.acnw AS LENDING_REF,
  CASE WHEN a.fkfs='A' THEN '01' WHEN a.fkfs='B' THEN '02' END AS EAST5_SSTZFXXB
FROM ODS_CASE1_SRC a
WHERE a.p_dt = '2024';
"""

    def test_case1_field_indexed_and_autocompleted(self, workspace_client):
        ws_id = workspace_client.create(_single_sql_zip("case1", self.SQL))
        try:
            result = workspace_client.index(ws_id)
            fi = result["field_index"]
            # Fix A: the CASE alias is an indexable field
            assert "EAST5_SSTZFXXB" in fi
            # regression guard: plain column alias still indexed
            assert "LENDING_REF" in fi
            # Fix A attribution: the output alias lands on the write target
            ti = result["table_index"]
            assert "EAST5_SSTZFXXB" in ti["bdm_case1_target"]["fields"]
            # autocomplete round-trips the exact name
            suggestions = workspace_client.autocomplete(ws_id, "field", "EAST5_SSTZFXXB")
            assert "EAST5_SSTZFXXB" in suggestions
        finally:
            workspace_client.delete(ws_id)


class TestAutocompleteTypoTolerance:
    """Fix B: a query one character off the indexed name must still surface it
    (case1 OCR: user typed EAST5_SSTZFXXB against the real east5_stzfxxb).
    """

    def test_table_typo_suggested(self, workspace_client):
        sql = """\
INSERT OVERWRITE TABLE east5_stzfxxb
SELECT CASE WHEN a.x=1 THEN 'a' ELSE 'b' END AS stzfje
FROM ODS_CASE1_SRC a;
"""
        ws_id = workspace_client.create(_single_sql_zip("case1_typo_tbl", sql))
        try:
            result = workspace_client.index(ws_id)
            assert "east5_stzfxxb" in result["table_index"]
            # query has an extra S vs the real table name
            suggestions = workspace_client.autocomplete(ws_id, "table", "east5_sstzfxxb")
            assert "east5_stzfxxb" in suggestions
        finally:
            workspace_client.delete(ws_id)

    def test_field_typo_suggested(self, workspace_client):
        sql = """\
INSERT OVERWRITE TABLE east5_stzfxxb
SELECT CASE WHEN a.x=1 THEN 'a' ELSE 'b' END AS stzfje
FROM ODS_CASE1_SRC a;
"""
        ws_id = workspace_client.create(_single_sql_zip("case1_typo_fld", sql))
        try:
            result = workspace_client.index(ws_id)
            fi = result["field_index"]
            assert "stzfje" in fi  # Fix A: the CASE alias is indexed
            # one-character substitution in the field query
            suggestions = workspace_client.autocomplete(ws_id, "field", "stzfja")
            assert "stzfje" in suggestions
        finally:
            workspace_client.delete(ws_id)

    def test_field_one_char_off_surfaces_intended_name(self, workspace_client):
        """Exact case1 verification: autocomplete(field, q='EAST5_SSTZFXXB')
        surfaces the intended east5_stzfxxb-related entry (Fix B) — the query
        has an extra S, the real field name is one char shorter."""
        sql = """\
INSERT OVERWRITE TABLE east5_stzfxxb
SELECT a.acnw AS east5_stzfxxb, a.bal AS stzfje
FROM ODS_CASE1_SRC a;
"""
        ws_id = workspace_client.create(_single_sql_zip("case1_fld", sql))
        try:
            result = workspace_client.index(ws_id)
            fi = result["field_index"]
            assert "east5_stzfxxb" in fi and "stzfje" in fi
            suggestions = workspace_client.autocomplete(ws_id, "field", "EAST5_SSTZFXXB")
            assert "east5_stzfxxb" in suggestions
        finally:
            workspace_client.delete(ws_id)

    def test_typo_fallback_does_not_shadow_substring(self, workspace_client):
        """A healthy substring hit (>=2 results) must NOT trigger the typo
        fallback — the fallback only fires when the primary returns <2."""
        sql = """\
INSERT OVERWRITE TABLE east5_stzfxxb
SELECT a.acnw AS STZFJE_A, a.bal AS STZFJE_B, a.x AS OTHER
FROM ODS_CASE1_SRC a;
"""
        ws_id = workspace_client.create(_single_sql_zip("case1_sub", sql))
        try:
            result = workspace_client.index(ws_id)
            fi = result["field_index"]
            assert "STZFJE_A" in fi and "STZFJE_B" in fi and "OTHER" in fi
            suggestions = workspace_client.autocomplete(ws_id, "field", "stzfje")
            assert "STZFJE_A" in suggestions and "STZFJE_B" in suggestions
            # substring pass dominates: the mid-substring-only name is NOT
            # surfaced by the distance fallback ahead of the two hits
            assert "OTHER" not in suggestions
        finally:
            workspace_client.delete(ws_id)


class TestOutputAliasIndexed:
    """Fix A: plain SELECT with NVL / NULL / getdate output aliases — all three
    non-column expression kinds must land in field_index."""

    SQL = """\
SELECT
  NVL(a.bal, 0) AS X,
  NULL AS Y,
  getdate() AS Z
FROM ODS_CASE1_SRC a;
"""

    def test_transform_literal_sysfunc_aliases_indexed(self, workspace_client):
        ws_id = workspace_client.create(_single_sql_zip("alias_out", self.SQL))
        try:
            result = workspace_client.index(ws_id)
            fi = result["field_index"]
            assert "X" in fi   # NVL(...) AS X  -> transform
            assert "Y" in fi   # NULL AS Y      -> expression
            assert "Z" in fi   # getdate() AS Z -> transform
        finally:
            workspace_client.delete(ws_id)


class TestBareSelectAliasesNotAttributed:
    """#308: a bare top-level SELECT's computed output aliases (aggregates /
    expressions) are NOT attributed to any physical table — only a DML write
    target makes a SELECT-output alias searchable."""

    BARE_SELECT = """\
SELECT
  u.user_id,
  u.username,
  COUNT(o.order_id) AS total_orders,
  SUM(o.amount) AS total_spent,
  AVG(o.amount) AS avg_order_amount,
  MAX(o.order_date) AS last_order_date
FROM users u
LEFT JOIN orders o ON u.user_id = o.user_id
GROUP BY u.user_id, u.username;
"""

    INSERT_OVERWRITE = """\
INSERT OVERWRITE TABLE daily_orders
SELECT SUM(o.amount) AS total_spent, COUNT(o.order_id) AS total_orders
FROM orders o;
"""

    def test_bare_select_aggregates_have_no_table(self, workspace_client):
        ws_id = workspace_client.create(
            _single_sql_zip("bare_select", self.BARE_SELECT))
        try:
            result = workspace_client.index(ws_id)
            fi = result["field_index"]
            ti = result["table_index"]
            # computed aliases are registered by name but never glued onto a
            # physical source table
            assert "total_orders" in fi
            assert fi["total_orders"]["tables"] == [], fi["total_orders"]
            assert fi["total_spent"]["tables"] == [], fi["total_spent"]
            assert "total_orders" not in ti.get("users", {}).get("fields", []), ti
            assert "total_spent" not in ti.get("orders", {}).get("fields", []), ti
        finally:
            workspace_client.delete(ws_id)

    def test_insert_overwrite_aggregate_indexed_against_target(self,
                                                              workspace_client):
        ws_id = workspace_client.create(
            _single_sql_zip("insert_ow", self.INSERT_OVERWRITE))
        try:
            result = workspace_client.index(ws_id)
            fi = result["field_index"]
            ti = result["table_index"]
            assert "total_spent" in ti["daily_orders"]["fields"], ti
            assert "daily_orders" in fi["total_spent"]["tables"], \
                fi["total_spent"]
        finally:
            workspace_client.delete(ws_id)


class TestFolderIndex:
    def test_index_builds_table_index(self, workspace_client, d1_zip):
        ws_id = workspace_client.create(d1_zip)
        result = workspace_client.index(ws_id)
        ti = result["table_index"]
        assert "orders" in ti
        assert result["script_count"] >= 2
        workspace_client.delete(ws_id)

    def test_index_builds_field_index(self, workspace_client, d2_zip):
        ws_id = workspace_client.create(d2_zip)
        result = workspace_client.index(ws_id)
        fi = result["field_index"]
        assert "amount" in fi
        assert "customer_id" in fi
        workspace_client.delete(ws_id)

    def test_autocomplete_table(self, workspace_client, d2_zip):
        ws_id = workspace_client.create(d2_zip)
        workspace_client.index(ws_id)
        suggestions = workspace_client.autocomplete(ws_id, "table", "sta")
        assert any("staging" in s.lower() for s in suggestions)
        workspace_client.delete(ws_id)

    def test_autocomplete_field(self, workspace_client, d2_zip):
        ws_id = workspace_client.create(d2_zip)
        workspace_client.index(ws_id)
        suggestions = workspace_client.autocomplete(ws_id, "field", "amo")
        assert "amount" in suggestions
        workspace_client.delete(ws_id)

    def test_autocomplete_empty_query(self, workspace_client, d2_zip):
        ws_id = workspace_client.create(d2_zip)
        workspace_client.index(ws_id)
        suggestions = workspace_client.autocomplete(ws_id, "table", "")
        assert len(suggestions) > 0
        workspace_client.delete(ws_id)

    def test_index_no_sql(self, workspace_client, d7_zip):
        ws_id = workspace_client.create(d7_zip)
        result = workspace_client.index(ws_id)
        assert result["script_count"] == 0
        workspace_client.delete(ws_id)

    def test_index_deep_nesting(self, workspace_client, d8_zip):
        ws_id = workspace_client.create(d8_zip)
        result = workspace_client.index(ws_id)
        assert result["script_count"] == 1
        workspace_client.delete(ws_id)
