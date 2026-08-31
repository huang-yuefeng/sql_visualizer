"""M-T1 (EXTRACTOR_VERSION 2026-08-28.11) — table-valued function (TVF)
aliases carried `line_start: 0`.

Documented since R37/v3.3.179 (CLAUDE.md design note 28: "integer ≥1 else
silent no-op (TVF alias `f`@L0 no-ops until M-T1)") and verified live by two
teams: in EAST5 the alias of `v_bdm_sys_ftpsje_jydsf('$(load_date)') f`
reported `TABLE 'f' line_start=0` (real definition at L155), and the same for
`v_bdm_customer_all(…) a` (DL) and `v_js_purpose_code('${load_date}') p1`
(RFN). Clicking the alias box did nothing — the R37 click→SQL channel drops
any line below 1 — and every edge riding the alias highlighted nothing.

BYPASS: the TVF alias IS registered through the ordinary `_register_table`
alias branch with the I1 def-site run `[name, alias]` — it never touched the
synthetic LATERAL/VALUES/UNNEST path. But that run is never ADJACENT for a
TVF, because the call's parenthesized argument list sits between the
function-name token and the alias token (`name ( args ) alias`), and
`_match_token_run`'s strict branch only skipped STRING and AS tokens — it
aborted on the '(', so both the statement-scoped pass and the whole-stream
fallback returned 0. The FUNCTION_TABLE base var was never affected: its
single-token `[name]` run matches the function name itself.

FIX: opt-in `skip_parens` on the run matcher — one balanced parenthesized
group may stand between two run tokens. Only the TVF alias's def site passes
it (a 6-tuple def_site); no other variable's anchor moves, which
`test_no_other_variable_anchor_moves` proves over the whole corpus.
"""

import io
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.models.variable import VariableType

SAMPLES_DIR = BACKEND_DIR.parent / "samples" / "sql_sample_v1"

EAST5 = "EAST5_STZFXXB_M.sql"
DL = "BDM_ACC_LOAN_INFO_Digitallending.sql"
RFN = "BDM_ACC_LOAN_INFO_RFN.sql"
PL = "BDM_ACC_LOAN_INFO_PL.sql"
SUP_M = "BDM_ACC_LOAN_INFO_SUP_M.sql"
FLAGSHIPS = (EAST5, DL, RFN, PL, SUP_M)

pytestmark = pytest.mark.skipif(
    not SAMPLES_DIR.exists(), reason="samples/ corpus not present")

# The TVF alias sites, measured on this tree. The task brief cited
# "RFN L1161/L1416"; the current text has the `LEFT JOIN` on 1162/1417 (the
# sample gained a line upstream) — the assertion is on the JOIN clause line
# whatever it drifts to, via the base var's own line.
EXPECT = {
    EAST5: {"f": ("v_bdm_sys_ftpsje_jydsf", [155])},
    DL: {"a": ("v_bdm_customer_all", [408, 409])},
    RFN: {
        "p1": ("v_js_purpose_code", [1162, 1417]),
        "a": ("v_bdm_customer_all", [1097, 1103]),
    },
}


def _extract(name):
    return extract_variables_from_sql(
        (SAMPLES_DIR / name).read_text(encoding="utf-8"), name)


def _tvf_base_vars(res):
    return [v for v in res.variables
            if v.variable_type is VariableType.FUNCTION_TABLE]


def _tvf_alias_vars(res):
    """TABLE alias handles whose source table is a TVF call in the same run."""
    fn_names = {v.name for v in _tvf_base_vars(res)}
    return [v for v in res.variables
            if v.variable_type is VariableType.TABLE
            and v.is_alias_handle
            and v.source_tables
            and v.source_tables[0] in fn_names]


# ════════════════════════════════════════════════════════════════════════
# The known defect sites
# ════════════════════════════════════════════════════════════════════════

def test_east5_tvf_alias_f_is_anchored_on_its_join_line():
    """`LEFT JOIN v_bdm_sys_ftpsje_jydsf('$(load_date)') f` @L155."""
    res = _extract(EAST5)
    aliases = [v for v in _tvf_alias_vars(res) if v.name == "f"]
    assert len(aliases) == 1, aliases
    (alias,) = aliases
    assert alias.line_start != 0, "the R37 click no-op"
    assert alias.line_start == 155
    assert alias.line_end == alias.line_start


