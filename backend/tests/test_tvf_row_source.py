"""Task #364: table-valued function (TVF) row sources.

A TVF used in FROM/JOIN — e.g. `JOIN v_bdm_sys_ftpsje_jydsf('$(load_date)') f`
— parses as `Table(this=Anonymous(<func>, args), alias=f)` whose `Table.name`
is '' (the function name lives inside `Anonymous.this`). Before the fix the
extractor's `_register_table` returned early on the empty name, so the
function + its alias were never registered and the `f.*` columns rendered as
orphan fields (no parent table). The fix recovers the function name and
registers a `FUNCTION_TABLE` source (plus the alias handle), so the columns
resolve and parent correctly — never synthesizing any schema.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.dependency_graph import build_dependency_graph
from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.models.variable import VariableType

FUNC_NAME = "v_bdm_sys_ftpsje_jydsf"

ALIASED_SQL = "SELECT f.df_dfzh FROM v_bdm_sys_ftpsje_jydsf('$(load_date)') f"
BARE_SQL = "SELECT df_dfzh FROM v_bdm_sys_ftpsje_jydsf('$(load_date)')"
JOIN_SQL = (
    "SELECT a.x, f.df_dfzh "
    "FROM t a "
    "LEFT JOIN v_bdm_sys_ftpsje_jydsf('$(load_date)') f ON a.k = f.k"
)


def _vars(res, name=None, vtype=None, ctx=None):
    return [v for v in res.variables
            if (name is None or v.name == name)
            and (vtype is None or v.variable_type == vtype)
            and (ctx is None or v.context == ctx)]


def _edges(res, deps, rel=None):
    by_id = {v.id: v for v in res.variables}
    out = []
    for d in deps:
        if rel is not None and d.relationship != rel:
            continue
        out.append((d, by_id.get(d.source_id), by_id.get(d.target_id)))
    return out


def test_tvf_registers_function_table_source():
    res = extract_variables_from_sql(ALIASED_SQL, "tvf_aliased.sql")
    fn = _vars(res, name=FUNC_NAME, vtype=VariableType.FUNCTION_TABLE, ctx="TOP0")
    assert fn, "the TVF call must register as a FUNCTION_TABLE variable"
    assert fn[0].defined_in == "FROM"


def test_tvf_alias_resolves_columns_to_function():
    res = extract_variables_from_sql(ALIASED_SQL, "tvf_aliased.sql")
    alias = _vars(res, name="f", vtype=VariableType.TABLE, ctx="TOP0")
    assert alias and alias[0].is_alias_handle, "alias f must be a scope handle"
    assert alias[0].source_tables == [FUNC_NAME], alias
    col = _vars(res, name="f.df_dfzh", vtype=VariableType.COLUMN, ctx="TOP0")
    assert col, "f.df_dfzh column must be registered"
    # the qualifier must resolve to the function, never stay the bare alias
    assert col[0].source_tables == [FUNC_NAME], col


def test_tvf_columns_not_orphaned():
    res = extract_variables_from_sql(ALIASED_SQL, "tvf_aliased.sql")
    assert "f.df_dfzh" not in res.resolution_stats["unresolved"], \
        res.resolution_stats
    assert res.resolution_stats["unresolved_count"] == 0


def test_tvf_read_and_alias_edges():
    res = extract_variables_from_sql(ALIASED_SQL, "tvf_aliased.sql")
    deps = build_dependency_graph(res)
    # the alias handle reads the function into the output VT
    flows = [d for d, s, t in _edges(res, deps, "TABLE_FLOW")
             if s.name == "f" and t.variable_type == VariableType.VIRTUAL_TABLE]
    assert flows, "Phase 1a must emit f -> output TABLE_FLOW"
    # the function -> alias pairing is expressed as an ALIAS edge
    aliases = [d for d, s, t in _edges(res, deps, "ALIAS")
               if s.name == FUNC_NAME and t.name == "f"]
    assert aliases, "the TVF alias must pair with its function source"


def test_tvf_bare_form_resolves_bare_column():
    res = extract_variables_from_sql(BARE_SQL, "tvf_bare.sql")
    fn = _vars(res, name=FUNC_NAME, vtype=VariableType.FUNCTION_TABLE, ctx="TOP0")
    assert fn, "bare TVF must register as a FUNCTION_TABLE variable"
    # a bare reference carries its own name as source_tables (read of itself)
    assert fn[0].source_tables == [FUNC_NAME], fn
    col = _vars(res, name="df_dfzh", vtype=VariableType.COLUMN, ctx="TOP0")
    assert col and col[0].source_tables == [FUNC_NAME], col
    assert res.resolution_stats["unresolved_count"] == 0


def test_tvf_join_form():
    res = extract_variables_from_sql(JOIN_SQL, "tvf_join.sql")
    fn = _vars(res, name=FUNC_NAME, vtype=VariableType.FUNCTION_TABLE, ctx="TOP0")
    assert fn and fn[0].defined_in == "JOIN", fn
    col = _vars(res, name="f.df_dfzh", vtype=VariableType.COLUMN, ctx="TOP0")
    assert col and col[0].source_tables == [FUNC_NAME], col
    key = _vars(res, name="f.k", vtype=VariableType.COLUMN, ctx="TOP0")
    assert key and key[0].source_tables == [FUNC_NAME], key
    assert res.resolution_stats["unresolved_count"] == 0
