"""Residual-orphan fixes (2026-08-06): confirmed cases A/B/C.

Fix A (1c) — set-op scope edge: `x NOT IN (SELECT ... UNION SELECT ...)` —
   each set-op branch SELECT is walked with its OWN scope so branch columns
   resolve via S3 (single-table branch scope) instead of being raw-walked
   only as unattributed outer-context phantom copies.
Fix B (2a) — implicit aliases of bare columns (S1 extension): the
   alias→source-column→table chain — an alias of a plain BARE column
   inherits exactly what S3 would attribute the source column (single
   physical table scope only; never guess).
Fix C (2b) — derived-table output columns (S2 extension, two-hop): an
   aliased derived table's projection aliases are recorded like CTE output
   columns; an outer bare column matching exactly ONE visible derived
   table's output resolves one-hop to the derived alias, or two-hop to the
   output column's own source table when it is an S1 alias of a plain
   column.

Every fix keeps the never-guess invariant: ambiguous cases (≥2 tables in
scope, ≥2 candidate derived tables, no followable chain) stay unresolved.
"""

import io
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.models.variable import VariableType


def _col_vars(result):
    return [v for v in result.variables if v.variable_type == VariableType.COLUMN]


def _find(result, name, var_type=VariableType.COLUMN):
    hits = [v for v in result.variables
            if v.name == name and v.variable_type == var_type]
    assert hits, f"no {var_type.value} var named {name!r} in {[v.name for v in result.variables]}"
    return hits[0]


def _find_src(result, name, src_tables, var_type=VariableType.COLUMN, context=None):
    """Find the var with the given name attributed to exactly src_tables.

    Subquery/set-op branch copies share names with outer phantom copies —
    this targets the attributed one; pass context to disambiguate.
    """
    hits = [v for v in result.variables
            if v.name == name and v.variable_type == var_type
            and v.source_tables == src_tables
            and (context is None or v.context == context)]
    assert hits, (f"no {var_type.value} var named {name!r} with "
                  f"source_tables={src_tables} ctx={context} in "
                  f"{[(v.name, v.context, v.source_tables) for v in result.variables]}")
    return hits[0]


# ── Fix A: set-op branch scopes (S3 scope bucket) ─────────────────────────

def test_fix_a_setop_branches_attributed_in_subquery():
    """spider 052 pattern: NOT IN (SELECT ... UNION SELECT ...) — both
    branch columns attribute to the branch's single table Flights."""
    r = extract_variables_from_sql(
        "SELECT AirportName FROM Airports WHERE AirportCode NOT IN "
        "(SELECT SourceAirport FROM Flights "
        "UNION SELECT DestAirport FROM Flights)", "fixa1")
    assert _find_src(r, "SourceAirport", ["Flights"]).source_tables == ["Flights"]
    assert _find_src(r, "DestAirport", ["Flights"]).source_tables == ["Flights"]
    assert r.resolution_stats["resolved_by"]["scope"] >= 2, r.resolution_stats
    assert "SourceAirport" not in r.resolution_stats["unresolved"], r.resolution_stats
    assert "DestAirport" not in r.resolution_stats["unresolved"], r.resolution_stats


def test_fix_a_intersect_branch_attributed():
    r = extract_variables_from_sql(
        "SELECT x FROM a WHERE x IN (SELECT y FROM b "
        "INTERSECT SELECT z FROM c)", "fixa2")
    assert _find_src(r, "y", ["b"]).source_tables == ["b"]
    assert _find_src(r, "z", ["c"]).source_tables == ["c"]
    assert r.resolution_stats["resolved_by"]["scope"] >= 2, r.resolution_stats


