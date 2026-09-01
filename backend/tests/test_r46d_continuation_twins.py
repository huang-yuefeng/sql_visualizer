"""R46d (EXTRACTOR_VERSION 2026-08-28.12) — continuation-twin edges.

Defect (AD3-adjudicated, FSB-measured on EAST5_STZFXXB_M): an occurrence
twin minted at the right LINE still died downstream. The display folds one
chip per (owner, field) anchored at the FIRST occurrence, and the twin
carried no edge of its own that said what its arm DOES — a CASE's 2nd..Nth
WHEN arm, a nested function body's operand and a JOIN ON's AND-continuation
leg lit only through the head's folded duplicate (the belongs-to SCHEMA and
the family-1 write leg, both anchored by the line-merged pass wherever the
first carrier put them), or not at all.

Two extraction-time facts close it, both read off the tokenizer stream the
rest of the occurrence machinery already uses:

  1. the CASE ARM of the occurrence (`_case_arm_roles` + `_arm_role_for`) —
     recorded per twin on `result.occurrence_arms` as "CASE WHEN" /
     "CASE THEN" / "CASE ELSE". A CASE arm never leaves the clause its
     statement collected it in, so the clause map says "SELECT expr" for
     BOTH a condition arm and a value operand; the arm is the finer fact,
     and it is what tells a ROW-SELECTION from a value source. It rides
     its own channel because `defined_in` is the clause stamp every
     downstream clause gate (and the display layer's write-projection
     test) reads — re-stamping it changed served closures that the arm
     fact had no business touching.
  2. family 4, the JOIN-ON AND-continuation legs (`_register_join_leg_
     twins`) — family 3's free-line handout can never serve an AND leg,
     because Fix F marks a line taken when ANY same-field-part var anchors
     it and the leg's OTHER side is exactly such a var.

dependency_graph Phase 9 turns the arm fact into the twin's own flow edge
(FILTER/ROW_SELECTION for a condition arm into the scope's output anchor)
and Phase 6b's own-clause gate already types the JOIN-ON leg twins. The
THEN/ELSE value leg is WITHHELD — its only available target is the ⟐
output anchor, which the strict walker walks backwards, so it leaked
sibling arms into unrelated seeds' closures (measured, see Phase 9). Everything is additive: no existing edge is dropped, re-typed or
re-anchored, and Phase 9 runs last so the L2 line-merge's
first-carrier-wins can never displace an existing carrier.
"""

import io
import subprocess
import sys
import zipfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import (  # noqa: E402
    EXTRACTOR_VERSION,
    _RoleBasedExtractor,
    ExtractionResult,
    extract_variables_from_sql,
)
from app.extractor.dependency_graph import (  # noqa: E402
    _OCCURRENCE_PREFIX,
    _clause_of,
    build_dependency_graph,
)
from app.models.variable import VariableDefinition, VariableType  # noqa: E402

SAMPLES = BACKEND_DIR.parent / "samples" / "sql_sample_v1"
EAST5 = SAMPLES / "EAST5_STZFXXB_M.sql"

SQL = EAST5.read_text(encoding="utf-8")


def _extract(sql: str, name: str = "R46D"):
    res = extract_variables_from_sql(sql, name)
    deps = build_dependency_graph(res, sql)
    return res, deps


def _twins(res, name: str, line: int | None = None):
    """The occurrence twins named `name` (at `line` when given)."""
    return [v for v in res.variables
            if v.name.casefold() == name.casefold()
            and (line is None or v.line_start == line)
            and (v.defined_in or "").upper().startswith(_OCCURRENCE_PREFIX)]


def _out_edges(deps, var_id: str, rel: str | None = None,
               op: str | None = None):
    out = []
    for d in deps:
        if d.source_id != var_id:
            continue
        if rel is not None and d.relationship != rel:
            continue
        if op is not None and (d.operation or "").upper() != op:
            continue
        out.append(d)
    return out


