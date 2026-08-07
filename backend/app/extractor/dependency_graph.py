"""
Dependency Graph Builder — build variable dependency edges from extraction results.

Phases are ordered top-down: table-level connections first, then column-level
details, then structural edges. This matches how data flows in SQL:
  tables → table-to-table flows → columns carry data between tables.
"""

from collections import defaultdict

from app.models.variable import VariableDefinition, VariableDependency, VariableType
from app.extractor.variable_extractor_v2 import ExtractionResult


# ── Table-like types that participate in table-level data flow ──────────
_TABLE_TYPES = {
    VariableType.TABLE, VariableType.VIEW, VariableType.CTE,
    VariableType.SUBQUERY, VariableType.VIRTUAL_TABLE,
    VariableType.MERGE_TARGET, VariableType.UNION_BRANCH,
}


def build_dependency_graph(
    result: ExtractionResult, sql_text: str = ""
) -> list[VariableDependency]:
    """Build dependency edges from extracted variables.

    Phase order (top-down):
      1. TABLE_FLOW — adjacent table-to-table data flow
      2. ALIAS      — alias → original table name
      3. Column edges — REF / AGGREGATE / TRANSFORM / WINDOW / COMPUTED
      4. SCHEMA     — column belongs to table / CTE / VT
      5. INDIRECT   — bare name reference (HAVING → SELECT)
      6. DML        — INSERT / UPDATE / DELETE / MERGE targets
      7. SET_OP     — UNION / INTERSECT / EXCEPT branch → VT
      8. FILTER     — WHERE / HAVING condition → VT
      9. SUBSET     — safety net for remaining disconnected components
    """
    variables = result.variables
    if not variables:
        return []

    deps: list[VariableDependency] = []
    seen_edges: set[tuple[str, str]] = set()

    # ── Indexes ──────────────────────────────────────────────────────
    name_index: dict[str, list[VariableDefinition]] = defaultdict(list)
    for v in variables:
        name_index[v.name].append(v)

    full_col_index: dict[str, VariableDefinition] = {}
    for v in variables:
        if v.variable_type in (VariableType.COLUMN, VariableType.CTE_COLUMN,
                                VariableType.EXPRESSION, VariableType.AGGREGATE,
                                VariableType.WINDOW, VariableType.CASE,
                                VariableType.TRANSFORM):
            full_col_index[v.name] = v

    # I4: id → var and registration order (Phase 2 alias_of lookup,
    # Phase 7/8 anchor tie-breaks)
    id_index: dict[str, VariableDefinition] = {}
    var_order: dict[str, int] = {}
    for i, v in enumerate(variables):
        id_index[v.id] = v
        var_order[v.id] = i

    # ── Table anchor index (VTs + CTEs as output containers) ─────────
    vt_map: dict[str, list[VariableDefinition]] = defaultdict(list)
    all_anchors: list[VariableDefinition] = []
    for v in variables:
        if v.variable_type == VariableType.VIRTUAL_TABLE:
            vt_map[v.context or "TOP"].append(v)
            all_anchors.append(v)
        elif v.variable_type == VariableType.CTE:
            cte_ctx = f"CTE{{{v.name}}}"
            vt_map[cte_ctx].append(v)
            all_anchors.append(v)
            # CTE is only an output anchor for its inner context.
            # Do NOT add to vt_map[TOP] — that causes FROM aliases
            # like 'ctr1' to get TABLE_FLOW → CTE, blocking ALIAS edges.

    # ══════════════════════════════════════════════════════════════════
    # Phase 1: TABLE_FLOW — adjacent table-to-table data flow
    # ══════════════════════════════════════════════════════════════════
    # Two table-like nodes are "adjacent" when data flows directly from
    # one to the other without passing through any intermediate table.
    # This is the high-level view: what tables feed what other tables.

    def _add_edge(src, tgt, rel, op="", ctx="", containment=False):
        ek = (src.id, tgt.id, rel)
        if ek not in seen_edges and src.id != tgt.id:
            seen_edges.add(ek)
            deps.append(VariableDependency(
                source_id=src.id, target_id=tgt.id,
                relationship=rel, operation=op,
                sql_context=ctx or f"{src.name} → {tgt.name}",
                containment=containment,
            ))

    # 1a: FROM / JOIN source → its context anchor (VT or CTE)
    #     TABLE/VIEW aliases, CTE references, subquery aliases all feed output.
    for v in variables:
        if v.variable_type == VariableType.CTE:
            ctx = v.context or "TOP"
            for anchor in vt_map.get(ctx, []):
                if anchor.id != v.id:
                    _add_edge(v, anchor, "TABLE_FLOW", "REFERENCE")
            continue
        if v.variable_type == VariableType.SUBQUERY:
            ctx = v.context or "TOP"
            for anchor in vt_map.get(ctx, []):
                if anchor.id != v.id:
                    _add_edge(v, anchor, "SUBQUERY", "REFERENCE")
            continue
        if v.variable_type not in (VariableType.TABLE, VariableType.VIEW):
            continue
        if not v.source_tables:  # skip original names — only aliases
            continue
        ctx = v.context or "TOP"
        for anchor in vt_map.get(ctx, []):
            _add_edge(v, anchor, "TABLE_FLOW", "FROM")

    # 1b: Nested anchors → parent context (subquery VT → parent VT)
    #     Shows "inner SELECT output flows into outer query"
    for anchor in all_anchors:
        ctx = anchor.context or "TOP"
        if "/" in ctx:
            parent_ctx = ctx.rsplit("/", 1)[0]
            for parent in vt_map.get(parent_ctx, []):
                _add_edge(anchor, parent, "TABLE_FLOW", "SUBSELECT")

    # 1c: DML targets — data flows from source columns to target table
    dml_entries: list[tuple[VariableDefinition, str]] = []
    for v in variables:
        if v.variable_type == VariableType.MERGE_TARGET:
            dml_entries.append((v, "MERGE"))
        elif v.variable_type == VariableType.TABLE:
            di = (v.defined_in or "").upper()
            for kw in ("INSERT", "UPDATE", "DELETE"):
                if kw in di:
                    dml_entries.append((v, kw))
                    break

    for tbl_var, op_type in dml_entries:
        ctx = tbl_var.context or "TOP"
        ctx_vars = [v for v in variables if (v.context or "TOP") == ctx]
        src_vars = [v for v in ctx_vars
                    if v.source_columns and v.id != tbl_var.id]
        if src_vars:
            for src in src_vars[:30]:
                _add_edge(src, tbl_var, "DML", op_type)
        else:
            ctx_anchor = next((v for v in ctx_vars
                              if v.variable_type in _TABLE_TYPES
                              and v.id != tbl_var.id), None)
            if ctx_anchor:
                _add_edge(ctx_anchor, tbl_var, "DML", op_type)

    # 1c-extra: TABLE_FLOW from FROM aliases → DML target tables
    # Shows "source table feeds data into INSERT/UPDATE/DELETE/MERGE target"
    for tbl_var, op_type in dml_entries:
        ctx = tbl_var.context or "TOP"
        for v in variables:
            if v.variable_type not in (VariableType.TABLE, VariableType.VIEW):
                continue
            if not v.source_tables:  # only aliases
                continue
            if (v.context or "TOP") != ctx:
                continue
            _add_edge(v, tbl_var, "TABLE_FLOW", op_type)

    # 1d: UNION branch → parent context VT (or DML target TABLE)
    # SET_OP edges connect UNION / INTERSECT / EXCEPT branches to their
    # output anchor. The anchor is normally a VIRTUAL_TABLE or CTE in the
    # same context. When no VT/CTE exists (e.g. INSERT INTO <table> SELECT
    # ... UNION ...), fall back to TABLE variables in the same context
    # (typically the DML target table).
    for v in variables:
        if v.variable_type != VariableType.UNION_BRANCH:
            continue
        ctx = v.context or "TOP"
        anchors = vt_map.get(ctx, [])
        if not anchors:
            # Fallback: look for TABLE vars in same context (DML targets)
            anchors = [tv for tv in variables
                       if tv.variable_type == VariableType.TABLE
                       and (tv.context or "TOP") == ctx
                       and tv.id != v.id]
        for anchor in anchors:
            _add_edge(v, anchor, "SET_OP", "SET")

    # ══════════════════════════════════════════════════════════════════
    # Phase 2: ALIAS — original table → alias
    # I4: the extractor records the exact source var on `alias_of` (its
    # id). Emit exactly ONE edge vars[v.alias_of] → v. A missing/absent
    # alias_of emits NOTHING — no name-matching loop, no cross-instance
    # guesses (bdm@16→p1@29-style artifacts are gone).
    for v in variables:
        orig_id = getattr(v, "alias_of", None)
        if not orig_id:
            continue
        orig_var = id_index.get(orig_id)
        if orig_var is not None and orig_var.id != v.id:
            _add_edge(orig_var, v, "ALIAS", "ALIAS")

    # ══════════════════════════════════════════════════════════════════
    # Phase 3: Column edges — REF / AGGREGATE / TRANSFORM / WINDOW / COMPUTED
    # ══════════════════════════════════════════════════════════════════
    # Each column carrying data between the tables connected in Phase 1.
    for target_var in variables:
        for src_col in target_var.source_columns:
            if src_col in full_col_index:
                src_var = full_col_index[src_col]
                _add_edge(src_var, target_var,
                         _classify_relationship(src_var, target_var),
                         "REFERENCE")
                continue
            # Fallback: match by bare column name
            col_name = src_col.rsplit(".", 1)[-1] if "." in src_col else src_col
            for src_var in name_index.get(col_name, []):
                _add_edge(src_var, target_var,
                         _classify_relationship(src_var, target_var),
                         "REFERENCE")
                break

    # ══════════════════════════════════════════════════════════════════
    # Phase 4: SCHEMA — column belongs to table / CTE / VT
    # ══════════════════════════════════════════════════════════════════

    # Build table index
    table_index: dict[str, list[VariableDefinition]] = defaultdict(list)
    for v in variables:
        if v.variable_type in (VariableType.TABLE, VariableType.VIEW,
                               VariableType.CTE, VariableType.MERGE_TARGET,
                               VariableType.SUBQUERY):
            table_index[v.name].append(v)

    # Pass 4a: alias/CTE/VT → columns (skip original table names)
    for v in variables:
        if v.variable_type != VariableType.COLUMN:
            continue
        if "." not in v.name:
            continue
        prefix = v.name.split(".", 1)[0]
        for tbl_var in table_index.get(prefix, []):
            is_original = (tbl_var.variable_type == VariableType.TABLE
                           and not tbl_var.source_tables)
            if is_original:
                continue
            _add_edge(tbl_var, v, "SCHEMA", "TABLE_COLUMN")

    # Pass 4b: CTE → inner variables
    # I5: container → nested ⟐ VT anchor edges are tagged `containment`
    # (the strict walker consumes the flag). Column/table SCHEMA edges
    # stay untagged.
    for v in variables:
        if v.variable_type != VariableType.CTE:
            continue
        cte_prefix = f"CTE{{{v.name}}}"
        for inner in variables:
            if inner.defined_in and (
                inner.defined_in == cte_prefix
                or inner.defined_in.startswith(cte_prefix)
            ):
                if inner.variable_type == VariableType.CTE:
                    continue
                _add_edge(
                    v, inner, "SCHEMA", "TABLE_COLUMN",
                    containment=inner.variable_type == VariableType.VIRTUAL_TABLE,
                )

    # Pass 4c: Output-container → output columns
    for ctx, anchors in vt_map.items():
        for anchor in anchors:
            for v in variables:
                if (v.context or "TOP") != ctx:
                    continue
                if not v.is_output:
                    continue
                # Skip table anchors, but NOT subquery — scalar subqueries
                # in SELECT are output values (e.g., (SELECT COUNT(*) ...) AS cnt)
                if v.variable_type in (VariableType.TABLE, VariableType.VIEW,
                                        VariableType.CTE, VariableType.VIRTUAL_TABLE,
                                        VariableType.MERGE_TARGET, VariableType.UNION_BRANCH):
                    continue
                _add_edge(anchor, v, "SCHEMA", "OUTPUT")

    # ══════════════════════════════════════════════════════════════════
    # Phase 5: INDIRECT — bare column → defined variable (HAVING→SELECT)
    # ══════════════════════════════════════════════════════════════════
    for v in variables:
        if v.variable_type != VariableType.COLUMN:
            continue
        if v.source_columns or "." in v.name:
            continue
        for src in name_index.get(v.name, []):
            if src.variable_type in (VariableType.AGGREGATE, VariableType.WINDOW,
                                      VariableType.CASE, VariableType.TRANSFORM,
                                      VariableType.EXPRESSION, VariableType.CTE_COLUMN):
                _add_edge(src, v, "INDIRECT", "NAME_MATCH")
                break

    # 5b: CORRELATED SUBQUERY — outer column referenced inside subquery
    # ══════════════════════════════════════════════════════════════════
    # When a column in a nested context (e.g., "TOP/subq1") has a table
    # prefix that resolves to a table/alias defined in a parent context,
    # it's a correlated reference (formal R10).
    # These columns carry data from the outer query into the subquery.
    for v in variables:
        if v.variable_type != VariableType.COLUMN:
            continue
        if not v.context or "/" not in v.context:
            continue  # not in a subquery
        if "." not in v.name:
            continue  # no table prefix to resolve
        prefix = v.name.split(".", 1)[0]
        # Walk up context hierarchy to find parent context
        ctx_parts = v.context.split("/")
        parent_ctx = "/".join(ctx_parts[:-1])  # e.g., "TOP/subq1" → "TOP"
        # Look for table/alias with this prefix in the parent context
        for pv in variables:
            if pv.variable_type not in (VariableType.TABLE, VariableType.VIEW,
                                         VariableType.CTE, VariableType.SUBQUERY,
                                         VariableType.VIRTUAL_TABLE):
                continue
            if (pv.context or "TOP") != parent_ctx:
                continue
            if pv.name == prefix:
                # Found: v is a correlated reference through table pv
                # Find matching columns from full_col_index that share
                # the same column name in the parent scope
                col_suffix = v.name.split(".", 1)[1]  # e.g., "order_id"
                for pcol in variables:
                    if pcol.variable_type != VariableType.COLUMN:
                        continue
                    if (pcol.context or "TOP") != parent_ctx:
                        continue
                    pcol_prefix = pcol.name.split(".", 1)[0] if "." in pcol.name else ""
                    pcol_suffix = pcol.name.split(".", 1)[1] if "." in pcol.name else pcol.name
                    if pcol_prefix == prefix and pcol_suffix == col_suffix:
                        _add_edge(pcol, v, "INDIRECT", "CORRELATED")
                        break
                # Also create INDIRECT edges to output columns of the outer scope
                for out_col in variables:
                    if not out_col.is_output:
                        continue
                    if (out_col.context or "TOP") != parent_ctx:
                        continue
                    _add_edge(v, out_col, "INDIRECT", "CORRELATED_OUT")
                break  # one match per correlated column

    # ══════════════════════════════════════════════════════════════════
    # Phase 6: FILTER — WHERE/HAVING column → context anchor
    # ══════════════════════════════════════════════════════════════════
    # Only columns from WHERE, HAVING, or JOIN ON clauses. These influence
    # which rows flow through without producing output data themselves.
    # SELECT expression sources (like o.amount consumed by SUM) and
    # general column references do NOT get FILTER edges.
    _FILTER_CLAUSES = {"WHERE", "HAVING", "QUALIFY"}
    _JOIN_CLAUSES = {"JOIN ON"}
    for v in variables:
        if v.variable_type != VariableType.COLUMN:
            continue
        if v.is_output:
            continue
        if "." not in v.name:
            continue
        # Only columns from filter clauses
        if (v.defined_in or "").upper().strip() not in _FILTER_CLAUSES:
            continue
        ctx = v.context or "TOP"
        if ctx not in vt_map:
            continue
        anchor = vt_map[ctx][0]
        _add_edge(v, anchor, "FILTER", "CONDITION")

    # ══════════════════════════════════════════════════════════════════
    # Phase 6b: JOIN — JOIN ON predicate columns influence which rows
    #           are matched, affecting every output column (formal R4)
    # ══════════════════════════════════════════════════════════════════
    # Join keys determine which tuples from each side are paired.
    # Changing a JOIN key changes the row composition → affects every
    # output column on the JOIN's output side.
    _JOIN_CLAUSES = {"JOIN ON"}
    for v in variables:
        if v.variable_type != VariableType.COLUMN:
            continue
        if v.is_output:
            continue
        if "." not in v.name:
            continue
        if (v.defined_in or "").upper().strip() not in _JOIN_CLAUSES:
            continue
        ctx = v.context or "TOP"
        if ctx not in vt_map:
            continue
        anchor = vt_map[ctx][0]
        _add_edge(v, anchor, "JOIN", "JOIN_CONDITION")

    # Phase 6b (B-series, Phase 2): materialized join-key expression nodes
    # (extractor `_walk_join_key_expressions`) carry the OTHER side of their
    # comparison on `source_variables`. Emit the JOIN edge from that outer
    # column/expression TO the expression node — the lineage engine admits
    # expression partners unconditionally, so CONCAT/RPAD/||-built keys show
    # their operand columns in the data flow.
    for v in variables:
        if v.variable_type != VariableType.EXPRESSION:
            continue
        if (v.defined_in or "").upper().strip() != "JOIN ON":
            continue
        for sid in (v.source_variables or []):
            other = next((x for x in variables if x.id == sid), None)
            if other is not None and other.id != v.id:
                _add_edge(other, v, "JOIN", "JOIN_KEY")

    # ══════════════════════════════════════════════════════════════════
    # Phase 7: SUBSET — safety net for disconnected components
    # ══════════════════════════════════════════════════════════════════
    # Union-Find to find disconnected components, bridge them.

    def _pick_anchor(base, v, scope_ctx, exclude_ids=frozenset()):
        """Nearest owner stage (I3): among `base` vars in `scope_ctx` of a
        table-like type with a REAL line (synthetic ⟐/union nodes are
        line 0 and can never own anything), the one registered at-or-
        before v's line — maximal line wins; ties prefer physical tables
        (empty source_tables), then non-VTs, then registration order.
        `exclude_ids` (the Phase 7 component's own vars) never anchors —
        a bridge must connect OUTSIDE the component or it is a no-op.
        Returns None when the stage has none."""
        best = None
        best_score = None
        for x in base:
            if x.variable_type not in _TABLE_TYPES or x.id == v.id:
                continue
            if x.id in exclude_ids:
                continue
            if (x.context or "TOP") != scope_ctx:
                continue
            if x.line_start < 1:
                continue
            if v.line_start >= 1 and x.line_start > v.line_start:
                continue
            # Virtual nodes carry line 0 — the at-or-before bound is
            # meaningless for them; any real-line anchor in the stage
            # qualifies, and the MINIMAL line wins (the stage's head —
            # the enclosing-container side), not the maximal.
            score = (-x.line_start if v.line_start >= 1 else x.line_start,
                     1 if x.source_tables else 0,
                     1 if x.variable_type == VariableType.VIRTUAL_TABLE else 0,
                     var_order[x.id])
            if best_score is None or score < best_score:
                best, best_score = x, score
        return best

    def _context_stages(ctx: str) -> list[str]:
        """Ordered candidate stages for the nearest-owner search (I3):
        the exact context, then every enclosing context up to the
        statement, then — for CTE bodies — the statement context of the
        CTE's own var (its recorded .context, extraction info). Contexts
        are statement-scoped (TOP{idx} since C-9), so a stage walk can
        never reach into another statement."""
        stages = []
        seen = set()
        c = ctx
        while c and c not in seen:
            seen.add(c)
            stages.append(c)
            last = max(c.rfind("/"), c.rfind(":join:"))
            if last > 0:
                c = c[:last]
                continue
            if c.startswith("CTE{") and c.endswith("}"):
                name = c[4:-1].lower()
                owner = next((v.context for v in variables
                              if v.variable_type == VariableType.CTE
                              and (v.name or "").lower() == name
                              and v.context), None)
                if owner:
                    c = owner
                    continue
            break
        return stages

    def _nearest_main_anchor(v, main_comp):
        """Nearest main-component table-like anchor by line — last resort
        for the Phase 7 bridge when the component's own statement has no
        other table to anchor on (e.g. a lone UPDATE's target + alias):
        maximal line at-or-before v's line, else the minimal line after
        it; ties by registration order. Deterministic, extraction-time —
        never a text or first-match search."""
        cands = [x for x in main_comp
                 if x.variable_type in _TABLE_TYPES and x.line_start >= 1]
        if not cands:
            return None
        if v.line_start >= 1:
            at_or_before = [x for x in cands if x.line_start <= v.line_start]
            if at_or_before:
                return max(at_or_before,
                           key=lambda x: (x.line_start, -var_order[x.id]))
        return min(cands, key=lambda x: (x.line_start, -var_order[x.id]))

    parent = {v.id: v.id for v in variables}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for d in deps:
        union(d.source_id, d.target_id)

    comps = defaultdict(list)
    for v in variables:
        comps[find(v.id)].append(v)
    comp_list = sorted(comps.values(), key=len, reverse=True)

    if len(comp_list) > 1:
        main_cols = {v.name for v in comp_list[0]
                     if v.variable_type == VariableType.COLUMN}
        for comp in comp_list[1:]:
            found = False
            for v in comp:
                for sc in v.source_columns:
                    sc_var = next((x for x in comp_list[0] if x.name == sc), None)
                    if sc_var:
                        _add_edge(sc_var, v, "REF", "CROSS_COMP")
                        found = True
            if not found:
                a = next((v for v in comp
                         if v.variable_type == VariableType.TABLE), comp[0])
                # Bridge onto the nearest owner: the full context chain —
                # exact context, then each enclosing context, then the
                # CTE's own statement context — each with the
                # at-or-before-line pick, excluding the component's own
                # vars (a bridge must connect OUTSIDE the component).
                # No anchor in any stage → last resort: the nearest
                # main-component table-like var by line, so the graph
                # stays one connected piece (topology invariant).
                comp_ids = {v.id for v in comp}
                m = None
                for scope_ctx in _context_stages(a.context or "TOP"):
                    m = _pick_anchor(variables, a, scope_ctx, comp_ids)
                    if m is not None:
                        break
                if m is None:
                    m = _nearest_main_anchor(a, comp_list[0])
                if m is not None:
                    _add_edge(a, m, "SUBSET", "BRIDGE")

    # ══════════════════════════════════════════════════════════════════
    # Phase 8: Ensure ≥2 edges for non-table nodes
    # ══════════════════════════════════════════════════════════════════
    from collections import Counter as _Ctr
    ec = _Ctr()
    for d in deps:
        ec[d.source_id] += 1
        ec[d.target_id] += 1

    skip_if_connected = {VariableType.TABLE, VariableType.VIEW}

    for v in variables:
        if ec.get(v.id, 0) >= 2:
            continue
        if v.variable_type in skip_if_connected and ec.get(v.id, 0) >= 1:
            continue
        # Anchor on the nearest owner: the full context chain — exact
        # context, then each enclosing context, then the CTE's own
        # statement context — each picking the table-like var at-or-
        # before v's line (I3; line-0 virtual nodes take the stage's
        # head). The global first-match fallback is gone — a var with no
        # anchor in any stage stays under-connected.
        anchor = None
        for scope_ctx in _context_stages(v.context or "TOP"):
            anchor = _pick_anchor(variables, v, scope_ctx)
            if anchor is not None:
                break
        if anchor:
            _add_edge(v, anchor, "SUBSET", "BRIDGE")

    return deps


def _classify_relationship(
    src: VariableDefinition, target: VariableDefinition
) -> str:
    """Classify the relationship type between two variables."""
    if target.variable_type in (VariableType.AGGREGATE,):
        return "AGGREGATE"
    if target.variable_type == VariableType.WINDOW:
        return "WINDOW"
    if target.variable_type == VariableType.CASE:
        return "COMPUTED"
    if target.variable_type == VariableType.TRANSFORM:
        return "TRANSFORM"
    if target.variable_type == VariableType.CTE_COLUMN and \
       src.variable_type == VariableType.COLUMN:
        return "TRANSFORM"
    if target.variable_type == VariableType.EXPRESSION:
        # B-series Phase 2: materialized join-key expression nodes
        # (CONCAT/RPAD/|| on columns in JOIN ON) are fed by their operand
        # columns — a plain column reference relationship (REF), not a
        # TRANSFORM, so lineage treats the operands as key inputs.
        if (target.defined_in or "").upper().startswith("JOIN ON"):
            return "REF"
        return "TRANSFORM"
    return "REF"