def test_fix_a_exists_setop_branch_attributed():
    r = extract_variables_from_sql(
        "SELECT x FROM t WHERE EXISTS "
        "(SELECT y FROM u UNION SELECT z FROM v)", "fixa3")
    assert _find_src(r, "y", ["u"]).source_tables == ["u"]
    assert _find_src(r, "z", ["v"]).source_tables == ["v"]
    assert "y" not in r.resolution_stats["unresolved"], r.resolution_stats
    assert "z" not in r.resolution_stats["unresolved"], r.resolution_stats


def test_fix_a_outer_phantom_copy_never_guessed():
    """Set-op subquery bodies are walked ONCE — no outer-context phantoms.

    M4: the raw walk no longer descends into a Subquery/EXISTS whose body
    is a set-op (the explicit _walk_setop covers it with per-branch
    scopes), so the branch columns register only in their own branch
    contexts — where they resolve via S3 (single-table branch scopes) —
    and are never attributed to the outer scope (never guess)."""
    r = extract_variables_from_sql(
        "SELECT AirportName FROM Airports WHERE AirportCode NOT IN "
        "(SELECT SourceAirport FROM Flights "
        "UNION SELECT DestAirport FROM Flights)", "fixa4")
    # M4: the outer-context phantom copies no longer exist (they previously
    # double-registered every branch column, inflating total_columns).
    phantoms = [v for v in _col_vars(r)
                if v.name in ("SourceAirport", "DestAirport") and v.context == "TOP0"]
    assert phantoms == [], phantoms
    # the branch copies resolve inside their own branch scopes (single table)
    branch = [v for v in _col_vars(r)
              if v.name in ("SourceAirport", "DestAirport")
              and v.context.startswith("TOP0/subq")]
    assert branch, "branch-context copies should exist"
    assert all(v.source_tables == ["Flights"] for v in branch), branch
    assert "SourceAirport" not in r.resolution_stats["unresolved"]
    assert "DestAirport" not in r.resolution_stats["unresolved"]


def test_m4_setop_subquery_no_double_count():
    """M4: the raw walk no longer descends into set-op subquery bodies, so
    branch columns register ONCE (in their own branch scopes) — the spider
    pattern's total_columns is the logical column count (4, not 6)."""
    r = extract_variables_from_sql(
        "SELECT x FROM t WHERE id IN "
        "(SELECT a FROM u1 UNION SELECT b FROM u2)", "m4_spider")
    stats = r.resolution_stats
    assert stats["total_columns"] == 4, stats  # x, id, a, b — no duplicates
    names = sorted(v.name for v in _col_vars(r))
    assert names == ["a", "b", "id", "x"], names
    assert stats["unresolved"] == [], stats  # a/b resolve in branch scopes


# ── Fix B: alias→source-column→table chain for bare columns (plain_alias) ─

def test_fix_b_implicit_alias_of_bare_column_chain():
    """tpcds q91 pattern: `cc_call_center_id Call_Center` — the alias var
    inherits the source column's S3 attribution (single-table scope)."""
    r = extract_variables_from_sql(
        "SELECT cc_call_center_id Call_Center FROM call_center cc", "fixb1")
    cc = _find_src(r, "Call_Center", ["call_center"])
    assert cc.source_tables == ["call_center"], cc
    assert r.resolution_stats["resolved_by"]["plain_alias"] == 1, r.resolution_stats
    assert "Call_Center" not in r.resolution_stats["unresolved"], r.resolution_stats


def test_fix_b_explicit_alias_of_bare_column_chain():
    """sqlglot parses implicit and AS-aliases identically — the same chain
    applies to `SELECT amount AS amt FROM orders`."""
    r = extract_variables_from_sql(
        "SELECT amount AS amt FROM orders", "fixb2")
    assert _find_src(r, "amt", ["orders"]).source_tables == ["orders"]
    assert r.resolution_stats["resolved_by"]["plain_alias"] == 1, r.resolution_stats
    assert "amt" not in r.resolution_stats["unresolved"], r.resolution_stats


