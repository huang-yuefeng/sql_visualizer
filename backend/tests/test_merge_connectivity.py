"""H11 (2026-08-31) — MERGE columns connect to the table they belong to.

Waiver adjudication (`test_graph_integrity._ADJUDICATED_CONNECTIVITY`) pinned
7 DEFECT-class `column_connectivity` findings: a MERGE statement's columns —
UPDATE SET targets' source reads, WHEN-clause columns, JOIN-ON operands of
the MERGE's ON (and of an ordinary JOIN) — carried no belongs-to edge from
the table the model attributes them to:

    fin_query4_merge_upsert.sql   gps_transactions.amount, .fee_amount,
                                  .txn_id, .settlement_date   (MERGE UPDATE SET)
                                  gps_transactions.net_amount, .currency_code
                                                                (MERGE WHEN)
    fin_query14_recursive_…sql    gps_transactions.merchant_id  (JOIN ON)

Root cause: the extractor resolves a read through the MERGE's USING/derived
alias (`source.amount`, `txn.merchant_id`) to the alias's PHYSICAL table and
registers the R44 family-2 twin under the owner-qualified spelling
`{owner}.{col}`. Pass 4a skips the owner (it is an original table name by
design), Phase 4d's prefix match misses it, and Phase 4d-gb's gate enumerates
only `GROUP BY` + the `OCCURRENCE` marker — the MERGE/JOIN ON clauses fell
between the two, so the var's only edge was the REF from the read it came
from and the topology check hard-errored.

Fix: dependency_graph Phase 4d-gc gives such a column its structural
belongs-to SCHEMA edge from the owner's table entity in its own statement —
nearest instance at-or-before the column's own line (I3), mirroring the
4d-gb pattern, no new edge type.

Admission is evidence-gated, and that gate is what keeps the 7 FALSE
POSITIVES of the same clause family disconnected: a column is admitted only
when the model's own schema evidence says the owner really has that field —
an alias-spelled qualified read (`t.amount`) resolved to the same owner in
the same statement. fin_query4's `gps_transactions.account_id` is the twin
of a RENAMED USING projection (`t.source_account_id AS account_id`): no such
read exists, the belongs-to premise is false, and emitting the edge would
fabricate a schema fact. The witness is never owner-spelled, so the rule
cannot witness itself.

These tests pin all three faces of the ruling: the 7 defects connected and
anchored at their own lines, the 7 false positives still disconnected, and
a corpus-wide blast radius of exactly those 7 edges.
"""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor import dependency_graph  # noqa: E402
from app.extractor.dependency_graph import (  # noqa: E402
    _MERGE_COLUMN_CLAUSES,
    build_dependency_graph,
)
from app.extractor.variable_extractor_v2 import (  # noqa: E402
    extract_variables_from_sql,
)
from app.services.topology_checker import run_all_checks  # noqa: E402

SAMPLES = BACKEND_DIR.parent / "samples"

FIN_Q4 = "financial/fin_query4_merge_upsert.sql"
FIN_Q14 = "financial/fin_query14_recursive_account_hierarchy.sql"
FIN_Q8 = "financial/fin_query8_multi_party_settlement.sql"


# ════════════════════════════════════════════════════════════════════════
# The 7 adjudicated DEFECT entries — (file, column, own line, clause)
# ════════════════════════════════════════════════════════════════════════

MERGE_DEFECTS = [
    (FIN_Q4, "gps_transactions.amount", 30, "MERGE UPDATE SET"),
    (FIN_Q4, "gps_transactions.fee_amount", 30, "MERGE UPDATE SET"),
    (FIN_Q4, "gps_transactions.txn_id", 35, "MERGE UPDATE SET"),
    (FIN_Q4, "gps_transactions.settlement_date", 36, "MERGE UPDATE SET"),
    (FIN_Q4, "gps_transactions.net_amount", 64, "MERGE WHEN"),
    (FIN_Q4, "gps_transactions.currency_code", 63, "MERGE WHEN"),
    (FIN_Q14, "gps_transactions.merchant_id", 107, "JOIN ON"),
]

# The 7 adjudicated FALSE POSITIVE entries — the belongs-to premise does not
# hold (renamed projection / aggregates born in a derived scope / bare
# GROUP BY keys of a derived container). The clause gate already refuses
# three of them; the schema-evidence gate is what refuses the renamed
# projection. None may gain an edge.
MERGE_FALSE_POSITIVES = [
    (FIN_Q4, "gps_transactions.account_id", 25),
    (FIN_Q14, "gps_transactions.txn_count", 87),
    (FIN_Q14, "gps_transactions.total_volume", 88),
    (FIN_Q14, "gps_transactions.total_fees", 89),
    (FIN_Q14, "gps_transactions.chargeback_count", 90),
    (FIN_Q8, "gps_exchange_rates.party_id", 155),
    (FIN_Q8, "gps_exchange_rates.party_type", 155),
]


