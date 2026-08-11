"""E3a extractor/lineage gap cluster — deterministic walker unit tests.

Covers Team B's case-testing sweep findings 1-6:

 1. UPDATE columns were not extracted at all (query4_update_delete.sql) —
    the dedicated UPDATE walker registers SET targets as fields of the
    target table and walks WHERE + subqueries (NOT EXISTS).
 2. Hive FROM-led multi-insert arms were ignored
    (dialect_test/hive_multi_insert.sql) — each arm's target table is
    registered and its SELECT columns are walked.
 3. DML INSERT-target columns were attributed to the synthetic output
    container (BDM_ACC_LOAN_INFO_SUP_M.sql TOP1) — the insert-column
    vars attribute to the DML TARGET table (rrcdm_job_log_exec_par).
 4. TPC-DS comma-join CTE (samples/tpcds/q1.sql) — comma-join scope
    tables stay attribution candidates: `_attribute_output_containers`
    must not swallow columns whose physical table is identifiable. The
    CTE's named outputs still attribute to the CTE; bare columns in the
    ≥2-table scope stay S4a candidates (in-script evidence → unique
    owner attribution via `_finalize_schema_candidates`).
 5. MERGE — the target is a searchable merge_target var and the
    WHEN-branch SET RHS columns are walked (target.total_spent +
    source.total_spent → both attributions present).
 6. PARTITION seeds are scoped to the partition var's own DML target
    table in compute_field_flow — a data_dt PARTITION var of another
    insert target never seeds a t.data_dt search.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.lineage import compute_field_flow
from app.extractor.physical_model import build_physical_model
from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.models.variable import VariableType

SAMPLES = REPO_ROOT / "samples"

# ── #1 UPDATE ──────────────────────────────────────────────────────

_UPDATE_SQL = """-- UPDATE and DELETE with logical conditions
UPDATE orders o
SET o.order_status = 'cancelled',
    o.shipped_date = NULL
WHERE o.order_status = 'pending'
  AND o.order_date < DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
  AND NOT EXISTS (
      SELECT 1 FROM payments p
      WHERE p.order_id = o.order_id
        AND p.status = 'completed'
  );

DELETE FROM logs l
WHERE l.table_name = 'orders'
  AND l.operation = 'DELETE'
  AND l.changed_at < DATE_SUB(CURRENT_DATE, INTERVAL 90 DAY)
  AND l.changed_by IN (
      SELECT u.user_id FROM users u
      WHERE u.status = 'disabled'
  );
"""


def _vars(res, ctx=None, name=None, vtype=None):
    out = []
    for v in res.variables:
        if ctx is not None and v.context != ctx:
            continue
        if name is not None and v.name != name:
            continue
        if vtype is not None and v.variable_type != vtype:
            continue
        out.append(v)
    return out


def test_update_set_targets_are_fields_of_target_table():
    res = extract_variables_from_sql(_UPDATE_SQL, "query4_update_delete.sql")
    st = _vars(res, ctx="TOP0", name="o.order_status",
               vtype=VariableType.COLUMN)
    assert st and st[0].source_tables == ["orders"], \
        f"UPDATE SET target must belong to the target table: {st}"
    assert st[0].defined_in == "UPDATE SET"
    sd = _vars(res, ctx="TOP0", name="o.shipped_date",
               vtype=VariableType.COLUMN)
    assert sd and sd[0].source_tables == ["orders"]


def test_update_where_and_not_exists_subquery_walked():
    res = extract_variables_from_sql(_UPDATE_SQL, "query4_update_delete.sql")
    # WHERE of the UPDATE walked
    assert _vars(res, ctx="TOP0", name="o.order_date",
                 vtype=VariableType.COLUMN), "UPDATE WHERE not walked"
    # NOT EXISTS subquery interior walked (payments table + columns)
    assert _vars(res, ctx="TOP0/exists1", name="payments",
                 vtype=VariableType.TABLE), "NOT EXISTS subquery not walked"
    assert _vars(res, ctx="TOP0/exists1", name="p.order_id",
                 vtype=VariableType.COLUMN)
    # correlated reference inside the subquery resolves to the outer table
    oid = _vars(res, ctx="TOP0/exists1", name="o.order_id",
                vtype=VariableType.COLUMN)
    assert oid and oid[0].source_tables == ["orders"]


def test_delete_where_still_walked():
    res = extract_variables_from_sql(_UPDATE_SQL, "query4_update_delete.sql")
    assert _vars(res, ctx="TOP1", name="l.changed_at",
                 vtype=VariableType.COLUMN), "DELETE WHERE not walked"
    assert _vars(res, ctx="TOP1/subq2", name="users",
                 vtype=VariableType.TABLE), "DELETE IN-subquery not walked"


# ── #2 Hive FROM-led multi-insert ──────────────────────────────────

_HIVE_MULTI_INSERT_SQL = """-- Apache Hive: multi-table insert from single source
FROM page_view_stg pvs
INSERT OVERWRITE TABLE page_view PARTITION(dt='2008-06-08', country)
    SELECT pvs.viewTime, pvs.userid, pvs.page_url, pvs.referrer_url, null, null, pvs.ip, pvs.cnt