def test_fix_b_multi_table_scope_stays_unresolved():
    """Guard: bare source column under ≥2 physical tables — the chain is
    NOT followable, never guess (q91's 7-table scope stays orphaned)."""
    r = extract_variables_from_sql(
        "SELECT x y FROM a JOIN b ON a.id = b.id", "fixb3")
    assert _find(r, "y").source_tables == []
    assert r.resolution_stats["resolved_by"]["plain_alias"] == 0, r.resolution_stats
    # both the alias and its bare source column are unattributed
    assert "y" in r.resolution_stats["unresolved"], r.resolution_stats
    assert "x" in r.resolution_stats["unresolved"], r.resolution_stats


def test_fix_b_degenerate_same_name_alias_untouched():
    """Guard: `SELECT amount amount FROM orders` — alias equals the bare
    name (auto-name collision) — NOT treated as an implicit alias; the
    single var keeps its plain S3 attribution (scope bucket)."""
    r = extract_variables_from_sql(
        "SELECT amount amount FROM orders", "fixb4")
    assert r.resolution_stats["resolved_by"]["plain_alias"] == 0, r.resolution_stats
    assert r.resolution_stats["resolved_by"]["scope"] == 1, r.resolution_stats
    assert _find_src(r, "amount", ["orders"]).source_tables == ["orders"]
    assert r.resolution_stats["unresolved"] == [], r.resolution_stats


def test_m2_alias_of_cte_resolved_column_lands_same_table():
    """M2: an alias of a bare column whose source resolves via the S2 CTE
    chain must land on the SAME table as its source column — previously the
    Fix B path only consulted the S3 physical scope, so `id AS c` was
    attributed to t1 while its own source column id resolved to the CTE w."""
    r = extract_variables_from_sql(
        "WITH w AS (SELECT id FROM t2) SELECT id AS c FROM t1, w", "m2")
    c = _find_src(r, "c", ["w"], context="TOP0")
    assert c.source_tables == ["w"], c
    id_src = _find_src(r, "id", ["w"], context="TOP0")
    assert id_src.source_tables == ["w"], id_src  # same table as its source
    assert r.resolution_stats["resolved_by"]["expr_alias"] >= 1, r.resolution_stats
    assert "c" not in r.resolution_stats["unresolved"], r.resolution_stats


def test_m2_alias_of_derived_output_column_two_hop():
    """M2 mirrors the Fix C chain too: an alias of a derived-table output
    resolves via the derived chain (two-hop when the output carries one)."""
    r = extract_variables_from_sql(
        "SELECT x AS c FROM t1, (SELECT t.x FROM t) d", "m2d")
    c = _find_src(r, "c", ["t"], context="TOP0")
    assert c.source_tables == ["t"], c  # two-hop to the source table
    assert r.resolution_stats["resolved_by"]["expr_alias"] >= 1, r.resolution_stats


def test_fix_b_qualified_alias_behavior_unchanged():
    """Existing S1 (qualified column) keeps its bucket and semantics."""
    r = extract_variables_from_sql(
        "SELECT sb.total_amount AS batch_total FROM settlement_batch sb", "fixb5")
    assert _find_src(r, "batch_total", ["settlement_batch"]).source_tables == \
        ["settlement_batch"]
    assert r.resolution_stats["resolved_by"]["plain_alias"] == 1, r.resolution_stats
    assert "batch_total" not in r.resolution_stats["unresolved"], r.resolution_stats


# ── Fix C: derived-table output columns (expr_alias, one-hop + two-hop) ───

def test_fix_c_derived_output_one_hop():
    """q93 pattern: `... end act_sales` inside `FROM (...) t`, then
    `sum(act_sales)` outside — the outer bare ref chains to the derived
    alias t."""
    r = extract_variables_from_sql(
        "SELECT sum(act_sales) FROM "
        "(SELECT ss_item_sk, "
        "case when a then b else c end act_sales "
        "FROM store_sales) t", "fixc1")
    outer = _find_src(r, "act_sales", ["t"])
    assert outer.context == "TOP0", outer
    assert outer.source_tables == ["t"], outer
    assert r.resolution_stats["resolved_by"]["expr_alias"] >= 1, r.resolution_stats
    assert "act_sales" not in r.resolution_stats["unresolved"], r.resolution_stats


