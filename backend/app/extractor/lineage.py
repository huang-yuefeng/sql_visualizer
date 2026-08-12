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

from .walkable_set import FIELD_WALKABLE, NEVER_WALKED

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
        # `read` flag: REF edges with operation == "READ" are field→holder
        # reads — walkable ONLY from the field node to its holder
        # (forward), never from the holder back out into sibling fields
        # (the L1 sibling-leak; the same model compute_field_flow gained in
        # v3.3.148). The flag rides the adjacency tuples so the expansion
        # loop and the production-evidence checks apply the same rule.
        read = bool(etype == "REF" and (ed.get("operation") or "") == "READ")
        adj.setdefault(src, []).append((tgt, etype, "forward", read))
        adj.setdefault(tgt, []).append((src, etype, "reverse", read))

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
            for (neighbor, etype, direction, read) in adj.get(nid, []):
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
                        for (n2, e2, d2, r2) in adj.get(neighbor, []):
                            # r2: read-flagged REF edges are the field
                            # being READ, not production into the table —
                            # never production evidence (sibling leak).
                            if (n2 in R and e2 in _PRODUCTION and e2 != "DML"
                                    and not r2):
                                should_add = True
                                break
                elif etype in _BIDIR:
                    if edge_filter is None or etype in edge_filter:
                        # read edges traverse field → holder only; the
                        # reverse walk (holder → sibling fields) is the
                        # v3.3.148 sibling leak.
                        should_add = not (read and direction == "reverse")
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
                        for (n2, e2, d2, r2) in adj.get(neighbor, []):
                            if (n2 in R and e2 in _PRODUCTION and d2 == "reverse"
                                    and not r2):
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
                            for (n2, e2, d2, r2) in adj.get(neighbor, []):
                                if n2 in R and e2 in _PRODUCTION and not r2:
                                    has_prod = True
                                    break
                            if has_prod:
                                should_add = True
                elif etype == "FILTER":
                    if edge_filter is not None and etype not in edge_filter:
                        pass  # skip
                    else:
                        has_prod = False
                        for (n2, e2, d2, r2) in adj.get(neighbor, []):
                            if n2 in R and e2 in _PRODUCTION and not r2:
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
# Field-identity edges: the field itself flows through these. Directionality
# is per-edge: the REF/READ edges (field → its owning table, dependency_graph
# Phase 4d/8 — commit 28d8210 retyped them from SUBSET to REF) are walked
# ONLY field → holder; value-copy REF and the other types here are
# bidirectional (the walker reads the edge's `read` flag from the adjacency).
FIELD_LAND = FIELD_WALKABLE
# Never walked by the strict walker. TABLE_FLOW has its own conditional
# rule (forward-only, source identity in the chain) so it never reaches
# the reject branch; the rest are the contract's NEVER_WALKED set.
# TABLE_FLOW/SCHEMA are replaced by identity resolution (SCHEMA's
# label-keyed targets are last-writer-wins and topologically broken);
# SUBQUERY/SET_OP/CORRELATED/INDIRECT/SUBSET carry no field identity.
NEVER = NEVER_WALKED


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


def _occ_field_part(o) -> str:
    """Last dotted segment of an occurrence's label — the field name
    proper (mirror of the retired display-side _field_part)."""
    return str((o or {}).get("name") or "").rsplit(".", 1)[-1]


def _occ_table_like(o) -> bool:
    """Table-like occurrence: declared source types, or resolved
    source_tables (mirror of the retired display-side _table_like)."""
    return (o.get("variable_type") in
            {"table", "view", "cte", "virtual_table", "subquery",
             "merge_target"}
            or bool(o.get("source_tables")))


def _occ_identity(o) -> str:
    """Physical identity of an occurrence (chain matching key): the
    attributed source table, else the resolved table_name/label (mirror
    of the retired display-side _identity)."""
    st = o.get("source_tables") or []
    if st:
        return st[0]
    return o.get("table_name") or o.get("name") or ""


