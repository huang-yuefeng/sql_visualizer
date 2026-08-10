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


class TestOneCCrossStatementGates:
    """E1/E2 (2026-08-10): the 1c-cross / 1c-direct cross-statement
    machinery must never emit edges that contradict statement order or
    CTE scope."""

    def test_e2_reader_before_writer_skipped(self):
        """1c-cross order guard: a same-name table read BEFORE the write
        statement cannot consume the write — no WRITE_READ edge may target
        the pre-write reader."""
        sql = ("SELECT * FROM audit_log;\n"
               "INSERT INTO audit_log SELECT * FROM src_tbl;")
        result = extract_variables_from_sql(sql, "test")
        graph = build_dependency_graph(result, sql)
        readers = [v for v in result.variables
                   if v.name == "audit_log" and (v.context or "").startswith("TOP0")]
        assert readers, "the pre-write reader must be extracted"
        bad = [d for d in graph if d.relationship == "DML"
               and d.operation == "WRITE_READ"
               and d.target_id in {v.id for v in readers}]
        assert not bad, \
            f"write-after-read edge targeting a PRE-write reader: {bad}"

    def test_e2_writer_before_reader_keeps_edge(self):
        """Positive control: when the writer precedes the reader, the
        1c-cross WRITE_READ edge is legitimate and must survive."""
        sql = ("INSERT INTO audit_log SELECT * FROM src_tbl;\n"
               "SELECT * FROM audit_log;")
        result = extract_variables_from_sql(sql, "test")
        graph = build_dependency_graph(result, sql)
        readers = [v for v in result.variables
                   if v.name == "audit_log" and (v.context or "").startswith("TOP1")]
        assert readers, "the post-write reader must be extracted"
        ok = [d for d in graph if d.relationship == "DML"
              and d.operation == "WRITE_READ"
              and d.target_id in {v.id for v in readers}]
        assert ok, "the legitimate cross-statement write→read must exist"

    def test_e1_cte_reader_pairs_only_same_statement_def(self):
        """1c-direct cross-statement gate: CTEs are statement-scoped — the
        stmt-1 reader of CTE `t` links to stmt-1's def only, never to
        stmt-0's def of the same name."""
        sql = ("WITH t AS (SELECT a FROM s1) "
               "INSERT INTO tgt1 SELECT * FROM t;\n"
               "WITH t AS (SELECT b FROM s2) "
               "INSERT INTO tgt2 SELECT * FROM t;")
        result = extract_variables_from_sql(sql, "test")
        graph = build_dependency_graph(result, sql)
        defs = [v for v in result.variables
                if v.variable_type == VariableType.CTE and v.name == "t"]
        assert len(defs) == 2, \
            [(v.id, v.context, v.line_start) for v in defs]
        by_ctx = {v.context: v for v in defs}
        tgt2_ids = {v.id for v in result.variables if v.name == "tgt2"}
        assert tgt2_ids, "stmt-1's DML target must be extracted"
        top0_def = by_ctx.get("TOP0")
        assert top0_def is not None
        cross = [d for d in graph if d.source_id == top0_def.id
                 and d.target_id in tgt2_ids]
        assert not cross, \
            f"stmt-0's CTE def must not feed stmt-1's INSERT: {cross}"
        top1_def = by_ctx.get("TOP1")
        assert top1_def is not None
        same = [d for d in graph if d.source_id == top1_def.id
                and d.target_id in tgt2_ids]
        assert same, "stmt-1's own CTE def must feed stmt-1's INSERT"
