"""
Dependency Graph Builder — build variable dependency edges from extraction results.

Phases are ordered top-down: table-level connections first, then column-level
details, then structural edges. This matches how data flows in SQL:
  tables → table-to-table flows → columns carry data between tables.
"""

from collections import defaultdict

from app.models.variable import VariableDefinition, VariableDependency, VariableType
from app.extractor.variable_extractor_v2 import ExtractionResult
from app.extractor.walkable_set import BRIDGE_EMIT_TYPES


# ── Table-like types that participate in table-level data flow ──────────
_TABLE_TYPES = {
    VariableType.TABLE, VariableType.VIEW, VariableType.CTE,
    VariableType.SUBQUERY, VariableType.VIRTUAL_TABLE,
    VariableType.MERGE_TARGET, VariableType.UNION_BRANCH,
}

# ── Column-ish types tracked by the Phase-3 bare-name index (D3): the
# full_col_index type universe — the evidence-scored resolution never
# overrides with a same-named literal/table/proxy var.
_SOURCE_COLUMN_TYPES = {
    VariableType.COLUMN, VariableType.CTE_COLUMN, VariableType.EXPRESSION,
    VariableType.AGGREGATE, VariableType.WINDOW, VariableType.CASE,
    VariableType.TRANSFORM,
}

