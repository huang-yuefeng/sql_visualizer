"""
SQL Snippet Extractor — extracts and formats the SQL text associated with
every edge and node in the dependency graph.

Runs as a post-processing step after graph construction. For each edge,
finds the SQL lines that connect the source and target variables. For each
node, aggregates SQL from all its connected edges.

Output is ready for human-readable display in the frontend side panel.
"""

import re
from collections import defaultdict


def _find_line_range(sql_text: str, expression: str) -> tuple[int, int]:
    """Find the line range for a SQL expression in the source text."""
    if not expression or not sql_text:
        return 0, 0
    lines = sql_text.split("\n")
    search = expression.strip()[:50]
    if not search:
        return 0, 0
    for i, line in enumerate(lines, start=1):
        if search[:20] in line:
            return i, i
    return 0, 0


def _extract_lines(sql_text: str, start: int, end: int, context: int = 2) -> str:
    """Extract lines [start-context, end+context] from SQL text, with line numbers."""
    if start <= 0 or not sql_text:
        return ""
    lines = sql_text.split("\n")
    begin = max(0, start - 1 - context)
    finish = min(len(lines), max(end, start) + context)
    result = []
    for i in range(begin, finish):
        prefix = f"{i+1:>4d} | " if i+1 >= start and i+1 <= end else f"{'':>4s}   "
        result.append(f"{prefix}{lines[i]}")
    return "\n".join(result)


def extract_edge_sql(
    analysis: dict,
    source_id: str,
    target_id: str,
) -> str:
    """Extract the SQL segment connecting two variables in an edge.

    Uses the line numbers from line_map to find the original SQL lines
    that define both variables, plus the lines between them.
    """
    variables = analysis.get("variables", [])
    line_map = analysis.get("line_map", {})
    sql_text = analysis.get("sql_text", "")

    src = next((v for v in variables if v["id"] == source_id), None)
    tgt = next((v for v in variables if v["id"] == target_id), None)

    if not src or not tgt or not sql_text:
        return ""

    sl = line_map.get(source_id, (0, 0))
    tl = line_map.get(target_id, (0, 0))
    s_start, s_end = sl if isinstance(sl, (list, tuple)) else (sl, sl)
    t_start, t_end = tl if isinstance(tl, (list, tuple)) else (tl, tl)

    parts = []

    # Source variable SQL
    if src.get("sql_expression"):
        parts.append(f"-- Source: {src['name']} [{src.get('variable_type','')}]")
        parts.append(src["sql_expression"])

    # Source original lines
    if s_start > 0:
        parts.append(f"\n-- Source lines {s_start}-{s_end}:")
        parts.append(_extract_lines(sql_text, s_start, s_end))

    # Target variable SQL
    if tgt.get("sql_expression"):
        parts.append(f"\n-- Target: {tgt['name']} [{tgt.get('variable_type','')}]")
        parts.append(tgt["sql_expression"])

    # Target original lines
    if t_start > 0:
        parts.append(f"\n-- Target lines {t_start}-{t_end}:")
        parts.append(_extract_lines(sql_text, t_start, t_end))

    # Connecting SQL (lines between source and target)
    if s_start > 0 and t_start > 0:
        lo = min(s_start, t_start)
        hi = max(s_end, t_end)
        if hi - lo <= 30:  # only show if the range is reasonable
            parts.append(f"\n-- Connecting SQL (lines {lo}-{hi}):")
            parts.append(_extract_lines(sql_text, lo, hi, context=0))

    return "\n".join(parts)


def extract_node_sql(analysis: dict, variable_id: str) -> str:
    """Extract all SQL associated with a node and its connected edges."""
    variables = analysis.get("variables", [])
    dependencies = analysis.get("dependencies", [])
    line_map = analysis.get("line_map", {})
    sql_text = analysis.get("sql_text", "")

    var = next((v for v in variables if v["id"] == variable_id), None)
    if not var or not sql_text:
        return ""

    parts = []

    # Variable definition
    parts.append(f"-- Variable: {var['name']} [{var.get('variable_type','')}]")
    parts.append(f"-- Defined in: {var.get('defined_in','TOP')}")
    if var.get("sql_expression"):
        parts.append(f"\n{var['sql_expression']}")

    # Original source lines
    lr = line_map.get(variable_id, (0, 0))
    l_start, l_end = lr if isinstance(lr, (list, tuple)) else (lr, lr)
    if l_start > 0:
        parts.append(f"\n-- Source lines {l_start}-{l_end}:")
        parts.append(_extract_lines(sql_text, l_start, l_end))

    # Connected edges
    related = [d for d in dependencies
               if d["source_id"] == variable_id or d["target_id"] == variable_id]
    if related:
        parts.append(f"\n-- Connected edges ({len(related)}):")
        for d in related[:20]:  # limit to 20 edges
            is_src = d["source_id"] == variable_id
            other_id = d["target_id"] if is_src else d["source_id"]
            other = next((v for v in variables if v["id"] == other_id), None)
            other_name = other["name"] if other else other_id
            direction = "→" if is_src else "←"
            parts.append(f"  {direction} [{d.get('relationship','')}] {other_name}")

    return "\n".join(parts)


def build_snippet_data(analysis: dict) -> dict:
    """Build edge and node SQL snippet data for the entire graph.

    Returns a dict with:
      - edge_snippets: { "src_id->tgt_id": sql_text }
      - node_snippets: { "node_id": sql_text }
    """
    dependencies = analysis.get("dependencies", [])
    variables = analysis.get("variables", [])

    # Limit: only compute snippets for the first 500 edges (performance)
    edge_snippets = {}
    for d in dependencies[:500]:
        key = f"{d['source_id']}->{d['target_id']}"
        edge_snippets[key] = extract_edge_sql(analysis, d["source_id"], d["target_id"])

    node_snippets = {}
    for v in variables[:200]:  # limit to 200 nodes
        node_snippets[v["id"]] = extract_node_sql(analysis, v["id"])

    return {
        "edge_snippets": edge_snippets,
        "node_snippets": node_snippets,
    }
