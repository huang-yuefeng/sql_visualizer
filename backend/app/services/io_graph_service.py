"""
Input-Output Graph Service — finds paths from input to output columns.

Input columns: table_column vars with NO source_columns (read-only from tables)
Output columns: user-defined via CSV (table_name, data_type, column_name, explanation)

Uses BFS to find all paths connecting input columns to output columns through
the dependency graph.
"""
import csv
import io
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OutputColumn:
    table_name: str
    data_type: str
    column_name: str
    explanation: str


@dataclass
class PathNode:
    variable_id: str
    variable_name: str
    variable_type: str
    table_name: str  # the table this column belongs to (if any)


@dataclass
class PathInfo:
    """A path from an input column to an output column."""
    input_col: PathNode
    output_col: PathNode
    nodes: list[PathNode]  # ordered from input to output
    edges: list[dict]       # edge details along the path
    length: int


def parse_output_csv(csv_text: str) -> list[OutputColumn]:
    """Parse a CSV with columns: table_name, data_type, column_name, explanation."""
    results = []
    reader = csv.reader(io.StringIO(csv_text))
    for row in reader:
        if len(row) < 3:
            continue
        results.append(OutputColumn(
            table_name=row[0].strip(),
            data_type=row[1].strip(),
            column_name=row[2].strip(),
            explanation=row[3].strip() if len(row) > 3 else "",
        ))
    return results


def _build_adjacency(variables: list[dict], dependencies: list[dict]) -> dict[str, list[dict]]:
    """Build adjacency list from the dependency graph (forward direction)."""
    adj = defaultdict(list)
    for d in dependencies:
        adj[d["source_id"]].append(d)
    return adj


def _build_reverse_adjacency(variables: list[dict], dependencies: list[dict]) -> dict[str, list[dict]]:
    """Build reverse adjacency (for walking backward from outputs)."""
    radj = defaultdict(list)
    for d in dependencies:
        radj[d["target_id"]].append(d)
    return radj


def find_input_columns(variables: list[dict]) -> list[dict]:
    """Input columns = table_column vars with NO source_columns (pure reads)."""
    inputs = []
    for v in variables:
        if v.get("variable_type") == "column" and not v.get("source_columns"):
            inputs.append(v)
    return inputs


def _format_node(var: dict) -> PathNode:
    """Format a variable as a PathNode with table name extracted from the name."""
    name = var.get("name", "")
    table = ""
    if "." in name:
        table = name.split(".", 1)[0]
    return PathNode(
        variable_id=var["id"],
        variable_name=name,
        variable_type=var.get("variable_type", ""),
        table_name=table,
    )


def find_paths(
    analysis: dict,
    output_columns: list[OutputColumn],
) -> list[PathInfo]:
    """Find all paths from input columns to output columns.

    Uses BFS from each input column forward. When we reach an output column
    (matched by name), we record the path. Limits to first 50 paths for performance.
    """
    variables = analysis.get("variables", [])
    dependencies = analysis.get("dependencies", [])

    # Build indexes
    var_index = {v["id"]: v for v in variables}
    adj = _build_adjacency(variables, dependencies)

    # Find input columns (pure reads, no source_columns)
    input_cols = find_input_columns(variables)

    # Match output columns by name
    output_names = {(oc.table_name, oc.column_name): oc for oc in output_columns}
    output_vars = []
    for v in variables:
        name = v.get("name", "")
        # Try: table.column or bare column
        if "." in name:
            parts = name.split(".", 1)
            key = (parts[0], parts[1])
        else:
            key = ("", name)
        for (ot, oc_name), oc in output_names.items():
            if name == oc_name or (ot and name == f"{ot}.{oc_name}"):
                output_vars.append((v, oc))
                break

    paths: list[PathInfo] = []
    seen_paths: set[tuple[str, str]] = set()

    for inp in input_cols:
        inp_node = _format_node(inp)
        # BFS from input forward
        queue = deque()
        queue.append((inp["id"], [inp["id"]], []))  # (current_id, node_path, edge_path)
        visited = {inp["id"]}

        while queue and len(paths) < 200:
            cur_id, node_path, edge_path = queue.popleft()
            cur_var = var_index.get(cur_id, {})

            # Check if we reached an output
            for ov, oc in output_vars:
                if cur_id == ov["id"]:
                    key = (inp["id"], ov["id"])
                    if key not in seen_paths:
                        seen_paths.add(key)
                        nodes = [_format_node(var_index.get(nid, {"id": nid, "name": "?"})) for nid in node_path]
                        paths.append(PathInfo(
                            input_col=inp_node,
                            output_col=_format_node(ov),
                            nodes=nodes,
                            edges=[dict(e) for e in edge_path],
                            length=len(nodes) - 1,
                        ))
                    continue  # found output, don't explore further

            # Explore forward
            for dep in adj.get(cur_id, []):
                nxt = dep["target_id"]
                if nxt not in visited:
                    visited.add(nxt)
                    new_edges = list(edge_path) + [dep]
                    queue.append((nxt, node_path + [nxt], new_edges))

    return paths


def build_io_graph_data(
    analysis: dict,
    paths: list[PathInfo],
) -> dict:
    """Build a simplified Cytoscape graph with only input/output columns and path nodes."""
    variables = analysis.get("variables", [])
    var_index = {v["id"]: v for v in variables}

    # Collect all node IDs that appear in any path
    node_ids = set()
    edge_set = set()

    for p in paths:
        for node in p.nodes:
            node_ids.add(node.variable_id)
        for e in p.edges:
            ek = (e.get("source_id", ""), e.get("target_id", ""), e.get("relationship", ""))
            edge_set.add(ek)

    # Build nodes
    io_nodes = []
    for nid in node_ids:
        v = var_index.get(nid, {})
        io_nodes.append({
            "data": {
                "id": v.get("id", nid),
                "label": v.get("name", nid),
                "variable_type": v.get("variable_type", ""),
                "sql_expression": v.get("sql_expression", ""),
                "defined_in": v.get("defined_in", ""),
                "source_tables": v.get("source_tables", []),
            }
        })

    # Build edges
    io_edges = []
    for src, tgt, rel in edge_set:
        io_edges.append({
            "data": {
                "id": f"{src}->{tgt}",
                "source": src,
                "target": tgt,
                "label": rel,
                "relationship": rel,
            }
        })

    return {
        "script_id": analysis.get("script_id", ""),
        "script_name": analysis.get("script_name", ""),
        "input_count": len(set(p.input_col.variable_id for p in paths)),
        "output_count": len(set(p.output_col.variable_id for p in paths)),
        "path_count": len(paths),
        "nodes": io_nodes,
        "edges": io_edges,
        "paths": [
            {
                "input": {"id": p.input_col.variable_id, "name": p.input_col.variable_name},
                "output": {"id": p.output_col.variable_id, "name": p.output_col.variable_name},
                "length": p.length,
                "nodes": [{"id": n.variable_id, "name": n.variable_name, "type": n.variable_type,
                           "table": n.table_name} for n in p.nodes],
                "edges": p.edges,
            }
            for p in paths
        ],
    }
