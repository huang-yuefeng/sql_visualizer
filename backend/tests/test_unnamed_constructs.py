"""Task B (2026-08-11 audit): registration of three unregistered table-like
constructs — LATERAL VIEW explode(...) x AS c2, FROM (VALUES ...) v(c1),
CROSS JOIN UNNEST(t.arr) AS u(c2).

Without the alias var, dependency_graph Phase 1a (gated on
`if not v.source_tables: continue`) emits no read edge — the exploded
array / VALUES rows / UNNEST rows vanish from the graph. Registration
mirrors `FROM base x`: a TABLE alias var carrying the base table name in
source_tables. For VALUES/UNNEST the base is the synthetic table the
clause itself represents (⟐ values / ⟐ unnest); for LATERAL VIEW it is
the physical table behind the exploded array column.

The alias is deliberately NOT added to scope.aliases/_table_aliases —
columns referencing it (x.c2 / v.c1 / u.c2) keep their current
registration and lines exactly as before.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.dependency_graph import build_dependency_graph
from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.models.variable import VariableType

LATERAL_SQL = "SELECT x.c2 FROM base t LATERAL VIEW explode(t.arr) x AS c2"
VALUES_SQL = """SELECT v.c1
FROM (
    VALUES (1),
           (2)
) v(c1)
"""
UNNEST_JOIN_SQL = "SELECT u.c2 FROM t CROSS JOIN UNNEST(t.arr) AS u(c2)"
UNNEST_FROM_SQL = "SELECT u.c2 FROM UNNEST(arr) AS u(c2)"
LATERAL_UNNEST_SQL = "SELECT x.c2 FROM t CROSS JOIN LATERAL UNNEST(t.arr) x AS c2"
BARE_LATERAL_SQL = "SELECT x.c2 FROM base LATERAL VIEW explode(arr) x AS c2"


def _vars(res, name=None, vtype=None, ctx=None):
    out = []
    for v in res.variables:
        if name is not None and v.name != name:
            continue
        if vtype is not None and v.variable_type != vtype:
            continue
        if ctx is not None and v.context != ctx:
            continue
        out.append(v)
    return out


def _table_flow_edges(res, deps, alias_name):
    """Phase 1a read edges: alias var → its context's ⟐ anchor."""
    out = []
    for d in deps:
        src = next((v for v in res.variables if v.id == d.source_id), None)
        tgt = next((v for v in res.variables if v.id == d.target_id), None)
        if (src and src.name == alias_name
                and d.relationship == "TABLE_FLOW"
                and tgt and tgt.variable_type == VariableType.VIRTUAL_TABLE):
            out.append(d)
    return out


# ── LATERAL VIEW explode ────────────────────────────────────────────

def test_lateral_view_alias_registered_with_physical_base():
    res = extract_variables_from_sql(LATERAL_SQL, "lateral_view.sql")
    x = _vars(res, name="x", vtype=VariableType.TABLE, ctx="TOP0")
    assert x and x[0].source_tables == ["base"], \
        f"LATERAL VIEW alias must carry the exploded column's table: {x}"
    assert x[0].defined_in == "FROM"
    assert x[0].line_start == 1
    # the exploded column keeps its current registration (never re-pointed
    # at the physical table by the alias — the alias is NOT in the scope
    # alias map)
    c = _vars(res, name="x.c2", vtype=VariableType.COLUMN, ctx="TOP0")
    assert c and c[0].source_tables == ["x"], \
        f"x.c2 must keep its registration: {c}"
    assert c[0].line_start == 1
    # the base table itself registers as before
    t = _vars(res, name="t", vtype=VariableType.TABLE)
    assert t and t[0].source_tables == ["base"]


def test_lateral_view_read_edge_emitted():
    # the audit consequence: without the alias var Phase 1a emits no read
    # edge — the alias var now carries source_tables and the edge appears
    res = extract_variables_from_sql(LATERAL_SQL, "lateral_view.sql")
    deps = build_dependency_graph(res)
    assert _table_flow_edges(res, deps, "x"), \
        "Phase 1a must emit the x → ⟐ output TABLE_FLOW read edge"