# ════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════

def _extract(sql: str, name: str):
    return extract_variables_from_sql(sql, name)


def _var(result, name: str, line: int | None = None):
    """The one variable spelled `name` (at `line` when given) — a same-named
    field of another statement/owner is a different column, so an ambiguous
    lookup is a test bug, never a pick-one."""
    matches = [v for v in result.variables
               if v.name == name and (line is None or v.line_start == line)]
    assert len(matches) == 1, (
        f"expected exactly one var {name!r}"
        + (f" @L{line}" if line else "")
        + f", got {len(matches)}: "
        + str([(v.line_start, v.defined_in, v.context) for v in matches]))
    return matches[0]


def _incoming(result, deps, var, relationship=None, operation=None):
    """Incoming edges of `var`, optionally filtered — [(source_var, dep)]."""
    by_id = {v.id: v for v in result.variables}
    out = []
    for d in deps:
        if d.target_id != var.id:
            continue
        if relationship is not None and d.relationship != relationship:
            continue
        if operation is not None and d.operation != operation:
            continue
        out.append((by_id[d.source_id], d))
    return out


def _graph_for(fname: str):
    sql = (SAMPLES / fname).read_text()
    result = _extract(sql, fname)
    return result, build_dependency_graph(result, "")


# ════════════════════════════════════════════════════════════════════════
# The 7 defects: connected, anchored at their own line
# ════════════════════════════════════════════════════════════════════════

class TestWaivedMergeDefectsConnected:
    """Each pinned defect carries its belongs-to SCHEMA edge."""

    @pytest.mark.parametrize("fname,column,line,clause", MERGE_DEFECTS)
    def test_belongs_to_edge_from_the_attribution_owner(self, fname, column,
                                                       line, clause):
        result, deps = _graph_for(fname)
        col = _var(result, column, line)
        owner = col.source_tables[0]

        # The column is spelled through its physical owner — exactly the
        # shape Pass 4a skips and the defect class this phase admits.
        assert column.split(".", 1)[0] == owner
        assert (col.defined_in or "").strip().upper() == clause

        edges = _incoming(result, deps, col, "SCHEMA", "TABLE_COLUMN")
        assert edges, (
            f"{fname}: {column} @L{line} ({clause}) has no belongs-to "
            f"SCHEMA edge — Phase 4d-gc did not admit it")
        assert any(src.name == owner for src, _ in edges), (
            f"{fname}: {column} belongs-to edge does not come from its "
            f"owner {owner}: "
            + str([(src.name, src.variable_type.value) for src, _ in edges]))

    @pytest.mark.parametrize("fname,column,line,clause", MERGE_DEFECTS)
    def test_edge_anchors_at_the_columns_own_line(self, fname, column,
                                                 line, clause):
        """The belongs-to edge is anchored at the column's OWN line — the
        chip that renders at that line is the connected one, not a sibling
        twin of the same field elsewhere in the statement (the waiver noted
        some defects stayed invisible only because a sibling carried the
        edge)."""
        result, deps = _graph_for(fname)
        col = _var(result, column, line)
        assert col.line_start == line
        assert any(src.name == col.source_tables[0]
                   for src, _ in _incoming(result, deps, col, "SCHEMA",
                                           "TABLE_COLUMN"))

    @pytest.mark.parametrize("fname,column,line,clause", MERGE_DEFECTS)
    def test_topology_no_longer_reports_the_defect(self, fname, column,
                                                   line, clause):
        result, deps = _graph_for(fname)
        vd = [{"id": v.id, "name": v.name,
               "variable_type": v.variable_type.value,
               "source_columns": v.source_columns,
               "source_tables": v.source_tables,
               "defined_in": v.defined_in, "is_output": v.is_output}
              for v in result.variables]
        dd = [{"source_id": d.source_id, "target_id": d.target_id,
               "relationship": d.relationship, "operation": d.operation,
               "sql_context": d.sql_context} for d in deps]
        issues = run_all_checks(vd, dd).get("column_connectivity", [])
        assert not any(i.startswith(f"[column] {column}:") for i in issues), (
            f"{fname}: {column} still trips column_connectivity — the "
            f"waiver entry cannot be retired: {issues}")


