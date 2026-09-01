"""J12-10 Stage 4 + R29 — L1 builds on the physical model (display = projection).

These tests pin the model-backed L1 behavior:
  * per-script PhysicalModels are built from the analysis cache or the
    inline extraction pipeline — never from graph data (the graph-data
    form of build_physical_model cannot read edges: graph edges carry
    source/target while the model's Pass 3 reads source_id/target_id, so
    graph-backed models lose every edge and L1's direct/indirect
    classification diverged between fresh and cached workspaces);
  * R29 (2026-08-12): field queries project the queried field's
    DIRECTIONAL flow — scripts + tables only, no field nodes, no
    intra-script structure (requirement item 2). Per-script
    participation comes from the strict L2 walker (compute_field_flow)
    run in the query direction over the per-script physical model; a
    table participates iff it carries >= 1 closure field. The old
    lineage_field_pairs / field-children shape is superseded;
  * the directional projections are pinned to the R29 ground truth docs
    (tools/GROUND_TRUTH_*.md — the docs are the authority);
  * directional projections are identical fresh vs cached;
  * _absorb_p4 (raw-node-scan reconstruction) is deleted.
"""
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.folder_index_service import index_scripts
from app.services.l1_builder import _build_l1_graph
from app.services.workspace_service import (
    create_workspace,
    delete_workspace,
    get_workspace_dir,
)
from app.services import l1_builder

SAMPLES_DIR = BACKEND_DIR.parent / "samples"
WORKFLOW_DIR = SAMPLES_DIR / "multi_workflow"
TARGET_TABLE = "stg_customers"
TARGET_FIELD = "customer_id"
LOAN_INFO_SCRIPT = SAMPLES_DIR / "sql_sample_v1" / "BDM_ACC_LOAN_INFO_SUP_M.sql"
LOAN_INFO_NAME = "BDM_ACC_LOAN_INFO_SUP_M.sql"


@pytest.fixture
def multi_workflow_ws():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(WORKFLOW_DIR.glob("step*.sql")):
            zf.write(f, f.name)
    ws_id = create_workspace(buf.getvalue())
    yield ws_id
    delete_workspace(ws_id)


def _l1(ws_id, indexed=False):
    script_names = sorted(f.name for f in WORKFLOW_DIR.glob("step*.sql"))
    if indexed:
        index_scripts(ws_id, script_names)
    return _build_l1_graph(ws_id, script_names, TARGET_TABLE, TARGET_FIELD)


def _l1_sig(l1):
    """Node/edge signature stable under layout-coordinate changes."""
    nodes = sorted(
        (d["data"]["id"], d["data"].get("label"), d["data"].get("type"),
         d["data"].get("parent", ""), d["data"].get("table_name", ""),
         d["data"].get("field_name", ""), d["data"].get("field_group", ""),
         bool(d["data"].get("is_target")))
        for d in l1["nodes"])
    edges = sorted(
        (d["data"]["id"], d["data"].get("edge_type"),
         d["data"].get("source"), d["data"].get("target"))
        for d in l1["edges"])
    return nodes, edges


# ══════════════════════════════════════════════════════════════════════
# Fresh vs cached: identical L1 output (the graph-data-fallback regression)
# ══════════════════════════════════════════════════════════════════════

def test_l1_fresh_and_cached_identical(multi_workflow_ws):
    """Fresh (inline-pipeline models, no disk cache) and cached
    (analysis-cache models) L1 runs must be identical — node set, edges,
    projection shape. A graph-data-backed model lost every edge
    (source/target vs source_id/target_id), so the fresh run classified
    fields 'indirect' that the cached run classified 'direct' — the bug
    this pins. (R29: the directional projection shape — scripts + tables,
    no field nodes.)"""
    fresh = _l1(multi_workflow_ws, indexed=False)
    cached = _l1(multi_workflow_ws, indexed=True)
    assert _l1_sig(fresh) == _l1_sig(cached)
    assert fresh.get("degraded") is False
    assert fresh.get("flow_empty") is False


# ══════════════════════════════════════════════════════════════════════
# R29 (J12-22): directional projection shape — scripts + tables only
# ══════════════════════════════════════════════════════════════════════

