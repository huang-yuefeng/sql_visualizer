"""
Graph Service — builds Cytoscape.js-compatible graph data from analysis results.
"""

from app.models.variable import VariableType

# Node color/shape styling by variable type
NODE_STYLES = {
    VariableType.DATABASE_TABLE.value: {
        "shape": "rectangle", "color": "#4A90D9", "size": 50,
    },
    VariableType.TABLE_COLUMN.value: {
        "shape": "ellipse", "color": "#A8D4FF", "size": 30,
    },
    VariableType.CTE_TABLE.value: {
        "shape": "round-rectangle", "color": "#5CB85C", "size": 45,
    },
    VariableType.CTE_COLUMN.value: {
        "shape": "triangle", "color": "#8FD98F", "size": 30,
    },
    VariableType.INTERMEDIATE.value: {
        "shape": "diamond", "color": "#F0AD4E", "size": 35,
    },
    VariableType.WINDOW_RESULT.value: {
        "shape": "hexagon", "color": "#967ADC", "size": 35,
    },
    VariableType.AGGREGATE.value: {
        "shape": "triangle", "color": "#37BC9B", "size": 35,
    },
    VariableType.CASE_RESULT.value: {
        "shape": "pentagon", "color": "#D770AD", "size": 35,
    },
    VariableType.FUNCTION_RESULT.value: {
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
    VariableType.SUBQUERY_RESULT.value: {
        "shape": "diamond", "color": "#AC92EC", "size": 35,
    },
    VariableType.VIRTUAL_TABLE.value: {
        "shape": "round-rectangle", "color": "#2ECC71", "size": 55,
    },
}

# Default style for unknown types
DEFAULT_NODE_STYLE = {"shape": "ellipse", "color": "#999999", "size": 30}


def build_graph_data(analysis: dict) -> dict:
    """Convert analysis result to Cytoscape.js-compatible nodes and edges.

    Args:
        analysis: The full analysis dict from analysis_service.

    Returns:
        Dict with script_id, script_name, nodes, edges, total_variables, total_dependencies.
    """
    variables = analysis.get("variables", [])
    dependencies = analysis.get("dependencies", [])

    nodes = []
    for v in variables:
        style = NODE_STYLES.get(v.get("variable_type", ""), DEFAULT_NODE_STYLE)
        nodes.append({
            "data": {
                "id": v["id"],
                "label": v["name"],
                "variable_type": v["variable_type"],
                "shape": style["shape"],
                "color": style["color"],
                "size": style["size"],
                "sql_expression": v.get("sql_expression", ""),
                "defined_in": v.get("defined_in", ""),
                "is_output": v.get("is_output", False),
                "source_tables": v.get("source_tables", []),
            }
        })

    EDGE_COLORS = {
        "BELONGS_TO":       "#8AB4F8",   # light blue
        "ALIAS_OF":         "#1ABC9C",   # teal-green
        "DIRECT_REFERENCE": "#9AA0A6",   # grey
        "AGGREGATION":      "#37BC9B",   # teal
        "TRANSFORMATION":   "#F0AD4E",   # orange
        "WINDOW":           "#967ADC",   # purple
        "COMPUTED_FROM":    "#D770AD",   # pink
        "REFERENCES":       "#5DADE2",   # steel blue
        "OPERATES_ON":      "#E74C3C",   # red
        "FEEDS_INTO":       "#2ECC71",   # green
        "COMPONENT_LINK":   "#E67E22",   # dark orange
        "COMPONENT_LINK":   "#E67E22",   # dark orange
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
                 if v.get("variable_type") in ("database_table","cte_table","merge_target",
                                                "virtual_table","subquery_result")}
    for v in variables:
        vt = v.get("variable_type", "")
        if vt == "table_column" and "." in v.get("name", ""):
            prefix = v["name"].split(".", 1)[0]
            # Find the table node with this prefix
            for tv in variables:
                if tv.get("variable_type") in ("database_table","cte_table") and tv["name"] == prefix:
                    v["parent"] = tv["id"]
                    break

    return {
        "script_id": analysis.get("script_id", ""),
        "script_name": analysis.get("script_name", ""),
        "total_variables": analysis.get("total_variables", 0),
        "total_dependencies": analysis.get("total_dependencies", 0),
        "table_count": analysis.get("table_count", 0),
        "cte_count": analysis.get("cte_count", 0),
        "line_map": analysis.get("line_map", {}),
        "sql_text": analysis.get("sql_text", ""),
        "nodes": nodes,
        "edges": edges,
    }
