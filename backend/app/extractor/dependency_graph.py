"""
Dependency Graph Builder — build variable dependency edges from extraction results.

Phases are ordered top-down: table-level connections first, then column-level
details, then structural edges. This matches how data flows in SQL:
  tables → table-to-table flows → columns carry data between tables.
"""

from collections import Counter, defaultdict

from app.models.variable import VariableDefinition, VariableDependency, VariableType
from app.extractor.variable_extractor_v2 import ExtractionResult
from app.extractor.walkable_set import BRIDGE_EMIT_TYPES


# ── Table-like types that participate in table-level data flow ──────────
_TABLE_TYPES = {
    VariableType.TABLE, VariableType.VIEW, VariableType.CTE,
    VariableType.SUBQUERY, VariableType.VIRTUAL_TABLE,
    VariableType.MERGE_TARGET, VariableType.UNION_BRANCH,
    VariableType.FUNCTION_TABLE,
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


# R45 (2026-08-28.6, F-C family 3): occurrence-line twins carry an
# `OCCURRENCE`-prefixed `defined_in` — the marker says "this var is an
# occurrence-side twin", while the rest of the string is the clause the
# occurrence was collected in. `_clause_of` recovers that clause for the
# SCHEMA-connectivity / FILTER / JOIN gates below.
_OCCURRENCE_PREFIX = "OCCURRENCE"


def _clause_of(defined_in: str | None) -> str:
    di = (defined_in or "").strip().upper()
    if di.startswith(_OCCURRENCE_PREFIX):
        return di[len(_OCCURRENCE_PREFIX):].strip()
    return di


# Tokenizer + clause keywords shared with the extractor's own per-line
# clause machinery (`VariableExtractorV2._line_clauses`, R45 Fix E): the
# same tokenizer, the same keyword map — so a line's clause read here is
# the SAME fact the extractor reads, never a second spelling of it.
from sqlglot import Tokenizer as _Tokenizer  # noqa: E402
from sqlglot.tokens import TokenType as _TokenType  # noqa: E402
from app.extractor.variable_extractor_v2 import (  # noqa: E402
    _LINE_CLAUSE_TOKENS,
)


def line_clause_map(sql_text: str) -> dict[int, str]:
    """line → the clause keyword governing it, over the whole script.

    The extraction-layer read of "is THIS line a line of THAT clause",
    which a var's `defined_in` alone cannot answer for a collapsed (non
    `OCCURRENCE`-stamped) carrier: the group's clause is a fact of the
    GROUP, while the line the collapsed var carries was handed out in
    stream order (R45 Fix B / F-E1) — so a projection line can hold a
    var whose clause says `JOIN ON`. Same semantics as the extractor's
    `_line_clauses`: the clause of a line is the last clause keyword at
    or before it, STRING tokens skipped (a literal 'where' is text).
    Statement heads self-label (`INSERT`/`SELECT`/… are clause keywords
    in the map), so a clause never leaks into the next statement's
    carrier lines.

    Consumers: l2_builder's field-involvement admission (Class 1 — a JOIN
    carrier may anchor only on a join-site line).
    """
    out: dict[int, str] = {}
    if not sql_text:
        return out
    try:
        toks = list(_Tokenizer().tokenize(sql_text))
    except Exception:            # mirror of the extractor: no tokens → no clauses
        return out
    cur = ""
    for tok in toks:
        if tok.token_type != _TokenType.STRING:
            kw = (_LINE_CLAUSE_TOKENS.get(tok.token_type.name)
                  or _LINE_CLAUSE_TOKENS.get(tok.text.lower()))
            if kw:
                cur = kw
        out[tok.line] = cur
    return out


# Clause labels the extractor stamps on a COLUMN var inside a MERGE
# statement (`_walk_merge`) plus the ordinary `JOIN ON` — the clauses whose
# columns belong to a table the extractor attributes at extraction time but
# whose belongs-to edge no other phase emits when the column is spelled
# through its PHYSICAL owner (Phase 4a skips original table names by
# design). `MERGE`/`MERGE USING` label MERGE_TARGET/SUBQUERY vars, never a
# column, so they are not in the set.
_MERGE_COLUMN_CLAUSES = {
    "MERGE ON", "MERGE UPDATE SET", "MERGE WHEN", "MERGE INSERT", "JOIN ON",
}


def _case_alias_spans(sql_text: str) -> dict[tuple[int, str], int]:
    """(END line, alias) → the first line of the CASE that alias closes.

    Rule 4e's producing-expression resolution (2026-08-28.14): a CASE
    output column's variable anchors at its AS-alias line, so the alias
    named at `END AS <alias>` is the key that identifies the CASE producing
    the value, and the span [CASE line, END line] is the expression's own
    lines. Same tokenizer as `line_clause_map`, and the same nesting count
    the extractor's `_case_arm_roles` walks — `END` pushes, `CASE` pops, so
    a nested CASE inside an arm never closes the outer one. An alias that
    is not preceded by `END AS` (`SELECT x AS y`) never enters the map, and
    an untokenizable script yields an empty map (callers keep every anchor
    they had — the rule never guesses).
    """
    out: dict[tuple[int, str], int] = {}
    if not sql_text:
        return out
    try:
        toks = list(_Tokenizer().tokenize(sql_text))
    except Exception:            # mirror of the extractor: no tokens → no spans
        return out
    n = len(toks)
    for i, tok in enumerate(toks):
        if tok.text.lower() != "as" \
                or tok.token_type == _TokenType.STRING:
            continue
        if i == 0 or toks[i - 1].token_type != _TokenType.END:
            continue
        if i + 1 >= n or toks[i + 1].token_type not in (
                _TokenType.VAR, _TokenType.IDENTIFIER):
            continue
        alias = toks[i + 1].text
        depth = 0
        k = i - 1
        while k >= 0:
            tt = toks[k].token_type
            if tt == _TokenType.END:
                depth += 1
            elif tt == _TokenType.CASE:
                depth -= 1
                if depth == 0:
                    out[(toks[i - 1].line, alias.casefold())] = toks[k].line
                    break
            k -= 1
    return out


def _producer_occurrence_in_span(
    variables: list, src, lo: int, hi: int,
):
    """The occurrence twin of `src`'s field INSIDE [lo, hi] — rule 4e's
    anchor, or None when no such variable exists (the keeper anchor stays).

    Identity is the pair the extraction layer already records: the SAME
    owner (`source_tables[0]`, case-insensitive — an unattributed source is
    never re-parented onto a guessed owner) and the SAME field part (the
    name's last dot-segment: `a.charge_department` and its owner-qualified
    twin `bdm_acc_entrusted_payment.charge_department` are the same field
    spelled through an alias handle and through its owner). The candidate
    must be a COLUMN of the source's own context inside the span, and the
    first candidate in registration order wins — script order is the
    corpus's determinism convention (Phase 3's last-writer-wins pick uses
    the same order), so the re-anchor is a set function of the SQL text.
    """
    if not src.source_tables:
        return None
    owner = src.source_tables[0].casefold()
    part = src.name.rsplit(".", 1)[-1].casefold()
    for v in variables:
        if v.id == src.id or v.variable_type != VariableType.COLUMN:
            continue
        if (v.context or "TOP") != (src.context or "TOP"):
            continue
        line = int(v.line_start or 0)
        if not line or line < lo or line > hi:
            continue
        if not v.source_tables or v.source_tables[0].casefold() != owner:
            continue
        if v.name.rsplit(".", 1)[-1].casefold() != part:
            continue
        return v
    return None


def _statement_scope(context: str | None) -> str:
    """The statement-level scope of a (possibly nested) context — the
    dependency-graph half of the extractor's `_scope_top` folding.

    Contexts are `TOP{n}` / `CTE{name}` (this corpus), with
    `VIEW@{stmt}:{name}` / `CTAS@{stmt}:{name}` / `VIEW:{name}` handled the
    same way the extractor folds them (`:` is part of the statement identity
    there, not a nested-scope separator). The root segment identifies the
    statement a var belongs to, so a search keyed on it can never reach into
    another statement."""
    ctx = context or "TOP"
    for prefix in ("VIEW@", "CTAS@"):
        if ctx.startswith(prefix):
            i = ctx.find(":", len(prefix))
            return ctx[:i] if i > 0 else ctx
    for prefix in ("VIEW:", "CTAS:"):
        if ctx.startswith(prefix):
            rest = ctx[len(prefix):]
            for sep in ("/", ":"):
                i = rest.find(sep)
                if i > 0:
                    rest = rest[:i]
            return prefix + rest
    if ctx.startswith("CTE{"):
        end = ctx.find("}")
        return ctx[:end + 1] if end > 0 else ctx
    for sep in ("/", ":"):
        i = ctx.find(sep)
        if i > 0:
            return ctx[:i]
    return ctx


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
        if v.variable_type not in (VariableType.TABLE, VariableType.VIEW,
                                   VariableType.FUNCTION_TABLE):
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
            if v.variable_type not in (VariableType.TABLE, VariableType.VIEW,
                                       VariableType.FUNCTION_TABLE):
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
            if v.variable_type not in (VariableType.TABLE, VariableType.VIEW,
                                       VariableType.FUNCTION_TABLE):
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
        if v.variable_type not in (VariableType.TABLE, VariableType.VIEW,
                                   VariableType.FUNCTION_TABLE):
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
            if v.variable_type not in (VariableType.TABLE, VariableType.VIEW,
                                       VariableType.FUNCTION_TABLE):
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

    # ── G7 RC-C (2026-08-28.10): the container provenance edge — G1's
    # withheld stage 2, LANDED. ──────────────────────────────────────────
    # A handle read (`p6.lending_ref`, `P1.REPAY_ACCT_NO`,
    # `A.Reserved_Field9`) is attributed to the CONTAINER the handle denotes
    # (source_tables[0] names a CTE / derived container), but the Phase-3
    # loop above rarely wires that container's own output column to the
    # read: a bare handle carries no source_columns at all (nothing to look
    # up), and a projection-shaped read records its own handle spelling as
    # its source column, which the last-writer-wins index resolves to an
    # unrelated same-named var in a LATER statement. Either way the seam is
    # the same: no edge connects the container body that produces the value
    # to the reader that consumes it, so every container chain in the script
    # is value-disconnected exactly there (RC-C: the whole upstream chain of
    # bdm_acc_loan_info.repay_acct_no stayed dark while its downstream reads
    # were lit — the chain crosses CTE{TEMP_BDM_ACC_LOAN_INFO_01} →
    # CTE{TEMP_BDM_ACC_LOAN_INFO_02} → TOP0 and each crossing is this
    # missing edge).
    #
    # G1 withheld the edge (2026-08-28.9) because it grew SUP_M's
    # lending_ref closure past the THEN-canonical set; those canonical rows
    # are re-derived now (G8 owns jaccard_canonical), and the growth is the
    # honest consequence of the dark lines lighting. The edge is wired with
    # the shape G1 prototyped, narrowed to a PROVENANCE rule (never a name
    # match) by three guards:
    #
    #   1. the attributed source must BE a container (CTE / SUBQUERY /
    #      VIRTUAL_TABLE) — a read of a physical table keeps its Phase-3 /
    #      Phase-4d wiring and never gains a synthetic producer;
    #   2. the reader must live OUTSIDE the container body — a consumer
    #      reads the container from its own scope; a var inside the body
    #      (including the statement's own ⟐ output projection, whose
    #      attribution container's body IS its context) is not a reader of
    #      it, and wiring those would connect same-named sibling
    #      projections of one SELECT to each other;
    #   3. the container must not have wired the reader already — an
    #      existing edge from a var inside the container body into the
    #      reader IS the provenance this rule exists to add (Phase 3's
    #      evidence-scored resolution found it); adding a second one would
    #      only duplicate the path.
    #
    # The producer is the container's own projection of the same field name
    # (a var whose `defined_in` is the container's body prefix — the same
    # convention Phase 4b uses to wire a CTE to its inner variables), and
    # when several same-named containers project it the LAST one at or
    # before the reader's line wins: the registration order is script order,
    # so this is the D3 last-writer-wins convention, and it keeps the edge
    # deterministic instead of unioning same-named CTE bodies.
    _prov_producers: dict[str, list[VariableDefinition]] = defaultdict(list)
    for v in variables:
        if v.variable_type not in _SOURCE_COLUMN_TYPES:
            continue
        di = (v.defined_in or "").casefold()
        if di:
            _prov_producers[di].append(v)
    _prov_bodies: dict[str, set[str]] = defaultdict(set)
    for v in variables:
        if v.variable_type == VariableType.CTE:
            _prov_bodies[v.name.casefold()].add(f"CTE{{{v.name}}}".casefold())
        elif v.variable_type in (VariableType.SUBQUERY,
                                 VariableType.VIRTUAL_TABLE):
            # A subquery/⟐ container's body context IS its projections'
            # `defined_in` (_walk_select_expression sets defined_in =
            # context).
            _ctx = (v.context or "").casefold()
            if _ctx:
                _prov_bodies[v.name.casefold()].add(_ctx)
    # Existing wiring, for guards 3/3b: every edge already built, keyed once
    # by the edge's TARGET (what already feeds the reader) and once by its
    # SOURCE (what the reader already feeds).
    _prov_fed: dict[str, set[str]] = defaultdict(set)
    _prov_feeds: dict[str, set[str]] = defaultdict(set)
    for _d in deps:
        _prov_fed[_d.target_id].add(_d.source_id)
        _prov_feeds[_d.source_id].add(_d.target_id)
    for reader in variables:
        if reader.variable_type not in _SOURCE_COLUMN_TYPES:
            continue
        st = reader.source_tables or []
        if not st or not st[0]:
            continue
        bodies = _prov_bodies.get(st[0].casefold())
        if not bodies:
            continue  # not attributed to a container (physical table read)
        rctx = (reader.context or "").casefold()
        rdi = (reader.defined_in or "").casefold()
        if any(rctx == b or rctx.startswith(b + "/") or rdi == b
               for b in bodies):
            continue  # guard 2 — the reader lives inside the container
        if _prov_fed.get(reader.id, set()) & {
                p.id for body in bodies
                for p in _prov_producers.get(body, ())}:
            continue  # guard 3 — the container already feeds this reader
        part = reader.name.rsplit(".", 1)[-1].casefold()
        if not part:
            continue
        # X1 fix 1 (2026-08-31): the candidate list is built ONCE and put in
        # a TOTAL order before anything consumes it. `bodies` is a SET, so
        # the old `for body in bodies` walked it in hash-random order and
        # `producers[-1]` inherited that order — the picked producer, and
        # with it the served L2 edge id, flipped between processes (measured:
        # 7 distinct pick-sets on RFN across 8 PYTHONHASHSEEDs). Sorting by
        # (line, registration order) is process-independent AND is the D3
        # last-writer-wins the comment always claimed: latest line
        # at-or-before the read, script order breaking the tie.
        candidates = sorted(
            (p for body in bodies for p in _prov_producers.get(body, ())
             if p.id != reader.id
             and p.name.rsplit(".", 1)[-1].casefold() == part
             and (not p.line_start or not reader.line_start
                  or p.line_start <= reader.line_start)),
            key=lambda p: (p.line_start or 0, var_order[p.id]))
        if not candidates:
            continue
        # Guard 4 — ambiguity inside ONE body: when the container body holds
        # several same-named projections (the two-source CTE
        # `SELECT s1.dt, s2.dt AS dt2 …` shape), the handle read is ambiguous
        # and the rule wires nothing — the derived_single ambiguity test
        # restated at the container seam. Value evidence only bridges a value
        # the script names once per body; across bodies (a CTE name defined
        # twice) the deterministic script-order pick above is the D3
        # convention. Counted over the SAME sorted sequence the pick reads,
        # keyed by each candidate's own body (its `defined_in`, the very key
        # `_prov_producers` filed it under) — never over the re-walked set.
        per_body = Counter((p.defined_in or "").casefold()
                           for p in candidates)
        if any(c > 1 for c in per_body.values()):
            continue
        producer = candidates[-1]
        # X1 fix 2 (2026-08-31): guard 3b, the reverse direction. Guard 3
        # only saw edges INTO the reader, so an existing reader → producer
        # REF/TRANSFORM edge survived next to the new producer → reader
        # PROVENANCE edge — a 2-cycle on the same pair (14 corpus-wide). The
        # container's value already reaches the reader through that leg;
        # wiring the pair backwards adds nothing but the cycle.
        if producer.id in _prov_feeds.get(reader.id, set()):
            continue
        # Value direction (producer → reader), REF with the PROVENANCE
        # operation — a REFERENCE edge here would be walked BOTH ways by the
        # strict walker, and the backward half fans the container's column
        # out to every same-named var in the script (the same-name REFERENCE
        # web that floods the closure — measured 16 → 267 nodes on RFN
        # reserved_field9). The walker therefore rides a PROVENANCE edge the
        # way it rides a READ edge: from the consumer to the producer only
        # (plus the R44 reverse-read of the searched field itself), which is
        # the direction the value chain needs and the only one that keeps
        # the container's column from re-entering its own sibling reads.
        _add_edge(producer, reader, "REF", "PROVENANCE")

    # ══════════════════════════════════════════════════════════════════
    # Phase 4: SCHEMA — column belongs to table / CTE / VT
    # ══════════════════════════════════════════════════════════════════

    # Build table index
    table_index: dict[str, list[VariableDefinition]] = defaultdict(list)
    for v in variables:
        if v.variable_type in (VariableType.TABLE, VariableType.VIEW,
                               VariableType.CTE, VariableType.MERGE_TARGET,
                               VariableType.SUBQUERY,
                               VariableType.FUNCTION_TABLE):
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
                                        VariableType.MERGE_TARGET, VariableType.UNION_BRANCH,
                                        VariableType.FUNCTION_TABLE):
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
            if t.variable_type not in (VariableType.TABLE, VariableType.VIEW,
                                       VariableType.FUNCTION_TABLE):
                continue
            if (t.context or "TOP") != ctx:
                continue
            if match_t(t):
                _add_edge(v, t, "REF", "READ")
                break

    # Phase 4d-gb: GROUP BY occurrence twins → SCHEMA connectivity.
    # (#387, R44 family 3) `_register_groupby_twins` registers an
    # occurrence-side twin `{owner}.{col}` (defined_in="GROUP BY",
    # is_output=False, source_columns populated, source_tables=[owner]) so
    # group-key lines anchor. The GROUP BY family is the ONLY twin family
    # that populates source_columns — the R45 occurrence-line twins below
    # are minted with an EMPTY list (`_mint_occurrence_twin`). The twin's
    # qualifier is the PHYSICAL owner,
    # not the read alias, so Phase 4a skips it (the owner is the
    # original-name source) and Phase 4d's prefix match misses it — the
    # twin's data-flow REF/READ is emitted by Phase 8's bridge, but no
    # INCOMING SCHEMA edge reaches it, which trips the column_connectivity
    # topology check ("no connection from source table"). Give each twin
    # its structural belongs-to edge from the owner's same-context table
    # instance (the original name or a bare self-attributed read — the
    # twin's source_tables[0] names the physical owner either way).
    for v in variables:
        if v.variable_type != VariableType.COLUMN:
            continue
        # R45: also admit the occurrence-line twins — same owner/shape
        # ({owner}.{col}, not an output), same connectivity need, but NOT
        # the same source_columns: `_mint_occurrence_twin` mints them with
        # an EMPTY list (family-1 precedent), only the GROUP BY family
        # above populates it — which is why the admission gate below is
        # source_tables only. Their `defined_in` is the OCCURRENCE marker +
        # the collected clause, never "GROUP BY".
        if _clause_of(v.defined_in) != "GROUP BY" \
                and not (v.defined_in or "").strip().upper().startswith(
                    _OCCURRENCE_PREFIX):
            continue
        # R45: occurrence twins deliberately carry an EMPTY
        # source_columns (family-1 precedent — see
        # `_mint_occurrence_twin`), so the gate is source_tables only.
        if v.is_output or not v.source_tables:
            continue
        owner = v.source_tables[0]
        ctx = v.context or "TOP"
        for t in variables:
            if t.variable_type not in (VariableType.TABLE, VariableType.VIEW,
                                       VariableType.FUNCTION_TABLE):
                continue
            if (t.context or "TOP") != ctx:
                continue
            if t.name == owner and t.id != v.id:
                _add_edge(t, v, "SCHEMA", "TABLE_COLUMN")
                break

    # Phase 4d-gc: MERGE/predicate-clause columns of their PHYSICAL owner
    # (H11, 2026-08-31 — the 7 waived `column_connectivity` defects).
    # `_walk_merge` walks a MERGE's ON / UPDATE SET / WHEN clauses through
    # the merge scope, and `_walk_join` the ordinary JOIN ON, so a read of
    # the USING/derived alias (`source.amount`, `txn.merchant_id`) resolves
    # I2 to the alias's PHYSICAL table and the R44 family-2 twin registers
    # it under the owner-qualified spelling `{owner}.{col}`. Its qualifier is
    # the physical owner, so Pass 4a skips it (the owner is the original
    # name), Phase 4d's prefix match misses it, and Phase 4d-gb's gate
    # enumerates only `GROUP BY` + the OCCURRENCE marker — the MERGE/JOIN ON
    # clauses fell between the two, and the var carried no incoming
    # SCHEMA edge at all (topology `column_connectivity`: "no connection
    # from source table").
    #
    # Admission needs the model's own SCHEMA EVIDENCE that `owner` really has
    # `col`: a QUALIFIED read (`t.amount`) that I2 resolved to `owner` in the
    # same statement. That evidence is exactly what separates the 7 defects
    # from the adjudicated false positives of the same clause family —
    # fin_query4's `gps_transactions.account_id` is the twin of a RENAMED
    # USING projection (`t.source_account_id AS account_id`), so no
    # alias-spelled read of `gps_transactions.account_id` exists anywhere in
    # the statement and the belongs-to premise is false; admitting it would
    # fabricate a schema fact. The witness is owner-scoped and never
    # owner-spelled (an `{owner}.{col}` var's own spelling proves nothing —
    # it is the shape under adjudication), so the rule can never witness
    # itself.
    _owner_reads: set[tuple[str, str, str]] = set()
    for w in variables:
        if w.variable_type != VariableType.COLUMN or "." not in w.name:
            continue
        if not w.source_tables or not w.source_tables[0]:
            continue
        w_qual, _, w_field = w.name.partition(".")
        if w_qual.casefold() == w.source_tables[0].casefold():
            continue  # owner-spelled — not schema evidence (see above)
        _owner_reads.add((_statement_scope(w.context),
                          w.source_tables[0].casefold(), w_field.casefold()))

    for v in variables:
        if v.variable_type != VariableType.COLUMN:
            continue
        if v.is_output or not v.source_tables:
            continue
        if "." not in v.name:
            continue  # bare columns need no belongs-to edge
        if _clause_of(v.defined_in) not in _MERGE_COLUMN_CLAUSES:
            continue
        qualifier, _, field = v.name.partition(".")
        owner = v.source_tables[0]
        if not owner or qualifier.casefold() != owner.casefold():
            continue  # alias-spelled columns take Pass 4a's belongs-to edge
        if (_statement_scope(v.context), owner.casefold(),
                field.casefold()) not in _owner_reads:
            continue  # no schema evidence — a renamed projection, not a member
        # Nearest owner instance in the column's own statement (I3): a
        # physical/merge-target var of that name, at-or-before the column's
        # own line when one exists (max line wins), else the earliest;
        # physical tables preferred over a MERGE_TARGET spelling of the same
        # name. Never the column itself — it is a COLUMN.
        stmt = _statement_scope(v.context)
        cands = [t for t in variables
                 if t.variable_type in (VariableType.TABLE, VariableType.VIEW,
                                        VariableType.FUNCTION_TABLE,
                                        VariableType.MERGE_TARGET)
                 and t.name.casefold() == owner.casefold()
                 and _statement_scope(t.context) == stmt
                 and t.line_start >= 1]
        if not cands:
            continue
        before = [t for t in cands
                  if v.line_start < 1 or t.line_start <= v.line_start]
        pool = before or cands
        pool.sort(key=lambda t: (
            1 if t.variable_type == VariableType.MERGE_TARGET else 0,
            -t.line_start if before else t.line_start,
            var_order[t.id]))
        _add_edge(pool[0], v, "SCHEMA", "TABLE_COLUMN")

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
                                         VariableType.VIRTUAL_TABLE,
                                         VariableType.FUNCTION_TABLE):
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

    # R45/F-E1 (2026-08-28) — occurrence-twin group clauses. A family-3
    # twin is named `{owner}.{col}` and carries `defined_in` =
    # "OCCURRENCE <clause>", where <clause> is the clause the COLLAPSED
    # occurrence was collected in. `_add` records those collapses in WALK
    # order (a JOIN-key operand pass before the WHERE pass), while the
    # LINE each twin gets is handed out in TEXTUAL order
    # (`_occurrence_lines`) — so inside one twin group the two can be
    # crossed. SUP_M, CTE{rollover_loan_info}/subq1/subq:join:p2, field
    # podtao: twins at L37 (`AND podtao <> pofddt`) and L41
    # (`LPAD(p2.podtao, 8, '0')`); the L37 twin carries the join-key
    # collapse's "SELECT expr" and the L41 twin carries "WHERE". The
    # group's clause MULTISET is still a fact of the SQL — only the
    # per-line pairing is not — so a twin whose own label lost the
    # crossing keeps its group's predicate participation: the L37 line is
    # a genuine occurrence of the field in that scope and its
    # FILTER/SCHEMA edges are the only own-line edges it can carry (its
    # belongs-to SCHEMA and REF/READ edges anchor at / fold into the
    # owner-table pair). Grouping is per (context, casefolded
    # owner.field) — never a bare-name match, so a DIFFERENT table's
    # same-named field (DigL's two data_dt owners) can never lend its
    # clause.
    _twin_clause_by_group: dict[tuple[str, str], set] = defaultdict(set)
    for v in variables:
        di = (v.defined_in or "").strip().upper()
        if not di.startswith(_OCCURRENCE_PREFIX):
            continue
        if v.variable_type != VariableType.COLUMN or not v.source_tables:
            continue
        _twin_clause_by_group[
            (v.context or "TOP", v.name.casefold())
        ].add(di[len(_OCCURRENCE_PREFIX):].strip())

    def _twin_group_admits(v, clauses) -> bool:
        """True when `v` is an occurrence twin whose group collected one of
        `clauses`, but the twin's OWN label is a different one (the honest
        twins keep their own typing — Phase 6/6b already cover them)."""
        di = (v.defined_in or "").strip().upper()
        if not di.startswith(_OCCURRENCE_PREFIX):
            return False
        if _clause_of(di) in clauses:
            return False
        return bool(_twin_clause_by_group.get(
            (v.context or "TOP", v.name.casefold()), set()) & clauses)

    for v in variables:
        if v.variable_type != VariableType.COLUMN:
            continue
        if v.is_output:
            continue
        if "." not in v.name:
            continue
        # Only columns from filter clauses
        if _clause_of(v.defined_in) not in _FILTER_CLAUSES \
                and not _twin_group_admits(v, _FILTER_CLAUSES):
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
        if _clause_of(v.defined_in) not in _JOIN_CLAUSES \
                and not _twin_group_admits(v, _JOIN_CLAUSES):
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
        if _clause_of(v.defined_in) != "JOIN ON":
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
                         if v.variable_type in (VariableType.TABLE,
                                                VariableType.FUNCTION_TABLE)), comp[0])
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

    skip_if_connected = {VariableType.TABLE, VariableType.VIEW,
                         VariableType.FUNCTION_TABLE}

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
        di = _clause_of(v.defined_in)
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
        if v.variable_type in (VariableType.TABLE, VariableType.VIEW,
                               VariableType.FUNCTION_TABLE):
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

    # ══════════════════════════════════════════════════════════════════
    # Phase 9: R46d — the continuation arm's OWN flow edge
    # ══════════════════════════════════════════════════════════════════
    # An occurrence twin minted at the right line still carried no flow
    # edge of its own: its belongs-to SCHEMA edge (4d-gb) is structure and
    # folds in L2's line-merged pass onto the FIRST occurrence's carrier,
    # so a CASE's 2nd..Nth WHEN arm, a nested function body's operand and
    # a JOIN ON's AND-continuation leg lit only through the head's folded
    # duplicate — or not at all. The arm stamp the extractor now carries
    # (`OCCURRENCE CASE WHEN` / `CASE THEN` / `CASE ELSE`) is the
    # per-occurrence fact the clause machinery could never express (a CASE
    # arm never leaves its clause, so every arm read as "SELECT expr"),
    # and it is what tells a ROW-SELECTION from a value operand:
    #
    #   CASE WHEN  → FILTER/ROW_SELECTION into the scope's output anchor —
    #                the condition selects the rows that flow, it is not a
    #                value source (AD3's ruling).
    #   CASE THEN/ → REF/VALUE into the same anchor — the operand's value
    #   CASE ELSE    IS projected into the statement's output.
    #
    # Admission is per-occurrence, never a group borrow: F-E1's
    # `_twin_group_admits` stays untouched (Phase 6), and a twin whose OWN
    # stamp is not an arm keeps exactly the edges it had. The guard is
    # "no OUTGOING flow edge yet": the belongs-to SCHEMA edge (4d-gb) and
    # the incoming write leg the family-1 machinery routes to the twin say
    # "belongs" / "written", never "this occurrence selects the row" or
    # "this occurrence feeds the output". An outgoing REF/READ (field →
    # its holder) is the structural read the walker already treats as
    # field → table, so it does not count either. This phase only
    # de-silo's the twins with no edge that says what their arm does.
    # Appended LAST, so the L2 line-merged pass's first-carrier-wins can
    # never displace an existing carrier with one of these.
    _OWN_FLOW_TYPES = {"FILTER", "JOIN", "REF", "COMPUTED", "TRANSFORM",
                       "AGGREGATE", "WINDOW", "INDIRECT"}
    twin_arms = getattr(result, "occurrence_arms", None) or {}
    for v in variables:
        arm = twin_arms.get(v.id)
        if arm not in ("CASE WHEN", "CASE THEN", "CASE ELSE"):
            continue  # JOIN ON legs are Phase 6b's own-clause case
        if v.variable_type != VariableType.COLUMN or v.is_output:
            continue
        if not v.source_tables:
            continue
        if any(d.source_id == v.id and d.relationship in _OWN_FLOW_TYPES
               and (d.operation or "").upper() != "READ"
               for d in deps):
            continue  # already carries its own flow story
        ctx = v.context or "TOP"
        anchors = vt_map.get(ctx) or []
        if not anchors:
            continue
        if arm != "CASE WHEN":
            # CASE THEN / CASE ELSE — WITHHELD (measured, E7): the value
            # leg would have to target the scope's ⟐ output anchor, and
            # REF is walked backwards by the strict walker, so every
            # sibling arm's twin became an upstream producer of EVERY seed
            # reached through that anchor — jaccard precision
            # bdm/Digitallending-upstream 1.0 -> 0.4286, east5-upstream
            # 1.0 -> 0.2308 (4 of the 20 gate cases). The honest target is
            # the CONSUMING OUTPUT COLUMN (`occ -> stzfdxhm`, not
            # `occ -> ⟐ output`), which needs the CASE → output-alias
            # pick: the surviving read carries one COMPUTED edge per CASE
            # it feeds (`a.TAG_PRIMARY_ACCOUNTABLE_PARTY`@71 feeds five),
            # and choosing among them needs the CASE → output-alias
            # resolution that does not exist yet (the same structured
            # field-hop gap the R40.12-A audit ledgered). The arm IS
            # recorded on `result.occurrence_arms`, so landing the target
            # rule is a Phase-9-local change — no extraction re-round.
            continue
        _add_edge(v, anchors[0], "FILTER", "ROW_SELECTION")
    # ── Phase 9b (2026-08-28.14): rule 4e — PRODUCER-OCCURRENCE ANCHORING ──
    # A COMPUTED edge that carries a producer column's value INTO a CASE
    # output column anchors where Phase 3's source pick put it: the
    # collapsed group's KEEPER, i.e. the producer's FIRST occurrence in the
    # statement — which for a CASE-arm operand is another statement's line
    # altogether (EAST5 × BBZ, measured on 2026-08-28.13: the
    # `a.charge_department` edge anchored L51, the stzfdxzh CASE's own WHEN
    # line, and the `A.ccy_code` edge anchored L47, the SIBLING column bz's
    # birth line — while the CASE producing BBZ is L70-73 and its arms read
    # both fields there). The value the edge carries is produced at the arm
    # line, and the arm line is where the reader looks.
    #
    #   RULE 4e: an edge carrying the searched field's value from a
    #   producer column anchors at the producer occurrence INSIDE the
    #   searched field's own expression (the arm line), never at another
    #   statement line where the same producer occurs (the collapsed
    #   group's keeper first-occurrence line).
    #
    # Resolution is the AS-alias mapping at the END line (`END AS BBZ`):
    # a CASE output var anchors at its alias line, and the span that alias's
    # END closes is the producing expression's own lines — the same span
    # read the extractor's family 5 mints twins on
    # (`_register_case_producer_twins`). The move is a RE-ANCHOR, never a
    # new edge: Phase 3's edge is re-pointed onto the in-span occurrence
    # twin of the same (owner, field), so the served set keeps exactly one
    # producer leg per producer and only its anchor changes. A producer
    # already anchored inside the span stays exactly where it is (`a.remark`
    # @70, `B.ccy_code` @71), a producer with no in-span occurrence keeps
    # the keeper anchor (never a guess), and an empty `sql_text` (graph
    # built from a pre-extracted result) keeps every anchor as it was.
    #
    # ORDER — appended AFTER the Phase-9 arm pass, and the two rules are
    # deliberately allowed to tell an occurrence twin TWO true stories: the
    # arm pass's `FILTER/ROW_SELECTION` into the scope's anchor (this
    # occurrence's condition selects the rows that flow) and rule 4e's
    # `COMPUTED` into the CASE output whose expression reads it (this
    # occurrence produces the value that flows). Running this pass FIRST and
    # leaning on the arm pass's "no OUTGOING flow edge yet" guard would keep
    # one story per twin — but it would SILENCE the arm row-selection of
    # every twin a producer leg lands on (three R46d pins red, the doc's
    # §4a arm rows unlit), so the arm story stays and the corpus pin
    # `test_no_second_story_for_a_twin_with_its_own_flow` reads one story
    # WIDER now: Phase 9 itself still never adds a second one.
    case_spans = _case_alias_spans(sql_text) if sql_text else {}
    if case_spans:
        _drop: list[int] = []                  # python id() of edges to drop
        for tgt in variables:
            if tgt.variable_type != VariableType.CASE or not tgt.line_start:
                continue
            span_lo = case_spans.get((tgt.line_start, tgt.name.casefold()))
            if not span_lo:
                continue
            # Group the movable edges by (in-span occurrence, relationship).
            # Phase 3 walks `source_columns` — a SET — so for a producer the
            # statement spells through two alias spellings (`a.x` and `A.X`,
            # two distinct vars) it emits TWO edges into the same CASE output
            # in hash order. Re-pointing whichever arrives first and blocking
            # on the second would make the served set a function of
            # PYTHONHASHSEED (measured, EAST5's charge_department →
            # stzfdxhm): seed 0 kept `a.CHARGE_DEPARTMENT`@51, seeds 1-3 kept
            # `a.charge_department`@51. Rule 4e leaves nothing at the keeper
            # line anyway, so the group is folded: ONE edge is re-pointed
            # onto the occurrence, the rest — the same producer value flow
            # duplicated through another spelling — are dropped. Which
            # member arrives first then changes nothing: the surviving edge
            # is the occurrence's, and no keeper-anchored one remains.
            groups: dict[tuple[str, str], list] = {}
            for d in deps:
                if d.target_id != tgt.id or d.relationship != "COMPUTED":
                    continue
                src = id_index.get(d.source_id)
                if src is None or src.variable_type != VariableType.COLUMN:
                    continue
                src_line = int(src.line_start or 0)
                if not src_line or span_lo <= src_line <= tgt.line_start:
                    continue  # already anchored inside the expression it feeds
                repl = _producer_occurrence_in_span(
                    variables, src, span_lo, tgt.line_start)
                if repl is not None:
                    groups.setdefault((repl.id, d.relationship),
                                      []).append((d, src, repl))
            for (repl_id, rel), members in groups.items():
                ek_new = (repl_id, tgt.id, rel)
                if ek_new in seen_edges:
                    # the occurrence already carries this edge — every member
                    # is a keeper-anchored duplicate of it.
                    for d, src, _r in members:
                        seen_edges.discard((src.id, tgt.id, rel))
                        _drop.append(id(d))
                    continue
                seen_edges.add(ek_new)
                d0, src0, repl = members[0]
                for d, src, _r in members[1:]:
                    seen_edges.discard((src.id, tgt.id, rel))
                    _drop.append(id(d))
                seen_edges.discard((src0.id, tgt.id, rel))
                d0.source_id = repl_id
                d0.sql_context = f"{repl.name} → {tgt.name}"
        if _drop:
            deps[:] = [d for d in deps if id(d) not in set(_drop)]


    # ── V8 walker determinism: the CANONICAL DEPENDENCY ORDER ──
    # The emitted list is a SET function of the SQL text but never was an
    # ORDER function of it: the per-variable source columns are
    # materialized through `list(set(...))`
    # (variable_extractor_v2._extract_source_columns), so the order the
    # edges arrive in is PYTHONHASHSEED-dependent. The order was
    # load-bearing (l2_builder's first-wins dedup and the closure walk's
    # admission decisions both take the first candidate), so a server
    # process served differently CHOSEN graphs across restarts.
    #
    # Two halves land together (either alone changes the served sets):
    #   1. THIS sort — the list becomes a pure function of the SQL text.
    #   2. lineage.compute_field_flow's canonical expansion precedence —
    #      the walker stops taking "the first edge in list order" as a
    #      decision (see lineage._WALK_RANK).
    # Keys are content only: the two endpoints' registration order (the
    # extractor's own counter, stable across processes) then the edge's
    # own fields. Never a repr, never a hash, never a set/dict order.
    deps.sort(key=lambda d: (var_order.get(d.source_id, 0),
                             var_order.get(d.target_id, 0),
                             d.relationship,
                             d.operation or "",
                             d.sql_context or "",
                             bool(d.containment)))

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
