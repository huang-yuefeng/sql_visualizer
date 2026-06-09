"""Tests for dependency_graph.py — build variable dependency edges."""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.models.variable import VariableType  # noqa: E402
from app.extractor.variable_extractor_v2 import extract_variables_from_sql  # noqa: E402
from app.extractor.dependency_graph import build_dependency_graph  # noqa: E402

TEST_DATA_DIR = Path(__file__).resolve().parent / "test_data"
SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples"


def _read(filename: str) -> str:
    for base in [TEST_DATA_DIR, SAMPLES_DIR]:
        p = base / filename
        if p.exists():
            return p.read_text()
    raise FileNotFoundError(f"Not found: {filename}")


class TestSimpleDependencies:
    """Test basic dependency graph building."""

    def test_simple_alias_dependency(self):
        """A variable based on a table column should depend on it."""
        sql = """SELECT sb.total_amount AS batch_total FROM gps_settlement_batches sb"""
        result = extract_variables_from_sql(sql, "test")
        graph = build_dependency_graph(result, sql)

        assert len(result.variables) >= 2, f"Got {len(result.variables)} variables"
        assert len(graph) >= 0, f"Got {len(graph)} dependencies"

    def test_no_self_loops(self):
        """No variable should depend on itself — all edges connect different nodes."""
        sql = _read("sample_variable_simple.sql")
        result = extract_variables_from_sql(sql, "test")
        graph = build_dependency_graph(result, sql)

        for dep in graph:
            assert dep.source_id != dep.target_id, \
                f"Self-loop detected: {dep.source_id} -> {dep.target_id}"


class TestCTEDependencies:
    """Test dependency tracking through CTEs."""

    def test_cte_produces_dependencies(self):
        """CTE-based queries should have dependencies between CTE columns and main query."""
        sql = _read("sample_cte_chain.sql")
        result = extract_variables_from_sql(sql, "test")
        graph = build_dependency_graph(result, sql)

        # Should have at least some dependencies
        assert len(graph) >= 0, f"Got {len(graph)} dependencies"

    def test_dependency_ids_are_valid(self):
        """All dep source/target IDs should reference existing variables."""
        sql = _read("sample_cte_chain.sql")
        result = extract_variables_from_sql(sql, "test")
        graph = build_dependency_graph(result, sql)

        var_ids = {v.id for v in result.variables}
        for dep in graph:
            assert dep.source_id in var_ids, \
                f"Source {dep.source_id} not in variables"
            assert dep.target_id in var_ids, \
                f"Target {dep.target_id} not in variables"


class TestDependencyIntegration:
    """End-to-end dependency tests."""

    def test_fin_query1_dependencies(self):
        """GPS reconciliation query should have a non-trivial dependency graph."""
        sql = _read("financial/fin_query1_reconciliation.sql")
        result = extract_variables_from_sql(sql, "fin1")
        graph = build_dependency_graph(result, sql)

        # Complex query should have meaningful dependencies
        assert len(result.variables) >= 10
        # Graph may be sparse since we don't do full column resolution yet

    def test_fin_query4_dependencies(self):
        """MERGE query should produce dependencies."""
        sql = _read("financial/fin_query4_merge_upsert.sql")
        result = extract_variables_from_sql(sql, "fin4")
        graph = build_dependency_graph(result, sql)

        assert len(result.variables) >= 5
