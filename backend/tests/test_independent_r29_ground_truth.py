"""CR10 — INDEPENDENT ground-truth re-derivation for the R29 direction seeds.

CR10 ruling (2026-08-13): ground truth MUST be built by a DIFFERENT /
independent method — it can never be derived from the system's own
output. The 2026-08-12 REPIN round (jaccard_canonical.py point 15)
pinned the R29 direction closures (rrcdm down, iiapty down, lending_ref
up/down, plus the bdm-up partition chains) FROM SERVED L2 CLOSURES —
i.e. from the engine's own emitted output. That is circular: with floors
at exactly 1.0000/1.0000, the benchmark now asserts the engine matches
its own output, so the J12-21 class (silent over/under-admission) would
be enshrined as correct.

THIS MODULE is the "distinct independent assertion" CR10 requires for
each repinned seed. It re-derives the ground truth from the SQL SOURCE
TEXT alone (samples/sql_sample_v1/*.sql) and asserts it WITHOUT ever
building an L2 graph, calling the engine, or reading a captured payload:

  1. Every key flow fact is asserted as an exact (line, substring) pair
     of the script — the line NUMBER is part of the assertion (catches
     drift) AND the line content is checked. The facts are the data-flow
     reasoning itself (FROM / WHERE / INSERT / JOIN / PARTITION sites).
  2. Node-groundedness: every canonical closure node (jaccard_canonical
     CANONICAL_NODES_DIR) for the repinned seeds is asserted to be a
     real identifier of the script text — the only exceptions are the
     documented engine-form virtual tables (⟐output / ⟐subq / ⟐subq1)
     and the served-truncated CONCAT expression labels.

If this module passes, the canonical NODE/flow content of the repinned
seeds is SQL-derived, not engine-derived. The engine-vs-canonical
benchmark (test_jaccard_benchmark.py) keeps comparing the engine to
that SQL-derived ground truth; the rows whose exact edge FORMS are
engine-emission conventions are flagged "pending" in jaccard_canonical.py
and printed distinctly by the consumer test (never silently asserted).

Seeds re-derived here: rrcdm (down, all 3 scripts), iiapty (down +
up-empty, SUP_M), lending_ref (up, DL; down, SUP_M), bdm data_dt
(up, PL + DL; up-empty, SUP_M).
"""

import sys
from pathlib import Path

import pytest

# tests/ is not on sys.path in the pytest run — sibling data module.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import jaccard_canonical as JC  # noqa: E402

# Container layout: /app/samples/sql_sample_v1; repo layout: ../../samples.
_SAMPLES = (
    Path("/app/samples/sql_sample_v1")
    if Path("/app/samples").exists()
    else Path(__file__).resolve().parent.parent.parent / "samples" / "sql_sample_v1"
)

SQL_SUP_M = "BDM_ACC_LOAN_INFO_SUP_M.sql"
SQL_PL = "BDM_ACC_LOAN_INFO_PL.sql"
SQL_DL = "BDM_ACC_LOAN_INFO_Digitallending.sql"


def sql_lines(name):
    """1-based line-indexed text of a sample script (lines[0] is line 1)."""
    return (_SAMPLES / name).read_text(encoding="utf-8").splitlines()


def assert_sql_fact(lines, line_no, substr, ctx=""):
    """Assert that line `line_no` (1-based) contains `substr`. The line
    NUMBER is part of the assertion — drift in the script must fail this,
    not silently slide the pin."""
    assert 1 <= line_no <= len(lines), (
        f"{ctx}: line {line_no} out of range (script has {len(lines)} lines)")
    line = lines[line_no - 1]
    assert substr.lower() in line.lower(), (
        f"{ctx}: line {line_no} expected to contain {substr!r}, got: {line!r}")


# ── Node-groundedness helpers ────────────────────────────────────────
# Canonical node labels that are engine-form (never literals of the SQL
# text): the ⟐ output / subquery virtual tables and the served-truncated
# CONCAT expression labels. Everything else must be a substring of the
# script text (case-insensitive) — proving the closure only contains
# identifiers that actually exist in the source.
_ENGINE_FORM_PREFIXES = ("⟐", "CONCAT")


def _node_base(label):
    """Strip the alias-embedded line suffix: 'p5@151' -> 'p5'."""
    return label.split("@")[0]


