"""Graph integrity tests — uses the topology checker module.

All topological checks are defined in app/services/topology_checker.py.
This test file runs them against every SQL sample.
"""

import sys
from pathlib import Path
from collections import Counter

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.extractor.dependency_graph import build_dependency_graph
from app.services.topology_checker import run_all_checks

SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "samples"


def _all_sample_files():
    """Yield (filename, sql_text) for all test SQL files."""
    for f in sorted(SAMPLES_DIR.glob("*.sql")):
        if f.name.endswith(".sql"):
            yield f.name, f.read_text()
    fin_dir = SAMPLES_DIR / "financial"
    if fin_dir.exists():
        for f in sorted(fin_dir.glob("fin_query*.sql")):
            yield f"financial/{f.name}", f.read_text()


def _var_dicts(variables):
    """Convert VariableDefinition objects to dicts for the checker."""
    return [
        {
            "id": v.id,
            "name": v.name,
            "variable_type": v.variable_type.value,
            "source_columns": v.source_columns,
            "source_tables": v.source_tables,
            "defined_in": v.defined_in,
            "is_output": v.is_output,
        }
        for v in variables
    ]


def _dep_dicts(deps):
    """Convert VariableDependency objects to dicts for the checker."""
    return [
        {
            "source_id": d.source_id,
            "target_id": d.target_id,
            "relationship": d.relationship,
            "operation": d.operation,
            "sql_context": d.sql_context,
        }
        for d in deps
    ]


class TestGraphIntegrity:
    """Run ALL topology checks against every SQL sample."""

    @pytest.mark.parametrize("fname,sql", list(_all_sample_files()))
    def test_topology_checks_pass(self, fname, sql):
        """Hard-error topology checks must return zero issues.

        Informational checks (component_link_usage, ambiguous_base_names)
        are warnings, not errors — they don't cause test failure.
        """
        r = extract_variables_from_sql(sql, fname)
        if len(r.variables) == 0:
            return  # DDL files — skip
        deps = build_dependency_graph(r, "")
        vars_dict = _var_dicts(r.variables)
        deps_dict = _dep_dicts(deps)

        results = run_all_checks(vars_dict, deps_dict)
        info_checks = {"component_link_usage", "ambiguous_base_names", "alias_edges", "tables_view_isolation", "duplicate_nodes", "duplicate_table_names", "node_name_uniqueness"}
        hard_errors = {k: v for k, v in results.items()
                       if v and k not in info_checks}
        assert len(hard_errors) == 0, \
            f"{fname}: {len(hard_errors)} hard errors: " \
            + "; ".join(f"{name}: {issues}" for name, issues in hard_errors.items())
