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
    # ROW_FLOW (2026-08-13, #226): the R29 row-selection BRIDGE — emitted
    # by compute_field_flow AFTER the closure fixpoint (an output edge,
    # never a walk input). It propagates the searched field's ROW-SELECTION
    # (its WHERE/JOIN usage) into the downstream statement's rows, where
    # the field's VALUE does NOT flow — never walkable, never value-
    # carrying (both flags False).
    "ROW_FLOW":   {"propagates_value": False, "always_bidir": False},
}

# Production edges "produce" a value in the target — derived from EDGE_SEMANTICS,
# shared with the L1 builder (app/services/l1_builder.py).
PRODUCTION_EDGES = {k for k, v in EDGE_SEMANTICS.items() if v["propagates_value"]}
# Structural edges always bidirectionally followed by the BFS.
ALWAYS_BIDIR_EDGES = {k for k, v in EDGE_SEMANTICS.items() if v["always_bidir"]}

# ── #399 option b′ (2026-08-29): alias-aware W1 seed expansion ──
# The switch IS the feature: the W1 downstream seed path below gates the
# alias-key union on it, so flipping it to False restores the pre-#399
# seeding exactly (test_alias_seed_expansion.py flips it to prove
# additivity for searches that already work). False disables the expansion
# entirely — an alias-named search target stays `search_matched: false`.
_ALIAS_SEED_EXPANSION = True


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

# ── R46c (v3.3.195, AD3 §Q2): the value-cone admission gate ──
# Chip → chip edge types the SERVED closure's value cone propagates over.
# Conspicuously absent: TABLE_FLOW (the box-level chain leg — cross-
# statement value flow rides it and a chip cone over it does not exist;
# AD3 Q1 measured the naive cone collapsing `bdm ↓ SUP_M` 27 → 8 edges),
# SCHEMA (belongs-to), FILTER/JOIN (row-selection), INDIRECT/CORRELATED
# (scope), SUBSET (padding), ROW_FLOW (an output bridge, never an input).
CONE_EDGES = {"REF", "COMPUTED", "TRANSFORM", "AGGREGATE", "WINDOW",
              "ALIAS", "SET_OP", "SUBQUERY", "DML"}

# The switch IS the feature (mirror of `_ALIAS_SEED_EXPANSION`): the gate
# runs inside `compute_field_flow` right after the closure fixpoint, so
# flipping it to False restores the pre-R46c served closure exactly —
# which is what `test_v4_walker_batch.py` uses for the before/after pins
# (own-occurrence recall floors, the no-shrink/casing tripwires).
_VALUE_CONE_GATE = True

# FSC-1's switch (mirror of the two above): False restores the pre-FSC-1
# seeding — an owner-less bare column stays unseeded and its pair is dead
# at L2 (`test_v4_walker_batch.py::test_fsc1_ownerless_seed`).
_OWNERLESS_SEED = True

# The J12-20 member switch: the SEARCHED table's own compound stays whole
# (its co-filter sibling is a documented closure member, PL @265 / DL @561).
# False reduces the gate to AD3's literal four chip rules.
_OWN_BOX_CHIPS = True

# V7's two switches (mirror of the three above), both inside the R-GATE:
#   `_PHANTOM_COPY_GATE` — False restores the cross-owner same-name REF
#   copy as a traversable cone edge (the G1 `src_b` residual comes back).
#   `_DERIVED_CONTAINER_CHIPS` — False restores the derived container's
#   projection read and its alias handle as droppable (G1's `s1`@6 goes
#   dark again).
_PHANTOM_COPY_GATE = True
_DERIVED_CONTAINER_CHIPS = True


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


def _is_spurious_ref_copy(ed, src_node) -> bool:
    """Phase-3 REFERENCE edge whose SOURCE is a subquery output column.

    A Virtual-Table output column (source_tables[0] starting with '⟐') is
    the RESULT of a subquery — its value flows OUT to the parent query,
    never INTO same-level sibling reads. The last-writer-wins
    `full_col_index` name match wires such an output column as the "source"
    of a same-named read in a DIFFERENT table (lending_ref@22 →
    lending_ref@13/@26/@50), producing the CR10 LFS6/LFS7 self-loops. The
    edge stays in the graph so the walker can bridge the subquery
    structure, but is NOT emitted as a flow edge. All other REFERENCE
    edges (real-table same-name reads, renamed copies, CONCAT/join-key
    operands into expressions) are unaffected.
    """
    d = ed.get("data", ed) if isinstance(ed, dict) else ed
    if d.get("relationship") != "REF":
        return False
    if (d.get("operation") or "").upper() != "REFERENCE":
        return False
    st = (src_node or {}).get("source_tables") or []
    return bool(st) and str(st[0]).startswith("⟐")


def _fold(s) -> str:
    """Case fold for SQL identifier identity (R46e, H7 §4).

    SQL identifiers are case-insensitive (F5/R2.10, ISSUE-4, #288, K4
    item 5), so the searched spelling and an occurrence's spelling are the
    SAME identity whatever casing each was written in. `.lower()` is the
    fold of every layer that feeds this walker (`resolve_name_ci`, the
    folder_index key space, `_dml_write_leg`/`_stmt_field_parts`/
    `_cont_cols`) and is provably equivalent to `.casefold()` on this
    corpus (AD2-E: 0 fold-divergent identifiers in the sample corpus — a
    divergence needs a non-`iff`-foldable character pair, i.e. ß/ς/ﬁ-class).
    ONE fold, BOTH sides of every comparison — never mix `.lower()` and
    `.casefold()` inside one expression (the mixed form is unreadable, not
    wrong, and it is how the two conventions drifted apart before).

    Shared with `l1_builder.detect_role` and
    `dataflow_service._filter_l1_by_lineage` (import, never a second
    spelling). NOT applied to the dead-legacy `compute_field_lineage` /
    `filter_relevant` pair — see the H7 §7-3 ruling in
    wiki/CODE_REVIEW_PENDING (delete-or-fold decision to follow).
    """
    return (s or "").lower()


def _occ_field_part(o) -> str:
    """Last dotted segment of an occurrence's label — the field name
    proper (mirror of the retired display-side _field_part)."""
    return str((o or {}).get("name") or "").rsplit(".", 1)[-1]


def _occ_table_like(o) -> bool:
    """Table-like occurrence: declared source types, or resolved
    source_tables (mirror of the retired display-side _table_like)."""
    return (o.get("variable_type") in
            {"table", "view", "cte", "virtual_table", "subquery",
             "merge_target", "function_table"}
            or bool(o.get("source_tables")))


def _occ_identity(o) -> str:
    """Physical identity of an occurrence (chain matching key): the
    attributed source table, else the resolved table_name/label (mirror
    of the retired display-side _identity)."""
    st = o.get("source_tables") or []
    if st:
        return st[0]
    return o.get("table_name") or o.get("name") or ""


def _ctx_within(inner: str, outer: str) -> bool:
    """True when context `inner` is `outer` itself or nested inside it —
    the equal / '/'-nested / ':'-nested relation the scope checks use."""
    return (inner == outer or inner.startswith(outer + "/")
            or inner.startswith(outer + ":"))


_DERIVED_CONTAINER_TYPES = ("subquery", "virtual_table")


def _cte_projects_target(pm, occ, holder_id: str, target_lower: str,
                         scratch: dict, admitted: set | None) -> bool:
    """G7 RC-C half 1 — the holder CTE is the searched field's own birth
    container AND that birth is on the value chain the closure is walking.

    Two model facts must both hold (AD1 option (a) AND option (b); neither
    alone is safe):

      (a) the CTE PROJECTS the searched field — a SCHEMA TABLE_COLUMN edge
          from the holder CTE to a field-like occurrence whose field part is
          the searched field. That edge is the extractor's own
          "this CTE's output column" evidence (Phase 4b), so the CTE is
          where the searched field is defined/aliased, never a container
          that merely reads a same-named column of some other table;

      (b) the model carries a value edge between that projection occurrence
          and an ADMITTED node (the projection is itself in the closure, or
          a FIELD_LAND neighbour of it is). Name-only matching (a) without
          (b) is the co-scope flood G1 closed: a CTE over ten sources that
          happens to project a same-named column would lend its scope to it.

    `admitted` is the closure built so far — the value-provenance qualifier
    is fixpoint-relative by design, so it is NOT memoized (the memo below
    only ever stores the derived-single branch, which is closure-free).
    """
    if admitted is None:
        return False
    proj = scratch.get("cte_projections")
    val = scratch.get("value_adjacency")
    if proj is None or val is None:
        proj = scratch["cte_projections"] = {}
        val = scratch["value_adjacency"] = {}
        for E in pm.edges:
            if E.containment:
                continue
            if (E.edge_type == "SCHEMA"
                    and (E.operation or "").upper() == "TABLE_COLUMN"):
                proj.setdefault(E.source_id, []).append(E.target_id)
            if E.edge_type in FIELD_LAND:
                val.setdefault(E.source_id, set()).add(E.target_id)
                val.setdefault(E.target_id, set()).add(E.source_id)
    connected = False
    for vid in proj.get(holder_id, ()):
        o = occ(vid) or {}
        if o.get("variable_type") not in FIELD_LIKE:
            continue
        if _fold(_occ_field_part(o)) != target_lower:
            continue
        if vid in admitted or (val.get(vid, set()) & admitted):
            connected = True
            break
    return connected


