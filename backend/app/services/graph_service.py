"""
Graph Service — builds Cytoscape.js-compatible graph data from analysis results.
"""
import json
from pathlib import Path

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
    VariableType.FUNCTION_TABLE.value: {
        "shape": "rectangle", "color": "#4A90D9", "size": 50,
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
    # ROW_FLOW (2026-08-13, #226): the row-level flow bridge — flow-class
    # edge (arrow + highlightable); per the uniform-style requirement it
    # shares the single line style — its TYPE NAME tells the user it is
    # row-level flow, not a color.
    "ROW_FLOW":   {"color": "#2ECC71", "line": "solid",  "width": 2, "desc": "Row-level flow"},
}

EDGE_TYPE_ORDER = [
    "TABLE_FLOW", "ALIAS", "REF", "AGGREGATE", "TRANSFORM", "WINDOW",
    "COMPUTED", "SCHEMA", "INDIRECT", "FILTER", "JOIN", "CORRELATED",
    "DML", "SET_OP", "SUBQUERY", "SUBSET", "ROW_FLOW",
]

CATEGORY_MAP = {
    "REF": "copy", "TRANSFORM": "compute", "COMPUTED": "compute",
    "AGGREGATE": "aggregate", "WINDOW": "aggregate",
    "FILTER": "filter", "JOIN": "filter", "INDIRECT": "filter", "CORRELATED": "filter",
    "SET_OP": "combine", "SUBQUERY": "combine",
    "DML": "write",
    # J12-23: TABLE_FLOW is the primary value-flow edge ("table feeds
    # output", green width 3) — NOT a containment/rename/bridge edge. It
    # moved out of "structure" into a value-flow category so it no longer
    # renders in the structure color; SCHEMA/ALIAS/SUBSET stay "structure".
    "SCHEMA": "structure", "ALIAS": "structure", "SUBSET": "structure",
    "TABLE_FLOW": "flow",
    # ROW_FLOW (2026-08-13, #226): row-selection flow — a flow-class edge
    # (highlightable, part of the flow path) even though the strict
    # walker never FOLLOWS it (it is emitted by the walker as an output).
    "ROW_FLOW": "flow",
}

def get_edge_style(edge_type: str) -> dict:
    """Get per-type display style for an edge."""
    return EDGE_TYPE_STYLE.get(edge_type, EDGE_TYPE_STYLE["SUBSET"])