def _pick_occurrence(pm, owner_key: str, label: str, ctx: str, occ):
    """Model mirror of the retired display-side _find_labeled: the owner
    entity's occurrence labeled `label` whose context is `ctx`, else the
    nearest ancestor context (deepest first); None when absent.

    The owner-entity restriction is the model truth: _find_labeled
    searched EVERY table-like var with that label in that context (a
    label can name different physical tables per scope — the exact
    approximation the physical model banishes).
    """
    tbl = pm.tables.get(owner_key)
    if tbl is None:
        return None
    cands = [vid for vid in tbl.occurrence_ids
             if (occ(vid) or {}).get("name") == label]
    if not cands:
        return None
    cur = ctx
    while True:
        for vid in cands:
            if (occ(vid) or {}).get("context") == cur:
                return vid
        if not cur or "/" not in cur:
            return None
        cur = cur.rsplit("/", 1)[0]


def _cte_occurrence(pm, name: str, occ):
    """Model mirror of the retired display-side _cte_var: the occurrence
    with variable_type "cte" labeled `name`, the one with the longest
    context; None when absent."""
    best, best_len = None, -1
    for vid, o in pm.occurrences.items():
        if o.get("variable_type") == "cte" and o.get("name") == name:
            clen = len(o.get("context") or "")
            if clen > best_len:
                best, best_len = vid, clen
    return best