INSERT OVERWRITE TABLE page_view_summary PARTITION(dt='2008-06-08')
    SELECT pvs.userid, COUNT(*) AS page_views, pvs.country
    GROUP BY pvs.userid, pvs.country;
"""


def test_hive_multi_insert_each_arm_registered_and_walked():
    res = extract_variables_from_sql(_HIVE_MULTI_INSERT_SQL,
                                     "hive_multi_insert.sql")
    # arm 0: target + PARTITION columns + walked SELECT columns
    assert _vars(res, ctx="TOP0/hive_arm0", name="page_view",
                 vtype=VariableType.TABLE), "arm0 target not registered"
    dt = _vars(res, ctx="TOP0/hive_arm0", name="dt",
               vtype=VariableType.COLUMN)
    assert dt and dt[0].source_tables == ["page_view"]
    v = _vars(res, ctx="TOP0/hive_arm0", name="pvs.page_url",
              vtype=VariableType.COLUMN)
    assert v and v[0].source_tables == ["page_view_stg"], \
        "arm0 SELECT columns not walked"
    # arm 1: second target + its aggregate output attributed to the target
    assert _vars(res, ctx="TOP0/hive_arm1", name="page_view_summary",
                 vtype=VariableType.TABLE), "arm1 target not registered"
    pv = _vars(res, ctx="TOP0/hive_arm1", name="page_views",
               vtype=VariableType.AGGREGATE)
    assert pv and pv[0].source_tables == ["page_view_summary"], \
        f"arm1 aggregate must attribute to its own target: {pv}"
    c = _vars(res, ctx="TOP0/hive_arm1", name="pvs.country",
              vtype=VariableType.COLUMN)
    assert c and c[0].source_tables == ["page_view_stg"]


# ── #3 INSERT-target column attribution ────────────────────────────

_FLAGSHIP_PATH = SAMPLES / "sql_sample_v1" / "BDM_ACC_LOAN_INFO_SUP_M.sql"


def test_insert_target_columns_attribute_to_dml_target():
    sql = _FLAGSHIP_PATH.read_text(encoding="utf-8")
    res = extract_variables_from_sql(sql, "BDM_ACC_LOAN_INFO_SUP_M.sql")
    for name in ("total_rows", "load_time", "data_dt"):
        vs = _vars(res, ctx="TOP1", name=name)
        assert vs, f"TOP1 var {name} missing"
        # the DML insert-target column attributes to the TARGET table,
        # never to the synthetic output container
        assert vs[0].source_tables == ["rrcdm_job_log_exec_par"], \
            f"{name} must attribute to rrcdm_job_log_exec_par, got " \
            f"{vs[0].source_tables}"


# ── #4 comma-join CTE ──────────────────────────────────────────────

_Q1_PATH = SAMPLES / "tpcds" / "q1.sql"


def test_comma_join_cte_columns_stay_attribution_candidates():
    sql = _Q1_PATH.read_text(encoding="utf-8")
    res = extract_variables_from_sql(sql, "q1.sql")
    # bare columns in the comma-join CTE body (store_returns, date_dim)
    # are NOT swallowed by the CTE stamp
    for name in ("sr_customer_sk", "sr_store_sk", "d_year"):
        vs = _vars(res, ctx="CTE{customer_total_return}", name=name,
                   vtype=VariableType.COLUMN)
        assert vs, f"{name} missing in CTE body"
        assert not vs[0].source_tables, \
            f"{name} must NOT be stamped to the CTE, got " \
            f"{vs[0].source_tables}"
    # the CTE's NAMED outputs still attribute to the CTE (S2 downstream)
    ctr = _vars(res, ctx="CTE{customer_total_return}",
                name="ctr_total_return", vtype=VariableType.AGGREGATE)
    assert ctr and ctr[0].source_tables == ["customer_total_return"], \
        "CTE named output must keep its CTE attribution"
    # the unresolved comma-join columns surface as S4a candidates
    # (the S4b index re-test contract)
    cands = res.resolution_stats.get("schema_candidates", [])
    fields = {c["field"] for c in cands}
    assert "sr_customer_sk" in fields and "d_year" in fields, \
        f"comma-join columns must stay schema candidates: {fields}"


def test_comma_join_columns_attribute_to_physical_table_with_evidence():
    # In-script qualified evidence makes the physical table identifiable:
    # emp_id exists only in employees, dept_id only in departments →
    # the unique-owner S4a post-pass attributes them to their own tables.
    sql = """with w as (
    select emp_id, dept_id, sal
    from employees, departments
    where emp_dept = dept_id
)
select e.emp_id, d.dept_id from employees e, departments d
"""
    res = extract_variables_from_sql(sql, "comma_cte.sql")
    emp = _vars(res, ctx="CTE{w}", name="emp_id",
                vtype=VariableType.COLUMN)
    assert emp and emp[0].source_tables == ["employees"], \
        f"emp_id must attribute to employees: {emp}"
    dep = _vars(res, ctx="CTE{w}", name="dept_id",
                vtype=VariableType.COLUMN)
    assert dep and dep[0].source_tables == ["departments"], \
        f"dept_id must attribute to departments: {dep}"
    # no-evidence columns stay honest candidates (never guess)
    sal = _vars(res, ctx="CTE{w}", name="sal", vtype=VariableType.COLUMN)
    assert sal and not sal[0].source_tables, \
        "sal has no evidence — must stay unresolved"
    cands = res.resolution_stats.get("schema_candidates", [])
    assert any(c["field"] == "sal" for c in cands)


# ── #5 MERGE ───────────────────────────────────────────────────────

_MERGE_SQL = """-- 06_merge_update.sql: MERGE with UPDATE/INSERT branches
-- Tests: DML, MERGE target, TABLE_FLOW edges
MERGE INTO customer_summary AS target
USING (
    SELECT
        t.customer_id,
        SUM(t.amount) AS total_spent,
        COUNT(*) AS transaction_count,
        MAX(t.order_date) AS last_order_date
    FROM stg_orders t
    WHERE t.order_status = 'COMPLETED'
    GROUP BY t.customer_id
) AS source
ON target.customer_id = source.customer_id
WHEN MATCHED THEN
    UPDATE SET
        total_spent = target.total_spent + source.total_spent,
        transaction_count = target.transaction_count + source.transaction_count,
        last_order_date = GREATEST(target.last_order_date, source.last_order_date)
