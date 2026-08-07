"""BDM_ACC_LOAN_INFO_SUP_M.sql — ground-truth data flow pin (v3.3.145 baseline).

Hand-verified data flow of samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql.
This is the reference for FUTURE WORK: any extractor / graph change that
alters these flows (or the data_dt L2 closure below) must be justified.

┌─ SCRIPT STRUCTURE ─────────────────────────────────────────────────────┐
│ Stmt1 (L9-208):  WITH rollover_loan_info (L9-63), loan_final (L64-159) │
│                  INSERT OVERWRITE bdm_acc_loan_info_sup                │
│                  PARTITION(data_dt, CHARGE_DEPARTMENT)                 │
│ Stmt2 (L211-225): INSERT INTO rrcdm_job_log_exec_par                   │
└────────────────────────────────────────────────────────────────────────┘

TABLE-LEVEL FLOW (reads → consumer):
  bdm_acc_loan_info (L16, L29) ─► rollover_loan_info
  ods_hub_lsacmsp (L33)        ─► rollover_loan_info
  bdm_evt_loan_trans (L52)     ─► rollover_loan_info
  bdm_acc_loan_info (L84)      ─► loan_final            (p1)
  bdm_gdc_label_fin (L89, L93) ─► loan_final            (accu / t)
  ods_cdp_gdc_acct_migrate_to_diff_branches (L101, L103)─► loan_final (branch / a)
  ods_hub_lsacmsp (L33)        ─► loan_final            (p2, derived)
  ods_hub_ssclmtp (L118)       ─► loan_final            (p3)
  ods_hie_ipblmsp (L132) / ods_hie_ipdcmsp (L133) / ods_hie_ippdcpp (L137) ─► loan_final (p4)
  ods_hie_ipacmsp (L151)       ─► loan_final            (p5)
  rollover_loan_info (L155)    ─► loan_final            (p6, CTE)
  loan_final (L198)            ─► bdm_acc_loan_info_sup (stmt1 target)
  bdm_acc_loan_info_sup (L199) ─► bdm_acc_loan_info_sup (prev-day self join, p2)
  bdm_sys_acc_loan_info (L204) ─► bdm_acc_loan_info_sup (p3)
  bdm_acc_loan_info_sup (L223) ─► rrcdm_job_log_exec_par (stmt2 target)

ALIAS DEF LINES (I1 semantics — first token of the defining clause):
  p1@29 (rollover inner), p2@40 (rollover inner derived), a@52 (NOT IN subq),
  p1@84 (loan_final), t@93 / accu@94 (label subq), a@103 / branch@104,
  p2@116 (derived), p3@118, a@132 / b@133 / c@137 / p4@149 (p4 derived),
  p5@151, p6@155, p1@198 / p2@199 / p3@204 (stmt1 main)

FIELD-LEVEL GROUND TRUTH — bdm_acc_loan_info.data_dt (L2 closure, 11/5):
  Reads:    L18 (CTE1 WHERE, bare), L43 (SUBSTR(p1.data_dt,1,7) filter,
            rollover inner), L158 (CTE2 WHERE p1.data_dt='$(load_date)')
  Write:    L160 (PARTITION(data_dt=...) of stmt1 target)
  NOT included (different owners): L93 (t.data_dt, bdm_gdc_label_fin),
  L202 (p2.data_dt, self-join), L225 (stmt2 WHERE, bdm_acc_loan_info_sup)
  Highlights: [[18,18],[43,43],[158,158],[160,160]] (byte-exact verified)
"""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.extractor.dependency_graph import build_dependency_graph
from app.services.graph_service import build_graph_data
from app.services.dataflow_service import filter_by_field_flow

_SAMPLE_NAME = "BDM_ACC_LOAN_INFO_SUP_M.sql"


def _load_sample() -> str:
    for base in (REPO_ROOT / "samples" / "sql_sample_v1",
                 Path("/app/samples/sql_sample_v1")):
        p = base / _SAMPLE_NAME
        if p.exists():
            return p.read_text(encoding="utf-8")
    pytest.fail(f"sample not found: {_SAMPLE_NAME}")