def assert_canon_nodes_sql_grounded(seed, script, direction, lines, ctx=""):
    """Every canonical closure node of a repinned seed is either a real
    identifier of the script text (its base label appears in the source)
    or a documented engine-form virtual/expression label."""
    nodes = JC.CANONICAL_NODES_DIR.get((seed, script, direction))
    assert nodes is not None, f"{ctx}: no CANONICAL_NODES_DIR entry for {seed}/{script}/{direction}"
    full = "\n".join(lines).lower()
    for nd in nodes:
        base = _node_base(nd["label"])
        if base.startswith(_ENGINE_FORM_PREFIXES):
            continue  # ⟐output/⟐subq/⟐subq1 VT, or served-truncated CONCAT
        assert base.lower() in full, (
            f"{ctx}: canonical node label {base!r} (line {nd['line']}) is NOT a "
            f"real identifier in {script} — the closure is not SQL-derived")
        if nd.get("line"):
            assert 1 <= nd["line"] <= len(lines), (
                f"{ctx}: canonical node {base!r} line {nd['line']} out of range")


# ── bdm.data_dt upstream (partition writes) ──────────────────────────
def test_bdm_up_pl_partition_write():
    """bdm↑PL — data_dt is written ONLY by the literal partition @19."""
    lines = sql_lines(SQL_PL)
    assert_sql_fact(lines, 19, "INSERT OVERWRITE TABLE bdm_acc_loan_info",
                    "bdm↑PL write site")
    assert_sql_fact(lines, 19, "PARTITION(data_dt='${load_date}'",
                    "bdm↑PL literal partition")
    assert_canon_nodes_sql_grounded("bdm", SQL_PL, "upstream", lines, "bdm↑PL")


def test_bdm_up_dl_partition_write():
    """bdm↑DL — data_dt written ONLY by the literal partition @99."""
    lines = sql_lines(SQL_DL)
    assert_sql_fact(lines, 99, "INSERT OVERWRITE TABLE bdm_acc_loan_info",
                    "bdm↑DL write site")
    assert_sql_fact(lines, 99, "PARTITION (data_dt = '$(load_date)'",
                    "bdm↑DL literal partition")
    assert_canon_nodes_sql_grounded("bdm", SQL_DL, "upstream", lines, "bdm↑DL")


def test_bdm_up_sup_m_empty():
    """bdm↑SUP_M — EMPTY: SUP_M READS bdm but writes no data_dt into it."""
    lines = sql_lines(SQL_SUP_M)
    # SUP_M's only bdm_acc_loan_info writes... there are none; its DML
    # targets are bdm_acc_loan_info_sup @160 and rrcdm_job_log_exec_par @211.
    assert JC.CANONICAL_NODES_DIR[("bdm", SQL_SUP_M, "upstream")] == []
    assert not any("INSERT OVERWRITE TABLE bdm_acc_loan_info " in l
                   for l in lines), "SUP_M must not write bdm_acc_loan_info"


# ── rrcdm.data_dt (writer's own leg, all 3 scripts) ──────────────────
def test_rrcdm_down_write_chain():
    """rrcdm↓ — the writer's OWN leg: literal -> data_dt write column ->
    -> statement output -> rrcdm DML target, in every writer script."""
    for name, ins_line, sel_line in (
        (SQL_PL, 253, 254),
        (SQL_SUP_M, 211, 213),
        (SQL_DL, 549, 550),
    ):
        lines = sql_lines(name)
        ctx = f"rrcdm↓{name}"
        assert_sql_fact(lines, ins_line, "INSERT INTO TABLE rrcdm_job_log_exec_par",
                        ctx)
        assert_sql_fact(lines, ins_line, "data_dt", ctx)   # target column list
        assert_sql_fact(lines, sel_line, "AS data_dt", ctx)  # literal write column
        assert_sql_fact(lines, sel_line, "load_date", ctx)   # literal source
        assert_canon_nodes_sql_grounded("rrcdm", name, "downstream", lines, ctx)


def test_rrcdm_no_reader():
    """rrcdm.data_dt has NO reader anywhere (writer's-own-leg shape): no
    script ever reads rrcdm_job_log_exec_par in a FROM/WHERE."""
    for name in (SQL_PL, SQL_SUP_M, SQL_DL):
        lines = sql_lines(name)
        for i, l in enumerate(lines, 1):
            if "rrcdm_job_log_exec_par" in l and "INSERT INTO TABLE" not in l:
                pytest.fail(f"{name}:{i} reads rrcdm — {l!r} (downstream "
                            f"must be the writer's own leg, not a read)")


