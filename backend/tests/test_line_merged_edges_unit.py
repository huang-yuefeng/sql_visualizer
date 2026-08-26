"""L-E5 / L-E6 — unit tests for `build_line_merged_edges`.

These pin the two code-review fixes in the line-merged pass
(`l2_builder.build_line_merged_edges`):

  * L-E5 (silent data loss) — a line whose only edges are two DISTINCT
    self-loops (`t1→t1` + `t2→t2`) must emit BOTH, not drop both. The old
    `len(self_loops) > 1` check silently swallowed every self-loop when there
    was no non-self pair on the line. The corrected rule: a self-loop `X→X`
    is absorbed only when `X` also appears in a NON-self pair on the line
    (that pair then carries the flow); otherwise it is kept.

  * L-E6 (TypeError) — an edge missing its `source`/`target` key previously
    produced `None` endpoints which later crashed `src <= tgt` /
    `sorted(pairs.items())`. The malformed edge is now skipped.

These tests are table-only (`nodes=[]`, no field→table promotion) so the
assertions exercise the merge/self-loop/malformed-edge logic directly.
"""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.l2_builder import build_line_merged_edges


def _edge(src, tgt, line, edge_type="TABLE_FLOW"):
    return {"data": {"source": src, "target": tgt,
                     "highlight_line": line, "edge_type": edge_type}}


def _sources(merged):
    return {e["data"]["source"] for e in merged}


def _targets(merged):
    return {e["data"]["target"] for e in merged}


def test_le5_two_distinct_self_loops_both_survive():
    # A line whose only edges are two DISTINCT self-loops. Each is its own
    # table's sole edge and must both survive (the old `len(self_loops) > 1`
    # dropped them both, emitting zero edges).
    edges = [_edge("t1", "t1", 10), _edge("t2", "t2", 10)]
    merged = build_line_merged_edges(edges, [])

    assert len(merged) == 2
    assert _sources(merged) == {"t1", "t2"}
    assert _targets(merged) == {"t1", "t2"}
    assert all(e["data"]["source"] == e["data"]["target"] for e in merged)
    assert all(e["data"]["highlight_line"] == 10 for e in merged)


def test_le5_self_loop_absorbed_when_table_has_non_self_pair():
    # `t1→t1` + `t1→t2` on the same line: the self-loop's table `t1` also
    # appears in a NON-self pair, so the self-loop is absorbed and only the
    # t1↔t2 edge remains.
    edges = [_edge("t1", "t1", 10), _edge("t1", "t2", 10)]
    merged = build_line_merged_edges(edges, [])

    assert len(merged) == 1
    assert _sources(merged) == {"t1"}
    assert _targets(merged) == {"t2"}


def test_le6_malformed_edge_without_endpoints_dropped_without_raising():
    # A malformed edge dict with no source/target key must be dropped without
    # raising; a valid t1→t2 on the same line still emits exactly 1 edge.
    edges = [
        {"data": {"highlight_line": 10, "edge_type": "TABLE_FLOW"}},
        _edge("t1", "t2", 10),
    ]
    merged = build_line_merged_edges(edges, [])

    assert len(merged) == 1
    assert _sources(merged) == {"t1"}
    assert _targets(merged) == {"t2"}
