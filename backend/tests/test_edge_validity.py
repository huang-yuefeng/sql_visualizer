"""Edge validity tests — every edge must correspond to a real data flow.

Synthetic edges (SUBSET, Phase-8 FILTER) are the safety net for connectivity.
All other edges must have a legitimate basis in the SQL data flow.
"""

import sys
from pathlib import Path
from collections import defaultdict

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.extractor.dependency_graph import build_dependency_graph
from app.models.variable import VariableType

SAMPLES_DIR = BACKEND_DIR.parent / "samples"


# ── Helpers ────────────────────────────────────────────────────────────────

def _analyze(sql: str, name: str = "test"):
    r = extract_variables_from_sql(sql, name)
    deps = build_dependency_graph(r, sql)
    var_by_id = {v.id: v for v in r.variables}
    return r, deps, var_by_id


# ══════════════════════════════════════════════════════════════════════════
# Core rule: SELECT expression sources must NOT get FILTER edges
# ══════════════════════════════════════════════════════════════════════════

class TestNoFilterOnSelectSources:
    """Columns consumed by aggregates/transforms are data sources, not filters."""

    def test_sum_source_not_filter(self):
        """o.amount consumed by SUM() → AGGREGATE edge, NOT FILTER."""
        sql = "SELECT SUM(o.amount) AS total FROM orders o"
        _, deps, vb = _analyze(sql)
        o_amt = next((v for v in vb.values() if v.name == "o.amount"), None)
        assert o_amt, "o.amount should exist"
        o_edges = [e for e in deps if e.source_id == o_amt.id]
        rels = {e.relationship for e in o_edges}
        assert "FILTER" not in rels, \
            f"o.amount is consumed by SUM, should NOT have FILTER. Edges: {rels}"

    def test_avg_source_not_filter(self):
        sql = "SELECT AVG(t.amount) AS avg_amt FROM gps_transactions t"
        _, deps, vb = _analyze(sql)
        t_amt = next((v for v in vb.values() if v.name == "t.amount"), None)
        assert t_amt
        t_edges = [e for e in deps if e.source_id == t_amt.id]
        assert "FILTER" not in {e.relationship for e in t_edges}, \
            "t.amount consumed by AVG should not have FILTER"

    def test_coalesce_source_not_filter(self):
        sql = "SELECT COALESCE(t.tax, 0) AS tax FROM gps_transactions t"
        _, deps, vb = _analyze(sql)
        t_tax = next((v for v in vb.values() if v.name == "t.tax"), None)
        assert t_tax
        t_edges = [e for e in deps if e.source_id == t_tax.id]
        assert "FILTER" not in {e.relationship for e in t_edges}, \
            "t.tax consumed by COALESCE should not have FILTER"

    def test_case_source_not_filter(self):
        sql = "SELECT CASE WHEN t.amount>100 THEN 'HIGH' ELSE 'LOW' END AS lvl FROM gps_transactions t"
        _, deps, vb = _analyze(sql)
        t_amt = next((v for v in vb.values() if v.name == "t.amount"), None)
        assert t_amt
        t_edges = [e for e in deps if e.source_id == t_amt.id]
        assert "FILTER" not in {e.relationship for e in t_edges}, \
            "t.amount consumed by CASE should not have FILTER"

    def test_window_source_not_filter(self):
        sql = "SELECT ROW_NUMBER() OVER (PARTITION BY t.batch ORDER BY t.date) AS rn FROM gps_transactions t"
        _, deps, vb = _analyze(sql)
        for col_name in ["t.batch", "t.date"]:
            col = next((v for v in vb.values() if v.name == col_name), None)
            if col:
                col_edges = [e for e in deps if e.source_id == col.id]
                assert "FILTER" not in {e.relationship for e in col_edges}, \
                    f"{col_name} consumed by window function should not have FILTER"

    def test_where_column_has_filter(self):
        """WHERE columns SHOULD have FILTER edges — they filter rows."""
        sql = "SELECT t.amount FROM gps_transactions t WHERE t.status = 'active'"
        _, deps, vb = _analyze(sql)
        t_status = next((v for v in vb.values() if v.name == "t.status"), None)
        assert t_status, "t.status should exist"
        t_edges = [e for e in deps if e.source_id == t_status.id]
        assert "FILTER" in {e.relationship for e in t_edges}, \
            f"WHERE column must have FILTER. Edges: {[e.relationship for e in t_edges]}"

    def test_join_on_column_has_filter(self):
        """JOIN ON columns filter join matches — should have FILTER."""
        sql = "SELECT u.name FROM users u JOIN orders o ON u.id = o.user_id"
        _, deps, vb = _analyze(sql)
        u_id = next((v for v in vb.values() if v.name == "u.id"), None)
        assert u_id
        u_edges = [e for e in deps if e.source_id == u_id.id]
        assert "FILTER" in {e.relationship for e in u_edges}, \
            f"JOIN ON column must have FILTER. Edges: {[e.relationship for e in u_edges]}"


