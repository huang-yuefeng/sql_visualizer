"""
Multi-Script Analysis Service — processes multiple SQL files, extracts
input/output tables, and builds a flat meta-graph.

Script nodes are circles. Table nodes are rectangles. Edges connect
table nodes across scripts showing data lineage.
"""

from collections import defaultdict
from app.extractor.adapter import run_full_analysis
from app.services.graph_service import build_graph_data


def _classify_tables(variables: list[dict]) -> tuple[set[str], set[str]]:
    """Classify tables as input (read) or output (written).

    DML scripts: output = target tables (INSERT/UPDATE/DELETE/MERGE/CTAS)
    SELECT scripts: output = virtual table (⟐ output) — temporary result set
    """
    input_tables: set[str] = set()
    output_tables: set[str] = set()
    has_dml_output = False

    for v in variables:
        vt = v.get("variable_type", "")
        name = v.get("name", "")
        di = (v.get("defined_in") or "").upper()

        if vt == "merge_target":
            output_tables.add(name)
            has_dml_output = True
            continue

        if vt not in ("table",):
            continue

        if "FROM" in di or "JOIN" in di:
            input_tables.add(name)

        if any(kw in di for kw in ("INSERT", "UPDATE", "DELETE", "MERGE")):
            output_tables.add(name)
            has_dml_output = True

        if "CREATE" in di or "SELECT INTO" in di:
            output_tables.add(name)
            has_dml_output = True

    # SELECT-only scripts: the virtual table IS the output

    return input_tables, output_tables


def analyze_multiple_scripts(
    scripts: list[tuple[str, str]]  # [(script_name, sql_text), ...]
) -> dict:
    """Analyze multiple scripts, build flat meta-graph with table-to-table edges."""
    if len(scripts) < 2:
        return {"scripts": [], "meta_nodes": [], "meta_edges": []}

    # ── Analyze each script ──────────────────────────────────────────
    results = []
    for name, sql in scripts:
        result = run_full_analysis(sql, name)
        if "script_id" not in result:
            import hashlib
            result["script_id"] = hashlib.md5((name + sql).encode()).hexdigest()[:12]
        variables = result.get("variables", [])
        graph_data = build_graph_data(result)
        input_tables, output_tables = _classify_tables(variables)
        # SELECT-only scripts: add unique virtual output per script
        if not output_tables:
            output_tables.add(f"⟐ {name}")
        results.append({
            "script_id": result["script_id"],
            "script_name": name,
            "total_variables": result["total_variables"],
            "total_dependencies": result["total_dependencies"],
            "input_tables": sorted(input_tables),
            "output_tables": sorted(output_tables),
            "graph": graph_data,
            "_all_vars": [{"name": v["name"], "source_tables": v.get("source_tables", [])}
                          for v in variables],
        })

    # ── Build meta-graph: scripts only, direct edges ────────────────
    meta_nodes = []
    meta_edges = []
    seen_pairs: set[tuple[str, str]] = set()

    # Script circles only (no table nodes)
    for r in results:
        meta_nodes.append({"data": {
            "id": r["script_id"], "label": r["script_name"],
            "type": "script_circle",
            "total_variables": r["total_variables"],
            "total_dependencies": r["total_dependencies"],
            "input_tables": r["input_tables"],
            "output_tables": r["output_tables"],
            "input_count": len(r["input_tables"]),
            "output_count": len(r["output_tables"]),
        }})

    # Helper: filter out alias names, keep only original table names
    def _originals(tbl_list: list[str]) -> list[str]:
        """Remove alias names (those that appear as source_tables of another)."""
        alias_of = set()
        for r in results:
            for v in r.get("_all_vars", []):
                st = v.get("source_tables", [])
                if st:
                    for orig in st:
                        alias_of.add(v["name"])
        return [t for t in tbl_list if t not in alias_of]

    # Edges: script → script with table labels
    for i, r1 in enumerate(results):
        for j, r2 in enumerate(results):
            if i >= j:
                continue
            pair = tuple(sorted([r1["script_id"], r2["script_id"]]))

            # Data lineage: r1 output tables that r2 reads
            out_to_in = sorted(set(r1["output_tables"]) & set(r2["input_tables"]))
            if out_to_in:
                clean = _originals(out_to_in)
                meta_edges.append({"data": {
                    "id": f"{r1['script_id']}→{r2['script_id']}",
                    "source": r1["script_id"], "target": r2["script_id"],
                    "edge_type": "data_lineage",
                    "label": ", ".join(clean) if clean else ", ".join(out_to_in),
                    "source_tables": clean if clean else out_to_in,
                    "target_tables": [],
                }})
                seen_pairs.add(pair)

            # Reverse: r2 output tables that r1 reads
            out_to_in_rev = sorted(set(r2["output_tables"]) & set(r1["input_tables"]))
            if out_to_in_rev:
                clean = _originals(out_to_in_rev)
                meta_edges.append({"data": {
                    "id": f"{r2['script_id']}→{r1['script_id']}",
                    "source": r2["script_id"], "target": r1["script_id"],
                    "edge_type": "data_lineage",
                    "label": ", ".join(clean) if clean else ", ".join(out_to_in_rev),
                    "source_tables": clean if clean else out_to_in_rev,
                    "target_tables": [],
                }})
                seen_pairs.add(pair)

            # Shared inputs
            shared = sorted(set(r1["input_tables"]) & set(r2["input_tables"]))
            if shared and pair not in seen_pairs:
                clean = _originals(shared)
                meta_edges.append({"data": {
                    "id": f"{r1['script_id']}↔{r2['script_id']}",
                    "source": r1["script_id"], "target": r2["script_id"],
                    "edge_type": "shared_input",
                    "label": ", ".join(clean) if clean else ", ".join(shared),
                    "source_tables": [],
                    "target_tables": [],
                }})
                seen_pairs.add(pair)

    return {"scripts": results, "meta_nodes": meta_nodes, "meta_edges": meta_edges}