def _flow_lines(table: str, field: str):
    """The served flow-only closure's anchor lines (the FSB baseline the
    SQL panel's string-match layer colours against)."""
    from app.services.l2_builder import _build_l2_graph
    from app.services.workspace_service import create_workspace, \
        delete_workspace

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(EAST5.name, SQL)
    ws_id = create_workspace(buf.getvalue())
    try:
        res = _build_l2_graph(ws_id, EAST5.name, SQL, table, field, True)
    finally:
        delete_workspace(ws_id)
    lines = {e["data"].get("highlight_line") for e in res["edges"]}
    lines |= {n["data"].get("line_start") for n in res["nodes"]}
    return {l for l in lines if isinstance(l, int) and l >= 1}, res


# ══════════════════════════════════════════════════════════════════════
# The arm-role classifier (extraction-time fact #1)
# ══════════════════════════════════════════════════════════════════════

class TestArmRoleClassifier:
    def _roles(self, sql):
        ex = _RoleBasedExtractor(ExtractionResult(script_name="ARM"),
                                 "ARM", sql)
        return ex

    def test_condition_then_else_arms(self):
        ex = self._roles(
            "SELECT CASE WHEN a.x = 1 THEN a.y ELSE a.z END AS o FROM t a")
        assert ex._arm_role_for("a.x", 1) == "CASE WHEN"
        assert ex._arm_role_for("a.y", 1) == "CASE THEN"
        assert ex._arm_role_for("a.z", 1) == "CASE ELSE"

    def test_both_arms_on_one_line_claim_different_roles(self):
        ex = self._roles(
            "SELECT CASE WHEN a.x = 1 THEN a.x END AS o FROM t a")
        assert ex._arm_role_for("a.x", 1) == "CASE WHEN"
        assert ex._arm_role_for("a.x", 1) == "CASE THEN"
        # and a third claim finds nothing left on that line
        assert ex._arm_role_for("a.x", 1) is None

    def test_operand_inside_a_call_keeps_its_arm(self):
        """`THEN NVL(a.x, f.y)` — the call's parens are transparent, the
        operand is still a THEN arm (the nested-body class of the defect)."""
        ex = self._roles(
            "SELECT CASE WHEN a.x = 1 THEN NVL(a.y, b.z) END AS o "
            "FROM t a LEFT JOIN u b ON b.k = a.k")
        assert ex._arm_role_for("a.y", 1) == "CASE THEN"
        assert ex._arm_role_for("b.z", 1) == "CASE THEN"

    def test_nested_case_regains_the_outer_arm(self):
        ex = self._roles(
            "SELECT CASE WHEN a.x = 1 THEN REGEXP_REPLACE(CASE WHEN a.y = 2 "
            "THEN a.z ELSE a.w END, '*', '*') END AS o FROM t a")
        assert ex._arm_role_for("a.y", 1) == "CASE WHEN"
        assert ex._arm_role_for("a.z", 1) == "CASE THEN"
        assert ex._arm_role_for("a.w", 1) == "CASE ELSE"

    def test_a_string_literal_is_not_an_arm(self):
        ex = self._roles(
            "SELECT CASE WHEN a.x = 'THEN' THEN a.y END AS o FROM t a")
        assert ex._arm_role_for("a.x", 1) == "CASE WHEN"
        assert ex._arm_role_for("a.y", 1) == "CASE THEN"

    def test_no_case_no_role(self):
        ex = self._roles("SELECT a.x FROM t a WHERE a.x = 1")
        assert ex._arm_role_for("a.x", 1) is None


# ══════════════════════════════════════════════════════════════════════
# Family 1 of the defect: the CASE WHEN condition arms of EAST5
# ══════════════════════════════════════════════════════════════════════

