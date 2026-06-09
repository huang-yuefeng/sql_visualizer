"""
Multi-Script Analysis Service — processes multiple SQL files, finds shared
variables, and builds a meta-graph where each script is a subgraph node.
"""

from collections import defaultdict
from app.extractor.adapter import run_full_analysis


def analyze_multiple_scripts(
    scripts: list[tuple[str, str]]  # [(script_name, sql_text), ...]
) -> dict:
    """Analyze multiple SQL scripts and build a meta-graph.

    Returns:
      - scripts: list of per-script analysis results
      - shared_vars: variables appearing in 2+ scripts
      - meta_nodes: one node per script (subgraph)
      - meta_edges: edges between scripts sharing variables
    """
    if len(scripts) < 2:
        return {"scripts": [], "shared_vars": {}, "meta_nodes": [], "meta_edges": []}

    # Analyze each script independently
    results = []
    for name, sql in scripts:
        result = run_full_analysis(sql, name)
        # Generate script_id if not present (run_full_analysis doesn't set it)
        if "script_id" not in result:
            import hashlib
            result["script_id"] = hashlib.md5((name+sql).encode()).hexdigest()[:12]
        # Build variable name set for this script
        var_names = set()
        for v in result.get("variables", []):
            if v.get("variable_type") in ("table_column", "table", "database_table"):
                var_names.add(v["name"])
        results.append({
            "script_id": result["script_id"],
            "script_name": name,
            "total_variables": result["total_variables"],
            "total_dependencies": result["total_dependencies"],
            "var_names": sorted(var_names),
            "tables": [v["name"] for v in result.get("variables", [])
                       if v.get("variable_type") == "database_table"],
        })

    # Find shared variables (appear in 2+ scripts)
    var_to_scripts = defaultdict(set)
    for r in results:
        for vname in r["var_names"]:
            var_to_scripts[vname].add(r["script_id"])

    shared_vars = {
        vname: sorted(sids)
        for vname, sids in var_to_scripts.items()
        if len(sids) >= 2
    }

    # Build meta-graph: one node per script
    meta_nodes = []
    for r in results:
        shared_count = sum(1 for vname in r["var_names"] if vname in shared_vars)
        meta_nodes.append({
            "data": {
                "id": r["script_id"],
                "label": r["script_name"],
                "type": "script",
                "total_variables": r["total_variables"],
                "total_dependencies": r["total_dependencies"],
                "shared_var_count": shared_count,
            }
        })

    # Build meta-edges: connect scripts that share variables
    meta_edges = []
    seen_pairs = set()
    for vname, sids in shared_vars.items():
        for i in range(len(sids)):
            for j in range(i + 1, len(sids)):
                pair = tuple(sorted([sids[i], sids[j]]))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    meta_edges.append({
                        "data": {
                            "id": f"{sids[i]}<->{sids[j]}",
                            "source": sids[i],
                            "target": sids[j],
                            "label": vname,
                            "shared_var": vname,
                        }
                    })

    return {
        "scripts": results,
        "shared_vars": {k: sorted(v) for k, v in shared_vars.items()},
        "meta_nodes": meta_nodes,
        "meta_edges": meta_edges,
    }
