"""S4 Phase 0 — SELECT-side schema enrichment instrumentation (report-only).

Implements SOLUTION_DESIGN "SELECT-Side Schema Enrichment", Phase 0:

  * `script_schemas`   — per-script canonical schema map built from evidence
    sources only (qualified refs, DML target column lists, CREATE TABLE /
    CTAS column definitions). Evidence NEVER creates column variables.
  * `schema_candidates` — every unresolved bare column in a ≥2-table scope
    is stashed as {field, visible_tables, loc}; the unique-owner post-pass
    adds `owner` ONLY when exactly one visible table's evidence contains the
    field (whole-name, case-insensitive; R6 collisions never attributed).
  * `r6_collision`     — candidates whose field equals a visible table name.
  * `resolved_by["schema"]` stays 0 — auto-resolution is gated on a human
    audit (Phase 2). Candidate vars stay in `unresolved` with source_tables
    untouched.

Invariants under test: never attribute, never guess, evidence-only.
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
    """Aliased / unaliased / db-qualified refs → canonical script_schemas."""
    r = extract_variables_from_sql(
        "SELECT sb.total_amount FROM settlement_batch sb", "s4a_alias")
    assert r.resolution_stats["script_schemas"] == {
        "settlement_batch": ["total_amount"]}, r.resolution_stats

    r = extract_variables_from_sql("SELECT t.amount FROM t", "s4a_plain")
    assert r.resolution_stats["script_schemas"] == {"t": ["amount"]}

    r = extract_variables_from_sql("SELECT db.t.amount FROM db.t", "s4a_dbq")
    # db qualifier dropped — keyed by bare table name
    assert r.resolution_stats["script_schemas"] == {"t": ["amount"]}


def test_qualified_ref_evidence_in_subqueries():
    """Refs inside subqueries contribute evidence (via the inner scope)."""
    r = extract_variables_from_sql(
        "SELECT (SELECT ws.ws_web_page_sk FROM web_sales ws) FROM web_page wp",
        "s4a_subq")
    assert r.resolution_stats["script_schemas"] == {
        "web_sales": ["ws_web_page_sk"]}, r.resolution_stats


def test_cte_and_derived_aliases_not_evidence():
    """CTE names and derived-table aliases are not physical — no evidence."""
    r = extract_variables_from_sql(
        "WITH c AS (SELECT 1 AS x) SELECT c.x FROM c;\n"
        "SELECT d.x FROM (SELECT 1 AS x) d;",
        "s4a_excl")
    assert r.resolution_stats["script_schemas"] == {}, r.resolution_stats


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
    assert "a" in stats["script_schemas"]["t"]
    assert "b" in stats["script_schemas"]["t"]
    # total_columns unchanged: only x,y (the SELECT source) are column vars
    assert stats["total_columns"] == 2, stats
    assert stats["total_columns"] == len(_col_vars(r)), stats
    assert not [v for v in _col_vars(r) if v.name in ("a", "b")]


def test_insert_values_list_evidence():
    """INSERT INTO t (a,b) VALUES … → same evidence, still no column vars."""
    r = extract_variables_from_sql(
        "INSERT INTO t (a,b) VALUES (1,2)", "s4a_insv")
    stats = r.resolution_stats
    assert "a" in stats["script_schemas"]["t"]
    assert "b" in stats["script_schemas"]["t"]
    assert stats["total_columns"] == 0, stats  # INSERT list creates nothing


def test_insert_without_list_no_evidence():
    """INSERT INTO t SELECT … (no column list) → skipped (no evidence)."""
    r = extract_variables_from_sql(
        "INSERT INTO t SELECT x FROM s", "s4a_insnl")
    assert "t" not in r.resolution_stats["script_schemas"]


def test_update_set_evidence():
    """UPDATE t SET a = 1 → SET targets are evidence for t."""
    r = extract_variables_from_sql("UPDATE t SET a = 1", "s4a_upd")
    assert r.resolution_stats["script_schemas"]["t"] == ["a"]


def test_merge_set_evidence():
    """MERGE INTO t … WHEN MATCHED THEN UPDATE SET a=… → evidence for t."""
    r = extract_variables_from_sql(
        "MERGE INTO t USING s ON t.id = s.id "
        "WHEN MATCHED THEN UPDATE SET a = 1", "s4a_merge")
    stats = r.resolution_stats
    assert "a" in stats["script_schemas"]["t"]
    # ON-condition qualified refs are source-1 evidence as well
    assert "id" in stats["script_schemas"]["t"]
    assert stats["script_schemas"]["s"] == ["id"]


# ── Source 3: CREATE TABLE / CTAS → script_schemas ──────────────────────

def test_create_table_ddl_evidence():
    """CREATE TABLE t (a INT, b VARCHAR(10)) → t: [a, b]; no column vars."""
    r = extract_variables_from_sql(
        "CREATE TABLE t (a INT, b VARCHAR(10))", "s4a_ddl")
    stats = r.resolution_stats
    assert stats["script_schemas"]["t"] == ["a", "b"], stats
    assert stats["total_columns"] == 0, stats  # DDL creates no column vars


def test_ctas_output_alias_evidence():
    """CTAS without a column list → SELECT output aliases (positional)."""
    r = extract_variables_from_sql(
        "CREATE TABLE t AS SELECT x AS a, y FROM s", "s4a_ctas")
    assert r.resolution_stats["script_schemas"]["t"] == ["a", "y"]


def test_ctas_with_column_list_uses_ddl_evidence():
    r = extract_variables_from_sql(
        "CREATE TABLE t (a INT) AS SELECT x FROM s", "s4a_ctas2")
    assert r.resolution_stats["script_schemas"]["t"] == ["a"]


# ── Candidates: stash + unique-owner computation (report-only) ──────────

def test_candidate_unique_owner_report_only():
    """Bare column in a 2-table scope → candidate with owner, var untouched.

    Statement 1 leaves ws_web_page_sk bare under {web_sales, web_page};
    statement 2's qualified ref (ws.ws_web_page_sk) is the script evidence.
    The unique owner is REPORTED on the candidate — the var keeps
    source_tables == [] and stays in unresolved (Phase 0 invariant).
    """
    r = extract_variables_from_sql(
        "SELECT ws_web_page_sk FROM web_sales ws JOIN web_page wp "
        "ON ws_web_page_sk = wp_web_page_sk;\n"
        "SELECT ws.ws_web_page_sk FROM web_sales ws;\n",
        "s4a_owner")
    stats = r.resolution_stats
    assert stats["resolved_by"]["schema"] == 0, stats  # report-only
    cand = _cand(stats, "ws_web_page_sk")
    assert cand["visible_tables"] == ["web_sales", "web_page"], cand
    assert cand["owner"] == "web_sales", cand
    # the other bare side has no evidence → no owner key
    cand2 = _cand(stats, "wp_web_page_sk")
    assert "owner" not in cand2, cand2
    # Phase 0 invariant: no var was attributed, nothing left unresolved
    var = _find(r, "ws_web_page_sk")
    assert var.source_tables == [], var
    assert "ws_web_page_sk" in stats["unresolved"], stats
    assert stats["r6_collision"] == 0, stats


def test_ambiguous_two_owners_no_owner_key():
    """Field owned by BOTH visible tables → candidate, no owner (1b)."""
    r = extract_variables_from_sql(
        "SELECT id FROM a JOIN b ON a.id = b.id", "s4a_amb")
    stats = r.resolution_stats
    cand = _cand(stats, "id")
    assert cand["visible_tables"] == ["a", "b"], cand
    assert "owner" not in cand, cand
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
    assert "call_center" in stats["unresolved"], stats


def test_case_insensitive_owner_whole_name_only():
    """DDL evidence `Id` matches bare `id`; never `customer_id` (R4)."""
    r = extract_variables_from_sql(
        "CREATE TABLE t (Id INT);\n"
        "CREATE TABLE u (customer_id INT);\n"
        "SELECT id FROM t JOIN u ON t.id = u.customer_id;\n",
        "s4a_ci")
    stats = r.resolution_stats
    # DDL evidence preserves original case ('Id'); the ON ref t.id adds 'id'
    assert "Id" in stats["script_schemas"]["t"], stats
    assert "id" in stats["script_schemas"]["t"], stats
    cand = _cand(stats, "id")
    assert cand["owner"] == "t", cand  # case-insensitive match
    # u's evidence is 'customer_id' — whole-name equality never matches 'id'
    assert stats["r6_collision"] == 0, stats
    assert stats["unresolved"] == ["id"], stats  # still unresolved (Phase 0)


def test_no_evidence_no_owner():
    """Field with no evidence anywhere → candidate recorded, no owner."""
    r = extract_variables_from_sql(
        "SELECT a FROM t1 JOIN t2 ON t1.id = t2.id", "s4a_noev")
    stats = r.resolution_stats
    cand = _cand(stats, "a")
    assert cand["visible_tables"] == ["t1", "t2"], cand
    assert "owner" not in cand, cand
    assert stats["unresolved"] == ["a"], stats


def test_self_join_stays_s3_no_candidate():
    """Self-join dedups to 1 physical table → S3 path, no candidate (S4)."""
    r = extract_variables_from_sql(
        "SELECT amount FROM orders o1 JOIN orders o2 ON o1.id = o2.id",
        "s4a_self")
    stats = r.resolution_stats
    assert _find(r, "amount").source_tables == ["orders"]
    assert stats["schema_candidates"] == [], stats
    assert stats["script_schemas"] == {"orders": ["id"]}, stats


def test_loc_is_line_number():
    """Candidate loc = the 1-based SQL line of the bare column."""
    r = extract_variables_from_sql(
        "-- header comment\n"
        "SELECT ws_web_page_sk FROM web_sales ws JOIN web_page wp "
        "ON ws.id = wp.id;\n",
        "s4a_loc")
    cand = _cand(r.resolution_stats, "ws_web_page_sk")
    assert cand["loc"] == 2, cand


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


def test_stats_defaults_on_trivial_script():
    """New keys present with empty defaults on a script with no candidates."""
    r = extract_variables_from_sql("SELECT 1", "s4a_triv")
    stats = r.resolution_stats
    assert stats["schema_candidates"] == [], stats
    assert stats["r6_collision"] == 0, stats
    assert stats["script_schemas"] == {}, stats
    assert stats["unresolved"] == [], stats