@pytest.fixture(scope="module")
def bdm():
    sql_text = _load_sample()
    result = extract_variables_from_sql(sql_text, _SAMPLE_NAME)
    deps = build_dependency_graph(result, sql_text)
    by_id = {v.id: v for v in result.variables}
    analysis = {
        "variables": [v.model_dump() for v in result.variables],
        "dependencies": [d.model_dump() for d in deps],
    }
    return sql_text, result, deps, by_id, analysis


def _nm(by_id, nid):
    v = by_id.get(nid)
    return f"{v.name}@{v.line_start}" if v else nid[:8]


# ── Global extraction ground truth ──────────────────────────────────────

def test_parse_errors_empty(bdm):
    _, result, _, _, _ = bdm
    assert result.parse_errors == []


def test_global_counts(bdm):
    _, result, deps, _, _ = bdm
    assert len(result.variables) == 253
    assert len(deps) == 649


def test_alias_pairs_exact(bdm):
    """I4: exactly 14 ALIAS edges, original table/CTE → its alias var."""
    _, _, deps, by_id, _ = bdm
    pairs = sorted((_nm(by_id, d.source_id), _nm(by_id, d.target_id))
                   for d in deps if d.relationship == "ALIAS")
    assert pairs == [
        "bdm_acc_loan_info@29 -> p1@29",
        "bdm_acc_loan_info@84 -> p1@84",
        "bdm_acc_loan_info_sup@160 -> p2@199",
        "bdm_evt_loan_trans@52 -> a@52",
        "bdm_gdc_label_fin@93 -> t@93",
        "bdm_sys_acc_loan_info@204 -> p3@204",
        "loan_final@64 -> p1@198",
        "ods_cdp_gdc_acct_migrate_to_diff_branches@103 -> a@103",
        "ods_hie_ipacmsp@151 -> p5@151",
        "ods_hie_ipblmsp@132 -> a@132",
        "ods_hie_ipdcmsp@133 -> b@133",
        "ods_hie_ippdcpp@137 -> c@137",
        "ods_hub_ssclmtp@118 -> p3@118",
        "rollover_loan_info@9 -> p6@155",
    ]


def test_table_like_inventory_by_context(bdm):
    """Every table/cte/subquery var grouped by scope — the read ground truth."""
    _, result, _, _, _ = bdm
    inv = {}
    for v in result.variables:
        if v.variable_type.value in ("table", "cte", "subquery"):
            inv.setdefault(v.context, set()).add(f"{v.name}@{v.line_start}")
    assert inv == {
        "CTE{rollover_loan_info}": {"bdm_acc_loan_info@16"},
        "CTE{rollover_loan_info}/subq1/subq": {
            "bdm_acc_loan_info@29", "p1@29", "ods_hub_lsacmsp@33"},
        "CTE{rollover_loan_info}/subq1/subq:join:p2": {
            "ods_hub_lsacmsp@33", "p2@40"},
        "CTE{rollover_loan_info}/subq1/subq/subq2": {
            "a@52", "bdm_evt_loan_trans@52"},
        "CTE{loan_final}": {
            "bdm_acc_loan_info@84", "p1@84", "ods_hub_ssclmtp@118", "p3@118",
            "ods_hie_ipacmsp@151", "p5@151", "p6@155"},
        "CTE{loan_final}:join:accu": {"bdm_gdc_label_fin@89", "accu@94"},
        "CTE{loan_final}:join:accu/subq3": {"bdm_gdc_label_fin@93", "t@93"},
        "CTE{loan_final}:join:branch": {
            "ods_cdp_gdc_acct_migrate_to_diff_branches@101", "branch@104"},
        "CTE{loan_final}:join:branch/subq4": {
            "ods_cdp_gdc_acct_migrate_to_diff_branches@103", "a@103"},
        "CTE{loan_final}:join:p2": {"ods_hub_lsacmsp@33", "p2@116"},
        "CTE{loan_final}:join:p4": {
            "a@132", "ods_hie_ipblmsp@132", "b@133", "ods_hie_ipdcmsp@133",
            "c@137", "ods_hie_ippdcpp@137", "p4@149"},
        "TOP0": {
            "bdm_acc_loan_info_sup@160", "loan_final@198", "p1@198",
            "bdm_acc_loan_info_sup@199", "p2@199",
            "bdm_sys_acc_loan_info@204", "p3@204"},
        "TOP1": {"rrcdm_job_log_exec_par@211", "bdm_acc_loan_info_sup@223"},
    }