def compute_field_flow(graph_data, target_table, target_field,
                       table_schemas=None, physical_model=None) -> set:
    """Strict table.field data flow closure (v3.3.140+, L2 only) —
    J12-10 stage 3: walks the PHYSICAL MODEL's edges and occurrences
    instead of the display graph with reconstruction heuristics. The
    model carries the truth (edge endpoints as raw var ids, containment,
    per-occurrence structure); the walk rules below are unchanged from
    v3.3.140 (see tools/PHYSICAL_MODEL_MIGRATION_MAP.md §stage 3):

      W1 seeds = PhysicalField occurrences of the searched name's
         entities (fields[(target_keys, field)].occurrence_ids). The
         PARTITION carve-out (a PARTITION var seeds only its own DML
         target table) is automatic: the model attributes every
         occurrence to its entity via source_tables/alias resolution, so
         another table's PARTITION var never lands in these fields.
      W2 FIELD_LAND both directions; REF/READ (field → its owning table)
         forward-only, EXCEPT the reverse read of a var carrying the
         target field part (Issue 3, R19.3 no-bypass completion).
      W3 ALIAS iff the neighbor's source_tables[0] == target_table.
      W4 FILTER/JOIN iff the seed zone (memoized BFS from the seeds over
         FIELD_LAND) contains an endpoint.
      W5 DML forward-only, plus backward for field-like vars carrying
         the target field part (write-side VALUE appearances).
      W6 TABLE_FLOW forward-only: (a) table-like source whose physical
         identity is in the chain; (b) VT source whose context is an
         ancestor-or-equal of a visited field var with the target field
         part.
    plus the identity-admission round (owner-holder + its physical table
    via _pick_occurrence, CTE container rule, Issue-3 bare physical
    instance) — every lookup through the model (entities, edges,
    occurrence index), never display reconstruction.

    physical_model is REQUIRED (TypeError when None). table_schemas is
    accepted for signature parity with compute_field_lineage but unused.
    Returns the set of node ids in the strict closure.
    """
    if physical_model is None:
        raise TypeError(
            "compute_field_flow: physical_model is required (J12-10 "
            "stage 3 — the walker consumes the physical model)")
    if not graph_data:
        return set()
    nodes = graph_data.get("nodes", []) or []

    node_map = {}
    for n in nodes:
        nd = n.get("data", n)
        node_map[nd.get("id")] = nd

    pm = physical_model
    occ = pm.occurrence

    # ── W1: seeds — occurrences of the PhysicalFields named target_field
    # on the searched name's entities. target_keys = every entity named
    # target_table (physical tables key by name; per-scope containers by
    # (name, context) — the union mirrors the display's name-based owner
    # match). ──
    target_keys = {k for k, t in pm.tables.items() if t.name == target_table}
    seeds = set()
    for (tkey, fname), fld in pm.fields.items():
        if tkey not in target_keys or fname != target_field:
            continue
        for vid in fld.occurrence_ids:
            o = occ(vid)
            if o is not None and o.get("variable_type") in FIELD_LIKE:
                seeds.add(vid)

    # ── adjacency over the MODEL's PhysicalEdges (occurrence-level — the
    # edge endpoints ARE the raw var ids the graph nodes carry).
    # I5 (v3.3.145): containment-tagged edges are excluded from the walk
    # entirely — syntactic nesting, not value flow (skipped here so
    # neither the expansion loop nor the seed-zone BFS ever follows
    # them). ──
    adjacency = {}
    for E in pm.edges:
        if E.containment:
            continue
        # `read` flag: REF edges with operation == "READ" are field→table
        # reads — walkable ONLY from the field node to its holder
        # (forward), never from the table back out into sibling fields
        # (the L2 field-flood defect). Value-copy REF and all other
        # FIELD_LAND types keep both directions.
        read = bool(E.edge_type == "REF" and E.operation == "READ")
        adjacency.setdefault(E.source_id, []).append(
            (E.target_id, E.edge_type, True, read, E.operation))
        adjacency.setdefault(E.target_id, []).append(
            (E.source_id, E.edge_type, False, read, E.operation))

    # ── seed_zone: memoized BFS from the seeds over FIELD_LAND edges
    # (both directions), computed lazily per queried node. ──
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
                for (nb, et, fwd, read, _op) in adjacency.get(cur, []):
                    # read edges traverse field → holder only (same rule
                    # as the expansion loop).
                    if (et in FIELD_LAND and nb not in zone
                            and not (read and not fwd)):
                        stack.append(nb)
            _zone_memo[nid] = nid in zone
        return _zone_memo[nid]

    # chain: identities of table-like admissions into the closure.
    # TABLE_FLOW is followed FORWARD only from a source whose identity is
    # already in the chain (Q1 clause a) — no reverse leakage.
    chain = {target_table}
    for sid in seeds:
        o = occ(sid)
        if o is not None and _occ_table_like(o):
            ident = _occ_identity(o)
            if ident:
                chain.add(ident)

    def _register(nid):
        """Record a table-like admission's identity into the chain."""
        o = occ(nid)
        if o is not None and _occ_table_like(o):
            ident = _occ_identity(o)
            if ident:
                chain.add(ident)

    # Field occurrence → owning entity key (the model's attribution —
    # source_tables[0] resolved through the alias map; the display used
    # to re-derive owners with a context walk).
    owner_by_id = {}
    for (tkey, _fname), fld in pm.fields.items():
        for vid in fld.occurrence_ids:
            owner_by_id[vid] = tkey

    # ── D2 (2026-08-12): the forward DML admit is field-aware — never
    # field-blind. Two per-call indexes:
    #   _dml_write_leg[target var id] — field parts of the columns the
    #     target's statement writes: the sources of the non-WRITE_READ
    #     DML edges into the target (Phase-1c select-list columns and
    #     Phase-8 projection/partition/literal write-leg vars all carry
    #     the written column's name; PARTITION columns arrive in the
    #     SQL's own casing → matched case-insensitively).
    #   _stmt_field_parts[TOP statement] — field parts referenced by any
    #     var of the statement (the write→read link admits only when the
    #     reader statement actually consumes the searched field).
    _dml_write_leg = {}
    for _E in pm.edges:
        if _E.edge_type != "DML":
            continue
        if (_E.operation or "").upper() == "WRITE_READ":
            continue
        _so = occ(_E.source_id)
        if _so is not None:
            _part = _occ_field_part(_so).lower()
            if _part:
                _dml_write_leg.setdefault(_E.target_id, set()).add(_part)
    _stmt_field_parts = {}
    for _vid, _o in pm.occurrences.items():
        _stmt = (_o.get("context") or "TOP").split("/", 1)[0]
        if not _stmt.startswith("TOP"):
            continue
        _part = _occ_field_part(_o).lower()
        if _part:
            _stmt_field_parts.setdefault(_stmt, set()).add(_part)

    # ── Joint fixpoint: expansion rounds and identity-admission rounds
    # alternate until neither grows (monotone — terminates; capped). ──
    visited = set(seeds)
    changed = True
    rounds = 0
    while changed and rounds < 100:
        changed = False
        rounds += 1
        # ── expansion round (walks the model's PhysicalEdges) ──
        stack = list(visited)
        while stack:
            nid = stack.pop()
            for (nb, et, fwd, read, op) in adjacency.get(nid, []):
                if nb in visited:
                    continue
                if et in FIELD_LAND:
                    # REF/READ (field → its owning table) admits only in
                    # the forward direction; the reverse traversal (table
                    # → sibling fields) is what flooded the L2 closure.
                    # Issue 3 (2026-08-11): EXCEPT the read of the
                    # SEARCHED field itself — an in-closure holder's
                    # reverse read of a field whose field part is the
                    # target field admits (the reader instance's read of
                    # the searched field joins the closure so the REF
                    # edge renders — R19.3 no-bypass completion). Same
                    # guard as the DML value rule below.
                    if read:
                        admit = fwd or (_occ_field_part(occ(nb)) == target_field)
                    else:
                        admit = True
                elif et == "ALIAS":
                    nb_o = occ(nb)
                    nb_st = (nb_o or {}).get("source_tables") or []
                    admit = bool(nb_st) and nb_st[0] == target_table
                elif et in ("FILTER", "JOIN"):
                    admit = _seed_zone(nid) or _seed_zone(nb)
                elif et == "DML":
                    # Forward only (source -> target) — plus the searched
                    # field's VALUE columns: a DML edge INTO an admitted
                    # node whose source is a field-like var carrying the
                    # target field part (the INSERT...SELECT value
                    # '$(load_date)' AS data_dt at L213 → rrcdm, P17
                    # §8.5) is the write-side value appearance — admitted
                    # backward so the value edge enters the closure.
                    nb_o = occ(nb)
                    admit = fwd or (
                        nb_o is not None
                        and nb_o.get("variable_type") in FIELD_LIKE
                        and _occ_field_part(nb_o) == target_field
                    )
                    if not admit and nb_o is not None:
                        # D2 (2026-08-12): a statement's OWN output VT
                        # (context exactly TOP{numeric} — a bare/VALUES
                        # INSERT names its output "⟐ insert", not "⟐
                        # output"; nested ⟐ containers carry "/" or ":"
                        # context segments) is the write leg's trunk:
                        # admitted backward from an admitted DML target
                        # when the statement's write leg carries the
                        # searched field — the same gate as the forward
                        # admit, so the trunk joins the closure only when
                        # the statement actually writes the field (the
                        # routed trunk→target write leg needs its own
                        # trunk node — J12-17).
                        if nb_o.get("variable_type") == "virtual_table":
                            _nb_ctx = (nb_o.get("context") or "")
                            if (_nb_ctx.startswith("TOP")
                                    and _nb_ctx[3:].isdigit()
                                    and target_field.lower()
                                    in _dml_write_leg.get(nid, ())):
                                admit = True
                    if fwd:
                        # D2 (2026-08-12): never field-blind — the
                        # statement must actually carry the searched
                        # field. Write edges (INSERT/UPDATE/DELETE/
                        # MERGE) admit only when the statement's write
                        # leg (the DML-edge sources into the target)
                        # writes the searched field; the write→read link
                        # (WRITE_READ) admits only when the reader
                        # statement references the searched field.
                        if (op or "").upper() == "WRITE_READ":
                            _stmt = ((nb_o or {}).get("context") or "TOP"
                                     ).split("/", 1)[0]
                            admit = target_field.lower() in _stmt_field_parts.get(
                                _stmt, ())
                        else:
                            admit = target_field.lower() in _dml_write_leg.get(
                                nb, ())
                elif et == "TABLE_FLOW":
                    # Q1, forward-only: (a) table-like source whose
                    # physical identity is in the chain; (b) VT whose
                    # context is an ancestor-or-equal of a visited field
                    # var's context with the target field part.
                    admit = False
                    if fwd:
                        src_o = occ(nid)
                        if (op or "").upper() in _DML_WRITE_OPS:
                            # D2 (2026-08-12): the table-level write
                            # legs (Phase 1c-extra/1c-direct TABLE_FLOW
                            # edges INTO a DML target, operation = the
                            # DML keyword) are the DML write admit's
                            # twins — same rule: the statement's write
                            # leg must carry the searched field (else a
                            # chain member's identity alone would drag
                            # every DML target of any statement into
                            # every closure).
                            admit = target_field.lower() in _dml_write_leg.get(
                                nb, ())
                        elif src_o is not None and src_o.get(
                                "variable_type") == "virtual_table":
                            sctx = src_o.get("context") or ""
                            for fv in node_map.values():
                                if (fv.get("variable_type") in FIELD_LIKE
                                        and fv.get("id") in visited
                                        and _occ_field_part(
                                            occ(fv.get("id"))) == target_field):
                                    fctx = fv.get("context") or ""
                                    if (fctx == sctx
                                            or fctx.startswith(sctx.rstrip("/") + "/")):
                                        admit = True
                                        break
                        elif src_o is not None and _occ_table_like(src_o):
                            admit = _occ_identity(src_o) in chain
                else:
                    admit = False  # NEVER types and anything unknown
                if admit:
                    visited.add(nb)
                    changed = True
                    _register(nb)

        # ── identity-admission round (owner-holders, physical tables,
        # CTE containers — existing rules, model-sourced) ──
        for nid in list(visited):
            o = occ(nid)
            if not o:
                continue
            if o.get("variable_type") in FIELD_LIKE:
                # Owner-holder admission: the field's owning entity (the
                # model's attribution) and its occurrence labeled
                # source_tables[0] in the var's context (or the nearest
                # ancestor context).
                owner = owner_by_id.get(nid)
                st = o.get("source_tables") or []
                holder = None
                if owner is not None and st and st[0]:
                    holder = _pick_occurrence(pm, owner, st[0],
                                              o.get("context") or "", occ)
                if holder and holder not in visited:
                    visited.add(holder)
                    changed = True
                    _register(holder)
                # The holder's own physical table (holder's st[0] → the
                # entity's bare instance in the holder's context).
                ho = occ(holder) if holder else None
                if ho is not None:
                    hst = ho.get("source_tables") or []
                    if hst and hst[0]:
                        hkey = pm.entity_of_id.get(holder)
                        if hkey is not None:
                            tv = _pick_occurrence(pm, hkey, hst[0],
                                                  ho.get("context") or "", occ)
                            if tv and tv not in visited:
                                visited.add(tv)
                                changed = True
                                _register(tv)
            # Container rule: context segments "CTE{...}" -> the CTE var
            # labeled X (the scope that contains the reads).
            for seg in (o.get("context") or "").split("/"):
                if seg.startswith("CTE{") and "}" in seg:
                    cte_id = _cte_occurrence(pm, seg[4:seg.index("}")], occ)
                    if cte_id and cte_id not in visited:
                        visited.add(cte_id)
                        changed = True
                        _register(cte_id)
        # Issue 3 (same-table physical-identity admission, R19.2 read
        # recognition — ruling 2026-08-11): a BARE TABLE/VIEW instance
        # (physical identity == its own label) whose physical identity
        # matches an in-closure table joins the closure — the statement-2
        # reader `bdm_acc_loan_info_sup@223` (bare FROM, line 223) shares
        # the physical identity of the in-closure writer sup@160 and joins
        # even without an incident walkable edge, so the read instance is
        # always on the flow path (identity comes from extraction-time
        # source_tables/label). Aliases (identity != label) are hop nodes
        # served by ALIAS edges and the ALIAS rule — they do not re-admit
        # themselves here.
        for nid, var in node_map.items():
            if var.get("variable_type") not in ("table", "view"):
                continue
            if nid in visited:
                continue
            o = occ(nid)
            ident = _occ_identity(o) if o is not None else ""
            if ident and ident == (o or {}).get("name") and ident in chain:
                visited.add(nid)
                changed = True
                _register(nid)
    # D1: the fixpoint is capped at 100 rounds (monotone — should never
    # fire); when it does, the closure may be incomplete — surface it in
    # the log instead of silently returning a partial closure.
    if rounds >= 100:
        _log.warning("compute_field_flow fixpoint hit the 100-round cap "
                     "(%d nodes in closure) for %s.%s — closure may be "
                     "incomplete", len(visited), target_table, target_field)
    return visited