# ── iiapty (downstream join-key closure + row-level continuation) ────
def test_iiapty_down_seed_zone_and_continuation():
    """iiapty↓SUP_M — the seed is the p5.iiapty join key @151-153 inside
    the sup-write statement; the row-level continuation carries the flow
    through the sup write @160 and the sup.data_dt filter @225 into the
    rrcdm write @211."""
    lines = sql_lines(SQL_SUP_M)
    # seed zone
    assert_sql_fact(lines, 151, "LEFT JOIN ods_hie_ipacmsp p5", "iiapty seed zone")
    assert_sql_fact(lines, 153, "p5.iiapty = p4.iiapty", "iiapty join key")
    # sup write target of the using statement
    assert_sql_fact(lines, 160, "INSERT OVERWRITE TABLE bdm_acc_loan_info_sup",
                    "iiapty sup write")
    # the using statement's p2 self-join zone
    assert_sql_fact(lines, 199, "LEFT JOIN bdm_acc_loan_info_sup p2",
                    "iiapty p2 self-join")
    assert_sql_fact(lines, 202, "p2.data_dt", "iiapty p2 data_dt key")
    # rrcdm continuation: the log statement reads sup rows selected by
    # data_dt @225 and writes rrcdm @211.
    assert_sql_fact(lines, 211, "INSERT INTO TABLE rrcdm_job_log_exec_par",
                    "iiapty rrcdm write")
    assert_sql_fact(lines, 222, "FROM", "iiapty rrcdm FROM")
    assert_sql_fact(lines, 223, "bdm_acc_loan_info_sup", "iiapty rrcdm FROM table")
    assert_sql_fact(lines, 225, "data_dt = '$(load_date)'", "iiapty rrcdm filter")
    assert_canon_nodes_sql_grounded("iiapty", SQL_SUP_M, "downstream", lines,
                                    "iiapty↓SUP_M")


def test_iiapty_up_empty():
    """iiapty↑SUP_M — EMPTY: no script writes ods_hie_ipacmsp at all."""
    assert JC.CANONICAL_NODES_DIR[("iiapty", SQL_SUP_M, "upstream")] == []
    for name in (SQL_PL, SQL_SUP_M, SQL_DL):
        lines = sql_lines(name)
        for i, l in enumerate(lines, 1):
            if "ods_hie_ipacmsp" in l and "INSERT" in l.upper():
                pytest.fail(f"{name}:{i} writes ods_hie_ipacmsp — {l!r}")


# ── lending_ref upstream (the real producer chain) ───────────────────
def test_lending_ref_up_dl_chain():
    """lending_ref↑DL — the producing chain runs from the ODS FROM source
    ods_ccb_cb_loan_acctloan A (A.acctnbr @426) through the statement
    output column A.acctnbr AS LENDING_REF @101 into the write target
    bdm_acc_loan_info @99."""
    lines = sql_lines(SQL_DL)
    assert_sql_fact(lines, 99, "INSERT OVERWRITE TABLE bdm_acc_loan_info",
                    "lending_ref↑DL write site")
    assert_sql_fact(lines, 101, "A.acctnbr AS LENDING_REF", "lending_ref↑DL output col")
    assert_sql_fact(lines, 426, "FROM ods_ccb_cb_loan_acctloan A",
                    "lending_ref↑DL chain start")
    assert_canon_nodes_sql_grounded("lending_ref", SQL_DL, "upstream", lines,
                                    "lending_ref↑DL")


def test_lending_ref_up_acnw_not_the_chain():
    """lending_ref↑DL — the acnw instances @62/@82 belong to the
    temp_kmbh_gl / temp_kmbh_ie CTE segment (sourced from
    ODS_CUPD_CLD_ACCTMASTER_NEW), NOT to the seed's producing chain."""
    lines = sql_lines(SQL_DL)
    assert_sql_fact(lines, 62, "SELECT p1.acnw AS lending_ref", "temp_kmbh_gl")
    assert_sql_fact(lines, 82, "SELECT p1.acnw AS lending_ref", "temp_kmbh_ie")
    # The seed chain never touches ODS_CUPD_CLD_ACCTMASTER_NEW between the
    # write @99 and the source @426 (the chain start is the A alias @426).
    assert_sql_fact(lines, 426, "FROM ods_ccb_cb_loan_acctloan A",
                    "lending_ref↑DL real chain start")


