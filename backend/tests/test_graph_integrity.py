"""Graph integrity tests — uses the topology checker module.

All topological checks are defined in app/services/topology_checker.py.
This test file runs them against every SQL sample.
"""

import sys
import re
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


def _r44_derived_read_twin_names(vars_dict):
    """R44 (2026-08-28, user ruling "walker occurrence coverage") — the
    derived-read twins the extractor registers as occurrence-side fields
    (`_register_flow_occurrence_twins` family 2: the outer read
    `source.account_id` through a single-physical-source derived alias
    materializes the occurrence `gps_transactions.account_id`).

    These are occurrence ATTRIBUTIONS, not schema members — txn.txn_count
    (COUNT born inside the subquery) is not a column OF gps_transactions —
    so the checker's BELONGS_TO premise ("a dotted column is a member of
    its prefix table") does not apply. Their model witness is the REF edge
    from their occurrence origin (the derived-alias read), which the
    checker's accepted set (SCHEMA/SELECT/DML) does not count; the
    physical model keys them under the table entity. Signature: column,
    non-output, name = {source_tables[0]}.{col}, source_columns non-empty
    (the occurrence origin). Write twins are NOT waived: they are only
    written, and their write-leg witness (Phase 4c OUTPUT SCHEMA) exists —
    the checker's contract 'every displayed field has a model edge' holds
    for them and must keep holding."""
    names = set()
    for v in vars_dict:
        if v.get("variable_type") != "column":
            continue
        st = v.get("source_tables") or []
        name = v.get("name") or ""
        if (not v.get("is_output") and v.get("source_columns")
                and st and "." in name
                and name.split(".", 1)[0].lower() == st[0].lower()):
            names.add(name)
    return names


# The topology checker's issue IDENTITY header: every issue opens with
# `[<variable_type>] <name>: ` and only the prose after that colon varies
# per check. Waiving on the PARSED identity (never on rendered prose)
# keeps the R44 waiver alive across wording changes — review L19.
_ISSUE_HEADER = re.compile(r"^\[(?P<vt>[^\]]+)\] (?P<name>.+?): ")
# isolated_nodes appends the offending edge count ("1e, need ≥2").
_EDGE_COUNT = re.compile(r"^(?P<n>\d+)e\b")


def _apply_twin_waiver(issues, waived, require_edge=False):
    """Drop the issues that name a waived R44 read twin.

    Returns (kept, unparsed). `unparsed` holds issues that mention a
    waived twin but do not match _ISSUE_HEADER (or, when require_edge is
    set, whose edge count is not a bare integer) — a checker message
    change must fail LOUDLY here ("update the header parser"), never
    silently disable the waiver.
    require_edge: isolated_nodes waives a read twin only when it still
    carries ≥1 edge — the REF witness from its occurrence origin. A twin
    with 0 edges is a real regression and stays a hard error.
    """
    kept, unparsed = [], []
    for issue in issues:
        m = _ISSUE_HEADER.match(issue)
        if m is None:
            if any(name in issue for name in waived):
                unparsed.append(issue)
            else:
                kept.append(issue)
            continue
        if m.group("name") not in waived:
            kept.append(issue)
            continue
        if require_edge:
            c = _EDGE_COUNT.match(issue[m.end():])
            if c is None:
                unparsed.append(issue)
                continue
            if int(c.group("n")) < 1:
                kept.append(issue)   # 0-edge twin: real regression
                continue
    return kept, unparsed


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
        # R44 (2026-08-28): derived-read twins are occurrence attributions
        # (REF-witnessed by their origin read), not schema members —
        # their column_connectivity findings are waived (see
        # _r44_derived_read_twin_names). Write twins stay covered.
        waived = _r44_derived_read_twin_names(vars_dict)
        unparsed = []
        if waived:
            # column_connectivity: the twin's witness is the REF from its
            # occurrence origin, which the check's accepted set
            # (SCHEMA/SELECT/DML) does not count.
            # isolated_nodes: that same single-REF witness can sit under
            # the check's "dotted column needs ≥2 edges" bar — same
            # false-positive class, so the same identity is waived there
            # (≥1 edge only; a 0-edge twin stays a hard error).
            for check, require_edge in (("column_connectivity", False),
                                        ("isolated_nodes", True)):
                if check not in results:
                    continue
                results[check], bad = _apply_twin_waiver(
                    results[check], waived, require_edge=require_edge)
                unparsed += bad
        assert unparsed == [], (
            "topology_checker issue text no longer matches the "
            f"`[<type>] <name>:` header the R44 twin waiver parses "
            f"(update _ISSUE_HEADER, do not re-pin prose): {unparsed}")
        info_checks = {"component_link_usage", "ambiguous_base_names", "alias_edges", "tables_view_isolation", "duplicate_nodes", "duplicate_table_names", "node_name_uniqueness"}
        hard_errors = {k: v for k, v in results.items()
                       if v and k not in info_checks}
        assert len(hard_errors) == 0, \
            f"{fname}: {len(hard_errors)} hard errors: " \
            + "; ".join(f"{name}: {issues}" for name, issues in hard_errors.items())
