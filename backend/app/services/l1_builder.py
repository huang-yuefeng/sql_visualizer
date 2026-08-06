"""L1 Graph Builder — cross-script pipeline graph construction.

Extracted from dataflow_service.py per ARCHITECTURE_REVIEW S3.
Builds L1 pipeline view: scripts + tables + reads_from/writes_to edges.
"""
import json
import uuid
import hashlib
import logging
import traceback

from app.services.workspace_service import get_workspace_dir
from app.extractor.lineage import compute_field_lineage, PRODUCTION_EDGES
from app.services.logger import _push

_log = logging.getLogger("sql_visualizer.dataflow")

# ── L1 helper functions ──────────────────────────────────────────────

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
                # B2/CW9: exact field-part semantics — a bare word-boundary
                # regex matched the alias/table part too (target_field="item"
                # vs "item.i_brand"), attributing roles for the wrong field.
                sc_field = sc.rsplit(".", 1)[-1] if "." in sc else sc
                if target_full in sc or sc_field == target_field:
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


def _extract_table_field_pairs(lineage_set: set, nodes: list,
                               alias_map: dict,
                               valid_table_fields: set | None = None,
                               skip_virtual: bool = False) -> set:
    """Collect (table_name, field_name) pairs from lineage nodes.

    Only nodes whose id is in lineage_set. Table/field taken from
    table_name/field_name, falling back to the label's "table.field"
    suffix split when either is missing. Alias prefixes are resolved
    via alias_map. When valid_table_fields is not None, pairs are
    validated against it (exact match to the current loops' behavior:
    an empty set means no validation). skip_virtual drops pairs whose
    (resolved) table name starts with the virtual-table marker ⟐.
    """
    pairs = set()
    for n in nodes:
        nd = n.get("data", n)
        if nd.get("id") not in lineage_set:
            continue
        tn = nd.get("table_name", "")
        fn = nd.get("field_name", "")
        if not tn or not fn:
            label = nd.get("label", "")
            if "." in label:
                parts = label.rsplit(".", 1)
                tn = tn or parts[0]
                fn = fn or parts[1]
        if not (tn and fn):
            continue
        tn = alias_map.get(tn, tn)
        if valid_table_fields is not None and (tn, fn) not in valid_table_fields:
            continue
        if skip_virtual and tn.startswith("⟐"):
            continue
        pairs.add((tn, fn))
    return pairs


def _push_l1_degraded(ws_id: str, table: str, field: str,
                      script_names: list[str], exc: Exception) -> None:
    """M4-B: emit an L1-degraded diagnostic block via the `_push` "profile"
    channel (same mechanism as the R16/R17 blocks) — the LogPanel shows why
    the script-only fallback was returned instead of a full pipeline graph.
    """
    W = 80
    lines = ["┌─ L1 GRAPH DEGRADED " + "─" * (W - len("┌─ L1 GRAPH DEGRADED ") - 1) + "┐"]
    lines.append(("│ target: %s.%s  scripts: %d" % (table, field, len(script_names)))
                 .ljust(W - 1) + "│")
    lines.append(("│ script-only fallback returned — L1 build failed:"
                  ).ljust(W - 1) + "│")
    msg = ("│ %s" % exc).strip()[:72]
    lines.append(msg.ljust(W - 1) + "│")
    lines.append("└" + "─" * (W - 2) + "┘")
    for line in lines:
        _push(ws_id, "profile", line)


