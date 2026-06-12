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


# ── Check 1: No isolated nodes ───────────────────────────────────────────

def _check_isolated_nodes(variables, dependencies):
    """Edge count rules by node type:
       - column, cte_column: must have ≥2 edges (source + target)
       - all other types: must have ≥1 edge
    """
    from collections import Counter
    edge_counts = Counter()
    for d in dependencies:
        edge_counts[d["source_id"]] += 1
        edge_counts[d["target_id"]] += 1
    issues = []
    col_types = {"column", "cte_column"}
    # table: only needs ≥1 edge (ALIAS or SCHEMA)
    # — redundant table→VT edges removed, columns cover the data flow
    table_types = {"table", "view", "cte", "virtual_table",
                   "merge_target", "union_branch", "subquery"}
    for v in variables:
        c = edge_counts.get(v["id"], 0)
        vt = v.get("variable_type", "")
        if vt in col_types:
            if c < 2:
                issues.append(f"[{vt}] {v['name']}: {c}e, need ≥2 (source + target)")
        elif vt in table_types:
            if c == 0:
                issues.append(f"[{vt}] {v['name']}: ZERO edges")
        else:
            if c == 0:
                issues.append(f"[{vt}] {v['name']}: ZERO edges")
    return issues

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
              if v.get("variable_type") in ("table", "cte")]
    dupes = {n: c for n, c in Counter(tables).items() if c > 1}
    return [f"{n} x{c}" for n, c in dupes.items()]

register_check("duplicate_table_names", _check_duplicate_table_names)


# ── Check 6: Column connectivity ──────────────────────────────────────────

def _check_column_connectivity(variables, dependencies):
    """Every column with a table prefix (e.g. 't.amount') must have
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
                   if v.get("variable_type") in ("table","view","cte","merge_target","subquery")}

    for v in variables:
        if v.get("variable_type") != "column":
            continue
        if "." not in v.get("name", ""):
            continue
        # Only check columns whose table prefix is a known table in this graph
        prefix = v["name"].split(".", 1)[0]
        if prefix not in table_names:
            continue  # subquery-scoped — table not in this scope
        in_edges = incoming.get(v["id"], [])
        has_source = any(d.get("relationship") in ("SCHEMA", "SELECT", "DML")
                        for d in in_edges)
        if not has_source:
            issues.append(f"[column] {v['name']}: no connection from source table '{prefix}'")

    return issues

register_check("column_connectivity", _check_column_connectivity)


# ── Check 7: COMPONENT_LINK usage ─────────────────────────────────────────

def _check_component_link_usage(variables, dependencies):
    """Flag excessive SUBSET edges that may indicate missing explicit edges.

    SUBSET edges are a safety net that bridges disconnected components.
    A few are normal; too many suggests named column references aren't
    being resolved properly.
    """
    cl_edges = [d for d in dependencies if d.get("relationship") == "SUBSET"]
    var_index = {v["id"]: v for v in variables}
    issues = []

    # Only flag SUBSET edges that connect two table-like nodes directly
    # (no columns involved). These suggest a missing explicit reference.
    table_types = {"table", "view", "cte", "virtual_table", "merge_target"}
    for d in cl_edges:
        src = var_index.get(d["source_id"], {})
        tgt = var_index.get(d["target_id"], {})
        src_type = src.get("variable_type", "")
        tgt_type = tgt.get("variable_type", "")
        # Both ends are table-like → suspicious, should have column bridge
        if src_type in table_types and tgt_type in table_types:
            issues.append(
                f"Table→table SUBSET: [{src_type}] {src.get('name','?')} "
                f"↔ [{tgt_type}] {tgt.get('name','?')} — missing column bridge?"
            )

    # Also flag if total SUBSET count exceeds a threshold
    if len(cl_edges) > 20:
        issues.append(f"High SUBSET count: {len(cl_edges)} edges (threshold: 20)")

    return issues


register_check("component_link_usage", _check_component_link_usage)


# ── Check 8: Node (name, type) uniqueness ──────────────────────────────

def _check_node_name_uniqueness(variables, dependencies):
    """Every (name, type) pair must be unique — enforced by dedup logic."""
    from collections import Counter
    issues = []
    keys = [(v["name"], v.get("variable_type", "")) for v in variables]
    dupes = {k: c for k, c in Counter(keys).items() if c > 1}
    for (name, vt), count in dupes.items():
        vars_ = [v for v in variables
                if v["name"] == name and v.get("variable_type") == vt]
        contexts = [v.get("context", "?") for v in vars_]
        issues.append(
            f"[{vt}] '{name}' appears {count}x — dedup bug! contexts: {contexts}"
        )
    return issues


register_check("node_name_uniqueness", _check_node_name_uniqueness)


# ── Check 9: Ambiguous base names ──────────────────────────────────────

def _check_ambiguous_base_names(variables, dependencies):
    """Report nodes sharing a base name across different types.

    Example: CTE 'customer_total_return' and its inner VT
    '⟐ customer_total_return' share the same base. Expected —
    the VT represents the CTE's SELECT output.
    """
    issues = []
    stripped = {}
    for v in variables:
        name = v["name"]
        base = name[2:] if name.startswith("⟐ ") else name
        stripped.setdefault(base, []).append(v)

    for base, vars_ in stripped.items():
        if len(vars_) <= 1:
            continue
        types = [(v["name"], v.get("variable_type", "?")) for v in vars_]
        unique_types = set(t for _, t in types)
        if len(unique_types) > 1:
            issues.append(
                f"'{base}': {len(vars_)} nodes of different types {types}"
            )
    return issues


register_check("ambiguous_base_names", _check_ambiguous_base_names)


# ── Check 10: alias connectivity ──────────────────────────────────────

def _check_alias_edges(variables, dependencies):
    """Every table alias (has source_tables) must have an ALIAS edge
    pointing to its original table or CTE."""
    issues = []
    # Build sets for fast lookup
    deps_by_src = {}
    for d in dependencies:
        deps_by_src.setdefault(d["source_id"], []).append(d)

    for v in variables:
        if v.get("variable_type") != "table":
            continue
        src_tables = v.get("source_tables", [])
        if not src_tables:
            continue  # original names (not aliases) — no ALIAS needed
        # Find ALIAS edges from this alias
        alias_edges = [d for d in deps_by_src.get(v["id"], [])
                      if d.get("relationship") == "ALIAS"]
        if not alias_edges:
            issues.append(
                f"[table] '{v['name']}' has source_tables={src_tables} "
                f"but no ALIAS edge")
    return issues


register_check("alias_edges", _check_alias_edges)