class TestChargeDepartmentCaseArms:
    """`a.charge_department` at L54/55/56/66/68/70 — every WHEN arm of the
    four CASE expressions carries its own row-selection edge."""

    def test_every_when_arm_carries_its_own_row_selection(self):
        res, deps = _extract(SQL)
        for line in (54, 55, 56, 66, 68, 70):
            twins = _twins(res, "bdm_acc_entrusted_payment.charge_department",
                           line)
            assert len(twins) == 1, \
                f"expected the L{line} WHEN-arm twin, got {len(twins)}"
            twin = twins[0]
            assert res.occurrence_arms.get(twin.id) == "CASE WHEN", (
                f"L{line} must record its own arm, got "
                f"{res.occurrence_arms.get(twin.id)!r}")
            sel = _out_edges(deps, twin.id, "FILTER", "ROW_SELECTION")
            assert sel, f"the L{line} arm has no own row-selection edge"
            # anchored at the occurrence's own line: the payload's
            # row-selection kind reads the source line.
            assert sel[0].target_id != twin.id

    def test_then_and_else_arms_are_recorded_but_not_row_selections(self):
        """A THEN/ELSE arm projects the field into the statement's output —
        a value/birth-class anchor, never a row-selection. The arm IS
        recorded (`result.occurrence_arms`), but its own value edge is
        WITHHELD: the only consumer Phase 9 could target today is the
        scope's ⟐ output anchor, and a REF into that anchor is walked
        BACKWARDS by the strict walker, which turned every sibling arm into
        an upstream producer of unrelated seeds (measured: jaccard
        precision bdm/Digitallending-upstream 1.0 → 0.4286,
        east5-upstream 1.0 → 0.2308). Landing it needs the consuming
        OUTPUT COLUMN as the target — see the Phase 9 WITHHELD note."""
        res, deps = _extract(SQL)
        for field, line in (("entd_opp_acct_name", 59),
                            ("entd_opp_acct_name", 60),
                            ("ISSUE_DT", 102),
                            ("ISSUE_DT", 103),
                            ("TAG_PRIMARY_ACCOUNTABLE_PARTY", 108)):
            twins = _twins(res, f"bdm_acc_entrusted_payment.{field}", line) \
                or _twins(res, f"bdm_acc_loan_info.{field}", line)
            assert twins, f"no twin for {field}@L{line}"
            twin = twins[0]
            assert res.occurrence_arms.get(twin.id) in ("CASE THEN",
                                                        "CASE ELSE"), (
                f"{field}@L{line} arm not recorded, got "
                f"{res.occurrence_arms.get(twin.id)!r}")
            assert not _out_edges(deps, twin.id, "FILTER", "ROW_SELECTION"), \
                f"{field}@L{line} must not read as a row-selection"
            assert not _out_edges(deps, twin.id, "REF", "VALUE"), \
                f"{field}@L{line} gained the withheld value leg"

    def test_arm_lines_light_in_the_served_closure(self):
        lines, _ = _flow_lines("bdm_acc_entrusted_payment",
                               "charge_department")
        assert {54, 55, 56, 66, 68, 70} <= lines

    def test_arm_edges_reach_the_served_closure(self):
        """The row-selection edges are served, not just built — the strict
        walker admits the searched field's own arm (W4) and the R-GATE's
        recall guard keeps an own-occurrence anchor line."""
        from app.services.l2_builder import _build_l2_graph
        from app.services.workspace_service import create_workspace, \
            delete_workspace

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(EAST5.name, SQL)
        ws_id = create_workspace(buf.getvalue())
        try:
            res = _build_l2_graph(ws_id, EAST5.name, SQL,
                                 "bdm_acc_entrusted_payment",
                                 "charge_department", True)
        finally:
            delete_workspace(ws_id)
        by_line = {}
        for e in res["edges"]:
            d = e["data"]
            if d.get("edge_type") == "FILTER":
                by_line.setdefault(d.get("highlight_line"), []).append(d)
        for line in (54, 55, 56, 66, 68, 70):
            assert line in by_line, \
                f"the L{line} WHEN arm lost its own FILTER edge in L2"
            assert by_line[line][0].get("flow_kind") == "row flow", (
                f"the L{line} row-selection must carry the canonical "
                f"row-selection kind, got {by_line[line][0].get('flow_kind')}")


class TestTagPrimaryAccountableParty:
    """`a.TAG_PRIMARY_ACCOUNTABLE_PARTY` L98-118 — four WHEN arms and one
    THEN arm of three CASE expressions."""

    def test_arms(self):
        res, deps = _extract(SQL)
        expect = {98: "CASE WHEN", 107: "CASE WHEN", 108: "CASE THEN",
                  111: "CASE WHEN", 118: "CASE WHEN"}
        for line, arm in expect.items():
            twins = _twins(
                res, "bdm_acc_entrusted_payment.tag_primary_accountable_party",
                line)
            assert len(twins) == 1, f"expected the L{line} twin, got none"
            assert res.occurrence_arms.get(twins[0].id) == arm, (
                f"L{line} recorded "
                f"{res.occurrence_arms.get(twins[0].id)!r}, expected {arm!r}")
            if arm == "CASE WHEN":
                assert _out_edges(deps, twins[0].id, "FILTER",
                                  "ROW_SELECTION"), \
                    f"L{line} has no own row-selection edge"

    def test_lines_light(self):
        lines, _ = _flow_lines("bdm_acc_entrusted_payment",
                               "tag_primary_accountable_party")
        assert {98, 107, 108, 111, 118} <= lines


