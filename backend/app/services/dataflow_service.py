"""Dataflow service — cross-script field tracing, L1/L2 graph building, relevance filter."""
import json
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field
from app.services.sql_range_finder import find_sql_range

from app.services.workspace_service import get_workspace_dir
from app.extractor.lineage import (
    compute_field_lineage,
    filter_graph_by_lineage,
    filter_relevant,
)


from app.services.l1_builder import _build_l1_graph
from app.services.l2_builder import _build_l2_graph, _compute_highlight_ranges

@dataclass
class SearchView:
    view_id: str
    table: str
    field: str
    script_ids: list[str]
    l1_graph_cache: dict = field(default_factory=dict)
    created_at: str = ""


def create_search(ws_id: str, table: str, field: str,
                  table_index: dict, field_index: dict,
                  lineage_mode: bool = True) -> dict:
    """Find scripts touching table AND field, build L1 graph.
    
    1. Find scripts from field_index that contain this field
    2. Find scripts from table_index that contain this table
    3. Intersection = scripts touching BOTH
    4. Build L1 graph via analyze_multiple_scripts()
    5. Store view in views.json
    """
    ws_dir = get_workspace_dir(ws_id)
    from app.services.logger import api_request
    api_request('POST', f'/workspace/{ws_id}/search', 200, f'table={table} field={field}', ws_id=ws_id)
    cache_dir = ws_dir / "cache"

    # Find scripts touching this table AND this field
    field_scripts = set(field_index.get(field, {}).get("scripts", []))
    table_scripts = set(table_index.get(table, {}).get("scripts", []))
    matching_scripts = sorted(field_scripts & table_scripts)

    match_mode = "exact"
    if not matching_scripts:
        # Try broader: scripts touching field only
        matching_scripts = sorted(field_scripts | table_scripts)
        match_mode = "fallback"
    else:
        # Full transitive closure: any script in the table-dependency connected
        # component can affect or be affected by the target variable.
        # Include ALL scripts reachable via table lineage, not just those
        # that directly reference the field.
        visited_scripts = set(matching_scripts)
        frontier_tables = set()

        # Collect all tables touched by seed scripts
        for s in matching_scripts:
            for tname, tdata in table_index.items():
                if s in tdata.get("scripts", []):
                    frontier_tables.add(tname)

        # BFS: tables → scripts → more tables → more scripts ...
        changed = True
        max_iterations = 10
        while changed and max_iterations > 0:
            changed = False
            max_iterations -= 1
            new_tables = set()
            for tname in frontier_tables:
                for s in table_index.get(tname, {}).get("scripts", []):
                    if s not in visited_scripts:
                        visited_scripts.add(s)
                        changed = True
                        # This script touches other tables — add them to frontier
                        for t2, td2 in table_index.items():
                            if s in td2.get("scripts", []):
                                new_tables.add(t2)
            frontier_tables = new_tables

        if len(visited_scripts) > len(matching_scripts):
            matching_scripts = sorted(visited_scripts)
            match_mode = "expanded"

    # Build L1 graph
    l1_graph = _build_l1_graph(ws_id, matching_scripts, table, field)

    # R18: Apply lineage filter to L1 graph when lineage_mode
    if lineage_mode:
        l1_graph = _filter_l1_by_lineage(l1_graph, table, field)

    # Create view
    view_id = uuid.uuid4().hex[:12]
    view = SearchView(
        view_id=view_id,
        table=table,
        field=field,
        script_ids=matching_scripts,
        l1_graph_cache=l1_graph,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    # Persist to views.json
    _persist_search_view(ws_id, {
        "view_id": view.view_id,
        "type": "search",
        "table": view.table,
        "field": view.field,
        "script_ids": view.script_ids,
        "script_count": len(view.script_ids),
        "l1_graph_cache": view.l1_graph_cache,
        "children": [],
        "created_at": view.created_at,
    })

    return {
        "view_id": view_id,
        "table": table,
        "field": field,
        "script_ids": matching_scripts,
        "l1_graph": l1_graph,
        "match_mode": match_mode,
    }



def _filter_l1_by_lineage(l1_graph: dict, target_table: str, target_field: str) -> dict:
    """R18: Filter L1 graph to show only field nodes in lineage of target field.

    Applies R18.1 empty table cleanup: after filtering, removes table nodes
    with 0 field children except the terminal marker (direct writes_to target
    of a script that has >=1 lineage field).
    """
    nodes = l1_graph.get("nodes", [])
    edges = l1_graph.get("edges", [])

    # Identify target field nodes in L1: field nodes whose field_name matches
    # and parent table matches target_table
    lineage_field_ids = set()
    lineage_table_ids = set()
    for n in nodes:
        nd = n.get("data", n)
        if nd.get("type") == "field":
            tname = nd.get("table_name", "")
            fname = nd.get("field_name", nd.get("label", "").lstrip("★"))
            if tname == target_table and fname == target_field:
                lineage_field_ids.add(nd.get("id"))
                lineage_table_ids.add(nd.get("parent", ""))

    # Bug 27: Use compute_field_lineage pairs instead of name matching
    # Per formal definition: same-name fields from different tables are NOT
    # equivalent. Use the lineage_field_pairs computed by _build_l1_graph
    # via compute_field_lineage (same engine as L2).
    lineage_pairs = l1_graph.get("lineage_field_pairs", set())
    # Convert to dict for O(1) lookup: key = (table_name, field_name)
    if isinstance(lineage_pairs, list):
        lineage_pairs = set(tuple(p) for p in lineage_pairs)
    filtered_nodes = []
    for n in nodes:
        nd = n.get("data", n)
        ntype = nd.get("type", "")
        if ntype == "field":
            tname = nd.get("table_name", "")
            fname = nd.get("field_name", nd.get("label", "").lstrip("★"))
            # Accept if (table_name, field_name) is in the lineage set
            if (tname, fname) in lineage_pairs:
                filtered_nodes.append(n)
                lineage_field_ids.add(nd.get("id"))
                lineage_table_ids.add(nd.get("parent", ""))
        else:
            # table, script_node — always keep
            filtered_nodes.append(n)

    # ── R18.1: Empty table cleanup ──────────────────────────────────────
    # After field filtering, some table nodes may have 0 field children.
    # Rule: keep a table with 0 fields iff it is the direct writes_to target
    # of a script that has >=1 lineage field (terminal marker).
    # Remove all other empty tables and their edges.

    # Collect field parent IDs first (tables with >=1 field after filtering)
    field_parent_ids = set()
    for n in filtered_nodes:
        nd = n.get("data", n)
        if nd.get("type") == "field" and nd.get("parent"):
            field_parent_ids.add(nd.get("parent"))

    # Bug 24c: derive scripts_with_fields from edges (field parent = table ID,
    # not script ID). Find scripts connected to field-bearing tables.
    scripts_with_fields = set()
    for e in edges:
        ed = e.get("data", e)
        if ed.get("edge_type") in ("reads_from", "writes_to"):
            src, tgt = ed.get("source"), ed.get("target")
            if src in field_parent_ids:
                scripts_with_fields.add(tgt)
            if tgt in field_parent_ids:
                scripts_with_fields.add(src)

    # Identify terminal tables: direct writes_to target of scripts with fields
    terminal_table_ids = set()
    for e in edges:
        ed = e.get("data", e)
        if ed.get("edge_type") == "writes_to" and ed.get("source") in scripts_with_fields:
            terminal_table_ids.add(ed.get("target"))

    # Build set of table node types
    table_types = {
        "source_table", "intermediate_table", "output_table",
        "query_output", "cte_table",
    }

    # Keep: scripts, tables with fields, terminal marker tables
    filtered_nodes = [n for n in filtered_nodes
        if n.get("data", n).get("type") == "script_node"
        or n.get("data", n).get("id") in field_parent_ids
        or n.get("data", n).get("id") in terminal_table_ids
        or n.get("data", n).get("type") not in table_types]

    # Rebuild keep_ids and re-filter edges
    # R18.1: Terminal marker outgoing edges are KEPT (requirement changed)
    keep_ids = {n.get("data", n).get("id") for n in filtered_nodes}
    filtered_edges = [e for e in edges
                      if (e.get("data", e).get("source") in keep_ids and
                          e.get("data", e).get("target") in keep_ids)]
    
    # R18.1: Remove disconnected scripts (no remaining table edges after cleanup)
    script_ids = {n.get("data", n).get("id") for n in filtered_nodes
                  if n.get("data", n).get("type") == "script_node"}
    scripts_with_edges = set()
    for e in filtered_edges:
        ed = e.get("data", e)
        scripts_with_edges.add(ed.get("source"))
        scripts_with_edges.add(ed.get("target"))
    disconnected_scripts = script_ids - scripts_with_edges
    if disconnected_scripts:
        filtered_nodes = [n for n in filtered_nodes
                          if n.get("data", n).get("id") not in disconnected_scripts]
        keep_ids = {n.get("data", n).get("id") for n in filtered_nodes}
        filtered_edges = [e for e in filtered_edges
                          if e.get("data", e).get("source") in keep_ids
                          and e.get("data", e).get("target") in keep_ids]

    return {**l1_graph, "nodes": filtered_nodes, "edges": filtered_edges}
def get_level2_graph(ws_id: str, view_id: str, script_name: str,
                     table: str, field: str, filter_relevant_nodes: bool = True) -> dict:
    """Build L2 graph for a script. Loads pre-computed graph cache,
    applies relevance filter, returns {graph, highlights}."""
    ws_dir = get_workspace_dir(ws_id)
    from app.services.logger import api_request, stage_graph

    scripts_dir = ws_dir / "scripts"
    cache_dir = ws_dir / "cache"

    sp = scripts_dir / script_name
    if not sp.exists():
        return {"error": f"Script '{script_name}' not found"}

    sql_text = sp.read_text(encoding="utf-8", errors="replace")
    cache_key = hashlib.md5((script_name + sql_text).encode()).hexdigest()[:12]

    # Bug 25: Initialize table_schemas before cache check
    table_schemas = None
    schemas_cache_path = cache_dir / f"schemas_{cache_key}.json"

    # Try pre-computed graph cache (v3.2.15)
    graph_cache_path = cache_dir / f"graph_3_2_15_{cache_key}.json"
    if graph_cache_path.exists():
        graph_data = json.loads(graph_cache_path.read_text())
        stage_graph(len(graph_data.get('nodes',[])), len(graph_data.get('edges',[])), ws_id=ws_id)
        # Bug 25: Load cached table_schemas on cache hit
        if schemas_cache_path.exists():
            table_schemas = json.loads(schemas_cache_path.read_text())
    else:
        # Build on-demand
        from app.extractor.adapter import run_full_analysis
        from app.services.graph_service import build_graph_data
        result = run_full_analysis(sql_text, script_name, ws_id=ws_id)
        graph_data = build_graph_data(result)
        # R18: build table_schemas for lineage seed validation
        from app.extractor.schema_inference import infer_table_schemas
        table_schemas = infer_table_schemas(
            result.get("variables", []), result.get("dependencies", []))
        # Bug 25: Cache table_schemas alongside graph
        cache_dir.mkdir(parents=True, exist_ok=True)
        schemas_cache_path.write_text(json.dumps(table_schemas, default=str))

    # Apply relevance filter (if requested)
    if filter_relevant_nodes:
        filtered = filter_relevant(graph_data, table, field, table_schemas=table_schemas)
    else:
        filtered = graph_data

    # Compute highlight ranges
    highlight_ids = set()
    for n in filtered.get("nodes", []):
        nd = n.get("data", n)
        highlight_ids.add(nd.get("id", ""))

    highlights = _compute_highlight_ranges(graph_data, highlight_ids, sql_text)

    # Build the transformed L2 graph with compound nodes
    l2_result = _build_l2_graph(ws_id, script_name, sql_text, table, field, filter_relevant_nodes)
    if not l2_result.get("error"):
        # _build_l2_graph returns {nodes, edges, ...} directly, extract graph
        l2_graph_data = {
            "nodes": l2_result.get("nodes", []),
            "edges": l2_result.get("edges", []),
        }
        return {
            "script_name": script_name,
            "sql_text": sql_text,
            "graph": l2_graph_data,
            "highlights": highlights,
            "total_nodes": l2_result.get("total_nodes", len(graph_data.get("nodes", []))),
            "filtered_nodes": l2_result.get("filtered_nodes", len(filtered.get("nodes", []))),
            "total_edges": len(l2_result.get("edges", [])),
        }
    
    # Fallback: return raw graph with edge count
    return {
        "script_name": script_name,
        "sql_text": sql_text,
        "graph": filtered,
        "highlights": highlights,
        "total_nodes": len(graph_data.get("nodes", [])),
        "filtered_nodes": len(filtered.get("nodes", [])),
        "total_edges": len(filtered.get("edges", [])),
    }



def _load_views(ws_id: str) -> list:
    ws_dir = get_workspace_dir(ws_id)
    from app.services.logger import api_request

    views_path = ws_dir / "cache" / "views.json"
    if views_path.exists():
        return json.loads(views_path.read_text())
    return []


def _save_views(ws_id: str, views: list):
    ws_dir = get_workspace_dir(ws_id)
    from app.services.logger import api_request

    views_path = ws_dir / "cache" / "views.json"
    views_path.write_text(json.dumps(views, indent=2, ensure_ascii=False))


def _persist_search_view(ws_id: str, view: dict):
    """Append a search view to views.json.

    Shared by create_search and the F1 no_matches path (dataflow.py), so
    every search — even an empty one — survives reload (R3).
    """
    view.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    views = _load_views(ws_id)
    views.append(view)
    _save_views(ws_id, views)


def list_views(ws_id: str) -> list:
    return _load_views(ws_id)


def delete_view(ws_id: str, view_id: str) -> bool:
    views = _load_views(ws_id)
    # Remove view or child entry
    new_views = []
    found = False
    for v in views:
        if v["view_id"] == view_id:
            found = True
            continue
        # Check children
        children = v.get("children", [])
        v["children"] = [c for c in children if c["view_id"] != view_id]
        if len(v["children"]) < len(children):
            found = True
        new_views.append(v)
    if found:
        _save_views(ws_id, new_views)
    return found
