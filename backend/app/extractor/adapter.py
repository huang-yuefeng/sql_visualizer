"""
Adapter — wraps existing extractor_v2 + new variable extraction + dependency graph.

Provides a unified interface for the full SQL analysis pipeline.
"""

import sys
from pathlib import Path

# Ensure the sql_field_extractor is importable
_FIELD_EXTRACTOR_PATH = Path(__file__).resolve().parent.parent.parent.parent.parent / "sql_field_extractor"
if str(_FIELD_EXTRACTOR_PATH) not in sys.path:
    sys.path.insert(0, str(_FIELD_EXTRACTOR_PATH))

from app.models.variable import VariableDefinition, VariableDependency
# Use v2 extractor (role-based Identifier walking — covers any SQL that sqlglot parses)
from app.extractor.variable_extractor_v2 import ExtractionResult, extract_variables_from_sql
from app.extractor.dependency_graph import build_dependency_graph
from app.extractor.sql_line_mapper import map_variables_to_lines


def run_full_analysis(sql_text: str, script_name: str) -> dict:
    """Run the complete analysis pipeline on a SQL script."""
    from app.services.logger import pipeline_start, stage_extract, stage_deps, stage_graph, pipeline_done
    from collections import Counter
    import time as _time
    _t0 = _time.time()

    pipeline_start(script_name, len(sql_text))

    # Phase 1: Variable extraction
    extract_result = extract_variables_from_sql(sql_text, script_name)
    from app.models.variable import VariableType
    tables = [v for v in extract_result.variables
              if v.variable_type == VariableType.TABLE]
    ctes = [v for v in extract_result.variables
            if v.variable_type == VariableType.CTE]
    stage_extract(len(extract_result.variables), len(tables), len(ctes))

    # Phase 2: Dependency graph
    dependencies = build_dependency_graph(extract_result, sql_text)
    stage_deps(len(dependencies), dict(Counter(d.relationship for d in dependencies)))

    # Phase 3: Line mapping
    line_map = map_variables_to_lines(extract_result.variables, sql_text)
    stage_graph(len(extract_result.variables), len(dependencies))

    pipeline_done((_time.time() - _t0) * 1000)

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