# ════════════════════════════════════════════════════════════════════════
# The false positives: still disconnected — no fabricated schema facts
# ════════════════════════════════════════════════════════════════════════

class TestAdjudicatedFalsePositivesStayDisconnected:
    """The renamed projection and friends must gain NO belongs-to edge."""

    @pytest.mark.parametrize("fname,column,line", MERGE_FALSE_POSITIVES)
    def test_no_belongs_to_edge(self, fname, column, line):
        result, deps = _graph_for(fname)
        col = _var(result, column, line)
        edges = _incoming(result, deps, col, "SCHEMA")
        assert not edges, (
            f"{fname}: {column} @L{line} is NOT a member of "
            f"{col.source_tables[0]} (renamed projection / aggregate born in "
            f"a derived scope / bare key of a derived container) but gained "
            f"a belongs-to edge from "
            + str([(src.name, src.variable_type.value) for src, _ in edges]))

    def test_renamed_projection_still_trips_the_check(self):
        """The false-positive verdict stays true: fin_query4's
        `gps_transactions.account_id` keeps its `column_connectivity`
        finding, which is why its waiver entry stays in the FALSE POSITIVE
        list (only the 7 DEFECT entries retire)."""
        result, deps = _graph_for(FIN_Q4)
        vd = [{"id": v.id, "name": v.name,
               "variable_type": v.variable_type.value,
               "source_columns": v.source_columns,
               "source_tables": v.source_tables,
               "defined_in": v.defined_in, "is_output": v.is_output}
              for v in result.variables]
        dd = [{"source_id": d.source_id, "target_id": d.target_id,
               "relationship": d.relationship, "operation": d.operation,
               "sql_context": d.sql_context} for d in deps]
        issues = run_all_checks(vd, dd).get("column_connectivity", [])
        assert ("[column] gps_transactions.account_id: no connection from "
                "source table 'gps_transactions'" in issues), issues


# ════════════════════════════════════════════════════════════════════════
# Blast radius — exactly the 7 edges, corpus-wide
# ════════════════════════════════════════════════════════════════════════

def _all_sample_files():
    files = sorted(SAMPLES.glob("*.sql"))
    fin = SAMPLES / "financial"
    if fin.exists():
        files += sorted(fin.glob("fin_query*.sql"))
    return files


class TestCorpusBlastRadius:
    def test_exactly_the_seven_defect_edges_corpus_wide(self):
        """The admission may add ONLY the 7 belongs-to edges the waiver
        pins — a wider blast radius would be an undisclosed model change
        (every L2 graph, snapshot and closure would shift)."""
        added = []
        for path in _all_sample_files():
            sql = path.read_text()
            result = _extract(sql, path.name)
            saved = set(_MERGE_COLUMN_CLAUSES)
            dependency_graph._MERGE_COLUMN_CLAUSES = set()
            try:
                before = {(d.source_id, d.target_id, d.relationship,
                           d.operation)
                          for d in build_dependency_graph(result, "")}
            finally:
                dependency_graph._MERGE_COLUMN_CLAUSES = saved
            by_id = {v.id: v for v in result.variables}
            for d in build_dependency_graph(result, ""):
                key = (d.source_id, d.target_id, d.relationship, d.operation)
                if key in before:
                    continue
                src, tgt = by_id[d.source_id], by_id[d.target_id]
                added.append((path.name, d.relationship, d.operation,
                              f"{src.name}@L{src.line_start}",
                              f"{tgt.name}@L{tgt.line_start}"))
        assert len(added) == 7, (
            f"Phase 4d-gc admitted {len(added)} edges corpus-wide, expected "
            f"exactly the 7 adjudicated defects: {added}")

    def test_clause_gate_is_the_documented_set(self):
        """Only the clauses a COLUMN var can carry from a MERGE walk plus the
        ordinary JOIN ON — `MERGE`/`MERGE USING` label MERGE_TARGET/SUBQUERY
        vars and must never admit a column."""
        assert _MERGE_COLUMN_CLAUSES == {
            "MERGE ON", "MERGE UPDATE SET", "MERGE WHEN", "MERGE INSERT",
            "JOIN ON",
        }


# ════════════════════════════════════════════════════════════════════════
# Synthetic MERGE fixture — ON + UPDATE SET + WHEN NOT MATCHED INSERT
# ════════════════════════════════════════════════════════════════════════

