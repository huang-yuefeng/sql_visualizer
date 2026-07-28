"""Unified dataflow extraction — variables + dependencies + schema inference + lineage.

This is the single entry point for SQL-to-dataflow analysis. L1/L2 graph builders
in dataflow_service.py are thin wrappers that consume this module's output.

Pipeline:
  SQL text → variable_extractor_v2 → dependency_graph → schema_inference → lineage
"""

from __future__ import annotations
import hashlib
import json
import logging
import sys
from pathlib import Path
from collections import Counter

_log = logging.getLogger('dataflow')

# Eager imports to fail fast if modules are missing
from app.extractor.adapter import run_full_analysis
from app.extractor.schema_inference import infer_table_schemas
from app.extractor.lineage import (
    compute_field_lineage,
    filter_graph_by_lineage,
    filter_relevant,
)
from app.services.graph_service import build_graph_data


def extract_script_dataflow(
    sql_text: str,
    script_name: str,
    ws_id: str | None = None,
    *,
    target_table: str | None = None,
    target_field: str | None = None,
    lineage_mode: bool = True,
) -> dict:
    """Run full extraction for one script: variables → deps → schemas → lineage → graph.

    Returns a dict with everything needed by L1/L2 builders:
      {
        "script_name": str,
        "sql_text": str,
        "variables": [...],
        "dependencies": [...],
        "table_schemas": {table: {col, ...}},
        "lineage_set": set(node_ids) | None,
        "graph_data": dict (raw Cytoscape graph from build_graph_data),
        "analysis": dict (raw result from run_full_analysis),
      }
    """
    # Phase 1-2: variable extraction + dependency graph (existing pipeline)
    analysis = run_full_analysis(sql_text, script_name, ws_id=ws_id)

    variables = analysis.get("variables", [])
    dependencies = analysis.get("dependencies", [])

    # Phase 3: schema inference (NEW for R18)
    table_schemas = infer_table_schemas(variables, dependencies)
    analysis["table_schemas"] = table_schemas
    _log.info(f'R18 schema inference: {len(table_schemas)} tables inferred')

    # Phase 4: build graph data (existing graph_service)
    graph_data = build_graph_data(analysis)

    # Phase 5: lineage computation (if target specified)
    lineage_set = None
    if target_table and target_field and lineage_mode:
        lineage_set = compute_field_lineage(graph_data, target_table, target_field)
        _log.info(f'R18 lineage: {len(lineage_set)} nodes in lineage '
                  f'(out of {len(graph_data.get("nodes",[]))} total)')

    return {
        "script_name": script_name,
        "sql_text": sql_text,
        "variables": variables,
        "dependencies": dependencies,
        "table_schemas": table_schemas,
        "lineage_set": lineage_set,
        "graph_data": graph_data,
        "analysis": analysis,
    }


def extract_multiple_scripts(
    scripts: list[tuple[str, str]],  # [(script_name, sql_text), ...]
    ws_id: str | None = None,
) -> list[dict]:
    """Run extraction for multiple scripts.

    Each item in `scripts` is (script_name, sql_text).
    Returns list of dicts from extract_script_dataflow().
    """
    results = []
    for name, sql in scripts:
        result = extract_script_dataflow(sql, name, ws_id=ws_id)
        results.append(result)
    return results


def build_cross_script_table_schemas(
    script_results: list[dict],
) -> dict[str, set[str]]:
    """Merge table_schemas from multiple scripts into one cross-script view.

    A table may appear in multiple scripts. Schemas from later scripts
    extend (but do not replace) schemas from earlier scripts.
    """
    merged: dict[str, set[str]] = {}
    for result in script_results:
        for table, cols in result.get("table_schemas", {}).items():
            if table not in merged:
                merged[table] = set(cols)
            else:
                merged[table].update(cols)
    return merged
