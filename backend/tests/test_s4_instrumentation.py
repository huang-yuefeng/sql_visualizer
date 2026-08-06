"""S4 Phase 2 — SELECT-side schema enrichment: AUTO-RESOLUTION.

Implements SOLUTION_DESIGN "SELECT-Side Schema Enrichment", Phase 2:

  * `script_schemas`   — per-script canonical schema map built from evidence
    sources only (qualified refs, DML target column lists, CREATE TABLE /
    CTAS column definitions). {table: {col_name: evidence_line}} — the
    evidence line is the line of the STATEMENT containing the evidence
    (statement-anchored, NOT a token text search); first occurrence wins.
    Evidence NEVER creates column variables.
  * `schema_candidates` — every unresolved bare column in a ≥2-table scope
    is stashed as {field, visible_tables, loc, contexts}. After the walk,
    the unique-owner post-pass AUTO-ATTRIBUTES: exactly one visible table's
    evidence contains the field (whole-name, case-insensitive, R6-guarded)
    → the var gets source_tables = [owner] (same shape as S3), the
    candidate is REMOVED (schema_candidates holds ONLY still-unresolved
    candidates — the S4b index re-test contract), the name leaves
    `unresolved`. 0/≥2 owners or R6 collisions stay unresolved and reported.
  * `r6_collision`     — candidates whose field equals a visible table name
    are NEVER attributed.

A3 (v3.3.134): the R6 guard is extended to S3 — `SELECT call_center FROM
call_center` (single visible table) is the same field==table-name ambiguity
and is likewise never attributed, counted in `r6_collision`, left
unresolved. The S1 bare-column alias mirror inherits the refusal.

Invariants under test: never guess (ambiguous/evidence-absent/R6 stay
unresolved), auto-attribution only under the confirmed rule, resolved vars
leave unresolved + schema_candidates, loc is statement-anchored.
"""

import sys
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


def _cand(stats, field):
    hits = [c for c in stats["schema_candidates"] if c["field"] == field]
    assert hits, f"no candidate for {field!r} in {stats['schema_candidates']}"
    return hits[0]


# ── Source 1: qualified column refs → script_schemas ────────────────────

def test_qualified_ref_evidence_builds_script_schemas():
    """Aliased / unaliased / db-qualified refs → canonical script_schemas
    (dict-of-dicts: {table: {col: evidence_line}})."""
    r = extract_variables_from_sql(
        "SELECT sb.total_amount FROM settlement_batch sb", "s4a_alias")
    assert r.resolution_stats["script_schemas"] == {
        "settlement_batch": {"total_amount": 1}}, r.resolution_stats

    r = extract_variables_from_sql("SELECT t.amount FROM t", "s4a_plain")
    assert r.resolution_stats["script_schemas"] == {"t": {"amount": 1}}

    r = extract_variables_from_sql("SELECT db.t.amount FROM db.t", "s4a_dbq")
    # db qualifier dropped — keyed by bare table name
    assert r.resolution_stats["script_schemas"] == {"t": {"amount": 1}}


def test_qualified_ref_evidence_in_subqueries():
    """Refs inside subqueries contribute evidence (via the inner scope)."""
    r = extract_variables_from_sql(
        "SELECT (SELECT ws.ws_web_page_sk FROM web_sales ws) FROM web_page wp",
        "s4a_subq")
    assert r.resolution_stats["script_schemas"] == {
        "web_sales": {"ws_web_page_sk": 1}}, r.resolution_stats


def test_cte_and_derived_aliases_not_evidence():
    """CTE names and derived-table aliases are not physical — no evidence."""
    r = extract_variables_from_sql(
        "WITH c AS (SELECT 1 AS x) SELECT c.x FROM c;\n"
        "SELECT d.x FROM (SELECT 1 AS x) d;",
        "s4a_excl")
    assert r.resolution_stats["script_schemas"] == {}, r.resolution_stats