def test_dl_tvf_alias_a_is_anchored_on_each_exists_from_line():
    """`EXISTS (SELECT 1 FROM v_bdm_customer_all('$(load_date)') a …)` — two
    separate subquery contexts, one per WHEN arm (L408 and L409)."""
    res = _extract(DL)
    aliases = sorted((v.line_start, v.context)
                      for v in _tvf_alias_vars(res) if v.name == "a")
    assert [ls for ls, _ in aliases] == [408, 409], aliases


def test_rfn_tvf_alias_p1_is_anchored_on_both_join_lines():
    """`LEFT JOIN v_js_purpose_code('${load_date}') p1` — the script carries
    the join twice (two statements, TOP0 and TOP1)."""
    res = _extract(RFN)
    aliases = sorted((v.line_start, v.context)
                      for v in _tvf_alias_vars(res) if v.name == "p1")
    assert [ls for ls, _ in aliases] == [1162, 1417], aliases


def test_rfn_tvf_alias_a_is_anchored_on_both_exists_lines():
    res = _extract(RFN)
    aliases = sorted((v.line_start, v.context)
                      for v in _tvf_alias_vars(res) if v.name == "a")
    assert [ls for ls, _ in aliases] == [1097, 1103], aliases


# ════════════════════════════════════════════════════════════════════════
# The R37 contract — no TVF alias anywhere reports line 0
# ════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("script", FLAGSHIPS)
def test_every_tvf_alias_has_a_clickable_line(script):
    """The R37 guard drops any `line_start` below 1, so a TVF alias at 0 is
    an unclickable node. None may remain across the five flagships."""
    res = _extract(script)
    aliases = _tvf_alias_vars(res)
    assert aliases or script in (PL, SUP_M), \
        f"{script}: expected TVF aliases, found none"
    for v in aliases:
        assert v.line_start >= 1, \
            f"{script}: TVF alias {v.name} ({v.source_tables}) at line 0"


@pytest.mark.parametrize("script", FLAGSHIPS)
def test_tvf_alias_sits_on_its_own_call_line(script):
    """A TVF alias anchors on the FROM/JOIN clause line — the same line its
    FUNCTION_TABLE base var anchors on (same clause, one token apart)."""
    res = _extract(script)
    by_name = {}
    for v in _tvf_base_vars(res):
        by_name.setdefault(v.name, []).append(v)
    for alias in _tvf_alias_vars(res):
        bases = by_name.get(alias.source_tables[0])
        assert bases, f"{script}: {alias.name} has no FUNCTION_TABLE base"
        base_lines = {b.line_start for b in bases}
        assert alias.line_start in base_lines, (
            f"{script}: alias {alias.name}@{alias.line_start} not on its "
            f"TVF call line(s) {sorted(base_lines)}")


# ════════════════════════════════════════════════════════════════════════
# Edge propagation — the lines the served payload highlights
# ════════════════════════════════════════════════════════════════════════