def test_virtual_table_containers(bdm):
    """⟐ intermediate nodes: 12 across 11 distinct container contexts."""
    _, result, _, _, _ = bdm
    containers = sorted({v.context for v in result.variables
                         if v.variable_type.value == "virtual_table"})
    assert len(containers) == 12


def test_dml_write_targets(bdm):
    """Stmt1 writes 15 fields into bdm_acc_loan_info_sup; stmt2 writes 1 row."""
    _, _, deps, by_id, _ = bdm
    writes = sorted(_nm(by_id, d.source_id) for d in deps
                    if d.relationship == "DML"
                    and _nm(by_id, d.target_id) == "bdm_acc_loan_info_sup@160")
    assert writes == [
        "p1.abnormal_issue_flag@171", "p1.acct_no@69", "p1.branch_code_sk@168",
        "p1.contract_no@68", "p1.desc_length20@169", "p1.interest_type@167",
        "p1.internal_key@162", "p1.limit_contract_no@170",
        "p1.product_code@166", "p1.sys_src_code@78",
        "p1.tag_primary_accountable_party@76", "p1.tag_responsible_party@77",
        "reserved_field6@181", "reserved_field7@182", "reserved_field8@183",
    ]
    log_writes = [d for d in deps if d.relationship == "DML"
                  and _nm(by_id, d.target_id) == "rrcdm_job_log_exec_par@211"]
    assert len(log_writes) == 1


# ── Field-level ground truth: bdm_acc_loan_info.data_dt ─────────────────

@pytest.fixture(scope="module")
def data_dt_l2(bdm):
    """L2 closure exactly as the live level2 API computes it."""
    _, _, _, _, analysis = bdm
    graph = build_graph_data(analysis)
    return filter_by_field_flow(graph, "bdm_acc_loan_info", "data_dt",
                                table_schemas=None)


def test_data_dt_closure_nodes(data_dt_l2, bdm):
    """The 11-node closure — the reference diagram for future work."""
    _, _, _, by_id, _ = bdm
    nodes = {_nm(by_id, n["data"]["id"]) for n in data_dt_l2["nodes"]}
    assert nodes == {
        "rollover_loan_info@9", "bdm_acc_loan_info@16", "data_dt@18",
        "⟐ subq@0", "bdm_acc_loan_info@29", "p1.data_dt@43",
        "loan_final@64", "bdm_acc_loan_info@84", "p1.data_dt@158",
        "bdm_acc_loan_info_sup@160", "data_dt@160",
    }


def test_data_dt_closure_edges(data_dt_l2, bdm):
    _, _, _, by_id, _ = bdm
    edges = sorted((e["data"].get("relationship", "?"),
                    _nm(by_id, e["data"]["source"]),
                    _nm(by_id, e["data"]["target"]))
                   for e in data_dt_l2["edges"])
    assert edges == [
        ("FILTER", "p1.data_dt@158", "loan_final@64"),
        ("FILTER", "p1.data_dt@43", "⟐ subq@0"),
        ("SUBSET", "bdm_acc_loan_info@16", "rollover_loan_info@9"),
        ("SUBSET", "data_dt@18", "bdm_acc_loan_info@16"),
        ("SUBSET", "data_dt@160", "bdm_acc_loan_info_sup@160"),
    ]


def test_data_dt_touch_lines(data_dt_l2, bdm):
    """The 4 touch points → highlight ground truth [[18],[43],[158],[160]]."""
    _, _, _, by_id, _ = bdm
    lines = sorted({by_id[n["data"]["id"]].line_start
                    for n in data_dt_l2["nodes"]
                    if by_id[n["data"]["id"]].variable_type.value == "column"})
    assert lines == [18, 43, 158, 160]
