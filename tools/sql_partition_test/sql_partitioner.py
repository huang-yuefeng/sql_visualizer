"""
SQL Atomic Operation Partition — uses mo-sql-parsing to split SQL
into the smallest meaningful operations (smaller than L2 edges).

Each atomic operation maps to a SQL clause:
  SELECT columns, FROM table, WHERE condition, JOIN ... ON, GROUP BY, etc.

Multiple atomic operations may map to one L2 edge.
Invariant: union of all atomic ops = entire SQL, 0 overlap.
"""
import re

# mo-sql-parsing operation keys → our partition types
ATOMIC_TYPE_MAP = {
    'select': 'SELECT',
    'from': 'TABLE_FLOW',
    'where': 'FILTER',
    'join': 'JOIN',
    'groupby': 'GROUP',
    'having': 'FILTER',
    'orderby': 'ORDER',
    'limit': 'LIMIT',
    'with': 'CTE',
    'union': 'UNION',
    'union_all': 'UNION',
}

# Statement keywords for line-boundary detection
CLAUSE_KEYWORDS = {
    'SELECT', 'FROM', 'WHERE', 'JOIN', 'INNER', 'LEFT', 'RIGHT',
    'OUTER', 'CROSS', 'FULL', 'GROUP', 'HAVING', 'ORDER', 'LIMIT',
    'UNION', 'INSERT', 'UPDATE', 'DELETE', 'MERGE', 'WITH', 'INTO',
    'CREATE', 'DROP', 'ALTER',
}


def _find_clause_lines(sql_text: str) -> list[tuple]:
    """
    Find all clause start lines by scanning for SQL keywords.
    Returns [(line_number, keyword, end_line), ...] sorted.
    """
    lines = sql_text.split('\n')
    n = len(lines)
    boundaries = []

    for i, line in enumerate(lines):
        stripped = line.strip().upper()
        for kw in sorted(CLAUSE_KEYWORDS, key=len, reverse=True):
            # Match keyword at start of line (possibly after whitespace)
            if stripped.startswith(kw) and (
                len(stripped) == len(kw) or
                stripped[len(kw)] in (' ', '\t', '(')
            ):
                boundaries.append((i + 1, kw))
                break

    # Dedup: keep first occurrence of each keyword
    seen_kw = set()
    dedup = []
    for line_no, kw in boundaries:
        if kw not in seen_kw:
            seen_kw.add(kw)
            dedup.append((line_no, kw))
    boundaries = sorted(dedup)

    # Compute end_line for each boundary
    result = []
    for idx, (start_line, kw) in enumerate(boundaries):
        next_start = boundaries[idx + 1][0] if idx + 1 < len(boundaries) else n + 1
        end_line = next_start - 1
        result.append((start_line, kw, end_line))

    return result


def partition_sql(sql_text: str, dialect: str = "mysql") -> list[dict]:
    """
    Partition SQL into atomic clause-level segments.

    Returns: [{start_line, end_line, type, sql}, ...]
    """
    lines = sql_text.split('\n')
    n = len(lines)
    if n == 0:
        return []

    # Try mo-sql-parsing for atomic operation names
    atomic_ops = {}
    try:
        from mo_sql_parsing import parse
        parsed = parse(sql_text)
        if parsed:
            for key, ptype in ATOMIC_TYPE_MAP.items():
                if key in parsed:
                    atomic_ops[key] = ptype
    except Exception:
        pass

    # Fallback: keyword-based clause splitting
    boundaries = _find_clause_lines(sql_text)

    if not boundaries:
        return [{'start_line': 1, 'end_line': n, 'type': 'OTHER', 'sql': sql_text.strip()}]

    # Build segments
    segments = []

    # Pre-clause segment (comments, etc.)
    first_start = boundaries[0][0]
    if first_start > 1:
        pre_lines = lines[:first_start-1]
        pre_text = '\n'.join(pre_lines).strip()
        if pre_text and not all(l.strip().startswith('--') or l.strip() == ''
                               for l in pre_lines):
            segments.append({
                'start_line': 1, 'end_line': first_start - 1,
                'type': 'OTHER', 'sql': pre_text,
            })

    for start_line, kw, end_line in boundaries:
        seg_sql = '\n'.join(lines[start_line-1:end_line]).strip()
        if not seg_sql:
            continue

        # Determine type: prefer mo-sql-parsing type, fall back to keyword
        kw_lower = kw.lower()
        seg_type = 'OTHER'
        for op_key, op_type in ATOMIC_TYPE_MAP.items():
            if op_key in kw_lower or kw_lower in op_key:
                seg_type = op_type
                break

        segments.append({
            'start_line': start_line,
            'end_line': end_line,
            'type': seg_type,
            'sql': seg_sql,
        })

    return segments
