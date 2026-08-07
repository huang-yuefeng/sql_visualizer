"""R18 Field-level lineage computation — extracted from dataflow_service.py.

Provides:
  compute_field_lineage()    — BFS with 15 edge-type rules from formal definition
  filter_graph_by_lineage()  — Filter graph nodes/edges by lineage set
  filter_relevant()          — Convenience: compute lineage then filter

Two modes: legacy table-level lineage (compute_field_lineage/filter_relevant,
L1 + legacy callers) and strict table.field flow (compute_field_flow/
filter_by_field_flow, L2, v3.3.140+).

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
    "SUBQUERY":   {"propagates_value": False, "always_bidir": True},
    "TABLE_FLOW": {"propagates_value": False, "always_bidir": True},
    "JOIN":       {"propagates_value": False, "always_bidir": False},
    "FILTER":     {"propagates_value": False, "always_bidir": False},
    "SCHEMA":     {"propagates_value": False, "always_bidir": False},
    # B-series: SUBSET is pure connectivity padding (dependency_graph
    # Phase 7/8 "BRIDGE" safety net) — it does NOT carry data semantics.
    # Phase 1 (stopgap) skipped SUBSET edges leading INTO constant
    # producers (literal/aggregate/window neighbors); Phase 2 makes SUBSET
    # never walkable at all (bidir=False): nothing enters the lineage
    # closure over a SUBSET bridge, which is what kept constants, filter-
    # only columns, and detached second-statement vars in the graph.
    "SUBSET":     {"propagates_value": False, "always_bidir": False},
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
      SUBSET:     NEVER followed (B-series Phase 2 — connectivity padding
                  with no data semantics: propagates_value=False,
                  always_bidir=False)
      SET_OP:     bidirectional, always follow
    """
    # None-seed guard (B-series): empty/missing table or field args (and a
    # missing graph) return an empty closure gracefully — never
    # AttributeError/TypeError (e.g. a filter_relevant call with only a
    # table, or a None field).
    if not graph_data:
        return set()
    if not target_table or not target_field:
        _log.info(f'R18 lineage: missing target table/field ({target_table!r}/{target_field!r}) — empty closure')
        return set()

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
                    # Bug 37 decision (pinned): SCHEMA directionality here is
                    # the intended shared semantics for BOTH consumers — L1
                    # (edge_filter=PRODUCTION_EDGES | {"SCHEMA"}, l1_builder)
                    # and L2 (filter_relevant default): reverse (column→table)
                    # always follows; forward (table→column) is
                    # production-filtered. The unified engine is the single
                    # BFS — no per-consumer copy.
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
                        # B-series Phase 2: materialized join-key EXPRESSION
                        # nodes (CONCAT/RPAD/|| on columns in JOIN ON) are
                        # admitted UNCONDITIONALLY — the key construction
                        # itself is part of the field's data flow (its
                        # operand columns then arrive via REF). All other
                        # JOIN partners (vtables, ctes, plain columns) stay
                        # conditional on production evidence.
                        if node_types.get(neighbor, "") == "expression":
                            should_add = True
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

    # None-seed guard (B-series): no table/field → return the graph
    # unchanged (the name-based fallback below would crash on
    # `None in label`).
    if not target_table or not target_field:
        return graph_data

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


# ═══════════════════════════════════════════════════════════════════════
# STRICT TABLE.FIELD FLOW (v3.3.140+) — L2 only
# New requirement (2026-08-07): exact data flow of table.field, not
# table-level flow around the field. Legacy compute_field_lineage /
# filter_relevant above remain the table-level path (L1 + legacy callers,
# byte-identical). This section is the additive strict walker.
# Rules: see wiki/SOLUTION_DESIGN.md §"v3.3.140" §4.
# ═══════════════════════════════════════════════════════════════════════

# Field-like variable types. Verified against backend/app/models/variable.py
# (VariableType .value strings): the enum has no "computed"/"variable"
# members — the computed-value types there are case/transform/expression/
# window, so those are the members used here.
FIELD_LIKE = {"column", "cte_column", "literal", "aggregate", "expression",
              "case", "transform", "window"}