MERGE_FIXTURE = """\
MERGE INTO gps_accounts AS tgt
USING (
    SELECT
        t.account_id,
        t.amount,
        t.fee_amount,
        t.currency_code
    FROM gps_transactions t
    WHERE t.txn_status = 'SETTLED'
) AS src
ON tgt.account_id = src.account_id
WHEN MATCHED AND src.txn_status = 'PAYMENT' THEN
    UPDATE SET
        tgt.balance = tgt.balance + src.amount,
        tgt.last_fee = COALESCE(src.fee_amount, 0)
WHEN NOT MATCHED THEN
    INSERT (account_id, balance, currency_code)
    VALUES (src.account_id, src.amount, src.currency_code)
"""

# Same statement with the USING projection RENAMED — the false-positive
# shape the admission must keep out (`account_id` is not a
# gps_transactions column here).
MERGE_RENAMED_FIXTURE = """\
MERGE INTO gps_accounts AS tgt
USING (
    SELECT t.source_account_id AS account_id, t.amount
    FROM gps_transactions t
) AS src
ON tgt.account_id = src.account_id
WHEN MATCHED THEN
    UPDATE SET tgt.balance = tgt.balance + src.amount
"""


class TestSyntheticMergeFixture:
    def _fixture_graph(self, sql: str, name: str):
        result = _extract(sql, name)
        deps = build_dependency_graph(result, "")
        return result, deps

    def test_on_set_and_when_columns_all_connected(self):
        """Every physical-owner column of the MERGE's ON, UPDATE SET and
        WHEN NOT MATCHED INSERT clauses carries its belongs-to edge."""
        result, deps = self._fixture_graph(MERGE_FIXTURE, "synth_merge")
        # 11 — ON operand; 14/15 — UPDATE SET RHS reads; 18 — WHEN/VALUES.
        for column, line, clause in [
                ("gps_transactions.account_id", 11, "MERGE ON"),
                ("gps_transactions.amount", 14, "MERGE UPDATE SET"),
                ("gps_transactions.fee_amount", 15, "MERGE UPDATE SET"),
                ("gps_transactions.currency_code", 18, "MERGE WHEN")]:
            col = _var(result, column, line)
            assert (col.defined_in or "").strip().upper() == clause
            edges = _incoming(result, deps, col, "SCHEMA", "TABLE_COLUMN")
            assert any(src.name == "gps_transactions" for src, _ in edges), (
                f"{column} @L{line} ({clause}) not connected to its table")

    def test_fixture_is_topology_clean(self):
        """The whole fixture passes the hard topology checks — a MERGE is
        not a special case that needs a waiver."""
        result, deps = self._fixture_graph(MERGE_FIXTURE, "synth_merge")
        vd = [{"id": v.id, "name": v.name,
               "variable_type": v.variable_type.value,
               "source_columns": v.source_columns,
               "source_tables": v.source_tables,
               "defined_in": v.defined_in, "is_output": v.is_output}
              for v in result.variables]
        dd = [{"source_id": d.source_id, "target_id": d.target_id,
               "relationship": d.relationship, "operation": d.operation,
               "sql_context": d.sql_context} for d in deps]
        info = {"component_link_usage", "ambiguous_base_names", "alias_edges",
                "tables_view_isolation", "duplicate_nodes",
                "duplicate_table_names", "node_name_uniqueness"}
        hard = {k: v for k, v in run_all_checks(vd, dd).items()
                if v and k not in info}
        assert not hard, f"synthetic MERGE fixture has hard errors: {hard}"

    def test_set_lhs_keeps_its_pass4a_edge(self):
        """A qualified SET target (`tgt.balance`) is a field of the MERGE
        TARGET alias — Pass 4a already wires it to the merge_target var, and
        Phase 4d-gc must not add a second belongs-to edge for it."""
        result, deps = self._fixture_graph(MERGE_FIXTURE, "synth_merge")
        lhs = _var(result, "tgt.balance", 14)
        edges = _incoming(result, deps, lhs, "SCHEMA", "TABLE_COLUMN")
        assert [src.name for src, _ in edges] == ["tgt"], (
            f"tgt.balance belongs-to edges: "
            + str([(src.name, src.variable_type.value) for src, _ in edges]))

    def test_renamed_projection_gains_no_edge(self):
        """The guard, in synthetic form: the twin of a renamed USING
        projection stays disconnected — the model must not fabricate the
        schema fact that gps_transactions has an account_id column."""
        result, deps = self._fixture_graph(MERGE_RENAMED_FIXTURE,
                                           "synth_merge_renamed")
        col = _var(result, "gps_transactions.account_id", 6)
        assert not _incoming(result, deps, col, "SCHEMA"), (
            "renamed USING projection gained a belongs-to edge — the "
            "admission fabricated a schema fact")