WHEN NOT MATCHED THEN
    INSERT (customer_id, total_spent, transaction_count, last_order_date)
    VALUES (source.customer_id, source.total_spent, source.transaction_count, source.last_order_date);
"""


def test_merge_target_is_searchable_var():
    res = extract_variables_from_sql(_MERGE_SQL, "06_merge_update.sql")
    tgt = _vars(res, ctx="TOP0", name="customer_summary",
                vtype=VariableType.MERGE_TARGET)
    assert tgt, "MERGE target must be a merge_target var"
    alias = _vars(res, ctx="TOP0", name="target",
                  vtype=VariableType.MERGE_TARGET)
    assert alias and alias[0].source_tables == ["customer_summary"]


def test_merge_update_branch_rhs_walked():
    res = extract_variables_from_sql(_MERGE_SQL, "06_merge_update.sql")
    # SET targets: bare LHS belongs to the target table
    bare = _vars(res, ctx="TOP0", name="total_spent",
                 vtype=VariableType.COLUMN)
    assert bare and bare[0].source_tables == ["customer_summary"], \
        f"bare SET LHS must belong to the target: {bare}"
    # SET RHS walked: target.total_spent + source.total_spent
    t = _vars(res, ctx="TOP0", name="target.total_spent",
              vtype=VariableType.COLUMN)
    assert t and t[0].source_tables == ["customer_summary"]
    s = _vars(res, ctx="TOP0", name="source.total_spent",
              vtype=VariableType.COLUMN)
    assert s and s[0].source_tables == ["source"]
    # insert branch: target columns + walked source values
    cid = _vars(res, ctx="TOP0", name="customer_id",
                vtype=VariableType.COLUMN)
    assert cid and cid[0].source_tables == ["customer_summary"], \
        f"MERGE INSERT column must belong to the target: {cid}"


# ── #6 PARTITION seed scoping ──────────────────────────────────────

def test_partition_seeds_scoped_to_own_dml_target():
    # Two scripts: one INSERTs PARTITION(data_dt) into ods_hie_ipacmsp,
    # another into a different table. Searching ods_hie_ipacmsp.data_dt
    # must seed only from the partition var of ods_hie_ipacmsp.
    nodes = [
        {"id": "t1", "label": "ods_hie_ipacmsp", "variable_type": "table",
         "table_name": "ods_hie_ipacmsp", "context": "TOP0"},
        {"id": "t2", "label": "other_tbl", "variable_type": "table",
         "table_name": "other_tbl", "context": "TOP1"},
        {"id": "p1", "label": "data_dt", "variable_type": "column",
         "context": "TOP0", "defined_in": "PARTITION",
         "source_tables": ["ods_hie_ipacmsp"]},
        {"id": "p2", "label": "data_dt", "variable_type": "column",
         "context": "TOP1", "defined_in": "PARTITION",
         "source_tables": ["other_tbl"]},
        {"id": "e1", "label": "e1", "variable_type": "expression",
         "context": "TOP0", "source_tables": ["ods_hie_ipacmsp"]},
        {"id": "e2", "label": "e2", "variable_type": "expression",
         "context": "TOP1", "source_tables": ["other_tbl"]},
    ]
    edges = [
        {"source": "p1", "target": "e1", "edge_type": "REF"},
        {"source": "p2", "target": "e2", "edge_type": "REF"},
    ]
    # J12-10 stage 3: the walker consumes the physical model — build it
    # from the synthetic graph data (the model's entity attribution is
    # what scopes the PARTITION seed to its own DML target table).
    graph_data = {"nodes": nodes, "edges": edges}
    pm = build_physical_model(graph_data)
    cl = compute_field_flow(graph_data, "ods_hie_ipacmsp", "data_dt",
                            physical_model=pm)
    assert "p1" in cl, "own-table PARTITION var must seed"
    assert "e1" in cl, "own-table partition flow must expand"
    assert "p2" not in cl, \
        "other-table PARTITION var must NOT seed ods_hie_ipacmsp.data_dt"
    assert "e2" not in cl


def test_partition_seed_still_works_for_own_target():
    # A script that INSERTs PARTITION(data_dt) into ods_hie_ipacmsp keeps
    # the write-side flow for its own table.
    nodes = [
        {"id": "t1", "label": "ods_hie_ipacmsp", "variable_type": "table",
         "table_name": "ods_hie_ipacmsp", "context": "TOP0"},
        {"id": "p1", "label": "data_dt", "variable_type": "column",
         "context": "TOP0", "defined_in": "PARTITION",
         "source_tables": ["ods_hie_ipacmsp"]},
        {"id": "e1", "label": "e1", "variable_type": "expression",
         "context": "TOP0", "source_tables": ["ods_hie_ipacmsp"]},
    ]
    edges = [{"source": "p1", "target": "e1", "edge_type": "REF"}]
    graph_data = {"nodes": nodes, "edges": edges}
    pm = build_physical_model(graph_data)
    cl = compute_field_flow(graph_data, "ods_hie_ipacmsp", "data_dt",
                            physical_model=pm)
    assert "p1" in cl and "e1" in cl
