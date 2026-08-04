"""
Adapter — wraps existing extractor_v2 + new variable extraction + dependency graph.

Provides a unified interface for the full SQL analysis pipeline.
"""

import sys

from app.models.variable import VariableDefinition, VariableDependency
# Use v2 extractor (role-based Identifier walking — covers any SQL that sqlglot parses)
from app.extractor.variable_extractor_v2 import ExtractionResult, extract_variables_from_sql
from app.extractor.dependency_graph import build_dependency_graph
from app.extractor.sql_line_mapper import map_variables_to_lines


import re

def _count_statement_types(sql_text: str) -> dict:
    """Count top-level statement types via regex."""
    upper = sql_text.upper()
    counts = {}
    for kw in ['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'MERGE', 'DROP', 'ALTER', 'WITH']:
        # Count occurrences at start of line or after semicolon (top-level)
        n = len(re.findall(rf'(?:^|;)\s*{kw}\s', upper, re.MULTILINE))
        if n > 0:
            counts[kw] = n
    return counts

def _count_clauses(sql_text: str) -> dict:
    """Count SQL clauses via regex."""
    upper = sql_text.upper()
    return {
        'FROM': len(re.findall(r'\bFROM\b', upper)),
        'JOIN': len(re.findall(r'\bJOIN\b', upper)),
        'WHERE': len(re.findall(r'\bWHERE\b', upper)),
        'GROUP_BY': len(re.findall(r'\bGROUP\s+BY\b', upper)),
        'ORDER_BY': len(re.findall(r'\bORDER\s+BY\b', upper)),
        'HAVING': len(re.findall(r'\bHAVING\b', upper)),
        'CTE': len(re.findall(r'\bWITH\b', upper)),
    }
def _count_functions(sql_text: str) -> dict:
    """Count function categories via regex."""
    upper = sql_text.upper()
    agg = len(re.findall(r'\b(SUM|COUNT|AVG|MAX|MIN)\s*\(', upper))
    xform = len(re.findall(r'\b(DATE|CAST|COALESCE|CONCAT|SUBSTR|TRIM|UPPER|LOWER|REPLACE|IFNULL|NVL)\s*\(', upper))
    win = len(re.findall(r'\b(ROW_NUMBER|RANK|DENSE_RANK|LAG|LEAD|SUM|COUNT|AVG)\s*\(.*\)\s*OVER\s*\(', upper))
    subq = len(re.findall(r'\(\s*SELECT\b', upper))
    return {'aggregate': agg, 'transform': xform, 'window': win, 'subquery': subq}
def _count_nesting(sql_text: str, cte_count: int) -> dict:
    """Count nesting depth and subquery count."""
    depth = 0; max_depth = 0; subq_count = 0
    for ch in sql_text:
        if ch == '(':
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch == ')':
            depth -= 1
    # Count subqueries: (SELECT ...)
    import re
    subq_count = len(re.findall(r'\(\s*SELECT\b', sql_text, re.IGNORECASE))
    return {'max_depth': max_depth, 'subqueries': subq_count, 'ctes': cte_count}


def run_full_analysis(sql_text: str, script_name: str, ws_id: str | None = None) -> dict:
    """Run the complete analysis pipeline on a SQL script."""
    from app.services.logger import pipeline_start, stage_extract, stage_deps, stage_graph, pipeline_done, pipeline_profile
    from collections import Counter
    import time as _time
    _t0 = _time.time()

    pipeline_start(script_name, len(sql_text), ws_id=ws_id)

    # Phase 1: Variable extraction
    extract_result = extract_variables_from_sql(sql_text, script_name)
    from app.models.variable import VariableType
    tables = [v for v in extract_result.variables
              if v.variable_type == VariableType.TABLE]
    ctes = [v for v in extract_result.variables
            if v.variable_type == VariableType.CTE]
    if extract_result.template_replacements:
        import time as _time
        print(f"[{_time.strftime('%H:%M:%S', _time.localtime())}]   🔧 template: {len(extract_result.template_replacements)} replacements: {extract_result.template_replacements[:10]}", file=sys.stderr, flush=True)
    stage_extract(len(extract_result.variables), len(tables), len(ctes), ws_id=ws_id)
    t1 = _time.time()

    # Phase 2: Dependency graph
    dependencies = build_dependency_graph(extract_result, sql_text)
    stage_deps(len(dependencies), dict(Counter(d.relationship for d in dependencies)), ws_id=ws_id)
    t2 = _time.time()

    # Phase 3: Line mapping
    line_map = map_variables_to_lines(extract_result.variables, sql_text)
    stage_graph(len(extract_result.variables), len(dependencies), ws_id=ws_id)
    t3 = _time.time()

    pipeline_done((_time.time() - _t0) * 1000, ws_id=ws_id)

    # Emit profile block (R15) — always to stderr, to SSE when ws_id available
    t_now = _time.time()
    total_ms = int((t_now - _t0) * 1000)
    counts = {
        'sql_len': len(sql_text),
        'line_count': len(sql_text.split(chr(10))),
        'stmt_count': sum(_count_statement_types(sql_text).values()),
        'stmt_types': _count_statement_types(sql_text),
        'clauses': _count_clauses(sql_text),
        'funcs': _count_functions(sql_text),
        'var_types': dict(Counter(v.variable_type.value for v in extract_result.variables)),
        'edge_types': dict(Counter(d.relationship for d in dependencies)),
        'nesting': _count_nesting(sql_text, len(ctes)),
        'timing': {
            'parse': max(0, int((t1 - _t0) * 1000)),
            'extract': max(0, int((t2 - t1) * 1000)),
            'deps': max(0, int((t3 - t2) * 1000)),
            'graph': max(0, int((total_ms - max(0, int((t3 - _t0) * 1000))))),
            'total': total_ms,
        },
    }
    pipeline_profile(script_name, counts, ws_id=ws_id)

    # Serialize variables to dicts
    variables_json = [_var_to_dict(v) for v in extract_result.variables]
    deps_json = [_dep_to_dict(d) for d in dependencies]

    # Build line map JSON
    line_map_json = {k: list(v) for k, v in line_map.items()}

    return {
        "script_name": script_name,
        "sql_text": sql_text,
        "variables": variables_json,
        "dependencies": deps_json,
        "line_map": line_map_json,
        "table_count": len(tables),
        "cte_count": len(ctes),
        "total_variables": len(extract_result.variables),
        "total_dependencies": len(dependencies),
        "template_replacements": extract_result.template_replacements,
    }


def _var_to_dict(v: VariableDefinition) -> dict:
    """Convert VariableDefinition to JSON-safe dict."""
    return {
        "id": v.id,
        "name": v.name,
        "variable_type": v.variable_type.value,
        "sql_expression": v.sql_expression,
        "source_columns": v.source_columns,
        "source_variables": v.source_variables,
        "source_tables": v.source_tables,
        "defined_in": v.defined_in,
        "line_start": v.line_start,
        "line_end": v.line_end,
        "data_type": v.data_type,
        "context": v.context,
        "is_output": v.is_output,
    }


def _dep_to_dict(d: VariableDependency) -> dict:
    """Convert VariableDependency to JSON-safe dict."""
    return {
        "source_id": d.source_id,
        "target_id": d.target_id,
        "relationship": d.relationship,
        "operation": d.operation,
        "sql_context": d.sql_context,
    }
