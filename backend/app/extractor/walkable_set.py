"""Walkable-set contract — single source of truth for which edge types
the value-flow walkers follow (code-review 2026-08-06 item 4, RC-1
hardening).

The system classifies the 17 edge types in several places; this module
is the walkability classification of the STRICT L2 walker
(lineage.compute_field_flow), extracted to one importable place:

  FIELD_WALKABLE — followed both directions by the BFS (value copies);
                   REF/READ edges additionally narrow to field → holder.
  CONDITIONAL    — followed only under the type's own rule:
                     ALIAS      — neighbor's source_tables[0] == searched table
                     FILTER/JOIN — the seed zone contains an endpoint
                     DML        — forward only (+ write-side VALUE rule)
                     TABLE_FLOW — forward only, source identity in the chain
  NEVER_WALKED   — never enters the lineage closure (structure/display
                   edges with no value semantics — the walker's else
                   branch rejects them).

Related-but-distinct classifications that deliberately do NOT live here:

  * lineage.EDGE_SEMANTICS — the LEGACY L1 semantic table
    (compute_field_lineage). The strict walker is deliberately stricter:
    it demotes DML/ALIAS from unconditional production to conditional,
    TABLE_FLOW from always-bidir to conditional, and
    CORRELATED/INDIRECT/SET_OP/SUBQUERY from always-bidir to never.
    (FIELD_WALKABLE == EDGE_SEMANTICS production minus {DML, ALIAS};
    NEVER_WALKED == (EDGE_SEMANTICS always-bidir minus {TABLE_FLOW})
    union {SCHEMA, SUBSET}.)
  * lineage.NON_FLOW_EDGE_TYPES — R19.5 net-flow ROLE counting
    (everything except ALIAS/SCHEMA/SUBSET is "flow" for roles). That is
    a role-classification notion, not walkability: SUBQUERY/SET_OP/
    CORRELATED/INDIRECT count as flow there yet are never walked here,
    and ALIAS is non-flow there yet conditionally walked here.
  * graph_service.EDGE_TYPE_STYLE / CATEGORY_MAP — visual categories
    (structure/copy/compute/aggregate/filter/combine/write), display
    only.

Consumers:

  * dependency_graph._bridge_typing (Phase 8) re-types SUBSET bridges
    and must only emit BRIDGE_EMIT_TYPES — REF (FIELD_WALKABLE),
    FILTER/JOIN/DML/TABLE_FLOW (CONDITIONAL), SUBSET (NEVER_WALKED, the
    honest fallback for physical-table bridges).
  * lineage.py's strict walker is pinned to this contract by
    tests/test_walkable_set.py (behavioral per-type probes + the
    flagship sample), so a change on either side fails the test instead
    of drifting.

Invariant: this module imports nothing and is importable by every layer
(extractor, services, tests).
"""

from __future__ import annotations

# ── Walkability classes (partition of the 17 edge types) ────────────────

# Followed both directions by the strict walker. (This is the former
# literal FIELD_LAND in lineage.py, before the contract extraction.)
FIELD_WALKABLE = frozenset({
    "REF", "TRANSFORM", "AGGREGATE", "WINDOW", "COMPUTED",
})

# Followed only when the type's rule holds (the walker's elif branches —
# see the module docstring for each rule).
CONDITIONAL = frozenset({
    "ALIAS", "DML", "FILTER", "JOIN", "TABLE_FLOW",
})

# Never entered the lineage closure.
NEVER_WALKED = frozenset({
    "SCHEMA", "SUBQUERY", "SET_OP", "CORRELATED", "INDIRECT", "SUBSET",
    # ROW_FLOW (2026-08-13, #226): the R29 row-selection BRIDGE — the
    # walker itself emits it AFTER the closure fixpoint (an output edge,
    # never a walk input): the strict value-flow walker must never follow
    # it (it carries row-selection, not value). It is the 17th edge type.
    "ROW_FLOW",
})

# All 17 edge types of the canonical taxonomy (lineage.EDGE_SEMANTICS,
# graph_service.EDGE_TYPE_ORDER). Any edge type produced by the
# extractor/builders must be a member (pinned on the flagship sample).
ALL_EDGE_TYPES = FIELD_WALKABLE | CONDITIONAL | NEVER_WALKED

# Phase-8 bridge emit palette — the types dependency_graph._bridge_typing
# may produce when re-typing Phase-7 SUBSET bridges. Every member is
# classified above; a new bridge type is a contract change.
BRIDGE_EMIT_TYPES = frozenset({
    "REF", "FILTER", "JOIN", "DML", "TABLE_FLOW", "SUBSET",
})

# Sanity: the classes partition ALL_EDGE_TYPES and the bridge palette
# stays inside the classification. Fails loudly at import on any edit
# that breaks the partition.
assert not (FIELD_WALKABLE & CONDITIONAL)
assert not (FIELD_WALKABLE & NEVER_WALKED)
assert not (CONDITIONAL & NEVER_WALKED)
assert len(ALL_EDGE_TYPES) == 17, ALL_EDGE_TYPES
assert BRIDGE_EMIT_TYPES <= ALL_EDGE_TYPES
