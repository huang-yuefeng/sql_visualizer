"""Graph integrity tests — dedup + isolated nodes + connected components.

Run after every source code modification to verify that:
  1. No duplicate nodes (same name + type) — every variable is unique
  2. No duplicate edges (same source + target + relationship)
  3. No variable is isolated (every node has at least one edge)
  4. The graph has exactly one connected component
"""

import sys, os
from pathlib import Path
from collections import defaultdict

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import extract_variables_from_sql  # noqa: E402
from app.extractor.dependency_graph import build_dependency_graph  # noqa: E402

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


def _find_components(variables, deps):
    """Union-Find: returns list of connected component node lists."""
    parent = {v.id: v.id for v in variables}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    for d in deps:
        union(d.source_id, d.target_id)
    comps = defaultdict(list)
    for v in variables:
        comps[find(v.id)].append(v)
    return list(comps.values())


class TestGraphIntegrity:
    """Verify every SQL sample produces a fully-connected graph."""

    @pytest.mark.parametrize("fname,sql", list(_all_sample_files()))
    def test_no_duplicate_nodes(self, fname, sql):
        """Every variable should be unique by (name, type) — no duplicates."""
        r = extract_variables_from_sql(sql, fname)
        keys = [(v.name, v.variable_type.value) for v in r.variables]
        dupes = {k: c for k, c in __import__('collections').Counter(keys).items() if c > 1}
        assert len(dupes) == 0, \
            f"{fname}: {len(dupes)} duplicate node types: " \
            + ", ".join(f"({n},{t})×{c}" for (n,t),c in sorted(dupes.items())[:10])

    @pytest.mark.parametrize("fname,sql", list(_all_sample_files()))
    def test_no_duplicate_edges(self, fname, sql):
        """Every edge should be unique by (source, target, relationship)."""
        r = extract_variables_from_sql(sql, fname)
        deps = build_dependency_graph(r, sql)
        keys = [(d.source_id, d.target_id, d.relationship) for d in deps]
        dupes = {k: c for k, c in __import__('collections').Counter(keys).items() if c > 1}
        assert len(dupes) == 0, \
            f"{fname}: {len(dupes)} duplicate edges: " \
            + ", ".join(f"({s[:8]}→{t[:8]},{r})×{c}" for (s,t,r),c in sorted(dupes.items())[:10])

    @pytest.mark.parametrize("fname,sql", list(_all_sample_files()))
    def test_no_duplicate_table_names(self, fname, sql):
        """CTE tables should not also appear as separate DATABASE_TABLE entries."""
        r = extract_variables_from_sql(sql, fname)
        from collections import Counter
        tables = [v for v in r.variables if v.variable_type.value in ('database_table','cte_table')]
        names = Counter(v.name for v in tables)
        dupes = {n: c for n, c in names.items() if c > 1}
        assert len(dupes) == 0, \
            f"{fname}: {len(dupes)} duplicate table names: " \
            + ", ".join(f"{n}×{c}" for n, c in sorted(dupes.items())[:10])

    @pytest.mark.parametrize("fname,sql", list(_all_sample_files()))
    def test_no_isolated_nodes(self, fname, sql):
        """Every variable should have at least one edge."""
        r = extract_variables_from_sql(sql, fname)
        deps = build_dependency_graph(r, sql)
        connected = set()
        for d in deps:
            connected.add(d.source_id)
            connected.add(d.target_id)
        isolated = [v for v in r.variables if v.id not in connected]
        assert len(isolated) == 0, \
            f"{fname}: {len(isolated)} isolated nodes: " \
            + ", ".join(f"[{v.variable_type.value}] {v.name}" for v in isolated[:10])

    @pytest.mark.parametrize("fname,sql", list(_all_sample_files()))
    def test_single_connected_component(self, fname, sql):
        """The graph should have exactly 1 connected component."""
        r = extract_variables_from_sql(sql, fname)
        if len(r.variables) == 0:
            return  # DDL files produce 0 variables — skip
        deps = build_dependency_graph(r, sql)
        comps = _find_components(r.variables, deps)
        assert len(comps) == 1, \
            f"{fname}: {len(comps)} disconnected components (expected 1). " \
            + f"Component sizes: {sorted([len(c) for c in comps], reverse=True)}. " \
            + f"Smallest: {[(v.variable_type.value, v.name) for v in min(comps, key=len)]}"
