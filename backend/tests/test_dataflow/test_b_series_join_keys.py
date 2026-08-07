"""B-series Phase 2: join-key expression materialization + B5 label hygiene.

A JOIN ON predicate comparing a computed expression over columns
(CONCAT/RPAD/|| …) with another key — e.g.
    CONCAT(p2.poctcd, p2.pogmab) = p1.lending_ref
— materializes the expression side as an EXPRESSION variable
(variable_extractor_v2._walk_join_key_expressions) with:

  - REF edges from the operand columns to the expression node
    (dependency_graph Phase 3 via source_columns; classified REF because
    the target's defined_in is "JOIN ON"),
  - a JOIN edge from the OTHER side of the comparison to the expression
    node (dependency_graph Phase 6b, operation JOIN_KEY; the other side's
    id is recorded on source_variables).

Only expressions with Column operands are materialized: plain
column=column and column=literal comparisons are already represented by
the JOIN ON column vars; DPipe ("||") renders as CONCAT under hive; the
inner halves of nested calls (RPAD inside CONCAT) are NOT materialized
as separate phantoms (the walk filters on exp.Predicate — DPipe is a
Binary but not a Predicate).

B5: rendered labels never carry the internal "⟐ "/"}" context markers
(regression: "⟐ loan_final}:join:acc" garbage labels).
"""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.extractor.dependency_graph import build_dependency_graph
from app.models.variable import VariableType


def _extract(sql):
    res = extract_variables_from_sql(sql, "join_keys.sql")
    deps = build_dependency_graph(res, sql)
    return res.variables, deps


def _by_id(vars_):
    return {v.id: v for v in vars_}


def test_concat_join_key_materialized():
    """CONCAT over columns in JOIN ON → EXPRESSION var with REF edges to
    the operands and a JOIN_KEY edge from the other side of the
    comparison."""
    sql = """INSERT OVERWRITE TABLE stg_loan
SELECT p1.lending_ref
FROM bdm_acc_loan_info p1
JOIN bdm_evt_loan_trans p2
  ON CONCAT(p2.poctcd, p2.pogmab) = p1.lending_ref;"""
    vars_, deps = _extract(sql)
    by_id = _by_id(vars_)

    exprs = [v for v in vars_
             if v.variable_type == VariableType.EXPRESSION]
    assert len(exprs) == 1, f"expected exactly one expression var: {exprs}"
    expr = exprs[0]
    assert expr.name == "CONCAT(p2.poctcd, p2.pogmab)"
    assert expr.defined_in == "JOIN ON"
    # operand order is not load-bearing (walk order may vary) — compare sets
    assert set(expr.source_columns) == {"p2.poctcd", "p2.pogmab"}
    assert expr.source_tables == ["p2"]
    assert expr.context.startswith("TOP")

    other = by_id[expr.source_variables[0]]
    assert other.name == "p1.lending_ref"

    # REF edges: each operand column → the expression node
    refs = {d.source_id: d for d in deps
            if d.target_id == expr.id and d.relationship == "REF"}
    assert len(refs) == 2, f"expected 2 REF edges, got {len(refs)}"
    ref_src_names = {by_id[sid].name for sid in refs}
    assert ref_src_names == {"p2.poctcd", "p2.pogmab"}

    # JOIN_KEY edge: the other side of the comparison → the expression
    jk = [d for d in deps
          if d.relationship == "JOIN" and d.operation == "JOIN_KEY"]
    assert len(jk) == 1, f"expected 1 JOIN_KEY edge, got {jk}"
    assert jk[0].target_id == expr.id
    assert jk[0].source_id == other.id


def test_rpad_inner_part_not_phantom():
    """RPAD nested inside CONCAT materializes ONLY the full key expression
    — the inner RPAD(...) half must not appear as a separate phantom node
    (regression found on the sample script)."""
    sql = """INSERT OVERWRITE TABLE stg_loan
SELECT p1.k
FROM bdm_acc_loan_info p1
JOIN bdm_evt_loan_trans p2
  ON CONCAT(RPAD(p2.iiapty, 3, '0'), p2.iiblno) = p1.k;"""
    vars_, _ = _extract(sql)
    exprs = [v for v in vars_
             if v.variable_type == VariableType.EXPRESSION]
    assert len(exprs) == 1, f"expected only the full CONCAT: {exprs}"
    assert exprs[0].name == "CONCAT(RPAD(p2.iiapty, 3, '0'), p2.iiblno)"
    assert set(exprs[0].source_columns) == {"p2.iiapty", "p2.iiblno"}


def test_hive_dpipe_join_key_materialized():
    """'||' concatenation (hive dialect — DPipe renders as CONCAT) is
    materialized as the key expression."""
    sql = """INSERT OVERWRITE TABLE stg_loan
SELECT p1.k
FROM bdm_acc_loan_info p1
JOIN bdm_evt_loan_trans p2
  ON p1.k = p2.a || p2.b;"""
    vars_, _ = _extract(sql)
    exprs = [v for v in vars_
             if v.variable_type == VariableType.EXPRESSION]
    assert len(exprs) == 1, f"expected the || key materialized: {exprs}"
    # sqlglot's hive normalization renders || as CONCAT(a, b) but the
    # operand walk order is not guaranteed — compare as a set.
    assert set(exprs[0].source_columns) == {"p2.a", "p2.b"}


