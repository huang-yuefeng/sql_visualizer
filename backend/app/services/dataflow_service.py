"""Dataflow service — cross-script field tracing, L1/L2 graph building, relevance filter."""
import json
import uuid
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field
from app.services.sql_range_finder import find_sql_range

from app.services.workspace_service import get_workspace_dir


@dataclass
class SearchView:
    view_id: str
    table: str
    field: str
    script_ids: list[str]
    l1_graph_cache: dict = field(default_factory=dict)
    created_at: str = ""


def create_search(ws_id: str, table: str, field: str,
                  table_index: dict, field_index: dict) -> dict:
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
    views = _load_views(ws_id)
    views.append({
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
    _save_views(ws_id, views)

    return {
        "view_id": view_id,
        "table": table,
        "field": field,
        "script_ids": matching_scripts,
        "l1_graph": l1_graph,
        "match_mode": match_mode,
    }


def _classify_table_node(table_name, all_scripts):
    """Classify a table as source, intermediate, or output based on read/write patterns."""
    readers = set()
    writers = set()
    for s in all_scripts:
        if table_name in s.get("input_tables", []):
            readers.add(s["script_name"])
        if table_name in s.get("output_tables", []):
            writers.add(s["script_name"])
    if readers and not writers:
        return "source_table"
    if writers and not readers:
        return "output_table"
    if writers and readers:
        return "intermediate_table"
    return "source_table"


def detect_role(script_analysis: dict, target_table: str, target_field: str) -> list:
    """Read-only summary: how is (T, f) used in this script?

    Queries the already-extracted variables and dependencies from cached
    analysis data. Uses defined_in, variable_type, is_output, and
    dependency relationship fields. No new SQL parsing.

    Resolves table aliases: if a column is named "sc.customer_id"
    and sc is an alias for stg_customers, it matches target_table="stg_customers".
    """
    # Graph uses nodes (not variables) and edges (not dependencies)
    nodes = script_analysis.get("nodes", [])
    # Also support raw analysis format with "variables" key
    raw_vars = script_analysis.get("variables", [])
    # Unwrap node data: each node is {"data": {...}}
    variables = []
    for n in nodes:
        nd = n.get("data", n)
        variables.append(nd)
    # Merge with raw variables if present
    if raw_vars:
        seen = {v["id"] for v in variables if "id" in v}
        for rv in raw_vars:
            if rv.get("id") not in seen:
                variables.append(rv)

    edges_list = script_analysis.get("edges", [])
    deps_raw = script_analysis.get("dependencies", [])
    # Unwrap edge data
    deps = []
    for e in edges_list:
        ed = e.get("data", e)
        deps.append(ed)
    deps.extend(deps_raw)

    target_full = f"{target_table}.{target_field}"

    var_by_id = {v["id"]: v for v in variables if "id" in v}

    # Build alias map: alias_name -> original_table_name
    alias_map = {}
    for v in variables:
        if v.get("variable_type") == "table":
            vname = v.get("label") or v.get("name", "")
            src_tables = v.get("source_tables", [])
            if src_tables and vname:
                alias_map[vname] = src_tables[0]  # alias -> original

    roles = set()

    for v in variables:
        name = v.get("label") or v.get("name", "")
        vid = v.get("id", "")
        vt = v.get("variable_type", "")

        # Match logic: exact match, alias-resolved match, or bare field match
        matches = False

        # 1. Exact full name match
        if target_full in name:
            matches = True

        # 2. Alias-resolved match: "sc.customer_id" where sc->stg_customers
        if not matches and "." in name:
            prefix, suffix = name.split(".", 1)
            resolved = alias_map.get(prefix, prefix)
            if resolved == target_table and suffix == target_field:
                matches = True

        # 3. Suffix match: "sc.customer_id" field part matches target_field
        if not matches and "." in name:
            suffix = name.rsplit(".", 1)[-1]
            if suffix == target_field:
                matches = True

        # 4. Bare field match (no table prefix at all)
        if not matches and "." not in name:
            if name == target_field:
                matches = True

        # 5. source_columns match
        if not matches:
            src_cols = v.get("source_columns", [])
            for sc in src_cols:
                if target_full in sc or re.search(rf'\b{re.escape(target_field)}\b', sc):
                    matches = True
                    break
                if "." in sc:
                    sp, ss = sc.split(".", 1)
                    if alias_map.get(sp, sp) == target_table and ss == target_field:
                        matches = True
                        break

        if not matches:
            continue

        di = (v.get("defined_in") or "").upper()

        # Column-level: detect role from defined_in context
        if vt == "column":
            if "FROM" in di:
                roles.add("SCHEMA")
            if "JOIN" in di or "ON" in di:
                roles.add("JOIN")
            if "WHERE" in di or "HAVING" in di:
                roles.add("FILTER")
            # GROUP BY modifies AGGREGATE, not a separate edge type
            # ORDER BY modifies WINDOW, not a separate edge type
            if v.get("is_output"):
                roles.add("REF")

        # Computed types: detect role from variable_type
        if vt == "aggregate":
            roles.add("AGGREGATE")
        if vt == "window":
            roles.add("WINDOW")
        if vt == "transform":
            roles.add("TRANSFORM")
        if vt == "case":
            roles.add("COMPUTED")

    # Dependency-level: DML and CORRELATED
    for d in deps:
        rel = d.get("relationship", "")
        tgt_id = d.get("target_id") or d.get("target", "")
        src_id = d.get("source_id") or d.get("source", "")
        tgt = var_by_id.get(tgt_id, {})
        src = var_by_id.get(src_id, {})
        tgt_name = tgt.get("name", "")
        src_name = src.get("name", "")

        def dep_matches(dep_name):
            if not dep_name:
                return False
            if target_full in dep_name:
                return True
            if "." in dep_name:
                p, s = dep_name.split(".", 1)
                if alias_map.get(p, p) == target_table and s == target_field:
                    return True
            if "." not in dep_name and dep_name == target_field:
                return True
            return False

        if rel == "DML" and dep_matches(tgt_name):
            roles.add("DML TARGET")
        if rel == "INDIRECT" and dep_matches(src_name):
            roles.add("CORRELATED")

    return sorted(roles)


def _build_l1_graph(ws_id: str, script_names: list[str],
                    table: str, field: str) -> dict:
    """Build Level 1 cross-script pipeline graph.

    Nodes: source tables (blue rect), scripts (orange rounded-rect),
           intermediate tables (gray rect), output tables (green rect).
    Edges: undirected table↔script per formal §5.1: (s,t) ∈ E iff s uses t, with role badges for target var.
    """
    if len(script_names) < 1:
        return {"nodes": [], "edges": [], "target": f"{table}.{field}"}

    scripts_dir = get_workspace_dir(ws_id) / "scripts"
    script_data = []
    for name in script_names:
        sp = scripts_dir / name
        if sp.exists():
            sql = sp.read_text(encoding="utf-8", errors="replace")
            script_data.append((name, sql))

    if len(script_data) < 2:
        nodes = []
        for name, _ in script_data:
            sid = hashlib.md5(name.encode()).hexdigest()[:12]
            nodes.append({"data": {
                "id": sid, "label": name, "type": "script_node",
                "script_name": name,
            }})
        return {"nodes": nodes, "edges": [], "target": f"{table}.{field}"}

    try:
        from app.services.multi_script_service import analyze_multiple_scripts
        result = analyze_multiple_scripts(script_data)

        all_scripts = result.get("scripts", [])
        nodes = []
        edges = []
        seen_node_ids = set()
        seen_edge_ids = set()

        def add_node(nid, label, ntype, **extra):
            if nid in seen_node_ids:
                return
            seen_node_ids.add(nid)
            d = {"id": nid, "label": label, "type": ntype}
            d.update(extra)
            nodes.append({"data": d})

        def add_edge(src, tgt, label, etype, role=None, roles=None):
            eid = f"{src}->{tgt}"
            if eid in seen_edge_ids:
                # Merge roles if edge already exists
                for e in edges:
                    if e["data"]["id"] == eid:
                        existing = e["data"].get("roles", [])
                        if roles:
                            merged = sorted(set(existing + roles))
                            e["data"]["roles"] = merged
                            e["data"]["role"] = ", ".join(merged)
                        break
                return
            seen_edge_ids.add(eid)
            d = {"id": eid, "source": src, "target": tgt,
                 "label": label, "edge_type": etype}
            if roles:
                d["roles"] = roles
                d["role"] = ", ".join(roles)
            elif role:
                d["roles"] = [role]
                d["role"] = role
            edges.append({"data": d})

        # ── Classify tables (filter out aliases) ──
        # Build alias set: table names that are actually SQL aliases.
        # An alias is a name that:
        #   a) appears as a variable with source_tables pointing to another table, OR
        #   b) is short (<=3 chars) and lowercase (typical SQL alias pattern like "so", "c")
        #   c) appears in analysis cache as an alias (has source_tables)
        aliases = set()
        for s in all_scripts:
            for v in s.get("_all_vars", []):
                src_tables = v.get("source_tables", [])
                name = v.get("name", "")
                if src_tables:
                    aliases.add(name)
                # Bug 5 fix: removed length heuristic — semantic check above covers real aliases
        # (Analysis cache aliases collected below after cache_map is built)

        all_inputs = set()
        all_outputs = set()
        for s in all_scripts:
            for t in s.get("input_tables", []):
                if not t.startswith("⟐") and t not in aliases:
                    all_inputs.add(t)
            for t in s.get("output_tables", []):
                if not t.startswith("⟐") and t not in aliases:
                    all_outputs.add(t)

        source_tables = sorted(all_inputs - all_outputs)
        intermediate_tables = sorted(all_inputs & all_outputs)
        output_tables = sorted(all_outputs - all_inputs)

        # ── Add table nodes (skip known SQL aliases: short names) ──
        for tname in source_tables:
            if tname in aliases:
                continue  # Bug 5 fix: skip confirmed aliases only
            if tname.startswith("⟐"):
                continue  # skip virtual/anonymous tables
            add_node(f"tbl_{tname}", tname, "source_table",
                     table_name=tname)
        for tname in intermediate_tables:
            if tname in aliases:
                continue  # Bug 5 fix: skip confirmed aliases only
            if tname.startswith("⟐"):
                continue  # skip virtual/anonymous tables
            add_node(f"tbl_{tname}", tname, "intermediate_table",
                     table_name=tname)
        for tname in output_tables:
            if tname in aliases:
                continue  # Bug 5 fix: skip confirmed aliases only
            # If the "output" is a virtual table from SELECT-only script,
            # still show it but mark as query_output
            ntype = "output_table"
            if tname.startswith("⟐"):
                ntype = "query_output"
            add_node(f"tbl_{tname}", tname, ntype,
                     table_name=tname)

        # ── Add script nodes + edges + role detection ──
        for s in all_scripts:
            sid = s["script_id"]
            sname = s["script_name"]
            inputs = [t for t in s.get("input_tables", []) if not t.startswith("⟐")]
            outputs = [t for t in s.get("output_tables", []) if not t.startswith("⟐")]

            # Detect roles for this script (read-only query over cached analysis)
            graph_data = s.get("graph", {})
            roles = detect_role(graph_data, table, field)

            add_node(sid, sname, "script_node",
                     script_name=sname,
                     total_variables=s.get("total_variables", 0),
                     input_tables=inputs,
                     output_tables=outputs,
                     roles=roles)

            # Directed table↔script edges: table→script (reads) + script→table (writes)
            for tname in inputs:
                tbl_id = f"tbl_{tname}"
                if tbl_id in seen_node_ids:
                    add_edge(tbl_id, sid, tname, "reads_from",
                             roles=roles if roles else None)
            for tname in outputs:
                tbl_id = f"tbl_{tname}"
                if tbl_id in seen_node_ids:
                    add_edge(sid, tbl_id, tname, "writes_to",
                             roles=roles if roles else None)
            
            # If script has inputs but no outputs (SELECT-only query),
            # add a virtual terminal output node so the pipeline is complete
            if inputs and not outputs:
                terminal_name = f"⟐result_{sid[:8]}"
                terminal_id = f"tbl_{terminal_name}"
                add_node(terminal_id, "Query Result", "query_output",
                         table_name=terminal_name)
                add_edge(sid, terminal_id, terminal_name, "writes_to",
                         roles=roles if roles else None)

        # ── V3.2.3: Script-to-script data lineage REMOVED ──
        # Per formal definition §5.1: data flows through variables, not scripts.
        # Edges are table→script (reads) and script→table (writes).
        # Script-to-script connectivity is implicit via shared tables.
        # The table_script edges above already capture this: e.g.
        #   step1 → stg_orders → step3 shows data flow through the variable.


        # ── V3.3: Enrich L1 with compound field children (design §5.1, §4.6) ──
        # Add field-level nodes as children of table compound nodes.
        # Reads per-script analysis cache (analysis_*.json) which has raw
        # variables+dependencies, NOT the graph cache (graph_*.json).
        target_full = f"{table}.{field}"
        direct_fields = set()    # (table_name, field_name) on path to target
        indirect_fields = set()  # (table_name, field_name) off-path
        cache_dir = scripts_dir.parent / "cache"

        # Build a map: script_name → analysis cache file path
        # Script IDs from analyze_multiple_scripts() may differ from those
        # generated during upload/index (different script name prefix).
        # We match by script_name inside each analysis file.
        analysis_cache_map = {}  # script_name → analysis dict
        if cache_dir.exists():
            for af_path in sorted(cache_dir.glob("analysis_*.json")):
                try:
                    adata = json.loads(af_path.read_text())
                    sname = adata.get("script_name", "")
                    if sname:
                        analysis_cache_map[sname] = adata
                except Exception:
                    pass

        for s in all_scripts:
            sid = s.get("script_id", "")
            sname = s.get("script_name", "")
            # Try exact match first, then prefix match (strip workspace dir prefix)
            analysis = analysis_cache_map.get(sname)
            if not analysis:
                # Try matching by just filename (strip dir prefix like "multi_workflow/")
                for cache_name, cache_data in analysis_cache_map.items():
                    if cache_name.endswith("/" + sname) or cache_name == sname:
                        analysis = cache_data
                        break
            if not analysis:
                continue

            variables = analysis.get("variables", [])
            deps = analysis.get("dependencies", [])

            # Build alias → real table name map from table variables
            alias_to_real = {}
            for v in variables:
                vt = v.get("variable_type", "")
                name = v.get("name", "")
                src_tables = v.get("source_tables", [])
                if vt in ("table",) and src_tables:
                    alias_to_real[name] = src_tables[0]

            # Find target variable in this script
            target_var_ids = set()
            var_by_id = {}
            for v in variables:
                vid = v.get("id", "")
                var_by_id[vid] = v
                vname = v.get("name", "")
                if vname == target_full or vname.endswith("." + field):
                    target_var_ids.add(vid)
            
            # Expand to transitively connected variables via BFS
            if target_var_ids:
                adj = {}
                for d in deps:
                    src = d.get("source_id", "")
                    tgt = d.get("target_id", "")
                    if src not in adj: adj[src] = set()
                    if tgt not in adj: adj[tgt] = set()
                    adj[src].add(tgt)
                    adj[tgt].add(src)
                
                visited = set(target_var_ids)
                queue = list(target_var_ids)
                while queue:
                    vid = queue.pop(0)
                    for neighbor in adj.get(vid, set()):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            queue.append(neighbor)
                
                for v in variables:
                    vname = v.get("name", "")
                    vt = v.get("variable_type", "")
                    # Only process column-like variables
                    if vt not in ("column", "cte_column"):
                        continue
                    
                    src_tables = v.get("source_tables", [])
                    var_table = None
                    # Derive field name: last part after dot, or whole name
                    var_field = vname.rsplit(".", 1)[-1] if "." in vname else vname
                    
                    if src_tables:
                        var_table = src_tables[0]
                    elif "." in vname:
                        prefix = vname.rsplit(".", 1)[0]
                        # Resolve alias prefix to real table name
                        var_table = alias_to_real.get(prefix, prefix)
                    
                    # Skip ⟐ and empty. Accept any valid table name (even short ones).
                    if var_table and var_table not in ("⟐", ""):
                        key = (var_table, var_field)
                        if v.get("id") in visited:
                            direct_fields.add(key)
                        else:
                            indirect_fields.add(key)
        
        # Add field child nodes to table compound nodes
        for (tname, fname) in sorted(direct_fields | indirect_fields):
            tbl_id = f"tbl_{tname}"
            if tbl_id not in seen_node_ids:
                continue
            field_id = f"fld_{tname}_{fname}"
            if field_id in seen_node_ids:
                continue
            seen_node_ids.add(field_id)
            is_direct = (tname, fname) in direct_fields
            is_target = (f"{tname}.{fname}" == target_full)
            field_label = f"★{fname}" if is_target else fname
            field_node = {
                "data": {
                    "id": field_id,
                    "label": field_label,
                    "type": "field",
                    "parent": tbl_id,
                    "field_group": "direct" if is_direct else "indirect",
                    "is_target": is_target,
                    "table_name": tname,
                    "field_name": fname,
                }
            }
            nodes.append(field_node)
        
        # ── Build layer info for pipeline layout ──
        # Longest-path layering (V3.3.10): assign layer = max(predecessor_layers) + 1
        # This produces the correct topological depth for densely-connected graphs.
        # Unlike shortest-path BFS, longest-path ensures nodes appear at their true
        # pipeline depth — all upstream dependencies must be at lower layers.
        #
        # Fixed-point iteration: repeat until no layer changes.
        # Edges go from lower layer → higher layer (forward edges propagate +1).
        # Backward edges (higher→lower, indicating cycles) propagate max+1 to break ties.

        # Build adjacency lists
        adj_forward = {}   # source → [targets]  (forward data flow)
        adj_backward = {}  # target → [sources]  (reverse / backward)
        for e in edges:
            ed = e["data"]
            s = ed["source"]
            t = ed["target"]
            adj_forward.setdefault(s, []).append(t)
            adj_backward.setdefault(t, []).append(s)

        # ── V3.3.15: Simple layer propagation (cap at 10) ──
        # Prevents layer explosion for disconnected components by capping
        # new_layer at MAX_LAYER=10. All nodes stay within visible range.
        MAX_LAYER = 10
        node_layers = {}
        for n in nodes:
            node_layers[n["data"]["id"]] = 0

        # Forward pass: longest-path with cap
        for _ in range(200):
            changed = False
            for n in nodes:
                nid = n["data"]["id"]
                max_pred_layer = -1
                for pred in adj_backward.get(nid, []):
                    if pred in node_layers:
                        max_pred_layer = max(max_pred_layer, node_layers[pred])
                if max_pred_layer >= 0:
                    new_layer = min(max_pred_layer + 1, MAX_LAYER)
                    if node_layers[nid] < new_layer:
                        node_layers[nid] = new_layer
                        changed = True
            if not changed:
                break

        # Reverse pass with cap
        for _ in range(20):
            changed = False
            for nid, lyr in list(node_layers.items()):
                max_neighbor = lyr
                for nb in adj_forward.get(nid, []) + adj_backward.get(nid, []):
                    if nb in node_layers and node_layers[nb] > max_neighbor:
                        max_neighbor = node_layers[nb]
                if max_neighbor > lyr + 1:
                    node_layers[nid] = min(max_neighbor - 1, MAX_LAYER)
                    changed = True
            if not changed:
                break

        # Assign layers to nodes
        for n in nodes:
            nid = n['data']['id']
            n['data']['layer'] = node_layers.get(nid, 0)

        # ── Snake-wrap layout (V3.3.9) ──
        # Interleave tables and scripts by layer — no more separate row groups.
        # Fixes: 2.1 (tables+scripts separated), 2.2 (edges span extreme distances),
        #        2.5 (R→L reversal removed)
        # Always left-to-right; no turn edges.
        
        # Collect top-level nodes (tables + scripts), skip field children
        top_nodes = []
        for n in nodes:
            nd = n["data"]
            t = nd.get("type", "")
            if nd.get("parent") or t == "field":
                continue
            if t.endswith("_table") or t == "script_node" or t == "query_output":
                top_nodes.append(n)
        
        # Sort by layer, then by type (tables before scripts in same layer), then label
        def sort_key(n):
            nd = n["data"]
            t = nd.get("type", "")
            type_priority = 0 if t.endswith("_table") else (1 if t == "script_node" else 2)
            return (nd.get("layer", 999), type_priority, nd.get("label", ""))
        
        top_nodes.sort(key=sort_key)
        
        # Snake-wrap parameters (unified row height for all node types)
        MAX_PER_ROW = 3
        NODE_SPACING = 320
        ROW_HEIGHT = 300
        
        # V3.3.15: Simple layer-based positioning (layers capped at 10).
        # All nodes in same layer share same Y; snake-wrap X within layer.
        for n in top_nodes:
            nd = n["data"]
            layer = nd.get("layer", 0)
            col_in_layer = 0
            for prev in top_nodes:
                if prev is n:
                    break
                if prev["data"].get("layer", 0) == layer:
                    col_in_layer += 1
            
            x = col_in_layer * NODE_SPACING + 100
            y = layer * ROW_HEIGHT + 60
            
            n["data"]["x"] = x
            n["data"]["y"] = y
        
        # Field nodes: positioned relative to parent (offset calculated by frontend)
        for n in nodes:
            nd = n["data"]
            if nd.get("parent"):
                nd["x"] = 0
                nd["y"] = 0

        # ── V3.2.6: Propagate fields to intermediate/output tables ──
        # Tables like analytics_orders, daily_summary may have 0 direct
        # fields because the extractor assigns columns to source tables
        # (via aliases). We propagate: if table A (with fields) feeds into
        # table B through script S, then B inherits A's fields (indirect).
        field_by_table = {}  # table_id -> set of (tname, fname)
        for n in nodes:
            nd = n["data"]
            if nd["type"] == "field":
                parent = nd.get("parent", "")
                if parent:
                    field_by_table.setdefault(parent, set()).add(
                        (nd.get("table_name", ""), nd.get("field_name", ""), nd.get("field_group", "indirect"))
                    )
        
        # Build: for each table, which scripts write to it (producers)
        #         and which tables those scripts read from (inputs)
        producers = {}  # table_id -> set of script_ids that write to it
        inputs_of = {}  # script_id -> set of table_ids it reads from
        for e in edges:
            ed = e["data"]
            if ed.get("edge_type") == "writes_to":
                # script -> table
                producers.setdefault(ed["target"], set()).add(ed["source"])
            elif ed.get("edge_type") == "reads_from":
                # table -> script
                inputs_of.setdefault(ed["target"], set()).add(ed["source"])
        
        # Propagate: for table B with 0 fields, find scripts S that
        # WRITE to B (producers), then find tables A that S READS from
        # (inputs), and inherit A's fields down to B.
        propagated = 0
        for n in nodes:
            nd = n["data"]
            nid = nd["id"]
            ntype = nd["type"]
            if ntype not in ("intermediate_table", "output_table"):
                continue
            if nid in field_by_table and field_by_table[nid]:
                continue  # already has fields
            
            tname = nd.get("table_name", "")
            # Find scripts that PRODUCE this table
            upstream_fields = set()
            for sid in producers.get(nid, set()):
                # For each producer script, get its input tables
                for input_tbl_id in inputs_of.get(sid, set()):
                    if input_tbl_id != nid and input_tbl_id in field_by_table:
                        upstream_fields.update(field_by_table[input_tbl_id])
            
            if upstream_fields:
                for (ftname, fname, fgroup) in upstream_fields:
                    field_id = f"fld_{tname}_{fname}"
                    if field_id in seen_node_ids:
                        continue
                    seen_node_ids.add(field_id)
                    is_target = (f"{tname}.{fname}" == target_full)
                    field_label = f"★{fname}" if is_target else fname
                    field_node = {
                        "data": {
                            "id": field_id,
                            "label": field_label,
                            "type": "field",
                            "parent": nid,
                            "field_group": "indirect",
                            "is_target": is_target,
                            "table_name": tname,
                            "field_name": fname,
                        }
                    }
                    nodes.append(field_node)
                    field_by_table.setdefault(nid, set()).add(
                        (tname, fname, "indirect")
                    )
                    propagated += 1
        
        if propagated:
            import logging
            logging.getLogger("sql_visualizer.dataflow").debug(
                "L1 field propagation: %d fields inherited by downstream tables", propagated)

        return {
            "nodes": nodes,
            "edges": edges,
            "target": f"{table}.{field}",
            "source_tables": source_tables,
            "intermediate_tables": intermediate_tables,
            "output_tables": output_tables,
            "script_count": len(all_scripts),
        }
    except Exception:
        import traceback
        traceback.print_exc()
        nodes = []
        for name in script_names:
            sid = hashlib.md5(name.encode()).hexdigest()[:12]
            nodes.append({"data": {"id": sid, "label": name, "type": "script_node", "script_name": name}})
        return {"nodes": nodes, "edges": [], "target": f"{table}.{field}"}




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

    # Try pre-computed graph cache (v3.2.15)
    graph_cache_path = cache_dir / f"graph_3_2_15_{cache_key}.json"
    if graph_cache_path.exists():
        graph_data = json.loads(graph_cache_path.read_text())
        stage_graph(len(graph_data.get('nodes',[])), len(graph_data.get('edges',[])), ws_id=ws_id)
    else:
        # Build on-demand
        from app.extractor.adapter import run_full_analysis
        from app.services.graph_service import build_graph_data
        result = run_full_analysis(sql_text, script_name, ws_id=ws_id)
        graph_data = build_graph_data(result)

    # Apply relevance filter (if requested)
    if filter_relevant_nodes:
        filtered = filter_relevant(graph_data, table, field)
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



def compute_field_lineage(graph_data: dict, target_table: str,
                          target_field: str) -> set:
    """R18: Compute the lineage set R for a target field using edge-type-specific rules.

    Uses iterative BFS through 15 edge types from the formal definition.
    Returns set of node IDs in the lineage closure.
    """
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    # Build adjacency: node_id -> [(neighbor_id, edge_type, direction)]
    # direction: "forward" (node -> neighbor) or "reverse" (neighbor -> node)
    adj = {}
    node_labels = {}
    node_types = {}
    for n in nodes:
        nd = n.get("data", n)
        nid = nd.get("id", "")
        node_labels[nid] = nd.get("label", "")
        node_types[nid] = nd.get("node_type", nd.get("variable_type", ""))
        adj.setdefault(nid, [])

    for e in edges:
        ed = e.get("data", e)
        src, tgt = ed.get("source"), ed.get("target")
        etype = ed.get("edge_type", "")
        adj.setdefault(src, []).append((tgt, etype, "forward"))
        adj.setdefault(tgt, []).append((src, etype, "reverse"))

    # Production edge types: edges that "produce" a target
    _PRODUCTION = {"REF", "TRANSFORM", "AGGREGATE", "WINDOW", "COMPUTED", "DML",
                   "TABLE_FLOW", "ALIAS"}
    _BIDIR = _PRODUCTION | {"CORRELATED", "INDIRECT", "SET_OP", "SUBSET"}
    _CONDITIONAL = {"JOIN", "FILTER", "SCHEMA"}

    # Find seed nodes matching target_table.target_field
    full_name = f"{target_table}.{target_field}"
    seed_ids = set()
    for n in nodes:
        nd = n.get("data", n)
        label = nd.get("label", "")
        ntype = nd.get("node_type", nd.get("variable_type", ""))
        if label == full_name or label == target_field:
            seed_ids.add(nd.get("id"))
        src_cols = nd.get("source_columns", [])
        if src_cols and (full_name in src_cols or target_field in src_cols):
            seed_ids.add(nd.get("id"))

    if not seed_ids:
        return set()

    R = set(seed_ids)
    changed = True

    while changed:
        changed = False
        new_nodes = set()
        for nid in list(R):
            for (neighbor, etype, direction) in adj.get(nid, []):
                if neighbor in R:
                    continue

                should_add = False

                if etype in _BIDIR:
                    # Unconditional bidirectional
                    should_add = True
                elif etype == "SCHEMA":
                    # table <-> column
                    if direction == "reverse":
                        # column -> table (upstream): always add table
                        should_add = True
                    else:
                        # table -> column (downstream): production-filtered
                        # Only add column if it has a production edge from R
                        for (n2, e2, d2) in adj.get(neighbor, []):
                            if n2 in R and e2 in _PRODUCTION and d2 == "reverse":
                                should_add = True
                                break
                elif etype == "JOIN":
                    # Both endpoints must already be in R via production
                    has_prod = False
                    for (n2, e2, d2) in adj.get(neighbor, []):
                        if n2 in R and e2 in _PRODUCTION:
                            has_prod = True
                            break
                    if has_prod:
                        should_add = True
                elif etype == "FILTER":
                    # Both must be in R via production
                    has_prod = False
                    for (n2, e2, d2) in adj.get(neighbor, []):
                        if n2 in R and e2 in _PRODUCTION:
                            has_prod = True
                            break
                    if has_prod:
                        should_add = True

                if should_add:
                    new_nodes.add(neighbor)

        if new_nodes:
            R |= new_nodes
            changed = True

    return R


def filter_graph_by_lineage(graph_data: dict, lineage_set: set) -> dict:
    """R18: Filter graph to only nodes and edges in the lineage set."""
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    filtered_nodes = [n for n in nodes
                      if (n.get("data", n).get("id") in lineage_set)]
    filtered_edges = [e for e in edges
                      if (e.get("data", e).get("source") in lineage_set and
                          e.get("data", e).get("target") in lineage_set)]

    return {
        **{k: v for k, v in graph_data.items() if k not in ("nodes", "edges")},
        "nodes": filtered_nodes,
        "edges": filtered_edges,
        "total_nodes": len(nodes),
        "filtered_nodes": len(filtered_nodes),
        "total_edges": len(edges),
        "filtered_edges": len(filtered_edges),
    }


def filter_relevant(graph_data: dict, target_table: str,
                    target_field: str) -> dict:
    """R18: Filter graph using field-level lineage rules (16 edge types).

    Falls back to old BFS if lineage returns empty.
    """
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    # Use formal lineage computation (R18)
    lineage = compute_field_lineage(graph_data, target_table, target_field)

    if not lineage:
        # Fallback: return full graph
        return graph_data

    relevant_nodes = [n for n in nodes if (n.get("data", n).get("id") in lineage)]
    relevant_edges = [
        e for e in edges
        if (e.get("data", e).get("source") in lineage and
            e.get("data", e).get("target") in lineage)
    ]

    return {
        **{k: v for k, v in graph_data.items() if k not in ("nodes", "edges")},
        "nodes": relevant_nodes,
        "edges": relevant_edges,
        "total_filtered": len(nodes) - len(relevant_nodes),
    }


def _compute_highlight_ranges(graph_data: dict, highlight_ids: set,
                               sql_text: str) -> list:
    """Compute line ranges to highlight based on node line_map."""
    line_map = graph_data.get("line_map", {})
    ranges = []
    for nid in highlight_ids:
        if nid in line_map:
            start, end = line_map[nid]
            ranges.append([start, end])
    if not ranges:
        return []

    # Merge overlapping/adjacent ranges
    ranges.sort()
    merged = [ranges[0]]
    for r in ranges[1:]:
        last = merged[-1]
        if r[0] <= last[1] + 1:
            merged[-1][1] = max(last[1], r[1])
        else:
            merged.append(r)
    return merged


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


# ══════════════════════════════════════════════════════════════════════
# V3.2: Edge Category Mapping (14 formal types → 7 visual categories)
# Per formal definition §10.3
# ══════════════════════════════════════════════════════════════════════

# V3.2.1: Per-type edge visualization — each of 16 formal edge types has its own color + style
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

def _get_edge_style(edge_type: str) -> dict:
    """Get per-type display style for an edge."""
    return EDGE_TYPE_STYLE.get(edge_type, EDGE_TYPE_STYLE["SUBSET"])


# V3.2.1: 7-category mapping for visual grouping
CATEGORY_MAP = {
    # copy: value flows without transformation
    "REF": "copy",
    # compute: transformation functions
    "TRANSFORM": "compute",
    "COMPUTED": "compute",
    # aggregate: summarization
    "AGGREGATE": "aggregate",
    "WINDOW": "aggregate",
    # filter: gate conditions
    "FILTER": "filter",
    "JOIN": "filter",
    "INDIRECT": "filter",
    "CORRELATED": "filter",
    # combine: set operations, subqueries
    "SET_OP": "combine",
    "SUBQUERY": "combine",
    # write: DML operations
    "DML": "write",
    # structure: ownership, aliasing, bridging
    "SCHEMA": "structure",
    "ALIAS": "structure",
    "SUBSET": "structure",
    "TABLE_FLOW": "structure",
}

def _get_category(edge_type: str) -> str:
    """Map edge type to one of 7 visual categories."""
    return CATEGORY_MAP.get(edge_type, "structure")


def _get_category_color(edge_type: str) -> str:
    """Get per-type color."""
    return EDGE_TYPE_STYLE.get(edge_type, {}).get("color", "#7F8C8D")


# ══════════════════════════════════════════════════════════════════════
# V3.2: _build_l2_graph — Per-script graph with compound nodes + sql_range
# ══════════════════════════════════════════════════════════════════════

def _build_l2_graph(ws_id: str, script_name: str, sql_text: str,
                    table: str, field: str,
                    relevance_filter: bool = True) -> dict:
    """Build Level 2 per-script graph with compound nodes and edge metadata.

    Returns:
      {
        "nodes": [{"data": {id, label, type, parent?, field_group?, is_target?, ...}}],
        "edges": [{"data": {id, source, target, edge_type, category, sql_range?, ...}}],
        "script_name": str,
        "total_nodes": int,           # nodes before filtering
        "filtered_nodes": int,        # nodes after filtering
        "target": "table.field",
      }

    Node types in L2:
      - source_table, intermediate_table, output_table (compound parents)
      - field (child of table, with parent=data.parent)
      - cte_table (CTE definition, L2 only)
      - expression, aggregate, window, transform, case, literal (existing V2 types)

    Edge metadata per formal definition §10:
      - edge_type: formal type (REF, JOIN, FILTER, etc.)
      - category: visual group (copy, filter, aggregate, compute, combine, write, structure)
      - sql_range: [start_line, start_col, end_line, end_col] for SQL highlighting
    """
    from app.extractor.adapter import run_full_analysis
    from app.services.graph_service import build_graph_data

    ws_dir = get_workspace_dir(ws_id)
    from app.services.logger import api_request, stage_graph

    cache_dir = ws_dir / "cache"
    cache_key = hashlib.md5((script_name + sql_text).encode()).hexdigest()[:12]

    # Try cached graph (v3.2.15 — includes edge filter fix)
    graph_cache_path = cache_dir / f"graph_3_2_15_{cache_key}.json"
    if graph_cache_path.exists():
        full_graph = json.loads(graph_cache_path.read_text())
        stage_graph(len(full_graph.get('nodes',[])), len(full_graph.get('edges',[])), ws_id=ws_id)
    else:
        result = run_full_analysis(sql_text, script_name, ws_id=ws_id)
        full_graph = build_graph_data(result)
        # Cache for future use
        cache_dir.mkdir(parents=True, exist_ok=True)
        graph_cache_path.write_text(json.dumps(full_graph, default=str))

    # Apply relevance filter if requested
    if relevance_filter:
        graph_data = filter_relevant(full_graph, table, field)
    else:
        graph_data = full_graph

    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    # ── Build compound node structure ──
    # Group field-level nodes by their parent table/CTE
    table_nodes = {}       # id -> table compound node
    field_nodes = []       # field children
    other_nodes = []       # expression, aggregate, etc. (non-compound)
    seen_ids = set()

    target_full = f"{table}.{field}"

    # Identify target node IDs (for is_target and direct/indirect)
    target_node_ids = set()
    for n in nodes:
        nd = n.get("data", n)
        name = nd.get("label", "")
        vt = nd.get("variable_type", "")
        if vt in ("column", "cte_column", "expression", "aggregate",
                   "window", "case", "transform"):
            # Match: exact full name, exact field name, or suffix after "."
            matched = False
            if name == target_full or name == field:
                matched = True
            elif "." in name:
                suffix = name.rsplit(".", 1)[-1]
                if suffix == field:
                    matched = True
            if matched:
                target_node_ids.add(nd.get("id"))
            # Also check source_columns
            src_cols = nd.get("source_columns", [])
            for sc in src_cols:
                if target_full in sc:
                    target_node_ids.add(nd.get("id"))
                elif target_field_sc(sc, target_field):
                    target_node_ids.add(nd.get("id"))

    # Compute upstream/downstream sets for direct/indirect classification
    fwd_adj = {}
    rev_adj = {}
    for e in edges:
        ed = e.get("data", e)
        src, tgt = ed.get("source"), ed.get("target")
        fwd_adj.setdefault(src, []).append(tgt)
        rev_adj.setdefault(tgt, []).append(src)

    # BFS from targets
    direct_ids = set(target_node_ids)
    if target_node_ids:
        # Upstream BFS
        queue = list(target_node_ids)
        while queue:
            cur = queue.pop(0)
            for src in rev_adj.get(cur, []):
                if src not in direct_ids:
                    direct_ids.add(src)
                    queue.append(src)
        # Downstream BFS
        queue = list(target_node_ids)
        while queue:
            cur = queue.pop(0)
            for tgt in fwd_adj.get(cur, []):
                if tgt not in direct_ids:
                    direct_ids.add(tgt)
                    queue.append(tgt)

    # ── Phase 0: Build alias map before classifying nodes ──
    # Aliases are table-like variables that reference another table via source_tables
    alias_map = {}  # alias_name -> canonical_table_name
    for n in nodes:
        nd = n.get("data", n)
        vt = nd.get("variable_type", "")
        src_tables = nd.get("source_tables", [])
        label = nd.get("label", "")
        if vt in ("table", "view", "cte", "subquery", "virtual_table",
                   "merge_target", "union_branch") and src_tables and len(src_tables) == 1:
            alias_map[label] = src_tables[0]
    # Also detect short lowercase aliases (typical SQL pattern)
    for n in nodes:
        nd = n.get("data", n)
        label = nd.get("label", "")
        vt = nd.get("variable_type", "")
        if vt in ("table", "view") and label and len(label) <= 3 and label.islower() and label.isalpha():
            # Find what this alias points to from edges
            for e in edges:
                ed = e.get("data", e)
                if ed.get("target") == nd.get("id") and ed.get("relationship") == "ALIAS":
                    for n2 in nodes:
                        n2d = n2.get("data", n2)
                        if n2d.get("id") == ed.get("source"):
                            alias_map[label] = n2d.get("label", "")
                            break

    # Classify each node
    for n in nodes:
        nd = n.get("data", n)
        nid = nd.get("id", "")
        label = nd.get("label", "")
        vt = nd.get("variable_type", "")
        src_tables = nd.get("source_tables", [])
        defined_in = (nd.get("defined_in") or "").upper()
        is_output_node = nd.get("is_output", False)

        if nid in seen_ids:
            continue
        seen_ids.add(nid)

        # ── Table-like nodes → compound parents ──
        if vt in ("table", "view", "cte", "subquery", "virtual_table",
                   "merge_target", "union_branch"):
            # Skip known aliases — they will be merged into their canonical table
            canonical = alias_map.get(label, label)
            if canonical != label:
                # This is an alias — remap to canonical table
                if canonical not in alias_map:
                    # Use canonical name; find or create its table node
                    pass  # handled below: fields will use canonical table
                continue  # skip creating a separate node for this alias

            tbl_id = f"l2_tbl_{hashlib.md5(nid.encode()).hexdigest()[:10]}"
            tbl_type = "cte_table" if vt == "cte" else (
                "output_table" if is_output_node and vt not in ("table", "view")
                else "intermediate_table")
            # If this is a source (read-only), mark as source_table
            if vt in ("table", "view") and not is_output_node:
                # Check if any node references this as source
                tbl_type = "source_table"

            table_nodes[nid] = {
                "id": tbl_id,
                "label": label,
                "type": tbl_type,
                "table_name": label,
                "variable_type": vt,
                "original_id": nid,
            }
            continue

        # ── Column-like nodes → field children ──
        if vt in ("column", "cte_column") or label.count(".") == 1:
            # Find parent table from source_tables or name prefix
            parent_table_id = None
            if src_tables and len(src_tables) == 1:
                # Resolve alias: map alias name to canonical table name
                resolved_src = alias_map.get(src_tables[0], src_tables[0])
                # Match to an existing table node
                for tid, tn in table_nodes.items():
                    if tn["table_name"] == resolved_src or tn["table_name"] == src_tables[0] or tid == src_tables[0]:
                        parent_table_id = tn["id"]
                        break
            if not parent_table_id and "." in label:
                prefix = label.split(".")[0]
                resolved_prefix = alias_map.get(prefix, prefix)
                for tid, tn in table_nodes.items():
                    if tn["table_name"] == resolved_prefix or tn["table_name"] == prefix:
                        parent_table_id = tn["id"]
                        break

            is_target = (nid in target_node_ids)
            is_direct = (nid in direct_ids)
            # Show orig type as a hint but use "field" for shape
            orig_vt = vt[:12] if len(vt) > 12 else vt
            field_id = f"fld_{hashlib.md5(nid.encode()).hexdigest()[:10]}"
            field_node = {
                "id": field_id,
                "label": (label.split(".")[-1] if "." in label else label) + (" ↻" if vt in ("aggregate","expression") else ""),
                "type": "field",
                "variable_type": "field",
                "orig_type": orig_vt,
                "is_target": is_target,
                "field_group": "direct" if is_direct else "indirect",
                "original_id": nid,
            }
            if parent_table_id:
                field_node["parent"] = parent_table_id
            field_nodes.append(field_node)
            continue

        # ── Expression/aggregate/window/computed nodes → field children ──
        if vt in ("expression", "aggregate", "window", "case", "transform", "literal"):
            # Find parent table from source_tables or fallback to any existing table
            parent_table_id = None
            if src_tables:
                for tid, tn in table_nodes.items():
                    if tn["table_name"] in src_tables or tid in src_tables:
                        parent_table_id = tn["id"]
                        break
            if not parent_table_id and table_nodes:
                # Fallback: attach to first table node
                parent_table_id = list(table_nodes.values())[0]["id"]
            
            is_target = (nid in target_node_ids)
            is_direct = (nid in direct_ids)
            orig_vt = vt[:12] if len(vt) > 12 else vt
            field_id = f"fld_{hashlib.md5(nid.encode()).hexdigest()[:10]}"
            field_node = {
                "id": field_id,
                "label": (label[:36] if len(label) > 36 else label) + " ↻",
                "type": "field",
                "variable_type": "field",
                "orig_type": orig_vt,
                "is_target": is_target,
                "field_group": "direct" if is_direct else "indirect",
                "original_id": nid,
            }
            if parent_table_id:
                field_node["parent"] = parent_table_id
            field_nodes.append(field_node)
            continue

        # Fallback: attach unknown node as field child to first available table
        if table_nodes:
            parent_table_id = list(table_nodes.values())[0]["id"]
            field_id = f"fld_{hashlib.md5(nid.encode()).hexdigest()[:10]}"
            field_nodes.append({
                "id": field_id,
                "label": (label[:36] if len(label) > 36 else label) + " ·",
                "type": "field",
                "variable_type": "field",
                "orig_type": (vt if vt else "unknown")[:12],
                "is_target": (nid in target_node_ids),
                "field_group": "indirect",
                "original_id": nid,
                "parent": parent_table_id,
            })



    # ── Build edge list with categories and sql_range ──
    # Map original IDs to new compound IDs
    id_map = {}
    for tn in table_nodes.values():
        id_map[tn["original_id"]] = tn["id"]
    for fn in field_nodes:
        id_map[fn["original_id"]] = fn["id"]
    for on in other_nodes:
        id_map[on["original_id"]] = on["id"]
    # ── Also map alias original IDs to canonical table node IDs ──
    # Aliases were skipped during node creation, but edges still reference them.
    # Find the canonical table for each alias and map the alias original_id → canonical table id.
    for n in nodes:
        nd = n.get("data", n)
        nid = nd.get("id", "")
        label = nd.get("label", "")
        if label in alias_map and nid not in id_map:
            canonical_name = alias_map[label]
            # Find the canonical table node
            for tn in table_nodes.values():
                if tn["table_name"] == canonical_name:
                    id_map[nid] = tn["id"]
                    break

    new_edges = []
    lines = sql_text.split("\n") if sql_text else []

    # Build label lookup from nodes for richer edge metadata
    node_labels = {}
    for n in nodes:
        nd = n.get("data", n)
        node_labels[nd.get("id", "")] = nd.get("label", "")

    for e in edges:
        ed = e.get("data", e)
        src_orig = ed.get("source", "")
        tgt_orig = ed.get("target", "")
        rel = ed.get("relationship", "") or ed.get("edge_type", "")
        edge_type = rel if rel else "REF"

        src_new = id_map.get(src_orig, src_orig)
        tgt_new = id_map.get(tgt_orig, tgt_orig)

        if src_new == tgt_new:
            continue  # skip self-loops from ID mapping

        category = _get_category(edge_type)
        style = _get_edge_style(edge_type)

        # Enrich with source/target labels for better SQL matching
        src_label = node_labels.get(src_orig, "")
        tgt_label = node_labels.get(tgt_orig, "")
        enriched = dict(ed)
        enriched["source_label"] = src_label
        enriched["target_label"] = tgt_label
        enriched["edge_type"] = edge_type   # 🔧 Bug 4 fix: edge_type was missing from enriched

        # P1: Try to find a line number for the target label in SQL
        # line_num propagation: only for edge types that benefit from label search
        # Keyword-matching types (FILTER, JOIN, DML, etc.) find lines via KeywordLocator
        # not label search, so skip override to avoid corrupting their line detection.
        keyword_match_types = {'FILTER', 'WHERE', 'HAVING', 'JOIN', 'GROUP_BY', 'ORDER_BY',
                              'DML', 'CTE', 'CREATE', 'ALTER', 'DROP', 'SCHEMA', 'AGGREGATE',
                              'WINDOW', 'TRANSFORM', 'CASE', 'COMPUTED', 'SUBQUERY',
                              'SUBSET', 'ALIAS', 'INDIRECT', 'REF', 'CORRELATED'}
        if tgt_label and lines and edge_type not in keyword_match_types:
            tgt_clean = tgt_label.split('.')[-1].strip().lower()
            if len(tgt_clean) > 2 and tgt_clean not in ('select','from','where','insert','into','values','join','table'):
                for i, line in enumerate(lines):
                    if tgt_clean in line.lower():
                        enriched["line_num"] = i + 1  # 1-based
                        break

        # Bug 3 fix: split compound edge types, each gets own sql_range
        etypes = [t.strip() for t in edge_type.split(",")] if "," in edge_type else [edge_type]
        # For compound types: emit one edge per individual type, each with own range/style
        if len(etypes) > 1:
            for et in etypes:
                enriched_copy = dict(enriched)
                enriched_copy["edge_type"] = et
                r = find_sql_range(enriched_copy, sql_text)
                if not r:
                    r = find_sql_range(enriched, sql_text)  # fallback
                et_style = EDGE_TYPE_STYLE.get(et, EDGE_TYPE_STYLE["SUBSET"])
                et_category = CATEGORY_MAP.get(et, "structure")
                new_edges.append({
                    "id": f"l2e_{hashlib.md5(f'{src_new}{tgt_new}{et}'.encode()).hexdigest()[:12]}",
                    "source": src_new,
                    "target": tgt_new,
                    "edge_type": et,
                    "category": et_category,
                    "color": et_style["color"],
                    "label": et,
                    "line_style": et_style["line"],
                    "width": et_style["width"],
                    "desc": et_style["desc"],
                    "sql_range": r,
                })
        else:
            sql_range = find_sql_range(enriched, sql_text)
            new_edges.append({
                "id": f"l2e_{hashlib.md5(f'{src_new}{tgt_new}{edge_type}'.encode()).hexdigest()[:12]}",
                "source": src_new,
                "target": tgt_new,
                "edge_type": edge_type,
                "category": category,
                "color": style["color"],
                "label": edge_type,
                "line_style": style["line"],
                "width": style["width"],
                "desc": style["desc"],
                "sql_range": sql_range,
            })

    # ── Edge combining: same (source,target,edge_type) → combine labels/sql_ranges ──
    combined_edges = {}
    for e in new_edges:
        key = (e["source"], e["target"], e["edge_type"])
        if key in combined_edges:
            existing = combined_edges[key]
            # Combine labels
            existing_labels = set(existing.get("label", "").split(", "))
            existing_labels.add(e.get("label", ""))
            existing["label"] = ", ".join(sorted(existing_labels))
            # Keep shortest non-zero sql_range (most specific)
            if e.get("sql_range") and not existing.get("sql_range"):
                existing["sql_range"] = e["sql_range"]
            elif e.get("sql_range") and existing.get("sql_range"):
                er = existing["sql_range"]
                nr = e["sql_range"]
                if len(er) >= 4 and len(nr) >= 4:
                    elen = max(1, er[2] - er[0]) if er[2] > er[0] else 999
                    nlen = max(1, nr[2] - nr[0]) if nr[2] > nr[0] else 999
                    if nlen < elen:
                        existing["sql_range"] = nr
        else:
            combined_edges[key] = e
    new_edges = list(combined_edges.values())

    # ── Promote field-level edges to table level ──
    # L2 graph should show data flow between tables, not individual fields.
    # Fields are shown as children of compound table nodes.
    # Edges with field sources/targets are promoted to their parent tables.
    # SCHEMA edges (table→field ownership) are removed since ownership is
    # implicit in the compound node structure.
    field_parents = {}
    for fn in field_nodes:
        pid = fn.get("parent")
        if pid:
            field_parents[fn["id"]] = pid

    # V3.3.65: Promote fields→tables, keep edges separate per type.
    # Each edge type gets its own edge with its own sql_range.
    # No compound merging — clicking different edge types shows different SQL.
    promoted = []
    for e in new_edges:
        src = e["source"]
        tgt = e["target"]
        etype = e["edge_type"]

        if etype == "SCHEMA":
            continue
        if src in field_parents:
            src = field_parents[src]
        if tgt in field_parents:
            tgt = field_parents[tgt]
        if src == tgt:
            continue

        e["source"] = src
        e["target"] = tgt
        if e.get("sql_range"):
            e["sql_ranges"] = {etype: e["sql_range"]}
        promoted.append(e)

    new_edges = promoted

    # ── Simplification 1: DML edges route through ⟐ output (intermediate_table) ──
    # Instead of creating synthetic qo_ nodes, use the existing intermediate_table
    # ("⟐ output") node that already represents the SELECT result set.
    # This eliminates 4 regression-prone patches: qo_ creation, dedup, repointing, self-loop removal.
    #
    # Before: raw_orders ──[DML]──> stg_orders
    # After:  raw_orders ──[TABLE_FLOW]──> ⟐ output ──[TABLE_FLOW]──> stg_orders
    #
    # All intermediate operations (TRANSFORM, AGGREGATE, FILTER, JOIN, etc.) connect to ⟐ output,
    # not directly to the DML target. The output node is the trunk of the data flow.
    intermediate_id = None
    for tn in table_nodes.values():
        if isinstance(tn, dict) and tn.get("type") == "intermediate_table":
            intermediate_id = tn.get("id")
            break

    # Collect DML target tables and DML source→target pairs
    dml_targets = set()
    dml_sources = set()
    dml_pairs = set()  # (source, target) pairs from DML edges
    for e in new_edges:
        if "DML" in e.get("edge_type", "").upper():
            dml_targets.add(e.get("target", ""))
            dml_sources.add(e.get("source", ""))
            dml_pairs.add((e.get("source", ""), e.get("target", "")))

    new_dml_edges = []
    for e in new_edges:
        etype = e.get("edge_type", "")
        src = e.get("source", "")
        tgt = e.get("target", "")
        # 1. Suppress TABLE_FLOW bypass edges (replaced by source→⟐→target chain)
        if (src in dml_sources and tgt in dml_targets
            and etype == "TABLE_FLOW"
            and src != intermediate_id and tgt != intermediate_id):
            continue
        # 2. Redirect non-DML bypass edges to ⟐ output (TRANSFORM, AGGREGATE, etc.)
        if (src in dml_sources and tgt in dml_targets
            and "DML" not in etype.upper()
            and etype != "TABLE_FLOW"
            and src != intermediate_id and tgt != intermediate_id
            and intermediate_id):
            e["target"] = intermediate_id
            new_dml_edges.append(e)
            continue
        # 3. Replace DML edges with ⟐ output → target (TABLE_FLOW)
        if "DML" in etype.upper() and intermediate_id:
            output_edge = dict(e)
            output_edge["id"] = f"{e['id']}_dml_out"
            output_edge["source"] = intermediate_id
            output_edge["edge_type"] = "TABLE_FLOW"
            output_edge["label"] = "TABLE_FLOW"
            if output_edge.get("sql_ranges"):
                tf_range = output_edge["sql_ranges"].get("TABLE_FLOW", output_edge.get("sql_range"))
                output_edge["sql_ranges"] = {"TABLE_FLOW": tf_range}
                output_edge["sql_range"] = tf_range
            new_dml_edges.append(output_edge)
        else:
            new_dml_edges.append(e)
    new_edges = new_dml_edges

    # ── Dedup: merge edges with same (source,target,type) ──
    deduped = {}
    for e in new_edges:
        key = (e.get("source"), e.get("target"), e.get("edge_type"))
        if key in deduped:
            ex = deduped[key]
            er = ex.get("sql_range"); nr = e.get("sql_range")
            if nr and (not er or (len(er)>=4 and len(nr)>=4 and (nr[2]-nr[0])<(er[2]-er[0]))):
                ex["sql_range"] = nr
            sr = ex.get("sql_ranges", {})
            sr.update(e.get("sql_ranges", {}))
            ex["sql_ranges"] = sr
        else:
            deduped[key] = e
    new_edges = list(deduped.values())

    # ── Assemble output (only table+field compound nodes) ──
    all_new_nodes = (
        [{"data": tn} for tn in table_nodes.values()] +
        [{"data": fn} for fn in field_nodes]
    )

    # Partition pass: reduce edge range overlap so edges form a near-partition
    from app.services.sql_range_finder import partition_edge_ranges
    if new_edges:
        edge_dicts = [e for e in new_edges]  # new_edges are plain dicts
        partition_edge_ranges(edge_dicts, len(sql_text.split('\n')))
        new_edges = edge_dicts

    total_edges = len(new_edges)
    return {
        "nodes": all_new_nodes,
        "edges": [{"data": e} for e in new_edges],
        "script_name": script_name,
        "total_nodes": len(nodes),
        "filtered_nodes": len(all_new_nodes),
        "total_edges": total_edges,
        "target": target_full,
    }


def _estimate_sql_range(edge_data: dict, lines: list) -> list | None:
    """Estimate SQL line/column range from edge metadata.

    Returns [start_line, start_col, end_line, end_col] or None.
    Strategy (in order):
      1) Explicit line_num if present
      2) defined_in context match
      3) Edge-type→SQL-keyword mapping (with statement extension)
      4) Source/target label search (variable/table names)
      5) Ultimate fallback: return full script range
    """
    import re as _re

    if not lines:
        return None

    def _extend_to_statement(line_idx: int) -> list:
        """Extend from a matched line to the full SQL statement boundaries."""
        start_line = line_idx
        end_line = line_idx
        # Extend backward to statement start (look for SELECT, WITH, INSERT, etc.)
        # Statement-level keywords: start entirely NEW statements
        # These correctly stop backward extension.
        # NOTE: SELECT is NOT in this list because it can be part of INSERT...SELECT.
        # Only keywords that DEFINITELY start a new top-level statement stop backward.
        STMT_START_KW = ('WITH', 'INSERT', 'UPDATE', 'DELETE', 'MERGE', 'CREATE',
                         'ALTER', 'DROP', 'TRUNCATE', 'UNION')
        # Forward: after blank line, only statement-start keywords indicate new statement.
        # Clause-level keywords (FROM, JOIN, etc.) within a statement are continuation lines.
        while start_line > 0:
            prev_raw = lines[start_line - 1].strip()
            prev = prev_raw.upper()
            if not prev or prev.startswith('--'):
                break
            # CTE boundary: ) pattern that closes a CTE definition in a WITH chain.
            # Matches patterns like:
            #   ),           — comma-separated CTE boundary  
            #   ), cte2 AS   — next CTE follows immediately
            #   )            — standalone closing paren (CTE end)
            # Avoid extending into a previous CTE's body.
            if prev.startswith(')') and (
                len(prev) <= 3 or          # ')' or '),'
                prev.startswith('),')      # '), cte_name ...'
            ):
                break
            # Also detect ), at end of line: e.g. '...sq1),'
            if prev_raw.rstrip().endswith('),'):
                break
            # Backward: only stop at true statement starts (not clause keywords)
            if any(prev.startswith(kw) for kw in STMT_START_KW):
                start_line -= 1  # include the statement-start line itself
                break
            start_line -= 1
        # Extend forward to statement end (semicolon or blank line followed by new statement)
        while end_line < len(lines) - 1:
            nxt_raw = lines[end_line + 1].strip()
            nxt = nxt_raw.upper()
            if not nxt or nxt.startswith('--'):
                # Check if the line after blank/comment starts a new statement
                if end_line + 2 < len(lines):
                    after = lines[end_line + 2].strip().upper()
                    # Only stop at statement-level keywords (include SELECT here
                    # because after a blank line, SELECT definitely starts new stmt)
                    FWD_KW = STMT_START_KW + ('SELECT',)
                    if any(after.startswith(kw) for kw in FWD_KW):
                        break
                else:
                    break
            # CTE boundary: ),  pattern that closes this CTE and starts the next one.
            # When we see ),  we've reached the end of the current CTE definition.
            if nxt.startswith(')') and (
                len(nxt) <= 3 or          # ')' or '),'
                nxt.startswith('),')      # '), cte_name ...'
            ):
                break
            # Also detect ), at end of line: e.g. '...sq1),'
            if nxt_raw.rstrip().endswith('),'):
                break
            end_line += 1
            if nxt_raw.rstrip().endswith(';'):
                break
        # Cap range to max 50 lines for deeply nested CTE chains
        range_len = end_line - start_line + 1
        if range_len > 50:
            end_line = start_line + 49  # cap at 50 lines
            if end_line >= len(lines):
                end_line = len(lines) - 1
        return [start_line + 1, 1, end_line + 1, len(lines[end_line])]

    # 1) Explicit line number
    line_num = edge_data.get("line_num") or edge_data.get("line_number") or edge_data.get("line")
    if line_num is not None:
        try:
            ln = int(line_num) - 1  # convert to 0-based
            if 0 <= ln < len(lines):
                return _extend_to_statement(ln)
        except (ValueError, TypeError):
            pass

    # 2) defined_in context
    defined_in = (edge_data.get("defined_in") or "").upper()
    if defined_in:
        for i, line in enumerate(lines):
            if defined_in in line.upper():
                return _extend_to_statement(i)

    edge_type = (edge_data.get("edge_type") or edge_data.get("relationship") or "").upper()
    label = edge_data.get("label", "")
    src_label = (edge_data.get("source_label") or "")
    tgt_label = (edge_data.get("target_label") or "")

    # 3) Edge-type→SQL-keyword mapping — try each type in priority order
    # Split compound types like "JOIN,FILTER" into individual types
    _SQL_KEYWORDS = {
        "JOIN":     [r"\b(LEFT|RIGHT|INNER|OUTER|CROSS|FULL)?\s*JOIN\b"],
        "FILTER":   [r"\bWHERE\b", r"\bHAVING\b"],
        "WHERE":    [r"\bWHERE\b"],
        "GROUP_BY": [r"\bGROUP\s+BY\b"],
        "ORDER_BY": [r"\bORDER\s+BY\b"],
        "AGGREGATE":[r"\b(SUM|COUNT|AVG|MIN|MAX|ROW_NUMBER|RANK|DENSE_RANK|LAG|LEAD)\s*\("],
        "UNION":    [r"\bUNION\b"],
        "DML":      [r"\bINSERT\s+(INTO\s+)?", r"\bUPDATE\s+", r"\bDELETE\s+FROM\s+",
                      r"\bMERGE\s+INTO\s+"],
        "TRANSFORM":[r"\b(CAST|COALESCE|CONCAT|SUBSTR|SUBSTRING|TRIM|UPPER|LOWER|IFNULL|NVL|NULLIF|COALESCE)\s*\("],
        "CASE":     [r"\bCASE\b"],
        "CTE":      [r"\bWITH\b"],
        "CREATE":   [r"\bCREATE\s+(TABLE|VIEW|TEMP)"],
        "INDIRECT":   [
            r"\bHAVING\b",                       # indirect ref often in HAVING
            r"\bWHERE\b",                        # correlated subquery in WHERE
        ],
        "SUBSET":     [
            r"\bWHERE\b",                        # WHERE filters to subset
            r"\bHAVING\b",                       # HAVING filters aggregates
        ],
        "TABLE_FLOW":[
            r"\bINSERT\s+INTO\b.*\bSELECT\b", # INSERT...SELECT pattern
            r"\bFROM\b",                          # FROM for simple SELECT
        ],
        "ALIAS":    [
            r"\bAS\s+\w+",                       # explicit AS alias
            r"\bFROM\s+\w+\s+\w+",            # implicit alias: FROM table alias
            r"\bJOIN\s+\w+\s+\w+",            # implicit alias: JOIN table alias
        ],
        "SCHEMA":   [
            r"\bCREATE\s+(TABLE|VIEW|TEMP)\b",  # schema definition
            r"\bALTER\s+(TABLE|VIEW)\b",        # schema alteration
            r"\bDROP\s+(TABLE|VIEW)\b",         # schema removal
        ],
        "REF":      [
            # Keyword matching too generic for REF — rely on
            # dynamic source/target label patterns added below
        ],
        "SUBQUERY": [r"\bSELECT\b"],
        "COMPUTED": [r"\b(SELECT|SET|CASE|COALESCE|CAST|CONCAT)\b"],
        "WINDOW":   [r"\b(OVER|PARTITION\s+BY|ROW_NUMBER|RANK|DENSE_RANK|LAG|LEAD)\b"],
        "CORRELATED": [r"\bEXISTS\b", r"\bIN\s*\("],
    }

    # Split compound edge types (JOIN,FILTER) — try each in priority order
    edge_types_to_try = [t.strip() for t in edge_type.split(',')] if edge_type else []
    edge_types_to_try.append(label.upper())  # also try label as fallback
    
    all_keywords = []
    for et in edge_types_to_try:
        kws = _SQL_KEYWORDS.get(et, [])
        if kws:
            all_keywords.extend(kws)
    
    if not all_keywords:
        all_keywords = _SQL_KEYWORDS.get(label.upper(), [])
    
    # V3.3.13: Dynamically add source/target label patterns for TABLE_FLOW and REF.
    # Generic keywords (FROM, SELECT, WHERE) match too broadly. Using the actual
    # table/column names from the edge labels makes matching specific.
    dynamic_patterns = []
    if "TABLE_FLOW" in edge_types_to_try or "TABLE_FLOW" in (label.upper(),):
        # Use target label as table name pattern
        for lbl in (tgt_label, src_label):
            if lbl and len(lbl) > 2:
                clean = lbl.strip().split(".")[-1].strip()  # take last part after dot
                if clean:
                    dynamic_patterns.append(r"\b" + re.escape(clean) + r"\b")
    if "REF" in edge_types_to_try or "REF" in (label.upper(),):
        # Use source label as column name pattern
        for lbl in (src_label, tgt_label):
            if lbl and len(lbl) > 2:
                for part in lbl.split(","):
                    clean = part.strip().split(".")[-1].strip()
                    if clean:
                        dynamic_patterns.append(r"\b" + re.escape(clean) + r"\b")
    
    keywords = all_keywords + dynamic_patterns

    for pat in keywords:
        try:
            for i, line in enumerate(lines):
                stripped = line.strip()
                # Skip comment-only lines
                if stripped.startswith('--'):
                    continue
                if _re.search(pat, line, _re.IGNORECASE):
                    return _extend_to_statement(i)
        except Exception:
            continue

    # 4) Search SQL for source/target labels (variable/table names)
    # Strip dots: "stg_orders.order_id" → search for "order_id" and "stg_orders"
    search_terms = []
    for lbl in (src_label, tgt_label, label):
        if not lbl:
            continue
        # Handle comma-separated compound labels
        for part_label in lbl.split(","):
            clean = part_label.strip().split(".")[0].strip()  # take first part before dot
            if clean and len(clean) > 2:
                search_terms.append(clean)
            # If dotted, add each part
            if "." in part_label.strip():
                for part in part_label.strip().split("."):
                    if len(part.strip()) > 1:
                        search_terms.append(part.strip())

    # Remove duplicates, sort by length descending (more specific first)
    search_terms = sorted(set(t.lower() for t in search_terms), key=len, reverse=True)

    # Score all lines by how many search terms they match
    # PLUS context bonus: some edge types prefer certain SQL contexts
    best_score = 0
    best_line = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('--'):
            continue
        score = 0
        uline = line.upper()
        # Base score: how many search terms appear
        for term in search_terms:
            if term in ("select", "from", "where", "insert", "into", "values", "join", "table"):
                continue
            if term in line.lower():
                score += 2  # each matching term = 2 points
        # Context bonus: weight lines higher based on edge type context
        if edge_type in ("REF", "COMPUTED", "TRANSFORM"):
            if "SELECT" in uline:
                score += 3  # REF prefers SELECT lines
        elif edge_type == "ALIAS":
            if "FROM" in uline or "JOIN" in uline:
                score += 3  # ALIAS prefers FROM/JOIN lines
        elif edge_type == "TABLE_FLOW":
            if "INSERT" in uline or "INTO" in uline:
                score += 3  # TABLE_FLOW prefers INSERT/INTO lines
        elif edge_type == "SCHEMA":
            if "CREATE" in uline or "ALTER" in uline or "DROP" in uline:
                score += 3  # SCHEMA prefers DDL lines
        elif edge_type == "SUBSET":
            if "WHERE" in uline or "HAVING" in uline:
                score += 3  # SUBSET prefers filter lines
        if score > best_score:
            best_score = score
            best_line = i
    
    if best_line is not None:
        return _extend_to_statement(best_line)

    # 5) Ultimate fallback: return the first substantive line range
    # Try to find FROM/SELECT line
    for i, line in enumerate(lines):
        uline = line.upper().strip()
        if not uline or uline.startswith('--'):
            continue
        if "FROM " in uline or "SELECT " in uline:
            return _extend_to_statement(i)

    # Last resort: return full script range so user sees something
    if lines:
        return [1, 1, len(lines), len(lines[-1])]

    return None


def target_field_sc(sc: str, target_field: str) -> bool:
    """Check if source_column matches target_field."""
    import re
    return bool(re.search(rf'\b{re.escape(target_field)}\b', sc))
