"""I1 (v3.3.145): alias/CTE definition-line resolution — regression pin.

The sample (tools/HIGHLIGHT_REVIEW_SAMPLE.sql) is the v3.3.144 highlight
review fixture: definition sites are keyword-anchored token runs resolved
in the extraction walk (CTE name AS (, the alias identifier after FROM/
JOIN/)', DML targets), so repeated table names can never steal a line
(the old occurrence text search landed a(mid) on 20 and a(main) on 20).

Expected lines in the sample:
  def:  src_x@13 (CTE)   mid@18 (CTE)   a(mid)@22   b@26 (derived)   a(main)@33
  read: ods_a@15  ods_b@25  a.id@20  b.val@21  b.id@27 (ON)  a.dt@28
        a.id@31  a.amt@32

Note: the ON clause's `a.id` (L27) dedups into the same-context var
`a.id` first read at L20 (one node per (name, type, context), v3.3.140
statement-anchored lines) — the ON pair is pinned by `b.id@27`.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.models.variable import VariableType

# Canonical copy of tools/HIGHLIGHT_REVIEW_SAMPLE.sql (the container does
# not mount tools/, so the text is embedded; the disk copy is preferred
# when present to keep the two from drifting).
_EMBEDDED_SQL = """-- ============================================================
-- HIGHLIGHT SOLUTIONS REVIEW SAMPLE (2026-08-07)
-- definition lines in THIS file:
--   CTE src_x def L13        CTE mid def L18
--   ods_a read L15           ods_b read L25
--   implicit alias a (mid)  def L22   (FROM src_x a)
--   derived alias  b        def L26   () b)
--   implicit alias a (main) def L33   (FROM mid a)
--   qualified reads: a.id L20, b.val L21, a.id L27 (ON), a.dt L28,
--                    a.id L31, a.amt L32
-- ============================================================
INSERT OVERWRITE TABLE tgt_loan PARTITION(dt='$(load_date)')
WITH src_x AS (
    SELECT id, amt
    FROM ods_a
    WHERE dt = '$(load_date)'
)
,mid AS (
    SELECT
        a.id
        ,b.val
    FROM src_x a
    LEFT JOIN (
        SELECT id, val
        FROM ods_b
    ) b
    ON a.id = b.id
    WHERE a.dt = '$(load_date)'
)
SELECT
    a.id
    ,a.amt
FROM mid a
;
"""


def _sample_sql() -> str:
    sample = REPO_ROOT / "tools" / "HIGHLIGHT_REVIEW_SAMPLE.sql"
    if sample.exists():
        return sample.read_text()
    return _EMBEDDED_SQL


def _find(result, name, var_type, context):
    hits = [v for v in result.variables
            if v.name == name and v.variable_type == var_type
            and v.context == context]
    assert hits, f"no {var_type.value} var named {name!r} in ctx {context!r}: " \
                 f"{[(v.name, v.context) for v in result.variables]}"
    return hits[0]


def test_i1_definition_lines():
    """Aliases and CTEs resolve to their DEFINITION lines — the alias
    identifier after FROM/JOIN/')', the CTE name token at its AS — never
    a first-occurrence text match (a(mid)@22, b@26, a(main)@33)."""
    r = extract_variables_from_sql(_sample_sql(), "HIGHLIGHT_REVIEW_SAMPLE.sql")
    assert r.parse_errors == [], r.parse_errors
    assert _find(r, "src_x", VariableType.CTE, "TOP0").line_start == 13
    assert _find(r, "mid", VariableType.CTE, "TOP0").line_start == 18
    # implicit alias a (FROM src_x a, L22) — source table carried too
    a_mid = _find(r, "a", VariableType.TABLE, "CTE{mid}")
    assert a_mid.line_start == 22 and a_mid.source_tables == ["src_x"], a_mid
    # derived alias b () b), L26)
    assert _find(r, "b", VariableType.SUBQUERY,
                 "CTE{mid}:join:b").line_start == 26
    # implicit alias a (FROM mid a, L33 — the main statement)
    a_main = _find(r, "a", VariableType.TABLE, "TOP0")
    assert a_main.line_start == 33 and a_main.source_tables == ["mid"], a_main


def test_i1_read_lines():
    """Column reads resolve to their own occurrence lines — a.id@20,
    b.val@21, the ON pair b.id@27, a.dt@28, and the main statement's
    a.id@31/a.amt@32 (never the first-use lines of an earlier statement)."""
    r = extract_variables_from_sql(_sample_sql(), "HIGHLIGHT_REVIEW_SAMPLE.sql")
    assert _find(r, "ods_a", VariableType.TABLE, "CTE{src_x}").line_start == 15
    assert _find(r, "ods_b", VariableType.TABLE,
                 "CTE{mid}:join:b").line_start == 25
    # qualified reads inside the mid CTE body
    assert _find(r, "a.id", VariableType.COLUMN, "CTE{mid}").line_start == 20
    assert _find(r, "b.val", VariableType.COLUMN, "CTE{mid}").line_start == 21
    assert _find(r, "b.id", VariableType.COLUMN, "CTE{mid}").line_start == 27
    assert _find(r, "a.dt", VariableType.COLUMN, "CTE{mid}").line_start == 28
    # the main statement's reads (a.id@27's ON twin dedups into a.id@20 —
    # same (name, type, context) var, v3.3.140 statement-anchored lines)
    assert _find(r, "a.id", VariableType.COLUMN, "TOP0").line_start == 31
    assert _find(r, "a.amt", VariableType.COLUMN, "TOP0").line_start == 32