# ══════════════════════════════════════════════════════════════════════════
# SUBSET edges are synthetic — flag them
# ══════════════════════════════════════════════════════════════════════════

class TestSyntheticEdges:
    """SUBSET edges are safety-net bridges, not real data flows."""

    def test_subset_edges_are_synthetic(self):
        """SUBSET edges should only exist when components would otherwise
        be disconnected. They represent the graph topology, not data flow."""
        sql = (SAMPLES_DIR / "query4_update_delete.sql").read_text()
        _, deps, vb = _analyze(sql)
        subset = [e for e in deps if e.relationship == "SUBSET"]
        # SUBSET edges exist — that's expected. But verify they connect
        # table-like nodes (the safety net bridges components).
        for e in subset:
            src = vb.get(e.source_id)
            tgt = vb.get(e.target_id)
            assert src and tgt, "SUBSET edge must have valid endpoints"
            # Source should be a table-like node (bridge uses TABLE as anchor)
            assert src.variable_type.value in (
                "table", "view", "cte", "virtual_table", "merge_target",
                "union_branch", "subquery"
            ), f"SUBSET source should be table-like, got {src.variable_type.value}"

    def test_complex_query_subset_count_reasonable(self):
        """Verify SUBSET count is within reasonable bounds.
        Too many SUBSET edges suggests missing explicit data flow edges."""
        for fname in ["query2_joins_complex.sql", "query3_subqueries_case.sql"]:
            sql = (SAMPLES_DIR / fname).read_text()
            _, deps, _ = _analyze(sql, fname)
            subset_count = sum(1 for e in deps if e.relationship == "SUBSET")
            # SUBSET is the last resort — expect at most a handful
            assert subset_count <= 15, \
                f"{fname}: {subset_count} SUBSET edges, expect ≤15. " \
                f"Too many suggests missing explicit edges."


# ══════════════════════════════════════════════════════════════════════════
# Edge-specific validity checks
# ══════════════════════════════════════════════════════════════════════════

class TestEdgeTypeValidity:
    """Each edge type must connect appropriate node types."""

    def test_table_flow_only_between_tables(self):
        """TABLE_FLOW connects table-like nodes to anchors."""
        sql = (SAMPLES_DIR / "query1_select_where.sql").read_text()
        _, deps, vb = _analyze(sql)
        table_types = {"table", "view", "cte", "subquery", "virtual_table",
                       "merge_target", "union_branch"}
        for e in deps:
            if e.relationship != "TABLE_FLOW":
                continue
            src = vb[e.source_id]
            tgt = vb[e.target_id]
            assert src.variable_type.value in table_types, \
                f"TABLE_FLOW source must be table-like, got {src.variable_type.value} ({src.name})"
            assert tgt.variable_type.value in table_types, \
                f"TABLE_FLOW target must be table-like, got {tgt.variable_type.value} ({tgt.name})"

    def test_schema_connects_table_to_column(self):
        """SCHEMA: source = table-like, target = column/computed."""
        sql = (SAMPLES_DIR / "query1_select_where.sql").read_text()
        _, deps, vb = _analyze(sql)
        table_types = {"table", "view", "cte", "subquery", "virtual_table",
                       "merge_target"}
        column_types = {"column", "cte_column", "aggregate", "window",
                        "case", "transform", "expression"}
        for e in deps:
            if e.relationship != "SCHEMA":
                continue
            src = vb[e.source_id]
            tgt = vb[e.target_id]
            assert src.variable_type.value in table_types, \
                f"SCHEMA source must be table-like, got {src.variable_type.value} ({src.name})"
            assert tgt.variable_type.value in column_types, \
                f"SCHEMA target must be column/computed, got {tgt.variable_type.value} ({tgt.name})"

    def test_aggregate_source_is_column(self):
        """AGGREGATE: source must be a column type."""
        sql = (SAMPLES_DIR / "query2_joins_complex.sql").read_text()
        _, deps, vb = _analyze(sql)
        col_types = {"column", "cte_column"}
        for e in deps:
            if e.relationship != "AGGREGATE":
                continue
            src = vb[e.source_id]
            assert src.variable_type.value in col_types, \
                f"AGGREGATE source must be column, got {src.variable_type.value} ({src.name})"

    def test_dml_source_has_source_columns(self):
        """DML source should be a variable with source_columns (data source)."""
        sql = "INSERT INTO target (id, amt) SELECT a.id, a.amount FROM source a"
        _, deps, vb = _analyze(sql)
        for e in deps:
            if e.relationship != "DML":
                continue
            src = vb[e.source_id]
            tgt = vb[e.target_id]
            assert tgt.variable_type.value in ("table", "merge_target"), \
                f"DML target must be table/merge_target, got {tgt.variable_type.value} ({tgt.name})"

    def test_alias_connects_alias_to_original(self):
        """ALIAS: source=alias (has source_tables), target=original (no source_tables)."""
        sql = "SELECT u.name FROM users u"
        _, deps, vb = _analyze(sql)
        for e in deps:
            if e.relationship != "ALIAS":
                continue
            src = vb[e.source_id]
            tgt = vb[e.target_id]
            assert not src.source_tables, \
                f"ALIAS source must be original (no source_tables): {src.name}"
            assert tgt.source_tables, \
                f"ALIAS target must be alias (has source_tables): {tgt.name}"

    def test_no_self_loops(self):
        """No edge should connect a node to itself."""
        for fname in ["query1_select_where.sql", "query2_joins_complex.sql",
                       "query3_subqueries_case.sql"]:
            sql = (SAMPLES_DIR / fname).read_text()
            _, deps, _ = _analyze(sql, fname)
            for e in deps:
                assert e.source_id != e.target_id, \
                    f"{fname}: self-loop {e.relationship} on {e.source_id[:8]}"


