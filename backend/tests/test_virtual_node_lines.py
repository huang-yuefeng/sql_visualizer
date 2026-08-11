"""Item A (v3.3.144 audit, item 1): ⟐ virtual-node clickability.

The audit flagged that ⟐ nodes used to carry line 0 (synthetic names,
never in highlights). v3.3.140/I1 (statement-anchored lines from the
pre-tokenized stream) plus E5 (the line<1 fallback in _walk_select /
_walk_update — a ⟐ VT whose def-site resolution came up empty lands on
its own statement's SELECT/UPDATE keyword line) closed the item. These
tests PIN the closure:

- statement-level ⟐ output VTs carry their statement's keyword line
  (flagship: INSERT OVERWRITE@160 / INSERT INTO@211 — baked into the
  ground-truth doc; MERGE@5 for 06_merge_update.sql);
- subquery/derived ⟐ containers carry their body's first-token line;
- E5 fallback: a render-canonicalized statement (SUBSTR→SUBSTRING in
  the rendered head) can never match its def-site run — without the
  fallback the VT would be line 0; it must land on the SELECT line;
- the UPDATE ⟐ VT falls back to the UPDATE keyword line the same way.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.models.variable import VariableType

SAMPLES_DIR = REPO_ROOT / "samples"


def _vts(res, name=None, ctx=None):
    out = []
    for v in res.variables:
        if v.variable_type != VariableType.VIRTUAL_TABLE:
            continue
        if name is not None and v.name != name:
            continue
        if ctx is not None and v.context != ctx:
            continue
        out.append(v)
    return out


def test_flagship_output_vts_carry_statement_anchor_lines():
    """⟐ output VTs land on their DML statement's keyword line (I1 anchors)."""
    path = SAMPLES_DIR / "sql_sample_v1" / "BDM_ACC_LOAN_INFO_SUP_M.sql"
    sql = path.read_text(encoding="utf-8")
    res = extract_variables_from_sql(sql, path.name)
    out0 = _vts(res, name="⟐ output", ctx="TOP0")
    out1 = _vts(res, name="⟐ output", ctx="TOP1")
    assert out0 and out0[0].line_start == 160, \
        f"TOP0 ⟐ output must land on INSERT OVERWRITE@160: {out0}"
    assert out1 and out1[0].line_start == 211, \
        f"TOP1 ⟐ output must land on INSERT INTO@211: {out1}"


def test_flagship_no_virtual_node_at_line_zero():
    """Every ⟐ node in the flagship carries a valid highlight line."""
    path = SAMPLES_DIR / "sql_sample_v1" / "BDM_ACC_LOAN_INFO_SUP_M.sql"
    sql = path.read_text(encoding="utf-8")
    res = extract_variables_from_sql(sql, path.name)
    vts = _vts(res)
    assert vts, "flagship must produce ⟐ VTs"
    zero = [v for v in vts if v.line_start < 1]
    assert not zero, f"⟐ VTs at line 0: {zero}"
    # subquery/derived containers carry their body's first-token line
    subq1 = _vts(res, name="⟐ subq1", ctx="CTE{rollover_loan_info}/subq1")
    assert subq1 and subq1[0].line_start == 22, subq1


def test_merge_output_vt_carries_merge_keyword_line():
    path = SAMPLES_DIR / "mock_sql_test" / "06_merge_update.sql"
    sql = path.read_text(encoding="utf-8")
    res = extract_variables_from_sql(sql, path.name)
    out = _vts(res, name="⟐ output", ctx="TOP0")
    assert out and out[0].line_start == 5, \
        f"MERGE ⟐ output must land on the MERGE keyword line: {out}"


def test_e5_fallback_canonicalized_head_lands_on_select_line():
    """SUBSTR renders as SUBSTRING — the def-site head run can never match
    the source stream, so the ⟐ VT would be line 0 without the E5
    fallback. It must land on its statement's SELECT keyword line."""
    sql = """SELECT SUBSTR(name, 1, 5) AS short_name,
       id
FROM accounts a
WHERE a.id > 10"""
    res = extract_variables_from_sql(sql, "substr_canonical.sql")
    out = _vts(res, name="⟐ output", ctx="TOP0")
    assert out and out[0].line_start == 1, \
        f"canonicalized-head ⟐ output must land on SELECT@1: {out}"


def test_e5_fallback_update_vt_lands_on_update_keyword_line():
    """Same fallback for the UPDATE walker — the ⟐ VT lands on the
    statement's own UPDATE keyword line (never line 0)."""
    sql = """UPDATE tgt t
SET t.amt = t.amt * 1.1
WHERE t.id IN (SELECT id FROM src)"""
    res = extract_variables_from_sql(sql, "update_fallback.sql")
    out = _vts(res, name="⟐ output", ctx="TOP0")
    assert out and out[0].line_start == 1, \
        f"UPDATE ⟐ output must land on UPDATE@1: {out}"
