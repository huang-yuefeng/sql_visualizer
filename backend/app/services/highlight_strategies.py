"""Display highlight strategies — SQL-panel highlight computation for the L2 view.

v3.3.145: GET .../level2 accepts an optional `highlight_strategy` query
param; the registry maps a strategy name to the callable that computes the
response `highlights` (SQL-panel line ranges). Strategies affect ONLY the
response `highlights` — graph nodes/edges and their labels are identical
regardless of strategy.

  - single_line (default): one [line, line] range per node-carried
    line_start of the closure's field-like vars (the v3.3.140 behavior).
  - label_only: no SQL-panel ranges — returns [] (graph labels unchanged).

Every strategy callable has the same signature
(graph_data, highlight_ids, sql_text) -> [[line, line], ...].
"""

# ── single_line: the v3.3.140 _compute_highlight_ranges behavior ──────
# The strict table.field walker's field-like var classes — the vars whose
# line_start carries the field's own occurrence line (design doc §4
# FIELD_LIKE). Members verified against VariableType (models/variable.py):
# the doc's "computed"/"variable" are not enum members — the actual
# computed-value members are "case" and "transform".
FIELD_LIKE_TYPES = frozenset({
    "column", "cte_column", "literal", "aggregate", "expression",
    "window", "case", "transform",
})


def _single_line_ranges(graph_data: dict, highlight_ids: set,
                        sql_text: str) -> list:
    """Compute line ranges to highlight from node-carried single lines.

    v3.3.140: highlights are single line numbers [line, line] taken from
    the node-carried line_start (computed by the extractor's
    comment-skipping line mapper) of the closure's field-like vars — the
    line_map-based computation is gone. Only field-like nodes
    (FIELD_LIKE_TYPES, or defined_in == "PARTITION") are eligible: the
    strict table.field closure's field vars are exactly what must light
    up. graph_data is the FULL graph while highlight_ids come from the
    filtered graph, so this yields exactly the closure's field lines.
    """
    ranges = []
    for n in graph_data.get("nodes", []):
        nd = n.get("data", n)
        if nd.get("id", "") not in highlight_ids:
            continue
        vt = nd.get("variable_type", "")
        if vt not in FIELD_LIKE_TYPES and \
                (nd.get("defined_in") or "").upper() != "PARTITION":
            continue
        line = int(nd.get("line_start") or 0)
        # D2: (0,0) was the "no line matched" placeholder — highlighting
        # line 0 would paint the editor's gutter. Never emit it.
        if line < 1:
            continue
        ranges.append([line, line])
    if not ranges:
        return []

    # Merge overlapping/adjacent ranges
    ranges.sort()
    merged = [ranges[0]]
    for r in ranges[1:]:
        last = merged[-1]
        if r[0] <= last[1] + 1:
            merged[-1][1] = max(last[1], r[1])
        else:
            merged.append(r)
    return merged


def _label_only_ranges(graph_data: dict, highlight_ids: set,
                       sql_text: str) -> list:
    """label_only: no SQL-panel highlight ranges — nothing lights up.

    The graph labels are unchanged; this strategy only suppresses the
    response `highlights` (returns [] unconditionally).
    """
    return []


# Registry of display strategies (v3.3.145). Each callable is
# (graph_data, highlight_ids, sql_text) -> [[line, line], ...].
STRATEGIES = {
    "single_line": _single_line_ranges,
    "label_only": _label_only_ranges,
}


def get_strategy(name: str):
    """Resolve a display strategy by name; unknown names fall back to the
    default 'single_line' (the response `highlights` contract stays stable)."""
    return STRATEGIES.get(name, STRATEGIES["single_line"])