def filter_by_field_flow(graph_data, target_table, target_field,
                         table_schemas=None, physical_model=None) -> dict:
    """Filter graph to the strict table.field flow closure (v3.3.140+, L2 only).

    Returns a dict identical to graph_data except nodes = those whose id is in
    the closure, edges = those with both ends in the closure; all other
    top-level keys are kept. I5 (v3.3.145): containment-tagged edges are
    excluded even when both ends are in the closure — nesting is shown by the
    nesting structure, not as flow arrows. An empty closure yields 0 nodes —
    the caller handles the not-in-flow case; this never raises.

    J12-10 stage 3: physical_model is REQUIRED (the walker consumes the
    physical model — see compute_field_flow).
    """
    if not graph_data:
        return graph_data
    closure = compute_field_flow(graph_data, target_table, target_field,
                                 table_schemas, physical_model=physical_model)
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


# ═══════════════════════════════════════════════════════════════════════
# FLOW SOURCE / FLOW TARGETS / NET-FLOW ROLES (R19.1/R19.2/R19.5 —
# user ruling 2026-08-11)
# Additive build-time helpers. Consumed at build time (the L2 node
# assembly), never at render — no reconstruction machinery.
#   flow_source_id()       R19.1: the searched seed's physical table node
#                          (the filtered view's single flow source — the
#                          source is USER-DEFINED by the search, never
#                          inferred; v3.3.140 seed semantics).
#   flow_targets()         R19.2: DML write targets whose write leg
#                          `output → T` lies in the seed's flow closure.
#   classify_flow_roles()  R19.5: full-view (no search) table roles —
#                          net-flow classification over FLOW edges only.
# ═══════════════════════════════════════════════════════════════════════

