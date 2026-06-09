"""
SQL Line Mapper — map variables to their line numbers in the source SQL.
"""

from app.models.variable import VariableDefinition


def map_variables_to_lines(
    variables: list[VariableDefinition], sql_text: str
) -> dict[str, tuple[int, int]]:
    """Map each variable to its (line_start, line_end) in the source SQL.

    Uses the variable's sql_expression to find matching lines in the source.
    For multi-line expressions, captures the contiguous line range.

    Args:
        variables: List of extracted variables.
        sql_text: Original SQL source text.

    Returns:
        Dict mapping variable ID to (start_line, end_line) tuple.
    """
    if not sql_text:
        return {}

    lines = sql_text.split("\n")
    line_map: dict[str, tuple[int, int]] = {}

    for var in variables:
        expr = var.sql_expression.strip()
        if not expr:
            line_map[var.id] = (0, 0)
            continue

        # Try to find the first line containing this expression
        start_line = 0
        end_line = 0

        # Search: find first line that contains the start of the expression
        search_key = expr[:40].strip()
        if search_key:
            for i, line in enumerate(lines, start=1):
                if search_key in line:
                    start_line = i
                    end_line = i
                    # For multi-line expressions, extend until the expression
                    # no longer contains references to this block
                    expr_lines = expr.split("\n")
                    if len(expr_lines) > 1:
                        end_line = min(start_line + len(expr_lines) - 1, len(lines))
                    break

        line_map[var.id] = (start_line, end_line)

    return line_map