def test_fix_c_derived_unaliased_projection_output():
    """An unaliased projection is also an output column of the derived
    table (same semantics as CTE output columns)."""
    r = extract_variables_from_sql(
        "SELECT ss_customer_sk FROM "
        "(SELECT ss_customer_sk FROM store_sales) d", "fixc2")
    outer = _find_src(r, "ss_customer_sk", ["d"])
    assert outer.context == "TOP0", outer
    assert "ss_customer_sk" not in r.resolution_stats["unresolved"], r.resolution_stats


def test_fix_c_derived_output_two_hop_to_source():
    """q93 two-hop: when the derived output column is itself an S1 alias
    of a plain column, the outer bare ref skips to the source table."""
    r = extract_variables_from_sql(
        "SELECT y FROM (SELECT t.x AS y FROM t) d", "fixc3")
    outer = _find_src(r, "y", ["t"], context="TOP0")
    assert outer.source_tables == ["t"], outer
    assert r.resolution_stats["resolved_by"]["expr_alias"] >= 1, r.resolution_stats
    assert "y" not in r.resolution_stats["unresolved"], r.resolution_stats


def test_fix_c_derived_from_join_visible():
    """JOINed derived tables are visible to the enclosing scope too."""
    r = extract_variables_from_sql(
        "SELECT z FROM t1 JOIN (SELECT sum(a) z FROM t2) d ON t1.id = d.a",
        "fixc4")
    outer = _find_src(r, "z", ["d"], context="TOP0")
    assert outer.source_tables == ["d"], outer
    assert "z" not in r.resolution_stats["unresolved"], r.resolution_stats


def test_fix_c_unnamed_derived_untouched():
    """Guard: `FROM (SELECT ...)` without an alias — no output columns are
    recorded, the outer bare ref stays unresolved (untouched behavior)."""
    r = extract_variables_from_sql(
        "SELECT y FROM (SELECT x FROM t)", "fixc5")
    assert _find(r, "y").source_tables == []
    assert r.resolution_stats["unresolved"] == ["y"], r.resolution_stats


def test_fix_c_no_output_match_stays_unresolved():
    """Guard: outer bare column that no derived table outputs stays
    unresolved (no physical tables in scope)."""
    r = extract_variables_from_sql(
        "SELECT q FROM (SELECT x FROM t) d", "fixc6")
    assert _find(r, "q").source_tables == []
    assert r.resolution_stats["unresolved"] == ["q"], r.resolution_stats


def test_fix_c_two_candidate_deriveds_ambiguous():
    """Guard: two visible derived tables both output the name — ambiguous,
    the outer bare ref is never guessed. (The name itself is attributed in
    each branch scope, so it is not in the name-level unresolved report —
    the outer copy simply carries no source_tables.)"""
    r = extract_variables_from_sql(
        "SELECT x FROM (SELECT a x FROM t) d1, (SELECT b x FROM u) d2", "fixc7")
    outer = _find(r, "x", VariableType.COLUMN)
    top_copies = [v for v in _col_vars(r) if v.name == "x" and v.context == "TOP0"]
    assert top_copies and top_copies[0].source_tables == [], top_copies
    assert r.resolution_stats["resolved_by"]["expr_alias"] == 0, r.resolution_stats


def test_l3_fix_c_shadows_physical_table_owner():
    """L3 (kept by design): the Fix C derived-output check runs BEFORE the
    S3 single-physical check — a derived output column shadows a physical
    table that also owns the name. Corpus-audited (q71's spider pattern
    relies on the derived chain winning); pinned here so the precedence is
    never silently reordered."""
    r = extract_variables_from_sql(
        "SELECT x FROM (SELECT SUM(a) AS x FROM t1) d, t2", "l3")
    outer = _find_src(r, "x", ["d"], context="TOP0")
    assert outer.source_tables == ["d"], outer  # derived chain wins
    assert "x" not in r.resolution_stats["unresolved"], r.resolution_stats


