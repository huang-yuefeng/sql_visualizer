"""
Variable Extractor v2 — Role-Based Identifier Extraction
=========================================================

Instead of checking for every possible SQL syntax structure (CASE, COALESCE,
Window, Subquery, etc.), this extractor walks the AST and classifies EVERY
Identifier node based on its **structural role** in the AST tree.

Principle: In SQL, every meaningful name is an Identifier AST node.
Its role is determined by its *parent* node type:

    Identifier inside Column     → TABLE_COLUMN
    Identifier inside Table      → DATABASE_TABLE
    Identifier inside TableAlias → DATABASE_TABLE (alias)
    Identifier inside Alias      → depends on the aliased expression type

This approach automatically handles ANY SQL construct that sqlglot can parse
— no new code needed when new SQL features are encountered.
"""

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

import sqlglot
from sqlglot import exp
from sqlglot.tokens import TokenType

from app.models.variable import VariableDefinition, VariableType


# Bump to invalidate analysis caches when extraction semantics change.
# 2026-08-11.3: dependency-graph source-resolution change (D3, round dl) —
# analysis caches store the dependency list, so engine-level semantics
# changes ride the same version gate.
# 2026-08-25.1: ISSUE-4 — case-insensitive physical-table identity via
# frequency-voted canonical spelling + scope-aware alias/CTE/derived
# registries (script-global case-fold applies to physical table names only).
# 2026-08-25.2: code-review fixes — M-E2 (`_scope_top` no longer collapses
# VIEW:{name}/CTAS:{name} into one bucket), M-E3 (`_canonicalize_table_names`
# skips CTE/derived source_tables entries), M-E4 (`_ident_votes` counts only
# VAR/IDENTIFIER tokens, not keywords).
# 2026-08-25.3: code-review R-1 — `_canonicalize_table_names` step 1 skips
# alias handles (new `is_alias_handle` flag on all three alias paths: the
# FROM/JOIN alias, the synthetic LATERAL/VALUES/UNNEST alias, and the
# INSERT-target alias) so an alias whose spelling case-collides with a
# physical table keeps its own scope-local case instead of folding to the
# physical majority spelling (which would merge the alias node into the
# physical source_table node in L2).
# 2026-08-28.4 (#387 + the #386 CTE-scope ruling, on top of R44's
# 2026-08-28.3): four semantic changes —
#   1. GROUP BY occurrence twins (`_register_groupby_twins`, R44 family
#      3): every GROUP BY item column with a resolved physical owner
#      registers an occurrence-side twin `{owner}.{col}` (source_columns
#      populated, NOT is_output, line = the item's own line via the
#      clause-keyword token run) — PL L246/247 style group-key lines now
#      anchor; the twin's REF/READ edge comes from the existing
#      dependency_graph Phase-8 bridge, and the newly-added Phase 4d-gb
#      emits the SCHEMA/TABLE_COLUMN connectivity edge (anchored at the
#      twin's line).
#   2. WINDOW edge anchors move to the window application's own line
#      (highlight_strategies `_anchor_line` — the OVER clause rides the
#      window var, the edge's target), so window-key lines are reachable
#      in flow-only closures.
#   3. l2_builder #387 follow-up: when the SEARCH targets the write
#      table, a derived-alias write-projection attributed to a real read
#      source re-parents (or re-points onto the write table's existing
#      same-named field) on the write target — display projection only,
#      extraction untouched.
#   4. #386 CTE-scope ruling (SQL-standard scoping): `_add`'s CTE-merge
#      is scope-aware (`_is_cte_name`) — a LATER statement's bare ref to
#      a CTE's name registers a PHYSICAL table read instead of being
#      swallowed by the any-context CTE merge; in-scope refs keep
#      folding. The model's owner resolution still matches by the SHARED
#      `name` string (`_name_to_key` — a CTE and a same-named physical
#      table collide there), so l2_builder disambiguates via `_stmt_root`
#      (the in-scope CTE compound) and `field_owner_key` (the field's
#      occurrence-owner entity) — the out-of-scope read's columns land on
#      the physical compound, never the cte_table node.
# 2026-08-28.5 (deferred-findings M1/M3, two more semantic changes):
#   5. WRITE-SIDE twins admit `VariableType.LITERAL` — a constant
#      projection (`1 AS flag`, `'x' AS col`) now materializes its
#      `{target}.{col}` twin exactly like `NULL AS x` (EXPRESSION)
#      already does, so literal write columns get a physical field entity.
#   6. Bare-INSERT merge (`_walk_insert`'s merged_select path) also
#      merges a following `exp.Union`/`exp.Intersect`/`exp.Except` — a
#      `SELECT … UNION ALL SELECT …` write source parses as a set-op, and
#      without the merge those write legs stayed severed.
# 2026-08-28.6 (R45 — residual occurrence coverage, F-C): one semantic
# change on top of R44's families 1/2, fixing field occurrences that stayed
# OUTSIDE the served closure while a sibling occurrence of the same field
# was already in it —
#   7. Family 3, occurrence-line twins (`_collapsed_occurrences` +
#      `_register_flow_occurrence_twins` family 3): `_add`'s (name, type,
#      context) dedup keeps ONE node per field per scope, so the 2nd..Nth
#      occurrence of that field inside the same statement left NO node at
#      all at its own line. Concrete shapes: a CASE's 2nd WHEN arm (RFN
#      L439 after L438), an NVL fallback operand (RFN L1029/L1314), a
#      byte-identical `TO_CHAR(TO_DATE(...)) AS X` projection (RFN L525
#      after L523 — the spec's class-5 anchor collision), the second leg of
#      a multi-line JOIN ON predicate whose expression side repeats the
#      first leg's key expression (PL L250 after L27), and an ELSE arm
#      (EAST5 L52 after L51). `_add` now records each collapsed
#      COLUMN/EXPRESSION occurrence; family 3 groups them per
#      (context, casefolded field name), hands out the group's remaining
#      textual occurrences in stream order (surviving vars keep the first),
#      and re-anchors each as an occurrence-side twin attributed to the
#      SAME owner the surviving var resolved to — never a guessed owner,
#      never a moved anchor (purely additive: no existing var's line
#      changes).
# 2026-08-28.7 (K4 ruling 3 — FIX-DEFECT, diagnostics only): the structural
#   paren-balance check (`_paren_balance_errors`) runs one tokenizer pass
#   over the ORIGINAL script and reports statements that still have '(' open
#   at their end. No extraction semantics change — no node, line or edge
#   moves; the ONLY output difference is `parse_errors` entries for scripts
#   that ErrorLevel.IGNORE silently recovered into a partial tree. Bumped so
#   analysis/graph caches written by 2026-08-28.6 (parse_errors: []) are
#   invalidated and re-stamped. GRAPH_CACHE_PREFIX bumps with it.
# 2026-08-28.8 (F-E2 — occurrence-twin owner/scope/clause correctness, K3):
#   8. Fix D — `_base_var_for` matches the group's FULL casefolded identity
#      first (qualifier included), falling back to the last dot-part only
#      when no surviving var carries that spelling (I2's owner-qualified
#      rewrite). Field-part-only matching made every same-field group in a
#      scope inherit the FIRST surviving var's owner: SUP_M's dynamic
#      PARTITION column CHARGE_DEPARTMENT@160 (bdm_acc_loan_info_sup)
#      preceded the projections, so both `p1.charge_department` occurrences
#      (@182/@196, p1 = loan_final) minted write-target-owned twins.
#   9. Fix C — the occurrence-line search is bounded by the group's OWN
#      paren scope (`_paren_scope_bound`, a token-depth profile) and never
#      claims a line a nested recorded scope owns (`_scope_line_owner`): a
#      subquery body's range no longer runs past its `)` into the enclosing
#      statement's continuation (SUP_M: the NOT-IN body closing @58 no
#      longer claims the enclosing `GROUP BY lending_ref` @59, which is
#      bdm_acc_loan_info's occurrence — the bdm_evt_loan_trans twin there
#      is gone).
#  10. Fix E/F/G — the occurrence→line handout pairs a collapsed occurrence
#      with a line of ITS OWN clause (`_line_clauses` + `_occurrence_clause`,
#      token-type aware), `taken` is spelling-insensitive and computed once
#      (a line any same-field var anchors is not free), and a bare identity
#      only matches BARE token occurrences (`p1.lending_ref` is another
#      group's occurrence). Together these stop a group's DUPLICATE
#      registration of an already-anchored occurrence from stealing the free
#      line a genuine occurrence needed (RFN: the `p_dt <= TO_DATE(…)`
#      predicate @831 is the twin's line; the MWF phantom twins are gone —
#      8 SQL-true twins, not 10).
#  11. K3 — a COLUMN/CTE_COLUMN whose NAME contains `,`/`(`/`)`/space is an
#      expression FRAGMENT (the unrepaired RFN's `lending_ref, 4, 5)`): the
#      var is kept (line/expression/edges are real) but stamped as an
#      auto-named output, so no write-side twin or owner-qualified
#      re-derivation ever mints a physical field from it. The structural
#      paren check (.7) reports the script; this boundary keeps the
#      recovered partial tree from being taken for field identities.
#  12. l2_builder Fix H (same version, no prefix bump): when one display
#      field folds several occurrences' edges, the carrier that names the
#      keeper chip's OWN line wins the folded edge — a CTE-internal
#      derivation's birth line (RFN `SUBSTR(P1.BRANCH_CODE,-3) AS
#      tag_branch` @721) is no longer anchored away by a later occurrence's
#      carrier (@1030), so the line is lit again (Item 2a; L364/L687 hold).
# 2026-08-28.9 (post-v3.3.191 adjudicated batch, fix team G1) — five fixes:
#   Fix A (HIGH, two stages that must land together) —
#     A1. lineage R44 derived-product round: a holder that is itself a
#         DERIVED CONTAINER (subquery | virtual_table) now qualifies only
#         when its physical identity IS the searched table, or when it is a
#         derived product of exactly one physical table and that table is
#         the searched one (`_holder_is_derived_single` — the extractor's
#         own derived_single rule mirrored on occurrences, EXISTS bodies
#         excluded, memoized). ADAPTED from the adjudicated spec, which
#         gated every holder kind: a physical/CTE holder keeps the
#         scope-presence rule, because the canonical closures depend on it
#         structurally — SUP_M's ods_hub_lsacmsp.lending_ref seeds ZERO
#         PhysicalField occurrences, the round's admissions are that
#         closure's only entry point, and every one of them hangs off a
#         plain physical-table holder (gating them: closure 21 -> 0 nodes,
#         jaccard lending_ref/SUP_M/downstream nodes precision 0.8491).
#         See the round comment and tests/test_g1_adjudicated_fixes.py.
#     A2. WITHHELD (dependency_graph Phase 3 provenance edge container
#         output column → same-named reader column): the edge is
#         semantically right and lights RFN's REPAY_ACCT_NO@364, but it
#         re-routes SUP_M's fold carriers and grows the
#         ods_hub_lsacmsp.lending_ref closure past its canonical set
#         (jaccard lending_ref/SUP_M/downstream edges recall 0.7905). It is
#         deferred to the SCHEMA-fold design item, together with a rule that
#         says whether a display-provenance edge may join the flow walk.
#   Fix B — occurrence twins stamp the CLAUSE OF THEIR OWN LINE
#     (`_LINE_CLAUSE_TO_DEFINED_IN` re-spells the raw line clause into the
#     walker's `defined_in` spelling: raw `on` → `JOIN ON`, which Phase
#     6/6b's `{"JOIN ON"}` gate is the only thing that reads). The collapsed
#     occurrence's clause was a GROUP fact (walk order) while the line
#     handout is textual — the two could be crossed. `_twin_group_admits`
#     stays (53 twins still take their only predicate edge through it).
#   Fix D — `_scope_line_owner` tie-breaks overlapping ranges by real
#     ANCESTRY (a context that contains the other is the outer one), not by
#     context-string length. Part 2 WITHHELD: reading `_paren_scope_bound`'s
#     depth at the context's own anchor TOKEN (the same-line nested body
#     bound) moves the occurrence twins corpus-wide and takes the canonical
#     SUP_M lending_ref closure past its set — deferred with A2.
#   Fix E — MERGE phantom writes: `dml_targets_by_ctx` skips ALIAS
#     occurrences (an alias handle is not a write target), and a MERGE
#     context mints `{target}.{col}` write-twins only for the columns its
#     WHEN clauses actually write (WHEN MATCHED UPDATE SET left-hand
#     targets + WHEN NOT MATCHED INSERT column list). INSERT/UPDATE/DELETE
#     keep the projection-list behavior.
#   Fix F — paren-balance diagnostics report SCRIPT lines: `_preprocess_sql`
#     returns `(clean_sql, kept_lines)` and `_paren_balance_errors`
#     tokenizes the PARSED text (so the split index IS the statement index)
#     and translates the reported line back through `kept_lines` — a
#     dropped SET line no longer shifts both the statement index and the
#     reported line.
EXTRACTOR_VERSION = "2026-08-28.9"


# ── Orphan resolution (R20) constants ─────────────────────────────────

# S5: sentinel attribution for columns resolved to a system schema
# (INFORMATION_SCHEMA / mysql / pg_catalog / sys). No real table node
# carries this name — it is a marker for the stats report only.
SYSTEM_TABLE_SENTINEL = "⟐system"
OTHER_SENTINEL = "⟐pseudo"  # E4: S6-marked vars (pseudocolumns/trigger idioms)
# Task B (audit: unregistered table-like constructs): the synthetic base
# tables behind VALUES / UNNEST aliases. ⟐-prefixed like the other
# synthetic container names ("⟐ output", "⟐ insert"); the alias var
# carries source_tables=[synthetic] so dependency_graph Phase 1a emits
# the read edge (gated on source_tables non-empty). No node is ever
# created for these names — they are markers, exactly like
# SYSTEM_TABLE_SENTINEL.
VALUES_TABLE_NAME = "⟐ values"
UNNEST_TABLE_NAME = "⟐ unnest"

# S5: schema names that make a resolved table a "system table".
_SYSTEM_SCHEMAS = {"information_schema", "mysql", "pg_catalog", "sys"}

# S6: known pseudocolumn / trigger variable names (case-insensitive).
# LEVEL (Oracle CONNECT BY), ROWNUM, trigger vars new/old.
_PSEUDOCOLUMN_NAMES = {"level", "rownum", "new", "old"}

# UPDATE/MERGE SET assignments parse as exp.EQ in sqlglot 30.x; older
# releases used exp.UpdateSet / exp.SetItem. Version-robust tuple for
# S4a source-2 (SET column list) evidence.
_UPDATE_SET_NODES = tuple(
    c for c in (exp.EQ, getattr(exp, "UpdateSet", None), getattr(exp, "SetItem", None))
    if c is not None)


def default_resolution_stats() -> dict:
    """Fresh resolution_stats shape (R20) — also the ExtractionResult default.

    S4a (Phase 2 — auto-resolution) additions:
      schema_candidates — STILL-UNRESOLVED bare columns in ≥2-table scopes,
        each {field, visible_tables, loc, contexts}. Candidates with a unique
        visible owner are AUTO-ATTRIBUTED (source_tables = [owner],
        resolved_by["schema"] += 1) and REMOVED — the list contains ONLY
        residuals (S4b index-side re-test input; never-guess invariant).
      r6_collision — count of candidates whose field equals a visible table
        name (R6 guard — never attributed).
      script_schemas — per-script canonical table → {column: evidence_line}
        (dict-of-dicts; the line is where the schema EVIDENCE occurred —
        qualified-ref / DML-list / DDL statement line; first occurrence wins).
      C4a (R20 contract unification): `resolved`, `unresolved_count` and
        `coverage_pct` are emitted ADDITIVELY alongside the legacy keys —
        old caches and defensive readers keep working, and new analyses
        carry the index-aggregate shapes without a frontend shim.
    """
    return {
        "total_columns": 0,
        "resolved_by": {"plain_alias": 0, "expr_alias": 0, "scope": 0,
                        "schema": 0, "sys": 0, "other": 0},
        "unresolved": [],
        "resolved": 0,              # C4a: total_columns − len(unresolved)
        "unresolved_count": 0,      # C4a: len(unresolved)
        "coverage_pct": None,       # C4a: one-decimal coverage; None @ 0 columns
        "schema_candidates": [],
        "r6_collision": 0,
        "script_schemas": {},
    }


# ── Aggregate / Window function name sets ───────────────────────────────

_AGGREGATE_NAMES = {
    "sum", "count", "avg", "min", "max", "group_concat",
    "stddev", "variance", "stddev_pop", "stddev_samp",
    "var_pop", "var_samp", "bit_and", "bit_or", "bit_xor",
}

_WINDOW_ONLY_NAMES = {
    "row_number", "rownumber", "rank", "dense_rank", "denserank",
    "percent_rank", "percentrank", "cume_dist", "cumedist",
    "ntile", "lag", "lead", "first_value", "firstvalue",
    "last_value", "lastvalue", "nth_value", "nthvalue",
}

_KNOWN_FUNCTIONS = {
    "coalesce", "cast", "concat", "json_extract", "if", "nullif",
    "greatest", "least", "date_add", "date_sub", "datediff",
    "timestampdiff", "period_diff", "date_trunc", "date_format",
    "extract", "abs", "round", "ceil", "floor", "substring_index",
    "st_x", "st_y",
}


# ── Helpers ─────────────────────────────────────────────────────────────

def _make_id(script_name: str, name: str, suffix: int = 0) -> str:
    base = f"{script_name}:{name}"
    if suffix:
        base = f"{base}_{suffix}"
    return hashlib.md5(base.encode()).hexdigest()[:16]


def _clean(name: str) -> str:
    """Strip quotes and backticks."""
    name = (name or "").strip()
    if len(name) >= 2 and name[0] in ('"', "'", '`') and name[0] == name[-1]:
        name = name[1:-1]
    return name


def _sql(expr) -> str:
    """Safe SQL rendering with pretty-print for readability."""
    if expr is None:
        return ""
    try:
        return expr.sql(dialect="mysql", pretty=True)
    except Exception:
        # benign: display-only render — a failure yields "" and every
        # caller already tolerates an empty SQL string.
        return ""


def _func_name(expr: exp.Expression) -> str:
    """Get the canonical function name from an expression node."""
    if isinstance(expr, exp.Anonymous):
        return (expr.name or "").lower()
    try:
        return (expr.sql_name() or "").lower()
    except Exception:
        # benign: classification helper — "" just falls through as an
        # unknown function name (no crash, no misclassification).
        return ""


# ── Classification: what is being aliased? ─────────────────────────────

def _classify_aliased_expression(aliased_expr: exp.Expression) -> VariableType:
    """Given the expression inside an Alias node, return its VariableType.

    This replaces the old _classify_select_expression — instead of checking
    for every possible expression subclass, we look at the structural
    properties of the expression AST node.
    """
    # Window functions
    if isinstance(aliased_expr, exp.Window):
        return VariableType.WINDOW

    # Check for window inside (e.g. SUM(...) OVER (...))
    has_window = any(isinstance(n, exp.Window) for n in aliased_expr.walk() if n is not aliased_expr)
    if has_window:
        return VariableType.WINDOW

    # Subquery
    if isinstance(aliased_expr, exp.Subquery):
        return VariableType.SUBQUERY

    # Aggregate functions (Sum, Count, Avg, Min, Max, AggFunc)
    if isinstance(aliased_expr, exp.AggFunc):
        return VariableType.AGGREGATE
    if isinstance(aliased_expr, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)):
        return VariableType.AGGREGATE

    # CASE expression
    if isinstance(aliased_expr, exp.Case):
        return VariableType.CASE

    # Check if it's an aggregate by sql_name
    fname = _func_name(aliased_expr)
    if fname in _AGGREGATE_NAMES:
        return VariableType.AGGREGATE
    if fname in _WINDOW_ONLY_NAMES:
        return VariableType.WINDOW

    # Known transformation functions
    if fname in _KNOWN_FUNCTIONS:
        return VariableType.TRANSFORM
    if isinstance(aliased_expr, (exp.Coalesce, exp.Cast, exp.Concat, exp.JSONExtract,
                                  exp.If, exp.Nullif, exp.Greatest, exp.Least,
                                  exp.DateAdd, exp.DateSub, exp.DateDiff)):
        return VariableType.TRANSFORM

    # Generic function (Func subclass but not a known aggregate)
    if isinstance(aliased_expr, exp.Func) and not isinstance(aliased_expr, exp.Column):
        return VariableType.TRANSFORM

    # Literal
    if isinstance(aliased_expr, exp.Literal):
        return VariableType.LITERAL

    # Bare column reference
    if isinstance(aliased_expr, exp.Column):
        return VariableType.COLUMN

    # Default: computed expression
    return VariableType.EXPRESSION


# ── Source column extraction ────────────────────────────────────────────

def _extract_source_columns(expr: exp.Expression) -> list[str]:
    """Walk an expression tree and extract all table.column references.

    Walks INTO subqueries to find their column references (e.g., scalar
    subquery in SELECT depends on columns inside the subquery).
    Only CTEs are pruned (their columns belong to a different scope).
    """
    cols = []
    if expr is None or not hasattr(expr, 'walk'):
        return cols
    try:
        for node in expr.walk(prune=lambda n: isinstance(n, (exp.CTE,))):
            if isinstance(node, exp.Column):
                table = _clean(node.table or "")
                col_name = _clean(node.name or "")
                if table:
                    cols.append(f"{table}.{col_name}")
                elif col_name:
                    cols.append(col_name)
    except Exception:
        # benign: best-effort walk — a partial column list only degrades
        # edge granularity, never crashes extraction.
        pass
    return list(set(cols))


def _extract_table_names(expr: exp.Expression) -> list[str]:
    """Walk an expression tree and extract all table references."""
    tables = set()
    if expr is None or not hasattr(expr, 'walk'):
        return []
    for node in expr.walk():
        if isinstance(node, exp.Table):
            name = _clean(node.name or "")
            if name:
                tables.add(name)
    return list(tables)


def _majority_spelling(votes: Counter) -> str:
    """Most-frequent spelling from a Counter; ties prefer lowercase, then
    first-seen (insertion order). ISSUE-4 canonical-name rule."""
    best = None
    best_count = -1
    for spelling, count in votes.items():
        if best is None or count > best_count:
            best = spelling
            best_count = count
        elif count == best_count and spelling.islower() and not best.islower():
            best = spelling
    return best


# ── M2 (2026-08-28): context-path scope algebra ─────────────────────────
# Contexts are PATHS whose segments are separated by "/", ":" or "\". Most
# segments are real scope levels (TOP0, subq1, union0, CTE{x}, exists2);
# two are DECORATIVE MARKERS that name the FROM/JOIN slot, not a scope:
# `/subq/<alias>` (FROM-position derived table, _walk_from) and
# `:join:<alias>` (JOIN-position derived table, _walk_join). Both bind their
# alias in the scope the FROM/JOIN clause belongs to — one level up, behind
# the marker. (`join_subq` is the alias-less JOIN slot: it never carries an
# alias, so no sub var is ever looked up by that name.)
_SCOPE_SLOT_MARKERS = {"subq", "join"}


def _ctx_segments(context: str) -> list[str]:
    return [s for s in re.split(r"[/\\:]", context) if s]


def _binding_scope(context: str, alias: str) -> str:
    """The scope a derived/CTE alias is bound in, given the sub var's own
    context path and its name.

    `TOP0/subq/p2` and `TOP0:join:p2` both bind `p2` in `TOP0` — the alias
    segment and its slot marker are display path decoration, not scope.
    A sub var registered directly under the binding scope (`TOP0` for a
    FROM-position derived table at statement level, `CTE{x}` for a CTE
    reference inside a CTE body) has nothing to strip. Only the trailing
    alias and its own slot marker are removed — a scope level that merely
    HAPPENS to be named `subq` (`TOP0/subq1/subq:join:p2`) is never
    crossed, so a CTE body's / nested body's alias stays inside its own
    scope and never resolves against a same-named statement-level alias.
    """
    segs = _ctx_segments(context)
    if segs and segs[-1].casefold() == alias.casefold():
        segs = segs[:-1]
        if segs and segs[-1].casefold() in _SCOPE_SLOT_MARKERS:
            segs = segs[:-1]
    return "/".join(segs)


def _ctx_within(inner: str, outer: str) -> bool:
    """True when `inner` is `outer` itself or nested inside it.

    The leading-separator guard keeps distinct scopes apart (TOP01 vs TOP0,
    CTE{a} vs CTE{ab}) — a bare startswith would conflate them."""
    return (inner == outer or inner.startswith(outer + "/")
            or inner.startswith(outer + ":"))


# ── Main Extractor ──────────────────────────────────────────────────────

@dataclass
class ExtractionResult:
    script_name: str
    variables: list[VariableDefinition] = field(default_factory=list)
    template_replacements: list[str] = field(default_factory=list)
    resolution_stats: dict = field(default_factory=default_resolution_stats)
    # v3.3.145 (I3/case-3): statements sqlglot could not parse
    # (ErrorLevel.IGNORE yields None) — {"stmt_idx": int, "detail": str}
    # per failure, in statement order; empty when everything parsed.
    # A3 surfaces this on the analysis response.
    parse_errors: list[dict] = field(default_factory=list)


@dataclass
class _SelectScope:
    """Per-statement table context used by orphan resolution (R20 S1/S3/S5).

    Built once per SELECT/UPDATE/DELETE while its FROM/JOIN are walked,
    then threaded to every column registration inside that statement.
    Physical tables are recorded as (db, name) so S5 can detect system
    schemas; CTE references are kept separate because they are not
    physical tables (S3 counts physical tables only).
    """
    owner: Optional[exp.Expression] = None        # the statement node this scope belongs to
    tables: list = field(default_factory=list)    # [(db, name)] physical tables in FROM/JOIN
    aliases: dict = field(default_factory=dict)   # alias → physical table name (S1)
    ctes: list = field(default_factory=list)      # CTE names referenced in FROM/JOIN (S2)
    deriveds: list = field(default_factory=list)  # derived-table aliases in FROM/JOIN (S2, Fix C)
    key: str = ""                                 # ISSUE-4: the scope's context string
    outer: Optional["_SelectScope"] = None        # enclosing scope (correlated/outer refs)