# Field-identity edges: the field itself flows through these (both directions).
FIELD_LAND = {"REF", "TRANSFORM", "AGGREGATE", "WINDOW", "COMPUTED"}
# Never walked by the strict walker. TABLE_FLOW/SCHEMA are replaced by
# identity resolution (SCHEMA's label-keyed targets are last-writer-wins and
# topologically broken); SUBQUERY/SET_OP/CORRELATED/INDIRECT/SUBSET carry no
# field identity.
NEVER = {"TABLE_FLOW", "SUBQUERY", "SET_OP", "CORRELATED", "INDIRECT", "SUBSET", "SCHEMA"}


def _is_containment(ed) -> bool:
    """I5 (v3.3.145): containment-tagged edge — nesting, not value flow.

    A2 tags SCHEMA containment edges (container table/CTE -> nested VT,
    e.g. rollover_loan_info@9 -> ⟐subq@0) so the strict walker does not
    treat them as flow. Contract: the edge dict carries key
    "containment" == True, or the edge object has attribute .containment.
    """
    if isinstance(ed, dict):
        return bool(ed.get("containment"))
    return bool(getattr(ed, "containment", False))


def _field_part(var):
    """Last dotted segment of the label — the field name proper."""
    return str(var.get("label") or "").rsplit(".", 1)[-1]


def _table_like(var):
    """Table-like vars: declared source types, or vars with resolved source_tables."""
    return (var.get("variable_type") in
            {"table", "view", "cte", "virtual_table", "subquery"}
            or bool(var.get("source_tables")))


def _context_of(var):
    return var.get("context") or ""


def _owner_index(nodes):
    """context -> label -> [ids] for table-like vars (identity lookup index)."""
    idx = {}
    for n in nodes:
        nd = n.get("data", n)
        if not _table_like(nd):
            continue
        label = nd.get("label")
        if not label:
            continue
        idx.setdefault(_context_of(nd), {}).setdefault(label, []).append(nd.get("id"))
    return idx


def _find_labeled(label, ctx, idx):
    """Id of a table-like var labeled `label` in `ctx`, else nearest ancestor
    context (context is a "/"-separated path; ancestor = rsplit("/", 1)[0],
    walking up). Returns None if never found."""
    cur = ctx
    while True:
        ids = idx.get(cur, {}).get(label)
        if ids:
            return ids[0]
        if not cur or "/" not in cur:
            return None
        cur = cur.rsplit("/", 1)[0]


def _resolve_owner_holder(var, nodes, idx=None):
    """Id of the table-like var that owns `var` (3-step identity rule), or None.

    1. source_tables non-empty -> var labeled source_tables[0] in same context,
       else nearest ancestor context;
    2. else if label or sql_expression contains "." (qualified, e.g.
       "p1.data_dt") -> qualifier = first segment -> table-like var labeled
       qualifier in same context, else nearest ancestor;
    3. else (unqualified) -> exactly ONE table-like var in the same context
       (labels starting "⟐" excluded) -> that var; zero or several -> None.
    """
    if idx is None:
        idx = _owner_index(nodes)
    ctx = _context_of(var)

    st = var.get("source_tables") or []
    if st:
        return _find_labeled(st[0], ctx, idx)

    label = str(var.get("label") or "")
    if "." in label:
        return _find_labeled(label.split(".", 1)[0], ctx, idx)
    expr = str(var.get("sql_expression") or "")
    if "." in expr:
        return _find_labeled(expr.split(".", 1)[0].strip(), ctx, idx)

    # unqualified: exactly one table-like var in the same context (⟐ excluded)
    cands = []
    for lbl, ids in idx.get(ctx, {}).items():
        if lbl.startswith("⟐"):
            continue
        cands.extend(ids)
    if len(cands) == 1:
        return cands[0]
    return None


def _owner_of(var, node_map, idx=None):
    """Physical owner table of `var`: holder's source_tables[0], or None.

    When the holder IS the physical table itself (its source_tables are empty
    — it owns, nothing owns it), the holder's own physical identity
    (table_name, else label) is the owner name."""
    holder = _resolve_owner_holder(var, node_map, idx)
    hv = node_map.get(holder) if holder else None
    if not hv:
        return None
    hst = hv.get("source_tables") or []
    if hst:
        return hst[0]
    return hv.get("table_name") or hv.get("label")


