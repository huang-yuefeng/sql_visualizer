"""Rule 4e — producer-occurrence anchoring (user ruling 2026-09-02, "fix now").

THE DEFECT (EAST5 × `east5_stzfxxb.BBZ`, extractor 2026-08-28.13): BBZ is
produced by the CASE at L70-73

    L70: CASE WHEN a.charge_department = 'GTRF_RFN' THEN a.remark
    L71: WHEN a.TAG_PRIMARY_ACCOUNTABLE_PARTY="WSB_GTRF_CoreTrade"
             AND A.ccy_code<>B.ccy_code THEN '…'||B.ccy_code
    L73: END AS BBZ

and two COMPUTED edges carrying REAL producer value into BBZ anchored on the
WRONG lines:

  - `a.ccy_code` anchored L47 (`a.ccy_code AS bz` — the SIBLING column bz's
    birth line). Measured root: the model held ONLY ('A.ccy_code', 47) /
    ('a.ccy_code', 47) — the `_add` collapse never minted an occurrence twin
    for the L71 condition operand, because the L71 spelling (`A.ccy_code`) is
    a DIFFERENT alias spelling than the L47 keeper (`a.ccy_code`), so
    `_add`'s (name, type, context) dedup created a second var instead of a
    collapse, and family 3 had no collapsed occurrence to re-anchor.
  - `a.charge_department` anchored L51 (the stzfdxzh CASE's WHEN line). The
    model HAD the L70 twin (`bdm_acc_entrusted_payment.charge_department`,
    family 3); the edge was published from the collapsed group's KEEPER line.

THE RULE: an edge carrying the searched field's value from a producer column
anchors at the producer occurrence INSIDE the searched field's own expression
(the arm line), never at another statement line where the same producer occurs
(the collapsed group's keeper first-occurrence line).

THE LANDING (extractor 2026-08-28.14):
  - family 5 (`_register_case_producer_twins`) mints the in-span occurrence
    twin a CASE output column's own operand lacked;
  - dependency_graph Phase 9b re-points the producer edge onto that in-span
    occurrence — a RE-ANCHOR, never a new edge.

These pins read the RAW extraction graph (extractor + dependency graph, no
workspace) unless stated otherwise; the one served-closure pin asserts the
SQL-panel line set, never per-edge ids (the L2 edge ids are content-derived
and move with any endpoint change).
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import (  # noqa: E402
    EXTRACTOR_VERSION,
    ExtractionResult,
    extract_variables_from_sql,
)
from app.extractor import variable_extractor_v2 as VX  # noqa: E402
from app.extractor import dependency_graph as DG  # noqa: E402
from app.extractor.dependency_graph import (  # noqa: E402
    build_dependency_graph,
    _case_alias_spans,
)

SAMPLES = BACKEND_DIR.parent / "samples" / "sql_sample_v1"
EAST5 = SAMPLES / "EAST5_STZFXXB_M.sql"
EAST5_NAME = "EAST5_STZFXXB_M.sql"
CORPUS = ("BDM_ACC_LOAN_INFO_SUP_M.sql", "BDM_ACC_LOAN_INFO_PL.sql",
          "BDM_ACC_LOAN_INFO_Digitallending.sql", "BDM_ACC_LOAN_INFO_RFN.sql")

# BBZ's producing expression: `CASE WHEN … / WHEN … / END AS BBZ`.
BBZ_CASE_SPAN = (70, 73)
# The keeper lines rule 4e moves OFF: L47 is the sibling column bz's birth
# line, L51 is the stzfdxzh CASE's own WHEN line.
KEEPER_LINES = (47, 51)
# `charge_department`'s occurrence-twin arm set, pinned by the doc's §4a/§3
# rows (family 3's mints). Rule 4e must not move a single line of it.
CHARGE_DEPARTMENT_ARMS = {54, 55, 56, 66, 68, 70}


def _extract():
    sql = EAST5.read_text(encoding="utf-8")
    return sql, extract_variables_from_sql(sql, EAST5_NAME)


def _bbz_case(res):
    cases = [v for v in res.variables
             if v.variable_type.value == "case" and v.name == "BBZ"]
    assert len(cases) == 1, f"expected exactly one BBZ CASE var, got {cases}"
    return cases[0]


def _producer_edges(res, deps, target_name="BBZ"):
    """The COMPUTED edges INTO `target_name`, as readable tuples."""
    by_id = {v.id: v for v in res.variables}
    out = []
    for d in deps:
        if d.relationship != "COMPUTED":
            continue
        s, t = by_id.get(d.source_id), by_id.get(d.target_id)
        if s is None or t is None or t.name != target_name:
            continue
        out.append((s.name, int(s.line_start or 0), t.name,
                    int(t.line_start or 0)))
    return sorted(out)


# ═══════════════════════════════════════════════════════════════════════
# the version gate
# ═══════════════════════════════════════════════════════════════════════

def test_extractor_version_bumped_for_rule_4e():
    """Rule 4e changes EXTRACTION output (new occurrence twin + moved
    producer anchors), so version-matched caches must invalidate: .13 → .14.

    Frame statement anchor (2026-08-28.15) moved the version again — the
    frame VTs of the `INSERT INTO TABLE` statements carry their own
    statement's anchor line — so this pins PAST .13 (the pre-4e version),
    never one exact literal: every later extraction-output change must
    keep invalidating the version-matched caches."""
    assert EXTRACTOR_VERSION > "2026-08-28.13", (
        f"EXTRACTOR_VERSION is {EXTRACTOR_VERSION!r} — rule 4e (and every "
        f"later extraction-output change) must keep the version past .13")


# ═══════════════════════════════════════════════════════════════════════
# family 5 — the in-span occurrence twin
# ═══════════════════════════════════════════════════════════════════════

def test_case_condition_operand_gets_its_own_line_twin():
    """`A.ccy_code<>B.ccy_code` at L71 is a producer occurrence INSIDE BBZ's
    own expression, so the model holds a twin at that line attributed to the
    operand's own owner — not only the L47 keeper of the sibling `bz`."""
    _, res = _extract()
    twins = [v for v in res.variables
             if v.variable_type.value == "column"
             and v.name.casefold() == "bdm_acc_entrusted_payment.ccy_code"
             and v.line_start == 71]
    assert twins, (
        "no occurrence twin for the L71 ccy_code condition operand — rule 4e "
        "has no in-span anchor to publish the producer edge at")
    twin = twins[0]
    assert twin.source_tables == ["bdm_acc_entrusted_payment"], (
        f"the L71 twin is attributed to {twin.source_tables}, never a guess")
    assert not twin.is_output, "the occurrence twin is the occurrence side"
    assert (twin.defined_in or "").startswith("OCCURRENCE"), (
        f"the twin lost its OCCURRENCE stamp: {twin.defined_in!r}")