class TestNestedFunctionBody:
    """`a.entd_opp_acct_name` L58-64 — the CASE inside REGEXP_REPLACE."""

    def test_nested_body_arms(self):
        res, deps = _extract(SQL)
        expect = {58: "CASE WHEN", 59: "CASE THEN", 60: "CASE ELSE",
                  64: "CASE ELSE"}
        for line, arm in expect.items():
            twins = _twins(res,
                           "bdm_acc_entrusted_payment.entd_opp_acct_name",
                           line)
            assert len(twins) == 1, f"expected the L{line} twin, got none"
            assert res.occurrence_arms.get(twins[0].id) == arm, (
                f"L{line} recorded "
                f"{res.occurrence_arms.get(twins[0].id)!r}, expected {arm!r}")

    def test_lines_light(self):
        lines, _ = _flow_lines("bdm_acc_entrusted_payment",
                               "entd_opp_acct_name")
        assert {54, 55, 58, 59, 60, 64} <= lines


class TestIssueDt:
    """`B.ISSUE_DT` — L102 (THEN) / L103 (ELSE) inside the RESERVED_7 CASE."""

    def test_arms(self):
        res, deps = _extract(SQL)
        expect = {102: "CASE THEN", 103: "CASE ELSE"}
        for line, arm in expect.items():
            twins = _twins(res, "bdm_acc_loan_info.issue_dt", line)
            assert len(twins) == 1, f"expected the L{line} twin, got none"
            assert res.occurrence_arms.get(twins[0].id) == arm

    def test_lines_light(self):
        lines, _ = _flow_lines("bdm_acc_loan_info", "issue_dt")
        assert {100, 102, 103} <= lines


# ══════════════════════════════════════════════════════════════════════
# Family 4: the JOIN ON AND-continuation legs
# ══════════════════════════════════════════════════════════════════════

class TestJoinOnAndLegs:
    """`AND b.lending_ref = a.lending_ref` @144 / `AND b.org_no = c.org_no`
    @147 — family 3 covers the head ON line, the AND legs get their own
    twin (the other side's var had taken the line)."""

    def test_and_leg_twins_carry_join_edges(self):
        res, deps = _extract(SQL)
        for owner, field, line in (("bdm_acc_loan_info", "lending_ref", 144),
                                   ("bdm_acc_loan_info", "org_no", 147)):
            twins = _twins(res, f"{owner}.{field}", line)
            assert len(twins) == 1, \
                f"expected the {owner}.{field} L{line} AND-leg twin"
            assert twins[0].defined_in.upper().endswith("JOIN ON")
            joins = _out_edges(deps, twins[0].id, "JOIN", "JOIN_CONDITION")
            assert joins, f"the L{line} AND-leg twin has no own JOIN edge"

    def test_leg_lines_light(self):
        for table, field, line in (("bdm_acc_loan_info", "lending_ref", 144),
                                   ("bdm_acc_loan_info", "org_no", 147)):
            lines, _ = _flow_lines(table, field)
            assert line in lines, \
                f"{table}.{field}: the L{line} AND leg is dark"

    def test_no_twin_without_owner_evidence(self):
        """A leg token that no surviving var spells exactly never mints —
        the last-dot-part fallback would attribute `d.org_no` to whichever
        same-named field the walker met first."""
        res, _ = _extract(SQL)
        anchored = {v.name.casefold() for v in res.variables
                    if v.variable_type == VariableType.COLUMN
                    and v.line_start == 150}
        # `d.org_no` / `c.parent_vir_no` are real vars at L150; family 4
        # must not have duplicated them with a second twin of the same
        # owner.field on that line.
        for name in ("d.org_no", "c.parent_vir_no"):
            assert name in anchored, f"{name} should already anchor L150"
        twins = [v for v in res.variables
                 if v.line_start == 150
                 and (v.defined_in or "").upper().startswith(
                     _OCCURRENCE_PREFIX)]
        assert not twins, (
            f"L150 minted {[(t.name, t.defined_in) for t in twins]} — "
            "family 4 duplicated an occurrence a surviving var anchors")

    def test_table_alias_never_mints(self):
        """A leg whose tokens name a TABLE alias (`LEFT JOIN u b`) has no
        column var to inherit an owner from — nothing is minted."""
        sql = ("SELECT a.x FROM t a LEFT JOIN u b ON b.k = a.k "
               "AND b.k = a.x")
        res, deps = _extract(sql, "ALIASLEG")
        for v in res.variables:
            if not (v.defined_in or "").upper().startswith(_OCCURRENCE_PREFIX):
                continue
            # the only legitimate leg twins are the b.k / a.x occurrences
            assert v.name.split(".")[-1].casefold() in {"k", "x"}, (
                f"family 4 minted {v.name}@L{v.line_start} from a leg token "
                "that is not a field occurrence")