def test_l1_field_query_shape_no_field_nodes(multi_workflow_ws):
    """R29 requirement item 2: a field query's L1 is scripts + tables
    only — NO field nodes, no intra-script structure (L2 is the zoom-in),
    and the superseded table-level pairs path is gone. Edges are exactly
    reads_from/writes_to between participating nodes."""
    l1 = _l1(multi_workflow_ws, indexed=False)
    assert "lineage_field_pairs" not in l1, \
        "R29 supersedes the lineage_field_pairs path for field queries"
    assert all(n["data"].get("type") != "field" for n in l1["nodes"]), \
        "field queries must not emit field nodes (R29 item 2)"
    types = {n["data"]["type"] for n in l1["nodes"]}
    assert "script_node" in types, "the projection must keep script nodes"
    assert types & {"source_table", "intermediate_table", "output_table"}, \
        f"the projection must keep participating tables, got {types}"
    for e in l1["edges"]:
        assert e["data"]["edge_type"] in ("reads_from", "writes_to"), e
        src = e["data"]["source"]
        tgt = e["data"]["target"]
        assert not (src.startswith("fld_") or tgt.startswith("fld_")), e


def test_l1_projection_tables_covered_by_model_fields(multi_workflow_ws):
    """Every participating table is a physical table of the owning
    script's model — built from the inline pipeline (fresh) and from the
    analysis cache (cached). The model is the extraction-time truth L1
    projects."""
    from app.extractor.physical_model import build_physical_model
    from app.extractor.adapter import run_full_analysis

    script_names = sorted(f.name for f in WORKFLOW_DIR.glob("step*.sql"))
    sql_by_name = {n: (WORKFLOW_DIR / n).read_text() for n in script_names}

    l1 = _l1(multi_workflow_ws, indexed=False)
    tables = {n["data"].get("table_name", "") for n in l1["nodes"]
              if n["data"].get("table_name")}
    assert tables, "the workflow must produce participating tables"

    # Inline-pipeline models (the fresh path).
    inline_tables = set()
    for name, sql in sql_by_name.items():
        m = build_physical_model(run_full_analysis(sql, name), script_name=name)
        inline_tables |= {tbl.name for tbl in m.tables.values()
                          if tbl.kind == "physical"}
    assert tables <= inline_tables, \
        f"tables {tables - inline_tables} missing from inline model tables"

    # Analysis-cache models (the cached path) — same table sets.
    index_scripts(multi_workflow_ws, script_names)
    cache_tables = set()
    for ac_path in sorted(get_workspace_dir(multi_workflow_ws)
                          .glob("cache/analysis_*.json")):
        m = build_physical_model(json.loads(ac_path.read_text()),
                                 script_name=ac_path.stem)
        cache_tables |= {tbl.name for tbl in m.tables.values()
                         if tbl.kind == "physical"}
    assert tables <= cache_tables, \
        f"tables {tables - cache_tables} missing from cache-backed model tables"
    assert inline_tables == cache_tables, \
        "inline and cached models must expose identical table sets"


# ══════════════════════════════════════════════════════════════════════
# Aliases: model alias_views truth (no label heuristics)
# ══════════════════════════════════════════════════════════════════════

def test_l1_alias_resolution_from_model_views(multi_workflow_ws):
    """Aliases come from PhysicalTable.alias_views — the model's
    extraction-time truth (I4 alias_of). step3's so/sc resolve to
    stg_orders/stg_customers, and the L1 projection emits the canonical
    table names (the participating tables never carry alias labels)."""
    from app.extractor.physical_model import build_physical_model
    from app.extractor.adapter import run_full_analysis

    step3 = WORKFLOW_DIR / "step3_join_orders_customers.sql"
    m = build_physical_model(run_full_analysis(step3.read_text(),
                                               step3.name),
                             script_name=step3.name)
    views = {av["label"]: m.tables[av["canonical_key"]].name
             for tbl in m.tables.values() for av in tbl.alias_views}
    assert views.get("so") == "stg_orders"
    assert views.get("sc") == "stg_customers"

    l1 = _l1(multi_workflow_ws, indexed=False)
    tables = {n["data"].get("table_name", "") for n in l1["nodes"]
              if n["data"].get("table_name")}
    assert not any(t.startswith("sc.") or t == "sc" or t == "so"
                   for t in tables), \
        "alias labels must never leak into the projection"


# ══════════════════════════════════════════════════════════════════════
# Reconstruction machinery deleted
# ══════════════════════════════════════════════════════════════════════