def _holder_is_derived_single(pm, occ, holder_id: str, target_lower: str,
                              memo: dict | None = None,
                              admitted: set | None = None) -> bool:
    """True when `holder_id` is a DERIVED PRODUCT of the searched table.

    R44 Fix A (2026-08-28.9), stage 1: the derived-product round may admit
    a field occurrence only when its holder actually delivers the searched
    table's value. Three holders can:

      1. the read itself — an occurrence whose physical identity IS the
         target (`_occ_identity(_ho) == target`), the alias read / the
         derived pass-through's own holder;
      2. a derived container (SUBQUERY / VIRTUAL_TABLE) whose scope reads
         EXACTLY ONE original physical TABLE/VIEW and that read's identity
         is the target — the extractor's own `derived_single` rule, mirrored
         here so the closure admits exactly the values the family-2 twins
         were minted for;
      3. G7 RC-C (2026-08-28.10): a CTE that PROJECTS the searched field
         while that projection is value-connected to the closure — the
         field's own birth container. RC-C's dark lines all sat inside
         multi-source CTEs (RFN's TEMP_BDM_ACC_LOAN_INFO_01/_02 read 10+
         physical tables), so the single-source test above can never admit
         them; what makes such a holder a product of the SEARCHED table is
         that the searched field is born there and its birth sits on the
         value chain the closure is walking (the audit evidence: the model
         carries `P5.HKZH@364 → REPAY_ACCT_NO@364`, the field's own birth).
         Pass `admitted` (the closure so far) to enable this branch.

    A container with two or zero sources — or one whose single source is a
    DIFFERENT table — must not lend its scope to a same-named column of the
    searched table. Callers gate on this for DERIVED-CONTAINER holders only
    (see the round comment for why a physical holder stays on the
    scope-presence rule); CTE holders take branch 3 when `admitted` is
    given and stay on the scope-presence rule when it is not.

    Scope = the holder's own context plus its '/'- and ':'-nested bodies.
    An EXISTS/NOT-EXISTS body under the holder is row-SELECTION, not a row
    source — its reads never make the container multi-source (PL's `p2`
    wraps bdm_fin_lrr_key_base_info and filters through
    `exists (select 1 from ODS_CDP_GDC_TABLE_COA_LIST …)`).

    Memoized per holder id + target for the length of one closure
    computation (the fixpoint re-enters the round on every round) — but only
    for the closure-free branches; the CTE branch is evaluated fresh (its
    answer depends on the closure built so far).
    """
    if memo is None:
        memo = {}
    ho = occ(holder_id) or {}
    if ho.get("variable_type") == "cte" and admitted is not None:
        # closure-relative — never memoized
        return _cte_projects_target(pm, occ, holder_id, target_lower, memo,
                                    admitted)
    key = (holder_id, target_lower)
    cached = memo.get(key)
    if cached is not None:
        return cached
    result = False
    if ho.get("variable_type") in _DERIVED_CONTAINER_TYPES:
        hctx = ho.get("context") or ""
        phys = set()
        for _vid, o in pm.occurrences.items():
            if o.get("variable_type") not in ("table", "view"):
                continue
            # originals only — an alias occurrence carries st[0] = another
            # table's name; a physical read carries its own name (I2
            # self-attribution) or nothing at all.
            _st = o.get("source_tables") or []
            if _st and _fold(_st[0]) != _fold(o.get("name")):
                continue
            tctx = o.get("context") or ""
            if not _ctx_within(tctx, hctx):
                continue
            rel = tctx[len(hctx):].lstrip("/:")
            if any(sg.startswith("exists")
                   for sg in rel.replace("/", ":").split(":") if sg):
                continue
            phys.add(_fold(_occ_identity(o)))
        result = len(phys) == 1 and target_lower in phys
    memo[key] = result
    return result


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
                       table_schemas=None, physical_model=None,
                       direction="downstream",
                       row_flow_out=None, _flow_memo=None) -> set:
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

    R29 (2026-08-12) `direction` — the QUERY direction, per the formal
    definition (wiki/DATAFLOW_FORMAL_DEFINITION.md §Field-Level Data
    Flow). Default "downstream" = the effect-scope closure walk above
    (W1-W6 + identity admissions + the R29 row-level continuation rounds
    — the closure is no longer byte-identical to the pre-R29 walk since
    the R29 walker landed, c037885). "upstream" = the TRANSITIVE
    WRITING chain of the field — where the field's value comes from —
    with the upstream rule set:

      U1 seeds = the field's WRITE instances only — the DML write
         targets (occurrences that are the targets of the field's write
         legs) whose statement's write leg carries the searched field
         (the D2 _dml_write_leg index, matched case-insensitively —
         PARTITION columns arrive in the SQL's own casing). Read
         instances are NOT seeds and are NEVER admitted in upstream
         mode — a script that only READS the field (SUP_M ×
         bdm_acc_loan_info.data_dt) yields an EMPTY upstream closure.
      U2 expand ONLY backward (the fwd=False adjacency tuples — the
         producing side of the admitted nodes) over production edges:
         FIELD_LAND backward (target → its producing source; REF/READ
         field→holder edges are consumer-side — never producers),
         ALIAS backward (alias → its original), DML backward (write
         target → its write-leg sources, write-leg-gated on the written
         field: the statement's output VT and the field-like var
         carrying the searched field part), TABLE_FLOW backward along
         the written legs (operation = the DML keyword; the leg source
         joins only when its physical identity is already in the chain
         — the write statement's OTHER input tables stay out:
         field-level, not statement-level).
      U3 NEVER walked upstream: FILTER, JOIN (the seed-zone rule is
         downstream-only), SCHEMA, SUBQUERY, SET_OP, CORRELATED,
         INDIRECT, SUBSET, and read edges (REF with operation=READ).
      U4 literals are chain ENDS — admitted (write-leg sources are
         FIELD_LIKE), no producers to expand.
      U5 identity admissions, owner resolution, container rule: same
         machinery, direction-free — EXCEPT the Issue-3 bare-instance
         admission, which is read-recognition (R19.2) and would drag
         read instances into the writing chain — downstream-only.
      U6 termination: fields whose producer is a literal, or fields
         with no write instance in the script (external source tables).

    physical_model is REQUIRED (TypeError when None). table_schemas is
    accepted for signature parity with compute_field_lineage but unused.
    Returns the set of node ids in the strict closure.

    R44 (2026-08-28, user ruling "covering all occurrences of the target
    field is the PURPOSE of flow-only") — downstream-only admission
    extensions, all ADDITIVE (existing closures only gain members):
      R0  W1 entity match is case-insensitive (CR11 mirror) — the
          extractor canonicalizes physical spelling by majority vote.
      R1  write-completion: an in-closure OUTPUT projection of the
          searched field carries its statement's write by itself (a
          constant `NULL AS Reserved_Field3` owns no DML edge) — the
          statement's ⟐ output VT is admitted so the table-level write
          leg renders; the _dml_write_leg index is extended with the
          CONSTANT projections' field parts (reads stay Phase-1c's
          domain — duplicating them amplifies the R29 effect-column
          continuation over the whole projection list).
      R3  derived-product admission: every field var carrying the target
          field part whose HOLDER (the owner entity's occurrence labeled
          source_tables[0], READ occurrences preferred over DML targets)
          reads the searched table inside its own scope is an occurrence
          of the searched field — derived pass-throughs (`p2.product`,
          `a.rn`, `p8.X5GMAB`), alias reads (`c.p_dt`), and subquery
          births (`row_number() … AS rn` on ⟐a) alike; the feeding read
          joins too (the value's origin and the display compound the
          extractor's physical-attributed twins parent under).

    R46c (2026-08-31, AD3 §Q2): after the fixpoint, the closure runs
    through the VALUE-CONE ADMISSION GATE (downstream only) — the
    co-written projection chips, the foreign statement trunks and the
    join-partner predicates the R29 continuation had swept in are no
    longer served. Chips = the W1 seeds ∪ same-name chips on an admitted
    box ∪ the forward chip-cone over CONE_EDGES ∪ the write-slot's direct
    producers; boxes = the owners of admitted chips plus the box
    endpoints of FIELD-JUSTIFIED legs (D2 write leg, R29 carry, W6b
    nested-VT context, W3 alias, W4 own-line predicate). Own-occurrence
    anchoring is guarded — the gate refuses to drop the sole anchor of an
    own occurrence (see the gate comment at the call site for the full
    rule, and `tests/test_v4_walker_batch.py` for the pins).

    ROW_FLOW (2026-08-13, #226): when `row_flow_out` is a list (not
    None) AND direction is "downstream", the closure fixpoint is
    followed by the row-level-flow bridge emission: the R29 continuation
    rounds may admit continuation TARGETS (the far CTEs/reads) as NODES
    with no edge connecting them back to the searched field's source —
    the only link is a containment SCHEMA edge (container → nested VT),
    excluded from the walk (I5). Every such containment edge crossing
    the seed's connected component (the value-flow side, holding the
    nested VT) to a DISCONNECTED continuation component (the container
    side) emits a ROW_FLOW edge from the nested VT to the container —
    the row-selection bridge that makes the L2 graph a single connected
    flow. Never fires when the closure is already connected (every
    benchmark seed: comps == 1, zero cross-component containment edges —
    the Jaccard gate stays byte-identical). Appends edge dicts (raw
    graph shape) to `row_flow_out`; the returned node set is unchanged.

    PERF (v3.3.194) `_flow_memo`: an optional CALLER-SCOPED dict (one per
    request — never module state, so no cross-request staleness and
    nothing shared between threads). One request runs this walker up to
    four times over the SAME graph with the same (table, field,
    direction) — the response-level filter, the L2 flow view's filter and
    the flow-role pass (directly and through flow_targets) — and the walk
    is a pure function of those inputs. Shaped
    `{id(graph): (graph, {(table, field, direction): (closure, bridges)})}`:
    each entry keeps the graph object itself alive, so its id can never be
    recycled onto a different graph while an entry lives (the `is` guard
    is belt-and-braces). A hit returns a fresh set and re-fills
    `row_flow_out`, so the caller's output arguments behave exactly as on
    a full walk.
    """
    if physical_model is None:
        raise TypeError(
            "compute_field_flow: physical_model is required (J12-10 "
            "stage 3 — the walker consumes the physical model)")
    if not graph_data:
        return set()
    if _flow_memo is not None:
        _entries = _flow_memo.get(id(graph_data))
        if _entries is not None and _entries[0] is graph_data:
            _hit = _entries[1].get((target_table, target_field, direction))
            if _hit is not None:
                if isinstance(row_flow_out, list):
                    row_flow_out.extend(_hit[1])
                return set(_hit[0])
    nodes = graph_data.get("nodes", []) or []

    node_map = {}
    for n in nodes:
        nd = n.get("data", n)
        node_map[nd.get("id")] = nd

    pm = physical_model
    occ = pm.occurrence
    # R46e: the folded search identity — hoisted once, used on BOTH sides
    # of every identity comparison below. `_tt` is the searched TABLE,
    # `_tf` the searched FIELD; nothing in this function compares a raw
    # identifier against them again.
    _tt = _fold(target_table)
    _tf = _fold(target_field)

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
    # (Built before the seed selection: R29 upstream seeds are the DML
    #     write targets — the index gates them.)
    _dml_write_leg = {}
    for _E in pm.edges:
        if _E.edge_type != "DML":
            continue
        if (_E.operation or "").upper() == "WRITE_READ":
            continue
        _so = occ(_E.source_id)
        if _so is not None:
            _part = _fold(_occ_field_part(_so))
            if _part:
                _dml_write_leg.setdefault(_E.target_id, set()).add(_part)
    # R44 class 1 (2026-08-28, user ruling "covering all occurrences of the
    # target field is the PURPOSE of flow-only"): a statement's SELECT
    # PROJECTION that carries no read (a constant — `NULL AS Reserved_Field3`)
    # has no DML edge of its own, so its written column never entered the
    # write-leg index and the D2 gate rejected the statement's write target.
    # The occurrence IS the write: every CONSTANT projection (is_output,
    # field-like, NO source_columns — exactly the vars dependency_graph
    # Phase 1c cannot link) adds its field part to that statement's DML
    # targets' legs (targets reached from the statement's own ⟐ output VT).
    # Read-carrying projections are NOT added here: they already own DML
    # edges, and duplicating them into the leg would amplify the R29
    # effect-column continuation over the whole projection list (DigL
    # data_dt closure 9 → 41 nodes — every co-written column pulling its
    # FILTER/JOIN scope in).
    # PERF (v3.3.194): the statement's ⟐-VT write edges grouped by their
    # context — the per-occurrence scan below used to re-filter ALL model
    # edges for EVERY constant projection (O(occurrences x edges)); the
    # grouped form walks the edges once and yields the same (target, part)
    # pairs in the same per-occurrence edge order.
    _dml_vt_edges_by_ctx = {}
    for _E in pm.edges:
        if _E.edge_type != "DML":
            continue
        if (_E.operation or "").upper() == "WRITE_READ":
            continue
        _sv = occ(_E.source_id)
        if _sv is None:
            continue
        if _sv.get("variable_type") != "virtual_table":
            continue
        _dml_vt_edges_by_ctx.setdefault(_sv.get("context") or "",
                                        []).append(_E)
    for _vid, _o in pm.occurrences.items():
        if not _o.get("is_output"):
            continue
        if _o.get("variable_type") not in FIELD_LIKE:
            continue
        if _o.get("source_columns"):
            continue          # read-carrying projection — Phase 1c's domain
        _part = _fold(_occ_field_part(_o))
        _ctx = _o.get("context") or ""
        if not _part or not _ctx:
            continue
        for _E in _dml_vt_edges_by_ctx.get(_ctx, ()):
            _dml_write_leg.setdefault(_E.target_id, set()).add(_part)
    _stmt_field_parts = {}
    for _vid, _o in pm.occurrences.items():
        _stmt = (_o.get("context") or "TOP").split("/", 1)[0]
        if not _stmt.startswith("TOP"):
            continue
        _part = _fold(_occ_field_part(_o))
        if _part:
            _stmt_field_parts.setdefault(_stmt, set()).add(_part)

    # ── R29 row-level continuation pre-scan (2026-08-12, user ruling):
    # a statement that USES the searched field (its row-selection —
    # WHERE/JOIN) carries the effect into EVERYTHING it writes (even
    # literal columns — the usage selects the rows the statement
    # emits); the chain continues while a later statement's row-
    # selection uses a column written in the effect, and terminates at
    # write targets nothing further uses.
    #   _cont_cols[table] — the columns any statement's FILTER/JOIN
    #     row-selects on that table (the effect's continuation
    #     carriers: the sup data_dt filter @223 continues the
    #     iiapty/lending_ref chains into the rrcdm write @211).
    #   _cte_top[cte_var] — the owning TOP statement of each CTE
    #     container (CTE-interior usages belong to the statement that
    #     defines the CTE — the join keys at CTE{loan_final} select the
    #     sup write's rows).
    _cont_cols = {}
    for _E in pm.edges:
        if _E.edge_type not in ("FILTER", "JOIN"):
            continue
        for _ep in (_E.source_id, _E.target_id):
            _eo = occ(_ep)
            if _eo is None or _eo.get("variable_type") not in FIELD_LIKE:
                continue
            _part = _fold(_occ_field_part(_eo))
            if _part:
                _cont_cols.setdefault(_fold(_occ_identity(_eo)),
                                      set()).add(_part)
    _cte_top = {}
    for _vid, _o in pm.occurrences.items():
        if _o.get("variable_type") == "cte":
            _ctx = (_o.get("context") or "").split("/", 1)[0]
            if _ctx.startswith("TOP"):
                _cte_top[_vid] = _ctx

    def _stmt_of(_o):
        """The owning TOP{stmt} of an occurrence — CTE-interior usages
        belong to the statement that defines the CTE."""
        _top = ((_o or {}).get("context") or "").split("/", 1)[0]
        if _top.startswith("TOP"):
            return _top
        if _top.startswith("CTE{") and "}" in _top:
            _cvid = _cte_occurrence(pm, _top[4:_top.index("}")], occ)
            if _cvid is not None:
                return _cte_top.get(_cvid)
        return None

    # ── W1: seeds — occurrences of the PhysicalFields named target_field
    # on the searched name's entities. target_keys = every entity named
    # target_table (physical tables key by name; per-scope containers by
    # (name, context) — the union mirrors the display's name-based owner
    # match). ──
    # R29 upstream (U1): seeds are the field's WRITE instances only —
    # the DML write targets (occurrences that are the targets of the
    # field's write legs) whose statement's write leg carries the
    # searched field (the _dml_write_leg index, matched case-
    # insensitively). Read instances are NOT seeds in upstream mode.
    # R46e: the entity-name match is folded on BOTH sides (`_tt`) —
    # H7 site 960 (was an exact comparison papered over by `_tkeys_ci`).
    # (Built before the seed block: FSC-1's owner-less test reads it.)
    owner_by_id = {}
    for (_okey, _fname), _fld in pm.fields.items():
        for _vid in _fld.occurrence_ids:
            owner_by_id[_vid] = _okey
    target_keys = {k for k, t in pm.tables.items() if _fold(t.name) == _tt}
    # The searched TABLE's entity set, used by the R46c gate as the "own
    # box" test (`target_keys ∪ _tkeys_ci ∪ _alias_keys` — the R46a
    # seed-claim set, one definition).
    _alias_keys: set = set()
    seeds = set()
    if direction == "upstream":
        for E in pm.edges:
            if E.edge_type != "DML":
                continue
            if (E.operation or "").upper() == "WRITE_READ":
                continue
            tgt_tbl = pm.tables.get(E.target[0]) if E.target[0] else None
            # CR11: case-insensitive — field-part logic lowercases, so the
            # table-name comparison must too (a searched-table casing
            # mismatch otherwise misses the write-target seeds).
            if tgt_tbl is None or _fold(tgt_tbl.name) != _tt:
                continue
            if _tf in _dml_write_leg.get(E.target_id, ()):
                seeds.add(E.target_id)
    else:
        # R44 rule 0: the entity-name match is case-insensitive (CR11
        # mirror of the upstream seed rule) — the extractor canonicalizes
        # physical-table spelling by majority vote, so a searched
        # 'ods_hub_ssinrtp' must find the entity spelled 'ODS_HUB_SSINRTP'
        # (a case mismatch previously yielded NO seeds and the not-in-flow
        # full-graph fallback).
        _tkeys_ci = {k for k, t in pm.tables.items()
                     if _fold(t.name) == _tt}
        # #399 option b′ (2026-08-29): the searched TABLE part may name a
        # SQL ALIAS (`a.data_dt`, `SSALSFP.ALCBP1`) rather than an entity.
        # An alias is never an entity (build_physical_model resolves alias
        # occurrences onto their canonical entity and records them only in
        # `alias_by_var_id`), so the entity probes find nothing to seed from
        # and the walker seeded from NOTHING — an empty closure, the
        # not-in-flow banner and the full-graph fallback (18 of the 21 S1
        # not-in-flow L2 fetches). DOWNSTREAM only: the upstream branch
        # above seeds from DML write targets keyed by entity name and is
        # API-unreachable since K4 ruling 4.
        #
        # Expansion: union the canonical ENTITY keys of every ALIAS
        # occurrence whose name casefolds to the searched table. Per-
        # occurrence truth only — never the label-keyed alias map
        # (physical_model pass 0), which is first-wins per script and
        # provably misses bindings (the derived `t` in RFN) and
        # mis-resolves others. The target is the alias's OWNING ENTITY
        # whatever its kind (physical, CTE or derived container) —
        # resolving to "the physical table" is measured impossible (9/12
        # S1 targets workspace-ambiguous, 2/12 CTE-owned).
        #
        # GATE (field-aware): expand ONLY when NO entity named the searched
        # table HOSTS the searched field — a bare "no entity named X" gate
        # wrongly preempts RFN `P1.INT_OD_DT`, where a subquery container
        # happens to be named `P1` but hosts no INT_OD_DT. A search that
        # already has its host keeps it (test 1: a real table named `a`
        # beats the alias `a`), so every working path is untouched — the
        # in-flow closures stay byte-identical (the Jaccard-gate /
        # L2-snapshot promise).
        #
        # AMBIGUITY: one alias name may bind to several owning entities in
        # ONE statement (the RFN `t.acct_no` shape — CTE `w` AND physical
        # `lbl_fin`). ALL of them join the seed set: the union closure.
        # Never "pick none" (that is today's full-graph fallback) and never
        # "pick one" (that silently drops the other owner's compound).
        if _ALIAS_SEED_EXPANSION:
            for _avid, _akey in pm.alias_by_var_id.items():
                _ao = occ(_avid)
                if _ao is not None and _fold(_ao.get("name")) == _tt:
                    _alias_keys.add(_akey)
            if _alias_keys:
                # The FIELD-AWARE gate: an entity named the searched table
                # preempts only when it actually HOSTS the searched field.
                _named = target_keys | _tkeys_ci
                _hosted = any(tkey in _named and _fold(fname) == _tf
                              for (tkey, fname) in pm.fields)
                if not _hosted:
                    target_keys |= _alias_keys
                    _log.info(
                        '#399: alias seed expansion for %s.%s — '
                        'owning entities %s', target_table, target_field,
                        sorted(pm.tables[k].name for k in _alias_keys
                               if k in pm.tables))
        for (tkey, fname), fld in pm.fields.items():
            if (tkey not in target_keys and tkey not in _tkeys_ci) \
                    or _fold(fname) != _tf:
                continue
            for vid in fld.occurrence_ids:
                o = occ(vid)
                if o is not None and o.get("variable_type") in FIELD_LIKE:
                    seeds.add(vid)

        # ── FSC-1 (v3.3.195): the J12-9 owner-agnostic seed ──
        # A bare column in a multi-table FROM has no model owner: no
        # PhysicalField names it (the extractor cannot attribute it), so the
        # W1 loop above finds NO seed and the pair is dead at L2 — 946
        # no_flow pairs corpus-wide, 923 of them with in-scope occurrences
        # (25 tpcds_qualified scripts were 100% dead). The DISPLAY already
        # marks such a chip `is_target` (the owner-agnostic
        # `_field_part_match_ids` J12-9 predicate); the closure refused it.
        # Seed from the occurrence, not the owner: every field-like
        # occurrence carrying the searched field part that the model could
        # NOT attribute to any entity. Gated on "no seed at all" — the
        # moment the searched table's own entities host the field, the W1
        # path owns the seeding and an owner-less same-name column of
        # another table stays out (the phantom-seed defect AD3 rejected).
        if not seeds and _OWNERLESS_SEED:
            for _vid, _o in pm.occurrences.items():
                if _o.get("variable_type") not in FIELD_LIKE:
                    continue
                if _fold(_occ_field_part(_o)) != _tf:
                    continue
                if _vid in owner_by_id or _o.get("source_tables"):
                    continue          # attributed — never an owner-less bare
                seeds.add(_vid)
            if seeds:
                _log.info(
                    'FSC-1: owner-agnostic seed for %s.%s — %d bare '
                    'occurrence(s), no model owner', target_table,
                    target_field, len(seeds))

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
        # G7 RC-C (2026-08-28.10): the container PROVENANCE bridge rides the
        # same one-way rule. Its direction is value direction (the
        # container's output column → the reader that consumes it), so
        # "forward" is producer → reader; the closure needs the OTHER half —
        # admit the container's column from a consumer — which is exactly
        # the reverse-read rule below (plus its searched-field exception).
        # Riding the read rule is what keeps the bridge from fanning the
        # container's column back out to its sibling readers (a plain
        # REFERENCE edge here grew RFN reserved_field9's closure 16 → 267).
        # X1 correction: the PROVENANCE edge is stored producer→reader
        # (source=producer, target=reader), so read=True admits its FORWARD
        # (producer→reader) half unconditionally and gates only the reverse
        # (reader→producer) half on the searched field — the value-correct
        # direction. (The old comment's "consumer to producer" was inverted.)
        read = bool(E.edge_type == "REF"
                    and E.operation in ("READ", "PROVENANCE"))
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
    # R46e: the identity chain is folded on BOTH sides — `chain` is seeded
    # with the folded searched table and every registration folds too, so
    # the set never becomes the mixed-fold set that made closures
    # casing-dependent (H7 sites 1107/1113/1121).
    chain = {_tt}
    for sid in seeds:
        o = occ(sid)
        if o is not None and _occ_table_like(o):
            ident = _occ_identity(o)
            if ident:
                chain.add(_fold(ident))

    def _register(nid):
        """Record a table-like admission's identity into the chain."""
        o = occ(nid)
        if o is not None and _occ_table_like(o):
            ident = _occ_identity(o)
            if ident:
                chain.add(_fold(ident))

    # ── R46c: the gate itself (nested — it reads the walk's own indexes;
    # called once, after the fixpoint, see the call site below) ──
    def _rg_chip(v):
        _o = occ(v)
        return (_o is not None and _o.get("variable_type") in FIELD_LIKE)

    def _rg_box_key_of(k):
        """Entity key → hashable box key (the per-scope containers are
        keyed by (name, context) tuples)."""
        return k if isinstance(k, str) else "\x00".join(str(x) for x in k)

    def _rg_box_key(v):
        """The display compound that renders `v` — a field chip renders on
        its OWNER entity's box, a table-like var on ITS OWN entity's box.

        Entity KEYS, never names: two statements' `⟐ output` trunks share a
        label (and an identity string), but they are different compounds —
        keying them together re-admits the FOREIGN statement's trunk (the
        EAST5 job-log write under a TOP0 field's closure)."""
        _o = occ(v) or {}
        if _o.get("variable_type") in FIELD_LIKE:
            _k = owner_by_id.get(v)
            if _k is not None:
                return _rg_box_key_of(_k)
        _k = pm.entity_of_id.get(v)
        if _k is not None:
            return _rg_box_key_of(_k)
        return _fold(_occ_identity(_o))

    def _value_cone_gate(_visited):
        # Box ids admitted + the box-key set that drives rule 2 (the
        # display merges by identity, so the same-name rule is keyed).
        _box_ids, _box_keys = set(), set()
        _tablelike_by_key = {}
        for _v in _visited:
            if _rg_chip(_v):
                continue
            _tablelike_by_key.setdefault(_rg_box_key(_v), []).append(_v)

        def _admit_key(k):
            if not k or k in _box_keys:
                return
            _box_keys.add(k)
            _box_ids.update(_tablelike_by_key.get(k, ()))

        # Own occurrences (the RECALL GUARD's anchor set): the searched
        # field's occurrences the walk reached, attributed to a
        # searched-table entity, by line.
        _own_entities = target_keys | _tkeys_ci | _alias_keys
        _own_at_line = {}
        for _v in _visited:
            _o = occ(_v)
            if (_o is None or _o.get("variable_type") not in FIELD_LIKE
                    or _fold(_occ_field_part(_o)) != _tf
                    or owner_by_id.get(_v) not in _own_entities):
                continue
            _ln = _o.get("line_start") or 0
            if _ln:
                _own_at_line.setdefault(_ln, []).append(_v)

        # V7 (2026-09-01, G1 residual retired): the CROSS-OWNER same-name
        # REF copy — two field chips carrying the SAME field name on
        # DIFFERENT owner entities. `build_dependency_graph` Phase 3 wires
        # such an edge whenever two scopes read a same-named column (the
        # last-writer-wins `full_col_index` match, and its bare-name
        # fallback): a graph-level FACT, not a value fact — the two
        # endpoints are different FIELDS (the same name on two tables).
        # Read as a PRODUCER claim ("the searched field's value comes from
        # that foreign same-named column") it is false by construction and
        # the cone must never cross it: that crossing is what put src_b's
        # `dt` into src_a.dt's closure (the G1 adjudicated repro; V3
        # recorded the admission as a residual, "recorded not endorsed" —
        # the USER RULE "only the field involved into the data flow is
        # shown" excludes it). Same-owner same-name copies (the P1
        # MOVE→COPY convention) are NOT gated: they are one entity's own
        # columns, and rule 2 admits them anyway.
        _phantom_memo = {}

        def _rg_copy_pair(E):
            _hit = _phantom_memo.get(id(E))
            if _hit is not None:
                return _hit
            _hit = False
            if (E.edge_type == "REF"
                    and (E.operation or "").upper() == "REFERENCE"):
                # Phase 3's co-scope wiring only (both the last-writer-wins
                # `source_columns` pick and its bare-name fallback). The
                # container PROVENANCE bridge is deliberately OUT: it is
                # cross-owner BY CONSTRUCTION (the producer container wraps
                # one table, the reader attributes to another) and it is
                # the searched field's own value leg — gating it darkened
                # RFN's ruled is_internet_loan derivation line @687.
                _uo, _vo = occ(E.source_id), occ(E.target_id)
                if (_uo is not None and _vo is not None
                        and _uo.get("variable_type") in FIELD_LIKE
                        and _vo.get("variable_type") in FIELD_LIKE
                        and _fold(_occ_field_part(_uo))
                        == _fold(_occ_field_part(_vo))
                        and _rg_box_key(E.source_id)
                        != _rg_box_key(E.target_id)):
                    _ok, _vk = owner_by_id.get(E.source_id), owner_by_id.get(
                        E.target_id)
                    _ot = pm.tables.get(_ok) if _ok is not None else None
                    _vt = pm.tables.get(_vk) if _vk is not None else None
                    # ... and it is a CROSS-TABLE collision: BOTH owners are
                    # physical tables. A chip owned by a container/VT is a
                    # computed column — its same-name copy IS the value that
                    # flows through the scope, not another table's field
                    # (05.sql: the outer projection `sales`@113 of the union
                    # container `foo` feeding the branch chip `sales`@93 is
                    # the searched field's own value path).
                    _hit = bool(_ot is not None and _vt is not None
                                and _ot.kind == "physical"
                                and _vt.kind == "physical")
            _phantom_memo[id(E)] = _hit
            return _hit

        def _rg_phantom_copy(E):
            # The PRODUCER half only: the edge presents a foreign
            # same-named column as the PRODUCER of a chip the closure
            # already holds (`A` — call only after `A` is bound). The
            # CONSUMER half (an in-closure chip read into a same-named
            # column elsewhere) is the searched field's own value flow and
            # must keep crossing — the canonical lending_ref↓SUP_M closure
            # carries the NOT-IN subquery's `DISTINCT lending_ref`@50
            # exactly that way (a cross-owner REFERENCE from the rollover
            # chip), and the consumer direction is what D2/J1 admit on.
            return _rg_copy_pair(E) and E.target_id in A

        # V7 (2026-09-01, G1 half 2): the DERIVED-CONTAINER chips. A
        # visited chip carrying the searched field part whose OWNER entity
        # is a subquery/virtual-table container that delivers the SEARCHED
        # table's value (`_holder_is_derived_single` — the walker's own
        # Fix-A-stage-1 qualification) IS an occurrence of the searched
        # field: the derived-product round admits it, and the gate had no
        # route back to its box (a box is admitted only through a chip
        # already in A), so the container's projection read AND the alias
        # handle that names it (`s1`@6) fell out of the served closure.
        # A container over TWO sources — or over another table — never
        # qualifies, so ITS same-named column stays out (the s2 half of
        # G1: `_holder_is_derived_single` counts src_b, not src_a).
        _derived_memo: dict = {}

        def _rg_derived_chip(v):
            _o = occ(v)
            if (_o is None or _o.get("variable_type") not in FIELD_LIKE
                    or _fold(_occ_field_part(_o)) != _tf):
                return False
            _k = owner_by_id.get(v)
            _tbl = pm.tables.get(_k) if _k is not None else None
            if (_tbl is None
                    or getattr(_tbl, "kind", None)
                    not in _DERIVED_CONTAINER_TYPES):
                return False
            _h = next((_h for _h in _tbl.occurrence_ids
                       if (occ(_h) or {}).get("variable_type")
                       in _DERIVED_CONTAINER_TYPES), None)
            if _h is None:
                return False
            _key = (_h, _tt)
            _hit = _derived_memo.get(_key)
            if _hit is None:
                _hit = _holder_is_derived_single(pm, occ, _h, _tt,
                                                 _derived_memo)
                _derived_memo[_key] = _hit
            return _hit

        _derived_chips = ({v for v in _visited if _rg_derived_chip(v)}
                          if _DERIVED_CONTAINER_CHIPS else set())

        # V7: the phantom CLASS, not just the phantom edge. A foreign
        # same-named chip presented as the producer of a seed carries no
        # field value, so it must not HOST a scope either — left in
        # `_hosts` it justified its own statement's FROM leg (W6b) and
        # pulled its box in through the back door, where rule 2 swept the
        # chip in anyway (the G1 `src_b`/`⟐ s2` route).
        _phantom_chips = set()
        for E in pm.edges:
            if _rg_copy_pair(E) and E.target_id in seeds:
                _phantom_chips.add(E.source_id)

        # W6b's context test, precomputed: every context that hosts a
        # visited field var carrying the searched field part (the ancestor
        # walk over "/" and ":" makes the per-edge probe O(1) — RFN's
        # 115k-edge closure cannot afford an O(edges x visited) scan).
        # Phantom chips never host (see `_phantom_chips` above).
        _hosts = set()
        for _v in _visited:
            _o = occ(_v)
            if (_o is None or _o.get("variable_type") not in FIELD_LIKE
                    or _fold(_occ_field_part(_o)) != _tf
                    or (_PHANTOM_COPY_GATE and _v in _phantom_chips)):
                continue
            _c = _o.get("context") or ""
            while _c:
                _hosts.add(_c)
                _i = max(_c.rfind("/"), _c.rfind(":"))
                if _i <= 0:
                    break
                _c = _c[:_i]

        # The A-free half of the leg justification (clause b) — memoized
        # per edge, it never changes during the fixpoint. (It reads
        # `_own_at_line`, so the own-occurrence scan above must run first.)
        _leg_memo = {}

        def _leg_justified_b(E):
            _et, _op = E.edge_type, (E.operation or "").upper()
            # D2 / R29 carry are WRITE-LEG tests: a DML edge that is not
            # the WRITE_READ link, or a TABLE_FLOW leg whose operation is
            # the DML keyword. A chain leg (`TABLE_FLOW` with a non-write
            # operation) is structure, never a write — justifying it on the
            # statement's row-selection would re-admit every join partner
            # of a statement that happens to filter the field (the EAST5
            # c/d/e/a.data_dt wrong-coverage class).
            _is_write_leg = ((_et == "DML" and _op != "WRITE_READ")
                             or (_et == "TABLE_FLOW"
                                 and _op in _DML_WRITE_OPS))
            if _is_write_leg:
                # D2 — the statement's write leg carries the searched field.
                if _tf in _dml_write_leg.get(E.target_id, ()):
                    return True
                # R29 carry — the target's statement row-selects the field
                # (the usage selects the rows the statement emits). DML edges
                # ONLY, mirroring the walker's own carry rule: a TABLE_FLOW
                # write leg into the same target is a SOURCE-side leg, and
                # justifying it on the statement's row-selection would drag
                # every join partner's box in (the EAST5 c/d/e/a.data_dt
                # wrong-coverage class).
                if _et == "DML":
                    _to = occ(E.target_id)
                    if _to is not None and _stmt_of(_to) in _sel_stmts_r:
                        return True
            if _et == "DML" and _op == "WRITE_READ":
                # D2's write→read link (V7, 2026-09-01): the link is the
                # READER statement's only leg and it carries no write of
                # its own, so without a clause here rule 6 had no way to
                # admit the reader box the fixpoint had already admitted,
                # and the reader that references the searched field fell
                # out of the served closure (test_d2_field_aware_dml
                # ::test_synthetic_write_read_reader_references_field).
                # Same gate as the walker's own forward WRITE_READ admit:
                # the reader joins only when it actually consumes the
                # searched field; a reader that never touches it stays
                # out (the negative twin of the same D2 test).
                _ro = occ(E.target_id)
                _rstmt = _stmt_of(_ro)
                if _rstmt and _tf in _stmt_field_parts.get(_rstmt, ()):
                    return True
            if _et == "TABLE_FLOW":
                # W6b — a VT endpoint whose context hosts a visited field
                # var carrying the field part (the CTE/FROM chain legs).
                # A BARE `TOP{n}` context is not a scope — it is the whole
                # statement — so a top-level trunk would justify every
                # TABLE_FLOW leg of its statement and the foreign-trunk
                # exclusion (AD3 item 2) would never fire. Only a NESTED
                # container context (`CTE{...}`, `TOP0/…`) is a scope here.
                for _ep in (E.source_id, E.target_id):
                    _o = occ(_ep)
                    if (_o is None
                            or _o.get("variable_type") != "virtual_table"):
                        continue
                    _sctx = _o.get("context") or ""
                    if not ("/" in _sctx or _sctx.startswith("CTE{")):
                        continue
                    if _sctx in _hosts:
                        return True
            if _et in ("FILTER", "JOIN"):
                # W4 row-selection clause — a predicate anchored on a line
                # where the SEARCHED field itself occurs is the field's own
                # row-selection: its join partner / co-filter sibling is
                # part of THAT predicate (the R44 join-mirror pair
                # `ON so.customer_id = sc.customer_id`, the J12-20
                # documented co-filter member). A predicate on a line the
                # searched field never touches is another table's
                # row-selection — the EAST5 c/d/e/a.data_dt class — and
                # stays out.
                if E.highlight_line in _own_at_line:
                    return True
            if _et == "ALIAS":
                # W3 — the alias names the searched table.
                _st = (occ(E.target_id) or {}).get("source_tables") or []
                if _st and _fold(_st[0]) == _tt:
                    return True
            return False

        # The R29 row-selection carriers, RE-SCOPED to the gate (AD3's
        # "re-scope _sel_stmts to row-level carriers only"): the walk's own
        # `_sel_stmts` was filled while the closure still held every
        # co-written sibling, so a statement whose row-selection touched any
        # of them is in it. Here a statement carries the effect only when
        # its row-selection has an ADMITTED chip as an endpoint. Recomputed
        # every round (it depends on A; A's growth depends on it — the same
        # monotone fixpoint).
        _sel_stmts_r = set()

        def _rescope_selection():
            _sel_stmts_r.clear()
            for E in pm.edges:
                if E.containment or E.edge_type not in ("FILTER", "JOIN"):
                    continue
                if E.source_id not in A and E.target_id not in A:
                    continue
                for _ep in (E.source_id, E.target_id):
                    _st = _stmt_of(occ(_ep))
                    if _st:
                        _sel_stmts_r.add(_st)

        A = set(seeds)
        # V7: the derived-container chips are searched-field occurrences
        # on their own container (a model fact, A-independent) — they
        # seed A so rule 5 admits the container box and rule 6 lets the
        # container's legs carry it.
        A |= _derived_chips
        _rescope_selection()
        # The SEARCHED table's own compounds stay whole: the search lands
        # on that box, and J12-20 pinned its co-filter sibling
        # (`charge_department` on bdm_acc_loan_info, edgeless, PL @265 /
        # DL @561) as a documented closure member. The co-written noise
        # the gate exists for lives on OTHER boxes (the ⟐ trunks, the CTE
        # projection lists, the join partners), never here.
        _own_box_keys = {_rg_box_key(_s) for _s in seeds}
        for _s in seeds:
            _admit_key(_rg_box_key(_s))
        changed, rounds = True, 0
        while changed and rounds < 100:
            changed = False
            rounds += 1
            _rescope_selection()
            for E in pm.edges:
                if E.containment:
                    continue
                _u, _v = E.source_id, E.target_id
                if _u not in _visited or _v not in _visited:
                    continue
                _et = E.edge_type
                # V7: a cross-owner same-name REFERENCE presented as a
                # PRODUCER of a chip the closure already holds carries no
                # value, so it admits nothing at all — not the foreign chip
                # (rules 3/4) and not its box (rule 6: admitting the box let
                # rule 2 sweep the foreign chip in anyway, which is how
                # src_b's `dt` survived the cone gate). Rule 5 still runs:
                # the near endpoint's own box is its own business.
                _phantom = _PHANTOM_COPY_GATE and _rg_phantom_copy(E)
                if _et in CONE_EDGES and not _phantom:
                    # 3. the forward value cone
                    if _u in A and _rg_chip(_v) and _v not in A:
                        A.add(_v)
                        changed = True
                    # 4. the write-slot's direct producers (one hop)
                    if _v in seeds and _rg_chip(_u) and _u not in A:
                        A.add(_u)
                        changed = True
                # 6. field-justified legs admit their box endpoints
                _just = _leg_memo.get(id(E))
                if _just is None:
                    _just = _leg_justified_b(E)
                    _leg_memo[id(E)] = _just
                if not _phantom and (_just or _u in A or _v in A):
                    for _ep in (_u, _v):
                        _k = _rg_box_key(_ep)
                        _admit_key(_k)
                        if not _rg_chip(_ep) and _ep not in _box_ids:
                            _box_ids.add(_ep)
                # 5. the owner box of every admitted chip
                for _c in (_u, _v):
                    if _c in A:
                        _admit_key(_rg_box_key(_c))
            # 2. same-name chips on an admitted box — plus every chip on
            #    the SEARCHED table's own compound (the J12-20 member).
            for _v in _visited:
                if _v in A or not _rg_chip(_v):
                    continue
                _bk = _rg_box_key(_v)
                if _bk not in _box_keys:
                    continue
                if (_fold(_occ_field_part(occ(_v))) != _tf
                        and (not _OWN_BOX_CHIPS
                             or _bk not in _own_box_keys)):
                    continue
                A.add(_v)
                changed = True

        # ── the RECALL GUARD: never lose the sole anchor of an own
        #    occurrence. A line whose own chips would all drop re-admits
        #    them, their owner box, and their pre-gate neighbours (the
        #    minimum that keeps the occurrence's edges renderable). ──
        for _ln, _chips in _own_at_line.items():
            if any(_c in A for _c in _chips):
                continue
            for _c in _chips:
                A.add(_c)
                _admit_key(_rg_box_key(_c))
                for (_nb, _e2, _f2, _r2, _o2) in adjacency.get(_c, ()):
                    if _nb in _visited:
                        A.add(_nb)

        _out = set(A)
        for _v in _visited:
            if _v in A:
                continue
            if _rg_chip(_v):
                continue                      # an unadmitted chip drops
            if _rg_box_key(_v) in _box_keys:
                _out.add(_v)
        if rounds >= 100:
            _log.warning("R46c value-cone gate hit the 100-round cap "
                         "(%d chips / %d boxes) for %s.%s", len(A),
                         len(_box_ids), target_table, target_field)
        return _out

    # ── Joint fixpoint: expansion rounds and identity-admission rounds
    # alternate until neither grows (monotone — terminates; capped). ──
    visited = set(seeds)
    # R29 continuation state: _effect_cols[table] = the write-leg
    # columns of DML admits into the table (the row-level carriers a
    # later row-selection reads through); _sel_stmts = statements owning
    # an admitted row-selection of the searched field or an effect
    # column — their write targets carry the effect (the carry rule).
    _effect_cols = {}
    _sel_stmts = set()
    # R44 Fix A stage 1: per-closure memo for `_holder_is_derived_single` —
    # the fixpoint re-enters the derived-product round every round, and the
    # holder's physical-source scan is the round's only real cost.
    _holder_memo: dict = {}
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
                if direction == "upstream":
                    # R29 (2026-08-12): upstream = backward production
                    # walk (U1-U6 in the docstring). Only the backward
                    # tuples (fwd=False) are consulted, and only over
                    # production edges — never FILTER/JOIN/SCHEMA/
                    # SUBQUERY/SET_OP/CORRELATED/INDIRECT/SUBSET or read
                    # edges (REF op=READ, U3), never forward (a chain
                    # member's consumers are downstream, not producers).
                    admit = False
                    if not fwd:
                        if et in FIELD_LAND:
                            # U2a: field production backward (target →
                            # its producing source).
                            admit = not read
                        elif et == "ALIAS":
                            # U2b: alias → its original.
                            admit = True
                        elif et == "DML":
                            # U2c: DML write target → its write-leg
                            # sources, write-leg-gated on the written
                            # field: the statement's own output VT (ctx
                            # exactly TOP{numeric}, same shape as the
                            # downstream D2 gate) admits when the write
                            # leg carries the searched field; a field-like
                            # var admits when its field part IS the
                            # searched field (partition columns arrive in
                            # the SQL's own casing → case-insensitive).
                            # WRITE_READ links are never production (U3).
                            if (op or "").upper() != "WRITE_READ":
                                nb_o = occ(nb)
                                if nb_o is not None:
                                    if nb_o.get("variable_type") == "virtual_table":
                                        _nb_ctx = nb_o.get("context") or ""
                                        if (_nb_ctx.startswith("TOP")
                                                and _nb_ctx[3:].isdigit()
                                                and _tf in _dml_write_leg.get(nid, ())):
                                            admit = True
                                    elif (nb_o.get("variable_type") in FIELD_LIKE
                                          and _fold(_occ_field_part(nb_o)) == _tf):
                                        admit = True
                        elif et == "TABLE_FLOW":
                            # U2d: backward along the WRITTEN legs only —
                            # operation is the DML keyword, and the leg
                            # source joins only when its physical identity
                            # is already in the chain (field-level gate:
                            # the write statement's unrelated input tables
                            # never enter the closure).
                            if (op or "").upper() in _DML_WRITE_OPS:
                                nb_o = occ(nb)
                                if (nb_o is not None
                                        and _occ_table_like(nb_o)
                                        and _fold(_occ_identity(nb_o)) in chain):
                                    admit = True
                    if admit:
                        visited.add(nb)
                        changed = True
                        _register(nb)
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
                        # G7 RC-C (2026-08-28.10): case-insensitive — the
                        # field part arrives in the SQL's own casing
                        # (`REPAY_ACCT_NO`) while the search may be typed in
                        # any casing (`repay_acct_no`); the case-sensitive
                        # comparison silently dropped every reverse-read
                        # admit whose occurrence spelled the field in the
                        # script's casing (R44 R0 / CR11 made the seed and
                        # entity matches case-insensitive — this comparison
                        # is the same rule).
                        admit = fwd or (_fold(_occ_field_part(occ(nb)))
                                        == _tf)
                    else:
                        admit = True
                elif et == "ALIAS":
                    nb_o = occ(nb)
                    nb_st = (nb_o or {}).get("source_tables") or []
                    admit = bool(nb_st) and _fold(nb_st[0]) == _tt
                elif et in ("FILTER", "JOIN"):
                    # W4 (J12-20, option b, 2026-08-13): a FILTER/JOIN edge
                    # admits only when the SEARCHED field itself is an
                    # endpoint — the bare seed-zone test was too broad: it
                    # admitted every co-filter SIBLING of the same WHERE
                    # clause (e.g. charge_department next to the data_dt
                    # filter on bdm_acc_loan_info), which is NOT on the
                    # searched field's flow path (J12-21 field-usage
                    # criterion). The searched field's own filter/join is
                    # the row-selection that renders its REF edge.
                    admit = False
                    if _seed_zone(nid) or _seed_zone(nb):
                        for _ep in (nid, nb):
                            _eo = occ(_ep)
                            if (_eo is not None
                                    and _fold(_occ_field_part(_eo)) == _tf):
                                admit = True
                                break
                    if not admit:
                        # R29 continuation: a row-selection whose
                        # endpoint column was WRITTEN in the effect
                        # admits (the usage selects the rows the
                        # statement emits — the sup data_dt filter @223
                        # continues the iiapty/lending_ref chains into
                        # the rrcdm write @211).
                        for _ep in (nid, nb):
                            _eo = occ(_ep)
                            if _eo is None:
                                continue
                            if (_fold(_occ_field_part(_eo))
                                    in _effect_cols.get(
                                        _fold(_occ_identity(_eo)), ())):
                                admit = True
                                break
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
                        and _fold(_occ_field_part(nb_o)) == _tf
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
                                    and _tf in _dml_write_leg.get(nid, ())):
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
                            admit = _tf in _stmt_field_parts.get(_stmt, ())
                        else:
                            admit = _tf in _dml_write_leg.get(nb, ())
                            if not admit:
                                # R29 carry rule: the target's own
                                # statement admitted a row-selection of
                                # the searched field or an effect column
                                # (the sup write admits — the join keys
                                # at CTE{loan_final} select its rows).
                                admit = (_stmt_of(nb_o) in _sel_stmts)
                    if admit and (op or "").upper() != "WRITE_READ":
                        # R29: record the target's write leg (the
                        # row-level carriers a later row-selection reads
                        # through), and — on the forward admit — bring
                        # in the target's continuation columns (fields
                        # any statement row-selects on the table, via
                        # _cont_cols). Their instances enter directly;
                        # their incident edges (the @223 read's FILTER)
                        # admit on the effect_cols rule. Columns nobody
                        # row-selects (sup p_dt) stay out — the pinned
                        # data_dt closures are unchanged.
                        _tgt = nb if fwd else nid
                        _tgt_leg = _dml_write_leg.get(_tgt, ())
                        if _tgt_leg:
                            _tgt_ident = _fold(_occ_identity(occ(_tgt)))
                            _effect_cols.setdefault(
                                _tgt_ident, set()).update(_tgt_leg)
                        if fwd:
                            _tgt_ident2 = (_fold(_occ_identity(nb_o))
                                           if nb_o is not None else "")
                            _cc = _cont_cols.get(_tgt_ident2, ())
                            if _cc:
                                for (_tk, _fname), _fld in pm.fields.items():
                                    if _fold(_fname) not in _cc:
                                        continue
                                    _tbl = pm.tables.get(_tk)
                                    if (_tbl is None
                                            or _fold(_tbl.name) != _tgt_ident2):
                                        continue
                                    for _vid in _fld.occurrence_ids:
                                        if _vid not in visited:
                                            visited.add(_vid)
                                            changed = True
                                            _register(_vid)
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
                            admit = _tf in _dml_write_leg.get(nb, ())
                        elif src_o is not None and src_o.get(
                                "variable_type") == "virtual_table":
                            sctx = src_o.get("context") or ""
                            for fv in node_map.values():
                                if (fv.get("variable_type") in FIELD_LIKE
                                        and fv.get("id") in visited
                                        and _fold(_occ_field_part(
                                            occ(fv.get("id")))) == _tf):
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

        # ── selection round (R29 continuation): the carrying statements.
        # A row-selection (FILTER/JOIN) with an endpoint in the closure
        # admits under the expansion's own rules (seed zone, or an
        # endpoint column written in the effect), and the endpoints'
        # owning statements are recorded — their write targets carry the
        # effect. This is a closure-invariant scan, NOT an edge admit:
        # the expansion's `nb in visited` guard skips edges whose other
        # end is already in the closure (the targeted admission below
        # pre-adds the continuation columns' instances), and the
        # selection must still be recorded.
        for _E in pm.edges:
            if _E.edge_type not in ("FILTER", "JOIN"):
                continue
            if (_E.source_id not in visited
                    and _E.target_id not in visited):
                continue
            _adm = (_seed_zone(_E.source_id) or _seed_zone(_E.target_id))
            if not _adm:
                for _ep in (_E.source_id, _E.target_id):
                    _eo = occ(_ep)
                    if _eo is None:
                        continue
                    if (_fold(_occ_field_part(_eo))
                            in _effect_cols.get(
                                _fold(_occ_identity(_eo)), ())):
                        _adm = True
                        break
            if _adm:
                for _ep in (_E.source_id, _E.target_id):
                    _eo = occ(_ep)
                    _st = _stmt_of(_eo)
                    if _st and _st not in _sel_stmts:
                        _sel_stmts.add(_st)
                        changed = True

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
        # ── R44 write-completion round (class 1, downstream only) ──
        # An in-closure OUTPUT projection of the searched field carries its
        # statement's write by itself (the occurrence IS the write — user
        # ruling 2026-08-28): admit the statement's ⟐ output VT so the
        # table-level DML write leg (⟐VT → target, whose _dml_write_leg the
        # index above already extends with the projection's field part)
        # renders through the normal DML forward rule. Without this, a
        # constant projection (`NULL AS Reserved_Field3`, no DML edge of its
        # own) left the write target and the ⟐ VT out of the closure — the
        # seed rendered with ZERO touching edges.
        if direction == "downstream":
            for nid in list(visited):
                o = occ(nid)
                if not o or o.get("variable_type") not in FIELD_LIKE:
                    continue
                if not o.get("is_output"):
                    continue
                if _fold(_occ_field_part(o)) != _tf:
                    continue
                _ctx = o.get("context") or ""
                if not _ctx:
                    continue
                for vid2, o2 in pm.occurrences.items():
                    if vid2 in visited:
                        continue
                    if o2.get("variable_type") != "virtual_table":
                        continue
                    if (o2.get("context") or "") != _ctx:
                        continue
                    visited.add(vid2)
                    changed = True
                    _register(vid2)
        # ── R44 derived-product admission round (classes 3/4, downstream) ──
        # Every occurrence of the searched field on a reader of the searched
        # table joins the closure: a field var V (field part == target)
        # whose HOLDER (the occurrence labeled source_tables[0] in V's
        # scope) reads the searched table INSIDE its own scope (an equal or
        # "/"-nested context) is an occurrence of the table's field — the
        # derived pass-through (`p2.product`, `a.rn`, `p8.X5GMAB`), the
        # alias read (`c.p_dt`), and the subquery-internal birth
        # (`row_number() … AS rn` on ⟐a) alike. The feeding read T joins
        # too (the value's origin — and the display compound the twin's
        # field node parents under).
        if direction == "downstream":
            _tl2 = _tt
            # READS only, and REAL table-like occurrences only: a DML-target
            # occurrence (defined_in INSERT/UPDATE/DELETE/MERGE) sitting in a
            # statement's scope must not turn every same-named sibling column
            # of that statement into an occurrence of the searched field
            # (DigL: the INSERT target bdm_acc_loan_info@99 shares TOP0 with
            # `D.DATA_DT` of BDM_PUB_BRANCH — D.DATA_DT is NOT
            # bdm_acc_loan_info.data_dt; and the write-side twin columns
            # carry source_tables=[target] but are fields, not reads).
            _REAL_TABLE_TYPES = {"table", "view", "cte", "virtual_table",
                                 "subquery", "merge_target", "union_branch",
                                 "function_table"}
            _tgt_occs = [(tv, to) for tv, to in pm.occurrences.items()
                         if to.get("variable_type") in _REAL_TABLE_TYPES
                         and _fold(_occ_identity(to)) == _tl2
                         and (to.get("defined_in") or "").upper()
                         not in ("INSERT", "UPDATE", "DELETE", "MERGE")]
            for vid2, o2 in pm.occurrences.items():
                if o2.get("variable_type") not in FIELD_LIKE:
                    continue
                if _fold(_occ_field_part(o2)) != _tf:
                    continue
                st2 = o2.get("source_tables") or []
                if not st2 or not st2[0]:
                    continue
                owner2 = owner_by_id.get(vid2)
                if owner2 is None:
                    continue
                # Holder resolution through the OWNER ENTITY's own
                # occurrences (label == source_tables[0]) — a derived
                # alias's var lives in the subquery's own scope (deeper
                # than the read site), so the ancestor-context picker
                # (_pick_occurrence) cannot find it; the entity's
                # occurrence list is the model's attribution truth. READ
                # occurrences win over DML-target occurrences (the value
                # flows through the read, and the target's own scope is
                # the whole statement).
                holder2 = None
                _otbl = pm.tables.get(owner2)
                if _otbl is not None:
                    o2_ctx = o2.get("context") or ""
                    for _hv in _otbl.occurrence_ids:
                        _ho = occ(_hv)
                        if _ho is None or _fold(_ho.get("name")) != _fold(st2[0]):
                            continue
                        if ((_ho.get("defined_in") or "").upper()
                                in ("INSERT", "UPDATE", "DELETE", "MERGE")):
                            if holder2 is None:
                                holder2 = _hv      # fallback of last resort
                            continue
                        # Prefer the holder whose context is the read's own
                        # scope or an ancestor of it — a derived alias is
                        # only usable from its own/descendant scopes, so a
                        # same-named holder in another statement (a
                        # cross-statement over-inclusion) must not win.
                        _hctx = _ho.get("context") or ""
                        if (_hctx == o2_ctx or o2_ctx.startswith(_hctx + "/")
                                or o2_ctx.startswith(_hctx + ":")):
                            holder2 = _hv
                            break
                        if holder2 is None:
                            holder2 = _hv   # first non-DML fallback
                if holder2 is None:
                    continue
                # Fix A stage 1 (2026-08-28.9): a holder that is itself a
                # DERIVED CONTAINER qualifies only when it actually delivers
                # the searched table's value — its scope must read EXACTLY
                # ONE original physical table and that table must be the
                # searched one (`_holder_is_derived_single`, the extractor's
                # own family-2 `derived_single` rule mirrored on
                # occurrences). The old test was scope PRESENCE only, so a
                # container over TWO sources (or over a different table
                # altogether) lent its scope to a same-named column of the
                # searched table.
                #
                # ADAPTED from the adjudicated spec (see the report): the
                # gate is applied to DERIVED-CONTAINER holders only
                # (subquery | virtual_table). A physical/CTE holder keeps
                # the scope-presence rule, because the canonical closures
                # depend on it structurally — SUP_M's
                # ods_hub_lsacmsp.lending_ref seeds ZERO PhysicalField
                # occurrences (the searched name is a derived alias's
                # source, never a var's owner), so the round's admissions
                # are the ONLY entry point into that closure and every one
                # of them hangs off a plain physical-table holder
                # (`bdm_acc_loan_info`@16 in CTE{rollover_loan_info}, …).
                # Gating those on the holder's own identity empties the
                # closure (measured: 21 -> 0 nodes, jaccard
                # lending_ref/SUP_M/downstream nodes precision 0.8491) —
                # the same shape as the false positive the gate is meant
                # for (PL's `c.p_dt`), so no occurrence-level test
                # separates them; the derived-container shapes are the part
                # that is provably decidable, and that is what is gated
                # here.
                _ho = occ(holder2) or {}
                # G7 RC-C half 1 (2026-08-28.10): a CTE holder that PROJECTS
                # the searched field while that projection is value-connected
                # to the closure is the field's own birth container — it
                # delivers the searched table's value whatever the number of
                # tables its body reads. Qualified CTE holders are admitted
                # directly below (their body context is a `CTE{...}` segment,
                # so the scope-presence test further down — an ancestor-or-
                # equal context match against the holder — can never see the
                # searched table's occurrence inside a CTE body anyway).
                _cte_birth = (
                    _fold(_occ_identity(_ho)) != _tl2
                    and _ho.get("variable_type") == "cte"
                    and _holder_is_derived_single(pm, occ, holder2, _tl2,
                                                  _holder_memo, visited))
                if (not _cte_birth
                        and _fold(_occ_identity(_ho)) != _tl2
                        and _ho.get("variable_type") in _DERIVED_CONTAINER_TYPES
                        and not _holder_is_derived_single(pm, occ, holder2,
                                                          _tl2, _holder_memo)):
                    continue
                hctx = _ho.get("context") or ""
                if not hctx:
                    continue
                if _cte_birth:
                    # The CTE is the field's own birth container: the
                    # occurrence and its holder join directly — the value
                    # chain reaches them through the container's PROVENANCE
                    # bridge, not through a searched-table occurrence inside
                    # the holder's scope.
                    if vid2 not in visited:
                        visited.add(vid2)
                        changed = True
                        _register(vid2)
                    if holder2 not in visited:
                        visited.add(holder2)
                        changed = True
                        _register(holder2)
                    continue
                for tv, to in _tgt_occs:
                    tctx = to.get("context") or ""
                    if not (tctx == hctx or tctx.startswith(hctx + "/")
                            or tctx.startswith(hctx + ":")):
                        continue
                    if vid2 not in visited:
                        visited.add(vid2)
                        changed = True
                        _register(vid2)
                    if holder2 not in visited:
                        visited.add(holder2)
                        changed = True
                        _register(holder2)
                    if tv not in visited:
                        visited.add(tv)
                        changed = True
                        _register(tv)
                    break
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
        #
        # R29 (2026-08-12): DOWNSTREAM-ONLY — this is read recognition
        # (U5): upstream is a writing-only walk, and a bare READER of the
        # table must never join it (the SUP_M reader
        # `bdm_acc_loan_info_sup@223` is the bdm.data_dt seed's reader —
        # it would enter the bdm.data_dt↑SUP_M closure, which must stay
        # EMPTY; the PL reader bdm@263 likewise must not enter ↑PL).
        if direction == "downstream":
            for nid, var in node_map.items():
                if var.get("variable_type") not in ("table", "view"):
                    continue
                if nid in visited:
                    continue
                o = occ(nid)
                ident = _occ_identity(o) if o is not None else ""
                if not (ident and _fold(ident) == _fold((o or {}).get("name"))
                        and _fold(ident) in chain):
                    continue
                # J12-21: scope-gate the bare-instance admission (mirror
                # of the W6b test above) — admit only when this instance's
                # context is an ancestor-or-equal of a VISITED field var
                # carrying the target field part. Without the gate, a
                # same-table read inside an unrelated CTE/subquery cascades
                # the whole branch into the closure (Digitallending
                # ODS_CUPD_CLD_ACCTMASTER_NEW.BNQXYE admitted temp_kmbh_gl/
                # temp_kmbh_ie's t@62/t@82 and the CTE-internal ODS@p1
                # instances). The intended peer-statement reader (SUP_M
                # bdm_acc_loan_info_sup@223, ctx=TOP1) still passes — the
                # visited data_dt vars carry the same TOP1 context.
                sctx = (o or {}).get("context") or ""
                scoped = False
                for fv in node_map.values():
                    if (fv.get("variable_type") in FIELD_LIKE
                            and fv.get("id") in visited
                            and _fold(_occ_field_part(
                                occ(fv.get("id")))) == _tf):
                        fctx = fv.get("context") or ""
                        if (fctx == sctx
                                or fctx.startswith(sctx.rstrip("/") + "/")):
                            scoped = True
                            break
                if not scoped:
                    continue
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

    # ── R46c (v3.3.195): the value-cone admission gate — AD3 §Q2, the
    #    adjudicated R-GATE ────────────────────────────────────────────
    # The fixpoint above answers "what does this field's value reach"; it
    # over-admits at the CO-WRITTEN level: every statement on the value's
    # path writes a whole projection list, and the R29 continuation then
    # carries those siblings into the closure as if they were the field.
    # FSB's audit of EAST5 measured the served flow-only closure at
    # ~54% OVER-INCLUSION for exactly that reason. The user ruling behind
    # item 48 ("only edges where the searched field is involved in the
    # data flow are shown") is the same statement at the walker level.
    #
    # The gate is a POST-FILTER over `visited` — it never walks, never
    # reconstructs, never reads the display `reason` string; every test
    # below is a model fact the walk already computed. Monotone fixpoint,
    # same 100-round cap, downstream only (upstream is the transitive
    # WRITING chain and is API-unreachable since K4 ruling 4 — the same
    # direction scoping as the R44 rounds and the Issue-3 admission).
    #
    #   CHIPS admitted (A):
    #     1. the W1 seeds — the searched field's occurrences on the
    #        searched table's entities (incl. the #399 alias expansion
    #        and FSC-1's owner-less bare columns);
    #     2. same-name chips on an ADMITTED box — the value's read/write
    #        slots in the other statements of the chain (the ONLY
    #        same-name rule; "same-name anywhere" is the phantom-seed
    #        defect AD3 rejected);
    #     3. the forward value cone — chip → chip over CONE_EDGES;
    #     4. the direct producers of an admitted write-slot chip (one hop
    #        backward over CONE_EDGES — never transitive upstream, K4.3).
    #   BOXES admitted (the display compounds, R22 label-keyed merge):
    #     5. the owner box of every admitted chip;
    #     6. both box endpoints of a FIELD-JUSTIFIED leg. A leg is field-
    #        justified when the walker's own admission rules say so —
    #        D2 (the statement's write leg carries the searched field),
    #        the R29 carry (the target's statement row-selects the field
    #        — `_sel_stmts`, which is what keeps the E5D4/D5-class
    #        statement write legs canonical), W6b (a VT endpoint whose
    #        context hosts a visited field var carrying the field part —
    #        the CTE/FROM chain legs), W3 (an ALIAS into the searched
    #        table) — plus clause (a): an endpoint chip is admitted.
    #     Everything else drops, and the edges drop with their endpoints
    #     through `filter_by_field_flow`'s existing both-ends test. A
    #     belongs-to SCHEMA edge of a dropped sibling chip therefore
    #     disappears for free — no suppression machinery is added here.
    #
    #   RECALL GUARD (AD3, corrected RFN numbers): the gate keeps the
    #   per-closure set of OWN-occurrence anchor lines (the searched
    #   field's occurrences on the searched table's entities that the
    #   walk reached) and refuses to lose one: a line whose every anchor
    #   would be dropped re-admits its own chips, their owner box and
    #   their pre-gate neighbours. In practice the seeds already carry
    #   every own chip and a chip's incident edges always survive, so the
    #   guard is a safety net — `test_occurrence_coverage_own_edge` pins
    #   the honest own-edge coverage per flagship so it stays that way.
    if direction == "downstream" and _VALUE_CONE_GATE and visited:
        visited = _value_cone_gate(visited)


    # ── ROW_FLOW bridges (#226, 2026-08-13): the R29 continuation rounds
    # may have admitted continuation TARGETS as NODES with no edge back to
    # the searched field's source — the only link is a containment SCHEMA
    # edge (container → nested VT, excluded from the walk by I5). Emit a
    # ROW_FLOW edge from the nested VT (the value-flow side, in the seed's
    # component) to the container (the disconnected continuation side) for
    # every such containment edge crossing the seed-component boundary.
    # Gated on `row_flow_out is not None` (only filter_by_field_flow asks)
    # and downstream (row-selection is a downstream effect; upstream is a
    # writing chain with no continuation rounds). A connected closure (all
    # benchmark seeds) emits nothing. ──
    if row_flow_out is not None and direction == "downstream" and visited:
        # Connected components of the closure over NON-containment edges
        # (the adjacency dict already excludes containment, I5).
        comp_of = {}
        _cid = 0
        for _nid in visited:
            if _nid in comp_of:
                continue
            comp_of[_nid] = _cid
            _stack = [_nid]
            while _stack:
                _cur = _stack.pop()
                for (_nb, _et, _fwd, _read, _op) in adjacency.get(_cur, []):
                    if _nb in visited and _nb not in comp_of:
                        comp_of[_nb] = _cid
                        _stack.append(_nb)
            _cid += 1
        # The seed component (the value-flow side holding the nested VT).
        _seed_comp = None
        for _s in seeds:
            if _s in comp_of:
                _seed_comp = comp_of[_s]
                break
        if _seed_comp is not None:
            for _E in pm.edges:
                if _E.edge_type != "SCHEMA" or not _E.containment:
                    continue
                _container = _E.source_id
                _nested_vt = _E.target_id
                if (_nested_vt not in comp_of
                        or _container not in comp_of):
                    continue
                if (_comp_of_nested_vt := comp_of[_nested_vt]) != _seed_comp:
                    continue
                if comp_of[_container] == _seed_comp:
                    continue  # already connected — no bridge needed
                row_flow_out.append({
                    "id": f"{_nested_vt}->{_container}",
                    "source": _nested_vt,
                    "target": _container,
                    "label": "ROW_FLOW",
                    "relationship": "ROW_FLOW",
                    "edge_type": "ROW_FLOW",
                    "operation": "ROW_SELECTION",
                    "color": "#2ECC71",
                    "containment": False,
                })
    if _flow_memo is not None:
        # Cache the walk: the closure as a snapshot + the ROW_FLOW bridges
        # it emitted (a hit re-fills the caller's list from the copy).
        _key = (target_table, target_field, direction)
        _entries = _flow_memo.get(id(graph_data))
        if _entries is not None and _entries[0] is graph_data:
            _entries[1].setdefault(_key, (set(visited), list(row_flow_out or [])))
        else:
            _flow_memo[id(graph_data)] = (
                graph_data, {_key: (set(visited), list(row_flow_out or []))})
    return visited