def _detect_dialect(sql_text: str) -> str:
    """Detect SQL dialect by scoring distinctive markers.

    Returns the best sqlglot dialect name (hive, mysql, postgres, etc.).
    """
    import re
    upper = sql_text.upper()
    scores = {}

    # Hive family (MaxCompute/ODPS/Spark/Hive/Databricks)
    if re.search(r'(?i)INSERT\s+OVERWRITE\s+TABLE', sql_text): scores['hive'] = scores.get('hive', 0) + 10
    if re.search(r'(?i)SET\s+odps\.', sql_text): scores['hive'] = scores.get('hive', 0) + 10
    if re.search(r'(?i)PARTITION\s*\(', sql_text): scores['hive'] = scores.get('hive', 0) + 5
    if re.search(r'(?i)TBLPROPERTIES|STORED\s+AS\s+(ORC|PARQUET|TEXTFILE|AVRO)', sql_text): scores['hive'] = scores.get('hive', 0) + 5
    if re.search(r'(?i)LATERAL\s+VIEW\s+EXPLODE', sql_text): scores['hive'] = scores.get('hive', 0) + 5

    # Oracle
    if re.search(r'(?i)DECODE\s*\(', sql_text): scores['oracle'] = scores.get('oracle', 0) + 3
    if re.search(r'(?i)NVL\s*\(', sql_text): scores['oracle'] = scores.get('oracle', 0) + 3
    if re.search(r'(?i)CONNECT\s+BY', sql_text): scores['oracle'] = scores.get('oracle', 0) + 10
    if re.search(r'(?i)DBMS_|UTL_', sql_text): scores['oracle'] = scores.get('oracle', 0) + 10
    if re.search(r'(?i)ROWNUM\b', sql_text): scores['oracle'] = scores.get('oracle', 0) + 5
    if re.search(r'(?i)FROM\s+DUAL\b', sql_text): scores['oracle'] = scores.get('oracle', 0) + 10

    # PostgreSQL
    if re.search(r'(?i)ILIKE\b', sql_text): scores['postgres'] = scores.get('postgres', 0) + 5
    if '::' in sql_text and not '::=' in sql_text: scores['postgres'] = scores.get('postgres', 0) + 5
    if re.search(r'(?i)RETURNING\b', sql_text): scores['postgres'] = scores.get('postgres', 0) + 3

    # BigQuery
    if re.search(r'(?i)`[a-z]+\.[a-z]+\.[a-z]+`', sql_text): scores['bigquery'] = scores.get('bigquery', 0) + 10
    if re.search(r'(?i)STRUCT\s*<', sql_text): scores['bigquery'] = scores.get('bigquery', 0) + 5
    if re.search(r'(?i)ARRAY\s*<', sql_text): scores['bigquery'] = scores.get('bigquery', 0) + 3

    # TSQL (SQL Server)
    if re.search(r'(?i)\bTOP\s+\d+', sql_text): scores['tsql'] = scores.get('tsql', 0) + 5
    if re.search(r'(?i)\[[a-zA-Z_][a-zA-Z0-9_]*\]\.[a-zA-Z_][a-zA-Z0-9_]*\]', sql_text): scores['tsql'] = scores.get('tsql', 0) + 3
    if re.search(r'(?i)WITH\s*\(\s*NOLOCK\s*\)', sql_text): scores['tsql'] = scores.get('tsql', 0) + 10

    # Snowflake
    if re.search(r'(?i)QUALIFY\b', sql_text): scores['snowflake'] = scores.get('snowflake', 0) + 10
    if re.search(r'(?i)COPY\s+INTO', sql_text): scores['snowflake'] = scores.get('snowflake', 0) + 5

    # MySQL
    if re.search(r'(?i)LIMIT\s+\d+(\s+OFFSET\s+\d+)?\s*;?\s*$', sql_text, re.MULTILINE): scores['mysql'] = scores.get('mysql', 0) + 2
    if re.search(r'(?i)ENGINE\s*=', sql_text): scores['mysql'] = scores.get('mysql', 0) + 10
    if re.search(r'(?i)AUTO_INCREMENT', sql_text): scores['mysql'] = scores.get('mysql', 0) + 10

    if not scores:
        return 'mysql'

    # Hive also gets Oracle points (MaxCompute has both)
    if 'hive' in scores:
        scores['hive'] += scores.pop('oracle', 0) * 0.5

    best = max(scores, key=scores.get)
    return best


def _preprocess_sql(sql_text: str) -> tuple[str, list[int]]:
    """Strip SET statements and other non-SQL configuration lines.
    Also handles MaxCompute/ODPS/Hive-specific syntax.

    Returns `(clean_sql, kept_lines)` — K4 Fix F: `kept_lines[i]` is the
    ORIGINAL 1-based script line of `clean_sql`'s i-th line. Every line
    number that comes out of the CLEAN text (a tokenizer line, a parse
    error line) can be translated back to the script the user wrote; the
    paren-balance diagnostic is the consumer (a SET statement dropped
    above a broken statement used to shift the reported line by the whole
    dropped prefix).
    """
    import re
    lines = sql_text.split('\n')
    cleaned = []
    kept_lines: list[int] = []
    # E3a/1: a "SET"-prefixed line is only a config statement when it is
    # NOT the SET clause of a multi-line UPDATE/MERGE/DELETE/INSERT — the
    # DML keyword line opens the statement, the first ';' closes it.
    in_dml = False
    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        # Skip pure comments
        if stripped.startswith('--'):
            continue
        if re.match(r'(?i)^(update|merge|delete|insert)\b', stripped):
            in_dml = True
        # Skip SET statements (MaxCompute/ODPS configuration) — the
        # standalone `SET key = value;` form only; a SET clause line inside
        # a DML statement is kept (sqlglot parses the SET assignments).
        if re.match(r'(?i)^set\s+', stripped):
            if not in_dml:
                continue
        if stripped.endswith(';'):
            in_dml = False
        cleaned.append(line)
        kept_lines.append(line_no)
    return '\n'.join(cleaned), kept_lines


def _split_hive_multi_inserts(clean_sql: str) -> dict[int, list[tuple[int, exp.Expression]]]:
    """Hive FROM-led multi-table INSERT → re-parsed per-arm statements.

    `FROM <source> INSERT OVERWRITE TABLE t1 SELECT … INSERT OVERWRITE
    TABLE t2 SELECT …` cannot be parsed by sqlglot in any dialect (it
    degrades to a garbage Select with the arms dropped). Returns
    {stmt_idx: [(arm_idx, sqlglot_stmt), …]} — only for statements that
    are textually FROM-led with ≥1 INSERT arm, and only arms that
    re-parse cleanly as exp.Insert (hive dialect covers the
    OVERWRITE/INTO + PARTITION forms).
    """
    import re as _re
    pieces = [p for p in clean_sql.split(";") if p.strip()]
    out: dict[int, list] = {}
    for idx, piece in enumerate(pieces):
        lines = piece.split('\n')
        # FROM-led guard: the statement's FIRST token must be FROM — a
        # plain `INSERT INTO t … SELECT … FROM u` is NOT a multi-insert
        # and must go through the normal walk (E3a/2 regression guard).
        first_line = next((l for l in lines if l.strip()), "")
        if not _re.match(r'(?i)^\s*from\b', first_line):
            continue
        from_lines, arm_blocks, cur = [], [], None
        for line in lines:
            if _re.match(r'(?i)^\s*insert\b', line):
                if cur is not None:
                    arm_blocks.append(cur)
                cur = [line]
            elif cur is None:
                from_lines.append(line)
            else:
                cur.append(line)
        if cur is not None:
            arm_blocks.append(cur)
        if not arm_blocks:
            continue
        from_clause = '\n'.join(from_lines).strip()
        stmts = []
        for i, block in enumerate(arm_blocks):
            text = '\n'.join(block).strip()
            m = _re.search(r'(?i)\bselect\b', text)
            if not m:
                continue
            header, body = text[:m.start()].strip(), text[m.start():].strip()
            # from_clause already starts with "FROM" (leading keyword of
            # the from-led statement) — do not prefix another one.
            synthetic = f"{header} {body} {from_clause}".strip()
            try:
                arm_stmt = sqlglot.parse_one(synthetic, dialect="hive",
                                             error_level=sqlglot.ErrorLevel.IGNORE)
            except Exception:
                arm_stmt = None
            if arm_stmt is not None and isinstance(arm_stmt, exp.Insert):
                stmts.append((i, arm_stmt))
        if stmts:
            out[idx] = stmts
    return out


def extract_variables_from_sql(sql_text: str, script_name: str) -> ExtractionResult:
    """Main entry point: extract all variables via role-based Identifier walking.

    Algorithm:
      1. Strip SET/config statements
      2. Try parsing with hive dialect (covers MaxCompute/ODPS/Spark)
      3. Fall back to mysql if hive produces nothing
      4. Walk ALL Identifier nodes in the AST
      5. Classify each by parent node role
    """
    result = ExtractionResult(script_name=script_name)

    # Strip SET statements, comment lines
    clean_sql, kept_lines = _preprocess_sql(sql_text)

    # Detect dialect and parse
    dialect_used = _detect_dialect(clean_sql)
    parsed = None
    try:
        parsed = sqlglot.parse(clean_sql, dialect=dialect_used, error_level=sqlglot.ErrorLevel.IGNORE)
    except Exception:
        # benign: parse is best-effort (ErrorLevel.IGNORE) — any failure
        # falls through to the fallback dialect attempts below.
        pass

    # Fallback: try hive (covers MaxCompute/ODPS), then mysql
    if not parsed or not any(s is not None for s in parsed):
        for fallback in ['hive', 'mysql']:
            if fallback == dialect_used:
                continue
            try:
                parsed = sqlglot.parse(clean_sql, dialect=fallback, error_level=sqlglot.ErrorLevel.IGNORE)
                if parsed and any(s is not None for s in parsed):
                    dialect_used = fallback
                    break
            except Exception:
                # benign: per-fallback failure — try the next dialect.
                continue

    if not parsed:
        try:
            parsed = sqlglot.parse(clean_sql, dialect="mysql", error_level=sqlglot.ErrorLevel.IGNORE)
        except Exception:
            # benign: final parse failed — graceful degradation: the
            # caller gets an empty extraction (visible as an empty graph).
            return result

    result.template_replacements = [f"dialect: {dialect_used}"]
    if '${' in sql_text:
        result.template_replacements.append("template vars present — may affect parsing")

    # K4 ruling 3 (2026-08-28): structural paren-balance check — the
    # ErrorLevel.IGNORE recovery above never rejects a broken script, so
    # the statement-level None-hole record below is not enough (a missing
    # ')' parses into a plausible PARTIAL tree and parse_errors stays []).
    # Diagnostics only: extraction continues, the graph may be incomplete.
    # One record per statement — a statement already covered by an existing
    # parse error is not reported twice.
    _reported_stmts = {e.get("stmt_idx") for e in result.parse_errors}
    for _pe in _paren_balance_errors(clean_sql, dialect_used, len(parsed),
                                     kept_lines):
        if _pe["stmt_idx"] in _reported_stmts:
            continue
        result.parse_errors.append(_pe)
        _reported_stmts.add(_pe["stmt_idx"])

    # E3a/2: Hive FROM-led multi-table INSERT (`FROM t INSERT OVERWRITE
    # TABLE a SELECT … INSERT OVERWRITE TABLE b SELECT …`) — sqlglot
    # parses it as a garbage Select in every dialect. Detect textually
    # per statement piece, synthesize one INSERT…SELECT per arm, re-parse
    # each arm (hive dialect), and walk the arms instead of the garbage
    # statement. The synthetic text is only for PARSING — var line
    # numbers come from token runs against the ORIGINAL stream (I1), so
    # the synthesised FROM/GROUP BY shift nothing.
    hive_arms = _split_hive_multi_inserts(clean_sql)

    extractor = _RoleBasedExtractor(result, script_name, sql_text)
    # C-9: top-level statements are context-scoped by their statement index
    # ("TOP0", "TOP1", …) so same-named variables across DIFFERENT
    # top-level statements no longer collapse under the old shared "TOP"
    # context (they are different nodes — one per statement).
    # R44 (2026-08-28, F1 write-severance): the ODPS idiom
    #   INSERT OVERWRITE TABLE t PARTITION(...);   ← bare INSERT, no source
    #   SELECT ... ;                                ← the write's SELECT
    # parses as TWO statements, so the target TABLE var lands in TOP{n}
    # while every projection lands in TOP{n+1} — the statement's DML write
    # legs never exist (PL's bdm_acc_loan_info columns returned not-in-flow
    # in their own writer). A bare INSERT (no expression of its own)
    # immediately followed by a Select is ONE write: walk the Select under
    # the INSERT's own context (the exact semantics of _walk_insert's
    # `process_statement(expr, context)` path for an inline SELECT — the
    # docstring's "anchors are last-wins (I1)" behavior).
    _skip_stmt_idx = set()
    for stmt_idx, statement in enumerate(parsed):
        if stmt_idx in _skip_stmt_idx:
            continue
        if (isinstance(statement, exp.Insert)
                and statement.args.get("expression") is None
                and stmt_idx + 1 < len(parsed)
                and isinstance(parsed[stmt_idx + 1],
                               (exp.Select, exp.Union, exp.Intersect,
                                exp.Except))):
            extractor.process_statement(statement, f"TOP{stmt_idx}",
                                         merged_select=parsed[stmt_idx + 1])
            _skip_stmt_idx.add(stmt_idx + 1)
            continue
        if stmt_idx in hive_arms:
            # E3a/2: skip the garbage parse of a FROM-led multi-insert —
            # walk the re-parsed arms instead (each arm is its own INSERT
            # with target + SELECT body, context TOP{idx}/hive_arm{i}).
            # R29/ISSUE-4: the FROM-led source clause (`FROM page_view_stg
            # pvs`) is the OUTER scope shared by every arm — register it
            # into a TOP{idx} scope and link each arm's scope back to it, so
            # a correlated ref (`pvs.col`) inside an arm resolves to the
            # physical source table. (An arm body that ends in GROUP BY/
            # ORDER BY drops the trailing synthetic FROM on re-parse, so the
            # alias is NOT on that arm's own scope — it lives here.)
            outer_scope = None
            if statement is not None:
                outer_scope = _SelectScope(owner=statement,
                                           key=f"TOP{stmt_idx}")
                from_exp = (statement.args.get("from")
                            or statement.args.get("from_"))
                if from_exp is not None:
                    extractor._walk_from(from_exp, f"TOP{stmt_idx}",
                                         outer_scope)
            for arm_idx, arm_stmt in hive_arms[stmt_idx]:
                extractor.process_statement(arm_stmt,
                                            f"TOP{stmt_idx}/hive_arm{arm_idx}",
                                            outer=outer_scope)
            continue
        if statement is not None:
            extractor.process_statement(statement, f"TOP{stmt_idx}")
        else:
            # I3/case-3: ErrorLevel.IGNORE left a hole in the statement list —
            # record it (statement index + short text) so the caller can
            # surface "statement N failed to parse" instead of silently
            # dropping it. Never a hard failure — extraction continues.
            # K4 ruling 3: a statement already carrying the structural
            # paren-balance diagnostic is not reported twice.
            if stmt_idx in _reported_stmts:
                continue
            result.parse_errors.append({
                "stmt_idx": stmt_idx,
                "detail": _failed_stmt_detail(clean_sql, stmt_idx),
            })
            _reported_stmts.add(stmt_idx)

    # B3 (v3.3.145): walk outputs the S1-S3 chains could not attribute land
    # on their OWN container — extraction-time info, never a guess. L2
    # parents fields exclusively from source_tables (the context-string
    # picker is deleted), so an unattributed output column would render
    # parentless.
    extractor._attribute_output_containers()

    # R44 (2026-08-28): occurrence-coverage twins — the output-side field
    # instances and the derived-read physical ties the strict table.field
    # walker needs to cover EVERY dataflow-relevant occurrence of a
    # searched field (user ruling). Post-walk, extraction-time facts only.
    extractor._register_flow_occurrence_twins()

    # ISSUE-4: fold physical-table spelling to one canonical form BEFORE the
    # resolution-stats build so `_finalize_schema_candidates` (inside
    # build_resolution_stats) compares against canonical `_script_schemas` /
    # `_schema_candidates.visible_tables` — a case-variant table must never
    # dodge a unique-owner attribution.
    extractor._canonicalize_table_names()

    # R20: orphan resolution coverage report
    result.resolution_stats = extractor.build_resolution_stats()
    return result


def _failed_stmt_detail(clean_sql: str, stmt_idx: int) -> str:
    """Short human-readable text of the statement that failed to parse.

    Statements are ';'-delimited in the preprocessed script (SET/config
    lines already stripped, so the pieces line up with sqlglot's statement
    list). Truncated to ~60 chars — detail only, never used for matching.
    """
    pieces = [p.strip() for p in clean_sql.split(";") if p.strip()]
    if 0 <= stmt_idx < len(pieces):
        text = pieces[stmt_idx]
        if len(text) > 60:
            return text[:60] + "…"
        return text
    return "parse error"


def _paren_balance_errors(sql_text: str, dialect: str, stmt_count: int,
                          kept_lines: list[int] | None = None) -> list[dict]:
    """Structural paren-balance check over the PARSED script (K4 ruling 3).

    `sql_text` is the text that was actually parsed — the CLEAN sql, i.e.
    the preprocessed one (SET/config lines and comment-only lines dropped).
    Callers that tokenize a raw script (the unit tests) pass no
    `kept_lines`, and the reported line is then the tokenized text's own
    line.

    ErrorLevel.IGNORE recovers a partial tree from almost anything, so a
    genuinely broken script (a ')' missing three statements up) still parses
    into a plausible graph and `parse_errors` stays [] — design rule 23's
    "never silently skipped" promise quietly unkept (RFN shipped +2 parens
    before its OCR repair and reported a clean extraction).

    The tokenizer is the independent structural check: ONE pass over the
    parsed text (string literals and comments are token-aware, so a paren
    inside either never counts), split at `;` TOKENS, net depth per
    statement. A statement that still has `(` open at its end is reported —
    extraction NEVER rejects (the recovered tree still walks; the detail
    says the graph may be incomplete). Extra `)` (net < 0) is not reported
    here: a dangling close leaves a real hole in sqlglot's statement list,
    which the walk loop records as a None-hole parse error already.

    split-index → parse stmt_idx mapping: the parse ran on THIS text, so
    the split index IS the statement index (K4 Fix F — tokenizing the
    pre-preprocessed script made every split after a dropped SET line land
    one statement early). The tail alignment (len(splits) - stmt_count)
    only survives for a caller that skipped preprocessing: a negative
    offset is still clamped to 0 (sqlglot synthesizing statements the
    tokenizer did not split), and a split mapping to a negative stmt_idx
    is skipped (no parsed statement to attach the diagnostic to).

    Reported line: the split's first-token line in the PARSED text is
    translated back to the script through `kept_lines[clean_line - 1]`
    (`_preprocess_sql`'s kept-line map) so the diagnostic names the line
    the user wrote, not the line the parser read.

    Tokenizer failure → [] (benign: a diagnostic helper never raises; the
    parse path already reports what it can).
    """
    if stmt_count <= 0 or not sql_text:
        return []
    try:
        tokens = list(sqlglot.Tokenizer(dialect=dialect).tokenize(sql_text))
    except Exception:
        # benign: fall back to the dialect-agnostic tokenizer (the file's
        # own line-resolution convention) before giving up.
        try:
            tokens = list(sqlglot.Tokenizer().tokenize(sql_text))
        except Exception:
            return []

    splits: list[tuple[int, int]] = []   # (first-token line, net depth)
    first_line = 0
    depth = 0
    for tok in tokens:
        tt = tok.token_type
        if tt == TokenType.SEMICOLON:
            splits.append((first_line, depth))
            first_line, depth = 0, 0
            continue
        if first_line == 0:
            first_line = tok.line
        if tt == TokenType.L_PAREN:
            depth += 1
        elif tt == TokenType.R_PAREN:
            depth -= 1
    if first_line:
        splits.append((first_line, depth))

    offset = len(splits) - stmt_count
    if offset < 0:
        offset = 0
    errors: list[dict] = []
    for i, (line, net) in enumerate(splits):
        idx = i - offset
        if idx < 0 or net <= 0:
            continue
        # K4 Fix F: the tokenizer ran over the PARSED text — translate its
        # line back to the script the user wrote. A line outside the kept
        # map (a caller without preprocessing) is reported as-is.
        script_line = (kept_lines[line - 1]
                       if kept_lines and 1 <= line <= len(kept_lines) else line)
        errors.append({
            "stmt_idx": idx,
            "detail": (
                "unbalanced parentheses: %d '(' left open at statement end "
                "(script line %d) — sqlglot recovered a partial tree; the "
                "graph may be incomplete" % (net, script_line)),
        })
    return errors


def _is_as_keyword(tok) -> bool:
    """The statement-anchor `as`: the AS KEYWORD only (a non-STRING token
    with text "as") — never a string literal containing `as`. String
    literals are skipped when scanning for the anchor (token-run matching
    semantics, L16): `'as' AS c, a` must not collapse to `c, a` and steal
    a later statement's anchor line.
    """
    return tok.text.lower() == "as" and tok.token_type != TokenType.STRING


def _statement_head_run(expr) -> list[str]:
    """First ~6 non-STRING token texts of `expr`'s WITH-stripped render —
    the statement-head token run (W6 VT definition sites).

    A leading WITH clause renders as a prefix and is stripped first, so the
    run is the statement's OWN head (INSERT/SELECT/… keyword line), never
    the WITH line; AS KEYWORD tokens are dropped from the run (sqlglot
    inserts `AS` before aliases in renders). STRING tokens are filtered —
    a string literal equal to a head token is never a definition.
    """
    try:
        stmt_sql = expr.sql(dialect="mysql")
    except Exception:
        # benign: render failure → empty run (callers fall back).
        return []
    if stmt_sql and (expr.args.get("with") is not None
                     or expr.args.get("with_") is not None):
        try:
            stripped = expr.copy()
            stripped.args.pop("with", None)
            stripped.args.pop("with_", None)
            stmt_sql = stripped.sql(dialect="mysql")
        except Exception:
            # benign: strip failure → keep the with-prefixed render.
            pass
    try:
        rendered = list(sqlglot.Tokenizer().tokenize(stmt_sql))
    except Exception:
        return []
    return [t.text.lower() for t in rendered
            if t.token_type != TokenType.STRING and not _is_as_keyword(t)][:6]


# R45 Fix E (2026-08-28.8): the clause keywords a line can BELONG to. Only
# the clauses the walker actually stamps into `defined_in` participate (no
# `when`/`from`/`values`: a CASE arm's WHEN would re-label every following
# projection line, and a FROM line is not a clause a field occurrence is
# collected in). Looked up by TOKEN TYPE name first — the tokenizer folds
# multi-word keywords into ONE token (`ORDER BY` → TokenType.ORDER_BY), so
# a text-only match would never see them — then by text.
_LINE_CLAUSE_TOKENS = {
    "SELECT": "select", "WHERE": "where", "GROUP_BY": "group",
    "GROUP": "group", "HAVING": "having", "ORDER_BY": "order",
    "ORDER": "order", "ON": "on", "SET": "set", "USING": "using",
    "PARTITION": "partition", "INSERT": "insert", "UPDATE": "update",
    "DELETE": "delete", "MERGE": "merge", "CREATE": "create",
    "select": "select", "where": "where", "group": "group",
    "having": "having", "order": "order", "on": "on", "set": "set",
    "using": "using", "partition": "partition", "insert": "insert",
    "update": "update", "delete": "delete", "merge": "merge",
    "create": "create",
}

# `defined_in` → the line-clause it demands. A collapsed occurrence is a
# token the walker visited inside a specific clause; the line handed to it
# must be a line of THAT clause (Fix E). Values the walker fills with the
# CONTEXT name (`CTE{loan_final}`, `TOP0`, `PARTITION`'s own statement head)
# carry no clause, so they map to None and take the stream-order fallback.
_DEFINED_IN_CLAUSES: tuple[tuple[str, str], ...] = (
    ("select", "select"),
    ("where", "where"),
    ("group", "group"),
    ("order", "order"),
    ("having", "having"),
    ("on", "on"),
    ("set", "set"),
    ("using", "using"),
    ("partition", "partition"),
    ("insert", "insert"),
    ("update", "update"),
    ("delete", "delete"),
    ("merge", "merge"),
    ("create", "create"),
)

# R45 Fix B (2026-08-28.9): line-clause → the `defined_in` spelling the
# WALKER uses for that clause. A family-3 twin's clause now comes from the
# LINE it was anchored on (`_line_clauses`, the raw lowercase keys here),
# and dependency_graph's Phase 6/6b gates read the WALKER's spelling
# (`{"JOIN ON"}`, `{"WHERE", "HAVING", "QUALIFY"}`) — so the raw line
# clause must be re-spelled, not passed through (`OCCURRENCE on` matches
# nothing; the twin would silently lose its JOIN edge). One map, one
# spelling authority; `_DEFINED_IN_CLAUSES` above stays the reverse
# direction for `_occurrence_clause`.
_LINE_CLAUSE_TO_DEFINED_IN = {
    "where": "WHERE",
    "having": "HAVING",
    "qualify": "QUALIFY",
    "on": "JOIN ON",
    "select": "SELECT expr",
    "group": "GROUP BY",
    "order": "ORDER BY",
    "set": "UPDATE SET",
    "using": "USING",
    "partition": "PARTITION",
    "insert": "INSERT",
    "update": "UPDATE",
    "delete": "DELETE",
    "merge": "MERGE",
    "create": "CREATE",
}


def _occurrence_clause(defined_in: str | None) -> str | None:
    """The clause a collapsed occurrence was collected in (R45 Fix E).

    `defined_in` is the walker's clause stamp (`SELECT expr`, `WHERE`,
    `GROUP BY`, `JOIN ON`, `MERGE UPDATE SET`, …) or — when the walker had
    no clause for it — the context name (`CTE{loan_final}`, `TOP0`). The
    context-shaped values never name a clause; they return None so the
    occurrence falls back to stream order instead of being pinned to a
    clause it was never in.
    """
    text = (defined_in or "").strip().casefold()
    if not text:
        return None
    if "{" in text or re.match(r"^top\d+$", text):
        return None
    for needle, clause in _DEFINED_IN_CLAUSES:
        if needle in text:
            return clause
    return None


# K3 (2026-08-28.8): the signature of an expression FRAGMENT that reached a
# FIELD name — a list/argument separator, a paren, or a space inside a name
# that claims to be a column. A real identifier (quoted ones are stripped by
# `_clean`) never contains any of these; `a.*` and the ⟐ sentinels do.
_FIELD_FRAGMENT_CHARS = re.compile(r"[,()\s]")


def _field_identity(name: str) -> str:
    """Casefolded field identity for occurrence grouping (R45 family 3).

    SQL identifiers are case-insensitive, so `A.REPAY_ACCT_NO` in a
    projection list and `A.repay_acct_no` in a JOIN ON leg are the SAME
    field — only CASE folds. The QUALIFIER stays part of the identity on
    purpose: a bare `podtao` and a join-key `p2.podtao` are different
    occurrences of one column, on different lines in different scopes, so
    grouping them would hand one occurrence's line to the other and mint a
    twin where no occurrence exists.
    """
    return name.casefold()


def _name_token_run(name: str) -> list[str]:
    """Token texts of `name` for token-run line resolution (W4).

    The I1 replacement for the deleted `_find_position_scoped` text search:
    a variable NAME (possibly dotted, e.g. "p1.data_dt", or parenthesized,
    e.g. "(subq)") becomes the token run matched against the stream — a
    non-STRING, spacing-insensitive, exact-token subsequence, so a name
    that also occurs inside a string literal never matches. STRING tokens
    are filtered (a quoted identifier's text would re-introduce the
    string-literal false positive at the run level). A name that does not
    tokenize at all (a truncated display fragment cut inside a string
    literal, e.g. `CONCAT'price=',_p.price,_',st`) yields an empty run —
    the var then resolves to (0, 0) like any unmatched name, and the
    tokenizer error never escapes the extractor for valid SQL.
    """
    try:
        toks = sqlglot.Tokenizer().tokenize(name)
    except Exception:
        return []
    return [t.text.lower() for t in toks
            if t.token_type != TokenType.STRING]