# ── lending_ref downstream (CTE-zone closure + continuation) ─────────
def test_lending_ref_down_sup_m_flow():
    """lending_ref↓SUP_M — the CTE-zone usages (rollover/loan_final join
    keys @41/@117/@150, the NOT-IN read @52, SELECT outputs @67) plus the
    row-level continuation through the sup write @160 into rrcdm @211."""
    lines = sql_lines(SQL_SUP_M)
    # rollover CTE SELECT output
    assert_sql_fact(lines, 13, "lending_ref", "lending_ref↓ rollover output")
    assert_sql_fact(lines, 15, "FROM", "lending_ref↓ rollover FROM")
    assert_sql_fact(lines, 16, "bdm_acc_loan_info", "lending_ref↓ rollover FROM table")
    # subq join-key operands
    assert_sql_fact(lines, 41, "CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0')",
                    "lending_ref↓ subq join key")
    assert_sql_fact(lines, 50, "DISTINCT lending_ref", "lending_ref↓ NOT-IN subq")
    assert_sql_fact(lines, 51, "FROM", "lending_ref↓ NOT-IN target")
    assert_sql_fact(lines, 52, "bdm_evt_loan_trans", "lending_ref↓ NOT-IN target table")
    # loan_final join-key operands
    assert_sql_fact(lines, 117, "CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0')",
                    "lending_ref↓ loan_final join key")
    assert_sql_fact(lines, 150, "RPAD(p4.iiapty,3,'')||p4.iiblno = p1.lending_ref",
                    "lending_ref↓ p4 join key")
    # sup write + p2 self-join + rrcdm continuation
    assert_sql_fact(lines, 160, "INSERT OVERWRITE TABLE bdm_acc_loan_info_sup",
                    "lending_ref↓ sup write")
    assert_sql_fact(lines, 199, "LEFT JOIN bdm_acc_loan_info_sup p2",
                    "lending_ref↓ p2 self-join")
    assert_sql_fact(lines, 201, "p2.lending_ref = p1.lending_ref",
                    "lending_ref↓ p2 lending_ref key")
    assert_sql_fact(lines, 211, "INSERT INTO TABLE rrcdm_job_log_exec_par",
                    "lending_ref↓ rrcdm write")
    assert_sql_fact(lines, 222, "FROM", "lending_ref↓ rrcdm FROM")
    assert_sql_fact(lines, 223, "bdm_acc_loan_info_sup", "lending_ref↓ rrcdm FROM table")
    assert_sql_fact(lines, 225, "data_dt = '$(load_date)'", "lending_ref↓ rrcdm filter")
    assert_canon_nodes_sql_grounded("lending_ref", SQL_SUP_M, "downstream", lines,
                                    "lending_ref↓SUP_M")


def test_lending_ref_pl_produces_lending_ref():
    """PL DOES produce a LENDING_REF column — `a.acnw AS LENDING_REF` @21
    (inside the bdm_acc_loan_info INSERT @19). It is a WRITER of
    bdm_acc_loan_info.lending_ref, not a non-writer: the prior "0
    occurrences" claim was wrong (the OCR-reconstructed PL keeps the
    borrow-number alias). Pins the SQL fact independently of the engine;
    whether the canonical lending_ref upstream should therefore also list
    PL is a separate under-admission question, not asserted here."""
    lines = sql_lines(SQL_PL)
    assert_sql_fact(lines, 21, "a.acnw AS LENDING_REF", "PL produces LENDING_REF")


# ── Repin-round DUPLICATE / self-loop defect guard ───────────────────
def test_no_duplicate_canonical_edges():
    """CR10: the repin round dumped the served closures into the
    canonical — a dump artifact can produce DUPLICATE rows. The canonical
    must not contain two identical (seed, script, direction, src, dst,
    type, anchor) entries (a used-set matcher can realize each row at most
    once; a duplicate is either a copy-paste artifact or the engine
    emitting a degenerate edge — both must be surfaced, never silently
    asserted twice)."""
    seen = {}
    for e in JC.CANONICAL_EDGES:
        key = (e["seed"], e.get("script"), e.get("direction", "downstream"),
               e["src"], e["dst"], e["type"], e["anchor"])
        if key in seen:
            pytest.fail(
                f"duplicate canonical edge: {seen[key]} and {e['row']} both = "
                f"{key} — a served-closure dump artifact (CR10). Re-derive or "
                f"remove; do not assert engine==engine twice.")


def test_no_self_loop_edges():
    """CR10: a data-flow edge whose src == dst endpoint is a degenerate
    self-loop — the row-11 class (removed 2026-08-10 for exactly this).
    The repin round re-introduced self-loops from the served closures; the
    canonical must not carry them (they have no SQL-text data-flow
    meaning)."""
    for e in JC.CANONICAL_EDGES:
        assert e["src"] != e["dst"], (
            f"self-loop canonical edge {e['row']}: {e['src']} -> {e['dst']} "
            f"({e['type']}@{e['anchor']}) — the degenerate row-11 class "
            f"(CR10: re-derive, do not assert engine==engine)")