def test_literal_side_not_materialized():
    """column = literal comparisons already have the JOIN ON column var —
    no expression node is created."""
    sql = """INSERT OVERWRITE TABLE stg_loan
SELECT p1.k
FROM bdm_acc_loan_info p1
JOIN bdm_evt_loan_trans p2
  ON p1.status = 'X';"""
    vars_, _ = _extract(sql)
    exprs = [v for v in vars_
             if v.variable_type == VariableType.EXPRESSION]
    assert exprs == []


def test_column_column_join_not_materialized():
    """Plain column=column keys are already represented by the JOIN ON
    column vars — no expression node is created."""
    sql = """INSERT OVERWRITE TABLE stg_loan
SELECT p1.k
FROM bdm_acc_loan_info p1
JOIN bdm_evt_loan_trans p2
  ON p1.k = p2.k;"""
    vars_, _ = _extract(sql)
    exprs = [v for v in vars_
             if v.variable_type == VariableType.EXPRESSION]
    assert exprs == []


def test_connector_skipped_but_inner_keys_materialized():
    """AND/OR connectors are not themselves keys; their inner EQ predicates
    with expression sides still materialize."""
    sql = """INSERT OVERWRITE TABLE stg_loan
SELECT p1.k
FROM bdm_acc_loan_info p1
JOIN bdm_evt_loan_trans p2
  ON p1.k = p2.k AND CONCAT(p2.a, p2.b) = p1.j;"""
    vars_, _ = _extract(sql)
    exprs = [v for v in vars_
             if v.variable_type == VariableType.EXPRESSION]
    assert [e.name for e in exprs] == ["CONCAT(p2.a, p2.b)"]


def test_expr_expr_join_key_both_sides_paired():
    """expression=expression JOIN ON (two CONCAT sides): BOTH sides
    materialize and record each other — the pairing is order-independent
    (regression: only the second-materialized side used to record the
    pair, so the first side's source_variables stayed empty)."""
    sql = """INSERT OVERWRITE TABLE stg_loan
SELECT p1.k
FROM bdm_acc_loan_info p1
JOIN bdm_evt_loan_trans p2
  ON CONCAT(p1.iidcptl, p1.iidcptc) = CONCAT(p2.ihctcd, p2.ihctorg);"""
    vars_, deps = _extract(sql)
    exprs = [v for v in vars_
             if v.variable_type == VariableType.EXPRESSION
             and v.defined_in == "JOIN ON"]
    assert len(exprs) == 2, f"expected 2 expression vars: {exprs}"
    by_name = {e.name: e for e in exprs}
    assert set(by_name) == {"CONCAT(p1.iidcptl, p1.iidcptc)",
                            "CONCAT(p2.ihctcd, p2.ihctorg)"}
    left, right = (by_name["CONCAT(p1.iidcptl, p1.iidcptc)"],
                   by_name["CONCAT(p2.ihctcd, p2.ihctorg)"])
    # both sides record the counterpart (symmetric pairing)
    assert left.source_variables == [right.id], left.source_variables
    assert right.source_variables == [left.id], right.source_variables
    # both sides carry an incident JOIN_KEY edge
    jk = {(d.source_id, d.target_id) for d in deps
          if d.relationship == "JOIN" and d.operation == "JOIN_KEY"}
    assert (right.id, left.id) in jk and (left.id, right.id) in jk, jk


def test_bdm_sample_join_key_expressions_all_paired():
    """Regression: in the real BDM sample, every JOIN ON expression side
    (7/7) records its counterpart — the two expression=expression CONCAT
    comparisons used to leave the first-materialized side with EMPTY
    source_variables. (v3.3.140: 8 → 7 — the phantom-dedup removed one
    raw-walk duplicate registration.)"""
    sample = (BACKEND_DIR.parent / "samples" / "sql_sample_v1"
              / "BDM_ACC_LOAN_INFO_SUP_M.sql")
    if not sample.exists():
        pytest.skip(f"sample not found: {sample}")
    res = extract_variables_from_sql(sample.read_text(), sample.name)
    exprs = [v for v in res.variables
             if v.variable_type == VariableType.EXPRESSION
             and (v.defined_in or "").upper() == "JOIN ON"]
    assert len(exprs) == 7, f"expected 7 JOIN ON expressions: {exprs}"
    empty = [e.name for e in exprs if not e.source_variables]
    assert empty == [], f"JOIN ON expressions with empty source_variables: {empty}"


def test_b5_labels_never_carry_context_markers():
    """Regression: VT/column labels were sometimes rendered from the whole
    context path ("⟐ loan_final}:join:accu") — B5 takes only the terminal
    segment. No variable name may contain '}' or a ':' inside a VT name."""
    sql = """WITH loan_final AS (
    SELECT p1.lending_ref, p1.branch_code
    FROM bdm_acc_loan_info p1
)
INSERT OVERWRITE TABLE stg_out
SELECT accu.lending_ref, accu.branch_code
FROM loan_final accu
JOIN (SELECT poctcd FROM bdm_evt_loan_trans) p2
  ON p2.poctcd = accu.lending_ref;"""
    vars_, _ = _extract(sql)
    names = [v.name for v in vars_]
    assert not any("}" in n for n in names), \
        [n for n in names if "}" in n]
    vt_names = [v.name for v in vars_
                if v.variable_type == VariableType.VIRTUAL_TABLE]
    assert vt_names and all(n.startswith("⟐ ") for n in vt_names)
    assert not any(":" in n or "/" in n for n in vt_names), \
        [n for n in vt_names if ":" in n or "/" in n]
    # terminal-segment labels: the join-context VT is "⟐ p2", never
    # "⟐ loan_final}:join:p2"
    assert "⟐ p2" in vt_names, vt_names