def _stmt_idx_of(context: str):
    """C-9: statement index of a variable context.

    Top-level statement contexts are "TOP0", "TOP1", … (branch and subquery
    descendants keep the prefix: "TOP0/union1", "TOP0:join:p2"). CTE-body
    scopes ("CTE{loan_final}") and legacy "TOP" carry no index → None.
    """
    if not context or not context.startswith("TOP"):
        return None
    digits = ""
    for ch in context[3:]:
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits) if digits else None


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

    # J12-10 (stage 4): the physical model is the single extraction-time
    # truth — alias_map / table_fields / parent assignment are projections
    # of it (one physical entity per table; alias views carry the alias
    # labels; fields are per-entity occurrence sets). No reconstruction.
    from app.extractor.physical_model import build_physical_model
    model = build_physical_model(analysis, script_name=analysis.get("script_name", ""))

    # P2+P5: alias_map from the model's alias views (alias label →
    # canonical entity name, last-writer-wins per label — insertion order
    # is the var order). Replaces the source_tables scan.
    alias_map = {}
    for tbl in model.tables.values():
        for av in tbl.alias_views:
            canon = model.tables.get(av["canonical_key"])
            if canon is not None:
                alias_map[av["label"]] = canon.name

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
        elif vt in ("table", "view", "cte", "virtual_table", "subquery", "merge_target",
                    "function_table"):
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
                # B3/C-9: carry the extraction context and the statement
                # index across the graph boundary — the L2 builder uses
                # context for the scope-based parent fallback (B3) and
                # stmt_idx for per-statement field dedup (C-9).
                "context": v.get("context", ""),
                "stmt_idx": _stmt_idx_of(v.get("context", "")),
                # v3.3.140: carry the var's line span across the graph
                # boundary (adapter._var_to_dict already emits
                # line_start/line_end) — the strict table.field walker uses
                # node-carried lines for its highlight ranges.
                "line_start": v.get("line_start", 0),
                "line_end": v.get("line_end", 0),
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
                # I5 (v3.3.145): containment rides the edge data — the
                # strict walker (lineage._is_containment) keys on the tag,
                # not the edge type, so it must survive the graph build.
                "containment": d.get("containment", False),
            }
        })

    # Build compound nodes: group columns under their parent table
    # Table nodes become parents, column nodes become children (nested inside)
    # J12-10 (stage 4): the parent assignment is a model lookup — the
    # first table-like occurrence of the column's owning entity (the
    # occurrence index carries the owner-name resolution, alias_map[prefix]
    # or prefix).
    owner_first_occ = {}
    for v in variables:
        vt = v.get("variable_type", "")
        if vt in ("table", "view", "cte", "function_table"):
            owner_first_occ.setdefault(v.get("name", ""), v["id"])
    for v in variables:
        vt = v.get("variable_type", "")
        if vt == "column" and "." in v.get("name", ""):
            occ = model.occurrence(v.get("id", "")) or {}
            owner = occ.get("table_name") or v["name"].split(".", 1)[0]
            pid = owner_first_occ.get(owner)
            if pid is None:
                pid = owner_first_occ.get(v["name"].split(".", 1)[0])
            if pid is not None:
                v["parent"] = pid

    # P4: Build table_fields — per-table set of field names from the
    # model's entity fields (one physical entity per table; SCHEMA-edge
    # columns are parented field occurrences, DML INSERT columns carry
    # source_tables=[target] so they land on model fields — both P4 paths
    # are covered by construction).
    # P5: alias-label keys carry the canonical entity's fields.
    table_fields = {}
    for tbl in model.tables.values():
        if tbl.fields:
            table_fields[tbl.name] = set(tbl.fields)
    for tbl in model.tables.values():
        for av in tbl.alias_views:
            canon = model.tables.get(av["canonical_key"])
            if canon is not None and canon.fields:
                table_fields.setdefault(av["label"], set()).update(canon.fields)
    table_fields = {k: sorted(v) for k, v in table_fields.items()}

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
        # P4: Per-table field sets (pre-resolved, model-projected)
        "table_fields": table_fields,
        # P5: Alias → canonical name map (pre-built, model-projected)
        "alias_map": alias_map,
    }


# ── FSC-2 (v3.3.195): the graph cache's alias-truth companion ──────────
#
# THE SNAPSHOT-INTEGRITY HOLE THIS CLOSES: the served L2 closure must be a
# pure function of the SQL text, but until this artifact existed it also
# depended on WHICH cache survived the restart/purge cycle. The graph cache
# serializes nodes WITHOUT `alias_of` (the I4 extraction fact that names
# the exact source var an alias pairs with), so a graph-cache hit that
# finds no current analysis cache rebuilds the physical model through
# physical_model's label-keyed alias FALLBACK — and that fallback
# mis-assigns aliases whenever a label is reused across scopes (measured
# on samples/sql_sample_v1/BDM_ACC_LOAN_INFO_RFN.sql: 28 of 74
# `alias_by_var_id` pairs differ between the two input forms, e.g. var
# 15b561ec4099c7c3 → `bdm_acc_loan_info` (the analysis truth) vs
# `ODS_IFAI_FCLETWK` (the label-rule guess); SUP_M 4 of 14). Same SQL,
# two different answers, decided by an artifact's survival.
#
# The fix is persistence, not a smarter fallback: the build that WRITES a
# graph cache also writes this sibling file carrying the analysis path's
# alias truth, so every later graph-cache-hit model build re-derives the
# SAME model the analysis path produced (byte-identical models, proven by
# tests/test_model_persistence.py). Nothing else about the model is
# persisted — the graph cache itself already carries every other input the
# model consumes (occurrence index, source_tables, edges).
#
# Naming: the prefix lives HERE (not cache_keys.py) because both of this
# artifact's consumers — `_load_or_build_graph` and
# `dataflow_service.get_level2_graph` — already take their graph-cache
# contract from the graph-serialization module; GRAPH_CACHE_PREFIX stays
# the single source of truth for the graph cache itself.
MODEL_CACHE_PREFIX = "model"             # + "_" + <cache_key> + ".json"

