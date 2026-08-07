"""Display-strategy module (v3.3.145): highlight_strategies registry.

The L2 response `highlights` is computed by a named strategy; the
registry is the single source of truth and unknown names must fall back
to the default 'single_line' so the response contract never breaks.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.highlight_strategies import (
    STRATEGIES,
    get_strategy,
    _label_only_ranges,
    _single_line_ranges,
)


def _graph(nodes):
    return {"nodes": [{"data": nd} for nd in nodes]}


def test_get_strategy_default_is_single_line():
    """The default strategy is 'single_line' — the v3.3.140 behavior."""
    assert get_strategy("single_line") is STRATEGIES["single_line"]
    assert get_strategy("single_line") is _single_line_ranges


def test_get_strategy_label_only_returns_no_ranges():
    """label_only suppresses the SQL-panel highlight ranges — [] for any
    input, regardless of the closure's field lines."""
    fn = get_strategy("label_only")
    assert fn is _label_only_ranges
    g = _graph([
        {"id": "n1", "variable_type": "column", "line_start": 13},
        {"id": "n2", "variable_type": "aggregate", "line_start": 27},
    ])
    assert fn(g, {"n1", "n2"}, "SELECT 1") == []


def test_get_strategy_unknown_name_falls_back_to_single_line():
    """An unknown strategy name must not crash or change semantics — the
    caller contract is get_strategy(name) -> callable, always."""
    assert get_strategy("no_such_strategy") is STRATEGIES["single_line"]
    assert get_strategy("") is STRATEGIES["single_line"]


def test_single_line_computes_field_like_closure_lines():
    """single_line renders one [line, line] per closure field-like var's
    line_start, merged when adjacent; synthetic line-0 nodes never emit a
    highlight (D2); non-field-like nodes are excluded."""
    g = _graph([
        {"id": "a", "variable_type": "column", "line_start": 13},
        {"id": "b", "variable_type": "column", "line_start": 14},
        {"id": "c", "variable_type": "table", "line_start": 16},  # not field-like
        {"id": "d", "variable_type": "literal", "line_start": 0},  # synthetic
        {"id": "e", "variable_type": "case", "line_start": 27},
    ])
    ranges = _single_line_ranges(g, {"a", "b", "c", "d", "e"}, "sql")
    assert ranges == [[13, 14], [27, 27]], ranges


def test_single_line_honors_highlight_ids():
    """Only the closure's vars (highlight_ids) light up — graph_data is
    the full graph, so the ids must gate eligibility."""
    g = _graph([
        {"id": "in", "variable_type": "column", "line_start": 5},
        {"id": "out", "variable_type": "column", "line_start": 9},
    ])
    assert _single_line_ranges(g, {"in"}, "sql") == [[5, 5]]