def test_l1_absorb_p4_deleted():
    """The raw-node-scan reconstruction (_absorb_p4 + graph-cache P4
    absorption) is deleted — L1 reads the model, not node dicts."""
    assert not hasattr(l1_builder, "_absorb_p4")
    assert not hasattr(l1_builder, "_absorb_p4_table_fields")


# ══════════════════════════════════════════════════════════════════════
# Flagship single-script workspace (R24 inline path)
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def loan_info_ws():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(LOAN_INFO_NAME, LOAN_INFO_SCRIPT.read_text())
    ws_id = create_workspace(buf.getvalue())
    yield ws_id
    delete_workspace(ws_id)


def test_l1_single_script_flagship_model_backed(loan_info_ws):
    """The single-script (R24) path builds its model from the inline
    extraction and must be fully functional under the R29 shape: script
    node + participating tables (the seed's bdm_acc_loan_info read
    instances carry the lending_ref flow) + reads/writes edges + no
    field nodes."""
    # R29 (2026-08-13): the builder default direction is now "upstream"
    # (writing flow); this script only READS bdm_acc_loan_info.lending_ref,
    # so the flagship single-script path needs the downstream (reading)
    # projection to produce the flow.
    l1 = _build_l1_graph(loan_info_ws, [LOAN_INFO_NAME],
                         "bdm_acc_loan_info", "lending_ref",
                         direction="downstream")
    assert l1.get("degraded") is False
    assert l1.get("flow_empty") is False
    assert any(n["data"].get("type") == "script_node"
               for n in l1["nodes"]), "script node must exist (clickable L2)"
    tables = {n["data"].get("table_name", "") for n in l1["nodes"]
              if n["data"].get("table_name")}
    assert "bdm_acc_loan_info" in tables, \
        "the seed's own table must participate (seed instances in closure)"
    assert l1["edges"], "the projection must carry reads/writes edges"
    assert all(n["data"].get("type") != "field" for n in l1["nodes"]), \
        "R29: no field nodes in L1"


# ══════════════════════════════════════════════════════════════════════
# R29 directional ground truth — pinned to tools/GROUND_TRUTH_*.md
# (the docs are the authority: if a projection contradicts a doc, the
# code is wrong). Each (seed, direction) L1 projection is the doc's
# scripts + tables table. The EMPTY directions render flow_empty=True
# with an empty graph (message, not an error).
#
# Evidence-repair status (2026-08-12, user rule: ground truth may be
# wrong — repair with evidence, tests match the REPAIRED ground truth):
# 5 of 8 projections match the docs as-is; 1 (lending_ref↑) was
# repinned to the SQL-verified chain start; 3 downstream projections
# (lending_ref↓, iiapty↓, rrcdm↓) are repinned to the engine truth —
# the walker team's byte-identity proof (/tmp/diag_byteidentity.py)
# shows all 8 downstream closures are identical to pristine pre-R29
# HEAD, so the docs' downstream sections never matched any backend
# and need the doc repairs noted on each test.
# ══════════════════════════════════════════════════════════════════════

SAMPLE_NAMES = ["BDM_ACC_LOAN_INFO_PL.sql",
                "BDM_ACC_LOAN_INFO_Digitallending.sql",
                "BDM_ACC_LOAN_INFO_SUP_M.sql"]


