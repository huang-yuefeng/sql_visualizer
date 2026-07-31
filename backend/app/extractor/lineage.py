"""R18 Field-level lineage computation — extracted from dataflow_service.py.

Provides:
  compute_field_lineage()    — BFS with 15 edge-type rules from formal definition
  filter_graph_by_lineage()  — Filter graph nodes/edges by lineage set
  filter_relevant()          — Convenience: compute lineage then filter

Design: This module owns all SQL-semantic algorithms. L1/L2 graph builders
are thin wrappers in dataflow_service.py that call these functions.
"""

from __future__ import annotations
import logging

_log = logging.getLogger('dataflow')

# ── Edge semantics table (single source of truth) ──
# Item 5 (Lessons Learned): all 16 edge types declare their lineage behavior here.
#   propagates_value: the edge carries a produced value into the target (production edge)
#   always_bidir:      the edge is always followed in both directions by the BFS
# JOIN/FILTER are conditional (both ends need a production path); SCHEMA has its
# own directionality rules handled in the BFS below.
EDGE_SEMANTICS = {
    "REF":        {"propagates_value": True,  "always_bidir": False},
    "TRANSFORM":  {"propagates_value": True,  "always_bidir": False},
    "AGGREGATE":  {"propagates_value": True,  "always_bidir": False},
    "WINDOW":     {"propagates_value": True,  "always_bidir": False},
    "COMPUTED":   {"propagates_value": True,  "always_bidir": False},
    "DML":        {"propagates_value": True,  "always_bidir": False},
    "ALIAS":      {"propagates_value": True,  "always_bidir": False},
    "CORRELATED": {"propagates_value": False, "always_bidir": True},
    "INDIRECT":   {"propagates_value": False, "always_bidir": True},
    "SET_OP":     {"propagates_value": False, "always_bidir": True},
    "SUBSET":     {"propagates_value": False, "always_bidir": True},
    "SUBQUERY":   {"propagates_value": False, "always_bidir": True},
    "TABLE_FLOW": {"propagates_value": False, "always_bidir": True},
    "JOIN":       {"propagates_value": False, "always_bidir": False},
    "FILTER":     {"propagates_value": False, "always_bidir": False},
    "SCHEMA":     {"propagates_value": False, "always_bidir": False},
}

# Production edges "produce" a value in the target — derived from EDGE_SEMANTICS,
# shared with the L1 builder (app/services/l1_builder.py).
PRODUCTION_EDGES = {k for k, v in EDGE_SEMANTICS.items() if v["propagates_value"]}
# Structural edges always bidirectionally followed by the BFS.
ALWAYS_BIDIR_EDGES = {k for k, v in EDGE_SEMANTICS.items() if v["always_bidir"]}