# The artifact's own contract version, independent of the graph cache's
# `format_version`: bump when the payload shape changes. A reader that
# finds any other value ignores the file and falls back to the pre-FSC-2
# rebuild (old caches without the file fall back the same way — no hard
# break, by design).
MODEL_CACHE_FORMAT_VERSION = 1


def extract_alias_of(analysis: dict) -> dict:
    """The minimal alias truth of one analysis: `{var_id: source_var_id}`.

    Only non-empty `alias_of` entries are kept — the map is the extraction
    fact (I4), never a guess, so an id absent from it simply means "not an
    alias", which is exactly what the graph-data form already assumes.
    Insertion order is variable order (deterministic; JSON round-trips it).
    """
    out = {}
    for v in (analysis or {}).get("variables", []) or []:
        if isinstance(v, dict):
            vid, src = v.get("id"), v.get("alias_of")
        else:
            vid, src = getattr(v, "id", None), getattr(v, "alias_of", None)
        if vid and src:
            out[vid] = src
    return out


def write_model_cache(path, cache_key: str, extractor_version: str,
                      analysis: dict) -> int:
    """Persist the analysis path's alias truth BESIDE the graph cache.

    Called from the same build that writes the graph cache, from the SAME
    analysis dict that graph was built from — so the artifact can never
    describe a graph other than its sibling's. Returns the number of alias
    entries written. Atomic write (P1's shared helper): a concurrent
    reader of the cache dir must never see a torn artifact.
    """
    from app.services.atomic_io import atomic_write_text
    alias_of = extract_alias_of(analysis)
    payload = {
        "format_version": MODEL_CACHE_FORMAT_VERSION,
        "extractor_version": extractor_version,
        # Identity guard (mirror of folder_index_service._load_evidence):
        # the key is content-derived, so a file can only ever be read for
        # the script whose bytes produced it.
        "cache_key": cache_key,
        "alias_count": len(alias_of),
        "alias_of": alias_of,
    }
    atomic_write_text(path, json.dumps(payload, indent=1, sort_keys=True))
    return len(alias_of)


def load_model_cache(path, cache_key: str, extractor_version: str) -> dict:
    """Read the persisted alias truth back — `{}` when it cannot be used.

    Every guard failure (absent / corrupt / other contract version / other
    extractor / other cache_key / wrong payload shape) returns `{}`, which
    the callers treat as "no persisted truth": they fall back to the
    pre-FSC-2 graph-data rebuild instead of guessing from a file that does
    not describe THIS script. A stale artifact can therefore never poison a
    model — it can only be ignored.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if (payload.get("format_version") != MODEL_CACHE_FORMAT_VERSION
            or payload.get("extractor_version") != extractor_version
            or payload.get("cache_key") != cache_key):
        return {}
    alias_of = payload.get("alias_of")
    if not isinstance(alias_of, dict):
        return {}
    return {k: v for k, v in alias_of.items()
            if isinstance(k, str) and isinstance(v, str)}


def graph_with_alias_of(graph: dict, alias_of: dict) -> dict:
    """The graph-data form of `graph` with the persisted `alias_of` put back.

    Returns a graph-shaped dict (`nodes`/`edges`/`script_name`) whose node
    dicts are SHALLOW COPIES carrying the extra `alias_of` key — the input
    `graph` (the served payload, and the caller's cache object) is never
    mutated, so the persisted fact stays a model-build input and never
    leaks into a response.
    """
    if not alias_of:
        return graph
    nodes = []
    for n in graph.get("nodes", []):
        data = n.get("data", n) if isinstance(n, dict) else n
        src = alias_of.get(data.get("id", ""))
        if not src:
            nodes.append(n)
            continue
        data = dict(data)
        data["alias_of"] = src
        nodes.append({"data": data} if isinstance(n, dict) and "data" in n
                     else data)
    out = dict(graph)
    out["nodes"] = nodes
    return out