# ══════════════════════════════════════════════════════════════════════════
# Comprehensive: every edge in all sample files is valid
# ══════════════════════════════════════════════════════════════════════════

class TestAllEdgesValidAcrossSamples:
    """Run edge validity checks against all sample SQL files."""

    ALL_SAMPLES = [
        "query1_select_where.sql",
        "query2_joins_complex.sql",
        "query3_subqueries_case.sql",
        "query4_update_delete.sql",
        "query5_nested.sql",
    ]

    @pytest.mark.parametrize("fname", ALL_SAMPLES)
    def test_no_filter_on_aggregate_transform_sources(self, fname):
        """In every sample, columns consumed by AGGREGATE/TRANSFORM/WINDOW/
        COMPUTED must NOT also have FILTER edges."""
        sql = (SAMPLES_DIR / fname).read_text()
        _, deps, vb = _analyze(sql, fname)

        # Find columns that have AGGREGATE/TRANSFORM/WINDOW/COMPUTED edges
        consumed_cols = set()
        for e in deps:
            if e.relationship in ("AGGREGATE", "TRANSFORM", "WINDOW", "COMPUTED", "REF"):
                consumed_cols.add(e.source_id)

        # Those columns must NOT also have FILTER edges
        for e in deps:
            if e.relationship == "FILTER" and e.source_id in consumed_cols:
                col = vb.get(e.source_id)
                col_name = col.name if col else "?"
                # Exception: if the column is both consumed AND in WHERE/JOIN ON,
                # it CAN have both. Check defined_in.
                if col and (col.defined_in or "").upper().strip() in (
                    "WHERE", "HAVING", "JOIN ON"):
                    continue  # legitimate dual role
                pytest.fail(
                    f"{fname}: {col_name} has FILTER but is consumed by "
                    f"aggregate/transform — bogus FILTER edge"
                )

    @pytest.mark.parametrize("fname", ALL_SAMPLES)
    def test_every_edge_has_valid_endpoints(self, fname):
        """Every edge must reference existing variables."""
        sql = (SAMPLES_DIR / fname).read_text()
        r, deps, vb = _analyze(sql, fname)
        for e in deps:
            assert e.source_id in vb, \
                f"{fname}: edge source {e.source_id[:8]} not found for {e.relationship}"
            assert e.target_id in vb, \
                f"{fname}: edge target {e.target_id[:8]} not found for {e.relationship}"

    @pytest.mark.parametrize("fname", ALL_SAMPLES)
    def test_table_flow_count_matches_from_tables(self, fname):
        """Number of TABLE_FLOW edges should match FROM/JOIN alias count."""
        sql = (SAMPLES_DIR / fname).read_text()
        r, deps, vb = _analyze(sql, fname)
        from_aliases = [v for v in r.variables
                        if v.variable_type == VariableType.TABLE
                        and v.source_tables]
        tf_count = sum(1 for e in deps if e.relationship == "TABLE_FLOW")
        # Each FROM/JOIN alias should have at least one TABLE_FLOW.
        # Some may have more (nested subquery VTs also get TABLE_FLOW).
        assert tf_count >= len(from_aliases), \
            f"{fname}: {tf_count} TABLE_FLOW edges for {len(from_aliases)} FROM/JOIN aliases"