# Non-flow edge types (R19.5): the identity/containment/padding family.
#   ALIAS  — original → alias identity hop, no data moves
#   SCHEMA — table → column ownership/containment (R19.4)
#   SUBSET — disconnected-component bridge, pure connectivity padding
# TABLE_FLOW is NOT excluded: it is the table-to-table data flow itself
# ("Table feeds output" — dependency_graph Phase 1), and the requirement
# examples pin it in (sup is a waypoint only because the read-into-output
# TABLE_FLOW counts as flow-out). The L2 DML rewrite re-types write legs
# to TABLE_FLOW (stamped category="write") — they count as flow-in to the
# target, as they must. Everything else (REF/TRANSFORM/COMPUTED/
# AGGREGATE/WINDOW/FILTER/JOIN/INDIRECT/CORRELATED/DML/SET_OP/SUBQUERY)
# is flow. The `category` field is deliberately NOT consulted: the L2
# TABLE_FLOW chain edges carry category="structure" yet ARE flow, so the
# edge type is the single discriminator.
NON_FLOW_EDGE_TYPES = {"ALIAS", "SCHEMA", "SUBSET"}
# DML write keywords — extraction-time attribution (dependency_graph
# Phase 1c: MERGE_TARGET vars, and TABLE vars whose defined_in names one).
_DML_WRITE_OPS = ("INSERT", "UPDATE", "DELETE", "MERGE")