def _cte_var(name, node_map):
    """Id of the CTE var (variable_type == "cte") labeled `name`, any context
    (the one with the longest context if several); None if absent."""
    best, best_len = None, -1
    for nid, var in node_map.items():
        if var.get("variable_type") == "cte" and (var.get("label") or "") == name:
            ctx = _context_of(var)
            if len(ctx) > best_len:
                best, best_len = nid, len(ctx)
    return best


def compute_field_flow(graph_data, target_table, target_field,
                       table_schemas=None) -> set:
    """Strict table.field data flow closure (v3.3.140+, L2 only).

    Seeds by exact field identity (per-instance table.field vars owned by
    target_table, plus PARTITION-defined write-side vars), then expands only
    where the field itself participates. Returns the set of node ids in the
    strict closure.

    table_schemas is accepted for signature parity with compute_field_lineage
    but unused: SCHEMA-based validation is replaced by identity resolution
    (wiki/SOLUTION_DESIGN.md §"v3.3.140" §4).
    """
    if not graph_data:
        return set()
    nodes = graph_data.get("nodes", []) or []
    edges = graph_data.get("edges", []) or []

    node_map = {}
    for n in nodes:
        nd = n.get("data", n)
        node_map[nd.get("id")] = nd

    # adjacency: nid -> [(neighbor, etype, forward)] — forward = nid is the
    # edge's source. etype from edge_type or relationship.
    # I5 (v3.3.145): containment-tagged edges are excluded from the walk
    # entirely — they express syntactic nesting (container -> nested VT),
    # already visible via the nesting structure; they must not look like
    # value flow. Skipped here so neither the expansion loop nor the
    # seed-zone BFS ever follows them (type-agnostic: the tag governs, not
    # the edge type).
    adjacency = {}
    for e in edges:
        ed = e.get("data", e)
        if _is_containment(ed):
            continue
        src, tgt = ed.get("source"), ed.get("target")
        etype = ed.get("edge_type") or ed.get("relationship")
        adjacency.setdefault(src, []).append((tgt, etype, True))
        adjacency.setdefault(tgt, []).append((src, etype, False))

    idx = _owner_index(nodes)

    # ── Seeds: field-like vars whose field part is target_field, with
    # defined_in == "PARTITION" or owner == target_table. ──
    seeds = set()
    for nid, var in node_map.items():
        if var.get("variable_type") not in FIELD_LIKE:
            continue
        if _field_part(var) != target_field:
            continue
        if var.get("defined_in") == "PARTITION" or _owner_of(var, node_map, idx) == target_table:
            seeds.add(nid)

    # ── seed_zone: memoized BFS from the seeds over FIELD_LAND edges (both
    # directions), computed lazily per queried node. Field identity flows
    # through these edges; used by the FILTER/JOIN admission rule. ──
    _zone_memo = {}

    def _seed_zone(nid):
        if nid not in _zone_memo:
            zone = set()
            stack = list(seeds)
            while stack:
                cur = stack.pop()
                if cur in zone:
                    continue
                zone.add(cur)
                for (nb, et, _fwd) in adjacency.get(cur, []):
                    if et in FIELD_LAND and nb not in zone:
                        stack.append(nb)
            _zone_memo[nid] = nid in zone
        return _zone_memo[nid]

    # ── Identity helper + chain ──
    # Physical identity of a var (chain matching key): the attributed
    # source table, else the declared table_name/label.
    def _identity(var):
        st = var.get("source_tables") or []
        if st:
            return st[0]
        return var.get("table_name") or var.get("label") or ""

    # chain: identities of table-like vars admitted into the closure.
    # TABLE_FLOW is followed FORWARD only from a source whose identity is
    # already in the chain (Q1 clause a) — no reverse leakage.
    chain = {target_table}
    for sid in seeds:
        var = node_map.get(sid)
        if var is not None and _table_like(var):
            ident = _identity(var)
            if ident:
                chain.add(ident)

    def _register(nb):
        """Record a table-like admission's identity into the chain."""
        var = node_map.get(nb)
        if var is not None and _table_like(var):
            ident = _identity(var)
            if ident:
                chain.add(ident)

    # ── Joint fixpoint: expansion rounds and identity-admission rounds
    # alternate until neither grows (monotone — terminates; rounds capped).
    # Identity admissions used to run ONCE after the BFS, so ALIAS /
    # TABLE_FLOW / DML edges from nodes that only enter via identity
    # (owner holders, physical tables, CTE containers) never fired. ──
    visited = set(seeds)
    changed = True
    rounds = 0
    while changed and rounds < 100:
        changed = False
        rounds += 1
        # ── expansion round ──
        stack = list(visited)
        while stack:
            nid = stack.pop()
            for (nb, et, fwd) in adjacency.get(nid, []):
                if nb in visited:
                    continue
                if et in FIELD_LAND:
                    admit = True
                elif et == "ALIAS":
                    nb_var = node_map.get(nb)
                    nb_st = (nb_var or {}).get("source_tables") or []
                    admit = bool(nb_st) and nb_st[0] == target_table
                elif et in ("FILTER", "JOIN"):
                    admit = _seed_zone(nid) or _seed_zone(nb)
                elif et == "DML":
                    admit = fwd  # forward only (source -> target)
                elif et == "TABLE_FLOW":
                    # Q1, forward-only: (a) table-like source whose physical
                    # identity is in the chain; (b) VT whose context is an
                    # ancestor-or-equal of a visited field var's context
                    # with the target field part.
                    admit = False
                    if fwd:
                        src_var = node_map.get(nid)
                        if src_var and src_var.get("variable_type") == "virtual_table":
                            sctx = _context_of(src_var)
                            for fv in node_map.values():
                                if (fv.get("variable_type") in FIELD_LIKE
                                        and fv.get("id") in visited
                                        and _field_part(fv) == target_field):
                                    fctx = _context_of(fv)
                                    if fctx == sctx or fctx.startswith(sctx.rstrip("/") + "/"):
                                        admit = True
                                        break
                        elif _table_like(src_var):
                            admit = _identity(src_var) in chain
                else:
                    admit = False  # NEVER types and anything unknown
                if admit:
                    visited.add(nb)
                    changed = True
                    _register(nb)

        # ── identity-admission round (owner-holders, physical tables, CTE
        # containers — existing rules unchanged) ──
        for nid in list(visited):
            var = node_map.get(nid)
            if not var:
                continue
            if var.get("variable_type") in FIELD_LIKE:
                holder = _resolve_owner_holder(var, nodes, idx)
                if holder and holder not in visited:
                    visited.add(holder)
                    changed = True
                    _register(holder)
                hv = node_map.get(holder) if holder else None
                if hv:
                    hst = hv.get("source_tables") or []
                    if hst and hst[0]:
                        tv = _find_labeled(hst[0], _context_of(hv), idx)
                        if tv and tv not in visited:
                            visited.add(tv)
                            changed = True
                            _register(tv)
            # Container rule: context segments "CTE{...}" -> the CTE var
            # labeled X (the scope that contains the reads).
            for seg in _context_of(var).split("/"):
                if seg.startswith("CTE{") and "}" in seg:
                    cte_id = _cte_var(seg[4:seg.index("}")], node_map)
                    if cte_id and cte_id not in visited:
                        visited.add(cte_id)
                        changed = True
                        _register(cte_id)
    return visited


def filter_by_field_flow(graph_data, target_table, target_field,
                         table_schemas=None) -> dict:
    """Filter graph to the strict table.field flow closure (v3.3.140+, L2 only).

    Returns a dict identical to graph_data except nodes = those whose id is in
    the closure, edges = those with both ends in the closure; all other
    top-level keys are kept. I5 (v3.3.145): containment-tagged edges are
    excluded even when both ends are in the closure — nesting is shown by the
    nesting structure, not as flow arrows. An empty closure yields 0 nodes —
    the caller handles the not-in-flow case; this never raises.
    """
    if not graph_data:
        return graph_data
    closure = compute_field_flow(graph_data, target_table, target_field, table_schemas)
    nodes = graph_data.get("nodes", []) or []
    edges = graph_data.get("edges", []) or []
    filtered_nodes = [n for n in nodes if n.get("data", n).get("id") in closure]
    filtered_edges = [e for e in edges
                      if (e.get("data", e).get("source") in closure and
                          e.get("data", e).get("target") in closure and
                          not _is_containment(e.get("data", e)))]
    return {
        **{k: v for k, v in graph_data.items() if k not in ("nodes", "edges")},
        "nodes": filtered_nodes,
        "edges": filtered_edges,
    }