def test_lateral_view_bare_arg_single_scope_table():
    # explode(arr) without a qualifier — base resolves to the single
    # distinct FROM table (never a guess on ambiguous scopes)
    res = extract_variables_from_sql(BARE_LATERAL_SQL, "lateral_bare.sql")
    x = _vars(res, name="x", vtype=VariableType.TABLE)
    assert x and x[0].source_tables == ["base"], f"bare explode base: {x}"


# ── FROM (VALUES ...) v(c1) ─────────────────────────────────────────

def test_values_alias_registered_with_synthetic_base():
    res = extract_variables_from_sql(VALUES_SQL, "values.sql")
    v = _vars(res, name="v", vtype=VariableType.TABLE, ctx="TOP0")
    assert v and v[0].source_tables == ["⟐ values"], \
        f"VALUES alias must carry the synthetic base: {v}"
    # def site: the alias token after the closing ')' — line 5 in the
    # multi-line fixture (ret_last semantics)
    assert v[0].line_start == 5, f"VALUES alias line: {v[0].line_start}"
    assert v[0].defined_in == "FROM"
    c = _vars(res, name="v.c1", vtype=VariableType.COLUMN)
    assert c and c[0].source_tables == ["v"], \
        f"v.c1 must keep its registration: {c}"
    assert c[0].line_start == 1


def test_values_alias_read_edge_emitted():
    res = extract_variables_from_sql(VALUES_SQL, "values.sql")
    deps = build_dependency_graph(res)
    assert _table_flow_edges(res, deps, "v"), \
        "Phase 1a must emit the v → ⟐ output TABLE_FLOW read edge"


def test_anonymous_values_no_alias_no_var():
    # no alias_or_name → nothing registered (the construct stays honest
    # and invisible, never a guessed name)
    sql = "SELECT * FROM (VALUES (1), (2))"
    res = extract_variables_from_sql(sql, "values_anon.sql")
    assert not _vars(res, vtype=VariableType.TABLE), \
        "anonymous VALUES must register no alias var"


# ── CROSS JOIN UNNEST ───────────────────────────────────────────────

def test_unnest_join_alias_registered_with_synthetic_base():
    res = extract_variables_from_sql(UNNEST_JOIN_SQL, "unnest_join.sql")
    u = _vars(res, name="u", vtype=VariableType.TABLE, ctx="TOP0")
    assert u and u[0].source_tables == ["⟐ unnest"], \
        f"UNNEST alias must carry the synthetic base: {u}"
    assert u[0].defined_in == "JOIN"
    c = _vars(res, name="u.c2", vtype=VariableType.COLUMN)
    assert c and c[0].source_tables == ["u"], \
        f"u.c2 must keep its registration: {c}"
    # the joined physical table still registers
    t = _vars(res, name="t", vtype=VariableType.TABLE)
    assert t and t[0].source_tables == ["t"]


def test_unnest_join_read_edge_emitted():
    res = extract_variables_from_sql(UNNEST_JOIN_SQL, "unnest_join.sql")
    deps = build_dependency_graph(res)
    assert _table_flow_edges(res, deps, "u"), \
        "Phase 1a must emit the u → ⟐ output TABLE_FLOW read edge"


def test_unnest_from_alias_registered():
    res = extract_variables_from_sql(UNNEST_FROM_SQL, "unnest_from.sql")
    u = _vars(res, name="u", vtype=VariableType.TABLE, ctx="TOP0")
    assert u and u[0].source_tables == ["⟐ unnest"]
    assert u[0].defined_in == "FROM"


def test_lateral_unnest_alias_falls_back_to_lateral_alias():
    # JOIN LATERAL UNNEST(t.arr) x AS c2 — the alias sits on the LATERAL
    # wrapper; the exp.Unnest itself carries no alias
    res = extract_variables_from_sql(LATERAL_UNNEST_SQL, "lateral_unnest.sql")
    x = _vars(res, name="x", vtype=VariableType.TABLE, ctx="TOP0")
    assert x and x[0].source_tables == ["⟐ unnest"], \
        f"LATERAL UNNEST alias must fall back to the lateral's alias: {x}"
    assert x[0].defined_in == "JOIN"