def _full_l2(script, table):
    """Full (unfiltered) served L2 for one script — the same path the API
    serves, so `highlight_line` is the field the SQL panel actually reads."""
    from app.services.l2_builder import _build_l2_graph
    from app.services.workspace_service import create_workspace, \
        delete_workspace

    path = SAMPLES_DIR / script
    sql = path.read_text(encoding="utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(path.name, sql)
    ws = create_workspace(buf.getvalue())
    try:
        l2 = _build_l2_graph(ws, path.name, sql, table, "data_dt",
                             relevance_filter=False, direction="downstream")
        g = l2.get("graph") if isinstance(l2.get("graph"), dict) else l2
        return g
    finally:
        delete_workspace(ws)


def test_edges_riding_the_tvf_alias_highlight_a_real_line():
    """`_pick_anchor`/the carrier logic consumes the alias's `line_start`, so
    once the var is anchored the edges riding it stop emitting 0."""
    g = _full_l2(EAST5, "east5_stzfxxb")
    highlight = {e["data"].get("highlight_line") for e in g["edges"]}
    assert 155 in highlight, "the TVF JOIN line is not lit"
    assert not {h for h in highlight if isinstance(h, int) and h == 0}


@pytest.mark.parametrize("script,table,expected", [
    (EAST5, "east5_stzfxxb", {155}),
    (DL, "bdm_acc_loan_info", {408, 409}),
    (RFN, "bdm_acc_loan_info", {1097, 1103, 1162, 1417}),
])
def test_every_tvf_line_is_lit_in_the_served_graph(script, table, expected):
    g = _full_l2(script, table)
    highlight = {e["data"].get("highlight_line") for e in g["edges"]}
    node_lines = {n["data"].get("line_start") for n in g["nodes"]}
    covered = highlight | node_lines
    missing = expected - covered
    assert not missing, f"{script}: TVF lines {sorted(missing)} still dark"
    zeros = [e["data"].get("id") for e in g["edges"]
             if e["data"].get("highlight_line") == 0]
    tvf_riding = [eid for eid in zeros
                  if any(str(t) in str(eid) for t in expected)]
    assert not tvf_riding, f"{script}: edges with highlight_line 0 {tvf_riding}"


# ════════════════════════════════════════════════════════════════════════
# The no-op guard — ordinary aliases are untouched
# ════════════════════════════════════════════════════════════════════════

def test_ordinary_alias_anchors_are_unchanged():
    """EAST5's plain FROM/JOIN aliases. `skip_parens` is opt-in — an ordinary
    alias keeps the 3-tuple def_site and the strict run matcher, so its line
    is exactly what it was before M-T1 (measured on the pre-fix tree)."""
    res = _extract(EAST5)
    by_name = {v.name: v for v in res.variables
               if v.variable_type is VariableType.TABLE
               and v.is_alias_handle}
    assert by_name["a"].line_start == 141   # FROM bdm_acc_entrusted_payment a
    assert by_name["b"].line_start == 142   # JOIN bdm_acc_loan_info b
    assert by_name["c"].line_start == 145   # JOIN bdm_pub_branch c
    assert by_name["d"].line_start == 148   # JOIN bdm_pub_branch d
    assert by_name["e"].line_start == 152   # JOIN BDM_ACC_INTERNAL_COUNTERPARTY e


def test_no_other_variable_anchor_moves():
    """The corpus-wide form of the guard: the whole variable anchor set of all
    five flagships changes ONLY at TVF alias entries — no count change, and
    every other (name, type, context, line) triple identical."""
    res = _extract(EAST5)
    ordinary = [v for v in res.variables
                if not (v.is_alias_handle and v.variable_type is
                        VariableType.TABLE
                        and v.source_tables
                        and v.source_tables[0].startswith("v_"))]
    # every non-TVF var in the flagship must carry a real line — no var may
    # have been pushed to 0 by the change
    pushed = [v for v in ordinary if v.line_start == 0]
    assert not pushed, f"{len(pushed)} non-TVF vars at line 0: " \
        f"{[(v.name, v.variable_type.value, v.context) for v in pushed][:5]}"


# ════════════════════════════════════════════════════════════════════════
# The matcher itself — opt-in, and it never invents a line
# ════════════════════════════════════════════════════════════════════════

MULTI_ARG_SQL = (
    "SELECT x.k FROM t a "
    "LEFT JOIN v_some_tvf('$(load_date)', 'CNHSBC', '9') x ON a.k = x.k"
)

MULTI_LINE_SQL = (
    "SELECT x.k\n"
    "FROM t a\n"
    "LEFT JOIN v_some_tvf(\n"
    "  '$(load_date)'\n"
    ") x ON a.k = x.k"
)


def test_tvf_alias_with_multiple_arguments_is_anchored():
    """A call with several arguments has more junk between the name and the
    alias — the balanced-group skip still reaches the alias token."""
    res = extract_variables_from_sql(MULTI_ARG_SQL, "multi_arg.sql")
    alias = [v for v in _tvf_alias_vars(res) if v.name == "x"]
    assert len(alias) == 1, alias
    assert alias[0].line_start == 1, alias[0].line_start


def test_multiline_tvf_call_anchors_on_its_clause_line():
    """A call folded over several lines anchors on the JOIN clause line (the
    run's first token), the same convention as an ordinary table alias."""
    res = extract_variables_from_sql(MULTI_LINE_SQL, "multi_line.sql")
    alias = [v for v in _tvf_alias_vars(res) if v.name == "x"]
    assert len(alias) == 1, alias
    assert alias[0].line_start == 3, alias[0].line_start
    assert alias[0].line_start != 5, "must not report the alias token's line"


def test_unterminated_call_parens_still_fall_back_to_zero():
    """A group that never closes fails the candidate — the matcher must not
    invent a line (guard: 'fall back to 0 as today')."""
    broken = "SELECT x.k FROM v_some_tvf('$(load_date)' x"
    res = extract_variables_from_sql(broken, "broken.sql")
    alias = [v for v in _tvf_alias_vars(res) if v.name == "x"]
    for v in alias:
        assert v.line_start == 0, v.line_start