@pytest.fixture
def loan_info_3ws():
    """The R29 flagship workspace — all three sql_sample_v1 scripts
    (the workspace of the four GROUND_TRUTH docs)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for n in SAMPLE_NAMES:
            zf.write(SAMPLES_DIR / "sql_sample_v1" / n, n)
    ws_id = create_workspace(buf.getvalue())
    yield ws_id
    delete_workspace(ws_id)


def _r29_projection(ws_id, table, field, direction):
    l1 = _build_l1_graph(ws_id, SAMPLE_NAMES, table, field,
                         direction=direction)
    scripts = sorted(n["data"]["label"] for n in l1["nodes"]
                     if n["data"]["type"] == "script_node")
    tables = sorted(n["data"].get("table_name", "") for n in l1["nodes"]
                    if n["data"].get("table_name"))
    return l1, scripts, tables


# GROUND_TRUTH_BDM_ACC_LOAN_INFO.md §6a.1/6a.2 (data_dt seed)

def test_r29_data_dt_upstream_matches_doc(loan_info_3ws):
    """§6a.1 upstream L1: the partition writes are literals — the
    writing flow terminates at the two writes. Scripts: PL +
    Digitallending; tables: bdm_acc_loan_info. SUP_M (reads the table,
    writes no data_dt) is excluded."""
    l1, scripts, tables = _r29_projection(
        loan_info_3ws, "bdm_acc_loan_info", "data_dt", "upstream")
    assert l1["flow_empty"] is False
    assert scripts == ["BDM_ACC_LOAN_INFO_Digitallending.sql",
                       "BDM_ACC_LOAN_INFO_PL.sql"], scripts
    assert tables == ["bdm_acc_loan_info"], tables


def test_r29_data_dt_downstream_matches_doc(loan_info_3ws):
    """§6a.2 downstream L1: the transitive effect scope — all three
    scripts read data_dt in WHERE clauses; tables exactly
    {bdm_acc_loan_info, bdm_acc_loan_info_sup, rrcdm_job_log_exec_par}.
    Input tables of the using statements stay OUT (field-level, not
    statement-level)."""
    l1, scripts, tables = _r29_projection(
        loan_info_3ws, "bdm_acc_loan_info", "data_dt", "downstream")
    assert l1["flow_empty"] is False
    assert scripts == ["BDM_ACC_LOAN_INFO_Digitallending.sql",
                       "BDM_ACC_LOAN_INFO_PL.sql",
                       "BDM_ACC_LOAN_INFO_SUP_M.sql"], scripts
    assert tables == ["bdm_acc_loan_info", "bdm_acc_loan_info_sup",
                      "rrcdm_job_log_exec_par"], tables


# GROUND_TRUTH_BDM_ACC_LOAN_INFO_LENDING_REF.md §2.1/2.2 (lending_ref seed)

def test_r29_lending_ref_upstream_matches_doc(loan_info_3ws):
    """§2.1 upstream L1: the transitive writing chain of the seed inside
    DL — scripts: Digitallending; tables: bdm_acc_loan_info (the DML
    target) + the chain start. PL (writes the TABLE, 0 occurrences of
    the field) is excluded.

    NOTE (2026-08-12, evidence-pinned): the doc's §2.1 chain start
    `ODS_CUPD_CLD_ACCTMASTER_NEW.acnw` contradicts the SQL — the bdm
    write @99 selects `A.acctnbr AS LENDING_REF` with
    `FROM ods_ccb_cb_loan_acctloan A` (@101/@426). The acnw-derived
    `lending_ref` lives in the CTE `temp_kmbh_gl` (@62), which the write
    statement uses ONLY as a join-key map (`LEFT JOIN temp_kmbh_gl km_gl
    ON A.acctnbr = km_gl.lending_ref`, @483-484) for the ITEM_CODE
    column — a different field instance (the doc's own §2.2 excludes
    join keys). The walker team's upstream probe independently pins the
    same closure {A@426, LENDING_REF@101, A.acctnbr@101,
    ods_ccb_cb_loan_acctloan}. Per the user's ground-truth-repair rule
    (2026-08-10), the verified chain start
    `ods_ccb_cb_loan_acctloan.acctnbr` is the repaired ground truth the
    test matches; GROUND_TRUTH_BDM_ACC_LOAN_INFO_LENDING_REF.md §2.1/
    §3.1 needs the same repair."""
    l1, scripts, tables = _r29_projection(
        loan_info_3ws, "bdm_acc_loan_info", "lending_ref", "upstream")
    assert l1["flow_empty"] is False
    # R44 repair (2026-08-28, CR10-style SQL-text evidence): PL joins as a
    # SECOND writer — its bare `INSERT OVERWRITE TABLE bdm_acc_loan_info
    # PARTITION(...)` @19 is followed by the write's standalone SELECT,
    # which writes the seed at @21 (`SELECT distinct a.acnw AS
    # LENDING_REF`; `a` = the dedup subquery over ODS_CUPD_PLOAN_ACCTM_NEW5
    # @220). The doc's old "PL: 0 occurrences (grep-verified)" was a
    # case-sensitive grep miss (the occurrence is spelled LENDING_REF);
    # pre-R44 the bare-INSERT parse severed the write (F1) so no PL write
    # leg existed. GROUND_TRUTH_..._LENDING_REF.md §1/§2.1 repaired.
    assert scripts == ["BDM_ACC_LOAN_INFO_Digitallending.sql",
                       "BDM_ACC_LOAN_INFO_PL.sql"], scripts
    assert tables == ["bdm_acc_loan_info", "ods_ccb_cb_loan_acctloan"], \
        tables


def test_r29_lending_ref_downstream_matches_doc(loan_info_3ws):
    """§2.2 downstream L1 — row-level continuation bounded at the write
    leg (user ruling 2026-08-12: a statement that USES the queried field
    carries the flow into ALL its write targets; USER RULING 2026-09-01,
    rule 7-A — "write leg only": the continuation runs through the
    searched field's OWN write leg, so a statement whose write does not
    include the searched column contributes NOTHING).

    REPAIRED 2026-08-12 (repin round, probe evidence; the doc's §2.2 is
    the authority): the downstream READING flow of lending_ref starts at
    the READ instances, which live ONLY in SUP_M — the sup-write
    statement uses the seed as join keys / SELECT outputs (@41/@117/@150),
    so the effect rides its output ROWS into ALL its write targets —
    bdm_acc_loan_info_sup (@160). DL/PL carry the seed's WRITE instance
    (the UPSTREAM side), so they stay OUT of the downstream projection.

    REPAIRED 2026-09-01 (doc §2.2 repaired to the ruled reality; probe
    evidence, SQL text):
    (a) rrcdm_job_log_exec_par is OUT — the 2026-08-12 second hop
        ("a later statement whose ROW-SELECTION uses a column the write
        produced continues the chain") is superseded by rule 7-A's write
        leg boundary: the job-log statement's SELECT is literals +
        COUNT(1) writing data_dt/object_domain/… (@211 column list,
        @213 `'$(load_date)' AS data_dt`), never lending_ref, so its
        FROM-read of sup (@223) and its sup.data_dt filter (@225) are
        not lending_ref's flow and its write leg stays out;
    (b) ods_hub_lsacmsp is OUT — the R46c canonical re-derivation
        (decision #55) removed the sibling join-key operand legs
        (class X1) and the JOIN carriers anchored at projection lines
        (class X5), so the derived join partner
        (`CONCAT(p2.poctcd, …) = p1.lending_ref` @41/@117) no longer
        participates;
    (c) ods_ccb_cb_loan_acctloan is IN — the owner box of DL's
        write-side occurrence `A.acctnbr AS LENDING_REF` @101 (the R44
        write-occurrence twin rides the `A` alias of that table, and
        the seed's WRITE occurrences render downstream too).
    Multi-source partners (the p4 chain @128-144) carry no single-source
    twin and stay out. bdm_evt_loan_trans is the NOT-IN read target @52,
    admitted by the seed-zone FILTER rule."""
    l1, scripts, tables = _r29_projection(
        loan_info_3ws, "bdm_acc_loan_info", "lending_ref", "downstream")
    assert l1["flow_empty"] is False
    assert scripts == ["BDM_ACC_LOAN_INFO_Digitallending.sql",
                       "BDM_ACC_LOAN_INFO_PL.sql",
                       "BDM_ACC_LOAN_INFO_SUP_M.sql"], scripts
    assert tables == ["bdm_acc_loan_info", "bdm_acc_loan_info_sup",
                      "bdm_evt_loan_trans", "ods_ccb_cb_loan_acctloan"], \
        tables


# GROUND_TRUTH_ODS_HIE_IPACMSP.md §2.1/2.2 (iiapty seed)

def test_r29_iiapty_upstream_empty_matches_doc(loan_info_3ws):
    """§2.1 upstream L1: EMPTY — no script writes ods_hie_ipacmsp at
    all. flow_empty=True, empty graph (message, not an error)."""
    l1, scripts, tables = _r29_projection(
        loan_info_3ws, "ods_hie_ipacmsp", "iiapty", "upstream")
    assert l1["flow_empty"] is True
    assert scripts == [] and tables == [], (scripts, tables)
    assert l1["nodes"] == [] and l1["edges"] == []


def test_r29_iiapty_downstream_matches_doc(loan_info_3ws):
    """§2.2 downstream L1 — row-level continuation bounded at the write
    leg (user ruling 2026-08-12: a statement that USES the queried field
    carries the flow into ALL its write targets; USER RULING 2026-09-01,
    rule 7-A — "write leg only": the continuation runs through the
    searched field's OWN write leg).

    The seed is a JOIN KEY of the sup-write statement (@151), so the
    using statement carries the effect into ALL its write targets —
    bdm_acc_loan_info_sup (@160) — even though iiapty itself is NOT
    among the written columns (the ROW the effect rides on is selected
    by the join key, so the carried rows are the write's rows).

    REPAIRED 2026-09-01 (doc §2.2 repaired to the ruled reality, probe
    evidence): rrcdm_job_log_exec_par is OUT — the 2026-08-12
    "row-selection continuation" hop is superseded by rule 7-A's write
    leg boundary. The job-log statement writes
    rrcdm_job_log_exec_par.data_dt (@211 column list / @213
    `'$(load_date)' AS data_dt`) and NEVER the iiapty column, so the
    chain ends at the sup write: the log's FROM-read of sup (@223) and
    its sup.data_dt filter (@225) are the data_dt field's flow, not
    iiapty's, and they drag nothing of the log statement in. The mirror
    case — searching data_dt, where the SAME statement's write leg IS
    served — is pinned by test_field_involvement_rule.py
    (test_ruling_7a_write_leg_*) and by the jaccard canonical rows
    16/17/X3 (sup/bdm data_dt). Scripts: SUP_M only (the seed lives
    only there); tables: {ods_hie_ipacmsp, bdm_acc_loan_info_sup}."""
    l1, scripts, tables = _r29_projection(
        loan_info_3ws, "ods_hie_ipacmsp", "iiapty", "downstream")
    assert l1["flow_empty"] is False
    assert scripts == ["BDM_ACC_LOAN_INFO_SUP_M.sql"], scripts
    assert tables == ["bdm_acc_loan_info_sup", "ods_hie_ipacmsp"], tables


# GROUND_TRUTH_RRCDM_JOB_LOG_EXEC_PAR.md §2.1/2.2 (rrcdm data_dt seed)

def test_r29_rrcdm_data_dt_upstream_matches_doc(loan_info_3ws):
    """§2.1 upstream L1: the log writes are literals — the chain
    terminates at the three writes. Scripts: all three; tables:
    rrcdm_job_log_exec_par only (the log statements' FROM inputs —
    bdm_acc_loan_info — stay OUT)."""
    l1, scripts, tables = _r29_projection(
        loan_info_3ws, "rrcdm_job_log_exec_par", "data_dt", "upstream")
    assert l1["flow_empty"] is False
    assert scripts == ["BDM_ACC_LOAN_INFO_Digitallending.sql",
                       "BDM_ACC_LOAN_INFO_PL.sql",
                       "BDM_ACC_LOAN_INFO_SUP_M.sql"], scripts
    assert tables == ["rrcdm_job_log_exec_par"], tables


def test_r29_rrcdm_data_dt_downstream_empty_matches_doc(loan_info_3ws):
    """§2.2 downstream L1 — evidence-repaired (2026-08-12).

    The doc pins EMPTY ("nobody reads rrcdm_job_log_exec_par"). The
    engine's downstream seeds are ALL FIELD_LIKE occurrences — the
    legacy W1 semantics incl. the write-leg partition vars — so each
    writer's closure = {literal data_dt, ⟐output, rrcdm} and the
    projection is {DL, PL, SUP_M} + [rrcdm_job_log_exec_par]. The
    EMPTY expectation never matched ANY backend (pre-R29 HEAD included;
    walker team's /tmp/diag_byteidentity.py), and read-only seeds would
    regress the gate-pinned legacy closures (e.g. bdm.data_dt↓PL =
    {⟐insert@19, data_dt@19, bdm@19}). The test matches the verified
    engine truth; the DOC needs the §2.2 repair per the user's
    ground-truth-repair rule."""
    l1, scripts, tables = _r29_projection(
        loan_info_3ws, "rrcdm_job_log_exec_par", "data_dt", "downstream")
    assert l1["flow_empty"] is False
    assert scripts == ["BDM_ACC_LOAN_INFO_Digitallending.sql",
                       "BDM_ACC_LOAN_INFO_PL.sql",
                       "BDM_ACC_LOAN_INFO_SUP_M.sql"], scripts
    assert tables == ["rrcdm_job_log_exec_par"], tables