# ══════════════════════════════════════════════════════════════════════
# No over-lighting
# ══════════════════════════════════════════════════════════════════════

class TestNoOverLighting:
    def test_lines_that_never_mention_the_field_stay_dark(self):
        """Charge_department never occurs on these lines (code or comment)
        — neither the arm edges nor anything else may light them."""
        lines, _ = _flow_lines("bdm_acc_entrusted_payment",
                               "charge_department")
        for dark in (44, 45, 48, 49, 74, 76, 87, 91, 99, 180, 185, 186, 188):
            assert "charge_department" not in \
                SQL.split("\n")[dark - 1].casefold(), \
                f"L{dark} mentions the field — pick another dark line"
            assert dark not in lines, \
                f"L{dark} never mentions charge_department but is lit"

    def test_new_operations_only_where_the_arms_are(self):
        """Phase 9 emits exactly two operations; a field with no CASE arm
        and no AND leg gains neither."""
        for table, field in (("east5_stzfxxb", "reserved_7"),
                             ("bdm_acc_loan_info", "dis_bank_id")):
            _, res = _flow_lines(table, field)
            for e in res["edges"]:
                d = e["data"]
                if d.get("edge_type") in ("FILTER", "REF") and \
                        (d.get("_op") or "").upper() in ("ROW_SELECTION",
                                                         "VALUE"):
                    assert False, (
                        f"{table}.{field} gained a {d.get('edge_type')}/"
                        f"{(d.get('_op') or '').upper()} edge at L"
                        f"{d.get('highlight_line')} with no arm to explain it")

    def test_arm_twins_keep_their_structural_edge(self):
        """Additive: the belongs-to SCHEMA edge (Phase 4d-gb) survives —
        the arm edge is a second story, never a replacement."""
        res, deps = _extract(SQL)
        twins = _twins(res, "bdm_acc_entrusted_payment.charge_department")
        assert twins
        for twin in twins:
            assert any(d.relationship == "SCHEMA"
                       and twin.id in (d.source_id, d.target_id)
                       for d in deps), \
                f"{twin.name}@L{twin.line_start} lost its belongs-to edge"


# ══════════════════════════════════════════════════════════════════════
# Phase 9's own guard (synthetic, no SQL corpus needed)
# ══════════════════════════════════════════════════════════════════════