# Expression-building target types (D3 round dl): the evidence-scored
# source resolution fires only for targets that BUILD a new value from
# their source columns (CASE/expression/aggregate/window/transform vars —
# e.g. DM_FLAG2's CASE over data_dt, or a join-key CONCAT). Plain column
# reads (COLUMN/CTE_COLUMN) keep the legacy last-writer-wins pick — their
# L2 shape is pinned by the bdm/sup/pl benchmark rounds.
_EXPRESSION_BUILDING_TYPES = _SOURCE_COLUMN_TYPES - {
    VariableType.COLUMN, VariableType.CTE_COLUMN,
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

    # 1c-extra2: statement output VT → DML target (the output ⟐ was a
    # dead end — the statement's query output feeds the write).
    # Issue 2 (Fix A, ruling 2026-08-11): the edge IS by definition the
    # write leg — emit DML, not TABLE_FLOW, so every DML target gets a
    # raw DML edge and the L2 rewrite stamps the write kind uniformly
    # (TOP0 sup used to survive unstamped and render as a chain — the
    # "3 parallel lines, 1 inverse" defect). The Phase-1c src_vars/
    # fallback DML edges already cover duplicate pairs and _add_edge
    # dedup absorbs the overlap; no ordering dependency.
    for tbl_var, op_type in dml_entries:
        ctx = tbl_var.context or "TOP"
        out_vts = [a for a in vt_map.get(ctx, [])
                   if a.variable_type == VariableType.VIRTUAL_TABLE]
        if len(out_vts) == 1:
            _add_edge(out_vts[0], tbl_var, "DML", op_type)

    # 1c-cross: cross-statement write->read. For each DML target (stmt n),
    # find TABLE/VIEW reads of the same canonical table name in OTHER
    # statements (context TOP{m}, m != n) and emit target -> READER
    # (write->read edge through the reader instance — Issue 3 no-bypass).
    # Must run before Phase 7/8 so the union-find sees the cross-statement
    # connection and the Phase-7 SUBSET bridge is not needed.
    def _stmt_key(v):
        ctx = v.context or "TOP"
        if ctx.startswith("TOP"):
            return ctx.split("/", 1)[0]
        return None  # CTE{...} bodies: statement not encoded in context

    # Issue 3: the DML-target-per-statement index was only used to
    # shortcut the write→read link onto the reader statement's DML target
    # — that bypass is gone (the link now routes through the reader
    # instance itself), so the index is gone with it.
    for tbl_var, op_type in dml_entries:
        t_stmt = _stmt_key(tbl_var)
        if t_stmt is None:
            continue
        canon = (tbl_var.source_tables[0] if tbl_var.source_tables
                 else tbl_var.name)
        for v in variables:
            if v.variable_type not in (VariableType.TABLE, VariableType.VIEW):
                continue
            if v.id == tbl_var.id:
                continue
            r_stmt = _stmt_key(v)
            if r_stmt is None or r_stmt == t_stmt:
                continue
            # E2 (1c-cross order guard): the reader appears BEFORE the
            # writer — a same-name table occurrence in an earlier statement
            # cannot be consuming THIS statement's write (the old code
            # emitted reversed write-after-read edges).
            if (int(tbl_var.line_start or 0) > 0 and int(v.line_start or 0) > 0
                    and tbl_var.line_start > v.line_start):
                continue
            if not (v.name == canon or
                    (v.source_tables and v.source_tables[0] == canon)):
                continue
            # Issue 3 (R19.3 no-bypass, user ruling 2026-08-11): the
            # write→read link routes THROUGH the reader instance — emit
            # the edge to the reader var v itself (sup@160 → sup@223),
            # never directly to the reader statement's DML target (the
            # old shortcut sup@160 → rrcdm@211 bypassed the reader and
            # hid the statement-2 read from the flow walker). The reader
            # then carries the flow onward through its own Phase-1a
            # (sup@223 → output2) and 1c-extra (sup@223 → rrcdm) edges;
            # `tgt` selection is gone — v is always the endpoint.
            _add_edge(tbl_var, v, "DML", "WRITE_READ")

    # 1c-direct: CTE output feeds its readers directly. A reference var
    # (TABLE/VIEW alias with source_tables[0] == CTE name) inside a CTE
    # body context CTE{Y} links CTE X -> CTE Y; a statement-level
    # reference links CTE X -> the statement's DML target. Direct edges
    # make the canonical endpoint keys (CTE var line -> reader line) pair
    # up exactly.
    cte_by_name: dict[str, list[VariableDefinition]] = defaultdict(list)
    for v in variables:
        if v.variable_type == VariableType.CTE:
            cte_by_name[v.name].append(v)
    for v in variables:
        if v.variable_type not in (VariableType.TABLE, VariableType.VIEW):
            continue
        if not v.source_tables:
            continue
        src_ctes = cte_by_name.get(v.source_tables[0])
        if not src_ctes:
            continue
        ctx = v.context or "TOP"
        if ctx.startswith("CTE{") and "}" in ctx:
            body_ctes = cte_by_name.get(ctx[4:ctx.index("}")])
            if not body_ctes:
                continue
            for src in src_ctes:
                for body in body_ctes:
                    if (src.id != body.id
                            and (src.context or "TOP") == (body.context or "TOP")):
                        _add_edge(src, body, "TABLE_FLOW", "REFERENCE")
        else:
            stmt = ctx.split("/", 1)[0]
            for tbl_var, op_type in dml_entries:
                if (tbl_var.context or "TOP") != stmt:
                    continue
                for src in src_ctes:
                    if (src.context or "TOP") != stmt:
                        # E1 (1c-direct cross-statement gate): a CTE
                        # defined in ANOTHER statement is not the reader's
                        # source — CTEs are statement-scoped, so the
                        # reader links only to same-statement defs (the old
                        # code paired the reader with any same-name CTE,
                        # emitting spurious cross-statement edges).
                        continue
                    if src.id != tbl_var.id:
                        _add_edge(src, tbl_var, "TABLE_FLOW", op_type)

    # 1c-self: the statement's write reads its own target (self-join into
    # the DML target) when a same-context FROM/JOIN alias of the target
    # table exists. Expressed as a TABLE_FLOW self-loop on the DML target.
    # Appended directly (the _add_edge guard forbids self-loops by design;
    # this one is deliberate and deduped via seen_edges).
    for tbl_var, op_type in dml_entries:
        ek = (tbl_var.id, tbl_var.id, "TABLE_FLOW")
        if ek in seen_edges:
            continue
        ctx = tbl_var.context or "TOP"
        for v in variables:
            if v.variable_type not in (VariableType.TABLE, VariableType.VIEW):
                continue
            if (v.context or "TOP") != ctx or v.id == tbl_var.id:
                continue
            if v.source_tables and v.source_tables[0] == tbl_var.name:
                seen_edges.add(ek)
                deps.append(VariableDependency(
                    source_id=tbl_var.id, target_id=tbl_var.id,
                    relationship="TABLE_FLOW", operation="SELF_JOIN",
                    sql_context=f"{tbl_var.name} → {tbl_var.name}",
                ))
                break

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
    # D3 (dl seed, 2026-08-12): a repeated column name read in several
    # contexts resolves by extraction-time evidence ONLY when the
    # last-writer-wins pick (full_col_index) lands OUTSIDE the target's
    # own statement — a read inside an expression cannot reach into
    # another statement's instance. DM_FLAG2's EXISTS-subquery
    # BDM_ACC_INTERNAL_COUNTERPARTY.data_dt@407 (TOP0/exists3) resolved
    # to the TOP1 WHERE instance data_dt@560; the target's OWN expression
    # tables (recorded at extraction time via _extract_table_names) bound
    # the possible read sites — a read inside the expression must be
    # attributed to a table the expression mentions. Among the target's
    # statement-root candidates (registration order), the first whose
    # attributed source table (source_tables[0], case-insensitive)
    # appears in the target's expression tables wins; no evidence match
    # keeps the previous last-writer-wins pick. Same-root picks are
    # never overridden (the SUP flagship's CONCAT join-key operands —
    # repeated `p2.xxx` aliases inside one CTE — stay byte-identical).
    def _stmt_root(ctx: str) -> str:
        """Statement root of a context: 'TOP0/exists3' → 'TOP0',
        'CTE{a}:join:p2/subq/x' → 'CTE{a}', 'TOP0:join:p3/…' → 'TOP0'."""
        return (ctx or "TOP").split(":join:")[0].split("/")[0]

    def _pick_source_var(src_col: str, target_var: VariableDefinition):
        if src_col not in full_col_index:
            return None
        old_pick = full_col_index[src_col]
        candidates = name_index.get(src_col, [])
        if (len(candidates) > 1 and target_var.source_tables
                and target_var.variable_type in _EXPRESSION_BUILDING_TYPES):
            target_root = _stmt_root(target_var.context)
            if _stmt_root(old_pick.context) != target_root:
                target_tables = {t.lower() for t in target_var.source_tables}
                for cand in candidates:
                    if cand.variable_type not in _SOURCE_COLUMN_TYPES:
                        continue  # same type universe as full_col_index
                    if _stmt_root(cand.context) != target_root:
                        continue  # a read inside the target's own statement only
                    if cand.source_tables and cand.source_tables[0].lower() in target_tables:
                        return cand
        return old_pick

    for target_var in variables:
        for src_col in target_var.source_columns:
            src_var = _pick_source_var(src_col, target_var)
            if src_var is not None:
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

    # Phase 4d: READ — column → its own-scope alias/physical table (the
    # table the read is attributed to at extraction time, I2). The
    # canonical field→table read edge. W-iteration (v3.3.147): every read
    # is REF/READ — a join-condition read is still a READ of the key
    # through its alias (user ruling, addendum 3: "the READ rule applies",
    # pair 19 → anchor 199), and BARE columns (WHERE data_dt = ...,
    # pair 18) get the same read edge to their owner table's same-context
    # instance (Phase 7/8 only ever bridged them FILTER/CONDITION). No
    # SUBSET escapes this phase.
    for v in variables:
        if v.variable_type != VariableType.COLUMN:
            continue
        if not v.source_tables:      # I2: attributed at extraction time
            continue
        ctx = v.context or "TOP"
        if "." in v.name:
            prefix = v.name.split(".", 1)[0]
            match_t = lambda t: (t.name == prefix and t.id != v.id
                                 and t.source_tables
                                 and t.source_tables[0] == v.source_tables[0])
        else:
            # Bare column: the owner's own instance in the same context
            # (bdm_acc_loan_info_sup@223 for the statement-2 WHERE read).
            match_t = lambda t: (t.name == v.source_tables[0]
                                 and t.id != v.id)
        for t in variables:
            if t.variable_type not in (VariableType.TABLE, VariableType.VIEW):
                continue
            if (t.context or "TOP") != ctx:
                continue
            if match_t(t):
                _add_edge(v, t, "REF", "READ")
                break

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
    # W3: Phase-7 SUBSET bridges are EXCLUDED from the edge count — an
    # incoming Phase-7 bridge on a TABLE's own bridge partner inflated
    # ec to ≥2 and left pair 2 (bdm@16 → rollover@9) and the subquery-
    # body TABLE→VT bridges stuck at SUBSET (Phase 8 skips them before
    # the re-type path runs). Only real (non-SUBSET) edges mean
    # "already connected".
    ec = _Ctr()
    for d in deps:
        if d.relationship == "SUBSET":
            continue
        ec[d.source_id] += 1
        ec[d.target_id] += 1

    skip_if_connected = {VariableType.TABLE, VariableType.VIEW}

    # W3 (v3.3.7x): the Phase-8 bridge is typed HONESTLY from
    # extraction-time info only (the vars' own types/defined_in — never
    # a render-time filter or closure scan):
    #   (a) predicate columns (WHERE/HAVING/QUALIFY)     → FILTER/CONDITION
    #   (b) non-table vars anchored on a DML target       → DML/<keyword>
    #       (the INSERT-target's partition/projection columns read as
    #       write-side — pair 12 data_dt@160 → bdm_acc_loan_info_sup@160)
    #   (c) join-condition columns (JOIN ON)              → JOIN/JOIN_CONDITION
    #   (d) any other non-table var                       → REF/READ
    #   (e) TABLE/VIEW → query-type anchor (CTE/SUBQUERY/
    #       VIRTUAL_TABLE/UNION_BRANCH)                   → TABLE_FLOW/REFERENCE
    #   (f) TABLE/VIEW → physical TABLE/MERGE_TARGET      → SUBSET/BRIDGE
    #       (the only SUBSET that may leave this phase — B1
    #       sup@223 → rrcdm@211 must stay SUBSET)
    #   (g) Every emitted type is a member of BRIDGE_EMIT_TYPES — the
    #       walkable-set contract (app/extractor/walkable_set.py): REF is
    #       FIELD_WALKABLE, FILTER/JOIN/DML/TABLE_FLOW are CONDITIONAL,
    #       SUBSET is NEVER_WALKED (the honest fallback for physical-
    #       table bridges). The bridge palette IS the walker's own
    #       vocabulary, pinned by tests/test_walkable_set.py — a new
    #       bridge type is a contract change, never a local one.
    _QUERY_ANCHOR_TYPES = {VariableType.CTE, VariableType.SUBQUERY,
                           VariableType.VIRTUAL_TABLE,
                           VariableType.UNION_BRANCH}
    _DML_WORDS = ("UPDATE", "DELETE", "MERGE", "INSERT")

    def _bridge_typing(v, anchor) -> tuple[str, str]:
        """W3 honest Phase-8 bridge typing (rules (a)-(f) above). Emits
        only BRIDGE_EMIT_TYPES (walkable-set contract) — a bridge must
        land on a type the strict walker classifies: REF is
        FIELD_WALKABLE, FILTER/JOIN/DML/TABLE_FLOW are CONDITIONAL,
        SUBSET is NEVER_WALKED."""
        di = (v.defined_in or "").strip().upper()
        ai = (anchor.defined_in or "").upper()
        if v.variable_type == VariableType.COLUMN \
                and di in ("WHERE", "HAVING", "QUALIFY"):
            return "FILTER", "CONDITION"
        if v.variable_type == VariableType.COLUMN and di == "JOIN ON":
            return "JOIN", "JOIN_CONDITION"
        if v.variable_type not in _TABLE_TYPES:
            for word in _DML_WORDS:
                if word in ai:
                    return "DML", word
            return "REF", "READ"
        if v.variable_type in (VariableType.TABLE, VariableType.VIEW):
            if anchor.variable_type in _QUERY_ANCHOR_TYPES:
                return "TABLE_FLOW", "REFERENCE"
            return "SUBSET", "BRIDGE"
        return "REF", "READ"

    def _bridge_target(v):
        """Nearest owner across the full context chain (I3) — the same
        deterministic pick for every phase-8 candidate."""
        for scope_ctx in _context_stages(v.context or "TOP"):
            anchor = _pick_anchor(variables, v, scope_ctx)
            if anchor is not None:
                return anchor
        return None

    def _retype_or_add(v, anchor, rel, op):
        existing = next((d for d in deps
                         if d.source_id == v.id
                         and d.target_id == anchor.id), None)
        if existing is not None:
            if existing.relationship != "SUBSET":
                # W-iteration (v3.3.147): a REAL edge already connects this
                # pair — the Phase-4d REF/READ (data_dt@225 → sup@223,
                # pair 18) must never be clobbered. The bridge is added
                # alongside below (the FILTER/CONDITION at the column's own
                # line still expresses the WHERE participation).
                pass
            else:
                # Phase 7 may already have bridged this exact pair as
                # SUBSET/BRIDGE — re-type that edge honestly instead of
                # adding a duplicate (W3: the pinned pairs 1/2/12/18 sit on
                # Phase-7-bridged singleton components).
                existing.relationship = rel
                existing.operation = op
                return
        _add_edge(v, anchor, rel, op)

    for v in variables:
        if v.variable_type in skip_if_connected:
            # TABLE/VIEW handled FIRST (before the ec≥2 skip): a table
            # referenced inside a CTE/subquery body whose ec was raised
            # to ≥2 by the Phase-4d REF/READs (pair 2 bdm@16, ec=3) must
            # still get its chain bridge to the owning query — the old
            # ordering skipped it at the ec≥2 gate and left pair 2 stuck
            # at SUBSET/BRIDGE.
            if ec.get(v.id, 0) >= 1:
                # TABLE/VIEW already has real edges. Never ADD a bridge to
                # a var that already connects to its anchor (the ALIAS
                # bdm@29→p1@29 already expresses that hop); re-type an
                # existing SUBSET to the same anchor (W3). The W-iteration
                # case (v3.3.147): a CTE/subquery-body reference whose
                # ec was raised to ≥1 by the Phase-4d REF/READs (pair 2
                # bdm@16 → rollover@9) — the old ec=0 path no longer
                # fires, so the chain bridge is re-added here with honest
                # typing. (Only CTE-internal bodies pass the TOP-context
                # guard below — statement-level subquery bodies never get
                # new bridges.)
                anchor = _bridge_target(v)
                if anchor is None:
                    continue
                existing = next((d for d in deps
                                 if d.source_id == v.id
                                 and d.target_id == anchor.id), None)
                if existing is not None:
                    if existing.relationship == "SUBSET":
                        existing.relationship, existing.operation = \
                            _bridge_typing(v, anchor)
                    continue
                if (v.context or "TOP").startswith("TOP"):
                    # Statement-level table with real edges: no bridge —
                    # the DML-routed ⟐ output already carries the write
                    # edge (rrcdm@211 → ⟐output@211 would duplicate it).
                    continue
                rel, op = _bridge_typing(v, anchor)
                if rel != "TABLE_FLOW":
                    # (f) TABLE→physical TABLE stays SUBSET only for the
                    # residual Phase-7 bridge (B1) — never add new ones.
                    continue
                _add_edge(v, anchor, rel, op)
                continue
            # TABLE/VIEW with no real edges: only Phase-7 SUBSET bridges
            # remain — re-type the EXISTING bridge to its EXISTING target
            # (the Phase-7 pick can differ from the Phase-8 pick when it
            # used the nearest-main fallback — B1 sup@223 → rrcdm@211 —
            # so the existing target is the honest one to type). If no
            # Phase-7 bridge exists at all, a new edge may still be added
            # from the Phase-8 anchor pick (the fallback below).
            bridge = next((d for d in deps
                           if d.source_id == v.id
                           and d.relationship == "SUBSET"), None)
            if bridge is not None:
                tgt = id_index.get(bridge.target_id)
                if tgt is not None:
                    rel, op = _bridge_typing(v, tgt)
                    bridge.relationship, bridge.operation = rel, op
                continue
            anchor = _bridge_target(v)
            if anchor:
                rel, op = _bridge_typing(v, anchor)
                _add_edge(v, anchor, rel, op)
            continue
        if ec.get(v.id, 0) >= 2:
            continue
        anchor = _bridge_target(v)
        if anchor:
            rel, op = _bridge_typing(v, anchor)
            _retype_or_add(v, anchor, rel, op)

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
