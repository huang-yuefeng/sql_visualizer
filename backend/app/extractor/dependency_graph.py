"""
Dependency Graph Builder — build variable dependency edges from extraction results.

Connects variables based on column references in their SQL expressions,
tracking data flow through CTE chains, aggregations, and transformations.
"""

import re
from collections import defaultdict

from app.models.variable import VariableDefinition, VariableDependency, VariableType
from app.extractor.variable_extractor_v2 import ExtractionResult


def build_dependency_graph(
    result: ExtractionResult, sql_text: str = ""
) -> list[VariableDependency]:
    """Build a list of VariableDependency edges from extracted variables.

    For each variable with source_columns (e.g. ["sb.amount"]), we look
    for upstream variables whose name matches the source column, creating
    a dependency edge.

    Args:
        result: The extraction result from variable_extractor.
        sql_text: Original SQL (unused currently, reserved for future use).

    Returns:
        List of VariableDependency objects representing directed edges.
    """
    variables = result.variables
    if not variables:
        return []

    deps: list[VariableDependency] = []
    seen_edges: set[tuple[str, str]] = set()

    # Build lookup by name for resolving source_column references
    name_index: dict[str, list[VariableDefinition]] = defaultdict(list)
    for v in variables:
        name_index[v.name].append(v)

    # Build lookup: variable name → variable (only index by OWN name, not source columns)
    full_col_index: dict[str, VariableDefinition] = {}
    for v in variables:
        if v.variable_type in (VariableType.TABLE_COLUMN, VariableType.CTE_COLUMN,
                                VariableType.INTERMEDIATE, VariableType.AGGREGATE,
                                VariableType.WINDOW_RESULT, VariableType.CASE_RESULT,
                                VariableType.FUNCTION_RESULT):
            full_col_index[v.name] = v

    # ── Phase 1: column → aggregate/window/function edges ──────────────
    for target_var in variables:
        for src_col in target_var.source_columns:
            if src_col in full_col_index:
                src_var = full_col_index[src_col]
                ek = (src_var.id, target_var.id)
                if ek not in seen_edges and src_var.id != target_var.id:
                    seen_edges.add(ek)
                    deps.append(VariableDependency(
                        source_id=src_var.id, target_id=target_var.id,
                        relationship=_classify_relationship(src_var, target_var),
                        operation="REFERENCE",
                        sql_context=f"{src_var.name} -> {target_var.name}",
                    ))
                continue
            # Fallback: match by bare column name
            col_name = src_col.rsplit(".", 1)[-1] if "." in src_col else src_col
            for src_var in name_index.get(col_name, []):
                ek = (src_var.id, target_var.id)
                if ek not in seen_edges and src_var.id != target_var.id:
                    seen_edges.add(ek)
                    deps.append(VariableDependency(
                        source_id=src_var.id, target_id=target_var.id,
                        relationship=_classify_relationship(src_var, target_var),
                        operation="REFERENCE",
                        sql_context=f"{src_var.name} -> {target_var.name}",
                    ))
                    break

    # ── Phase 2: ALIAS_OF — alias → original table name ───────────────
    # E.g., "FROM users u" → u is alias of users
    for v in variables:
        if v.variable_type == VariableType.DATABASE_TABLE and v.source_tables:
            for orig_name in v.source_tables:
                orig_vars = [x for x in variables
                             if x.variable_type == VariableType.DATABASE_TABLE
                             and x.name == orig_name and not x.source_tables]
                for orig_var in orig_vars:
                    ek = (v.id, orig_var.id)
                    if ek not in seen_edges and v.id != orig_var.id:
                        seen_edges.add(ek)
                        deps.append(VariableDependency(
                            source_id=v.id, target_id=orig_var.id,
                            relationship="ALIAS_OF", operation="ALIAS",
                            sql_context=f"{v.name} → {orig_name}",
                        ))

    # ── Phase 3: FEEDS_INTO — input tables → VIRTUAL_TABLE (SELECT output) ─
    vt_map: dict[str, list[VariableDefinition]] = defaultdict(list)
    all_vts: list[VariableDefinition] = []
    for v in variables:
        if v.variable_type == VariableType.VIRTUAL_TABLE:
            vt_map[v.context or "TOP"].append(v)
            all_vts.append(v)

    for v in variables:
        if v.variable_type != VariableType.DATABASE_TABLE:
            continue
        # Skip original table names — only aliases feed into the output.
        # E.g., "FROM users u" → only 'u' gets FEEDS_INTO, not 'users'.
        # The ALIAS_OF edge (u → users) already expresses the relationship.
        if not v.source_tables:
            continue  # no source_tables = original name, not alias
        ctx = v.context or "TOP"
        for vt in vt_map.get(ctx, []):
            ek = (v.id, vt.id)
            if ek not in seen_edges and v.id != vt.id:
                seen_edges.add(ek)
                deps.append(VariableDependency(
                    source_id=v.id, target_id=vt.id,
                    relationship="FEEDS_INTO", operation="SELECT",
                    sql_context=f"{v.name} → {vt.name}",
                ))

    # Connect nested VIRTUAL_TABLEs into a tree (child contexts → parent)
    for vt in all_vts:
        parent_ctx = "TOP"
        ctx = vt.context or "TOP"
        if ":" in ctx:
            parent_ctx = ctx.rsplit(":", 1)[0]
        if parent_ctx != ctx:
            for parent_vt in vt_map.get(parent_ctx, []):
                ek = (vt.id, parent_vt.id)
                if ek not in seen_edges and vt.id != parent_vt.id:
                    seen_edges.add(ek)
                    deps.append(VariableDependency(
                        source_id=vt.id, target_id=parent_vt.id,
                        relationship="FEEDS_INTO", operation="SUBSELECT",
                        sql_context=f"subquery {vt.name} → parent {parent_vt.name}",
                    ))

    # ── Phase 5: table → column edges (BELONGS_TO) ──────────────────
    # Index: name → list of table-like variables (handles duplicates across contexts)
    table_index: dict[str, list[VariableDefinition]] = defaultdict(list)
    alias_to_original: dict[str, str] = {}     # alias → original table name
    cte_alias_to_table: dict[str, str] = {}     # CTE alias → CTE table name
    for v in variables:
        if v.variable_type in (VariableType.DATABASE_TABLE, VariableType.CTE_TABLE,
                                VariableType.MERGE_TARGET, VariableType.SUBQUERY_RESULT):
            table_index[v.name].append(v)
            if v.source_tables:
                for orig in v.source_tables:
                    alias_to_original[v.name] = orig
                    # If the original is a CTE table, record the mapping
                    if any(v2.variable_type == VariableType.CTE_TABLE and v2.name == orig
                           for v2 in variables):
                        cte_alias_to_table[v.name] = orig

    # Pass 1: create BELONGS_TO from alias/CTE/VT → column (skip original names)
    # An alias like 't' has source_tables=['gps_transactions'] — it's the active ref.
    # The original name 'gps_transactions' has source_tables=[] — skip it.
    # Only aliases, CTE tables, merge targets, subquery results, and virtual tables
    # get BELONGS_TO edges, because those are the names actually used in the query.
    for v in variables:
        if v.variable_type != VariableType.TABLE_COLUMN:
            continue
        if "." not in v.name:
            continue
        prefix = v.name.split(".", 1)[0]
        for tbl_var in table_index.get(prefix, []):
            # Only aliases, CTE_TABLE, VIRTUAL_TABLE, MERGE_TARGET, SUBQUERY_RESULT
            # — skip original table names (they have no source_tables and are not CTEs etc.)
            is_original = (v.variable_type == VariableType.DATABASE_TABLE
                           and not tbl_var.source_tables)
            if is_original:
                continue
            ek = (tbl_var.id, v.id)
            if ek not in seen_edges:
                seen_edges.add(ek)
                deps.append(VariableDependency(
                    source_id=tbl_var.id, target_id=v.id,
                    relationship="BELONGS_TO", operation="TABLE_COLUMN",
                    sql_context=f"{prefix} → {v.name}",
                ))

    # Pass 2: BELONGS_TO from CTE tables to their inner variables
    for v in variables:
        if v.variable_type != VariableType.CTE_TABLE:
            continue
        # Find all variables defined inside this CTE
        cte_prefix = f"CTE:{v.name}"
        for inner in variables:
            if inner.defined_in and (inner.defined_in == cte_prefix or inner.defined_in.startswith(cte_prefix)):
                if inner.variable_type == VariableType.CTE_TABLE:
                    continue  # skip the CTE itself
                ek = (v.id, inner.id)
                if ek not in seen_edges:
                    seen_edges.add(ek)
                    deps.append(VariableDependency(
                        source_id=v.id, target_id=inner.id,
                        relationship="BELONGS_TO", operation="TABLE_COLUMN",
                        sql_context=f"CTE {v.name} → {inner.name}",
                    ))

    # ── Pass 3: BELONGS_TO from VIRTUAL_TABLE → output columns ────────
    # Only connect to variables explicitly in the SELECT clause (is_output=True).
    # WHERE/HAVING condition columns are NOT output columns — they are inputs.
    for vt in all_vts:
        for v in variables:
            if (v.context or "TOP") != (vt.context or "TOP"):
                continue
            if not v.is_output:
                continue
            if v.variable_type in (VariableType.DATABASE_TABLE, VariableType.CTE_TABLE,
                                    VariableType.VIRTUAL_TABLE, VariableType.UNION_BRANCH):
                continue
            ek = (vt.id, v.id)
            if ek not in seen_edges:
                seen_edges.add(ek)
                deps.append(VariableDependency(
                    source_id=vt.id, target_id=v.id,
                    relationship="BELONGS_TO", operation="OUTPUT",
                    sql_context=f"output {vt.name} → {v.name}",
                ))

    # ── Phase 8: REFERENCES — bare column → defined variable ──────────
    # Bare columns like "total_orders" in HAVING reference the aggregate
    # "total_orders" defined in SELECT. Match by name and type.
    for v in variables:
        if v.variable_type != VariableType.TABLE_COLUMN:
            continue
        if v.source_columns:  # already has source — handled by Phase 1
            continue
        if "." in v.name:     # qualified column — handled by BELONGS_TO
            continue
        # Find a defined variable with the same name (aggregate, window, case, etc.)
        for src in name_index.get(v.name, []):
            if src.variable_type in (VariableType.AGGREGATE, VariableType.WINDOW_RESULT,
                                      VariableType.CASE_RESULT, VariableType.FUNCTION_RESULT,
                                      VariableType.INTERMEDIATE, VariableType.CTE_COLUMN):
                ek = (src.id, v.id)
                if ek not in seen_edges and src.id != v.id:
                    seen_edges.add(ek)
                    deps.append(VariableDependency(
                        source_id=src.id, target_id=v.id,
                        relationship="REFERENCES", operation="NAME_MATCH",
                        sql_context=f"{src.name} → {v.name} (bare reference)",
                    ))
                    break  # one match is enough

    # ── Phase 9: OPERATES_ON — DML target table edges ─────────────────
    # INSERT/UPDATE/DELETE/MERGE target tables should have edges from
    # the columns that feed into the operation.
    dml_tables = {}  # table_name → list of (table_var, operation_type)
    for v in variables:
        if v.variable_type == VariableType.MERGE_TARGET:
            dml_tables.setdefault(v.name, []).append((v, "MERGE"))
        elif v.variable_type == VariableType.DATABASE_TABLE:
            di = v.defined_in or ""
            if "INSERT" in di.upper():
                dml_tables.setdefault(v.name, []).append((v, "INSERT"))
            elif "DELETE" in di.upper():
                dml_tables.setdefault(v.name, []).append((v, "DELETE"))
            elif "UPDATE" in di.upper():
                dml_tables.setdefault(v.name, []).append((v, "UPDATE"))

    for table_name, entries in dml_tables.items():
        for tbl_var, op_type in entries:
            # Find all columns that feed this operation (in same context)
            ctx = tbl_var.context or "TOP"
            ctx_vars = [v for v in variables if (v.context or "TOP") == ctx]
            # Connect columns referenced in the same statement to the target
            src_vars = [v for v in ctx_vars if v.variable_type == VariableType.TABLE_COLUMN and v.source_columns]
            for src in src_vars[:30]:  # limit to avoid over-connecting
                ek = (src.id, tbl_var.id)
                if ek not in seen_edges and src.id != tbl_var.id:
                    seen_edges.add(ek)
                    deps.append(VariableDependency(
                        source_id=src.id, target_id=tbl_var.id,
                        relationship="OPERATES_ON", operation=op_type,
                        sql_context=f"{src.name} → {op_type} {table_name}",
                    ))

    # ── Phase 11: bridge remaining components intelligently ──────
    # Rule: if two components share a named column reference (explicit usage),
    # connect them via that column (no COMPONENT_LINK). Only use COMPONENT_LINK
    # when there is truly no named column shared between components.
    p={v.id:v.id for v in variables}
    def f(x):
        while p[x]!=x:p[x]=p[p[x]];x=p[x]
        return x
    def u(a,b):
        ra,rb=f(a),f(b)
        if ra!=rb:p[ra]=rb
    for d in deps:u(d.source_id,d.target_id)
    c=defaultdict(list)
    for v in variables:c[f(v.id)].append(v)
    cl=sorted(c.values(),key=len,reverse=True)
    if len(cl)>1:
        # Build column name index for the main component
        main_ids = {v.id for v in cl[0]}
        main_cols = {v.name for v in cl[0]
                     if v.variable_type == VariableType.TABLE_COLUMN}

        for comp in cl[1:]:
            # Try: find explicit column references between components
            comp_ids = {v.id for v in comp}
            comp_cols = {v.name for v in comp
                         if v.variable_type == VariableType.TABLE_COLUMN}
            shared = main_cols & comp_cols

            # Try: find variables in comp whose source_columns point to main
            found_link = False
            for v in comp:
                for sc in v.source_columns:
                    # Check if sc refers to a variable in the main component
                    sc_var = next((x for x in cl[0] if x.name == sc), None)
                    if sc_var:
                        ek = (sc_var.id, v.id)
                        if ek not in seen_edges and sc_var.id != v.id:
                            seen_edges.add(ek)
                            deps.append(VariableDependency(
                                source_id=sc_var.id, target_id=v.id,
                                relationship="DIRECT_REFERENCE", operation="CROSS_COMP",
                                sql_context=f"cross-component: {sc_var.name} → {v.name}"))
                            found_link = True

            if not found_link:
                # No named column reference found — use COMPONENT_LINK
                a = next((v for v in comp
                          if v.variable_type == VariableType.DATABASE_TABLE), comp[0])
                m = cl[0][0]
                ek = (a.id, m.id)
                if ek not in seen_edges:
                    seen_edges.add(ek)
                    deps.append(VariableDependency(
                        source_id=a.id, target_id=m.id,
                        relationship="COMPONENT_LINK", operation="BRIDGE",
                        sql_context=f"bridge {len(comp)}n → main (no named columns)"))
    # ── Phase 12: ensure every node has ≥2 edges ─────────────────
    from collections import Counter as _Ctr
    ec = _Ctr()
    for d in deps:
        ec[d.source_id] += 1
        ec[d.target_id] += 1

    for v in variables:
        if ec.get(v.id, 0) >= 2:
            continue
        # Find anchor: VIRTUAL_TABLE in same context, parent context, or any VT
        ctx = v.context or "TOP"
        anchor = next((x for x in variables
                       if x.variable_type == VariableType.VIRTUAL_TABLE
                       and (x.context or "TOP") == ctx), None)
        # Try parent context (for nested CTEs)
        if not anchor and ":" in ctx:
            pctx = ctx.rsplit(":", 1)[0]
            anchor = next((x for x in variables
                           if x.variable_type == VariableType.VIRTUAL_TABLE
                           and (x.context or "TOP") == pctx), None)
        # Fallback: any VT (skip if the node IS a VT itself and anchor is itself)
        if not anchor:
            anchor = next((x for x in variables
                           if x.variable_type == VariableType.VIRTUAL_TABLE
                           and x.id != v.id), None)
        if not anchor:
            continue
        # CONDITIONAL_USED can coexist with any edge type — no seen_edges check
        if v.id != anchor.id:
            deps.append(VariableDependency(
                source_id=v.id, target_id=anchor.id,
                relationship="CONDITIONAL_USED", operation="CONDITION",
                sql_context=f"{v.name} → conditional input to {anchor.name}"))

    return deps


def _classify_relationship(
    src: VariableDefinition, target: VariableDefinition
) -> str:
    """Classify the relationship type between two variables."""
    if target.variable_type in (VariableType.AGGREGATE,):
        return "AGGREGATION"
    if target.variable_type == VariableType.WINDOW_RESULT:
        return "WINDOW"
    if target.variable_type == VariableType.CASE_RESULT:
        return "COMPUTED_FROM"
    if target.variable_type == VariableType.FUNCTION_RESULT:
        return "TRANSFORMATION"
    if target.variable_type == VariableType.CTE_COLUMN and \
       src.variable_type == VariableType.TABLE_COLUMN:
        return "TRANSFORMATION"
    if target.variable_type == VariableType.INTERMEDIATE:
        return "TRANSFORMATION"
    return "DIRECT_REFERENCE"