def compute_field_lineage(graph_data: dict, target_table: str,
                          target_field: str,
                          table_schemas: dict | None = None,
                          edge_filter: set | None = None) -> set:
    """Compute the lineage set R for a target field using edge-type-specific rules.

    Uses iterative BFS through 15 edge types from the formal definition
    (DATAFLOW_FORMAL_DEFINITION.md). Returns set of node IDs in the lineage closure.

    Edge-type rules:
      SCHEMA:     ↑ always add table; ↓ production-filtered columns only
      REF:        bidirectional, always follow
      TRANSFORM:  bidirectional, always follow
      AGGREGATE:  bidirectional, always follow
      WINDOW:     bidirectional, always follow
      COMPUTED:   bidirectional, always follow
      TABLE_FLOW: bidirectional — always follow (via _ALWAYS_BIDIR — DML/REF/SCHEMA↑ already reach source tables)
      ALIAS:      bidirectional, always follow
      DML:        forward (col→table): always; reverse (table→col): production-filtered
      JOIN:       conditional — both ends must be in R via production
      FILTER:     conditional — both ends must be in R via production
      CORRELATED: bidirectional, always follow
      INDIRECT:   bidirectional, always follow
      SUBSET:     bidirectional, always follow
      SET_OP:     bidirectional, always follow
    """
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    # --- R18: Use table_schemas for O(1) table+field validation ---
    if table_schemas:
        if target_table not in table_schemas:
            _log.info(f'R18 lineage: table {target_table} not in schema')
            return set()
        if target_field not in table_schemas.get(target_table, set()):
            _log.info(f'R18 lineage: field {target_field} not in table {target_table}')
            return set()
        _log.info(f'R18 lineage: table_schemas validation passed for {target_table}.{target_field}')

    # Build adjacency: node_id -> [(neighbor_id, edge_type, direction)]
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
        etype = ed.get("edge_type") or ed.get("relationship", "")
        adj.setdefault(src, []).append((tgt, etype, "forward"))
        adj.setdefault(tgt, []).append((src, etype, "reverse"))

    # --- Edge type classification ---
    # Production edges "produce" a value in the target
    _PRODUCTION = PRODUCTION_EDGES
    # Structural edges always bidirectionally followed (derived from EDGE_SEMANTICS)
    _BIDIR = _PRODUCTION | ALWAYS_BIDIR_EDGES

    # --- Seed matching: table-first validated lookup ---
    table_node_id = None
    for n in nodes:
        nd = n.get("data", n)
        if nd.get("label") == target_table and \
           nd.get("variable_type", "") in ("table", "view", "virtual_table"):
            table_node_id = nd.get("id")
            break
    if not table_node_id:
        target_lower = target_table.lower()
        for n in nodes:
            nd = n.get("data", n)
            if (nd.get("label", "").lower() == target_lower and
                nd.get("variable_type", "") in ("table", "view", "virtual_table")):
                table_node_id = nd.get("id")
                break

    # --- Bug 35: Build ALIAS-transitive closure from target table ---
    # SCHEMA edges from the target table's aliases must also be accepted.
    alias_sources = {table_node_id} if table_node_id else set()
    if table_node_id:
        queue = [table_node_id]
        while queue:
            nid = queue.pop(0)
            for e in edges:
                ed = e.get("data", e)
                etype = ed.get("edge_type") or ed.get("relationship", "")
                if etype == "ALIAS" and ed.get("source") == nid:
                    alias_tgt = ed.get("target")
                    if alias_tgt not in alias_sources:
                        alias_sources.add(alias_tgt)
                        queue.append(alias_tgt)

    seed_ids = set()
    full_name = f"{target_table}.{target_field}"
    if table_node_id:
        for n in nodes:
            nd = n.get("data", n)
            label = nd.get("label", "")
            nid = nd.get("id")
            # Match: exact full name, exact field, or suffix after dot
            if not (label == full_name or label == target_field or
                    ("." in label and label.rsplit(".", 1)[-1] == target_field)):
                src_cols = nd.get("source_columns", [])
                if not (src_cols and (full_name in src_cols or target_field in src_cols)):
                    continue
            # Bug 35: Validate via SCHEMA from target table OR any of its aliases
            for e in edges:
                ed = e.get("data", e)
                etype = ed.get("edge_type") or ed.get("relationship", "")
                if (etype == "SCHEMA" and
                    ed.get("source") in alias_sources and
                    ed.get("target") == nid):
                    seed_ids.add(nid)
                    break
    
    # Bug 39: DML-based seed search when SCHEMA alone can't find seeds.
    # When a column belongs to a different table's alias (e.g., c.customer_id
    # on alias "c" of crm_customers, DML'd INTO stg_customers), SCHEMA from
    # the target table won't match. Instead, search DML edges INTO the target.
    if not seed_ids and table_node_id:  # Bug 39: works without table_schemas for constrained union
        for e in edges:
            ed = e.get("data", e)
            etype = ed.get("edge_type") or ed.get("relationship", "")
            if etype == "DML" and ed.get("target") == table_node_id:
                src_node_id = ed.get("source")
                for n in nodes:
                    nd = n.get("data", n)
                    if nd.get("id") == src_node_id:
                        fn = nd.get("field_name", "")
                        if not fn and "." in nd.get("label", ""):
                            fn = nd["label"].rsplit(".", 1)[-1]
                        if fn == target_field:
                            seed_ids.add(src_node_id)

    # P6: No fallback — if no seeds after SCHEMA + DML search, return empty
    if not seed_ids:
        _log.info(f'R18 lineage: no seeds (SCHEMA+DML) found for {target_table}.{target_field}')
        return set()

    R = set(seed_ids)
    _log.info(f'R18 lineage: {len(nodes)} total nodes, seed={seed_ids}')

    # --- BFS expansion ---
    changed = True
    iteration = 0
    while changed:
        changed = False
        new_nodes = set()
        for nid in list(R):
            for (neighbor, etype, direction) in adj.get(nid, []):
                if neighbor in R:
                    continue

                should_add = False

                # DML special handling (before _BIDIR check):
                # forward (col→table): always; reverse (table→col): production-filtered
                if etype == "DML":
                    if edge_filter is not None and etype not in edge_filter:
                        pass  # skip
                    elif direction == "forward":
                        should_add = True
                    else:
                        # table→column: only if column has non-DML production from R
                        for (n2, e2, d2) in adj.get(neighbor, []):
                            if n2 in R and e2 in _PRODUCTION and e2 != "DML":
                                should_add = True
                                break
                elif etype in _BIDIR:
                    if edge_filter is None or etype in edge_filter:
                        should_add = True
                elif etype == "SCHEMA":
                    if edge_filter is not None and etype not in edge_filter:
                        pass  # skip
                    elif direction == "reverse":
                        # column → table (upstream): always add table
                        should_add = True
                    else:
                        # table → column (downstream): production-filtered
                        for (n2, e2, d2) in adj.get(neighbor, []):
                            if n2 in R and e2 in _PRODUCTION and d2 == "reverse":
                                should_add = True
                                break
                elif etype == "JOIN":
                    if edge_filter is not None and etype not in edge_filter:
                        pass  # skip
                    else:
                        has_prod = False
                        for (n2, e2, d2) in adj.get(neighbor, []):
                            if n2 in R and e2 in _PRODUCTION:
                                has_prod = True
                                break
                        if has_prod:
                            should_add = True
                elif etype == "FILTER":
                    if edge_filter is not None and etype not in edge_filter:
                        pass  # skip
                    else:
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
        iteration += 1
        if new_nodes:
            _log.info(f'R18 iteration {iteration}: +{len(new_nodes)}, R size={len(R)}')

    _log.info(f'R18 complete: {len(R)} nodes in lineage ({len(nodes)} total)')
    return R