class _RoleBasedExtractor:
    """Walks the AST, classifies every Identifier by its structural role."""

    def __init__(self, result: ExtractionResult, script_name: str, sql_text: str):
        self.result = result
        self.script_name = script_name
        self.sql_text = sql_text
        self._counter: dict[str, int] = {}
        # ISSUE-4 (scope-aware identity): CTE names are statement-local.
        # Keyed by top-level statement scope so a CTE name in one statement
        # never makes a physical table in another statement look like a CTE.
        # A CTE body context ("CTE{name}") maps to its enclosing statement
        # scope via `_cte_enclosing` (recorded in `_walk_cte_definitions`).
        self._cte_names: dict[str, set[str]] = {}   # scope → {casefolded CTE name}
        self._cte_enclosing: dict[str, str] = {}    # "CTE{name}" → enclosing scope
        # Physical-table names seen during the walk (casefolded). This is the
        # ONLY script-global namespace — feeds the frequency-vote canonical
        # spelling post-pass. Local handles (alias/CTE/derived) never enter.
        self._physical_table_names: set[str] = set()
        # Node identity key is (name, type.value, context) — see `_add`
        # (C-9: statement-scoped contexts made the dedup key a 3-tuple).
        self._seen: set[tuple[str, str, str]] = set()
        # R20 orphan resolution state
        self._resolution_stats: dict = default_resolution_stats()
        self._cte_output_columns: dict[str, set[str]] = {}  # cte name → output column names (S2)
        # Fix C (2b): derived-table alias → {output column name: two-hop
        # physical table or None}. None = one-hop attribution to the derived
        # alias; a table name = the output is an S1 alias of a plain column.
        self._derived_output_columns: dict[str, dict] = {}
        self._subq_counter: int = 0  # unique subquery IDs
        # Select bodies already walked by the explicit Subquery/Exists
        # branches (with their own subq{N}/exists{N} contexts) — the raw
        # walk prunes them so no phantom outer-context copies are registered.
        self._explicitly_walked_selects: set = set()
        # S4a (Phase 2, auto-resolution): SELECT-side schema enrichment state.
        # `script_schemas` = canonical table → {column: evidence_line};
        # `schema_candidates` = STILL-UNRESOLVED bare columns in ≥2-table
        # scopes ({field, visible_tables, loc, contexts}) — unique-owner
        # candidates are auto-attributed and removed (never-guess invariant).
        self._script_schemas: dict[str, dict] = {}  # table → {col: evidence_line}
        self._schema_candidates: list[dict] = []  # {field, visible_tables, loc, contexts}
        self._candidate_keys: set = set()         # (field, tuple(visible)) dedup
        self._derived_aliases: dict[str, set[str]] = {}  # scope → {casefolded derived alias}
        self._alias_names: dict[str, set[str]] = {}  # scope → {casefolded table alias} (M-E3b)
        # Pre-tokenize SQL for accurate position lookups (Bug 4 fix)
        try:
            self._tokens = list(sqlglot.Tokenizer().tokenize(sql_text))
        except Exception:
            # benign: tokenization failure → empty stream; every position
            # lookup then falls back to the string-based search.
            self._tokens = []
        # R45 Fix C (2026-08-28.8): paren depth BEFORE each token, and the
        # stream's last line — the structural bound for the occurrence-pass
        # line search (`_paren_scope_bound`). A `)` inside a string literal
        # or a comment never counts (the tokenizer is both-aware), so the
        # depth profile is exact.
        self._tok_depth: list[int] = []
        self._token_last_line = 0
        _depth = 0
        for _tok in self._tokens:
            self._tok_depth.append(_depth)
            if _tok.token_type == TokenType.L_PAREN:
                _depth += 1
            elif _tok.token_type == TokenType.R_PAREN:
                _depth -= 1
            if _tok.line > self._token_last_line:
                self._token_last_line = _tok.line
        # ISSUE-4: frequency vote over identifier tokens for the canonical
        # physical-table spelling. Only identifier token types vote —
        # TokenType.VAR / TokenType.IDENTIFIER. STRING/NUMBER literals (the
        # op-log `'EAST5_STZFXXB'` string) and KEYWORD tokens (SELECT/FROM/
        # ORDER/…) are excluded (M-E4), so a table named after a reserved
        # word (`order`/`user`/`group`) is never skewed by keyword votes.
        # Counting from the token stream (NOT `_register_table`) sees the
        # ALTER TABLE references the AST walk skips, so the majority spelling
        # is the true majority of the SOURCE text (east5: 8 vs 1 uppercase).
        self._ident_votes: dict[str, Counter] = defaultdict(Counter)
        for _tok in self._tokens:
            if _tok.token_type not in (TokenType.VAR, TokenType.IDENTIFIER):
                continue
            _txt = _tok.text
            if _txt:
                self._ident_votes[_txt.casefold()][_txt] += 1
        # Statement-anchor cache: id(statement node) → its first-token line
        # (original file), computed by token-subsequence matching. This
        # sqlglot version has no parse_position_marks, so the anchor comes
        # from the token stream, never from a token TEXT search (the q76
        # string-literal caveat — a STRING token equal to a run token on an
        # earlier line would beat the real name token).
        self._anchor_cache: dict[int, int] = {}
        # S3 (v3.3.152): occurrence-aware anchors — head-token tuple → the
        # last line already matched for that head. `_statement_anchor`
        # searches STRICTLY AFTER it, so the k-th walk of a textually
        # identical statement/CTE body (tpcds q14/q39: the same
        # `with cross_items … ) x` appears in BOTH top-level statements)
        # anchors on its OWN occurrence instead of always first-matching
        # the earlier statement's body — the old first-match left the
        # second statement's def-site lookups scoped to the first
        # statement's range, and their whole-stream fallback then picked
        # the FIRST `) alias` in the file (S3 bug family: occurrence
        # beats definition). Walks happen in stream order per head, so
        # the k-th call with a given head is the k-th occurrence.
        self._anchor_head_last: dict[tuple, int] = {}
        # Context-prefix → statement first-token line: recorded at each
        # statement-walk entry so `_find_def_position` can scope line
        # lookups to the variable's own statement (D-series).
        self._stmt_anchor_lines: dict[str, int] = {}
        # L4 (part 2): ids of SELECT outputs whose name is the extractor's
        # AUTO-NAME for an unaliased expression/literal projection (a
        # truncated SQL-text fragment: `CONCAT'price=',_p.price,_',st`,
        # `NULL`, `1`) rather than a column name the statement states. The
        # write-side twin pass consults this so it never mints a physical
        # field identity from such a fragment.
        self._auto_named_outputs: set[str] = set()
        # C-13(b): AS-filtered token stream + first-token position index,
        # built ONCE per analysis. `_statement_anchor` scans the index
        # candidates instead of rebuilding the filtered list and linearly
        # re-scanning the whole stream for every statement (O(S·n) per
        # anchor call → O(candidates) lookups; identical results — the
        # linear scan stays as the fallback).
        self._tokens_wo_as = [t for t in self._tokens
                              if not _is_as_keyword(t)]
        self._first_token_index: dict[str, list[int]] = {}
        for _ti, _tok in enumerate(self._tokens_wo_as):
            self._first_token_index.setdefault(_tok.text.lower(), []).append(_ti)
        # R45 (2026-08-28.6) — occurrences the (name, type, context) dedup
        # in `_add` collapsed away. Each entry is a genuine walker-visited
        # field occurrence (a column ref, or a JOIN-key expression side)
        # that would otherwise leave NO node at its own line; family 3 of
        # `_register_flow_occurrence_twins` re-anchors them as
        # occurrence-side twins.
        self._collapsed_occurrences: list[dict] = []
        # R45 Fix E (2026-08-28.9): per-context columns a MERGE actually
        # WRITES — the WHEN MATCHED UPDATE SET left-hand targets plus the
        # WHEN NOT MATCHED INSERT column list (casefolded; SQL identifiers
        # are case-insensitive). `_register_flow_occurrence_twins` family 1
        # gates its write-twin mint on this for MERGE contexts: a MERGE's
        # write slots are exactly what its WHEN clauses name, never the
        # USING subquery's projections.
        self._merge_written: dict[str, set[str]] = defaultdict(set)

    def _next_id(self, key: str) -> str:
        self._counter[key] = self._counter.get(key, 0) + 1
        return _make_id(self.script_name, key, self._counter[key])

    def _statement_anchor(self, expr) -> int:
        """1-based line (original file) of `expr`'s FIRST token.

        Anchors a statement (Select/Update/Insert/Create/Merge node) by
        matching the first 6 tokens of its rendered SQL as a token
        subsequence in the pre-tokenized stream. The statement's own text
        is unique enough that the first match is its own occurrence, and
        the match is exact — no text search, no string-literal confusion.
        (6 tokens, not fewer: 4-token heads collide when a body statement
        shares its opening tokens with an earlier one — the sample's main
        `SELECT a.id, a.amt` collides with the mid-body `SELECT a.id, b.val`
        at token 5, so the shorter head anchors the main select at the mid
        body's line and last-wins TOP0 reads resolve one statement early.)
        Returns 0 when no match is found (callers fall back conservatively).
        A leading WITH clause renders as a prefix and is stripped before
        matching — the anchor is the statement's OWN first token (the
        INSERT/SELECT keyword line), never the WITH line.

        When the same head tokens occur more than once (identical
        statements/CTE bodies, e.g. tpcds q14/q39), the k-th anchor call
        for that head returns the k-th occurrence — the walks run in
        stream order per head, so each node lands on its own text
        (`_anchor_head_last`).
        """
        key = id(expr)
        cached = self._anchor_cache.get(key)
        if cached is not None:
            return cached
        line = 0
        try:
            stmt_sql = expr.sql(dialect="mysql")
        except Exception:
            # benign: render failure → no anchor (0); callers fall back
            # conservatively (documented in the docstring).
            stmt_sql = ""
        if stmt_sql and (expr.args.get("with") is not None
                         or expr.args.get("with_") is not None):
            # The WITH clause is a modifier on the statement ("WITH cte AS
            # (...) INSERT ..."); the statement's own first token is the one
            # AFTER it. Strip the with args from a copy so the anchor lands
            # on the statement keyword itself — otherwise a WITH-wrapped
            # INSERT anchors at the WITH line and its scoped lookup range
            # collapses to the with clause (D-series).
            try:
                stripped = expr.copy()
                stripped.args.pop("with", None)
                stripped.args.pop("with_", None)
                stmt_sql = stripped.sql(dialect="mysql")
            except Exception:
                # benign: strip failure → keep the with-prefixed render.
                pass
        if stmt_sql:
            try:
                rendered = list(sqlglot.Tokenizer().tokenize(stmt_sql))
            except Exception:
                # benign: tokenize failure → no head match → anchor 0,
                # the same conservative fallback.
                rendered = []
            if rendered:
                # Skip AS KEYWORD tokens on BOTH sides: sqlglot's render
                # inserts `AS` before aliases (`MERGE INTO customers tgt`
                # renders as "MERGE INTO customers AS tgt"), which breaks
                # the 6-token head match for alias-bearing statement heads.
                # Only the KEYWORD counts — a STRING literal containing
                # `as` is never the anchor (token-run string-skip), and
                # dropping it from BOTH sides would collapse `'as' AS c, a`
                # into `c, a`, letting an earlier statement masquerade as a
                # later one's head (L16).
                head = [t.text.lower() for t in rendered
                        if not _is_as_keyword(t)][:6]
                # S3: an identical earlier statement's body already claimed
                # this head — search strictly after its matched line so THIS
                # node lands on its own occurrence (walks are in stream
                # order per head).
                head_key = tuple(head)
                last_line = self._anchor_head_last.get(head_key, 0)
                # C-13(b): candidate scan via the first-token position index
                # (built once in __init__). Identical matching semantics to
                # the linear scan below — the index only skips tokens that
                # cannot start the subsequence (head[0] mismatch).
                tokens = self._tokens_wo_as
                limit = len(tokens) - len(head) + 1
                candidates = self._first_token_index.get(head[0], [])
                for i in candidates:
                    if i >= limit:
                        break
                    if tokens[i].line <= last_line:
                        continue
                    match = True
                    for j in range(1, len(head)):
                        if tokens[i + j].text.lower() != head[j]:
                            match = False
                            break
                    if match:
                        line = tokens[i].line
                        break
                if not line and candidates:
                    # Index miss (defensive — head[0] came from the same
                    # tokenizer family) → full linear scan fallback, the
                    # pre-C-13(b) behavior.
                    for i, tok in enumerate(tokens):
                        if i + len(head) > len(tokens):
                            break
                        if tok.text.lower() != head[0]:
                            continue
                        if tok.line <= last_line:
                            continue
                        match = True
                        for j in range(1, len(head)):
                            if tokens[i + j].text.lower() != head[j]:
                                match = False
                                break
                        if match:
                            line = tok.line
                            break
        if line and head_key:
            self._anchor_head_last[head_key] = line
        self._anchor_cache[key] = line
        return line

    def _record_stmt_anchor(self, context: str, stmt) -> None:
        """Record the first-token line of the statement walked under `context`.

        LAST-WINS (I1): a context walked more than once — the INSERT walk
        followed by its source SELECT's walk under the same "TOP{n}" — keeps
        the LAST walk's anchor. Vars registered between the two (the INSERT
        target, its alias, PARTITION columns) have already resolved against
        the INSERT's anchor by then, and the body vars that follow resolve
        against their own SELECT — each var's own statement, D-series.
        """
        if context:
            line = self._statement_anchor(stmt)
            if line > 0:
                self._stmt_anchor_lines[context] = line

    def _stmt_anchor_for(self, context: str) -> int:
        """Longest recorded context that is a '/'-segment prefix of `context`."""
        best, best_len = 0, -1
        for ctx, line in self._stmt_anchor_lines.items():
            if line <= 0:
                continue
            if context == ctx or context.startswith(ctx + "/"):
                if len(ctx) > best_len:
                    best, best_len = line, len(ctx)
        return best

    def _next_anchor_after(self, line: int, context: str = "") -> int:
        """Smallest recorded anchor line > `line` from a context that is NOT
        nested inside `context`. Nested statements (subquery/derived-table
        bodies walked under `context`/`context/...`) must not truncate the
        range: a var may legitimately sit anywhere inside its OWN statement,
        including after a nested body's anchor (e.g. the loan_final-body
        WHERE at line 158 sits after the :join:accu body anchor at 86 — the
        next non-nested anchor is the following statement's 160)."""
        def _nested(ctx: str) -> bool:
            return (ctx == context or ctx.startswith(context + "/")
                    or ctx.startswith(context + ":"))
        return min((a for c, a in self._stmt_anchor_lines.items()
                    if a > line and not _nested(c)), default=10**9)

    def _first_keyword_token_after(self, keyword: str, line: int) -> int:
        """Line of the first `keyword` token at line > `line` (0 if none).
        Token-stream only (I1): the pre-tokenized stream's first-token
        position index. STRING tokens and quoted identifiers never match —
        a literal 'select' or a `select`-quoted column tokenizes with its
        quotes, so only the unquoted KEYWORD hits.
        """
        for i in self._first_token_index.get(keyword, []):
            tok = self._tokens_wo_as[i]
            if tok.line > line:
                return tok.line
        return 0

    def _vt_fallback_line(self, stmt, context: str) -> int:
        """SELECT/statement-keyword line for a VIRTUAL_TABLE whose
        def-site resolution failed (line 0). I1 token-stream only — never
        a text search. E5 (audit item 1): render-head runs fail when
        sqlglot canonicalizes tokens (substr→SUBSTRING in every dialect,
        TSQL brackets→backticks, TOP→LIMIT), so the ⟐ VT's def-site comes
        up empty. Fallback chain:
          1. the statement's OWN anchor — its keyword line when the render
             head matches;
          2. the nearest ANCESTOR select with a valid anchor → the first
             "select" keyword token strictly after that line;
          3. the recorded statement anchor for the context prefix
             (`_stmt_anchor_for`) → the first statement-keyword token
             strictly after the ENCLOSING statement's keyword line;
          4. the first statement-keyword token in the whole stream.
        Returns 0 only when the stream has no matching keyword at all.
        """
        anch = self._statement_anchor(stmt)
        if anch > 0:
            return anch
        p = stmt.parent
        while p is not None:
            if isinstance(p, exp.Select):
                a = self._statement_anchor(p)
                if a > 0:
                    ln = self._first_keyword_token_after("select", a)
                    if ln > 0:
                        return ln
            p = p.parent
        head = _statement_head_run(stmt)
        kw = head[0] if head else "select"
        ca = self._stmt_anchor_for(context)
        if ca > 0:
            ln = self._first_keyword_token_after(kw, ca)
            if ln > 0:
                return ln
        return self._first_keyword_token_after(kw, 0)

    def _find_def_position(self, runs: list[list[str]], node=None,
                           stmt_ctx: str = "",
                           ret_last: bool = False,
                           loose_first: bool = False) -> tuple[int, int]:
        """1-based (line, line) of a DEFINITION site — token-run matching (I1).

        Replaces the composition text search for definition sites: the runs
        (each a token text list, e.g. ["bdm_acc_loan_info", "p1"] or [")",
        "accu"]) are matched as token subsequences, STRING tokens excluded —
        a string literal equal to a run token is never a definition. Order:
        (1) the first run that matches, scoped to the enclosing statement
        ([its anchor, the next non-nested anchor)); (2) whole-stream token
        run — never a text search, so multi-line pretty renders and
        'name AS alias' compositions cannot break it. Returns (0, 0) when
        nothing matches (tokenizer failures degrade gracefully).

        `ret_last=True` returns the line of the run's LAST matched token
        instead of its first — clause-keyword runs like ["where", "data_dt"]
        (W2, Defect 5) anchor the occurrence on the clause keyword but must
        report the COLUMN's line, not the keyword's.

        `loose_first=True` relaxes adjacency for the FIRST run only (the
        clause-keyword run): "where" followed by the NEXT occurrence of the
        column anywhere in the statement (STRING tokens still skipped) —
        `WHERE a = 1 AND data_dt = …` has no "where data_dt" adjacency, and
        the scoped range may legitimately extend past nested bodies, so the
        keyword-then-next-name match is the honest reading of "the name in
        this clause". The fallback bare-name run stays strict.
        """
        try:
            tokens = self._tokens
            if not tokens:
                return (0, 0)
            anchor = 0
            if node is not None:
                anchor = self._statement_anchor(node)
            if anchor <= 0:
                anchor = self._stmt_anchor_for(stmt_ctx)
            if anchor > 0:
                end = self._next_anchor_after(anchor, stmt_ctx)
                for idx, run in enumerate(runs):
                    if not run:
                        continue
                    line = self._match_token_run(run, tokens, anchor, end,
                                                 ret_last=ret_last,
                                                 loose=(loose_first and idx == 0))
                    if line:
                        return (line, line)
            # Whole-stream fallback: ONLY the last run (the bare-name run).
            # Clause-keyword runs (["where", name], ["update", name], …) are
            # meaningful only inside the owning statement — a whole-stream
            # match would anchor on a DIFFERENT statement's clause keyword
            # (W2: the L90 WHERE's data_dt must not jump to the L224 one).
            for run in runs[-1:]:
                if not run:
                    continue
                line = self._match_token_run(run, tokens, 0, 10**9,
                                             ret_last=ret_last)
                if line:
                    return (line, line)
            return (0, 0)
        except Exception:
            return (0, 0)

    def _paren_scope_bound(self, anchor: int, context: str = "") -> int:
        """Last line of the paren scope `anchor` sits in (token-stream, I1).

        R45 Fix C: a subquery / derived-table body's line range must stop at
        the `)` that closes it. The recorded statement anchors give a range
        its start and its "next statement" end, but a nested body's next
        non-nested anchor is the ENCLOSING statement's next one — so
        without a structural bound the body's range runs past its own
        closing paren and the enclosing statement's continuation after it
        (its GROUP BY, its next join leg) reads as an occurrence of the
        NESTED scope's field (SUP_M: `GROUP BY lending_ref` @59 sits in the
        enclosing subquery whose source is bdm_acc_loan_info, but the
        NOT-IN subquery that closes at L58 handed the line to its own
        bdm_evt_loan_trans group).

        R45 Fix D (2026-08-28.9): WITHHELD — reading the scope depth at the
        context's own anchor TOKEN instead of at its anchor line's first
        token (the adjudicated same-line-nested-body correction) moved the
        occurrence twins of the whole corpus, and with them the canonical
        SUP_M ods_hub_lsacmsp.lending_ref closure (jaccard
        lending_ref/SUP_M/downstream recall 0.7905, 22 canonical edges
        unmatched). The line-based read is what the repinned baselines
        encode, so it stays; the same-line correction needs its own
        baseline wave. The scope-OWNER tie-break half of Fix D did land
        (see `_scope_line_owner`).

        Depth 0 at the anchor (a top-level statement) has no enclosing
        paren to close → 10**9 (the "next statement" bound then rules
        alone, exactly as before). Tokenizer failure / empty stream →
        10**9 (degrades to the previous behavior).
        """
        tokens = self._tokens
        depths = self._tok_depth
        if not tokens or anchor <= 0:
            return 10**9
        start = 0
        n = len(tokens)
        while start < n and tokens[start].line < anchor:
            start += 1
        if start >= n:
            return 10**9
        own = depths[start]
        if own <= 0:
            return 10**9
        for i in range(start, n):
            if (tokens[i].token_type == TokenType.R_PAREN
                    and depths[i] - 1 < own):
                return tokens[i].line
        return 10**9

    @staticmethod
    def _ctx_is_ancestor(outer: str, inner: str) -> bool:
        """True when context `outer` is a strict ancestor-or-equal scope of
        `inner` (the context tree's '/'-segment and ':join:' nesting).

        R45 Fix D: the scope-owner tie-break. String LENGTH said nothing
        about nesting (`CTE{x}` is longer than `TOP0` yet the two are
        different statements; `TOP0/a` vs `TOP0/abc` orders by name length),
        and two contexts anchored on the SAME line resolved by whichever
        spelling happened to be longer — a same-line subquery's parent lost
        its own continuation lines to it. Ancestry is the real relation: of
        two contexts claiming one line, the DESCENDANT is the innermost.
        """
        return inner == outer or inner.startswith(outer + "/") \
            or inner.startswith(outer + ":")

    def _scope_line_owner(self) -> dict[int, str]:
        """line → innermost RECORDED context whose range covers it.

        R45 Fix C: an occurrence line belongs to the scope the walker
        collected it in. A line inside a nested body's own range is that
        nested context's occurrence — the enclosing context must never
        claim it (`_occurrence_lines` skips such lines), otherwise a
        nested scope's textual occurrence is handed to the enclosing
        group's twin and the twin lands on the wrong table's line.

        R45 Fix D (2026-08-28.9): overlapping ranges resolve by ANCESTRY,
        not by context-string length — a context that contains the other
        is the outer one, so the descendant wins its own lines; when
        neither contains the other (sibling statements), the LATER anchor
        line wins (the closer statement start); equal anchors fall back to
        the longest spelling (the old tie-break, last resort only).
        """
        innermost: dict[int, str] = {}
        for ctx, line in self._stmt_anchor_lines.items():
            if line <= 0:
                continue
            end = min(self._next_anchor_after(line, ctx),
                      self._paren_scope_bound(line, ctx),
                      self._token_last_line + 1)
            for ln in range(line, end):
                cur = innermost.get(ln)
                if cur is None or self._ctx_is_ancestor(cur, ctx):
                    innermost[ln] = ctx
                elif not self._ctx_is_ancestor(ctx, cur) and line > (
                        self._stmt_anchor_lines.get(cur, 0)):
                    innermost[ln] = ctx
        return innermost

    def _line_clauses(self, lo: int, hi: int) -> dict[int, str]:
        """line → clause keyword governing it, over the token stream (Fix E).

        The clause of a line is the last clause keyword at or before it
        (`AND x = 1` under a WHERE is a WHERE line; the first line of a
        subquery's SELECT is a SELECT line). Computed per group over
        [lo, hi) so a clause never leaks in from the previous statement.
        STRING tokens are skipped (a literal 'where' is text, not a clause).
        """
        out: dict[int, str] = {}
        cur = ""
        for tok in self._tokens:
            if tok.line >= hi:
                break
            if tok.token_type != TokenType.STRING:
                kw = (_LINE_CLAUSE_TOKENS.get(tok.token_type.name)
                      or _LINE_CLAUSE_TOKENS.get(tok.text.lower()))
                if kw:
                    cur = kw
            if tok.line >= lo:
                out[tok.line] = cur
        return out

    def _occurrence_lines(self, name: str, context: str,
                          taken: set[int],
                          innermost: dict[int, str] | None = None
                          ) -> list[int]:
        """R45 Fix B: every line of `context`'s statement range where
        `name`'s token run occurs, EXCEPT lines a surviving var of the same
        field already anchors, in stream order.

        A collapsed occurrence consumes these in order, so the 2nd
        occurrence of a field lands on the 2nd textual occurrence even
        though the 1st is taken by the surviving node.

        R45 Fix C: two boundaries keep the search inside `context`'s own
        scope — the paren scope of `context`'s anchor (`_paren_scope_bound`)
        and the nested recorded scopes' ranges (`innermost`, from
        `_scope_line_owner`): a line a nested body owns is never an
        occurrence of the enclosing context, so handing it out would mint
        the enclosing group's twin on another scope's line.

        R45 Fix G: a BARE field identity (`lending_ref`) only matches BARE
        token occurrences. The token run of a bare name is one token, so
        every qualified spelling of that field (`p1.lending_ref`) also
        matches it — and those are ANOTHER group's occurrences (Fix D
        splits groups per qualifier for exactly that reason). Requiring the
        token before the match not to be `.` keeps each group inside its
        own qualifier's occurrences.
        """
        tokens = self._tokens
        run = _name_token_run(name)
        if not tokens or not run:
            return []
        anchor = self._stmt_anchor_for(context)
        if anchor <= 0:
            return []
        end = min(self._next_anchor_after(anchor, context),
                  self._paren_scope_bound(anchor))
        bare = "." not in (name or "")
        out: list[int] = []
        for ln, first_idx in self._all_match_lines(run, anchor, end):
            if bare and first_idx > 0 and tokens[first_idx - 1].text == ".":
                continue  # a qualified spelling — another group's occurrence
            if ln in taken:
                continue
            if innermost is not None:
                owner = innermost.get(ln)
                # A line another recorded scope owns is admissible only when
                # that scope is an ANCESTOR of `context` (the case where
                # `context` has no anchor of its own and borrows the
                # enclosing statement's range). A nested body's line is that
                # nested context's occurrence — never this context's.
                if (owner is not None and owner != context
                        and not (context.startswith(owner + "/")
                                 or context.startswith(owner + ":"))):
                    continue
            out.append(ln)
        return out

    def _all_match_lines(self, run: list[str], lo_line: int,
                         hi_line: int) -> list[tuple[int, int]]:
        """Every (line, first-token index) where `run` occurs in [lo, hi).

        Same matching rules as `_match_token_run` (non-STRING tokens, AS
        KEYWORD may interleave) — but it collects ALL matches instead of
        stopping at the first, so an occurrence pass can hand them out in
        stream order. The index lets the caller inspect the token BEFORE the
        match (Fix G's bare/qualified discriminator).
        """
        tokens = self._tokens
        out: list[int] = []
        n = len(tokens)
        r0 = run[0].lower()
        for i in range(n):
            tok = tokens[i]
            if tok.line < lo_line:
                continue
            if tok.line >= hi_line:
                break
            if tok.token_type == TokenType.STRING:
                continue
            if tok.text.lower() != r0:
                continue
            j, k = i + 1, 1
            while k < len(run):
                if j >= n:
                    break
                t2 = tokens[j]
                if t2.token_type == TokenType.STRING:
                    j += 1
                    continue
                if t2.text.lower() == run[k].lower():
                    k += 1
                    j += 1
                    continue
                if _is_as_keyword(t2):
                    j += 1
                    continue
                break
            if k == len(run):
                out.append((tok.line, i))
        return out

    @staticmethod
    def _match_token_run(run: list[str], tokens, lo_line: int,
                         hi_line: int, ret_last: bool = False,
                         loose: bool = False) -> int:
        """First line where `run` occurs as a token run within [lo, hi).

        Each run token must equal a non-STRING token's text (lowercased);
        the AS KEYWORD may be interleaved between run tokens ('FROM t AS a'
        tokenizes t, AS, a — the alias run is [t, a]). Returns 0 when the
        run never occurs in the range. `ret_last=True` reports the LAST
        matched token's line instead of the first's (clause-keyword runs).
        `loose=True` drops the adjacency requirement: each later run token
        is the next at-or-after occurrence (STRING tokens still skipped) —
        clause-keyword runs ("where" … column) never require adjacency.
        """
        n = len(tokens)
        r0 = run[0].lower()
        for i in range(n):
            tok = tokens[i]
            if tok.line < lo_line:
                continue
            if tok.line >= hi_line:
                break
            if tok.token_type == TokenType.STRING:
                continue
            if tok.text.lower() != r0:
                continue
            j, k = i + 1, 1
            if loose:
                while k < len(run):
                    rk = run[k].lower()
                    found = False
                    while j < n and tokens[j].line < hi_line:
                        t2 = tokens[j]
                        if t2.token_type != TokenType.STRING \
                                and t2.text.lower() == rk:
                            found = True
                            break
                        j += 1
                    if not found:
                        break
                    k += 1
                    j += 1
            else:
                while k < len(run):
                    if j >= n:
                        break
                    t2 = tokens[j]
                    if t2.token_type == TokenType.STRING:
                        j += 1
                        continue
                    if t2.text.lower() == run[k].lower():
                        k += 1
                        j += 1
                        continue
                    if _is_as_keyword(t2):
                        j += 1
                        continue
                    break
            if k == len(run):
                return tokens[j - 1].line if ret_last else tok.line
        return 0

    def _add(self, name: str, var_type: VariableType, sql_expr: str = "",
             defined_in: str = "", context: str = "TOP",
             source_cols: list[str] | None = None,
             source_tables: list[str] | None = None,
             is_output: bool = False,
             def_site: tuple | None = None,
             alias_of: str | None = None,
             is_alias_handle: bool = False) -> VariableDefinition | None:
        """Add a variable, deduplicating by (name, type, context) — one node
        per unique variable per scope (C-9: top-level statements are scoped
        by statement index, so same-named vars in DIFFERENT statements stay
        distinct nodes).

        `def_site` = (runs, anchor_node, stmt_ctx) — or 4-tuple (runs,
        anchor_node, stmt_ctx, ret_last) or 5-tuple (runs, anchor_node,
        stmt_ctx, ret_last, loose_first) — for I1 DEFINITION sites: line
        lookup via token runs instead of the occurrence text search.
        `alias_of` (I4) = id of the exact source var this alias pairs with.
        """
        name = _clean(name)
        if not name:
            return None

        # CTE tables referenced in FROM clauses also appear as TABLE.
        # Merge: if a CTE with same name exists, skip the TABLE — but only
        # when the CTE is VISIBLE in this context (#386 ruling, 2026-08-28:
        # a CTE's scope ends with its statement — a LATER statement
        # referencing the same bare name refers to a PHYSICAL table, not
        # the CTE). The old any-context merge swallowed the out-of-scope
        # read whole: no TABLE var, so the physical table node never
        # existed and its columns folded onto the cte_table entity. Scope
        # visibility is `_is_cte_name`'s own rule (statement-scoped
        # `_cte_names` via `_scope_top`), so in-scope refs keep folding
        # exactly as before.
        if var_type == VariableType.TABLE and self._is_cte_name(name, context):
            for existing in self.result.variables:
                if (existing.variable_type == VariableType.CTE
                        and existing.name.lower() == name.lower()):
                    return None  # already exists as CTE (visible here)

        # Universal node identity: (name, type, context)
        # Every variable is scoped to its context. Two variables with the
        # same name and type in DIFFERENT contexts are different nodes.
        # Example: SUM(x) AS total in UNION branch 0 vs branch 1.
        key = (name, var_type.value, context)
        if key in self._seen:
            # R45 Fix B: the dedup keeps ONE node per (name, type, context),
            # but the occurrence the walker just visited is still a genuine
            # field occurrence — a 2nd WHEN arm, an NVL fallback operand, a
            # byte-identical projection, a later JOIN-key leg, a parallel
            # derived-body copy. Record it so family 3 can anchor it at its
            # own line (resolved post-walk, so base anchors never move).
            if var_type in (VariableType.COLUMN, VariableType.EXPRESSION):
                self._collapsed_occurrences.append({
                    "name": name, "type": var_type, "context": context,
                    "defined_in": defined_in,
                })
            return None
        self._seen.add(key)

        vid = self._next_id(f"{context}:{name}")
        if def_site is not None:
            if len(def_site) >= 5:
                runs, node, stmt_ctx, ret_last, loose_first = def_site
                ls, le = self._find_def_position(runs, node, stmt_ctx,
                                                 ret_last=ret_last,
                                                 loose_first=loose_first)
            elif len(def_site) >= 4:
                runs, node, stmt_ctx, ret_last = def_site
                ls, le = self._find_def_position(runs, node, stmt_ctx,
                                                 ret_last=ret_last)
            else:
                runs, node, stmt_ctx = def_site
                ls, le = self._find_def_position(runs, node, stmt_ctx)
        else:
            ls, le = self._find_def_position(
                [_name_token_run(name)], None, context)
        var = VariableDefinition(
            id=vid, name=name, variable_type=var_type,
            sql_expression=sql_expr,
            source_columns=source_cols or [],
            source_tables=source_tables or [],
            defined_in=defined_in, context=context,
            line_start=ls, line_end=le,
            is_output=is_output,
            alias_of=alias_of,
            is_alias_handle=is_alias_handle,
        )
        # K3 (2026-08-28.8): a FIELD whose NAME is not an identifier is an
        # expression FRAGMENT, never a column the script names. The
        # unrepaired RFN produced `lending_ref, 4, 5)` this way: the missing
        # ')' made sqlglot recover a partial tree whose alias render spans a
        # paren, and the fragment reached the field namespace as if it were
        # `lending_ref`'s name. The structural check (`_paren_balance_errors`,
        # 2026-08-28.7) now REPORTS such a script; this boundary keeps the
        # fragment from being TAKEN for a field identity afterwards — the var
        # itself is kept (its line, its expression, its edges are real), but
        # it is stamped as an auto-named fragment, so the write-side twin
        # pass (family 1) and every owner-qualified re-derivation skip it
        # exactly as they skip `CONCAT'price=',…`. `,` / `(` / `)` / space in
        # a field name are the fragment signature; `a.*` and the ⟐ sentinels
        # stay legal.
        if (var_type in (VariableType.COLUMN, VariableType.CTE_COLUMN)
                and _FIELD_FRAGMENT_CHARS.search(name)):
            self._auto_named_outputs.add(var.id)
        self.result.variables.append(var)
        # R20: count every column-type variable actually created.
        if var_type == VariableType.COLUMN:
            self._resolution_stats["total_columns"] += 1
        return var

    # ── R20 resolution stats (orphan coverage report) ────────────────

    def _attribute_output_containers(self) -> None:
        """B3 (v3.3.145): attribute walk outputs to their OWN container.

        The S1-S3 chains run inside the walks; a projection they could not
        resolve (a CTE body output over no single physical table, or an
        unaliased expression/bare column inside a subquery/derived body
        whose scope has no physical table) used to fall to L2's deleted
        context-string picker. The owner is extraction-time and exact:
        - a CTE body output column (CTE_COLUMN / case / aggregate …) in a
          bare "CTE{name}" context belongs to the CTE that defines it;
        - an is_output var of a subquery/derived-body walk belongs to the
          VIRTUAL_TABLE the walk itself created in the SAME context
          (⟐ subq1 / ⟐ accu/subq3 / ⟐ d — line-0 synthetic containers,
          never in highlights).
        Statement-level outputs (TOP{n} — no "/" and no ":join:") are
        untouched: their ambiguity rules are pinned by S3 (never guess).
        Table-like vars are never touched (they carry their own
        source_tables semantics). S2 expr_alias counts the attribution —
        these ARE expression/CTE-output attributions.
        """
        table_like = (VariableType.TABLE, VariableType.VIEW,
                      VariableType.CTE, VariableType.SUBQUERY,
                      VariableType.VIRTUAL_TABLE, VariableType.UNION_BRANCH,
                      VariableType.MERGE_TARGET, VariableType.FUNCTION_TABLE)
        ctx_to_vt: dict[str, str] = {}
        for v in self.result.variables:
            if v.variable_type == VariableType.VIRTUAL_TABLE:
                ctx_to_vt.setdefault(v.context or "TOP", v.name)
        for v in self.result.variables:
            if v.source_tables or v.variable_type in table_like:
                continue
            ctx = v.context or "TOP"
            if (ctx.startswith("CTE{") and "/" not in ctx
                    and ":join:" not in ctx):
                # E3a/4 (TPC-DS comma-join CTE): a bare column in a ≥2-table
                # scope (comma join) was stashed as an S4a schema candidate —
                # stamping it here would (a) mis-parent it under the CTE in
                # L2 and (b) block the S4a unique-owner post-pass and the
                # index-time S4b re-test (both require `not source_tables`).
                # Comma-join scope tables stay attribution candidates.
                if self._is_schema_candidate(v):
                    continue
                # CTE body output → the CTE that defines it
                end = ctx.find("}")
                if end > 4:
                    v.source_tables = [ctx[4:end]]
                    self._resolution_stats["resolved_by"]["expr_alias"] += 1
                continue
            if v.is_output and ("/" in ctx or ":join:" in ctx):
                # subquery/derived-body walk output → its own ⟐ container
                # (the output column OF the subquery — its own S2 container
                # attribution, pinned by test_m13_cache_attribution_
                # context_scoped: never a schema/scope attribution).
                container = ctx_to_vt.get(ctx)
                if container:
                    v.source_tables = [container]
                    self._resolution_stats["resolved_by"]["expr_alias"] += 1

    def _register_flow_occurrence_twins(self) -> None:
        """R44 (2026-08-28): register the missing OCCURRENCE-SIDE field
        instances so the strict table.field walker covers every
        dataflow-relevant occurrence of a searched field (user ruling:
        "covering all occurrences of the target field is the PURPOSE of
        flow-only"). Two twin families — both EXTRACTION-TIME facts of the
        SQL (never search-time reconstruction), both registered IN
        ADDITION to the existing vars (nothing is re-attributed):

        1. WRITE-SIDE twins (rename-writes, class 2/5): a DML statement's
           SELECT projection names a column of the WRITE TARGET
           (`p1.HTJE AS LOAN_AMT` writes bdm_acc_loan_info.LOAN_AMT;
           `A.Reserved_Field18 AS RESERVED_6` writes
           east5_stzfxxb.RESERVED_6), but the output var is attributed to
           the VALUE's read source (S1/I2), so the target's field entity
           never exists and a search for the target's column returns
           not-in-flow. For every is_output var of a statement that
           DML-writes table T whose attribution is not already T, register
           twin `{T}.{output alias}` attributed to T — same line, same
           context, is_output, carrying the projection's source_columns
           (so the rename REF edge anchors at the projection line).
        2. DERIVED-READ twins (reads through derived aliases, class 3/4):
           an outer read `p2.product` / `a.rn` / `p8.X5GMAB` is attributed
           to the derived alias; its tie to the underlying physical table
           (the derived body reads EXACTLY ONE physical table) is a fact
           of the SQL. For every non-output column var qualified by such
           an alias, register twin `{P}.{col}` attributed to P with
           source_columns=[the dotted read] — the copy REF edge then
           anchors at the read line and the physical table's field
           carries the occurrence.
        """
        # ── index 1: per-context DML write targets ──
        # R45 Fix E (2026-08-28.9): ALIAS occurrences are not write targets.
        # Both branches used to take every var's NAME, so an alias handle
        # (`MERGE INTO tgt_table tgt`, `UPDATE tgt t SET`) registered the
        # ALIAS spelling as a write target of its own — and family 1 then
        # minted `{alias}.{output}` fields on a table that does not exist
        # (`tgt_table.*`/`tgt.sid` from a projection that never names it).
        # An original carries an empty source_tables, or its own name (I2
        # self-attribution); an alias carries ANOTHER table's name.
        dml_targets_by_ctx: dict[str, list[str]] = {}
        for v in self.result.variables:
            st = v.source_tables or []
            if st and st[0].casefold() != v.name.casefold():
                continue
            if v.variable_type == VariableType.MERGE_TARGET:
                dml_targets_by_ctx.setdefault(v.context or "TOP",
                                              []).append(v.name)
            elif v.variable_type == VariableType.TABLE:
                di = (v.defined_in or "").upper()
                if any(kw in di for kw in ("INSERT", "UPDATE", "DELETE")):
                    dml_targets_by_ctx.setdefault(v.context or "TOP",
                                                  []).append(v.name)
        # R45 Fix E: the MERGE targets per context — a MERGE's written
        # columns are EXACTLY the ones its WHEN clauses name, so family 1's
        # projection-list rule (right for INSERT/UPDATE/DELETE, whose
        # projections are the write) over-mints for MERGE: the USING
        # subquery's projections are the SOURCE's reads, never the target's
        # write slots.
        merge_targets_by_ctx: dict[str, set[str]] = defaultdict(set)
        for v in self.result.variables:
            if v.variable_type != VariableType.MERGE_TARGET:
                continue
            st = v.source_tables or []
            if st and st[0].casefold() != v.name.casefold():
                continue
            merge_targets_by_ctx[v.context or "TOP"].add(v.name)

        # ── index 2: derived containers with exactly ONE physical source ──
        # A SUBQUERY/VIRTUAL_TABLE occurrence owns every physical read
        # whose context is inside its scope (its own context, or a
        # "/"-nested body scope — sibling ":join:" scopes of the same
        # parent never match the "/"-segment prefix).
        derived_single: dict[tuple[str, str], str] = {}
        subs_by_label: dict[str, list] = {}
        for s in self.result.variables:
            if s.variable_type in (VariableType.SUBQUERY,
                                   VariableType.VIRTUAL_TABLE):
                subs_by_label.setdefault(s.name, []).append(s)
        for label, subs in subs_by_label.items():
            for s in subs:
                sctx = s.context or ""
                phys = set()
                for t in self.result.variables:
                    if t.variable_type not in (VariableType.TABLE,
                                               VariableType.VIEW):
                        continue
                    # originals only — an alias carries st[0] = another
                    # table's name; a physical read may carry st[0] = its
                    # own name (I2 self-attribution) or none.
                    if (t.source_tables
                            and t.source_tables[0].casefold()
                            != t.name.casefold()):
                        continue
                    tctx = t.context or ""
                    if not (tctx == sctx or tctx.startswith(sctx + "/")
                            or tctx.startswith(sctx + ":")):
                        continue
                    # An EXISTS/NOT-EXISTS body under the derived scope is
                    # row-SELECTION, not a row source — its FROM reads do
                    # not make the derived table multi-source (PL's p2
                    # wraps bdm_fin_lrr_key_base_info and filters through
                    # `exists (select 1 from ODS_CDP_GDC_TABLE_COA_LIST …)`).
                    rel = tctx[len(sctx):].lstrip("/:")
                    segs = re.split(r"[/\:]", rel)
                    if any(sg.startswith("exists") for sg in segs if sg):
                        continue
                    phys.add(t.name)
                if len(phys) == 1:
                    # Determinism pin (2026-08-29): `next(iter(phys))` over a
                    # str set is hash-order-shaped even though the `len==1`
                    # guard makes it numerically safe today — a future edit
                    # that admits a second source would silently turn this
                    # into a per-process coin flip (PYTHONHASHSEED). `min()`
                    # is order-independent at any cardinality.
                    derived_single[(label, sctx)] = min(phys)

        # ── family 1: write-side twins ──
        for v in self.result.variables:
            if not v.is_output:
                continue
            if v.variable_type not in (VariableType.COLUMN,
                                       VariableType.CTE_COLUMN,
                                       VariableType.TRANSFORM,
                                       VariableType.CASE,
                                       VariableType.EXPRESSION,
                                       VariableType.AGGREGATE,
                                       VariableType.WINDOW,
                                       VariableType.LITERAL):
                continue
            vctx = v.context or ""
            targets = dml_targets_by_ctx.get(vctx)
            if not targets:
                continue
            alias = v.name.rsplit(".", 1)[-1] if "." in v.name else v.name
            if not alias:
                continue
            if v.id in self._auto_named_outputs:
                # L4 (part 2): the projection carries no alias, so its name
                # is an expression fragment (`CONCAT'price=',_p.price,_',st`,
                # `NULL`, `1`), not a column. The INSERT column list that
                # would name the write slot is NOT positionally recoverable
                # here — projection outputs do not register 1:1 in source
                # order (fin_query4_merge_upsert TOP1: an 11-item SELECT with
                # an 11-name column list registers 10 outputs, so an index
                # map would silently mis-name). Same ruling as the CTE/
                # derived output-column recording ("never resolvable output
                # names"): skip the twin rather than mint a bogus physical
                # field on the write target.
                continue
            for tname in targets:
                if (v.source_tables
                        and v.source_tables[0].casefold() == tname.casefold()):
                    continue  # already attributed to the write target
                # R45 Fix E: a MERGE writes only the columns its WHEN
                # clauses name. A projection of the USING subquery is the
                # SOURCE's read, not the target's write slot — minting
                # `{target}.{projection}` for it invented write-twins for
                # every source column (AD1's `t.*` phantom / `tgt_table.sid`
                # twin). INSERT/UPDATE/DELETE keep the projection-list
                # behavior: there the projection IS the write.
                if tname in merge_targets_by_ctx.get(vctx, set()):
                    if alias.casefold() not in self._merge_written.get(
                            vctx, set()):
                        continue
                # source_columns stays EMPTY on purpose: the twin is the
                # write slot, not a read — copying the projection's read
                # columns would let dependency_graph Phase 3's bare-name
                # fallback wire UNRELATED same-named reads onto the twin
                # across statements (DigL: data_dt@560 → DM_FLAG2 twin),
                # and Phase 1c would emit a second DML leg family. The
                # write occurrence renders through Phase 4c's OUTPUT SCHEMA
                # edge (anchor = the twin's own line) and the projection's
                # own edges.
                twin = self._add(
                    f"{tname}.{alias}", VariableType.COLUMN,
                    sql_expr=v.sql_expression,
                    defined_in=v.defined_in or "SELECT", context=vctx,
                    source_cols=[],
                    source_tables=[tname], is_output=True)
                if twin is not None:
                    # _add's text-search cannot find a synthetic dotted
                    # name — the twin anchors at the projection itself.
                    twin.line_start = v.line_start
                    twin.line_end = v.line_end

        # ── family 2: derived-read twins ──
        for v in self.result.variables:
            if v.variable_type != VariableType.COLUMN or v.is_output:
                continue
            if "." not in v.name or not v.source_tables:
                continue
            _q, _, col = v.name.partition(".")
            if not col:
                continue
            vctx = v.context or ""
            # M2: lexical visibility — the alias is usable from the read's
            # scope when the read sits inside (or on) the scope BINDING it.
            # The pre-M2 check compared the read against the SUB VAR's own
            # context, so it only ever matched the FROM/JOIN scope that
            # declares the alias and missed every deeper nested use
            # (`p2.col` inside a scalar subquery of that same FROM).
            # Matching on `_scope_top` instead would over-match: it folds
            # `CTE{x}:join:p2` and `TOP0:join:p2` onto one statement, so a
            # CTE-local derived `p2` would twin the statement-level JOIN
            # alias `p2` (SUP_M: p2.data_dt → ods_hub_lsacmsp.data_dt for a
            # read that is really bdm_acc_loan_info_sup). `_binding_scope`
            # keeps the CTE boundary and adds the nested-scope uses.
            best_bind = None
            best_phys = None
            for s in subs_by_label.get(_q, []):
                sctx = s.context or ""
                bind = _binding_scope(sctx, s.name)
                if not bind or not _ctx_within(vctx, bind):
                    continue  # the alias is not usable from the read's scope
                phys = derived_single.get((_q, sctx))
                if phys is None:
                    continue
                if phys.casefold() == v.source_tables[0].casefold():
                    continue
                # innermost binding wins — a nearer redeclaration of the
                # same alias shadows the outer one (standard SQL scoping).
                if best_phys is None or len(_ctx_segments(bind)) > len(best_bind):
                    best_bind, best_phys = _ctx_segments(bind), phys
            if best_phys is None:
                continue
            phys = best_phys
            twin = self._add(
                f"{phys}.{col}", VariableType.COLUMN,
                sql_expr=v.sql_expression,
                defined_in=v.defined_in or "SELECT", context=vctx,
                source_cols=[v.name],
                source_tables=[phys], is_output=False)
            if twin is not None:
                twin.line_start = v.line_start
                twin.line_end = v.line_end

        # ── family 3: occurrence-line twins (R45, 2026-08-28.6) ──
        # The (name, type, context) dedup in `_add` keeps ONE node per field
        # per scope, so the SECOND and later occurrences of that field inside
        # the same statement used to leave no node at all at their own line —
        # a multi-leg JOIN ON predicate anchored only its first leg, an NVL
        # fallback operand collapsed onto the bare read above it, a CASE's
        # 2nd WHEN arm collapsed onto the 1st, byte-identical projections
        # collapsed onto each other (class 5), and a predicate operand
        # collapsed onto the same field's projection in the parallel
        # derived-body copy. `_add` recorded each such collapsed occurrence;
        # re-anchor it here as an occurrence-side twin attributed to the SAME
        # owner the surviving var resolved to.
        #
        # Grouped per (context, casefolded field identity): the group's
        # surviving vars already hold the FIRST occurrence lines, so the
        # collapsed ones are handed the remaining textual occurrences in
        # stream order. Grouping — never a global cursor — is what keeps
        # every surviving anchor exactly where it was (a purely additive
        # change; no existing line can move).
        groups: dict[tuple[str, str], list[dict]] = {}
        for occ in self._collapsed_occurrences:
            ck = (occ["context"], _field_identity(occ["name"]))
            groups.setdefault(ck, []).append(occ)
        # R45 Fix C: the per-line scope map is shared by every group — one
        # pass over the recorded anchors, not one per group.
        innermost = self._scope_line_owner()
        # R45 Fix F: `taken` is computed ONCE, from the pre-twin variable
        # list, so the pass is order-independent. A line is taken when ANY
        # surviving COLUMN var of this FIELD (last dot-part, any qualifier
        # spelling) anchors it, not only one spelled exactly like the
        # occurrence: a group's occurrences are recorded under the walker's
        # spelling (`lending_ref`) while the surviving node may carry the
        # owner-qualified spelling (`bdm_acc_loan_info.lending_ref`, the
        # GROUP BY occurrence @59) — comparing spellings made the
        # already-anchored line look free, and the group's DUPLICATE
        # registration of that same occurrence grabbed another line further
        # down (the @41 filter/JOIN pair) as its "own".
        field_lines: dict[tuple[str, str], set[int]] = {}
        for v in self.result.variables:
            if (v.variable_type != VariableType.COLUMN or not v.line_start):
                continue
            key = (v.context or "",
                   v.name.rsplit(".", 1)[-1].casefold())
            field_lines.setdefault(key, set()).add(v.line_start)
        for (context, ident), occs in groups.items():
            base = self._base_var_for(ident, context)
            if base is None or not base.line_start:
                continue
            taken = field_lines.get((context,
                                     ident.rsplit(".", 1)[-1].casefold()),
                                    set())
            lines = self._occurrence_lines(base.name, context, taken,
                                           innermost)
            if not lines:
                continue
            # ── R45 Fix E: pair occurrences to lines by CLAUSE, not by raw
            # stream order. `_add` records collapses in WALK order (clauses
            # are walked SELECT → FROM → WHERE → …, and a nested body is
            # walked mid-clause), while `lines` is textual. Zipping the two
            # hands an occurrence the line of a DIFFERENT one whenever the
            # group mixes clauses: the rollover CTE's `lending_ref IN (...)`
            # predicate (WHERE) is the 2nd textual occurrence but the FIRST
            # collapsed record is the projection's own duplicate
            # registration, so the predicate's twin landed on the subquery
            # projection line and the real predicate line got nothing. An
            # occurrence whose `defined_in` names a clause takes the first
            # free line OF THAT CLAUSE; only clause-less occurrences (and
            # occurrences whose clause has no free line left) fall back to
            # stream order.
            anchor = self._stmt_anchor_for(context)
            clause_by_line = self._line_clauses(anchor, lines[-1] + 1)
            free_by_clause: dict[str, list[int]] = {}
            for ln in lines:
                free_by_clause.setdefault(clause_by_line.get(ln, ""),
                                          []).append(ln)
            used: set[int] = set()
            assigned: dict[int, int] = {}
            leftover: list[dict] = []
            for occ in occs:
                clause = _occurrence_clause(occ["defined_in"])
                bucket = free_by_clause.get(clause, []) if clause else []
                pick = next((ln for ln in bucket if ln not in used), None)
                if pick is None:
                    leftover.append(occ)
                else:
                    used.add(pick)
                    assigned[id(occ)] = pick
            if leftover:
                free = [ln for ln in lines if ln not in used]
                for occ in leftover:
                    if not free:
                        break
                    pick = free.pop(0)
                    used.add(pick)
                    assigned[id(occ)] = pick
            for occ in occs:
                line = assigned.get(id(occ))
                if line is not None:
                    self._mint_occurrence_twin(base, line,
                                               occ["defined_in"],
                                               clause_by_line)

    def _base_var_for(self, ident: str,
                      context: str) -> VariableDefinition | None:
        """The surviving node a collapsed occurrence group belongs to.

        R45 Fix D: the group identity is the occurrence's own qualified
        spelling (`p1.charge_department`), so the surviving var that shares
        it EXACTLY (casefolded) is the one whose owner the twin inherits.
        Only when no surviving var carries that spelling do we fall back to
        the last dot-part: I2 rewrites a column's name to OWNER-qualified
        spelling (`bdm_acc_loan_info.lending_ref`), so the surviving var may
        spell the qualifier differently than the occurrence's alias.

        Matching on the last dot-part alone (the pre-Fix-D behavior) made
        every same-field group in a scope resolve to the FIRST surviving
        var with that field part — for SUP_M's INSERT the PARTITION column
        `CHARGE_DEPARTMENT` @160 (owner bdm_acc_loan_info_sup) precedes the
        projections, so both `p1.charge_department` groups (@182/@196, p1 =
        loan_final) minted twins owned by the write target. A same-named
        field of two tables in one scope is two different occurrences of
        two different columns; the qualifier is the only thing that tells
        them apart.
        """
        for v in self.result.variables:
            if v.context != context or v.variable_type != VariableType.COLUMN:
                continue
            if v.name.casefold() == ident:
                return v
        col_id = ident.rsplit(".", 1)[-1]
        for v in self.result.variables:
            if v.context != context or v.variable_type != VariableType.COLUMN:
                continue
            if v.name.rsplit(".", 1)[-1].casefold() == col_id:
                return v
        return None

    def _mint_occurrence_twin(self, base: VariableDefinition, line: int,
                              defined_in: str,
                              clause_by_line: dict[int, str] | None = None
                              ) -> None:
        """Register one occurrence-side twin at `line`.

        Mirrors the R44 families: same owner, same context, not an output
        (the twin is the occurrence side — a genuinely projected var keeps
        its own output var), carrying a source_columns entry so
        dependency_graph wires the copy/READ edge at the twin's line. `_add`
        is bypassed deliberately: the twin is a SECOND node for a (name,
        type, context) that already exists, which is the whole point.

        R45 Fix B (2026-08-28.9): the stamped clause is the LINE's clause —
        `clause_by_line` (the group's `_line_clauses` map) names the clause
        the twin's own line belongs to, spelled through
        `_LINE_CLAUSE_TO_DEFINED_IN` (the walker's spelling: raw `on` must
        become `JOIN ON`, or Phase 6/6b's `{"JOIN ON"}` gate would never
        see it). The COLLAPSED occurrence's clause was only ever a group
        fact — `_add` records collapses in walk order while the line
        handout is textual, so the two could be crossed (F-E1). A line with
        no clause at all (a context-shaped anchor line) falls back to the
        collapsed occurrence's clause, exactly as before.
        """
        if not base.source_tables:
            return  # never guess an owner
        owner = base.source_tables[0]
        if not owner or owner.startswith(OTHER_SENTINEL):
            return
        col = base.name.rsplit(".", 1)[-1] if "." in base.name else base.name
        if not col:
            return
        twin_id = self._next_id(f"{base.context}:{base.name}@{line}")
        # `defined_in` carries the OCCURRENCE marker so dependency_graph can
        # (a) give the twin its structural belongs-to SCHEMA edge (the Phase
        # 4d-gb precedent — without it the twin trips column_connectivity)
        # and (b) still see the clause the occurrence was collected in for
        # FILTER/JOIN typing (`_clause_of` strips the marker there).
        line_clause = _LINE_CLAUSE_TO_DEFINED_IN.get(
            (clause_by_line or {}).get(line, ""))
        if line_clause:
            clause = line_clause
        else:
            clause = (defined_in or base.defined_in or "").strip()
        self.result.variables.append(VariableDefinition(
            id=twin_id, name=f"{owner}.{col}",
            variable_type=VariableType.COLUMN,
            sql_expression=base.sql_expression,
            # source_columns stays EMPTY on purpose — the family-1
            # precedent: the twin is the occurrence slot, not a read.
            # Copying the base read's column would let dependency_graph
            # Phase 3's bare-name fallback wire UNRELATED same-named reads
            # onto the twin across statements (the SUP_M `charge_department`
            # walker-closure widening). The twin's own edges come from
            # Phase 4d (READ to its owner), Phase 4d-gb (belongs-to SCHEMA)
            # and Phase 6/6b (FILTER/JOIN, by the clause it was collected
            # in).
            source_cols=[],
            source_tables=[owner],
            defined_in=f"OCCURRENCE {clause}".strip(),
            context=base.context,
            line_start=line, line_end=line,
            is_output=False,
        ))
        self._resolution_stats["total_columns"] += 1

    def _canonicalize_table_names(self) -> None:
        """ISSUE-4: fold physical-table spelling to one canonical form.

        Physical-table identity is script-global and case-insensitive; the
        canonical spelling is the majority spelling of the identifier tokens
        in the source (ties → lowercase, then first-seen). Only the physical
        table name (+ qualified field) is a global identifier, so ONLY that
        namespace is folded here — alias/CTE/derived handles are scope-local
        and are NEVER canonicalized (their case variants are within-scope
        equivalents resolved by `_resolve_alias` M3a).

        Rewrites:
          - table/view/merge_target var `name` (the global node label)
          - every var's `source_tables` entries (physical-table attribution)
          - the qualifier of a qualified column var `name` (part before the
            first `.`) when that qualifier is a physical table name — never
            an alias handle (alias spelling is scope-local, not global)
          - `_script_schemas` keys (canonical schema evidence, merged)
          - `_schema_candidates[].visible_tables`
        """
        table_like = (VariableType.TABLE, VariableType.VIEW,
                      VariableType.MERGE_TARGET, VariableType.FUNCTION_TABLE)
        for v in self.result.variables:
            # 1. table-like var name → canonical physical spelling. Skip
            # alias handles: an alias is a scope-local handle (is_alias_handle
            # R-1), never a physical table — even when its spelling
            # case-collides with a physical name elsewhere (e.g. `FROM
            # EAST5_STZFXXB AS east5_stzfxxb` must keep the alias's own case,
            # not fold to the physical majority spelling). CTE/derived handles
            # are already excluded by the `table_like` filter (CTE/SUBQUERY
            # types).
            if (v.variable_type in table_like
                    and not v.is_alias_handle
                    and (v.name or "").casefold() in self._physical_table_names):
                v.name = self._canonical_spelling(v.name)
            # 2. source_tables entries — M-E3: only canonicalize entries that
            # are KNOWN PHYSICAL for this var's scope. A local CTE / derived
            # alias whose casefold collides with a physical table elsewhere
            # must NOT be relabeled to the physical canonical spelling (CTE/
            # derived handles are scope-local and never canonicalized).
            if v.source_tables:
                v.source_tables = [
                    self._canonical_spelling(t)
                    if (t.casefold() in self._physical_table_names
                        and not self._is_cte_name(t, v.context)
                        and not self._is_derived_alias(t, v.context))
                    else t
                    for t in v.source_tables
                ]
            # 3. qualified column var name qualifier — M-E3b: only fold a
            # qualifier that is a KNOWN PHYSICAL table in this var's scope.
            # A scope-local alias/CTE/derived qualifier whose casefold
            # collides with a physical table elsewhere must NOT be relabeled
            # (`SELECT a.x FROM t1 a; SELECT * FROM A;` must keep `a.x`, not
            # fold it to `A.x`) — mirror of step 2's guard, plus the alias
            # registry (aliases are already resolved out of source_tables).
            if v.variable_type == VariableType.COLUMN and "." in (v.name or ""):
                qual, _, col = (v.name or "").partition(".")
                if (qual.casefold() in self._physical_table_names
                        and not self._is_cte_name(qual, v.context)
                        and not self._is_derived_alias(qual, v.context)
                        and not self._is_alias_name(qual, v.context)):
                    v.name = f"{self._canonical_spelling(qual)}.{col}"
        # 4. script_schemas keys (merge case-folded duplicates, first-wins)
        merged: dict[str, dict] = {}
        for table, cols in self._script_schemas.items():
            canon = (self._canonical_spelling(table)
                     if table.casefold() in self._physical_table_names
                     else table)
            target = merged.setdefault(canon, {})
            for col, line in cols.items():
                target.setdefault(col, line)
        self._script_schemas = merged
        # 5. schema_candidates visible_tables
        for cand in self._schema_candidates:
            cand["visible_tables"] = [
                self._canonical_spelling(t)
                if t.casefold() in self._physical_table_names else t
                for t in cand.get("visible_tables", [])
            ]

    def _is_schema_candidate(self, v) -> bool:
        """E3a/4: is this var a still-unresolved S4a schema candidate?

        The candidate stash records (field, visible_tables, contexts) —
        exact name + context membership, case-insensitive field compare
        (the stash and _finalize_schema_candidates both compare names
        case-insensitively; R4 whole-name equality).
        """
        for cand in self._schema_candidates:
            if (cand["field"].lower() == (v.name or "").lower()
                    and v.context in cand.get("contexts", [])):
                return True
        return False

    def build_resolution_stats(self) -> dict:
        """Final resolution_stats for this script.

        unresolved = names of column-type vars (VariableType.COLUMN) that
        still have no table attribution after S1–S3 — no source_tables, no
        qualifier prefix — excluding S5 (⟐system) and S6 (pseudocolumn)
        marked-expected entries. Names are deduped, creation order kept.

        A name counts as unresolved only if NO COLUMN var with that name
        carries attribution: subquery-interior columns are registered ONCE,
        in their own subquery-scope context (the raw walk prunes re-descent
        into explicitly walked Select bodies — no phantom outer-context
        copies since v3.3.140).

        C4a (R20 contract unification): additionally emits `resolved`
        (total − unresolved), `unresolved_count`, `coverage_pct`
        (one-decimal, None @ 0 columns) — additive, old readers unaffected.
        """
        # S4a (Phase 2): unique-owner post-pass over the stashed candidates.
        # Unique-owner candidates are AUTO-attributed (source_tables set,
        # resolved_by["schema"] += 1, removed from schema_candidates); R6
        # collisions are counted; ambiguous/evidence-absent candidates stay.
        # A3: the S3-side R6 count (field == visible table name in a
        # single-table scope, accumulated during the walk) is summed with
        # the S4 candidates' own collisions — same per-script counter.
        r6 = (self._finalize_schema_candidates()
              + self._resolution_stats["r6_collision"])
        stats = {
            "total_columns": self._resolution_stats["total_columns"],
            "resolved_by": dict(self._resolution_stats["resolved_by"]),
            "unresolved": [],
            "schema_candidates": self._schema_candidates,
            "r6_collision": r6,
            # {table: {col: evidence_line}} — first occurrence wins
            "script_schemas": {t: dict(cols)
                               for t, cols in self._script_schemas.items()},
        }
        attributed = {v.name for v in self.result.variables
                      if v.variable_type == VariableType.COLUMN
                      and ("." in v.name or v.source_tables)}
        seen = set()
        for v in self.result.variables:
            if v.variable_type != VariableType.COLUMN:
                continue
            if v.name in attributed:
                continue  # prefix-attributed or resolved by S1/S2/S3/S5/S6
            if v.name in seen:
                continue
            seen.add(v.name)
            stats["unresolved"].append(v.name)
        # C4a (R20 contract unification): emit the index-aggregate shapes
        # ADDITIVELY — nothing existing is removed, and the frontend shim's
        # derivation becomes a no-op for new analyses. `resolved` is exactly
        # total − unresolved (the shim's math); coverage_pct is one-decimal
        # (Math.round((1 − unresolved/total) * 1000) / 10); None when no
        # columns were seen (matches the shim's "—" display).
        stats["resolved"] = stats["total_columns"] - len(stats["unresolved"])
        stats["unresolved_count"] = len(stats["unresolved"])
        total = stats["total_columns"]
        stats["coverage_pct"] = (
            round(100.0 * (1 - len(stats["unresolved"]) / total), 1)
            if total > 0 else None)
        return stats

    # ── Top-level dispatch ──────────────────────────────────────────

    def process_statement(self, stmt: exp.Expression, context: str,
                          outer: _SelectScope | None = None,
                          merged_select: exp.Select | exp.Union
                          | exp.Intersect | exp.Except | None = None):
        """Process a top-level statement, dispatching to walkers.

        `outer` (R29/ISSUE-4 outer-chain) is the enclosing scope when this
        statement is nested (a subquery/exists/derived body, or a Hive
        FROM-led multi-insert arm) — its own scope links back to it so
        correlated references resolve outward.

        `merged_select` (R44 F1): the following standalone SELECT when this
        INSERT is a bare `INSERT OVERWRITE TABLE t PARTITION(...);` — the
        ODPS idiom's write source. Passed through to _walk_insert, which
        walks it under this statement's own context INSTEAD of creating the
        ⟐ insert VT (two VTs in one context would starve dependency_graph
        Phase 1c-extra2's single-output-VT write leg).
        """
        # Process any WITH clause first (can appear on any statement type)
        with_clause = stmt.args.get("with") or stmt.args.get("with_")
        if with_clause:
            self._walk_cte_definitions(with_clause, context=context)

        # sqlglot wraps queries with complex table names in a With node
        if isinstance(stmt, exp.With):
            self._walk_cte_definitions(stmt, context=context)
            inner = stmt.this
            if inner:
                self.process_statement(inner, context, outer=outer)
            return

        if isinstance(stmt, exp.Select):
            self._walk_select(stmt, context, is_cte=False, outer=outer)
        elif isinstance(stmt, exp.Union):
            self._walk_setop(stmt, "UNION", context, outer=outer)
        elif isinstance(stmt, exp.Intersect):
            self._walk_setop(stmt, "INTERSECT", context, outer=outer)
        elif isinstance(stmt, exp.Except):
            self._walk_setop(stmt, "EXCEPT", context, outer=outer)
        elif isinstance(stmt, exp.Merge):
            self._walk_merge(stmt, context, outer=outer)
        elif isinstance(stmt, exp.Update):
            self._walk_update(stmt, context, outer=outer)
        elif isinstance(stmt, exp.Insert):
            self._walk_insert(stmt, context, outer=outer,
                              merged_select=merged_select)
        elif isinstance(stmt, exp.Create):
            self._walk_create(stmt, context)
        else:
            self._walk_select(stmt, context, is_cte=False, outer=outer)  # try generic SELECT walk

    # ── CTE definitions ─────────────────────────────────────────────

    def _walk_cte_definitions(self, with_clause, context: str = "TOP"):
        """Extract CTE table names from a WITH clause.

        `context` is the ENCLOSING statement's context (C-9: "TOP0", "TOP1",
        or a set-op branch context like "TOP0/union1"). The CTE table
        variable lives in that statement scope — dependency_graph's Phase 1a
        CTE→VT-anchor lookup keys on the CTE var's context, and the
        statement's VIRTUAL_TABLE carries the same context, so the two must
        agree (a hardcoded "TOP" would orphan every CTE once statements are
        statement-indexed).
        """
        cte_list = []
        if hasattr(with_clause, 'expressions'):
            cte_list = with_clause.expressions
        elif isinstance(with_clause, exp.CTE):
            cte_list = [with_clause]

        for cte_def in cte_list:
            if not isinstance(cte_def, exp.CTE):
                continue
            alias = _clean(getattr(cte_def, 'alias_or_name', '') or '')
            if not alias:
                continue
            # ISSUE-4: CTE names are statement-local — record under the
            # enclosing top-level statement scope, and remember the CTE body
            # context so references inside the body resolve to this scope.
            cte_scope = self._scope_top(context)
            self._cte_names.setdefault(cte_scope, set()).add(alias.casefold())
            self._cte_enclosing[f"CTE{{{alias}}}"] = cte_scope

            # CTE table variable (scoped to the enclosing statement — C-9).
            # I1 def site: the CTE name token followed by AS then '(' —
            # self-identifying, so repeated table names elsewhere can never
            # steal the line ("src_x" at L13 / "mid" at L18).
            self._add(alias, VariableType.CTE,
                      sql_expr=_sql(cte_def),
                      defined_in=f"CTE{{{alias}}}", context=context,
                      def_site=([[alias, "as", "("]], None, context))

            # Walk the inner query to extract columns
            inner = cte_def.this
            if isinstance(inner, exp.Select):
                self._walk_select(inner, f"CTE{{{alias}}}", is_cte=True,
                                  cte_name=alias)
            elif isinstance(inner, (exp.Union, exp.Intersect, exp.Except)):
                # fin_query8: a UNION-derived CTE (positions) — thread the
                # CTE name into the set-op walk so each branch's outputs are
                # recorded as the CTE's output columns (S2 downstream refs).
                self._walk_setop(inner, type(inner).__name__.upper(),
                                 f"CTE{{{alias}}}", cte_name=alias)

    # ── SELECT walker (the core) ────────────────────────────────────

    def _walk_select(self, select: exp.Select, context: str, is_cte: bool = False,
                     derived_alias: str | None = None,
                     cte_name: str | None = None,
                     setop_body: bool = False,
                     outer: _SelectScope | None = None):
        """Walk a SELECT/UPDATE/DELETE and classify every Identifier found.

        `derived_alias` (Fix C) is set when this SELECT is the body of an
        aliased derived table (FROM (SELECT ...) AS d) — its projections'
        output names are recorded for downstream bare-column resolution.
        `cte_name` (S2) is the CTE whose body this SELECT is (explicit —
        otherwise derived from the CTE{…} context).
        `setop_body` marks a UNION/INTERSECT/EXCEPT branch: per-branch
        source tables differ, so two-hop output attribution is suppressed
        (q71 — one-hop to the derived alias only, never a guess).
        """
        # D-series: record this statement's first-token line BEFORE scope
        # creation so every var registered under `context` scopes its line
        # lookup to [this anchor, next anchor).
        self._record_stmt_anchor(context, select)
        # R20: per-statement scope — tables/aliases/CTEs this statement sees.
        scope = _SelectScope(owner=select, key=context, outer=outer)
        output_container = None  # what expression outputs attribute to (S2)
        # `cte_name` comes in as a parameter (set-op CTE bodies thread it
        # through _walk_setop); only the is_cte context fallback may assign.
        # Create a VIRTUAL_TABLE for this SELECT's output.
        # Exception: inside a CTE, the CTE node itself serves as the output
        # container — no separate VT needed. The CTE IS the named result set.
        if not is_cte:
            # CTE{t} → label=t, TOP/subq1 → label=subq1, TOP → label=output
            # B5: the context is a PATH ("CTE{loan_final}:join:accu",
            # "CTE{loan_final}/subq1") — take only the terminal segment
            # (CTE name / subquery number / derived-table alias), never the
            # whole remainder (context[4:-1] grabbed the rest of the path
            # and produced labels like "⟐ loan_final}:join:accu").
            if context.startswith("CTE{") and "/" not in context and ":" not in context:
                label = context[4:context.index("}")]  # extract name between { }
            elif ":join:" in context:
                label = context.rsplit(":", 1)[-1]  # derived-table alias (p2, accu, …)
            elif "/" in context:
                label = context.rsplit("/", 1)[-1]
            else:
                label = "output"
            vt_name = f"⟐ {label}"
            # W6: the synthetic-source VT carries its CREATION line. The
            # name ("⟐ output") never occurs in the source, so the plain
            # name-run resolution could never match — the def_site run
            # comes from the statement itself:
            #  - statement-level (TOP contexts): the statement HEAD run of
            #    the DML-clause node (INSERT OVERWRITE … at 160 — never
            #    the WITH or the SELECT body), anchored on that node;
            #  - subquery/derived-body: the body's own FIRST output token
            #    (first projection rendered, e.g. lending_ref@22/26),
            #    fallback the body's SELECT head — the creation line is
            #    where the body's output begins, not the SELECT keyword.
            p = select.parent
            if "/" not in context and ":join:" not in context \
                    and isinstance(p, (exp.Insert, exp.Create, exp.Merge,
                                       exp.Update, exp.Delete)):
                node = p
                head_run = _statement_head_run(p)
                # Second run: the DML keyword pair only (head_run[:2]) as
                # the whole-stream fallback — renders drop keywords the
                # source keeps ("INSERT INTO TABLE t" renders "insert into
                # t", so the full head never matches the stream and the
                # statement anchor degrades to the SELECT's line, pushing
                # the DML keyword line 211 out of scope).
                runs = [head_run, head_run[:2]]
            elif "/" not in context and ":join:" not in context:
                node = select
                head_run = _statement_head_run(select)
                runs = [head_run, head_run[:2]]
            else:
                node = select
                head_run = _statement_head_run(select)
                proj_run = []
                exprs = select.expressions or []
                if exprs:
                    proj_run = _statement_head_run(exprs[0])
                runs = ([proj_run, head_run] if proj_run else [head_run])
            vt_var = self._add(vt_name, VariableType.VIRTUAL_TABLE,
                               sql_expr=_sql(select),
                               defined_in=context, context=context,
                               def_site=(runs, node, context))
            # E5 (audit item 1): a ⟐ VT whose def-site resolution came up
            # empty (line 0 — the render-head runs fail when sqlglot
            # canonicalizes tokens: substr→SUBSTRING, TSQL brackets/TOP,
            # probed on samples/tpcds/q62/q85/q99/q51/q8 + tsql_top_nolock)
            # falls back to the statement's SELECT-keyword line (I1 token
            # stream only). NEVER touches a valid line — the flagship's
            # output@160/211 are baked into the ground-truth doc.
            if vt_var is not None and vt_var.line_start < 1:
                fl = self._vt_fallback_line(select, context)
                if fl > 0:
                    vt_var.line_start = fl
                    vt_var.line_end = fl
            output_container = vt_name
            # E3a/3: when this SELECT is the source of an INSERT, its
            # expression outputs attribute to the INSERT TARGET table (the
            # DML statement defines them — COUNT(1) AS total_rows in
            # INSERT INTO TABLE rrcdm_job_log_exec_par(…) is a column of
            # rrcdm_job_log_exec_par, never of the synthetic ⟐ output
            # container). The ⟐ VT is still created (DML edges route
            # through it) — only the S2 output attribution moves.
            if isinstance(p, exp.Insert):
                into = p.args.get("into") or p.args.get("this")
                if isinstance(into, exp.Schema):
                    into = into.this
                if isinstance(into, exp.Table):
                    tname = _clean(into.name or "")
                    if tname:
                        output_container = tname
        else:
            if cte_name is None:
                cte_name = context[4:-1] if context.startswith("CTE{") else context

        # Detect statement type for DML marking
        stmt_type = type(select).__name__.upper()
        dml_mark = ""
        if stmt_type in ("UPDATE", "DELETE"):
            dml_mark = stmt_type

        # Main table (UPDATE/DELETE use 'this', SELECT uses 'from')
        main_table = select.args.get("this")
        if main_table and isinstance(main_table, exp.Table):
            self._register_table(main_table, context, dml=dml_mark, scope=scope)
            # S4a source 2: UPDATE t SET a=… — SET targets are canonical
            # schema evidence for t. EVIDENCE ONLY — the SET columns are
            # still registered as ordinary column vars downstream (existing
            # behavior); no new vars are created here.
            if dml_mark == "UPDATE":
                target_name = _clean(main_table.name or "")
                if target_name:
                    stmt_line = self._statement_anchor(select)
                    for e in (select.expressions or []):
                        if (isinstance(e, _UPDATE_SET_NODES)
                                and isinstance(e.this, exp.Column)):
                            cname = _clean(e.this.name or "")
                            if cname:
                                self._script_schemas.setdefault(
                                    target_name, {}).setdefault(cname, stmt_line)

        # FROM clause — table names and aliases
        from_exp = select.args.get("from") or select.args.get("from_")
        if from_exp:
            self._walk_from(from_exp, context, scope)

        # JOIN clauses
        for join in (select.args.get("joins") or []):
            self._walk_join(join, context, scope)

        # Task B: SELECT-level LATERAL VIEW (hive) — `LATERAL VIEW
        # explode(t.arr) x AS c2` lives in select.args["laterals"], never
        # in joins. Register the alias var (base = the physical table
        # behind the exploded array column) so Phase 1a emits the read
        # edge; the exploded column refs inside the lateral body walk
        # through the normal expression walker downstream.
        for lateral in (select.args.get("laterals") or []):
            self._register_lateral_alias(lateral, context, scope)

        # USING clause (DELETE ... USING / MERGE USING)
        using_tables = select.args.get("using") or []
        if isinstance(using_tables, exp.Expression):
            using_tables = [using_tables]
        for ut in using_tables:
            if isinstance(ut, exp.Table):
                self._register_table(ut, context, scope=scope)
            elif isinstance(ut, exp.Subquery):
                sub_alias = _clean(ut.alias or "")
                if sub_alias:
                    self._derived_aliases.setdefault(
                        self._scope_top(context), set()).add(sub_alias.casefold())
                    # I1 def site: the alias identifier right after ')'
                    self._add(sub_alias, VariableType.SUBQUERY,
                              sql_expr=_sql(ut.this),
                              defined_in="USING", context=context,
                              def_site=([[")", sub_alias]], scope.owner
                                        if scope is not None else None, context))
                if isinstance(ut.this, exp.Select):
                    self._walk_select(ut.this, context, is_cte=False, outer=scope)

        # SELECT expressions — process FIRST so aggregates are registered
        # before HAVING/ORDER BY references are encountered
        raw_exprs = select.expressions or []
        for expr in raw_exprs:
            self._walk_select_expression(expr, context, is_cte,
                                         scope=scope,
                                         output_container=output_container,
                                         cte_name=cte_name,
                                         derived_alias=derived_alias,
                                         setop_body=setop_body)

        # WHERE / HAVING conditions — after SELECT so bare refs dedup against aggregates
        for key in ("where", "having"):
            cond = select.args.get(key)
            if cond:
                self._walk_columns_in_expr(cond, context, defined_in=key.upper(), scope=scope)

        # GROUP BY / ORDER BY — column references
        for key, label in [("group", "GROUP BY"), ("order", "ORDER BY")]:
            clause = select.args.get(key)
            if clause:
                for e in (clause.expressions if hasattr(clause, 'expressions') else [clause]):
                    self._walk_columns_in_expr(e, context, defined_in=label, scope=scope)
                    # #387 (2026-08-28, R44 family 3): GROUP BY item
                    # occurrences get their own occurrence-side twin vars
                    # (see _register_groupby_twins) — ORDER BY stays on the
                    # historical path (presentation ordering, not a row
                    # grouping; not part of the ruling's anchor set).
                    if key == "group":
                        self._register_groupby_twins(e, context, scope)

        # SELECT INTO — creates a new table from the SELECT result
        into = select.args.get("into")
        if into:
            into_table = into.this if isinstance(into, exp.Into) else into
            if isinstance(into_table, exp.Table):
                into_name = _clean(into_table.name or "")
                if into_name:
                    # I1 def site: the name token after the INTO keyword
                    # (SELECT ... INTO tgt — the target is textually last)
                    self._add(into_name, VariableType.TABLE,
                              sql_expr=f"SELECT INTO {into_name}",
                              defined_in="SELECT INTO", context=context,
                              def_site=([["into", into_name], [into_name]],
                                        select, context))

    # ── FROM / JOIN walkers ─────────────────────────────────────────

    def _walk_from(self, from_exp, context: str, scope: _SelectScope | None = None):
        """Extract table references from a FROM clause."""
        # Unwrap From wrapper
        if isinstance(from_exp, exp.From):
            from_exp = from_exp.this
        if isinstance(from_exp, exp.Table):
            self._register_table(from_exp, context, scope=scope)
        elif isinstance(from_exp, exp.Subquery):
            # FROM (SELECT ...) AS alias — register alias as subquery type
            sub_alias = _clean(from_exp.alias or "")
            sub_ctx = f"{context}/subq/{sub_alias}" if sub_alias else f"{context}/subq"
            if sub_alias:
                self._derived_aliases.setdefault(
                    self._scope_top(context), set()).add(sub_alias.casefold())
                # I1 def site: the alias identifier right after ')'; anchored
                # on the ENCLOSING statement (scope.owner), never on the
                # subquery's own head (a duplicate body head can match the
                # whole-stream anchor scan and pull the line out of range).
                self._add(sub_alias, VariableType.SUBQUERY,
                          sql_expr=_sql(from_exp.this),
                          defined_in=f"FROM:{context}", context=sub_ctx,
                          def_site=([[")", sub_alias]], scope.owner
                                    if scope is not None else None, context))
            if isinstance(from_exp.this, exp.Select):
                self._walk_select(from_exp.this, sub_ctx, is_cte=False,
                                  derived_alias=sub_alias or None,
                                  outer=scope)
            elif isinstance(from_exp.this, (exp.Union, exp.Intersect, exp.Except)):
                # set-op derived table in FROM — thread the derived alias so
                # branch outputs are recorded (Fix C, one-hop only).
                self._walk_setop(from_exp.this, type(from_exp.this).__name__.upper(),
                                 sub_ctx, derived_alias=sub_alias or None,
                                 outer=scope)
            # Fix C: the derived alias is visible to the enclosing scope —
            # bare columns matching its output columns resolve via S2.
            if sub_alias and scope is not None:
                scope.deriveds.append(sub_alias)
        elif isinstance(from_exp, exp.Values):
            # Task B: FROM (VALUES ...) v(c1) — register the alias (base =
            # the synthetic VALUES table) so Phase 1a emits its read edge.
            self._register_values_alias(from_exp, context, scope)
        elif isinstance(from_exp, exp.Unnest):
            # Task B: FROM UNNEST(arr) AS u(c2) — alias base = synthetic
            # UNNEST table (duckdb/bigquery style, same registration).
            self._register_unnest_alias(from_exp, context, scope)

    def _walk_join(self, join, context: str, scope: _SelectScope | None = None):
        """Extract from a JOIN clause (including LATERAL)."""
        join_expr = join.this
        lateral_alias = None

        # Unwrap Lateral
        if isinstance(join_expr, exp.Lateral):
            lateral_alias = _clean(join_expr.alias_or_name or join_expr.alias or "")
            join_expr = join_expr.this

        if isinstance(join_expr, exp.Table):
            # Register JOIN tables with "JOIN" prefix in defined_in
            self._register_table(join_expr, context, join_table=True, scope=scope)
        elif isinstance(join_expr, exp.Subquery):
            # JOIN (SELECT ...) AS alias
            sub_alias = _clean(join_expr.alias or lateral_alias or "")
            sub_ctx = f"{context}:join:{sub_alias}" if sub_alias else f"{context}:join_subq"
            if sub_alias:
                self._derived_aliases.setdefault(
                    self._scope_top(context), set()).add(sub_alias.casefold())
                # I1 def site: ') alias' — anchored on the enclosing
                # statement (scope.owner): the loan_final ") p2" must land
                # on 116, never on the rollover subq's duplicate ") p2" at
                # 40 (that one anchors inside its own subq body).
                self._add(sub_alias, VariableType.SUBQUERY,
                          sql_expr=_sql(join_expr.this),
                          defined_in=f"JOIN:{context}", context=sub_ctx,
                          def_site=([[")", sub_alias]], scope.owner
                                    if scope is not None else None, context))
            if isinstance(join_expr.this, exp.Select):
                self._walk_select(join_expr.this, sub_ctx, is_cte=False,
                                  derived_alias=sub_alias or None,
                                  outer=scope)
            elif isinstance(join_expr.this, (exp.Union, exp.Intersect, exp.Except)):
                # q71 root cause: `FROM item, (SELECT … UNION ALL SELECT …)
                # tmp, time_dim` parses as CROSS JOINS — the set-op derived
                # table lands in `joins`. The Subquery branch only handled
                # exp.Select bodies, so the union body was NEVER walked and
                # _derived_output_columns["tmp"] was never populated.
                # Thread the derived alias so branch outputs are recorded
                # (Fix C, one-hop only — per-branch sources differ).
                self._walk_setop(join_expr.this, type(join_expr.this).__name__.upper(),
                                 sub_ctx, derived_alias=sub_alias or None,
                                 outer=scope)
            # Fix C: the derived alias is visible to the enclosing scope.
            if sub_alias and scope is not None:
                scope.deriveds.append(sub_alias)
        elif isinstance(join_expr, exp.Unnest):
            # Task B: CROSS JOIN UNNEST(t.arr) AS u(c2) — alias base =
            # the synthetic UNNEST table (hive/spark/duckdb). A LATERAL
            # UNNEST unwraps to the same exp.Unnest — the alias then sits
            # on the LATERAL wrapper, so lateral_alias falls back in.
            self._register_unnest_alias(join_expr, context, scope,
                                        defined_in="JOIN",
                                        alias_override=lateral_alias or "")
        elif isinstance(join_expr, exp.Values):
            # Task B: JOIN (VALUES ...) v(c1) — the VALUES-with-alias
            # construct in JOIN position, same registration as FROM
            # (alias base = the synthetic VALUES table). sqlglot parses
            # `JOIN (VALUES (1)) v(c1)` as a bare exp.Values (no Subquery
            # wrapper), so the FROM branch never sees it.
            self._register_values_alias(join_expr, context, scope)
        elif lateral_alias and isinstance(join_expr, exp.Select):
            # LATERAL SELECT without Subquery wrapper
            self._add(lateral_alias, VariableType.SUBQUERY,
                      sql_expr=_sql(join_expr),
                      defined_in=f"LATERAL:{context}", context=context)
            self._walk_select(join_expr, context, is_cte=False, outer=scope)

        # JOIN ON conditions — belong to the outer SELECT's scope
        on_expr = join.args.get("on")
        if on_expr:
            self._walk_columns_in_expr(on_expr, context, defined_in="JOIN ON", scope=scope)
            # Phase 2 (B-series): materialize computed JOIN-key expressions
            self._walk_join_key_expressions(on_expr, context)

    def _walk_join_key_expressions(self, on_expr, context: str):
        """Materialize expression nodes for computed JOIN keys (Phase 2).

        A JOIN ON predicate like
            CONCAT(p2.poctcd, p2.pogmab, LPAD(p2.poacb, 3, '0')) = p1.lending_ref
        compares a computed expression over columns with another column.
        The expression side becomes an EXPRESSION variable so the graph
        shows the key construction itself: REF edges to the operand columns
        (dependency_graph Phase 3 picks them up from `source_columns`) and a
        JOIN edge from the OTHER side of the comparison (the other side's
        variable id is recorded on `source_variables`; dependency_graph
        Phase 6b emits the edge). Only expressions with Column operands are
        materialized — plain column=column and column=literal comparisons
        are already represented by the JOIN ON column vars.
        """
        if on_expr is None:
            return
        try:
            nodes = list(on_expr.walk(
                prune=lambda n: isinstance(n, (exp.Subquery, exp.Exists, exp.CTE))))
        except Exception:
            # benign: walk failure → no join-key nodes (only degrades key
            # granularity, never crashes extraction)
            return
        pairs: list[tuple[str, str]] = []  # (materialized var id, other-side name)
        for node in nodes:
            # Predicates only (EQ/NEQ/GT/…): DPipe ("||") is also a Binary
            # but is the KEY EXPRESSION itself, not a comparison — matching
            # it would materialize the key's inner halves as phantom nodes
            # (RPAD(p4.iiapty, …) appearing alongside the full CONCAT key).
            if not isinstance(node, exp.Predicate):
                continue
            if isinstance(node, exp.Connector):
                continue  # AND/OR structure — not a key comparison
            left, right = node.this, node.expression
            for side, other in ((left, right), (right, left)):
                var = self._materialize_join_key_side(side, other, context)
                if var is None:
                    continue
                other_name = _sql(other)
                if other_name:
                    pairs.append((var.id, " ".join(other_name.split())))
        # Order-independent pairing (B-series fix): in an
        # expression=expression comparison the FIRST side is materialized
        # before its counterpart exists, so pairing at creation time only
        # ever linked the SECOND side — half the JOIN_KEY edges were
        # missing. Cross-link both sides of every comparison after the
        # whole walk instead.
        if pairs:
            self._pair_join_key_sides(pairs, context)

    def _materialize_join_key_side(self, side, other, context: str) -> VariableDefinition | None:
        """Create the EXPRESSION variable for one side of a JOIN-key
        comparison. Returns the new variable, or None when the side is not
        materializable (plain column/literal/subquery side, expression
        without column operands, or an already-materialized duplicate).
        The pairing with the OTHER side is deferred to
        `_pair_join_key_sides` so it is independent of walk order."""
        if side is None or other is None:
            return None
        if isinstance(side, (exp.Column, exp.Literal, exp.Subquery, exp.Exists)):
            return None  # plain columns / literals / subqueries are not materialized
        src_cols = _extract_source_columns(side)
        if not src_cols:
            return None  # an expression without column operands (constants) is not a key
        name = _sql(side)
        if not name:
            return None
        # Flatten the rendered SQL to a single line — the dialect render
        # emits newlines for nested calls, which would produce multi-line
        # field labels in the L2 graph.
        name = " ".join(name.split())
        # Source tables = distinct qualifier prefixes of the operand columns
        # (e.g. CONCAT(p2.poctcd, ...) → ["p2"] — the derived-table alias).
        src_tables = []
        for sc in src_cols:
            if "." in sc:
                p = sc.split(".", 1)[0]
                if p not in src_tables:
                    src_tables.append(p)
        # I1 (hl=0 fix): the synthesized name is the RENDERED expression
        # ("CONCAT(...)") — `||` renders as CONCAT, so the name never
        # matches the token stream and the default name-run lookup yields
        # (0, 0). Anchor the def line on the operand columns' OWN tokens —
        # W2's clause-keyword idiom from `_register_column`: a qualified
        # first operand matches the strict `alias . col` run (ret_last
        # reports the COLUMN's line, not the alias's); a bare one the
        # loose `on col` run (the JOIN ON keyword, scoped to the
        # statement), bare [col] as the whole-stream fallback.
        def_site = None
        first = sorted(src_cols)[0]
        parts = first.split(".")
        if len(parts) >= 2:
            run: list[str] = [parts[0]]
            for part in parts[1:]:
                run += [".", part]
            def_site = ([run], None, context, True)
        else:
            def_site = ([["on", first], [first]], None, context, True, True)
        return self._add(name, VariableType.EXPRESSION,
                         sql_expr=name,
                         defined_in="JOIN ON",
                         context=context,
                         source_cols=src_cols,
                         source_tables=src_tables,
                         is_output=False,
                         def_site=def_site)

    def _pair_join_key_sides(self, pairs: list[tuple[str, str]], context: str):
        """Cross-link both sides of every JOIN-key comparison — symmetric
        and order-independent.

        Each side appends the OTHER side's variable id to its own
        `source_variables`; dependency_graph Phase 6b then emits the
        JOIN_KEY edge FROM the other side TO the expression node. An
        expression=expression comparison therefore yields a JOIN edge
        incident on BOTH materialized nodes regardless of which side was
        materialized first (previously only the second-materialized side
        was paired, so the first side stayed edge-less)."""
        if not pairs:
            return
        by_id = {v.id: v for v in self.result.variables}
        by_name: dict[str, VariableDefinition] = {}
        for v in self.result.variables:
            if v.context != context:
                continue
            by_name.setdefault(v.name, v)  # first var of that name, as before
        for var_id, other_name in pairs:
            var = by_id.get(var_id)
            if var is None:
                continue
            other = by_name.get(other_name)
            if other is None or other.id == var.id:
                continue
            others = list(var.source_variables or [])
            if other.id not in others:
                others.append(other.id)
            var.source_variables = others
            # Symmetric: the OTHER side records this side too. Inert for
            # Phase 6b when the other side is a plain column (only
            # EXPRESSION vars emit JOIN_KEY edges), but keeps the pairing
            # record complete — and for expression=expression comparisons
            # it is what gives the first-materialized node its edge.
            back = list(other.source_variables or [])
            if var.id not in back:
                back.append(var.id)
            other.source_variables = back

    def _register_table(self, table: exp.Table, context: str, join_table: bool = False,
                        dml: str = "", scope: _SelectScope | None = None):
        """Register a database table and its alias."""
        name = _clean(table.name or "")
        alias = _clean(table.alias_or_name or "")
        var_type = VariableType.TABLE
        if not name:
            # Table-valued function (TVF) row source — e.g.
            # `JOIN v_bdm_sys_ftpsje_jydsf('$(load_date)') f`. sqlglot parses
            # the call as Table(this=Anonymous(<func>, args)) so Table.name
            # is '' (the function name lives inside Anonymous.this). Recover
            # the function name and register the call as a FUNCTION_TABLE
            # source. Extraction-time only: no schema is synthesized — only
            # the columns actually referenced downstream are materialized.
            if isinstance(table.this, exp.Func):
                fn_name = _func_name(table.this)
                if fn_name:
                    name = _clean(fn_name)
                    var_type = VariableType.FUNCTION_TABLE
                    if not alias:
                        # Bare TVF (`FROM fn('x')`, no alias): alias_or_name
                        # fell back to the empty Table.name, so mirror a bare
                        # physical table — the function is its own table name.
                        alias = name
        if not name:
            return
        # ISSUE-4: record the physical-table identity (casefolded) for the
        # frequency-vote canonical spelling. CTE references are excluded —
        # they are statement-local handles, not physical tables.
        if not self._is_cte_name(name, context):
            self._physical_table_names.add(name.casefold())
        if dml:
            defined_in = dml  # "UPDATE" or "DELETE"
        elif join_table:
            defined_in = "JOIN"
        else:
            defined_in = "FROM"

        # I1 def sites: token runs anchored on the enclosing statement —
        # [name] for the table, [name, alias] for the alias (an AS KEYWORD
        # between them is tolerated), DML keyword runs for UPDATE/DELETE
        # targets. Statement scoping disambiguates repeated tables (FROM
        # bdm_acc_loan_info p1 at L29 and L84 each resolve in their own
        # statement's range).
        node = scope.owner if scope is not None else None
        if dml == "UPDATE":
            table_runs = [["update", name], [name]]
        elif dml == "DELETE":
            table_runs = [["delete", "from", name], [name]]
        else:
            table_runs = [[name]]
        # Issue 3 (read recognition, Fix A — R19.2/R19.5, ruling
        # 2026-08-11): a BARE FROM/JOIN reference (no alias —
        # alias_or_name yields the table's own name) is a READ of its own
        # table — carry source_tables=[name] exactly like the aliased var
        # below, so Phase 1a/1c-extra see the read instance (statement
        # 2's `FROM bdm_acc_loan_info_sup` @L223 becomes a real
        # `sup@223 → output2` TABLE_FLOW instead of an invisible node).
        # NOT for DML targets (dml= UPDATE/DELETE — the walk's INSERT
        # path registers targets separately): a target must never emit a
        # spurious target→output Phase-1a edge. NOT for the base var of
        # an ALIASED ref either — the alias var already carries the read
        # (source_tables=[name]); the base var stays invisible so the
        # read is represented once, not twice.
        table_var = self._add(name, var_type,
                              sql_expr=name, defined_in=defined_in,
                              context=context,
                              source_tables=[name] if (not dml and alias == name) else None,
                              def_site=(table_runs, node, context))

        if alias and alias != name:
            # I4: alias_of = the KEY of the exact source var this alias was
            # registered with — the table var registered in this same clause
            # walk, or (when it was skipped/deduped) the known var of the
            # same name: the CTE's own var for CTE refs, else the
            # already-registered same-context table var (the INSERT target at
            # 160 re-referenced as the main select's "FROM
            # bdm_acc_loan_info_sup p2" → pairs with the TOP0 instance,
            # never the TOP1 one). Never across statements — contexts differ.
            alias_of = None
            if table_var is not None:
                alias_of = table_var.id
            else:
                want = (VariableType.CTE
                        if self._is_cte_name(name, context)
                        else var_type)
                same_ctx = next((v.id for v in self.result.variables
                                 if v.variable_type == want
                                 and v.name.lower() == name.lower()
                                 and v.context == context), None)
                if same_ctx is not None:
                    alias_of = same_ctx
                elif want == VariableType.CTE:
                    # CTE refs may legitimately point at a CTE var recorded
                    # in the enclosing statement context (a nested statement
                    # referencing a TOP0 CTE).
                    alias_of = next((v.id for v in self.result.variables
                                     if v.variable_type == VariableType.CTE
                                     and v.name.lower() == name.lower()), None)
            self._add(alias, VariableType.TABLE,
                      sql_expr=f"{name} AS {alias}",
                      defined_in=defined_in, context=context,
                      source_tables=[name], alias_of=alias_of,
                      is_alias_handle=True,
                      def_site=([[name, alias]], node, context))

        # R20: record into the statement scope for orphan resolution.
        if scope is not None:
            # M3a: case-insensitive CTE membership — `FROM C` for a CTE
            # defined as `c` is a CTE ref, not a physical table (never
            # count it as physical scope evidence). ISSUE-4: scope-aware —
            # only CTEs visible in THIS statement's scope count.
            if self._is_cte_name(name, context):
                # CTE reference — not a physical table (S2 resolves its columns)
                scope.ctes.append(name)
            else:
                scope.tables.append((_clean(table.db or ""), name))
            if alias:
                scope.aliases[alias] = name
                if alias != name:
                    # M-E3b: only a REAL alias (AS a, alias != table) is a
                    # scope-local handle; a bare reference has alias_or_name
                    # == table name and must NOT enter the alias registry.
                    self._alias_names.setdefault(
                        self._scope_top(context), set()).add(alias.casefold())

    # ── Task B: LATERAL VIEW / VALUES / UNNEST alias registration ────
    # The audit found three table-like constructs whose table var/alias
    # was never registered: `LATERAL VIEW explode(...) x AS c2`
    # (SELECT-level laterals), `FROM (VALUES ...) v(c1)`, and
    # `CROSS JOIN UNNEST(t.arr) AS u(c2)`. Without the alias var,
    # dependency_graph Phase 1a (gated on `if not v.source_tables:
    # continue`) emits no read edge — the exploded array / VALUES rows /
    # UNNEST rows vanish from the graph. Registering mirrors `FROM base x`:
    # a TABLE alias var carrying the base table name in source_tables.
    # For VALUES/UNNEST the "base" is the synthetic table the clause
    # itself represents (⟐ values / ⟐ unnest); for LATERAL VIEW it is the
    # physical table whose array column is exploded. The alias is NOT
    # added to scope.aliases: columns referencing it
    # (x.c2 / v.c1 / u.c2) keep their current registration and lines
    # exactly as before.

    def _lateral_base_table(self, lateral, scope: _SelectScope | None) -> str:
        """Physical table whose array column a LATERAL VIEW explodes ("" if
        unresolvable — honest, never a guess). The exploded argument is a
        qualified column (explode(t.arr) → t resolves via _resolve_alias),
        a bare column (explode(arr) → the single distinct FROM/JOIN table),
        or absent → "".
        """
        fn = lateral.this
        if fn is None:
            return ""
        arg = fn.this if isinstance(fn, exp.Func) else None
        if arg is None and isinstance(fn, exp.Func):
            exprs = fn.args.get("expressions") or []
            arg = exprs[0] if exprs else None
        if arg is None:
            return ""
        if isinstance(arg, exp.Column) and arg.table:
            return self._resolve_alias(_clean(arg.table or ""), scope)
        if scope is not None:
            names = {n for _, n in scope.tables}
            if len(names) == 1:
                # Determinism pin (2026-08-29): same shape as the
                # `derived_single` pick — hash-order-shaped singleton read.
                return min(names)
        return ""

    def _register_synthetic_alias(self, alias: str, base: str, context: str,
                                  defined_in: str, node,
                                  sql_expr: str) -> None:
        """Add a TABLE alias var with source_tables=[base] for a
        LATERAL VIEW / VALUES / UNNEST clause. I1 def site: the alias
        token right after the closing ')' of the clause — `[")", alias]`
        with ret_last (report the ALIAS token's line), whole-stream
        fallback `[alias]`. base may be "" (no source_tables → no read
        edge, honest)."""
        if not alias:
            return
        self._add(alias, VariableType.TABLE,
                  sql_expr=sql_expr,
                  defined_in=defined_in, context=context,
                  source_tables=[base] if base else None,
                  is_alias_handle=True,
                  def_site=([[")", alias], [alias]], node, context, True))

    def _register_values_alias(self, values, context: str,
                               scope: _SelectScope | None) -> None:
        """FROM (VALUES ...) v(c1) — the alias v is a TABLE var whose base
        is the synthetic VALUES table (⟐ values)."""
        alias = _clean(values.alias_or_name or "")
        if not alias:
            return
        node = scope.owner if scope is not None else None
        self._register_synthetic_alias(alias, VALUES_TABLE_NAME, context,
                                       "FROM", node, _sql(values))

    def _register_unnest_alias(self, unnest, context: str,
                               scope: _SelectScope | None,
                               defined_in: str = "FROM",
                               alias_override: str = "") -> None:
        """UNNEST(...) AS u(c2) in FROM or JOIN — the alias u is a TABLE
        var whose base is the synthetic UNNEST table (⟐ unnest).
        `alias_override` covers `JOIN LATERAL UNNEST(...) x` — the alias
        sits on the LATERAL wrapper, never on the exp.Unnest itself."""
        alias = _clean(alias_override or unnest.alias_or_name or "")
        if not alias:
            return
        node = scope.owner if scope is not None else None
        self._register_synthetic_alias(alias, UNNEST_TABLE_NAME, context,
                                       defined_in, node, _sql(unnest))

    def _register_lateral_alias(self, lateral, context: str,
                                scope: _SelectScope | None) -> None:
        """LATERAL VIEW explode(t.arr) x AS c2 — the alias x is a TABLE
        var whose base is the physical table behind the exploded array
        column (t → resolved)."""
        alias = _clean(lateral.alias_or_name or "")
        if not alias:
            return
        base = self._lateral_base_table(lateral, scope)
        node = scope.owner if scope is not None else None
        self._register_synthetic_alias(alias, base, context, "FROM", node,
                                       _sql(lateral))

    # ── Column walker ───────────────────────────────────────────────

    def _walk_columns_in_expr(self, expr, context: str, defined_in: str = "",
                              scope: _SelectScope | None = None):
        """Walk an expression tree: register columns AND nested table aliases."""
        if expr is None:
            return
        # M4: prune descent into subquery/EXISTS bodies — the explicit
        # branches below walk them ONCE with their own contexts
        # (subq{N}/exists{N}), so the raw walk must not ALSO descend and
        # re-register every branch column in the outer context
        # (context-keyed vars → double count, inflated total_columns,
        # phantom outer-context copies like "p1@subq3"). This covers both
        # set-op bodies and Select bodies: walk() yields a node BEFORE
        # evaluating prune for it and the Subquery/Exists wrapper is yielded
        # before its Select child, so recording the Select at the wrapper
        # guarantees the raw walk prunes that subtree before any column
        # inside it is registered.
        for node in expr.walk(
                prune=lambda n: (
                    isinstance(n, (exp.CTE,))
                    or (isinstance(n, exp.Subquery)
                        and isinstance(n.this, (exp.Union, exp.Intersect,
                                                exp.Except)))
                    or (isinstance(n, exp.Exists)
                        and isinstance(n.this, (exp.Union, exp.Intersect,
                                                exp.Except)))
                    or (isinstance(n, exp.Select)
                        and id(n) in self._explicitly_walked_selects))):
            if isinstance(node, exp.Column):
                self._register_column(node, context, defined_in, scope)
            # Walk INTO subqueries — fully process inner SELECT.
            # Fix A (1c): when the subquery body is a SET OP (UNION/EXCEPT/
            # INTERSECT — e.g. `x IN (SELECT ... UNION SELECT ...)`), the
            # branches must each be walked with their OWN scope so their
            # columns resolve via S3 (single-table branch scopes). Previously
            # only the raw-walk phantom copies were registered in the outer
            # context, where `_in_scope_owner` correctly refused attribution.
            elif isinstance(node, exp.Subquery):
                if isinstance(node.this, exp.Select):
                    # record BEFORE _walk_select: the raw walk's prune is
                    # evaluated when the wrapper's Select child is reached
                    # (after this wrapper is yielded), so the subtree is
                    # skipped there and only the explicit walk registers it.
                    self._explicitly_walked_selects.add(id(node.this))
                    self._subq_counter += 1
                    self._walk_select(node.this, f"{context}/subq{self._subq_counter}", is_cte=False,
                                      outer=scope)
                elif isinstance(node.this, (exp.Union, exp.Intersect, exp.Except)):
                    self._subq_counter += 1
                    self._walk_setop(node.this, type(node.this).__name__.upper(),
                                     f"{context}/subq{self._subq_counter}", outer=scope)
            elif isinstance(node, exp.Exists):
                # EXISTS wraps a Select directly (not a Subquery)
                if isinstance(node.this, exp.Select):
                    self._explicitly_walked_selects.add(id(node.this))
                    self._subq_counter += 1
                    self._walk_select(node.this, f"{context}/exists{self._subq_counter}", is_cte=False,
                                      outer=scope)
                elif isinstance(node.this, (exp.Union, exp.Intersect, exp.Except)):
                    self._subq_counter += 1
                    self._walk_setop(node.this, type(node.this).__name__.upper(),
                                     f"{context}/exists{self._subq_counter}", outer=scope)

    def _register_groupby_twins(self, expr, context: str,
                                scope: _SelectScope | None = None):
        """#387 (2026-08-28, R44 family 3): occurrence-side column vars for
        GROUP BY item occurrences.

        The GROUP BY walk above attributes each item's column to its owner
        (S1-S3), but the OCCURRENCE itself registers no var of its own: a
        bare item folds onto the SELECT projection's var (line = the
        projection line), so lines like PL L246/247 (`product,` /
        `lrr_key,` inside GROUP BY) never anchor — the group-key usage is
        invisible to the strict table.field walker (user ruling: flow-only
        must cover every dataflow-relevant occurrence).

        Same shape as the R44 derived-read twins: for every column leaf of
        a GROUP BY item whose (already-attributed) occurrence var carries a
        physical owner, register twin `{owner}.{col}` in the SAME context
        with source_columns populated and is_output=False (the twin is the
        occurrence side — a genuinely projected var keeps its own output
        var untouched). The twin's line is the item's OWN line — resolved
        by the clause-keyword token run (["group", …, col], the W2/Defect-5
        mechanism: loose on the keyword, anchored past it to the column),
        never the projection's line. dependency_graph's Phase 4d-gb then
        gives the group-key usage a REF/read-class edge anchored at the
        twin's line.
        """
        if expr is None:
            return
        for node in expr.walk():
            if not isinstance(node, exp.Column):
                continue
            table = _clean(node.table or "")
            col_name = _clean(node.name or "")
            if not col_name:
                continue
            full = f"{table}.{col_name}" if table else col_name
            # The occurrence var the plain walk just registered/attributed
            # (the projection var for a bare item, the qualified read var
            # for a dotted one). Last match in this context = this clause's.
            var = next((v for v in reversed(self.result.variables)
                        if v.variable_type == VariableType.COLUMN
                        and v.name == full
                        and v.context == context), None)
            if var is None or not var.source_tables:
                continue
            st0 = var.source_tables[0]
            # Physical owners only — a ⟐ VT / system-sentinel owner is a
            # container, not a table the group key can anchor against.
            if (not st0 or st0.startswith("⟐")
                    or st0 == SYSTEM_TABLE_SENTINEL
                    or st0 == OTHER_SENTINEL):
                continue
            # W2 clause-keyword def site: ["group by", …, col] loose on
            # the keyword (the sqlglot tokenizer emits GROUP BY as ONE
            # keyword token), ret_last so the COLUMN's line (not the
            # keyword's) is reported; the bare-name run is the strict
            # fallback.
            if table:
                bare_run = [table, col_name]
            else:
                bare_run = [col_name]
            twin = self._add(
                f"{st0}.{col_name}", VariableType.COLUMN,
                sql_expr=_sql(node),
                defined_in="GROUP BY", context=context,
                source_cols=[full],
                source_tables=[st0], is_output=False,
                def_site=([["group by"] + bare_run, bare_run], None,
                         context, True, True))
            if twin is not None and not twin.line_start:
                # The token-run site missed (tokenizer hiccup) — degrade
                # to the occurrence var's own line, never line 0 silently.
                twin.line_start = var.line_start
                twin.line_end = var.line_end

    def _walk_select_tables(self, select_node, context: str):
        """Extract table references from a Select node inside subquery/EXISTS."""
        if not isinstance(select_node, exp.Select):
            return
        frm = select_node.args.get("from") or select_node.args.get("from_")
        if frm:
            self._walk_from(frm, context)
        for join in (select_node.args.get("joins") or []):
            self._walk_join(join, context)

    def _register_column(self, col: exp.Column, context: str, defined_in: str = "",
                         scope: _SelectScope | None = None):
        """Register a single column reference.

        R20: after registration, orphan resolution runs against `scope`:
        S6 pseudocolumns, S2 CTE output columns, S3/S5 nearest-scope
        physical tables. Qualified columns keep the historical
        prefix-based behavior (S5 system-schema qualifiers excepted).
        """
        table = _clean(col.table or "")
        col_name = _clean(col.name or "")
        if not col_name:
            return
        # For bare column names (no table prefix): skip if a defined variable
        # with the same name already exists in the same context.
        if not table:
            for existing in self.result.variables:
                if (existing.name == col_name
                    and existing.context == context
                    and existing.variable_type in (
                    VariableType.AGGREGATE, VariableType.WINDOW,
                    VariableType.CASE, VariableType.TRANSFORM,
                    VariableType.EXPRESSION, VariableType.CTE_COLUMN)):
                    return  # already defined in this context
        full = f"{table}.{col_name}" if table else col_name
        def_site = None
        if not table:
            # W2 (Defect 5): a BARE column in a filter clause (WHERE data_dt
            # = '$(load_date)' at L225) resolves to its OWN occurrence, not
            # the clause's first name token — a later WHERE in the same
            # statement used to steal the earlier projection's line (213).
            # The clause-keyword run ["where", data_dt] (ret_last) anchors
            # the scan on the clause keyword and reports the COLUMN's line;
            # the bare [name] fallback keeps first-in-scope resolution for
            # second+ columns of the same clause (WHERE a=1 AND b=2).
            kw = {"WHERE": "where", "HAVING": "having",
                  "JOIN ON": "on", "MERGE ON": "on"}.get(
                      (defined_in or "").strip().upper())
            if kw:
                # loose_first: "where" … next data_dt in the statement —
                # never require adjacency (WHERE a=1 AND data_dt=…).
                def_site = ([[kw, col_name], [col_name]], None,
                            context, True, True)
        var = self._add(full, VariableType.COLUMN,
                        sql_expr=_sql(col),
                        defined_in=defined_in or "condition", context=context,
                        def_site=def_site)
        if var is None:
            # Already created via another path (e.g. the SELECT-expression
            # alias var for a bare column) — pick it up for attribution.
            var = next((v for v in self.result.variables
                        if v.name == full
                        and v.variable_type == VariableType.COLUMN
                        and v.context == context), None)

        # ── R20 orphan resolution ─────────────────────────────────────
        if table:
            # S4a source 1: qualified refs (t.col / alias.col / db.t.col)
            # build the per-script canonical schema evidence map.
            # REPORT-ONLY — evidence never attributes the variable.
            self._record_qualified_evidence(col, table, scope)
            # Qualified column: S5 — qualifier sits in a system schema
            # (e.g. INFORMATION_SCHEMA.TABLES.TABLE_NAME).
            if var is not None and _clean(col.db or "").lower() in _SYSTEM_SCHEMAS:
                var.source_tables = [SYSTEM_TABLE_SENTINEL]
                self._resolution_stats["resolved_by"]["sys"] += 1
                return
            # I2: qualified refs attribute to their OWN qualifier's physical
            # table (S1 resolution through the statement scope) — p1.data_dt
            # inside loan_final → bdm_acc_loan_info, never a whole-file
            # first-match table. System-schema qualifiers stay on the S5
            # path above; derived-alias qualifiers resolve to themselves.
            if var is not None:
                var.source_tables = [self._resolve_alias(table, scope)]
            return
        if var is None:
            return
        if col_name.lower() in _PSEUDOCOLUMN_NAMES:
            # S6 — known pseudocolumn / trigger var (LEVEL, ROWNUM, new, old):
            # marked expected (OTHER_SENTINEL), excluded from unresolved,
            # never attributed.
            # E4 (reviewer): new/old are only trigger idioms inside
            # row_to_json/trigger bodies — a REAL column named "new"/"old"
            # elsewhere must NOT be misclassified; fall through to S3 then.
            _parent = col.parent
            trigger_idiom = (col_name.lower() in ("new", "old")
                             and _parent is not None
                             and ((isinstance(_parent, exp.Func)
                                   and _parent.sql_name().lower() == "row_to_json")
                                  or (isinstance(_parent, exp.Anonymous)
                                      and _parent.name.lower() == "row_to_json")))
            if col_name.lower() in ("level", "rownum") or trigger_idiom:
                var.source_tables = [OTHER_SENTINEL]
                self._resolution_stats["resolved_by"]["other"] += 1
                return
        if scope is None or not self._in_scope_owner(col, scope):
            return  # no scope, or the subquery-copy artifact (outer context)
        # S2 — unqualified reference to a CTE output column
        for cte_name in scope.ctes:
            if col_name in self._cte_output_columns.get(cte_name, ()):
                var.source_tables = [cte_name]
                self._resolution_stats["resolved_by"]["expr_alias"] += 1
                return
        # S2 (Fix C) — unqualified reference to a derived-table output column.
        # Exactly ONE visible derived table may claim the name (two or more =
        # ambiguous → left unresolved, never guessed). One-hop → the derived
        # alias; two-hop → the output column's own source table (S1 chain).
        # L3 (kept by design): this check runs BEFORE the S3 single-physical
        # check below, so a derived output column shadows a physical table
        # that also owns the name. Corpus-audited — q71's spider pattern
        # relies on the derived chain winning; attributing to the physical
        # table instead would require guessing between two owners. Pinned by
        # test_fix_c_shadows_physical_table_owner.
        derived_matches = [d for d in scope.deriveds
                           if col_name in self._derived_output_columns.get(d, ())]
        if len(derived_matches) == 1:
            d_name = derived_matches[0]
            two_hop = self._derived_output_columns[d_name][col_name]
            var.source_tables = [two_hop] if two_hop else [d_name]
            self._resolution_stats["resolved_by"]["expr_alias"] += 1
            return
        # S3/S5 — exactly one distinct physical table in the nearest scope
        distinct = self._distinct_scope_tables(scope)
        if len(distinct) == 1:
            db, name = distinct[0]
            # A3: R6 guard extended to S3 — `SELECT call_center FROM
            # call_center` has the same field == visible-table-name ambiguity
            # S4 excludes in ≥2-table scopes (SOLUTION_DESIGN follow-up 5).
            # Never attribute; counted in r6_collision; stays unresolved.
            if col_name.lower() == name.lower():
                self._resolution_stats["r6_collision"] += 1
                return
            if db.lower() in _SYSTEM_SCHEMAS:
                var.source_tables = [SYSTEM_TABLE_SENTINEL]
                self._resolution_stats["resolved_by"]["sys"] += 1
            else:
                var.source_tables = [name]
                self._resolution_stats["resolved_by"]["scope"] += 1
        elif len(distinct) >= 2:
            # S4a: the S3 "≥2 tables" branch. The candidate is stashed for
            # the unique-owner post-pass (S4a auto-attribution) and the
            # index-time cross-script re-test (S4b). Only a UNIQUE visible
            # owner (whole-name, case-insensitive, R6-guarded) attributes.
            self._stash_schema_candidate(col_name, distinct, defined_in,
                                         context, scope)
        # 0 physical tables → left unresolved.

    def _in_scope_owner(self, col: exp.Column, scope: _SelectScope) -> bool:
        """True when `col` sits directly under the scope's own statement node.

        Subquery-inner columns are ALSO registered in the outer context by the
        raw walk (historical behavior). Those outer-context copies must never
        be scope-attributed — their nearest statement ancestor is the inner
        SELECT, not `scope.owner`.
        """
        node = col.parent
        while node is not None:
            if isinstance(node, (exp.Select, exp.Update, exp.Delete, exp.Merge)):
                return node is scope.owner
            node = node.parent
        return False

    @staticmethod
    def _distinct_scope_tables(scope: _SelectScope) -> list:
        """Distinct PHYSICAL tables in scope (alias→canonical already deduped).

        A table and its alias count as ONE physical table because aliases are
        never added to `tables` — only `aliases`. Returns [(db, name), ...].
        """
        distinct = []
        seen = set()
        for db, name in scope.tables:
            if name and name not in seen:
                seen.add(name)
                distinct.append((db, name))
        return distinct

    @staticmethod
    def _ci_find(mapping: dict, name: str):
        """Case-insensitive key lookup — MySQL identifiers are case-insensitive.
        Returns the stored (definition-case) key, or None. Exact match wins
        first; the first case-insensitive match otherwise."""
        if name in mapping:
            return name
        low = name.lower()
        for k in mapping:
            if k.lower() == low:
                return k
        return None

    def _scope_top(self, context: str | None) -> str:
        """Top-level statement scope of a (possibly nested) context.

        ISSUE-4 scope-aware identity: a nested context (`TOP0/subq1`,
        `TOP0:join:p2`, `TOP0/union0`) maps back to its top-level statement
        `TOP0`; a CTE body context (`CTE{name}`, `CTE{name}:join:x`) maps to
        the statement that DEFINES the CTE (recorded in `_cte_enclosing`).
        """
        ctx = context or ""
        if ctx.startswith("CTE{"):
            end = ctx.find("}")
            cte_ctx = ctx[:end + 1] if end > 0 else ctx
            return self._cte_enclosing.get(cte_ctx, ctx)
        # L-E4 (2026-08-26, folded 2026-08-28): VIEW@{stmt}:{name.casefold()}
        # / CTAS@{stmt}:{name.casefold()} — the statement-owning, case-folded
        # scope key. Two same-name (re)definitions now map to their OWN
        # defining statements, and case-variant spellings of one name share
        # one bucket (the old "VIEW:{name}" key was neither indexed nor
        # folded, so `_scope_top` shared one registry across redefinitions
        # and split one view across case variants).
        for prefix in ("VIEW@", "CTAS@"):
            if ctx.startswith(prefix):
                rest = ctx[len(prefix):]
                i = rest.find(":")
                if i > 0:
                    return rest[:i]
                break
        # M-E2: VIEW:{name} / CTAS:{name} are distinct per-statement scopes —
        # the ":" is part of the statement identity, not a nested-scope
        # separator. Strip any nested sub-context ("/subq", ":join:..") AFTER
        # the name, but never collapse two views/CTAS into one bucket (the
        # old "/" and ":" strip mapped VIEW:a and VIEW:b to the same "VIEW").
        for prefix in ("VIEW:", "CTAS:"):
            if ctx.startswith(prefix):
                rest = ctx[len(prefix):]
                for sep in ("/", ":"):
                    i = rest.find(sep)
                    if i > 0:
                        rest = rest[:i]
                return prefix + rest
        for sep in ("/", ":"):
            i = ctx.find(sep)
            if i > 0:
                ctx = ctx[:i]
        return ctx

    def _is_cte_name(self, name: str, context: str | None = None) -> bool:
        """True when `name` is a CTE visible in `context` (scope-aware)."""
        return name.casefold() in self._cte_names.get(self._scope_top(context), set())

    def _is_derived_alias(self, name: str, context: str | None = None) -> bool:
        """True when `name` is a derived-table alias in `context`'s scope."""
        return name.casefold() in self._derived_aliases.get(self._scope_top(context), set())

    def _is_alias_name(self, name: str, context: str | None = None) -> bool:
        """True when `name` is a table alias in `context`'s scope (M-E3b)."""
        return name.casefold() in self._alias_names.get(self._scope_top(context), set())

    def _canonical_spelling(self, name: str) -> str:
        """Majority spelling of a physical-table name from the token vote."""
        votes = self._ident_votes.get(name.casefold())
        return _majority_spelling(votes) if votes else name

    def _resolve_alias(self, qualifier: str, scope: _SelectScope | None = None) -> str:
        """Resolve a column qualifier to its physical table name (S1).

        Case-insensitive (M3a): a case-variant qualifier (`SELECT W.x FROM
        t AS w`) must resolve to the canonical stored alias — never leak the
        variant spelling as schema evidence. ISSUE-4: resolution is
        SCOPE-LOCAL — an alias `a` in one statement never resolves through a
        same-spelled alias registered in a different statement (the old
        flat script-global `_table_aliases` was last-write-wins). Nested
        scopes walk their OUTER chain (innermost → outermost) so a
        correlated/outer reference (`o.order_id` inside a NOT EXISTS
        subquery) still resolves to the enclosing scope's physical table.
        """
        s = scope
        while s is not None:
            for a, t in s.aliases.items():
                if a.lower() == qualifier.lower():
                    return t
            s = s.outer
        return qualifier

    # ── S4a (Phase 0): SELECT-side schema evidence + candidates ──────
    # REPORT-ONLY: nothing below ever sets source_tables. Evidence feeds
    # `script_schemas`; the unique-owner computation only annotates the
    # candidate records (`owner`), which stay in `unresolved`.

    def _record_qualified_evidence(self, col: exp.Column, table: str,
                                   scope: _SelectScope | None):
        """S4a source 1: a qualified ref (t.col / alias.col / db.t.col) is
        schema evidence for its canonical physical table.

        Canonicalization: alias → physical via the script alias map
        (scope-local first, then script-global); unaliased `t.col` → `t`;
        `db.t.col` → `t` (db dropped). Excluded: `⟐` containers, CTE names,
        derived-table aliases, system-schema qualifiers. Subquery-phantom
        copies (outer-context raw-walk registrations) are gated via
        `_in_scope_owner` so aliases resolve against the subquery's own scope.
        """
        if _clean(col.db or "").lower() in _SYSTEM_SCHEMAS:
            return  # INFORMATION_SCHEMA/… refs are not physical evidence
        if scope is not None:
            # M3a: case-insensitive — MySQL identifiers are case-insensitive;
            # `SELECT C.x FROM c` must not leak phantom evidence under "C".
            if (table.lower() in {t.lower() for t in scope.ctes}
                    or table.lower() in {d.lower() for d in scope.deriveds}):
                return  # CTE / derived-table qualifier — not physical
            if not self._in_scope_owner(col, scope):
                return  # subquery phantom copy — the inner walk records it
        canonical = self._resolve_alias(table, scope)
        col_name = _clean(col.name or "")
        scope_key = scope.key if scope is not None else None
        if (not col_name or canonical.startswith("⟐")
                or self._is_cte_name(canonical, scope_key)
                or self._is_derived_alias(canonical, scope_key)):
            return
        # {table: {col: evidence_line}} — evidence line = the line of the
        # statement containing the qualified ref (the schema-EVIDENCE line,
        # not the bare-use line); first occurrence wins (setdefault).
        evidence_line = (self._statement_anchor(scope.owner)
                         if scope is not None else 0)
        self._script_schemas.setdefault(canonical, {}).setdefault(
            col_name, evidence_line)

    def _stash_schema_candidate(self, col_name: str, distinct: list,
                                defined_in: str, context: str,
                                scope: _SelectScope | None = None):
        """S4a: record an unresolved bare column in a ≥2-table scope.

        The record feeds the unique-owner post-pass (S4a) and the index-time
        cross-script re-test (S4b). The dedup key is (field, visible-set):
        ANY occurrences — even in different statements — that share the same
        visible table set collapse into one candidate (extra contexts are
        appended for var attribution); a statement with a different visible
        set gets its own candidate.

        `loc` is anchored to the STATEMENT containing the scope (the
        statement's first-token line via `_statement_anchor`) — the token
        stream, never a text search: a STRING token equal to the name on an
        earlier line (q76: `'ws_ship_hdemo_sk' col_name`) or another
        statement's use would beat the real name token. The statement anchor
        is conservative in every case: when the field only appears inside
        string literals, and when it appears nowhere, the anchor still
        points at the enclosing statement.
        """
        visible = [name for _db, name in distinct]
        key = (col_name, tuple(visible))
        if key in self._candidate_keys:
            for cand in self._schema_candidates:
                if (cand["field"] == col_name
                        and cand["visible_tables"] == visible):
                    if context not in cand["contexts"]:
                        cand["contexts"].append(context)
                    return
        self._candidate_keys.add(key)
        line = self._statement_anchor(scope.owner) if scope is not None else 0
        loc = line if line and line > 0 else (defined_in or "unknown")
        self._schema_candidates.append({
            "field": col_name,
            "visible_tables": visible,
            "loc": loc,
            "contexts": [context],
        })

    def _finalize_schema_candidates(self) -> int:
        """S4a post-pass (Phase 2 — AUTO-resolution): unique-owner attribution.

        Per candidate:
          1. R6 guard — lower(field) ∈ lower(visible tables) → r6_collision,
             never attributed; the candidate stays (S4b re-tests it, the
             report lists it).
          2. owners = visible tables whose evidence contains the field
             (whole-name equality, case-insensitive — R4: "id" never matches
             "customer_id").
          3. Exactly one owner → AUTO-ATTRIBUTE: every COLUMN var named
             `field` in the recorded contexts with no source_tables gets
             source_tables = [owner] (canonical name, same shape as S3);
             resolved_by["schema"] += 1; the candidate is REMOVED —
             `schema_candidates` contains ONLY still-unresolved candidates
             (the S4b index re-test contract).
          4. 0 or ≥2 owners → left unresolved (never guess; stays in
             `unresolved` + the ORPHAN RESOLUTION REPORT).
        """
        r6 = 0
        still_unresolved = []
        for cand in self._schema_candidates:
            field = cand["field"]
            visible = cand["visible_tables"]
            if field.lower() in {t.lower() for t in visible}:
                r6 += 1
                still_unresolved.append(cand)  # R6 guard — never attribute
                continue
            owners = [t for t in visible
                      if field.lower() in {c.lower()
                                           for c in self._script_schemas.get(t, {})}]
            if len(owners) == 1:
                owner = owners[0]
                for v in self.result.variables:
                    if (v.variable_type == VariableType.COLUMN
                            and v.name == field
                            and v.context in cand.get("contexts", [])
                            and not v.source_tables):
                        v.source_tables = [owner]
                self._resolution_stats["resolved_by"]["schema"] += 1
                # resolved — REMOVED from schema_candidates (S4b contract)
            else:
                still_unresolved.append(cand)  # 0 or ≥2 owners — unresolved
        self._schema_candidates = still_unresolved
        return r6

    @staticmethod
    def _projection_output_name(expr) -> str:
        """S4a: a SELECT projection's output name (alias > bare column).

        Mirrors `_walk_select_expression` auto-naming for the alias/column
        cases; computed projections carry no usable column evidence and are
        skipped (CTAS positional mapping is per-projection).
        """
        if isinstance(expr, exp.Alias):
            return _clean(expr.alias or "")
        if isinstance(expr, exp.Column):
            return _clean(expr.name or "")
        return ""

    def _expand_star_columns(self, inner, scope):
        """S2 extension (fin_query8): a QUALIFIED star projection (`pe.*`)
        in a CTE/derived body expands the referenced CTE's/derived table's
        RECORDED output columns — exact SQL semantics (SELECT pe.* outputs
        every column of pe), never a heuristic.

        sqlglot 30.12 parses `pnp.*` as exp.Column(this=exp.Star(),
        table='pnp') — never as exp.Star with a table arg. Without this
        expansion the body records the bogus output name '*' and downstream
        bare refs stay orphans.

        Returns {output_name: two_hop_or_None} (two_hop propagated from the
        referenced derived table's own map; CTE refs carry None — CTE
        outputs are name-only). {} for unqualified stars, physical-table
        stars, and unresolvable refs (record nothing — honest, never guess).
        """
        if not (isinstance(inner, exp.Column) and isinstance(inner.this, exp.Star)):
            return {}
        ref = _clean(inner.table or "")
        if not ref:
            return {}
        if scope is not None:
            ref = self._resolve_alias(ref, scope)
        out = {}
        # M3a: case-insensitive membership + map lookup (P.* vs CTE p).
        # ISSUE-4: scope-aware — the CTE/derived name must be visible in
        # the referenced scope, never a same-spelled name in another scope.
        scope_key = scope.key if scope is not None else None
        if self._is_cte_name(ref, scope_key):
            key = self._ci_find(self._cte_output_columns, ref)
            if key is not None:
                for c in self._cte_output_columns[key]:
                    out.setdefault(c, None)
        elif self._is_derived_alias(ref, scope_key):
            key = self._ci_find(self._derived_output_columns, ref)
            if key is not None:
                for c, two in self._derived_output_columns[key].items():
                    out.setdefault(c, two)
        return out

    # ── SELECT expression walker ────────────────────────────────────

    def _walk_select_expression(self, expr, context: str, is_cte: bool = False,
                                scope: _SelectScope | None = None,
                                output_container: str | None = None,
                                cte_name: str | None = None,
                                derived_alias: str | None = None,
                                setop_body: bool = False):
        """Walk one SELECT expression (may or may not have an alias).

        `setop_body` suppresses two-hop attribution for UNION/INTERSECT/
        EXCEPT branch outputs (q71): per-branch source tables differ, so a
        branch's plain-alias output resolves one-hop to the derived alias.
        """
        if expr is None:
            return

        # Unwrap Alias to get the actual expression
        alias = ""
        explicit_alias = False
        inner = expr
        if isinstance(expr, exp.Alias):
            alias = _clean(expr.alias or "")
            explicit_alias = True
            inner = expr.this

        # Skip None / non-walkable
        if inner is None or not hasattr(inner, 'walk'):
            return

        # Auto-name: use alias if present, otherwise derive from expression
        if not alias:
            if isinstance(inner, exp.Column):
                # Bare column reference: table.column or just column
                tbl = _clean(inner.table or "")
                col = _clean(inner.name or "")
                alias = f"{tbl}.{col}" if tbl else col
            elif isinstance(inner, exp.Literal):
                alias = _sql(inner)[:30]
            else:
                raw = _sql(inner)[:30].replace(" ", "_").replace("(", "").replace(")", "")
                alias = raw or "expr"

        sql_expr = _sql(inner)
        src_cols = _extract_source_columns(inner)
        src_tables = _extract_table_names(inner)
        var_type = _classify_aliased_expression(inner)

        # CTE context: only bare "expression" becomes cte_column
        if is_cte and var_type == VariableType.EXPRESSION:
            var_type = VariableType.CTE_COLUMN

        # ── R20 S1/S2: alias attribution ──────────────────────────────
        attr_strategy = None  # resolved_by key incremented on attribution
        attr_table = None     # source_tables entry to apply
        if cte_name:
            # CTE body: every SELECT output is an output column of the CTE.
            # Auto-named qualified columns record their bare field name so
            # downstream `SELECT <field> FROM <cte>` resolves. A qualified
            # star (pe.*) expands the referenced CTE's/derived's recorded
            # outputs (fin_query8) instead of recording the bogus name '*'.
            star_out = self._expand_star_columns(inner, scope)
            if star_out:
                self._cte_output_columns.setdefault(cte_name, set()).update(star_out)
            elif alias:
                # L4: bare Star/Literal projections auto-name to junk ("*",
                # "1", …) — never resolvable output names; skip recording.
                if isinstance(inner, (exp.Star, exp.Literal)) and not explicit_alias:
                    pass
                else:
                    record_name = (_clean(inner.name)
                                   if isinstance(inner, exp.Column) and not explicit_alias
                                   else alias)
                    self._cte_output_columns.setdefault(
                        cte_name, set()).add(record_name)
        if explicit_alias:
            if isinstance(inner, exp.Column):
                qualifier = _clean(inner.table or "")
                if qualifier:
                    # S1: alias of a plain qualified column → inherits the
                    # source column's physical table (dotted db.t.col → t).
                    if _clean(inner.db or "").lower() in _SYSTEM_SCHEMAS:
                        attr_strategy, attr_table = "sys", SYSTEM_TABLE_SENTINEL
                    else:
                        attr_strategy, attr_table = (
                            "plain_alias", self._resolve_alias(qualifier, scope))
                elif alias != _clean(inner.name or "") and scope is not None:
                    # S1 (Fix B): alias of a plain BARE column — the alias
                    # var inherits EXACTLY what _register_column would
                    # attribute the source column, in the SAME order:
                    # S2 CTE outputs → Fix C derived outputs (two-hop
                    # chain) → S3 single physical table. Never guess — a
                    # bare column under ≥2 physical tables stays unresolved.
                    # M2: previously only the S3 physical path was consulted,
                    # so an alias whose source resolved via the CTE/derived
                    # chain (e.g. `SELECT id AS c FROM t1, w` with w a CTE)
                    # landed on a DIFFERENT table than its own source column.
                    # `alias != bare-name` skips the degenerate `col col`
                    # re-alias, which already merges via node dedup.
                    source_name = _clean(inner.name or "")
                    for cte_n in scope.ctes:
                        key = self._ci_find(self._cte_output_columns, cte_n)
                        if key is not None and source_name in self._cte_output_columns[key]:
                            attr_strategy, attr_table = "expr_alias", cte_n
                            break
                    if attr_table is None:
                        derived_matches = [
                            d for d in scope.deriveds
                            if self._ci_find(self._derived_output_columns, d)
                            is not None and source_name in self._derived_output_columns[
                                self._ci_find(self._derived_output_columns, d)]]
                        if len(derived_matches) == 1:
                            d_name = derived_matches[0]
                            d_key = self._ci_find(self._derived_output_columns, d_name)
                            two = self._derived_output_columns[d_key][source_name]
                            attr_strategy, attr_table = "expr_alias", (two or d_name)
                    if attr_table is None:
                        distinct = self._distinct_scope_tables(scope)
                        if len(distinct) == 1:
                            _db, _name = distinct[0]
                            if source_name.lower() == _name.lower():
                                # A3: R6 guard mirrored from _register_column —
                                # the alias inherits EXACTLY what its source
                                # column gets (S3 refuses field==table-name
                                # collisions); the collision is counted there.
                                pass
                            elif _db.lower() in _SYSTEM_SCHEMAS:
                                attr_strategy, attr_table = "sys", SYSTEM_TABLE_SENTINEL
                            else:
                                attr_strategy, attr_table = "plain_alias", _name
            elif output_container is not None:
                # S2: expression output (Sum/Cast/Case/Window/Func/…)
                # → the statement's output container (⟐ output / ⟐ subqN …).
                attr_strategy, attr_table = "expr_alias", output_container

        # Fix C (2b): record this projection as an output column of the
        # derived table being walked. Bare columns (no alias) record their
        # own name (same semantics as CTE output columns). two_hop carries
        # the physical table when the output is itself an S1 alias of a
        # plain column — downstream refs then skip to the source table;
        # otherwise None → one-hop to the derived alias.
        if derived_alias:
            # Fix C (2b): record this projection as an output column of the
            # derived table being walked. Bare columns (no alias) record
            # their own name (same semantics as CTE output columns). A
            # qualified star (d.*) expands the referenced CTE's/derived's
            # recorded outputs (fin_query8) with their two_hop chains.
            # two_hop carries the physical table when the output is itself
            # an S1 alias of a plain column — downstream refs then skip to
            # the source table; otherwise None → one-hop to the derived
            # alias. Set-op branches (setop_body) never get two_hop — the
            # branch source sets differ (q71), one-hop only.
            star_out = self._expand_star_columns(inner, scope)
            if star_out:
                out_map = self._derived_output_columns.setdefault(derived_alias, {})
                for rec, two in star_out.items():
                    out_map.setdefault(rec, two)
            elif alias:
                # L4: bare Star/Literal projections auto-name to junk ("*",
                # "1", …) — never resolvable output names; skip recording.
                if isinstance(inner, (exp.Star, exp.Literal)) and not explicit_alias:
                    pass
                else:
                    record_name = (_clean(inner.name)
                                   if isinstance(inner, exp.Column) and not explicit_alias
                                   else alias)
                    if (not explicit_alias and isinstance(inner, exp.Column)
                            and inner.table):
                        # L5: unaliased QUALIFIED projection
                        # (`SELECT t.col FROM t2 t`) — two-hop straight to
                        # the source column's physical table (S1 semantics
                        # without the alias var). Suppressed for set-op
                        # branches (per-branch sources differ, q71).
                        qualifier = _clean(inner.table or "")
                        src = (self._resolve_alias(qualifier, scope)
                               if qualifier else None)
                        two_hop = src if (src and not setop_body) else None
                    else:
                        two_hop = (attr_table
                                   if attr_strategy == "plain_alias"
                                   and not setop_body else None)
                    self._derived_output_columns.setdefault(
                        derived_alias, {})[record_name] = two_hop

        # Existing table attribution inside the expression wins (e.g. scalar
        # subquery aliases already carry their inner tables).
        apply_tables = src_tables
        if attr_strategy is not None and not src_tables:
            apply_tables = [attr_table]

        defined_in = context

        def_site = None
        if var_type == VariableType.AGGREGATE and not explicit_alias:
            # I1 (hl=0 fix): an unaliased aggregate projection auto-names
            # to a sanitized fragment ("MAXt.data_dt") that never matches
            # the token stream — anchor the def line on the raw
            # expression's OWN tokens (MAX ( t . data_dt )), which appear
            # verbatim in the stream.
            run = _name_token_run(sql_expr)
            if run:
                def_site = ([run], None, context)

        var = self._add(alias, var_type,
                        sql_expr=sql_expr,
                        defined_in=defined_in, context=context,
                        source_cols=src_cols, source_tables=apply_tables,
                        is_output=(not is_cte),
                        def_site=def_site)
        if (var is not None and not explicit_alias
                and not isinstance(inner, (exp.Column, exp.Star))):
            # L4 (part 2): this output had NO alias, so its name is the
            # expression-fragment auto-name above — a projection-shape
            # artifact, not a column name. A bare column's auto-name IS its
            # own column name (kept); a Star never reaches `_add` as a field.
            self._auto_named_outputs.add(var.id)
        if var is not None and attr_strategy is not None and not src_tables:
            self._resolution_stats["resolved_by"][attr_strategy] += 1

        # Register columns inside the expression — needed for BELONGS_TO edges
        self._walk_columns_in_expr(inner, context, defined_in="SELECT expr",
                                   scope=scope)

    # ── Set operations (UNION / INTERSECT / EXCEPT) ─────────────────

    def _walk_setop(self, setop, op_type: str, context: str,
                    derived_alias: str | None = None,
                    cte_name: str | None = None,
                    outer: _SelectScope | None = None):
        """Walk UNION ALL, INTERSECT, EXCEPT — process all branches.

        `derived_alias` (q71): the set-op is the body of an aliased derived
        table — each branch's outputs are recorded as the derived table's
        output columns (Fix C). two_hop is suppressed per branch: branch
        source sets differ, so downstream refs resolve one-hop to the
        derived alias only (never guess).
        `cte_name` (fin_query8): the set-op is the body of a CTE — each
        branch's outputs are recorded as the CTE's output columns (S2),
        exactly like the exp.Select CTE-body path.
        """
        self._add(f"{op_type.lower()}_result", VariableType.UNION_BRANCH,
                  sql_expr=_sql(setop),
                  defined_in=op_type, context=context)

        sides = []
        if hasattr(setop, 'left') and hasattr(setop, 'right'):
            sides = [setop.left, setop.right]
        else:
            if setop.this is not None:
                sides.append(setop.this)
            if hasattr(setop, 'expression') and setop.expression is not None:
                sides.append(setop.expression)

        for i, side in enumerate(sides):
            if side is not None:
                side_ctx = f"{context}/union{i}"
                if isinstance(side, exp.Select):
                    # WITH-clause parity with process_statement (a branch may
                    # carry its own WITH when parenthesized).
                    with_clause = side.args.get("with") or side.args.get("with_")
                    if with_clause:
                        self._walk_cte_definitions(with_clause, context=side_ctx)
                    self._walk_select(side, side_ctx, is_cte=False,
                                      derived_alias=derived_alias,
                                      cte_name=cte_name, setop_body=True,
                                      outer=outer)
                elif isinstance(side, (exp.Union, exp.Intersect, exp.Except)):
                    # nested set-op (UNION of UNIONs) — thread through
                    self._walk_setop(side, type(side).__name__.upper(),
                                     side_ctx, derived_alias=derived_alias,
                                     cte_name=cte_name, outer=outer)
                else:
                    self.process_statement(side, side_ctx, outer=outer)

    # ── MERGE walker ────────────────────────────────────────────────

    def _walk_merge(self, merge: exp.Merge, context: str,
                    outer: _SelectScope | None = None):
        """Walk a MERGE statement."""
        # D-series: record the merge's own anchor first so all its vars
        # (target, USING, ON, WHEN) scope line lookups to this statement.
        self._record_stmt_anchor(context, merge)
        # M3b: the merge ON/WHEN walks get a real scope so qualified refs
        # resolve via scope/script alias maps and evidence lines anchor to
        # the merge statement itself.
        merge_scope = _SelectScope(owner=merge, key=context, outer=outer)
        target = merge.args.get("target") or merge.args.get("this")
        target_name = ""
        if target and isinstance(target, exp.Table):
            target_name = _clean(target.name or "")
            alias = _clean(target.alias_or_name or "")
            self._add(target_name, VariableType.MERGE_TARGET,
                      sql_expr=_sql(target), defined_in="MERGE", context=context)
            if alias and alias != target_name:
                self._add(alias, VariableType.MERGE_TARGET,
                          sql_expr=f"{target_name} AS {alias}", defined_in="MERGE",
                          context=context, source_tables=[target_name])
                # M3b: mirror _register_table — the target alias must resolve
                # canonically (`tgt.id` → evidence under "customers", never
                # under the alias spelling).
                merge_scope.aliases[alias] = target_name
                self._alias_names.setdefault(
                    self._scope_top(context), set()).add(alias.casefold())
            self._physical_table_names.add(target_name.casefold())

        # Source (USING)
        using = merge.args.get("using")
        if using:
            if isinstance(using, exp.Table):
                self._register_table(using, context, scope=merge_scope)
            elif isinstance(using, exp.Subquery):
                # Walk in SAME context so DML phase finds source columns
                sub_alias = _clean(using.alias or "")
                if sub_alias:
                    self._derived_aliases.setdefault(
                        self._scope_top(context), set()).add(sub_alias.casefold())
                    # I1 def site: the alias identifier right after ')'
                    self._add(sub_alias, VariableType.SUBQUERY,
                              sql_expr=_sql(using.this),
                              defined_in="MERGE USING", context=context,
                              def_site=([[")", sub_alias]], merge, context))
                self._walk_select(using.this, context, is_cte=False,
                                  outer=merge_scope)

        # ON condition
        on_expr = merge.args.get("on")
        if on_expr:
            self._walk_columns_in_expr(on_expr, context, defined_in="MERGE ON",
                                       scope=merge_scope)

        # WHEN clauses
        for when in (merge.args.get("whens") or []):
            # E3a/5: sqlglot MergeWhen nodes always have this=None — the
            # branch action (exp.Update / exp.Insert) lives in `then`.
            action = when.this or when.args.get("then")
            # S4a source 2: MERGE INTO t … WHEN UPDATE SET a=… — the SET
            # targets are canonical schema evidence for t (evidence only).
            if target_name and isinstance(action, exp.Update):
                stmt_line = self._statement_anchor(merge)
                for e in (action.expressions or []):
                    if (isinstance(e, _UPDATE_SET_NODES)
                            and isinstance(e.this, exp.Column)):
                        cname = _clean(e.this.name or "")
                        if cname:
                            self._script_schemas.setdefault(
                                target_name, {}).setdefault(cname, stmt_line)
            if isinstance(action, exp.Update):
                # E3a/5: walk the WHEN UPDATE SET assignments — bare SET
                # targets become fields of the MERGE target table; RHS
                # columns (target.total_spent + source.total_spent) walk
                # the normal chain against the merge scope.
                for e in (action.expressions or []):
                    if not isinstance(e, _UPDATE_SET_NODES):
                        continue
                    lhs = e.this
                    if isinstance(lhs, exp.Column):
                        # R45 Fix E: record the write slot (both spellings
                        # of a qualified LHS write the same column).
                        self._merge_written[context].add(
                            _clean(lhs.name or "").casefold())
                        if _clean(lhs.table or ""):
                            # qualified LHS (target.a = …) — S1 chain
                            self._register_column(lhs, context,
                                                  defined_in="MERGE UPDATE SET",
                                                  scope=merge_scope)
                        elif target_name:
                            lname = _clean(lhs.name or "")
                            if lname:
                                self._add(lname, VariableType.COLUMN,
                                          sql_expr=_sql(lhs),
                                          defined_in="MERGE UPDATE SET",
                                          context=context,
                                          source_tables=[target_name],
                                          def_site=([["set", lname],
                                                     [lname]], None,
                                                    context, True, True))
                    rhs = e.args.get("expression")
                    if rhs is not None:
                        self._walk_columns_in_expr(rhs, context,
                                                   defined_in="MERGE UPDATE SET",
                                                   scope=merge_scope)
            elif isinstance(action, exp.Insert):
                # E3a/5: WHEN NOT MATCHED THEN INSERT (cols) VALUES (vals)
                # — the insert column list defines fields of the MERGE
                # target; the VALUES expressions walk the normal chain.
                col_tuple = (action.this
                             if isinstance(action.this, exp.Tuple) else None)
                if col_tuple and target_name:
                    for col in (col_tuple.expressions or []):
                        if isinstance(col, exp.Column):
                            cname = _clean(col.name or "")
                            if cname:
                                # R45 Fix E: the INSERT column list is a
                                # write slot too.
                                self._merge_written[context].add(
                                    cname.casefold())
                                self._add(cname, VariableType.COLUMN,
                                          sql_expr=_sql(col),
                                          defined_in="MERGE INSERT",
                                          context=context,
                                          source_tables=[target_name])
                val_expr = action.expression
                if val_expr is not None:
                    self._walk_columns_in_expr(val_expr, context,
                                               defined_in="MERGE WHEN",
                                               scope=merge_scope)

    # ── UPDATE walker ───────────────────────────────────────────────

    def _walk_update(self, update: exp.Update, context: str,
                     outer: _SelectScope | None = None):
        """Walk an UPDATE statement (E3a/1).

        A dedicated walker — the generic SELECT walk treats `expressions`
        as SELECT projections, but for exp.Update they are the SET
        assignments. Here:
          - the target table registers with dml="UPDATE" (the dependency
            graph's DML phase keys on defined_in containing UPDATE);
          - bare SET targets become COLUMN vars whose source_tables is the
            TARGET table (fields of the updated table, never ⟐ output);
          - qualified SET LHS (t.a = …) walk the normal S1 chain;
          - SET RHS + WHERE walk the normal column chain — subqueries and
            NOT EXISTS bodies get their own subqN/existsN contexts;
          - a ⟐ output VT exists so DML edges route through it.
        """
        # D-series: statement anchor for line-scoped resolution.
        self._record_stmt_anchor(context, update)
        scope = _SelectScope(owner=update, key=context, outer=outer)

        # Output VT for DML routing (same label convention as _walk_select).
        label = "output"
        if context.startswith("CTE{") and "/" not in context and ":" not in context:
            label = context[4:context.index("}")]
        vt_name = f"⟐ {label}"
        head_run = _statement_head_run(update)
        vt_var = self._add(vt_name, VariableType.VIRTUAL_TABLE,
                           sql_expr=_sql(update), defined_in=context,
                           context=context,
                           def_site=([head_run, head_run[:2]], update,
                                     context))
        # E5 (audit item 1): same line<1 fallback as _walk_select — the
        # ⟐ VT must land on the statement's own UPDATE-keyword line when
        # def-site resolution came up empty. Never touches a valid line.
        if vt_var is not None and vt_var.line_start < 1:
            fl = self._vt_fallback_line(update, context)
            if fl > 0:
                vt_var.line_start = fl
                vt_var.line_end = fl

        # Target table (exp.Update.this) — UPDATE-marked for the DML phase.
        target = update.args.get("this")
        target_name = ""
        if target and isinstance(target, exp.Table):
            target_name = _clean(target.name or "")
            self._register_table(target, context, dml="UPDATE", scope=scope)
            # S4a source 2: SET targets are canonical schema evidence for
            # the target table (evidence only — mirrored from _walk_select).
            if target_name:
                stmt_line = self._statement_anchor(update)
                for e in (update.expressions or []):
                    if (isinstance(e, _UPDATE_SET_NODES)
                            and isinstance(e.this, exp.Column)):
                        cname = _clean(e.this.name or "")
                        if cname:
                            self._script_schemas.setdefault(
                                target_name, {}).setdefault(cname, stmt_line)

        # SET clauses — sqlglot puts the assignments in `expressions`.
        for e in (update.expressions or []):
            if not isinstance(e, _UPDATE_SET_NODES):
                continue
            lhs = e.this
            if isinstance(lhs, exp.Column) and _clean(lhs.table or ""):
                # Qualified LHS (t.a = …) — normal chain (S1 alias
                # resolution through the statement scope).
                self._register_column(lhs, context, defined_in="UPDATE SET",
                                      scope=scope)
            elif isinstance(lhs, exp.Column) and target_name:
                # Bare SET target: a field OF THE TARGET TABLE — the UPDATE
                # defines this column of the target (E3a/1: SET targets were
                # previously not extracted at all, or attributed to ⟐ output).
                lname = _clean(lhs.name or "")
                if lname:
                    self._add(lname, VariableType.COLUMN,
                              sql_expr=_sql(lhs),
                              defined_in="UPDATE SET", context=context,
                              source_tables=[target_name],
                              def_site=([["set", lname], [lname]], None,
                                        context, True, True))
            rhs = e.args.get("expression")
            if rhs is not None:
                self._walk_columns_in_expr(rhs, context,
                                           defined_in="UPDATE SET",
                                           scope=scope)

        # FROM / JOIN clauses (MySQL UPDATE ... FROM / JOIN forms)
        from_exp = update.args.get("from") or update.args.get("from_")
        if from_exp:
            self._walk_from(from_exp, context, scope)
        for join in (update.args.get("joins") or []):
            self._walk_join(join, context, scope)

        # WHERE — after SET so bare refs dedup against the SET targets
        cond = update.args.get("where")
        if cond:
            self._walk_columns_in_expr(cond, context, defined_in="WHERE",
                                       scope=scope)

        # ORDER BY (MySQL UPDATE ... ORDER BY ... LIMIT)
        order = update.args.get("order")
        if order:
            for e in (order.expressions if hasattr(order, 'expressions') else [order]):
                self._walk_columns_in_expr(e, context, defined_in="ORDER BY",
                                           scope=scope)

    # ── INSERT / CREATE walkers ─────────────────────────────────────

    def _walk_insert(self, insert: exp.Insert, context: str,
                     outer: _SelectScope | None = None,
                     merged_select: exp.Select | exp.Union
                     | exp.Intersect | exp.Except | None = None):
        """Walk an INSERT statement (INSERT INTO ... SELECT/VALUES).

        `merged_select` (R44 F1): the following standalone SELECT for a
        bare INSERT — walked as this statement's source, replacing the ⟐
        insert VALUES anchor (see process_statement).
        """
        # D-series: record BEFORE the into/target and PARTITION registration.
        # Anchors are last-wins (I1) — the source SELECT's walk later
        # overwrites "TOP{n}" with its own line — but the target and
        # PARTITION vars register BEFORE that walk, so they still resolve
        # against the INSERT's anchor (line 160), not the SELECT's (161).
        self._record_stmt_anchor(context, insert)
        into = insert.args.get("into") or insert.args.get("this")
        if isinstance(into, exp.Schema):
            # S4a source 2: INSERT INTO t (a,b) — the target column list is
            # canonical schema evidence for t. EVIDENCE ONLY — no column
            # variables are created (total_columns unchanged). A missing
            # list (plain INSERT INTO t SELECT …) contributes no evidence.
            target_canon = (_clean(into.this.name or "")
                            if isinstance(into.this, exp.Table) else "")
            if target_canon:
                stmt_line = self._statement_anchor(insert)
                for col_ident in (into.expressions or []):
                    cname = _clean(col_ident.name or "")
                    if cname:
                        self._script_schemas.setdefault(
                            target_canon, {}).setdefault(cname, stmt_line)
            into = into.this
        # name is defined by the Table branch below; init defensively so the
        # PARTITION registration never hits a NameError for exotic targets.
        name = ""
        if isinstance(into, exp.Table):
            # Register target with INSERT marking (not default "FROM").
            # I1 def site: the name token after the target keyword — the
            # INSERT keyword runs cover INTO / INTO TABLE / OVERWRITE TABLE
            # forms ("INSERT INTO TABLE x" at L211, "INSERT OVERWRITE TABLE
            # x" at L160), with the bare-name run as the graceful fallback.
            name = _clean(into.name or "")
            alias = _clean(into.alias_or_name or "")
            if name:
                self._physical_table_names.add(name.casefold())
                self._add(name, VariableType.TABLE,
                          sql_expr=name, defined_in="INSERT", context=context,
                          def_site=([["insert", "into", name],
                                     ["insert", "into", "table", name],
                                     ["insert", "overwrite", "table", name],
                                     [name]], insert, context))
                if alias and alias != name:
                    self._add(alias, VariableType.TABLE,
                              sql_expr=f"{name} AS {alias}",
                              defined_in="INSERT", context=context,
                              source_tables=[name],
                              is_alias_handle=True,
                              def_site=([[name, alias]], insert, context))
        # v3.3.140: INSERT-with-partition target columns become column vars
        # (e.g. INSERT OVERWRITE TABLE t PARTITION(data_dt='$(load_date)',
        # CHARGE_DEPARTMENT)) so the write side seeds table.field flow.
        # NOTE: sqlglot parses a bare PARTITION(...) after the target table
        # onto the TABLE node (verified 30.8.0/30.12.0, all dialects);
        # Insert.partition is only the Hive-style PARTITION BY clause — check
        # both locations so the write-side seed exists regardless of form.
        part = insert.args.get("partition")
        if not isinstance(part, exp.Partition) and isinstance(into, (exp.Table, exp.Schema)):
            part = into.args.get("partition")
        if isinstance(part, exp.Partition) and name:
            for part_expr in (part.expressions or []):
                col = None
                if isinstance(part_expr, exp.Column):
                    col = part_expr
                elif isinstance(part_expr, exp.EQ) and isinstance(part_expr.left, exp.Column):
                    col = part_expr.left
                if col is not None:
                    pname = _clean(col.name or "")
                    if pname:
                        # sql_expr is the COLUMN, not the whole EQ: line
                        # resolution is the bare column-name token run in
                        # the INSERT's own scope — the rendered
                        # "data_dt = '$(load_date)'" EQ never occurs
                        # verbatim in the source
                        # ("PARTITION(data_dt='$(load_date)', …)"), but the
                        # bare column token does — same convention as
                        # _register_column.
                        self._add(pname, VariableType.COLUMN, sql_expr=_sql(col),
                                  defined_in="PARTITION", context=context,
                                  source_tables=[name])
        # Walk the source SELECT (INSERT INTO ... SELECT)
        expr = insert.args.get("expression")
        if expr and isinstance(expr, (exp.Select, exp.Union)):
            self.process_statement(expr, context, outer=outer)
        elif merged_select is not None:
            # R44 F1: bare INSERT + following standalone SELECT (ODPS idiom)
            # — the SELECT IS this statement's source; walking it here keeps
            # ONE output VT per context (dependency_graph Phase 1c-extra2's
            # write leg needs exactly one).
            self.process_statement(merged_select, context, outer=outer)
        else:
            # VALUES-based INSERT — create a minimal VT anchor so the target
            # table isn't isolated (the DML phase can connect VT → target).
            # W6: creation line = the INSERT statement's head (keyword line).
            self._add("⟐ insert", VariableType.VIRTUAL_TABLE,
                      sql_expr="INSERT VALUES", defined_in="INSERT",
                      context=context,
                      def_site=([_statement_head_run(insert)], insert, context))
            # Also extract target columns if present in Schema
            if isinstance(into, exp.Schema):
                for col_expr in (into.expressions or []):
                    if isinstance(col_expr, exp.Column):
                        col_name = _clean(col_expr.name or "")
                        if col_name:
                            self._add(col_name, VariableType.COLUMN,
                                      sql_expr=_sql(col_expr),
                                      defined_in="INSERT", context=context)

    def _walk_create(self, create: exp.Create, context: str):
        """Walk a CREATE statement (TABLE, VIEW, MATERIALIZED VIEW, CTAS)."""
        # D-series: record the CREATE's own anchor first so its vars
        # (table, DDL columns, CTAS body) scope to this statement.
        self._record_stmt_anchor(context, create)
        kind = str(create.args.get("kind", "")).upper()
        table_expr = create.args.get("this")
        name = _clean(table_expr.name or "") if table_expr and isinstance(table_expr, exp.Table) else ""

        if kind == "VIEW":
            # CREATE VIEW / CREATE MATERIALIZED VIEW
            if name:
                self._physical_table_names.add(name.casefold())
                # I1 def site: the name token after the CREATE keyword
                # (bare-name run covers OR REPLACE / MATERIALIZED forms)
                self._add(name, VariableType.VIEW,
                          sql_expr=_sql(create), defined_in="CREATE VIEW",
                          context=context,
                          def_site=([["create", "view", name], [name]],
                                    create, context))
            # Walk the inner SELECT defining the view
            # L-E4: statement-owning, case-folded scope key (see _scope_top).
            inner = create.args.get("expression")
            vctx = f"VIEW@{context}:{name.casefold()}" if name else context
            if inner and isinstance(inner, exp.Select):
                self._walk_select(inner, vctx, is_cte=False)
            elif inner and isinstance(inner, (exp.Union, exp.Intersect, exp.Except)):
                self._walk_setop(inner, type(inner).__name__.upper(), vctx)

        elif kind == "TABLE":
            # S4a canonical name: a Schema node (`CREATE TABLE t (a INT, …)`)
            # carries the name on .this — `table_expr.name` is empty for it.
            canonical = name
            if isinstance(table_expr, exp.Schema):
                canonical = (_clean(table_expr.this.name or "")
                             if isinstance(table_expr.this, exp.Table) else canonical)
            if name:
                self._physical_table_names.add(name.casefold())
                # I1 def site: the name token after the CREATE keyword
                self._add(name, VariableType.TABLE,
                          sql_expr=_sql(create), defined_in="CREATE TABLE",
                          context=context,
                          def_site=([["create", "table", name], [name]],
                                    create, context))
            # S4a source 3: DDL column definitions (CREATE TABLE t (a INT, …))
            # → canonical schema evidence. REPORT-ONLY — no column variables.
            if canonical and isinstance(table_expr, exp.Schema):
                stmt_line = self._statement_anchor(create)
                for col_def in (table_expr.expressions or []):
                    if isinstance(col_def, exp.ColumnDef) and hasattr(col_def.this, "name"):
                        cname = _clean(col_def.this.name or "")
                        if cname:
                            self._script_schemas.setdefault(
                                canonical, {}).setdefault(cname, stmt_line)
            # CTAS: CREATE TABLE ... AS SELECT — walk the inner SELECT
            # L-E4: statement-owning, case-folded scope key (see _scope_top).
            inner = create.args.get("expression")
            cctx = f"CTAS@{context}:{name.casefold()}" if name else context
            if inner and isinstance(inner, exp.Select):
                self._walk_select(inner, cctx, is_cte=False)
                # S4a source 3: CTAS without a column list → the SELECT
                # output aliases are positional column evidence for the new
                # table (same semantics as the Bug 41 DML mapping).
                if canonical and not isinstance(table_expr, exp.Schema):
                    stmt_line = self._statement_anchor(create)
                    for p in (inner.expressions or []):
                        pname = self._projection_output_name(p)
                        if pname:
                            self._script_schemas.setdefault(
                                canonical, {}).setdefault(pname, stmt_line)
            elif inner and isinstance(inner, (exp.Union, exp.Intersect, exp.Except)):
                self._walk_setop(inner, type(inner).__name__.upper(), cctx)
