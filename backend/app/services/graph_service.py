"""
Graph Service — builds Cytoscape.js-compatible graph data from analysis results.
"""

from app.models.variable import VariableType

# Node color/shape styling by variable type
NODE_STYLES = {
    VariableType.TABLE.value: {
        "shape": "rectangle", "color": "#4A90D9", "size": 50,
    },
    VariableType.VIEW.value: {
        "shape": "rectangle", "color": "#5DADE2", "size": 50,
    },
    VariableType.COLUMN.value: {
        "shape": "ellipse", "color": "#A8D4FF", "size": 30,
    },
    VariableType.CTE.value: {
        "shape": "round-rectangle", "color": "#5CB85C", "size": 45,
    },
    VariableType.CTE_COLUMN.value: {
        "shape": "triangle", "color": "#8FD98F", "size": 30,
    },
    VariableType.EXPRESSION.value: {
        "shape": "diamond", "color": "#F0AD4E", "size": 35,
    },
    VariableType.WINDOW.value: {
        "shape": "hexagon", "color": "#967ADC", "size": 35,
    },
    VariableType.AGGREGATE.value: {
        "shape": "triangle", "color": "#37BC9B", "size": 35,
    },
    VariableType.CASE.value: {
        "shape": "pentagon", "color": "#D770AD", "size": 35,
    },
    VariableType.TRANSFORM.value: {
        "shape": "parallelogram", "color": "#FFCE54", "size": 35,
    },
    VariableType.LITERAL.value: {
        "shape": "ellipse", "color": "#CCCCCC", "size": 25,
    },
    VariableType.MERGE_TARGET.value: {
        "shape": "rectangle", "color": "#DA4453", "size": 50,
    },
    VariableType.UNION_BRANCH.value: {
        "shape": "vee", "color": "#E6E9ED", "size": 40,
    },
    VariableType.SUBQUERY.value: {
        "shape": "diamond", "color": "#AC92EC", "size": 35,
    },
    VariableType.VIRTUAL_TABLE.value: {
        "shape": "round-rectangle", "color": "#2ECC71", "size": 55,
    },
}

# Default style for unknown types
DEFAULT_NODE_STYLE = {"shape": "ellipse", "color": "#999999", "size": 30}


# ── Edge Type Styling ──────────────────────────────────────────────────

EDGE_TYPE_STYLE = {
    "TABLE_FLOW": {"color": "#2ECC71", "line": "solid",   "width": 3, "desc": "Table feeds output"},
    "ALIAS":      {"color": "#1ABC9C", "line": "dashed",  "width": 1, "desc": "Original → alias"},
    "REF":        {"color": "#27AE60", "line": "solid",   "width": 1, "desc": "Column reference"},
    "AGGREGATE":  {"color": "#8E44AD", "line": "solid",   "width": 3, "desc": "SUM/COUNT/AVG"},
    "TRANSFORM":  {"color": "#D35400", "line": "dashed",  "width": 2, "desc": "COALESCE/CAST/CONCAT"},
    "WINDOW":     {"color": "#9B59B6", "line": "dashed",  "width": 2, "desc": "ROW_NUMBER/RANK/LAG"},
    "COMPUTED":   {"color": "#E67E22", "line": "dotted",  "width": 2, "desc": "CASE WHEN result"},
    "SCHEMA":     {"color": "#3498DB", "line": "dotted",  "width": 1, "desc": "Table→Column ownership"},
    "INDIRECT":   {"color": "#C0392B", "line": "dot-dash","width": 1, "desc": "HAVING→SELECT match"},
    "FILTER":     {"color": "#E74C3C", "line": "solid",   "width": 2, "desc": "WHERE/JOIN ON condition"},
    "JOIN":       {"color": "#E91E63", "line": "dashed",  "width": 2, "desc": "JOIN key condition"},
    "CORRELATED": {"color": "#FF5722", "line": "dotted",  "width": 2, "desc": "Correlated subquery"},
    "DML":        {"color": "#2980B9", "line": "double",  "width": 3, "desc": "INSERT/UPDATE/DELETE/MERGE"},
    "SET_OP":     {"color": "#F1C40F", "line": "dashed",  "width": 2, "desc": "UNION/INTERSECT/EXCEPT"},
    "SUBQUERY":   {"color": "#16A085", "line": "dotted",  "width": 2, "desc": "Subquery reference"},
    "SUBSET":     {"color": "#7F8C8D", "line": "dotted",  "width": 1, "desc": "Disconnected bridge"},
}

EDGE_TYPE_ORDER = [
    "TABLE_FLOW", "ALIAS", "REF", "AGGREGATE", "TRANSFORM", "WINDOW",
    "COMPUTED", "SCHEMA", "INDIRECT", "FILTER", "JOIN", "CORRELATED",
    "DML", "SET_OP", "SUBQUERY", "SUBSET",
]

