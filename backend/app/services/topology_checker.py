"""
Topology Checker — validates graph integrity after construction.

All topological checks live here. Each check is a function that takes
(variables, dependencies) and returns a list of issues found.

Add new checks by defining a function and registering it in ALL_CHECKS.
"""

from collections import defaultdict
from app.models.variable import VariableType


# ── Public API ────────────────────────────────────────────────────────────

def run_all_checks(variables: list, dependencies: list) -> dict:
    """Run all registered topology checks. Returns {check_name: issues_list}."""
    results = {}
    for name, check_fn in ALL_CHECKS:
        issues = check_fn(variables, dependencies)
        if issues:
            results[name] = issues
    return results


def register_check(name: str, fn):
    """Register a new topology check."""
    ALL_CHECKS.append((name, fn))


# ── Check Registry ─────────────────────────────────────────────────────────

ALL_CHECKS: list[tuple[str, callable]] = []


# ── Check 1: No isolated nodes ────────────────────────────────────────────

def _check_isolated_nodes(variables, dependencies):
    """Every node must have at least one edge."""
    connected = set()
    for d in dependencies:
        connected.add(d["source_id"])
        connected.add(d["target_id"])
    return [
        f"[{v.get('variable_type','?')}] {v['name']}"
        for v in variables if v["id"] not in connected
    ]

register_check("isolated_nodes", _check_isolated_nodes)


# ── Check 2: Single connected component ───────────────────────────────────

def _check_disconnected_components(variables, dependencies):
    """The graph must be one connected piece."""
    if not variables:
        return []
    parent = {v["id"]: v["id"] for v in variables}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
    for d in dependencies:
        union(d["source_id"], d["target_id"])
    comps = defaultdict(list)
    for v in variables:
        comps[find(v["id"])].append(v["name"])
    if len(comps) > 1:
        sizes = sorted([len(c) for c in comps.values()], reverse=True)
        return [f"{len(comps)} components (sizes: {sizes})"]
    return []

register_check("disconnected_components", _check_disconnected_components)


# ── Check 3: No duplicate nodes ───────────────────────────────────────────

def _check_duplicate_nodes(variables, dependencies):
    """No two nodes with the same (name, type)."""
    from collections import Counter
    keys = [(v["name"], v.get("variable_type","")) for v in variables]
    dupes = {k: c for k, c in Counter(keys).items() if c > 1}
    return [f"({n},{t}) x{c}" for (n, t), c in dupes.items()]

register_check("duplicate_nodes", _check_duplicate_nodes)


# ── Check 4: No duplicate edges ───────────────────────────────────────────

def _check_duplicate_edges(variables, dependencies):
    """No two edges with the same (source, target, relationship)."""
    from collections import Counter
    keys = [(d["source_id"], d["target_id"], d.get("relationship","")) for d in dependencies]
    dupes = {k: c for k, c in Counter(keys).items() if c > 1}
    return [f"({s[:8]}->{t[:8]},{r}) x{c}" for (s, t, r), c in dupes.items()]

register_check("duplicate_edges", _check_duplicate_edges)


# ── Check 5: No duplicate table names ─────────────────────────────────────

def _check_duplicate_table_names(variables, dependencies):
    """CTE tables should not also appear as separate DATABASE_TABLE entries."""
    from collections import Counter
    tables = [v["name"] for v in variables
              if v.get("variable_type") in ("database_table", "cte_table")]
    dupes = {n: c for n, c in Counter(tables).items() if c > 1}
    return [f"{n} x{c}" for n, c in dupes.items()]

register_check("duplicate_table_names", _check_duplicate_table_names)


# ── Check 6: Column connectivity ──────────────────────────────────────────

def _check_column_connectivity(variables, dependencies):
    """Every table_column with a table prefix (e.g. 't.amount') must have
    at least 1 BELONGS_TO incoming edge from its source table.

    Bare columns (no dot) are HAVING/ORDER BY references — they don't
    need BELONGS_TO; their REFERENCES edge handles the connection.
    """
    issues = []
    incoming = defaultdict(list)
    outgoing = defaultdict(list)
    for d in dependencies:
        incoming[d["target_id"]].append(d)
        outgoing[d["source_id"]].append(d)

    # Build set of known table prefixes
    table_names = {v["name"] for v in variables
                   if v.get("variable_type") in ("database_table","cte_table","merge_target","subquery_result")}

    for v in variables:
        if v.get("variable_type") != "table_column":
            continue
        if "." not in v.get("name", ""):
            continue
        # Only check columns whose table prefix is a known table in this graph
        prefix = v["name"].split(".", 1)[0]
        if prefix not in table_names:
            continue  # subquery-scoped — table not in this scope
        in_edges = incoming.get(v["id"], [])
        has_source = any(d.get("relationship") in ("BELONGS_TO", "FEEDS_INTO", "OPERATES_ON")
                        for d in in_edges)
        if not has_source:
            issues.append(f"[table_column] {v['name']}: no connection from source table '{prefix}'")

    return issues

register_check("column_connectivity", _check_column_connectivity)


# ── Check 7: COMPONENT_LINK usage ─────────────────────────────────────────

def _check_component_link_usage(variables, dependencies):
    """COMPONENT_LINK should only bridge genuinely separate subgraphs.
    If components share column names, they should use explicit edges instead.
    """
    issues = []
    cl_edges = [d for d in dependencies if d.get("relationship") == "COMPONENT_LINK"]
    if not cl_edges:
        return []

    # Count COMPONENT_LINK edges — flag if there are many (potential design issue)
    var_index = {v["id"]: v for v in variables}
    for d in cl_edges:
        src = var_index.get(d["source_id"], {})
        tgt = var_index.get(d["target_id"], {})
        issues.append(
            f"COMPONENT_LINK: [{src.get('variable_type','?')}] {src.get('name','?')} "
            f"↔ [{tgt.get('variable_type','?')}] {tgt.get('name','?')}"
        )

    return issues

