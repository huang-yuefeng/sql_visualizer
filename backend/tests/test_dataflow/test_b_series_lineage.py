"""B-series lineage-engine semantics tests.

Phases 1+2 of the B-series lineage work (extractor/lineage.py):

  - SUBSET edges are NEVER walked (always_bidir=False,
    propagates_value=False in EDGE_SEMANTICS): nothing enters the lineage
    closure over a SUBSET bridge. Phase 1 (stopgap) skipped SUBSET edges
    leading INTO constant producers (literal/aggregate/window neighbors);
    Phase 2 made SUBSET non-walkable altogether. This is what previously
    kept constant literals ('X'/'Y'/'N'), filter-only columns and detached
    second-statement vars in the graph (measured on the sample script:
    78 fields → 12 after the fix).
  - JOIN edges admit materialized join-key EXPRESSION partners
    UNCONDITIONALLY (the key construction is part of the field's data
    flow; its operand columns then arrive via REF), while
    vtable/cte/plain-column partners stay conditional on production
    evidence.
  - None-seed guards: compute_field_lineage / filter_relevant return
    empty / unchanged gracefully on None or empty table/field arguments
    (never AttributeError/TypeError on the name-based fallback).
"""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.lineage import (
    compute_field_lineage,
    filter_relevant,
)


def _node(nid, label, vt):
    return {"data": {"id": nid, "label": label, "variable_type": vt,
                     "node_type": vt}}


def _edge(src, tgt, etype):
    return {"data": {"source": src, "target": tgt, "edge_type": etype,
                     "relationship": etype}}


# ── Phase 2: SUBSET is never walked ─────────────────────────────────────

def test_subset_edge_never_walked():
    """A node reachable from the seed ONLY over a SUBSET bridge stays out of
    the closure — SUBSET is pure connectivity padding, not data flow."""
    graph = {
        "nodes": [
            _node("T", "customers", "table"),
            _node("c1", "customers.id", "column"),
            _node("T2", "audit_log", "table"),
            _node("c2", "audit_log.ts", "column"),
        ],
        "edges": [
            _edge("T", "c1", "SCHEMA"),
            _edge("c1", "c2", "SUBSET"),
            _edge("T2", "c2", "SCHEMA"),
        ],
    }
    R = compute_field_lineage(graph, "customers", "id")
    assert {"c1", "T"} <= R
    assert "c2" not in R, "SUBSET bridge must not pull the neighbor in"
    assert "T2" not in R, "SUBSET bridge must not pull the neighbor's table in"


def test_subset_never_pulls_constant_literal():
    """Regression: pre-B-series the 'X'/'Y'/'N'/'1'/'2' literal columns of
    the sample script entered the closure over SUBSET bridges (they were
    among the 78 fields). A literal reachable only via SUBSET stays out."""
    graph = {
        "nodes": [
            _node("T", "customers", "table"),
            _node("c1", "customers.id", "column"),
            _node("VT", "⟐ sub", "virtual_table"),
            _node("lit", "X", "literal"),
        ],
        "edges": [
            _edge("T", "c1", "SCHEMA"),
            _edge("c1", "VT", "SUBSET"),
            _edge("VT", "lit", "SCHEMA"),
        ],
    }
    R = compute_field_lineage(graph, "customers", "id")
    assert "c1" in R
    assert "lit" not in R
    assert "VT" not in R


def test_subset_into_aggregate_producer_not_walked():
    """Phase-1 stopgap scenario: SUBSET leading into an aggregate producer
    (SUM over a filter-only column) — excluded by the Phase-2 rule."""
    graph = {
        "nodes": [
            _node("T", "customers", "table"),
            _node("c1", "customers.id", "column"),
            _node("ag", "SUM(t2.amt)", "aggregate"),
            _node("T2", "t2", "table"),
            _node("amt", "t2.amt", "column"),
        ],
        "edges": [
            _edge("T", "c1", "SCHEMA"),
            _edge("c1", "ag", "SUBSET"),
            _edge("T2", "amt", "SCHEMA"),
        ],
    }
    R = compute_field_lineage(graph, "customers", "id")
    assert "c1" in R
    assert "ag" not in R and "amt" not in R and "T2" not in R


# ── Phase 2: JOIN expression partners — unconditional, others conditional ─