def _is_flow_edge(ed: dict) -> bool:
    """R19.5 flow test on one edge dict (raw or L2 shape).

    Every edge type except ALIAS/SCHEMA/SUBSET is flow — TABLE_FLOW
    included (table-to-table flow; the L2 DML rewrite's write legs are
    TABLE_FLOW and must count as flow-in to their target).
    """
    etype = (ed.get("edge_type") or ed.get("relationship") or "").upper()
    return etype not in NON_FLOW_EDGE_TYPES


def classify_flow_roles(edge_list, table_node_ids) -> dict:
    """R19.5 net-flow classification for full-view (no search) table roles.

    A table is a SOURCE when flow out dominates (out-edges > in-edges), a
    TARGET when flow in dominates; balanced (out == in, including 0-0) is
    a WAYPOINT — both roles (e.g. sup: target of output1→sup, source of
    sup→output2). Counted over FLOW edges only (every edge type except
    ALIAS/SCHEMA/SUBSET — the identity/containment/padding family; R19.4
    SCHEMA is not flow), with self-loops excluded. TABLE_FLOW counts —
    the read-into-output legs of bare FROM reads (Issue 3 read
    recognition) are TABLE_FLOW, so read-only tables dominate flow-out
    and classify as sources (R19.1 full-view note), and DML write legs
    (re-typed TABLE_FLOW in the L2 list) count as flow-in to targets.

    Input: the L2 edge list of the FULL view (no search) — the DML value
    edges are already collapsed into the single write leg and merged
    self-loops are gone, so the counting is per physical table. Raw
    full-graph edges work too (same edge-type rule), but raw DML value
    edges are not collapsed — pass the L2 list for exact roles. Both
    wrapped {"data": {...}} and flat edge dicts work. `table_node_ids`
    is the caller's table node set (the L2 compound keepers).

    Returns {node_id: "source" | "target" | "waypoint"} — one entry per
    passed table node id.
    """
    out_deg = {}
    in_deg = {}
    for e in edge_list:
        ed = e.get("data", e)
        src, tgt = ed.get("source"), ed.get("target")
        if not src or not tgt or src == tgt:
            continue
        if not _is_flow_edge(ed):
            continue
        if src in table_node_ids:
            out_deg[src] = out_deg.get(src, 0) + 1
        if tgt in table_node_ids:
            in_deg[tgt] = in_deg.get(tgt, 0) + 1
    roles = {}
    for nid in table_node_ids:
        o, i = out_deg.get(nid, 0), in_deg.get(nid, 0)
        if o > i:
            roles[nid] = "source"
        elif i > o:
            roles[nid] = "target"
        else:
            roles[nid] = "waypoint"
    return roles