class TestPhaseNineAdmission:
    @staticmethod
    def _result(arm=None):
        """One table, one ⟐ output anchor and one occurrence twin."""

        def twin(var_id):
            v = VariableDefinition(
                id=var_id, name="ods_a.data_dt",
                variable_type=VariableType.COLUMN,
                defined_in="OCCURRENCE SELECT expr", context="TOP0",
                source_tables=["ods_a"], line_start=10, line_end=10,
                is_output=False)
            return v

        res = ExtractionResult(script_name="P9", variables=[
            VariableDefinition(id="ods_a", name="ods_a",
                               variable_type=VariableType.TABLE,
                               defined_in="FROM", context="TOP0",
                               line_start=2, line_end=2),
            VariableDefinition(id="out0", name="⟐ output",
                               variable_type=VariableType.VIRTUAL_TABLE,
                               defined_in="TOP0", context="TOP0",
                               line_start=1, line_end=1),
            twin("t1"),
        ])
        if arm:
            res.occurrence_arms["t1"] = arm
        return res

    def test_case_when_twin_gains_the_row_selection(self):
        res = self._result("CASE WHEN")
        deps = build_dependency_graph(res, "")
        assert any(d.source_id == "t1" and d.relationship == "FILTER"
                   and (d.operation or "").upper() == "ROW_SELECTION"
                   for d in deps)

    def test_case_then_twin_gains_no_edge_yet(self):
        """The THEN/ELSE value leg is WITHHELD (see Phase 9): the arm is
        recorded so landing it stays a Phase-9-local change."""
        res = self._result("CASE THEN")
        deps = build_dependency_graph(res, "")
        assert res.occurrence_arms.get("t1") == "CASE THEN"
        assert not any(d.source_id == "t1"
                       and (d.operation or "").upper() in ("VALUE",
                                                           "ROW_SELECTION")
                       for d in deps)

    def test_non_arm_twin_gains_nothing(self):
        res = self._result(None)
        deps = build_dependency_graph(res, "")
        assert not any(d.source_id == "t1"
                       and (d.operation or "").upper() in ("ROW_SELECTION",
                                                           "VALUE")
                       for d in deps)

    def test_no_second_story_for_a_twin_with_its_own_flow(self):
        """A twin that already carries an outgoing flow edge keeps exactly
        that story — Phase 9 never adds a second one (corpus pin of the
        guard: an arm edge's source has no other own flow edge)."""
        own_flow = {"FILTER", "JOIN", "REF", "COMPUTED", "TRANSFORM",
                    "AGGREGATE", "WINDOW", "INDIRECT"}
        res, deps = _extract(SQL)
        for d in deps:
            if (d.operation or "").upper() not in ("ROW_SELECTION", "VALUE"):
                continue
            others = [x for x in deps
                      if x.source_id == d.source_id
                      and x.relationship in own_flow
                      and (x.operation or "").upper() != "READ"]
            assert len(others) == 1, (
                f"{d.operation} from {d.source_id} sits next to "
                f"{[(x.relationship, x.operation) for x in others]} — "
                "a twin got a second story")


# ══════════════════════════════════════════════════════════════════════
# Version + determinism
# ══════════════════════════════════════════════════════════════════════

class TestDeterminism:
    def test_extractor_version_bumped(self):
        assert EXTRACTOR_VERSION > "2026-08-28.11", (
            "the continuation-twin semantics must invalidate the analysis "
            "caches: EXTRACTOR_VERSION has to move past 2026-08-28.11")

    def test_twin_edge_set_identical_across_two_processes(self):
        probe = (
            "import sys, json; sys.path.insert(0, %r)\n"
            "from pathlib import Path\n"
            "from app.extractor.variable_extractor_v2 import "
            "extract_variables_from_sql\n"
            "from app.extractor.dependency_graph import build_dependency_graph,"
            " _OCCURRENCE_PREFIX\n"
            "sql = Path(%r).read_text(encoding='utf-8')\n"
            "res = extract_variables_from_sql(sql, 'EAST5')\n"
            "deps = build_dependency_graph(res, sql)\n"
            "byid = {v.id: v for v in res.variables}\n"
            "rows = []\n"
            "for d in deps:\n"
            "    s, t = byid.get(d.source_id), byid.get(d.target_id)\n"
            "    if not s or not t: continue\n"
            "    if not (s.defined_in or '').upper().startswith("
            "_OCCURRENCE_PREFIX): continue\n"
            "    rows.append([s.name, s.line_start, t.name, t.line_start,"
            " d.relationship, (d.operation or '').upper()])\n"
            "print(json.dumps(sorted(rows)))\n" % (str(BACKEND_DIR),
                                                   str(EAST5))
        )
        runs = []
        for _ in range(2):
            out = subprocess.run(
                [sys.executable, "-c", probe],
                capture_output=True, text=True, check=True,
                env={"PYTHONHASHSEED": "random", "PATH": "/usr/bin:/bin",
                     "PYTHONPATH": str(BACKEND_DIR)}).stdout
            runs.append(out)
        assert runs[0] == runs[1], (
            "the occurrence-twin edge set is hash-order-shaped: two fresh "
            "processes disagree")
        assert len(set(runs[0])) > 20, "suspiciously few twin edges compared"