def filter_by_field_flow(graph_data, target_table, target_field,
                         table_schemas=None, physical_model=None,
                         direction="downstream", _flow_memo=None) -> dict:
    """Filter graph to the strict table.field flow closure (v3.3.140+, L2 only).

    Returns a dict identical to graph_data except nodes = those whose id is in
    the closure, edges = those with both ends in the closure; all other
    top-level keys are kept. I5 (v3.3.145): containment-tagged edges are
    excluded even when both ends are in the closure — nesting is shown by the
    nesting structure, not as flow arrows. An empty closure yields 0 nodes —
    the caller handles the not-in-flow case; this never raises.

    J12-10 stage 3: physical_model is REQUIRED (the walker consumes the
    physical model — see compute_field_flow).

    R29 (2026-08-12): direction is passed through to compute_field_flow —
    "downstream" (default) is the byte-identical legacy behavior;
    "upstream" filters to the field's WRITING flow (backward production
    walk — see compute_field_flow's U1-U6 rules).

    ROW_FLOW (2026-08-13, #226): the walker emits row-selection bridge
    edges (nested subquery VT → continuation container) into `row_flow_out`
    when the R29 continuation rounds left the closure disconnected; they
    are appended to the filtered edge list (raw graph shape, wrapped in
    {"data": ...} like every other served edge). Never fires when the
    closure is already connected (every benchmark seed).

    `_flow_memo` (PERF v3.3.194): the caller's request-scoped walker cache —
    see compute_field_flow. None (the default) always walks.
    """
    if not graph_data:
        return graph_data
    row_flow_out = []
    closure = compute_field_flow(graph_data, target_table, target_field,
                                 table_schemas, physical_model=physical_model,
                                 direction=direction,
                                 row_flow_out=row_flow_out,
                                 _flow_memo=_flow_memo)
    nodes = graph_data.get("nodes", []) or []
    edges = graph_data.get("edges", []) or []
    node_map = {n.get("data", n).get("id"): n.get("data", n) for n in nodes}
    # R44 / audit #383 (INV-2, 2026-08-28): closure edges with NO valid
    # anchor (highlight_line < 1 — the exists-subquery legs through line-0
    # synthetic ⟐ containers) are excluded cleanly instead of served: an
    # unanchorable edge cannot highlight in the SQL panel and cannot render
    # in the merged views (R32 rule 5). Keyed on the model's PhysicalEdge
    # twins — an endpoint/type key is excluded only when NO twin carries a
    # valid line.
    _anchorless = set()
    _anchored = set()
    if physical_model is not None:
        for _E in physical_model.edges:
            _k = (_E.source_id, _E.target_id, _E.edge_type)
            if (_E.highlight_line or 0) >= 1:
                _anchored.add(_k)
            else:
                _anchorless.add(_k)
        _anchorless -= _anchored
    filtered_edges = [e for e in edges
                      if (e.get("data", e).get("source") in closure and
                          e.get("data", e).get("target") in closure and
                          not _is_containment(e.get("data", e)) and
                          not _is_spurious_ref_copy(
                              e.get("data", e),
                              node_map.get(e.get("data", e).get("source"))) and
                          ((e.get("data", e).get("source"),
                            e.get("data", e).get("target"),
                            (e.get("data", e).get("edge_type")
                             or e.get("data", e).get("relationship") or ""))
                           not in _anchorless))]
    filtered_nodes = [n for n in nodes if n.get("data", n).get("id") in closure]
    # ROW_FLOW bridges: only when both endpoints are served nodes (they
    # are — the walker only emits for closure members).
    for _rf in row_flow_out:
        if (_rf["source"] in node_map and _rf["target"] in node_map
                and _rf["source"] != _rf["target"]):
            filtered_edges.append({"data": _rf})
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
# is flow. The `category` field is deliberately NOT consulted: TABLE_FLOW
# is flow by edge type regardless of its visual category (J12-23 moved it
# out of "structure" into "flow" — the edge type stays the discriminator).
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
                 physical_model=None, _flow_memo=None) -> set:
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
                                 physical_model=physical_model,
                                 _flow_memo=_flow_memo)
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
        # R46e: folded — the served flow SOURCE must not depend on the
        # casing the caller typed (H7 site 2056).
        if (o.get("variable_type") in ("table", "view")
                and _fold(o.get("name")) == _fold(target_table)):
            return vid
    return None