def _build_l1_graph(ws_id: str, script_names: list[str],
                    table: str, field: str) -> dict:
    """Build Level 1 cross-script pipeline graph.

    Nodes: source tables (blue rect), scripts (orange rounded-rect),
           intermediate tables (gray rect), output tables (green rect).
    Edges: undirected table↔script per formal §5.1: (s,t) ∈ E iff s uses t, with role badges for target var.
    """
    if len(script_names) < 1:
        return {"nodes": [], "edges": [], "target": f"{table}.{field}",
                "degraded": False}

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
        return {"nodes": nodes, "edges": [], "target": f"{table}.{field}",
                "degraded": False}

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
                except Exception as exc:
                    _log.warning("L1: failed to read analysis cache %s: %s",
                                 af_path.name, exc)

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

        # ── Pattern 1 fix (Bug 47+39): Single P4-based extraction ──
        # Instead of three independent passes with diverging fallbacks,
        # build all_table_fields once from SCHEMA + DML edges across all
        # scripts, then use it as single source of truth.
        # (PRODUCTION_EDGES imported from app.extractor.lineage at module level)

        # C2: single disk-cache pass — absorb the pre-built P4 table_fields
        # and P5 alias_map from each graph cache (Bug 48). The former two
        # passes (alias scan, table_fields scan) re-read the same files;
        # one read now feeds both structures.
        global_alias_map = {}
        all_table_fields = set()

        def _absorb_p4(gdata: dict) -> None:
            """Merge the pre-built P4 table_fields + P5 alias_map from one
            graph data dict (disk cache or on-the-fly graph data)."""
            g_alias = gdata.get("alias_map", {})
            if g_alias:
                global_alias_map.update(g_alias)
            for tbl, flds in gdata.get("table_fields", {}).items():
                for fn in flds:
                    all_table_fields.add((tbl, fn))

        if cache_dir.exists():
            for gc_path in sorted(cache_dir.glob("graph_*.json")):
                try:
                    gdata = json.loads(gc_path.read_text())
                    # CW7: normalize edge_type on cache read (cache stores "relationship")
                    for _e in gdata.get("edges", []):
                        _ed = _e.get("data", _e)
                        _ed.setdefault("edge_type", _ed.get("relationship", "REF"))
                    # Item 4: cache format versioning — warn once per stale cache file
                    if gdata.get("format_version") != 3:
                        logging.getLogger("sql_visualizer.dataflow").warning(
                            "L1 cache %s has format_version=%r (expected 3) — stale graph cache",
                            gc_path.name, gdata.get("format_version"))
                    _absorb_p4(gdata)
                except Exception as exc:
                    _log.warning("L1: failed to read graph cache %s: %s",
                                 gc_path.name, exc)
        # Fallback to analysis caches if no graph caches have alias_map
        if not global_alias_map and cache_dir.exists():
            for af_path in sorted(cache_dir.glob("analysis_*.json")):
                try:
                    adata = json.loads(af_path.read_text())
                    for v in adata.get("variables", []):
                        vt = v.get("variable_type", "")
                        name = v.get("name", "")
                        src_tables = v.get("source_tables", [])
                        if vt in ("table",) and src_tables:
                            global_alias_map[name] = src_tables[0]
                except Exception as exc:
                    _log.warning("L1: failed to read analysis cache %s: %s",
                                 af_path.name, exc)

        # C2: absorb P4/P5 from each script's own graph data (on-the-fly
        # analyze_multiple_scripts output — build_graph_data carries both),
        # so the P1 validation also works before any graph cache is written
        # (fresh workspaces with no disk cache yet).
        for s in all_scripts:
            _absorb_p4(s.get("graph", {}) or {})

        # Single extraction: run compute_field_lineage per script,
        # intersect reached nodes with all_table_fields
        lineage_field_pairs = set()
        for s in all_scripts:
            gdata = s.get("graph", {})
            if not gdata or not gdata.get("nodes"):
                continue
            try:
                # G2/Bug 37 (pinned): this constrained union — production
                # edges plus SCHEMA — is the shared L1/L2 BFS semantics from
                # the single unified engine (app/extractor/lineage.py,
                # EDGE_SEMANTICS). SCHEMA: reverse (column→table) always
                # follows, forward (table→column) is production-filtered.
                lineage_set = compute_field_lineage(gdata, table, field,
                                                    edge_filter=PRODUCTION_EDGES | {"SCHEMA"})
            except Exception as exc:
                _log.error("compute_field_lineage failed for %s.%s: %s",
                           table, field, exc, exc_info=True)
                continue
            # CW3: shared pair extraction — P1 validation + virtual-table skip
            lineage_field_pairs |= _extract_table_field_pairs(
                lineage_set, gdata.get("nodes", []), global_alias_map,
                valid_table_fields=all_table_fields or None,
                skip_virtual=True)

        # Always include target field
        lineage_field_pairs.add((table, field))

        # Multi-hop expansion (Bug 40) — iterate until stable
        _already_expanded = set()
        round_num = 0
        while round_num < 10:
            round_num += 1
            added = False
            for (tn, fn) in list(lineage_field_pairs):
                if (tn, fn) in _already_expanded:
                    continue
                _already_expanded.add((tn, fn))
                for s in all_scripts:
                    gdata = s.get("graph", {})
                    if not gdata or not gdata.get("nodes"):
                        continue
                    try:
                        lineage_set = compute_field_lineage(gdata, tn, fn,
                                                            edge_filter=PRODUCTION_EDGES | {"SCHEMA"})
                    except Exception as exc:
                        _log.error("compute_field_lineage failed for %s.%s: %s",
                                   tn, fn, exc, exc_info=True)
                        continue
                    # CW3: shared pair extraction — P1 validation, no virtual-table skip
                    for pair in _extract_table_field_pairs(
                            lineage_set, gdata.get("nodes", []),
                            global_alias_map,
                            valid_table_fields=all_table_fields or None):
                        if pair not in lineage_field_pairs:
                            lineage_field_pairs.add(pair)
                            added = True
            if not added:
                break

        return {
            "nodes": nodes,
            "edges": edges,
            "target": f"{table}.{field}",
            "source_tables": source_tables,
            "intermediate_tables": intermediate_tables,
            "output_tables": output_tables,
            "script_count": len(all_scripts),
            "lineage_field_pairs": [list(p) for p in lineage_field_pairs],
            # M4-B: stable frontend contract — `degraded` is always present.
            "degraded": False,
        }
    except Exception as exc:
        # M4-B: the degraded fallback must be VISIBLE, not a silent success —
        # flag the response and emit an L1 diagnostic (same `_push` "profile"
        # mechanism as the R16/R17 blocks) so the LogPanel shows the failure
        # while the script-only graph still keeps the UI usable.
        import traceback
        traceback.print_exc()
        nodes = []
        for name in script_names:
            sid = hashlib.md5(name.encode()).hexdigest()[:12]
            nodes.append({"data": {"id": sid, "label": name, "type": "script_node", "script_name": name}})
        try:
            _log.error("L1: degraded fallback for %s.%s (%d scripts): %s",
                       table, field, len(script_names), exc)
            _push_l1_degraded(ws_id, table, field, script_names, exc)
        except Exception:
            pass  # diagnostics must never break the response path
        return {"nodes": nodes, "edges": [], "target": f"{table}.{field}",
                "degraded": True}





