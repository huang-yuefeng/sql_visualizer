"""L2 Graph Builder — per-script detail graph construction.

Extracted from dataflow_service.py per ARCHITECTURE_REVIEW S3.
Builds L2 detail view: tables + fields + all 16 edge types for a single script.
"""
import json
import hashlib
from pathlib import Path

from app.services.workspace_service import get_workspace_dir
from app.extractor.adapter import run_full_analysis
from app.services.graph_service import (
    build_graph_data,
    get_edge_style as _get_edge_style,
    get_category as _get_category,
    get_category_color as _get_category_color,
    EDGE_TYPE_STYLE,
    CATEGORY_MAP,
)
from app.services.logger import api_request, stage_graph
from app.extractor.schema_inference import infer_table_schemas
from app.extractor.lineage import filter_relevant
from app.services.sql_range_finder import partition_edge_ranges
from app.services.sql_range_finder import find_sql_range

# ── L2 helper functions ──────────────────────────────────────────────

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
    schemas_cache_path = cache_dir / f"schemas_{cache_key}.json"
    if graph_cache_path.exists():
        full_graph = json.loads(graph_cache_path.read_text())
        stage_graph(len(full_graph.get('nodes',[])), len(full_graph.get('edges',[])), ws_id=ws_id)
        # Bug 25: load cached table_schemas on cache hit
        _table_schemas = None
        if schemas_cache_path.exists():
            _table_schemas = json.loads(schemas_cache_path.read_text())
    else:
        result = run_full_analysis(sql_text, script_name, ws_id=ws_id)
        full_graph = build_graph_data(result)
        # Cache for future use
        cache_dir.mkdir(parents=True, exist_ok=True)
        graph_cache_path.write_text(json.dumps(full_graph, default=str))
        # R18: build table_schemas for lineage seed validation
        _table_schemas = infer_table_schemas(
            result.get("variables", []), result.get("dependencies", []))
        # Bug 25: cache table_schemas alongside graph
        schemas_cache_path.write_text(json.dumps(_table_schemas, default=str))

    # Apply relevance filter if requested
    if relevance_filter:
        graph_data = filter_relevant(full_graph, table, field, table_schemas=_table_schemas)
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
            # Bug 28: Keep aliases as visible compound nodes
            # Aliases carry fields and show the data flow explicitly:
            #   canonical_table --ALIAS--> alias (with fields) --DML--> target_table
            is_alias = (label in alias_map and alias_map[label] != label)
            tbl_id = f"l2_tbl_{hashlib.md5(nid.encode()).hexdigest()[:10]}"
            if is_alias:
                tbl_type = "alias_table"
            elif vt == "cte":
                tbl_type = "cte_table"
            elif is_output_node and vt not in ("table", "view"):
                tbl_type = "output_table"
            elif vt in ("table", "view") and not is_output_node:
                tbl_type = "source_table"
            else:
                tbl_type = "intermediate_table"

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
                # Bug 28: Match source table name directly (aliases are now visible nodes)
                # Try exact match first, then try canonical name if this is an alias
                src_name = src_tables[0]
                for tid, tn in table_nodes.items():
                    if tn["table_name"] == src_name or tid == src_tables[0]:
                        parent_table_id = tn["id"]
                        break
                if not parent_table_id:
                    resolved = alias_map.get(src_tables[0], src_tables[0])
                    for tid, tn in table_nodes.items():
                        if tn["table_name"] == resolved:
                            parent_table_id = tn["id"]
                            break
            if not parent_table_id and "." in label:
                prefix = label.split(".")[0]
                # Bug 28: Try prefix directly (aliases are now visible nodes)
                for tid, tn in table_nodes.items():
                    if tn["table_name"] == prefix:
                        parent_table_id = tn["id"]
                        break
                if not parent_table_id:
                    resolved_prefix = alias_map.get(prefix, prefix)
                    for tid, tn in table_nodes.items():
                        if tn["table_name"] == resolved_prefix:
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

    # Bug 45 (Pattern 2): JOIN edge survival pass.
    # Build node_by_id for JOIN survival pass
    node_by_id = {}
    for tn_id, tn in table_nodes.items():
        node_by_id[tn_id] = tn
    for fn in field_nodes:
        node_by_id[fn["id"]] = fn

    # filter_relevant() removes JOIN edges because JOIN is conditional (both ends
    # need a production path). But JOIN edges are semantically valuable — they show
    # table relationships even without value flow. After promotion, re-add JOIN
    # edges from the full graph that connect tables in the current L2 graph.
    seen_join_keys = set()
    for e in new_edges:
        if e.get("edge_type") == "JOIN":
            seen_join_keys.add((e["source"], e["target"]))
    full_edges = full_graph.get("edges", [])
    for fe in full_edges:
        fed = fe.get("data", fe)
        fetype = fed.get("edge_type", "") or fed.get("relationship", "")
        if fetype != "JOIN":
            continue
        src_orig = fed.get("source", "")
        tgt_orig = fed.get("target", "")
        src_new = id_map.get(src_orig)
        tgt_new = id_map.get(tgt_orig)
        if not src_new or not tgt_new or src_new == tgt_new:
            continue
        key = (src_new, tgt_new)
        if key in seen_join_keys:
            continue
        seen_join_keys.add(key)
        src_obj = node_by_id.get(src_new, {})
        tgt_obj = node_by_id.get(tgt_new, {})
        if src_obj.get("type") in ("field",) or tgt_obj.get("type") in ("field",):
            continue
        promoted.append({
            "id": f"l2e_join_survive_{src_new}_{tgt_new}",
            "source": src_new,
            "target": tgt_new,
            "edge_type": "JOIN",
            "category": "filter",
            "color": "#E91E63",
            "label": "JOIN",
            "line_style": "dashed",
            "width": 2,
            "desc": "JOIN key (table relationship)",
            "sql_range": fed.get("sql_range"),
        })

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

    # Bug 46 (Pattern 2): Redirect TABLE_FLOW edges that bypass ⟐ output.
    # After DML simplification, any surviving TABLE_FLOW edge into a DML target
    # that doesn't go through intermediate_id should be redirected.
    if intermediate_id:
        for e in new_edges:
            src = e.get("source", "")
            tgt = e.get("target", "")
            etype = e.get("edge_type", "")
            if tgt in dml_targets and src != intermediate_id and etype == "TABLE_FLOW":
                e["source"] = intermediate_id

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

    # ── Bug 28: Alias field synchronization + DML phantom fields ──
    # Per formal definition: when alias exists, its field set MUST mirror
    # the original table. And DML edges show fields flowing into targets.

    # Build field index: parent_table_id -> list of field dicts
    field_by_parent = {}
    for fn in field_nodes:
        pid = fn.get("parent", "")
        if pid:
            field_by_parent.setdefault(pid, []).append(fn)

    # ── Bug 31: Output table fields from SCHEMA edges ──
    # Per formal definition: output table fields = {columns with SCHEMA edge
    # FROM this output table}. Read from full_graph (before lineage filtering)
    # because filter_relevant() may remove SCHEMA edges if the output table
    # is not in the lineage set (TABLE_FLOW not followed by BFS).
    import hashlib as _hl
    existing_vt_ids = {tn["original_id"] for tn in table_nodes.values()
                       if tn.get("variable_type") == "virtual_table"}
    full_edges = full_graph.get("edges", [])
    for e in full_edges:
        ed = e.get("data", e)
        etype = ed.get("edge_type") or ed.get("relationship", "")
        if etype == "SCHEMA" and ed.get("source") in existing_vt_ids:
            # Find the column node that this SCHEMA edge points to
            for n in nodes:
                nd = n.get("data", n)
                if nd.get("id") == ed.get("target"):
                    label = nd.get("label", "")
                    # Extract field name from label (e.g., "c.customer_id" → "customer_id")
                    fn = label.rsplit(".", 1)[-1] if "." in label else label
                    tn_name = nd.get("table_name", "") or label.rsplit(".", 1)[0] if "." in label else ""
                    # Get the output table's compound node id
                    vt_id = table_nodes[ed["source"]]["id"] if ed["source"] in table_nodes else None
                    if vt_id and fn:
                        already = any(
                            f.get("parent") == vt_id and f.get("label") == fn
                            for f in field_nodes
                        )
                        if not already:
                            field_nodes.append({
                                "id": f"fld_{_hl.md5((vt_id + fn).encode()).hexdigest()[:10]}",
                                "label": fn,
                                "type": "field",
                                "variable_type": "field",
                                "field_group": "direct",
                                "table_name": tn_name,
                                "field_name": fn,
                                "parent": vt_id,
                                "original_id": nd.get("id"),
                            })
                    break

    # Sync 1: alias -> canonical (alias invariant)
    for label, canonical in alias_map.items():
        if label == canonical:
            continue
        # Find alias table node
        alias_tbl_id = None
        canon_tbl_id = None
        for tid, tn in table_nodes.items():
            if tn["table_name"] == label:
                alias_tbl_id = tn["id"]
            if tn["table_name"] == canonical:
                canon_tbl_id = tn["id"]
        if alias_tbl_id and canon_tbl_id and alias_tbl_id in field_by_parent:
            # Copy alias fields to canonical table
            for af in field_by_parent[alias_tbl_id]:
                exists = any(
                    f.get("parent") == canon_tbl_id and f.get("label") == af.get("label")
                    for f in field_nodes
                )
                if not exists:
                    proxy = dict(af)
                    proxy["id"] = f"sync_{af['id']}_canon"
                    proxy["parent"] = canon_tbl_id
                    proxy["field_group"] = "direct"
                    field_nodes.append(proxy)

    # Sync 2: DML phantom fields (field -> DML target table)
    # Bug 29: After field promotion, dml_pairs may contain table IDs (not field IDs).
    # Handle both: table ID → sync all fields under that table; field ID → direct match.
    for (src_fid, tgt_tid) in dml_pairs:
        # Find all field nodes whose parent is src_fid (table-level DML after promotion)
        src_fields = [fn for fn in field_nodes if fn.get("parent") == src_fid]
        if not src_fields:
            # src_fid might be a field ID (pre-promotion path) — try direct match
            src_fields = [fn for fn in field_nodes if fn["id"] == src_fid]
        for fn in src_fields:
            exists = any(
                f.get("parent") == tgt_tid and f.get("label") == fn.get("label")
                for f in field_nodes
            )
            if not exists:
                proxy = dict(fn)
                proxy["id"] = f"dml_{fn['id']}_{tgt_tid[:8]}"
                proxy["parent"] = tgt_tid
                proxy["field_group"] = "direct"
                field_nodes.append(proxy)

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