def flow_targets(graph_data, target_table, target_field,
                 physical_model=None) -> set:
    """R19.2 flow targets of the searched table.field — J12-10 stage 3:
    model-backed decision procedure (the model's roles and DML edges
    carry the truth the display used to reconstruct).

    DECISION PROCEDURE (user ruling 2026-08-11): T is a flow target iff
      (a) T's entity carries the write or merge_target role (the model's
          extraction-time DML attribution — mirror of dependency_graph
          Phase 1c), AND
      (b) T's write leg — the DML edge from a virtual source entity into
          T — has both raw endpoints in the seed's flow closure (the
          compute_field_flow reachability walk).

    physical_model is REQUIRED. Operates on the model's edges; returns
    the set of raw node ids of the target tables (the caller maps them
    to the L2 compound keepers via id_map). A table can be BOTH target
    and waypoint (sup: target of output1→sup, source of sup→output2) —
    roles are per-edge/path, unified by physical identity; the decision
    procedure here is purely mechanical.
    """
    if physical_model is None:
        raise TypeError(
            "flow_targets: physical_model is required (J12-10 stage 3)")
    if not graph_data or not target_table or not target_field:
        return set()
    closure = compute_field_flow(graph_data, target_table, target_field,
                                 physical_model=physical_model)
    if not closure:
        return set()
    write_keys = {key for key, tbl in physical_model.tables.items()
                  if tbl.roles & {"write", "merge_target"}}
    out = set()
    for M in physical_model.edges:
        if M.edge_type != "DML":
            continue
        if (M.operation or "").upper() not in _DML_WRITE_OPS:
            continue
        src_tbl = (physical_model.tables.get(M.source[0])
                   if M.source[0] else None)
        if src_tbl is None or src_tbl.kind != "virtual":
            continue
        if M.target[0] not in write_keys:
            continue
        if M.source_id in closure and M.target_id in closure:
            out.add(M.target_id)
    return out


def flow_source_id(graph_data, target_table, physical_model=None) -> str | None:
    """R19.1 exposure: raw id of the searched table's physical table node
    — J12-10 stage 3: resolved through the model's occurrence index (var
    order preserved) instead of a graph-node scan; semantics unchanged
    (the first table/view occurrence labeled exactly target_table).

    The filtered L2 flow view's single flow source is the searched seed —
    a USER-DEFINED source (the search), never inferred. This helper only
    exposes the seed's table node so the display can mark it.
    """
    if physical_model is None:
        raise TypeError(
            "flow_source_id: physical_model is required (J12-10 stage 3)")
    if not graph_data or not target_table:
        return None
    for vid, o in physical_model.occurrences.items():
        if o.get("variable_type") in ("table", "view") and o.get("name") == target_table:
            return vid
    return None