def test_in_span_twin_carries_the_case_arm_stamp():
    """The L71 operand sits in BBZ's second WHEN arm — the per-occurrence arm
    fact Phase 9 reads must be recorded under the twin's own id."""
    _, res = _extract()
    twins = [v for v in res.variables
             if v.variable_type.value == "column"
             and v.name.casefold() == "bdm_acc_entrusted_payment.ccy_code"
             and v.line_start == 71]
    assert twins, "no L71 ccy_code twin to stamp"
    assert res.occurrence_arms.get(twins[0].id) == "CASE WHEN", (
        f"arm stamp is {res.occurrence_arms.get(twins[0].id)!r}, expected "
        f"'CASE WHEN'")


def test_family5_blast_radius_is_the_one_missing_operand():
    """Rule 4e mints a twin ONLY where a CASE output column's own operand had
    no node: across the sample corpus that is exactly the EAST5 L71 ccy_code
    occurrence — every other variable the corpus already had stays put."""
    real = VX._RoleBasedExtractor._register_case_producer_twins

    def var_keys(script):
        sql = (SAMPLES / script).read_text(encoding="utf-8")
        res = extract_variables_from_sql(sql, script)
        return {(v.name, v.variable_type.value, v.context, v.line_start,
                 v.line_end, v.is_output, tuple(v.source_tables))
                for v in res.variables}

    def without_family5(script):
        sql = (SAMPLES / script).read_text(encoding="utf-8")
        VX._RoleBasedExtractor._register_case_producer_twins = \
            lambda self, innermost: None
        try:
            res = extract_variables_from_sql(sql, script)
        finally:
            VX._RoleBasedExtractor._register_case_producer_twins = real
        return {(v.name, v.variable_type.value, v.context, v.line_start,
                 v.line_end, v.is_output, tuple(v.source_tables))
                for v in res.variables}

    for script in CORPUS:
        added = var_keys(script) - without_family5(script)
        assert not added, (
            f"{script}: rule 4e minted {sorted(added)} — the pass is scoped "
            f"to a CASE output column's OWN unanchored operand, so a mint "
            f"outside EAST5's L71 ccy_code is a scope leak")
    added = var_keys(EAST5_NAME) - without_family5(EAST5_NAME)
    assert added == {("bdm_acc_entrusted_payment.ccy_code", "column", "TOP0",
                      71, 71, False, ("bdm_acc_entrusted_payment",))}, (
        f"EAST5: rule 4e minted {sorted(added)} — expected exactly the L71 "
        f"ccy_code condition operand")