def test_case_variant_cte_qualifier_no_phantom_evidence():
    """M3a: `SELECT C.x FROM c` (CTE defined as c) must NOT record phantom
    evidence under "C" — MySQL identifiers are case-insensitive."""
    r = extract_variables_from_sql(
        "WITH c AS (SELECT 1 AS x) SELECT C.x FROM c", "m3a")
    assert r.resolution_stats["script_schemas"] == {}, r.resolution_stats


def test_case_variant_alias_qualifier_canonical_evidence():
    """M3a: `SELECT w.x FROM t AS W` — a case-variant alias qualifier must
    resolve to the canonical table, never leak the alias spelling."""
    r = extract_variables_from_sql("SELECT w.x FROM t AS W", "m3a2")
    assert r.resolution_stats["script_schemas"] == {"t": {"x": 1}}, r.resolution_stats


def test_system_schema_refs_not_evidence():
    r = extract_variables_from_sql(
        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES", "s4a_sys")
    assert r.resolution_stats["script_schemas"] == {}


# ── Source 2: DML target column lists → script_schemas ──────────────────

def test_insert_list_evidence_no_column_vars():
    """INSERT INTO t (a,b) SELECT … → evidence for t; NO new column vars."""
    r = extract_variables_from_sql(
        "INSERT INTO t (a,b) SELECT x,y FROM s", "s4a_ins")
    stats = r.resolution_stats
    assert stats["script_schemas"]["t"] == {"a": 1, "b": 1}, stats
    # total_columns unchanged: only x,y (the SELECT source) are column vars
    assert stats["total_columns"] == 2, stats
    assert stats["total_columns"] == len(_col_vars(r)), stats
    assert not [v for v in _col_vars(r) if v.name in ("a", "b")]


def test_insert_values_list_evidence():
    """INSERT INTO t (a,b) VALUES … → same evidence, still no column vars."""
    r = extract_variables_from_sql(
        "INSERT INTO t (a,b) VALUES (1,2)", "s4a_insv")
    stats = r.resolution_stats
    assert stats["script_schemas"]["t"] == {"a": 1, "b": 1}, stats
    assert stats["total_columns"] == 0, stats  # INSERT list creates nothing


def test_insert_without_list_no_evidence():
    """INSERT INTO t SELECT … (no column list) → skipped (no evidence)."""
    r = extract_variables_from_sql(
        "INSERT INTO t SELECT x FROM s", "s4a_insnl")
    assert "t" not in r.resolution_stats["script_schemas"]


def test_update_set_evidence():
    """UPDATE t SET a = 1 → SET targets are evidence for t (statement line)."""
    r = extract_variables_from_sql("UPDATE t SET a = 1", "s4a_upd")
    assert r.resolution_stats["script_schemas"]["t"] == {"a": 1}


def test_merge_set_evidence():
    """MERGE INTO t … ON t.id = s.id … UPDATE SET a=… → evidence for t with
    the MERGE statement's line; ON-qualified refs are source-1 evidence
    under the CANONICAL target name (M3b: alias tgt → customers)."""
    r = extract_variables_from_sql(
        "MERGE INTO customers tgt USING orders src ON tgt.id = src.id "
        "WHEN MATCHED THEN UPDATE SET a = 1", "s4a_merge")
    stats = r.resolution_stats
    assert stats["script_schemas"] == {
        "customers": {"id": 1, "a": 1},
        "orders": {"id": 1},
    }, stats


# ── Source 3: CREATE TABLE / CTAS → script_schemas ──────────────────────

def test_create_table_ddl_evidence():
    """CREATE TABLE t (a INT, b VARCHAR(10)) → t: {a: 1, b: 1}; no vars."""
    r = extract_variables_from_sql(
        "CREATE TABLE t (a INT, b VARCHAR(10))", "s4a_ddl")
    stats = r.resolution_stats
    assert stats["script_schemas"]["t"] == {"a": 1, "b": 1}, stats
    assert stats["total_columns"] == 0, stats  # DDL creates no column vars


def test_ctas_output_alias_evidence():
    """CTAS without a column list → SELECT output aliases (positional)."""
    r = extract_variables_from_sql(
        "CREATE TABLE t AS SELECT x AS a, y FROM s", "s4a_ctas")
    assert r.resolution_stats["script_schemas"]["t"] == {"a": 1, "y": 1}


def test_ctas_with_column_list_uses_ddl_evidence():
    r = extract_variables_from_sql(
        "CREATE TABLE t (a INT) AS SELECT x FROM s", "s4a_ctas2")
    assert r.resolution_stats["script_schemas"]["t"] == {"a": 1}


# ── Evidence lines: statement-anchored, first occurrence wins ───────────

def test_evidence_line_is_statement_line_first_occurrence_wins():
    """Evidence lines = the enclosing statement's first line; setdefault
    keeps the FIRST occurrence (DDL line 1 beats the two later SELECT refs)."""
    r = extract_variables_from_sql(
        "CREATE TABLE t (a INT);\n"
        "SELECT t.a FROM t;\n"
        "SELECT t.a FROM t;\n",
        "s4a_evl")
    assert r.resolution_stats["script_schemas"] == {"t": {"a": 1}}


def test_evidence_lines_per_statement():
    """INSERT/CREATE evidence lines are each statement's own line."""
    r = extract_variables_from_sql(
        "-- header\n"
        "INSERT INTO t (a) SELECT x FROM s;\n"
        "CREATE TABLE u (p INT);\n",
        "s4a_evl2")
    assert r.resolution_stats["script_schemas"] == {
        "t": {"a": 2},
        "u": {"p": 3},
    }


# ── Candidates: stash + unique-owner AUTO-attribution (Phase 2) ─────────

def test_candidate_unique_owner_auto_attribution():
    """S4a Phase 2: a unique visible owner AUTO-ATTRIBUTES.

    Statement 1 leaves ws_web_page_sk bare under {web_sales, web_page};
    statement 2's qualified ref (ws.ws_web_page_sk) is the script evidence.
    The var is attributed to web_sales (canonical name, S3 shape), the
    candidate is REMOVED from schema_candidates (contract: candidates hold
    only still-unresolved residuals for the S4b index re-test), and the
    name leaves unresolved. The other bare side (wp_web_page_sk) has no
    evidence → stays candidate and unresolved.
    """
    r = extract_variables_from_sql(
        "SELECT ws_web_page_sk FROM web_sales ws JOIN web_page wp "
        "ON ws_web_page_sk = wp_web_page_sk;\n"
        "SELECT ws.ws_web_page_sk FROM web_sales ws;\n",
        "s4a_owner")
    stats = r.resolution_stats
    assert stats["resolved_by"]["schema"] == 1, stats
    var = _find(r, "ws_web_page_sk")
    assert var.source_tables == ["web_sales"], var
    assert "ws_web_page_sk" not in stats["unresolved"], stats
    # resolved candidate REMOVED — only still-unresolved candidates remain
    fields = [c["field"] for c in stats["schema_candidates"]]
    assert "ws_web_page_sk" not in fields, stats
    assert fields == ["wp_web_page_sk"], stats
    cand2 = _cand(stats, "wp_web_page_sk")
    assert "owner" not in cand2, cand2
    assert "wp_web_page_sk" in stats["unresolved"], stats
    assert stats["r6_collision"] == 0, stats


def test_ambiguous_two_owners_no_owner_key():
    """Field owned by BOTH visible tables → candidate, no owner (1b)."""
    r = extract_variables_from_sql(
        "SELECT id FROM a JOIN b ON a.id = b.id", "s4a_amb")
    stats = r.resolution_stats
    cand = _cand(stats, "id")
    assert cand["visible_tables"] == ["a", "b"], cand
    assert "owner" not in cand, cand
    assert stats["resolved_by"]["schema"] == 0, stats  # never guessed
    assert stats["unresolved"] == ["id"], stats
    assert stats["r6_collision"] == 0, stats


def test_r6_collision_field_equals_visible_table():
    """Field name == a visible table name → r6_collision, never attributed."""
    r = extract_variables_from_sql(
        "SELECT call_center FROM call_center cc JOIN x ON cc.id = x.id",
        "s4a_r6")
    stats = r.resolution_stats
    assert stats["r6_collision"] == 1, stats
    cand = _cand(stats, "call_center")
    assert cand["visible_tables"] == ["call_center", "x"], cand
    assert "owner" not in cand, cand
    assert stats["resolved_by"]["schema"] == 0, stats
    assert "call_center" in stats["unresolved"], stats


# ── A3: R6 guard extended to S3 (single-table scope) ─────────────────────

def test_r6_collision_s3_single_table_scope():
    """A3: `SELECT call_center FROM call_center` — the S3 single-table rule
    must NOT attribute either: the same field == visible-table-name
    ambiguity S4 excludes in ≥2-table scopes. Counted in r6_collision,
    left unresolved (SOLUTION_DESIGN follow-up 5)."""
    r = extract_variables_from_sql(
        "SELECT call_center FROM call_center", "a3_r6s3")
    stats = r.resolution_stats
    var = _find(r, "call_center")
    assert var.source_tables == [], var
    assert stats["r6_collision"] == 1, stats
    assert stats["resolved_by"]["scope"] == 0, stats
    assert stats["unresolved"] == ["call_center"], stats


def test_r6_collision_s3_case_insensitive():
    """A3: the S3 guard is case-insensitive (MySQL identifiers are), just
    like the S4 guard."""
    r = extract_variables_from_sql(
        "SELECT CALL_CENTER FROM Call_Center", "a3_r6ci")
    stats = r.resolution_stats
    assert _find(r, "CALL_CENTER").source_tables == []
    assert stats["r6_collision"] == 1, stats
    assert "CALL_CENTER" in stats["unresolved"], stats


def test_r6_collision_s3_alias_inherits_refusal():
    """A3: the S1 bare-column alias mirror (`SELECT call_center AS cc FROM
    call_center`) refuses too — the alias inherits EXACTLY what its source
    column gets (nothing); the collision is counted once, at the source."""
    r = extract_variables_from_sql(
        "SELECT call_center AS cc FROM call_center", "a3_r6alias")
    stats = r.resolution_stats
    assert _find(r, "cc").source_tables == [], _find(r, "cc")
    assert _find(r, "call_center").source_tables == [], _find(r, "call_center")
    assert stats["r6_collision"] == 1, stats
    assert stats["resolved_by"]["plain_alias"] == 0, stats
    assert "cc" in stats["unresolved"] and "call_center" in stats["unresolved"], stats


def test_r6_collision_s3_guard_does_not_block_normal_columns():
    """A3 regression: a normal bare column in a single-table scope is still
    S3-attributed, and a self-join (one physical table) still resolves —
    the guard fires only when field == the visible table name."""
    r = extract_variables_from_sql(
        "SELECT customer_id FROM customers", "a3_reg")
    stats = r.resolution_stats
    assert _find(r, "customer_id").source_tables == ["customers"]
    assert stats["resolved_by"]["scope"] == 1, stats
    assert stats["r6_collision"] == 0, stats
    assert stats["unresolved"] == [], stats
    # self-join single physical table — still S3-resolvable, guard not fired
    r2 = extract_variables_from_sql(
        "SELECT amount FROM orders o1 JOIN orders o2 ON o1.id = o2.id",
        "a3_self")
    assert _find(r2, "amount").source_tables == ["orders"]
    assert r2.resolution_stats["r6_collision"] == 0, r2.resolution_stats


def test_case_insensitive_owner_whole_name_only():
    """DDL evidence `Id` matches bare `id` (case-insensitive); never
    `customer_id` (R4 whole-name equality)."""
    r = extract_variables_from_sql(
        "CREATE TABLE t (Id INT);\n"
        "CREATE TABLE u (customer_id INT);\n"
        "SELECT id FROM t JOIN u ON t.id = u.customer_id;\n",
        "s4a_ci")
    stats = r.resolution_stats
    # DDL evidence preserves original case ('Id'); the ON ref t.id adds 'id'
    assert stats["script_schemas"] == {
        "t": {"Id": 1, "id": 3},
        "u": {"customer_id": 2},
    }, stats
    var = _find(r, "id")
    assert var.source_tables == ["t"], var  # case-insensitive match
    assert stats["resolved_by"]["schema"] == 1, stats
    # u's evidence is 'customer_id' — whole-name equality never matches 'id'
    assert stats["r6_collision"] == 0, stats
    assert stats["unresolved"] == [], stats
    assert stats["schema_candidates"] == [], stats  # resolved → removed


def test_no_evidence_no_owner():
    """Field with no evidence anywhere → candidate recorded, no owner."""
    r = extract_variables_from_sql(
        "SELECT a FROM t1 JOIN t2 ON t1.id = t2.id", "s4a_noev")
    stats = r.resolution_stats
    cand = _cand(stats, "a")
    assert cand["visible_tables"] == ["t1", "t2"], cand
    assert "owner" not in cand, cand
    assert stats["resolved_by"]["schema"] == 0, stats
    assert stats["unresolved"] == ["a"], stats


def test_self_join_stays_s3_no_candidate():
    """Self-join dedups to 1 physical table → S3 path, no candidate (S4)."""
    r = extract_variables_from_sql(
        "SELECT amount FROM orders o1 JOIN orders o2 ON o1.id = o2.id",
        "s4a_self")
    stats = r.resolution_stats
    assert _find(r, "amount").source_tables == ["orders"]
    assert stats["schema_candidates"] == [], stats
    assert stats["script_schemas"] == {"orders": {"id": 1}}, stats


def test_loc_is_line_number():
    """Candidate loc = the 1-based line of the statement containing the
    ≥2-table scope."""
    r = extract_variables_from_sql(
        "-- header comment\n"
        "SELECT ws_web_page_sk FROM web_sales ws JOIN web_page wp "
        "ON ws.id = wp.id;\n",
        "s4a_loc")
    cand = _cand(r.resolution_stats, "ws_web_page_sk")
    assert cand["loc"] == 2, cand


def test_loc_anchored_to_statement_not_string_literal():
    """Audit recommendation 1: `'ws_ship_customer_sk' col_name` (a STRING
    literal on an earlier line) must not beat the real use — the candidate
    loc is the line of the STATEMENT containing the ≥2-table scope."""
    r = extract_variables_from_sql(
        "-- header comment\n"
        "SELECT 'ws_ship_customer_sk' AS col_name;\n"
        "SELECT ws_ship_customer_sk FROM web_sales ws JOIN web_page wp "
        "ON ws.id = wp.id;\n",
        "s4a_q76")
    cand = _cand(r.resolution_stats, "ws_ship_customer_sk")
    assert cand["loc"] == 3, cand  # the statement's line, not the literal's (2)


def test_candidate_dedup_same_scope():
    """Repeated bare uses in the same scope → one candidate record."""
    r = extract_variables_from_sql(
        "SELECT id FROM a JOIN b ON a.id = b.id "
        "WHERE id > 0 AND id < 10", "s4a_dedup")
    cands = [c for c in r.resolution_stats["schema_candidates"]
             if c["field"] == "id"]
    assert len(cands) == 1, cands


def test_multiple_scopes_same_field_two_candidates():
    """Same field under different visible sets → separate candidates."""
    r = extract_variables_from_sql(
        "SELECT id FROM a JOIN b ON a.id = b.id;\n"
        "SELECT id FROM c JOIN d ON c.id = d.id;\n",
        "s4a_multi")
    cands = r.resolution_stats["schema_candidates"]
    assert [c["visible_tables"] for c in cands] == [["a", "b"], ["c", "d"]], cands


# ── S2 extensions (Phase 2): set-op derived/CTE output chains ───────────

def test_s2_setop_derived_output_chain():
    """q71: `FROM item, (SELECT … UNION ALL SELECT …) tmp, time_dim` parses
    the derived table as a JOIN (cross-join) — the set-op body is now
    walked with the derived alias, so outer refs to its outputs resolve
    ONE-HOP to the derived alias (two_hop suppressed: per-branch sources
    differ — never guess)."""
    r = extract_variables_from_sql(
        "SELECT sold_item_sk, time_sk\n"
        "FROM item,\n"
        "     (SELECT i_item_sk AS sold_item_sk, i_rec_start_date AS time_sk\n"
        "        FROM item WHERE i_manager_id = 7\n"
        "      UNION ALL\n"
        "      SELECT i_item_sk AS sold_item_sk, i_rec_start_date AS time_sk\n"
        "        FROM item WHERE i_manager_id = 9) tmp,\n"
        "     time_dim\n",
        "s2_q71")
    stats = r.resolution_stats
    for name in ("sold_item_sk", "time_sk"):
        top = [v for v in _col_vars(r)
               if v.name == name and v.context == "TOP"]
        assert top and top[0].source_tables == ["tmp"], (name, top)
    # one-hop only — the outputs were plain aliases of item columns, but a
    # set-op branch must never two-hop (the branches' sources differ)
    assert stats["resolved_by"]["expr_alias"] >= 1, stats
    assert "sold_item_sk" not in stats["unresolved"], stats


def test_s2_union_cte_outputs_and_star_expansion():
    """fin_query8: a UNION-derived CTE (positions) records each branch's
    outputs as the CTE's output columns; `pnp.*` inside the next CTE body
    expands them (exact SQL semantics, never a heuristic) — downstream
    bare refs resolve through the chain exactly like the CTE-output
    mechanism."""
    r = extract_variables_from_sql(
        "WITH positions AS (\n"
        "  SELECT txn_id, debit_amount_usd FROM settlement_party_debit\n"
        "  UNION ALL\n"
        "  SELECT txn_id, credit_amount_usd FROM settlement_party_credit\n"
        "),\n"
        "positions_with_action AS (\n"
        "  SELECT pnp.*, SUM(debit_amount_usd) AS total_debit_usd\n"
        "  FROM positions pnp\n"
        ")\n"
        "SELECT txn_id, debit_amount_usd, total_debit_usd "
        "FROM positions_with_action",
        "s2_fq8")
    stats = r.resolution_stats
    assert stats["unresolved"] == [], stats
    for name in ("txn_id", "debit_amount_usd", "total_debit_usd"):
        top = [v for v in _col_vars(r)
               if v.name == name and v.context == "TOP"]
        assert top and top[0].source_tables == ["positions_with_action"], (
            name, top)


def test_s2_union_cte_direct_output_resolution():
    """fin_query8: refs to a UNION-derived CTE's outputs resolve DIRECTLY
    against the CTE (no star needed) — the branch outputs are recorded."""
    r = extract_variables_from_sql(
        "WITH positions AS (\n"
        "  SELECT txn_id, debit_amount_usd FROM settlement_party_debit\n"
        "  UNION ALL\n"
        "  SELECT txn_id, credit_amount_usd FROM settlement_party_credit\n"
        ")\n"
        "SELECT txn_id FROM positions WHERE debit_amount_usd > 0",
        "s2_fq8b")
    stats = r.resolution_stats
    assert stats["unresolved"] == [], stats
    for name in ("txn_id", "debit_amount_usd"):
        top = [v for v in _col_vars(r) if v.name == name and v.context == "TOP"]
        assert top and top[0].source_tables == ["positions"], (name, top)


def test_stats_defaults_on_trivial_script():
    """New keys present with empty defaults on a script with no candidates."""
    r = extract_variables_from_sql("SELECT 1", "s4a_triv")
    stats = r.resolution_stats
    assert stats["schema_candidates"] == [], stats
    assert stats["r6_collision"] == 0, stats
    assert stats["script_schemas"] == {}, stats
    assert stats["unresolved"] == [], stats