def test_join_expression_partner_admitted_unconditionally():
    """A materialized join-key EXPRESSION node (CONCAT/RPAD/|| on columns)
    is admitted via JOIN even with NO production evidence of its own — the
    key construction itself is part of the field's flow."""
    graph = {
        "nodes": [
            _node("T", "t1", "table"),
            _node("k", "t1.k", "column"),
            _node("expr", "CONCAT(t2.a, t2.b)", "expression"),
            _node("T2", "t2", "table"),
            _node("a", "t2.a", "column"),
            _node("b", "t2.b", "column"),
        ],
        "edges": [
            _edge("T", "k", "SCHEMA"),
            _edge("k", "expr", "JOIN"),
            _edge("a", "expr", "REF"),
            _edge("b", "expr", "REF"),
            _edge("T2", "a", "SCHEMA"),
            _edge("T2", "b", "SCHEMA"),
        ],
    }
    R = compute_field_lineage(graph, "t1", "k")
    assert {"k", "T", "expr"} <= R
    assert {"a", "b", "T2"} <= R, \
        "operand columns (REF) and their table (SCHEMA reverse) follow"


def test_join_vtable_partner_stays_conditional():
    """A virtual-table/CTE/plain-column JOIN partner without production
    evidence is NOT admitted (the conditional production-evidence rule)."""
    graph = {
        "nodes": [
            _node("T", "t1", "table"),
            _node("k", "t1.k", "column"),
            _node("vt", "⟐ sub", "virtual_table"),
            _node("j", "t2.j", "column"),
            _node("T2", "t2", "table"),
        ],
        "edges": [
            _edge("T", "k", "SCHEMA"),
            _edge("k", "j", "JOIN"),
            _edge("vt", "j", "SCHEMA"),
            _edge("T2", "j", "SCHEMA"),
        ],
    }
    R = compute_field_lineage(graph, "t1", "k")
    assert "k" in R
    assert "j" not in R and "vt" not in R and "T2" not in R


def test_join_conditional_partner_admitted_with_production():
    """The same vtable partner IS admitted once it carries a production
    edge back into the closure (conditional rule satisfied)."""
    graph = {
        "nodes": [
            _node("T", "t1", "table"),
            _node("k", "t1.k", "column"),
            _node("vt", "⟐ sub", "virtual_table"),
            _node("j", "t2.j", "column"),
            _node("T2", "t2", "table"),
        ],
        "edges": [
            _edge("T", "k", "SCHEMA"),
            _edge("k", "j", "JOIN"),
            _edge("vt", "j", "SCHEMA"),
            _edge("T2", "j", "SCHEMA"),
            _edge("j", "k", "REF"),  # production evidence: j produces k
        ],
    }
    R = compute_field_lineage(graph, "t1", "k")
    assert {"k", "j", "T2"} <= R


def test_join_expression_partner_through_filter_relevant():
    """The unconditional expression admission survives the full
    filter_relevant path (L2's entry point)."""
    graph = {
        "nodes": [
            _node("T", "t1", "table"),
            _node("k", "t1.k", "column"),
            _node("expr", "CONCAT(t2.a, t2.b)", "expression"),
            _node("a", "t2.a", "column"),
            _node("T2", "t2", "table"),
        ],
        "edges": [
            _edge("T", "k", "SCHEMA"),
            _edge("k", "expr", "JOIN"),
            _edge("a", "expr", "REF"),
            _edge("T2", "a", "SCHEMA"),
        ],
    }
    out = filter_relevant(graph, "t1", "k")
    ids = {n["data"]["id"] for n in out["nodes"]}
    assert {"T", "k", "expr", "a", "T2"} <= ids


# ── None-seed guards ────────────────────────────────────────────────────

def test_compute_field_lineage_none_guard():
    """None/empty table or field → empty closure, never a crash."""
    graph = {
        "nodes": [_node("T", "t", "table")],
        "edges": [],
    }
    assert compute_field_lineage(graph, None, "f") == set()
    assert compute_field_lineage(graph, "t", None) == set()
    assert compute_field_lineage(graph, "", "") == set()
    assert compute_field_lineage(None, "t", "f") == set()
    assert compute_field_lineage(graph, "t", "f") == set()  # no seed → empty


def test_filter_relevant_none_guard():
    """None/empty table or field → graph returned unchanged (the name-based
    fallback would crash on `None in label` without the guard)."""
    graph = {
        "nodes": [_node("T", "t", "table")],
        "edges": [],
    }
    assert filter_relevant(graph, None, None) is graph
    assert filter_relevant(graph, "t", None) is graph
    assert filter_relevant(graph, None, "f") is graph