def filter_graph_by_lineage(graph_data: dict, lineage_set: set) -> dict:
    """Filter graph to only nodes and edges in the lineage set."""
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
                    target_field: str,
                    table_schemas: dict | None = None) -> dict:
    """Filter graph using field-level lineage rules (16 edge types).

    Falls back to full graph if lineage returns empty.
    """
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    lineage = compute_field_lineage(graph_data, target_table, target_field, table_schemas)

    if not lineage:
        # Fallback: name-based filtering — keep only nodes mentioning target field/table
        _log.info('R18 filter_relevant: lineage empty, using name-based fallback')
        fallback_nodes = []
        for n in nodes:
            nd = n.get('data', n)
            label = nd.get('label', '')
            src_cols = nd.get('source_columns', [])
            if (target_field in label or target_table in label or
                any(target_field in sc or target_table in sc for sc in src_cols)):
                fallback_nodes.append(n)
        if fallback_nodes:
            fallback_ids = {n.get('data', n).get('id') for n in fallback_nodes}
            fallback_edges = [e for e in edges
                if (e.get('data', e).get('source') in fallback_ids and
                    e.get('data', e).get('target') in fallback_ids)]
            return {
                **{k: v for k, v in graph_data.items() if k not in ('nodes', 'edges')},
                'nodes': fallback_nodes,
                'edges': fallback_edges,
            }
        return graph_data  # truly nothing found

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