def test_case_span_resolution_reads_the_end_as_alias_mapping():
    """The producing CASE is resolved through `END AS <alias>`: BBZ's alias
    line 73 closes the CASE that starts at L70. A nested CASE inside an arm
    (stzfdxhm's, L58-61) never closes the outer one."""
    sql = EAST5.read_text(encoding="utf-8")
    spans = _case_alias_spans(sql)
    assert spans.get((73, "bbz")) == 70, (
        f"BBZ's span resolved to {spans.get((73, 'bbz'))}, expected 70")
    assert spans.get((65, "stzfdxhm")) == 54, (
        f"stzfdxhm's span resolved to {spans.get((65, 'stzfdxhm'))} — the "
        f"nested CASE at L58 must not close the outer one")
    # a plain `SELECT x AS y` is not a CASE closing
    assert not any(alias == "bz" for _line, alias in spans), (
        "a non-CASE alias entered the CASE span map")


# ═══════════════════════════════════════════════════════════════════════
# Phase 9b — the re-anchor
# ═══════════════════════════════════════════════════════════════════════

def test_bbz_producer_edges_anchor_at_the_arm_lines():
    """THE rule-4e pin: the two producer edges carry real producer value into
    BBZ and anchor at the arm lines — `charge_department` at L70 (arm 1's
    condition) and `ccy_code` at L71 (arm 2's condition)."""
    sql, res = _extract()
    deps = build_dependency_graph(res, sql)
    edges = _producer_edges(res, deps)
    by_producer = {name.casefold().rsplit(".", 1)[-1]: (name, line)
                   for name, line, _t, _tl in edges}
    assert by_producer["charge_department"][1] == 70, (
        f"charge_department's producer edge anchors "
        f"L{by_producer['charge_department'][1]} "
        f"({by_producer['charge_department'][0]}) — rule 4e: the arm line is "
        f"L70, never the collapsed group's keeper line")
    assert by_producer["ccy_code"][1] == 71, (
        f"ccy_code's producer edge anchors L{by_producer['ccy_code'][1]} "
        f"({by_producer['ccy_code'][0]}) — rule 4e: the arm-2 condition line "
        f"is L71, never the sibling column bz's birth line")


def test_no_producer_edge_anchors_at_another_statement_line():
    """Every COMPUTED edge into BBZ anchors INSIDE BBZ's own producing
    expression — no producer may anchor at the keeper line it shares with a
    sibling column's flow."""
    sql, res = _extract()
    deps = build_dependency_graph(res, sql)
    lo, hi = BBZ_CASE_SPAN
    for name, line, _t, _tl in _producer_edges(res, deps):
        assert lo <= line <= hi, (
            f"{name}'s producer edge into BBZ anchors L{line}, outside the "
            f"producing expression L{lo}-L{hi}")


def test_reanchor_is_a_move_never_a_second_edge():
    """BBZ keeps exactly one producer leg per producer field — the re-anchor
    re-points Phase 3's edge, it never adds one."""
    sql, res = _extract()
    deps = build_dependency_graph(res, sql)
    edges = _producer_edges(res, deps)
    parts = sorted(name.casefold().rsplit(".", 1)[-1] for name, _l, _t, _tl
                   in edges)
    assert parts == ["ccy_code", "ccy_code", "charge_department", "remark",
                     "tag_primary_accountable_party"], (
        f"BBZ's producer legs are {parts} — one per producer field, five in "
        f"all (a.remark@70, charge_department@70, ccy_code@71 x2 owners, "
        f"TAG_PRIMARY_ACCOUNTABLE_PARTY@71)")


def test_empty_sql_text_keeps_every_anchor():
    """A graph built from a pre-extracted result without the text has no CASE
    spans to read, so no anchor may move (the rule never guesses)."""
    _, res = _extract()
    deps = build_dependency_graph(res, "")
    edges = _producer_edges(res, deps)
    by_producer = {(name.casefold(), line) for name, line, _t, _tl in edges}
    assert ("a.charge_department", 51) in by_producer and \
        ("a.ccy_code", 47) in by_producer, (
        f"without sql_text the keeper anchors must stand: "
        f"{sorted(by_producer)}")


def test_producer_without_an_in_span_occurrence_keeps_its_anchor():
    """Rule 4e re-anchors onto an occurrence that EXISTS. A producer read
    only inside its own CASE keeps that line; a CASE operand whose only
    occurrence IS the arm line anchors there natively — the pass never
    invents a line the text does not carry."""
    sql = (
        "INSERT INTO tgt_table\n"
        "SELECT a.flag AS first_flag,\n"
        "       CASE WHEN a.other = 1 THEN a.payload END AS second_col\n"
        "FROM src_table a\n"
    )
    res = extract_variables_from_sql(sql, "rule4e_no_inspan")
    deps = build_dependency_graph(res, sql)
    by_id = {v.id: v for v in res.variables}
    moved = []
    for d in deps:
        if d.relationship not in ("COMPUTED", "REF"):
            continue
        s, t = by_id.get(d.source_id), by_id.get(d.target_id)
        if t is not None and t.name == "second_col" and s is not None:
            moved.append((s.name, int(s.line_start or 0)))
    # `a.other` and `a.payload` occur ONLY inside the CASE (L3) — their edges
    # anchor there. No twin is minted for them (both lines are already taken
    # by their own vars), and no anchor is invented anywhere else.
    assert sorted(moved) == [("a.other", 3), ("a.payload", 3)], (
        f"the CASE's own operands must anchor at their arm line L3: {moved}")


