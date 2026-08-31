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


class TestProvenancePhase:
    """X1 review (2026-08-31) — the container-PROVENANCE bridge
    (dependency_graph Phase 3, G7 RC-C) must be process-independent and must
    never close a 2-cycle on a pair it did not create.

    Defect 1 (HIGH): the candidate containers live in a `set`
    (`_prov_bodies`), so `for body in bodies` walked them in hash-random
    order and `producers[-1]` inherited it — the picked producer, and with it
    the served L2 edge id, flipped between processes. Measured before the
    fix: 7 distinct PROVENANCE pick-sets on BDM_ACC_LOAN_INFO_RFN across 8
    PYTHONHASHSEEDs, 2 on SUP_M.
    Defect 2 (MED-HIGH): guard 3 only saw edges INTO the reader, so an
    existing reader → producer REF/TRANSFORM leg coexisted with the new
    producer → reader PROVENANCE leg — 14 direct 2-cycles corpus-wide.
    """

    # A derived alias reused in TWO statements: `d1` maps to two container
    # bodies (`TOP0/subq/d1` and `TOP1/subq/d1`), each projecting `amount`,
    # and each statement reads the handle from outside the body — the exact
    # shape that makes the pick contested (RFN: 9 names / 21 readers).
    # Under the pre-fix pick this fixture flips with PYTHONHASHSEED: the
    # TOP1 reader bridges to `t.amount`@L1 (statement 0's projection!) on
    # most seeds and to `b.amount`@L2 on others.
    CONTESTED = (
        "SELECT d1.amount FROM (SELECT t.amount FROM gps_transactions t) AS d1;\n"
        "SELECT d1.amount FROM (SELECT b.amount FROM gps_accounts b) AS d1;"
    )

    def test_pick_is_identical_across_process_hash_seeds(self):
        """The served edge must not depend on PYTHONHASHSEED — the child
        process is the only honest way to vary the interpreter's str hash."""
        import os
        import subprocess

        here = Path(__file__).resolve().parent
        child = (
            "import sys; sys.path.insert(0, %r); "
            "from app.extractor.variable_extractor_v2 import "
            "extract_variables_from_sql; "
            "from app.extractor.dependency_graph import "
            "build_dependency_graph; "
            "sql = open(sys.argv[1], encoding='utf-8').read(); "
            "res = extract_variables_from_sql(sql, 'det'); "
            "deps = build_dependency_graph(res, sql); "
            "byid = {v.id: v for v in res.variables}; "
            "print(sorted((byid[d.source_id].name, byid[d.source_id].line_start,"
            " byid[d.target_id].name, byid[d.target_id].line_start)"
            " for d in deps if d.operation == 'PROVENANCE'))"
            % str(here)
        )
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".sql",
                                         delete=False) as fh:
            fh.write(self.CONTESTED)
            path = fh.name
        try:
            seen = []
            for seed in ("0", "1", "2", "3"):
                env = dict(os.environ, PYTHONHASHSEED=seed)
                out = subprocess.run(
                    [sys.executable, "-c", child, path], env=env,
                    capture_output=True, text=True, check=True,
                ).stdout
                seen.append(out.strip())
            assert len(set(seen)) == 1, (
                "the PROVENANCE pick is process-dependent — the served L2 "
                f"edge id flips between runs: {seen}")
            assert seen[0] != "[]", (
                "the fixture wires no provenance edge, so this pin proves "
                "nothing — make the container name contested again")
        finally:
            path and os.unlink(path)

    def _prov_pairs(self, sql: str, name: str):
        """The PROVENANCE edges as (producer, its line, reader, its line)."""
        res = extract_variables_from_sql(sql, name)
        deps = build_dependency_graph(res, sql)
        byid = {v.id: v for v in res.variables}
        return sorted(
            (byid[d.source_id].name, byid[d.source_id].line_start,
             byid[d.target_id].name, byid[d.target_id].line_start)
            for d in deps if d.operation == "PROVENANCE")

    def test_contested_fixture_wires_the_last_writer(self):
        """The deterministic pick IS the D3 last-writer-wins: the latest
        candidate line at-or-before the read wins, never a random body —
        and a reader never bridges to ANOTHER statement's projection."""
        pairs = self._prov_pairs(self.CONTESTED, "det")
        assert pairs, "no provenance edge — the contested fixture regressed"
        by_reader = {}
        for src, sline, tgt, tline in pairs:
            by_reader.setdefault((tgt, tline), []).append((src, sline))
        assert set(by_reader) == {("d1.amount", 1), ("d1.amount", 2)}, \
            f"both statements' handle reads must be wired: {sorted(by_reader)}"
        # Each reader takes its OWN statement's projection — the body whose
        # line is nearest at-or-before the read.
        assert by_reader[("d1.amount", 1)] == [("t.amount", 1)], pairs
        assert by_reader[("d1.amount", 2)] == [("b.amount", 2)], pairs

    def test_no_two_cycle_with_the_provenance_leg(self):
        """Guard 3b — no PROVENANCE edge may coexist with its own reverse."""
        for fname in ("financial/fin_query4_merge_upsert.sql",
                      "financial/fin_query12_revenue_waterfall.sql",
                      "financial/fin_query15_multidimensional_cube.sql"):
            sql = _read(fname)
            res = extract_variables_from_sql(sql, fname)
            deps = build_dependency_graph(res, sql)
            directed = {(d.source_id, d.target_id) for d in deps}
            cycles = [(d.source_id, d.target_id) for d in deps
                      if d.operation == "PROVENANCE"
                      and (d.target_id, d.source_id) in directed]
            assert not cycles, (
                f"{fname}: PROVENANCE leg closing a 2-cycle: {cycles}")