# ── JOIN (VALUES ...) v(c1) — the VALUES construct in JOIN position ──

def test_values_join_alias_registered_with_synthetic_base():
    # sqlglot parses `JOIN (VALUES (1)) v(c1)` as a bare exp.Values (no
    # Subquery wrapper) — the JOIN walk must register the alias exactly
    # like the FROM position does
    sql = "SELECT v.c1 FROM t JOIN (VALUES (1)) v(c1) ON t.id = v.c1"
    res = extract_variables_from_sql(sql, "values_join.sql")
    v = _vars(res, name="v", vtype=VariableType.TABLE, ctx="TOP0")
    assert v and v[0].source_tables == ["⟐ values"], \
        f"JOIN VALUES alias must carry the synthetic base: {v}"
    assert v[0].defined_in == "FROM"
    c = _vars(res, name="v.c1", vtype=VariableType.COLUMN)
    assert c and c[0].source_tables == ["v"], \
        f"v.c1 must keep its registration: {c}"


def test_values_join_read_edge_emitted():
    sql = "SELECT v.c1 FROM t JOIN (VALUES (1)) v(c1) ON t.id = v.c1"
    res = extract_variables_from_sql(sql, "values_join.sql")
    deps = build_dependency_graph(res)
    assert _table_flow_edges(res, deps, "v"), \
        "Phase 1a must emit the v → ⟐ output TABLE_FLOW read edge"


# ── one script, all three constructs (the audit's combined fixture) ────

COMBINED_SQL = """SELECT v.c1
FROM (
    VALUES (1),
           (2)
) v(c1);
SELECT x.c2
FROM base t
LATERAL VIEW explode(t.arr) x AS c2;
SELECT u.c2
FROM t2
CROSS JOIN UNNEST(t2.arr) AS u(c2);
"""


def test_combined_script_all_three_aliases_registered():
    res = extract_variables_from_sql(COMBINED_SQL, "combined.sql")
    v = _vars(res, name="v", vtype=VariableType.TABLE, ctx="TOP0")
    x = _vars(res, name="x", vtype=VariableType.TABLE, ctx="TOP1")
    u = _vars(res, name="u", vtype=VariableType.TABLE, ctx="TOP2")
    assert v and v[0].source_tables == ["⟐ values"], v
    assert x and x[0].source_tables == ["base"], x
    assert u and u[0].source_tables == ["⟐ unnest"], u
    # each alias carries its own statement's context (per-statement dedup)
    assert v[0].context == "TOP0" and u[0].context == "TOP2"


def test_combined_script_read_edges_emitted_per_statement():
    res = extract_variables_from_sql(COMBINED_SQL, "combined.sql")
    deps = build_dependency_graph(res)
    for alias, ctx in (("v", "TOP0"), ("x", "TOP1"), ("u", "TOP2")):
        edges = [d for d in _table_flow_edges(res, deps, alias)
                 if _tgt(res, d).context == ctx]
        assert edges, f"Phase 1a must emit {alias} → ⟐ output in {ctx}: " \
            f"{_table_flow_edges(res, deps, alias)}"


def test_combined_script_columns_keep_read_lines():
    res = extract_variables_from_sql(COMBINED_SQL, "combined.sql")
    c = _vars(res, name="v.c1", vtype=VariableType.COLUMN, ctx="TOP0")
    assert c and c[0].line_start == 1 and c[0].source_tables == ["v"], c
    c = _vars(res, name="x.c2", vtype=VariableType.COLUMN, ctx="TOP1")
    assert c and c[0].line_start == 6 and c[0].source_tables == ["x"], c
    c = _vars(res, name="u.c2", vtype=VariableType.COLUMN, ctx="TOP2")
    assert c and c[0].line_start == 9 and c[0].source_tables == ["u"], c


def _tgt(res, dep):
    return next((v for v in res.variables if v.id == dep.target_id), None)

