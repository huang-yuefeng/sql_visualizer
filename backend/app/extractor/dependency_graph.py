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

    # ── Table anchor index (VTs + CTEs as output containers) ─────────
    vt_map: dict[str, list[VariableDefinition]] = defaultdict(list)
    all_anchors: list[VariableDefinition] = []
    for v in variables:
        if v.variable_type == VariableType.VIRTUAL_TABLE:
            vt_map[v.context or "TOP"].append(v)
            all_anchors.append(v)
        elif v.variable_type == VariableType.CTE:
            cte_ctx = f"CTE:{v.name}"
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

    def _add_edge(src, tgt, rel, op="", ctx=""):
        ek = (src.id, tgt.id)
        if ek not in seen_edges and src.id != tgt.id:
            seen_edges.add(ek)
            deps.append(VariableDependency(
                source_id=src.id, target_id=tgt.id,
                relationship=rel, operation=op,
                sql_context=ctx or f"{src.name} → {tgt.name}",
            ))

    # 1a: FROM / JOIN table alias → its context anchor (VT or CTE)
    #     This shows "table u feeds the SELECT / CTE output"
    for v in variables:
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
        if ":" in ctx:
            parent_ctx = ctx.rsplit(":", 1)[0]
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

    # 1d: UNION branch → parent context VT
    for v in variables:
        if v.variable_type != VariableType.UNION_BRANCH:
            continue
        ctx = v.context or "TOP"
        for anchor in vt_map.get(ctx, []):
            _add_edge(v, anchor, "TABLE_FLOW", "SET")

    # ══════════════════════════════════════════════════════════════════
    # Phase 2: ALIAS — original table → alias
    # Data flows FROM the real table/CTE TO its alias reference:
    #   FROM users u        → users ──ALIAS──→ u
    #   FROM customer_total_return ctr1 → customer_total_return ──ALIAS──→ ctr1
    for v in variables:
        if v.variable_type == VariableType.TABLE and v.source_tables:
            for orig_name in v.source_tables:
                orig_vars = [x for x in variables
                             if x.variable_type in (VariableType.TABLE, VariableType.CTE)
                             and x.name == orig_name and not x.source_tables]
                for orig_var in orig_vars:
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
    for v in variables:
        if v.variable_type != VariableType.CTE:
            continue
        cte_prefix = f"CTE:{v.name}"
        for inner in variables:
            if inner.defined_in and (
                inner.defined_in == cte_prefix
                or inner.defined_in.startswith(cte_prefix)
            ):
                if inner.variable_type == VariableType.CTE:
                    continue
                _add_edge(v, inner, "SCHEMA", "TABLE_COLUMN")

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

    # ══════════════════════════════════════════════════════════════════
    # Phase 6: FILTER — WHERE/HAVING column → context anchor
    # ══════════════════════════════════════════════════════════════════
    # Only columns from WHERE, HAVING, or JOIN ON clauses. These influence
    # which rows flow through without producing output data themselves.
    # SELECT expression sources (like o.amount consumed by SUM) and
    # general column references do NOT get FILTER edges.
    _FILTER_CLAUSES = {"WHERE", "HAVING", "JOIN ON"}
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
    # Phase 7: SUBSET — safety net for disconnected components
    # ══════════════════════════════════════════════════════════════════
    # Union-Find to find disconnected components, bridge them.
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
                m = comp_list[0][0]
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
        ctx = v.context or "TOP"
        anchor = next((x for x in variables
                       if x.variable_type in _TABLE_TYPES
                       and (x.context or "TOP") == ctx
                       and x.id != v.id), None)
        if not anchor and ":" in ctx:
            pctx = ctx.rsplit(":", 1)[0]
            anchor = next((x for x in variables
                           if x.variable_type in _TABLE_TYPES
                           and (x.context or "TOP") == pctx
                           and x.id != v.id), None)
        if not anchor:
            anchor = next((x for x in variables
                           if x.variable_type in _TABLE_TYPES
                           and x.id != v.id), None)
        if anchor:
            _add_edge(v, anchor, "FILTER", "CONDITION")

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
        return "TRANSFORM"
    return "REF"