def test_first_flag_producer_is_not_pulled_into_the_case():
    """The negative half of the scope rule: a producer that does not occur
    inside the producing expression is never re-anchored into it."""
    sql = (
        "INSERT INTO tgt_table\n"
        "SELECT a.flag AS first_flag,\n"
        "       CASE WHEN a.other = 1 THEN a.payload END AS second_col\n"
        "FROM src_table a\n"
    )
    res = extract_variables_from_sql(sql, "rule4e_scope")
    deps = build_dependency_graph(res, sql)
    by_id = {v.id: v for v in res.variables}
    flags = [int(by_id[d.source_id].line_start or 0) for d in deps
             if d.relationship in ("COMPUTED", "REF")
             and by_id.get(d.target_id) is not None
             and by_id[d.target_id].name == "first_flag"]
    assert flags == [2], (
        f"first_flag's producer anchors {flags} — a.line 2 is outside "
        f"second_col's CASE and must stay where it is read")


# ═══════════════════════════════════════════════════════════════════════
# the existing pins stay true
# ═══════════════════════════════════════════════════════════════════════

def test_charge_department_occurrence_arm_set_is_unchanged():
    """`charge_department`'s arm twins {54,55,56,66,68,70} are the doc's
    §4a/§3 rows — rule 4e moves anchors, it never moves a twin's line."""
    _, res = _extract()
    arms = sorted(v.line_start for v in res.variables
                  if v.variable_type.value == "column"
                  and v.name.casefold() == "bdm_acc_entrusted_payment.charge_department"
                  and v.id in res.occurrence_arms)
    assert arms == sorted(CHARGE_DEPARTMENT_ARMS), (
        f"charge_department's arm twins are {arms}, expected "
        f"{sorted(CHARGE_DEPARTMENT_ARMS)}")


def test_charge_department_stzfdxzh_edge_keeps_its_own_case_line():
    """L51 IS inside the stzfdxzh CASE (L51-53) — the keeper's own edge into
    that CASE's output is already anchored at the producer's in-span
    occurrence, so it stays (rule 4e moves nothing that is already right)."""
    sql, res = _extract()
    deps = build_dependency_graph(res, sql)
    by_id = {v.id: v for v in res.variables}
    lines = sorted(int(by_id[d.source_id].line_start or 0) for d in deps
                   if d.relationship == "COMPUTED"
                   and by_id.get(d.target_id) is not None
                   and by_id[d.target_id].name == "stzfdxzh"
                   and by_id[d.source_id].name.casefold().endswith(
                       "charge_department"))
    assert lines == [51], (
        f"stzfdxzh's charge_department legs anchor {lines} — the L51 CASE "
        f"reads the field at L51, inside its own expression")


# ═══════════════════════════════════════════════════════════════════════
# the served line set (SEGMENT's admission filter is a parallel work stream;
# pin the SQL-panel lines, never the per-edge ids)
# ═══════════════════════════════════════════════════════════════════════

def test_served_bbz_closure_lights_the_arm_lines_never_the_keeper_lines():
    """Searching BBZ highlights the producing expression's arm lines L70/L71
    and never the sibling's birth line L47 nor another CASE's WHEN line L51."""
    import contextlib
    import io
    import zipfile
    import app.services.l2_builder as LB
    from app.services.l2_builder import _build_l2_graph
    from app.services.workspace_service import create_workspace, delete_workspace

    sql = EAST5.read_text(encoding="utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(EAST5_NAME, sql)
    ws_id = create_workspace(buf.getvalue())
    try:
        result = _build_l2_graph(ws_id, EAST5_NAME, sql, "east5_stzfxxb",
                                 "BBZ", relevance_filter=True,
                                 direction="downstream")
    finally:
        delete_workspace(ws_id)
    graph = result.get("graph") if isinstance(result.get("graph"), dict) \
        else result
    lines = {int(e["data"].get("highlight_line") or 0)
             for e in graph["edges"]}
    assert {70, 71} <= lines, (
        f"BBZ's arm lines went dark: served highlights are {sorted(lines)}")
    assert not ({47, 51} & lines), (
        f"BBZ's producer edges still anchor at another statement's line: "
        f"{sorted({47, 51} & lines)} in {sorted(lines)}")