CATEGORY_MAP = {
    "REF": "copy", "TRANSFORM": "compute", "COMPUTED": "compute",
    "AGGREGATE": "aggregate", "WINDOW": "aggregate",
    "FILTER": "filter", "JOIN": "filter", "INDIRECT": "filter", "CORRELATED": "filter",
    "SET_OP": "combine", "SUBQUERY": "combine",
    "DML": "write",
    "SCHEMA": "structure", "ALIAS": "structure", "SUBSET": "structure", "TABLE_FLOW": "structure",
}

def get_edge_style(edge_type: str) -> dict:
    """Get per-type display style for an edge."""
    return EDGE_TYPE_STYLE.get(edge_type, EDGE_TYPE_STYLE["SUBSET"])

def get_category(edge_type: str) -> str:
    """Map edge type to one of 7 visual categories."""
    return CATEGORY_MAP.get(edge_type, "structure")

def get_category_color(edge_type: str) -> str:
    """Get category color for an edge type."""
    return EDGE_TYPE_STYLE.get(edge_type, {}).get("color", "#7F8C8D")

def build_graph_data(analysis: dict) -> dict:
    """Convert analysis result to Cytoscape.js-compatible nodes and edges.

    Args:
        analysis: The full analysis dict from analysis_service.

    Returns:
        Dict with script_id, script_name, nodes, edges, total_variables, total_dependencies.
    """
    variables = analysis.get("variables", [])
    dependencies = analysis.get("dependencies", [])

    # P2+P5: Build alias_map from source_tables (alias → canonical)
    alias_map = {}
    for v in variables:
        src_tbls = v.get("source_tables", [])
        if src_tbls and v.get("variable_type") in ("table", "view", "cte"):
            alias_map[v["name"]] = src_tbls[0]

    nodes = []
    for v in variables:
        vt = v.get("variable_type", "")
        name = v.get("name", "")
        src_tbls = v.get("source_tables", [])
        style = NODE_STYLES.get(vt, DEFAULT_NODE_STYLE)

        # P2: Resolve table_name and field_name for columns
        table_name = ""
        field_name = ""
        display_name = name  # default
        if vt in ("column", "aggregate", "transform", "window", "window_computed"):
            if "." in name:
                prefix, fname = name.split(".", 1)
                # Resolve alias prefix to canonical name
                table_name = alias_map.get(prefix, prefix)
                field_name = fname
                display_name = name  # keep original label
            else:
                field_name = name
                # R20/E1: unqualified columns resolved by the extractor
                # (S1-S3/S2) carry source_tables — attach in the graph too,
                # so data-flow fields connect to their table/container node.
                # Skip S5/S6 sentinels (⟐system/⟐pseudo — not graph nodes).
                _st = v.get("source_tables", [])
                if _st and _st[0] and _st[0] not in ("⟐system", "⟐pseudo"):
                    table_name = _st[0]
                else:
                    table_name = ""
        elif vt in ("table", "view", "cte", "virtual_table", "subquery", "merge_target"):
            table_name = name

        nodes.append({
            "data": {
                "id": v["id"],
                "label": display_name,
                "variable_type": vt,
                "shape": style["shape"],
                "color": style["color"],
                "size": style["size"],
                "sql_expression": v.get("sql_expression", ""),
                "defined_in": v.get("defined_in", ""),
                "is_output": v.get("is_output", False),
                "source_tables": src_tbls,
                # H3: carry source_columns across the graph boundary (lineage seed
                # matching + L2 target detection depend on it)
                "source_columns": v.get("source_columns", []),
                # P2: Pre-resolved canonical names
                "table_name": table_name,
                "field_name": field_name,
                "node_type": vt,  # alias for variable_type (used by lineage.py)
            }
        })

    EDGE_COLORS = {
        "TABLE_FLOW":       "#2ECC71",   # green       — table-to-table data flow
        "SCHEMA":           "#8AB4F8",   # light blue  — column belongs to table
        "ALIAS":            "#1ABC9C",   # teal-green  — alias → original name
        "SELECT":           "#2ECC71",   # green       — table feeds into SELECT output
        "JOIN":             "#E91E63",   # pink-red    — JOIN operation data flow
        "REF":              "#9AA0A6",   # grey        — direct column reference
        "AGGREGATE":        "#37BC9B",   # teal        — SUM/COUNT/AVG
        "TRANSFORM":        "#F0AD4E",   # orange      — COALESCE/CAST function
        "WINDOW":           "#967ADC",   # purple      — ROW_NUMBER/RANK/LAG
        "COMPUTED":         "#D770AD",   # pink        — CASE WHEN result
        "INDIRECT":         "#5DADE2",   # steel blue  — HAVING→SELECT name ref
        "FILTER":           "#3498DB",   # blue        — WHERE/HAVING condition
        "DML":              "#E74C3C",   # red         — INSERT/UPDATE/DELETE/MERGE
        "SUBSET":           "#E67E22",   # dark orange — subquery/CTE boundary
        "SET_OP":           "#9B59B6",   # amethyst   — UNION/INTERSECT/EXCEPT
    }
    edges = []
    for d in dependencies:
        rel = d.get("relationship", "")
        edges.append({
            "data": {
                "id": f"{d['source_id']}->{d['target_id']}",
                "source": d["source_id"],
                "target": d["target_id"],
                "label": rel,
                "relationship": rel,
                "operation": d.get("operation", ""),
                "color": EDGE_COLORS.get(rel, "#555555"),
            }
        })

    # Build compound nodes: group columns under their parent table
    # Table nodes become parents, column nodes become children (nested inside)
    table_ids = {v["id"] for v in variables
                 if v.get("variable_type") in ("table","view","cte","merge_target",
                                                "virtual_table","subquery")}
    for v in variables:
        vt = v.get("variable_type", "")
        if vt == "column" and "." in v.get("name", ""):
            prefix = v["name"].split(".", 1)[0]
            # Find the table node with this prefix
            for tv in variables:
                if tv.get("variable_type") in ("table","view","cte") and tv["name"] == prefix:
                    v["parent"] = tv["id"]
                    break

    # P4: Build table_fields — per-table set of field names from SCHEMA edges
    # P5: Extend alias_map to sync alias canonical fields
    table_fields = {}
    for d in dependencies:
        rel = d.get("relationship", "")
        if rel == "SCHEMA":
            src_id = d["source_id"]
            tgt_id = d["target_id"]
            # Find the table node
            table_node = None
            col_node = None
            for nd in nodes:
                nid = nd["data"]["id"]
                if nid == src_id:
                    table_node = nd
                if nid == tgt_id:
                    col_node = nd
            if table_node and col_node:
                tbl_name = table_node["data"].get("table_name",
                                                   table_node["data"].get("label", ""))
                col_fname = col_node["data"].get("field_name",
                                                  col_node["data"].get("label", "").rsplit(".",1)[-1] if "." in col_node["data"].get("label","") else col_node["data"].get("label",""))
                if tbl_name and col_fname:
                    table_fields.setdefault(tbl_name, set()).add(col_fname)

    # P4-ext: Record fields for DML target tables from DML source columns.
    # E.g., INSERT INTO stg_customers(customer_id) SELECT c.customer_id
    #   → c.customer_id --DML--> stg_customers.customer_id
    #   → stg_customers.fields ∋ customer_id
    node_by_id = {nd["data"]["id"]: nd["data"] for nd in nodes}
    for d in dependencies:
        rel = d.get("relationship", "")
        if rel == "DML":
            src_id = d["source_id"]
            tgt_id = d["target_id"]
            src_node = node_by_id.get(src_id)
            tgt_node = node_by_id.get(tgt_id)
            if src_node and tgt_node:
                src_field = src_node.get("field_name", "")
                tgt_table = tgt_node.get("table_name", "")
                if not tgt_table:
                    # Try from label if table_name not set
                    tgt_label = tgt_node.get("label", "")
                    if "." in tgt_label:
                        tgt_table = tgt_label.split(".", 1)[0]
                if not src_field and "." in src_node.get("label", ""):
                    src_field = src_node["label"].rsplit(".", 1)[-1]
                if tgt_table and src_field:
                    table_fields.setdefault(tgt_table, set()).add(src_field)

    # P5: Sync alias → canonical fields (both ways via ALIAS edges)
    for d in dependencies:
        rel = d.get("relationship", "")
        if rel == "ALIAS":
            src_id = d["source_id"]
            tgt_id = d["target_id"]
            src_tbl = None
            tgt_tbl = None
            for nd in nodes:
                nid = nd["data"]["id"]
                if nid == src_id:
                    src_tbl = nd["data"]
                if nid == tgt_id:
                    tgt_tbl = nd["data"]
            if src_tbl and tgt_tbl:
                src_name = src_tbl.get("table_name", src_tbl.get("label", ""))
                tgt_name = tgt_tbl.get("table_name", tgt_tbl.get("label", ""))
                # Sync fields: canonical → alias
                if src_name in table_fields:
                    table_fields.setdefault(tgt_name, set()).update(table_fields[src_name])
                # Sync fields: alias → canonical
                if tgt_name in table_fields:
                    table_fields.setdefault(src_name, set()).update(table_fields[tgt_name])

    return {
        "script_id": analysis.get("script_id", ""),
        "script_name": analysis.get("script_name", ""),
        "total_variables": analysis.get("total_variables", 0),
        "total_dependencies": analysis.get("total_dependencies", 0),
        "table_count": analysis.get("table_count", 0),
        "cte_count": analysis.get("cte_count", 0),
        "line_map": analysis.get("line_map", {}),
        "sql_text": analysis.get("sql_text", ""),
        "template_replacements": analysis.get("template_replacements", []),
        "nodes": nodes,
        "edges": edges,
        # P4: Per-table field sets (pre-resolved)
        "table_fields": {k: sorted(v) for k, v in table_fields.items()},
        # P5: Alias → canonical name map (pre-built)
        "alias_map": alias_map,
    }