def test_l4_junk_derived_output_names_not_recorded():
    """L4: bare Star/Literal projections auto-name to junk ("*", "1", …) —
    never recorded as derived output columns (they are not resolvable
    names). Explicit identifier aliases of literals ARE recorded."""
    r = extract_variables_from_sql(
        "SELECT s FROM (SELECT *, 1 FROM t2) d", "l4a")
    assert "s" in r.resolution_stats["unresolved"], r.resolution_stats  # no outputs
    r = extract_variables_from_sql(
        "SELECT x FROM (SELECT 1 AS x, 2 AS y FROM t2) d", "l4b")
    assert "x" not in r.resolution_stats["unresolved"], r.resolution_stats
    assert _find_src(r, "x", ["d"], context="TOP0").source_tables == ["d"]


def test_l5_unaliased_qualified_projection_two_hop():
    """L5: an unaliased QUALIFIED projection (`SELECT t.col FROM t2 t`)
    records its derived output with a two-hop to the source column's
    physical table — S1 semantics without the alias var."""
    r = extract_variables_from_sql(
        "SELECT col FROM (SELECT t.col FROM t2 t) d", "l5")
    outer = _find_src(r, "col", ["t2"], context="TOP0")
    assert outer.source_tables == ["t2"], outer
    assert "col" not in r.resolution_stats["unresolved"], r.resolution_stats


def test_fix_c_cte_behavior_unchanged():
    """Existing CTE output-column resolution keeps working alongside the
    derived-table mechanism."""
    r = extract_variables_from_sql(
        "WITH c AS (SELECT SUM(a) AS s FROM t) SELECT s FROM c", "fixc8")
    s = _find_src(r, "s", ["c"])
    assert s.context == "TOP0", s
    # v3.3.145 (B3): the CTE body output (SUM(a) AS s) is attributed to
    # its own CTE too — expr_alias = body output + downstream ref.
    assert r.resolution_stats["resolved_by"]["expr_alias"] == 2, r.resolution_stats
    assert r.resolution_stats["unresolved"] == [], r.resolution_stats


# ── Real-fixture-shaped integration (A+B+C in one script) ─────────────────

def test_fix_abc_real_fixture_shapes():
    """The three verified sample shapes end with no orphans in their
    attributed classes."""
    spider = extract_variables_from_sql(
        "SELECT AirportName FROM Airports WHERE AirportCode NOT IN "
        "(SELECT SourceAirport FROM Flights "
        "UNION SELECT DestAirport FROM Flights)", "fixture_spider")
    assert spider.resolution_stats["unresolved"] == [], spider.resolution_stats
    assert spider.resolution_stats["resolved_by"]["scope"] == 4, spider.resolution_stats

    q91 = extract_variables_from_sql(
        "SELECT cc_call_center_id Call_Center, cc_name Call_Center_Name "
        "FROM call_center cc", "fixture_q91")
    assert q91.resolution_stats["resolved_by"]["plain_alias"] == 2, q91.resolution_stats
    assert q91.resolution_stats["unresolved"] == [], q91.resolution_stats

    q93 = extract_variables_from_sql(
        "SELECT ss_customer_sk, sum(act_sales) sumsales "
        "FROM (SELECT ss_item_sk, ss_customer_sk, "
        "case when a is not null then (b - c) * d else e end act_sales "
        "FROM store_sales) t GROUP BY ss_customer_sk", "fixture_q93")
    assert q93.resolution_stats["resolved_by"]["expr_alias"] >= 3, q93.resolution_stats
    assert q93.resolution_stats["unresolved"] == [], q93.resolution_stats
