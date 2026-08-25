"""ISSUE-6 / R32 — L2 line-merged views: merge-pass unit tests.

The line-merged pass (`l2_builder.build_line_merged_edges`) rewrites a
closure's EDGES only, so that one SQL line corresponds to one edge:

* field→table promotion (field endpoint → its parent table, never dropped,
  never kept as a field endpoint);
* same-line same-table-pair merge → one edge, single arrow (one direction)
  / double arrow (both directions);
* type removed — the merged edge is an untyped "FLOW" edge;
* self-loop kept ONLY as the line's sole edge, absorbed otherwise;
* no-SQL-line edges dropped;
* a line spanning >2 tables → one edge per table pair.

These tests exercise `build_line_merged_edges` directly (a pure pass over
synthetic node/edge dicts) — no workspace/parse machinery.
"""

from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.l2_builder import build_line_merged_edges


def _tbl(nid):
    return {"data": {"id": nid, "type": "source_table", "label": nid}}


def _fld(nid, parent):
    return {"data": {"id": nid, "type": "field", "parent": parent}}


def _edge(nid, source, target, line):
    return {"data": {"id": nid, "source": source, "target": target,
                     "highlight_line": line}}


def test_same_line_same_pair_field_edges_merge_to_double_arrow():
    """Rule 1+2: two same-line field edges between the same table pair
    (opposite directions) collapse to ONE double-arrow table edge."""
    nodes = [_tbl("T1"), _tbl("T2"), _fld("f1", "T1"), _fld("f2", "T2")]
    edges = [_edge("e1", "f1", "f2", 10), _edge("e2", "f2", "f1", 10)]
    out = build_line_merged_edges(edges, nodes)
    assert len(out) == 1, f"expected one merged edge, got {len(out)}"
    d = out[0]["data"]
    # both field endpoints promoted to their parent tables; direction is a
    # double arrow (canonical min→max ordering)
    assert d["source"] == "T1" and d["target"] == "T2", d
    assert d["bidirectional"] is True
    assert d["edge_type"] == "FLOW" and d["label"] == "FLOW", d
    assert d["highlight_line"] == 10


def test_field_edge_promoted_to_table_single_arrow():
    """Rule 1: a single-direction field edge becomes a table edge."""
    nodes = [_tbl("T1"), _tbl("T2"), _fld("f1", "T1")]
    edges = [_edge("e1", "f1", "T2", 11)]
    out = build_line_merged_edges(edges, nodes)
    assert len(out) == 1
    d = out[0]["data"]
    assert d["source"] == "T1" and d["target"] == "T2", d
    assert d["bidirectional"] is False


def test_self_loop_absorbed_when_line_has_other_edge():
    """Rule 4: a self-loop on a line that also has another edge is
    absorbed (never emitted alongside it)."""
    nodes = [_tbl("T1"), _tbl("T2")]
    edges = [_edge("e1", "T1", "T1", 20), _edge("e2", "T1", "T2", 20)]
    out = build_line_merged_edges(edges, nodes)
    assert len(out) == 1
    d = out[0]["data"]
    assert (d["source"], d["target"]) == ("T1", "T2"), d
    assert d["bidirectional"] is False
    assert all(e["data"]["source"] != e["data"]["target"] for e in out), \
        "no self-loop may survive on a shared line"


def test_sole_self_loop_kept():
    """Rule 4: a self-loop that is the line's ONLY edge is kept."""
    nodes = [_tbl("T1")]
    edges = [_edge("e1", "T1", "T1", 30)]
    out = build_line_merged_edges(edges, nodes)
    assert len(out) == 1
    d = out[0]["data"]
    assert d["source"] == "T1" and d["target"] == "T1", d
    assert d["highlight_line"] == 30
    assert d["bidirectional"] is False


def test_lineless_edge_dropped():
    """Rule 5: an edge with no SQL-line reference (0 / None) is dropped."""
    nodes = [_tbl("T1"), _tbl("T2")]
    edges = [
        _edge("e1", "T1", "T2", 0),
        _edge("e2", "T1", "T2", None),
        _edge("e3", "T1", "T2", 40),
    ]
    out = build_line_merged_edges(edges, nodes)
    assert len(out) == 1
    assert out[0]["data"]["highlight_line"] == 40


def test_line_spanning_three_tables_emits_one_edge_per_pair():
    """Rule 6: a line spanning >2 tables emits one edge per table pair."""
    nodes = [_tbl("T1"), _tbl("T2"), _tbl("T3")]
    edges = [
        _edge("e1", "T1", "T2", 50),
        _edge("e2", "T2", "T3", 50),
        _edge("e3", "T1", "T3", 50),
    ]
    out = build_line_merged_edges(edges, nodes)
    pairs = {(e["data"]["source"], e["data"]["target"]) for e in out}
    assert pairs == {("T1", "T2"), ("T2", "T3"), ("T1", "T3")}, pairs
    assert len(out) == 3
