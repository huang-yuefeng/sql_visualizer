"""Cross-statement instance fold ownership (fix team J2, 2026-09-01).

Canonical adjudication point 23 (jaccard_canonical.py) names three served
defects of one family — a field occurrence rendered on an instance of a
table that does not own it:

  (A) sup↓SUP_M, one edge: a SECOND Table→Column ownership edge at L202
      whose carrier source was `bdm_acc_loan_info_sup@L223` — the NEXT
      statement's instance of the same table (the job-log INSERT@211-225),
      duplicating the ownership fact S5 already renders at the qualifying
      alias instance p2@199. IID18/LFS110 ("one ownership fact per line,
      rendered at the qualifying alias instance") + the §8.5
      endpoint-duplicate collapse both refuse the second row.
  (B) pl↓PL, two edges riding a FOREIGN same-name chip at L250
      (`SCHEMA bdm_acc_loan_info → data_dt@250`,
      `JOIN data_dt@250 → ⟐output@19`): L250 reads
      `... AND T_BRANCH.data_dt = '${load_date}'` under
      `LEFT JOIN BDM_PUB_HSBC_ACCT_BRANCH T_BRANCH` — the occurrence's
      owner is BDM_PUB_HSBC_ACCT_BRANCH and bdm_acc_loan_info has NO token
      on the line. This is the FSB phantom class the R46a seed rule names
      verbatim (`_scope_target_stamp`: "READ-side same-name chips on other
      tables' compounds — the FSB phantoms (b/c/d/e.data_dt, a JOIN
      partner's partition column)"): a guessed owner the fold must never
      re-parent onto the searched compound.
  (C) pl↓PL, one node: the J12-20 edgeless co-filter sibling
      `charge_department`@265 dropped by the FILTERED path while its DL
      mirror (@561, byte-identical statement shape) and the PL UNFILTERED
      view still serve it.

ROOT CAUSE OF THE ADJUDICATED SERVING (evidence, 2026-09-01): none of the
three survives a cold build. The engine's graph cache is keyed by
EXTRACTOR_VERSION alone (`l2_builder._load_or_build_graph`:
md5(EXTRACTOR_VERSION + "|" + script + sql)), so the workspaces that were
adjudicated were still serving graphs built by an earlier state of the
R46d `.12` batch — one that minted an owner-qualified OCCURRENCE JOIN ON
twin (`bdm_acc_loan_info_sup.data_dt`@202 / `bdm_acc_loan_info.data_dt`@250,
`defined_in = "OCCURRENCE JOIN ON"`) for the AND leg. The twin's belongs-to
edges are what folded onto the foreign instance (A) and onto the searched
compound (B), and its extra seed is what displaced the co-filter sibling
from the walk's continuation bookkeeping (C). The staged `.12` tree
qualification-guards the mint (`_mint_join_leg_twins`:
`if base.line_start == line: continue` — "this very occurrence is the var
that anchors it"), so the twin is no longer minted and the fold — which
only ever projected the model — serves the adjudicated-correct shape.

This file pins the adjudicated properties so the class cannot come back
silently through either door: the fold must render one ownership fact per
(token, qualifying instance), never on a foreign statement's instance of
the same table, never on a compound the model does not name as the owner —
AND the foreign-statement / other-compound belongs-to edges that ARE
canonical (MA1/MA2, LFS120's `bdm@16 → lending_ref@19`) must keep serving,
so the class cannot be "repaired" with a blanket rule either.

Tests 1-3 are the three repros; tests 4-6 are the no-regression pins.
"""

import shutil
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.l2_builder import _build_l2_graph  # noqa: E402
from app.services.workspace_service import get_workspace_dir  # noqa: E402

SAMPLES = BACKEND_DIR.parent / "samples" / "sql_sample_v1"

# A workspace id of this module's own: the builds below cache into it, and
# the cache is cleared once per module import. A graph cache is keyed by
# EXTRACTOR_VERSION only (`_load_or_build_graph`), so a cache left behind by
# an earlier state of the SAME version would serve the pre-guard engine and
# fail these pins for a reason that is not an engine regression — the exact
# false positive this adjudication started from.
WS = "j2-fold"
shutil.rmtree(get_workspace_dir(WS), ignore_errors=True)


def _build(script, table, field, filtered=True):
    sql = (SAMPLES / script).read_text(encoding="utf-8")
    result = _build_l2_graph(WS, script, sql, table, field,
                             relevance_filter=filtered, direction="downstream")
    graph = result.get("graph") if isinstance(result.get("graph"), dict) else result
    nodes = {n["data"]["id"]: n["data"] for n in graph["nodes"]}
    edges = [e["data"] for e in graph["edges"]]
    return result, nodes, edges


def _label(nodes, edge, side):
    nd = nodes.get(edge[side]) or {}
    return nd.get("label", "")


def _schema_edges(edges, anchor=None):
    return [e for e in edges
            if e.get("edge_type") == "SCHEMA"
            and (anchor is None or e.get("highlight_line") == anchor)]


# ── Defect A: sup↓SUP_M — one ownership fact for the L202 occurrence ────

def test_sup_l202_ownership_served_once_at_the_qualifying_alias():
    """S5: the L202 occurrence's belongs-to renders ONCE, from p2@199 —
    never a second copy from the searched table's own compound, and never
    anchored on the next statement's instance (L223)."""
    _r, nodes, edges = _build("BDM_ACC_LOAN_INFO_SUP_M.sql",
                              "bdm_acc_loan_info_sup", "data_dt")
    at_202 = _schema_edges(edges, 202)
    assert len(at_202) == 1, (
        "exactly one ownership edge for the L202 occurrence expected, got %d: %s"
        % (len(at_202), [(e["id"], _label(nodes, e, "source"),
                          e.get("reason")) for e in at_202]))
    assert _label(nodes, at_202[0], "source") == "p2@199", (
        "the L202 ownership edge must render at the qualifying alias "
        "instance p2@199, got %r" % _label(nodes, at_202[0], "source"))
    # the dropped class: the searched table's own compound claiming the
    # ownership of the occurrence its alias instance already renders
    own = [e for e in at_202
           if _label(nodes, e, "source") == "bdm_acc_loan_info_sup"]
    assert not own, "searched compound must not duplicate the L202 ownership: %s" % own
    # the foreign statement's instance (the job-log read at L223) never
    # becomes the owner of record for a TOP0 occurrence
    foreign = [e for e in edges
               if e.get("edge_type") == "SCHEMA"
               and "bdm_acc_loan_info_sup@L223" in (e.get("reason") or "")]
    assert not foreign, "L223 instance must not own a L202 occurrence: %s" % foreign


def test_sup_full_view_l202_has_no_searched_compound_owner_copy():
    """The full view renders the ownership once per p2 INSTANCE (the
    MA1/MA2 doctrine) and still never from the searched compound."""
    _r, nodes, edges = _build("BDM_ACC_LOAN_INFO_SUP_M.sql",
                              "bdm_acc_loan_info_sup", "data_dt", filtered=False)
    at_202 = _schema_edges(edges, 202)
    assert at_202, "the L202 belongs-to twins must render in the full view"
    assert all(_label(nodes, e, "source").startswith("p2") for e in at_202), (
        "every L202 ownership edge must render at a p2 instance, got %s"
        % [(_label(nodes, e, "source"), e.get("reason")) for e in at_202])
    assert not [e for e in at_202
                if _label(nodes, e, "source") == "bdm_acc_loan_info_sup"], (
        "the searched compound must not own the L202 occurrence")


# ── Defect B: pl↓PL — the L250 token belongs to T_BRANCH ────────────────

def test_pl_l250_edges_never_attribute_to_the_searched_table():
    """The filtered closure serves no edge of the guessed-owner twin: no
    `bdm_acc_loan_info.data_dt` occurrence (the owner-qualified spelling)
    reaches the payload, and nothing anchors on the join line."""
    _r, nodes, edges = _build("BDM_ACC_LOAN_INFO_PL.sql",
                              "bdm_acc_loan_info", "data_dt")
    guessed = [e for e in edges
               if "bdm_acc_loan_info.data_dt" in
               ((e.get("_src_label") or "") + " " + (e.get("_tgt_label") or ""))
               or "bdm_acc_loan_info.data_dt@" in (e.get("reason") or "")]
    assert not guessed, (
        "the guessed-owner twin must not serve: %s"
        % [(e["id"], e.get("edge_type"), e.get("highlight_line"), e.get("reason"))
           for e in guessed])
    at_250 = [e for e in edges if e.get("highlight_line") == 250]
    assert not at_250, (
        "the join-partner partition line must stay out of the searched "
        "field's closure: %s" % [(e["id"], e.get("edge_type"), e.get("reason"))
                                 for e in at_250])


def test_pl_full_view_l250_ownership_names_t_branch():
    """The truth side: the L250 token's belongs-to renders from the model's
    own owner attribution — T_BRANCH@250 — never from bdm_acc_loan_info."""
    _r, nodes, edges = _build("BDM_ACC_LOAN_INFO_PL.sql",
                              "bdm_acc_loan_info", "data_dt", filtered=False)
    owners = [e for e in _schema_edges(edges, 250)
              if _label(nodes, e, "target").casefold() == "data_dt"]
    assert owners, "the L250 data_dt chip must keep its belongs-to edge"
    src_labels = {_label(nodes, e, "source") for e in owners}
    assert src_labels == {"T_BRANCH@250"}, (
        "the L250 data_dt ownership must attribute to T_BRANCH only, got %s (%s)"
        % (sorted(src_labels),
           [(e.get("reason")) for e in owners]))
    reasons = " | ".join(e.get("reason") or "" for e in owners)
    assert "T_BRANCH.data_dt@L250" in reasons and "T_BRANCH@L250" in reasons, (
        "the served reason must carry the model's own owner attribution, got %r"
        % reasons)
    assert not [e for e in _schema_edges(edges, 250)
                if _label(nodes, e, "source") == "bdm_acc_loan_info"
                and _label(nodes, e, "target").casefold() == "data_dt"], (
        "bdm_acc_loan_info has no token on L250 — it must not own the chip")


def test_synthetic_join_partner_partition_column_stays_on_its_own_box():
    """The FSB phantom class R46a names ("a JOIN partner's partition
    column"), distilled: a two-table join whose partner carries the
    searched field as a join-leg partition column. The partner's chip
    renders on the partner's compound (never on the searched compound) and
    carries no ownership edge from the searched table; the searched chip
    keeps its own seed claim."""
    sql = (
        "INSERT INTO TABLE bdm_acc_loan_info PARTITION (data_dt = '${load_date}')\n"
        "SELECT a.cust_no AS cust_no, a.acct_no AS acct_no,\n"
        "       t_branch.branch_code AS branch_code\n"
        "FROM staging_acc a\n"
        "LEFT JOIN bdm_pub_hsbc_acct_branch t_branch\n"
        "       ON a.branch_code = t_branch.branch_code\n"
        "      AND t_branch.data_dt = '${load_date}';\n"
        "\n"
        "INSERT INTO TABLE rrcdm_job_log_exec_par (data_dt, table_name)\n"
        "SELECT '${load_date}' AS data_dt, 'SYNTH' AS table_name\n"
        "FROM bdm_acc_loan_info\n"
        "WHERE data_dt = '${load_date}'\n"
        "AND charge_department = 'OPS';\n"
    )
    result = _build_l2_graph(WS, "J2_SYNTH.sql", sql, "bdm_acc_loan_info",
                             "data_dt", relevance_filter=False,
                             direction="downstream")
    graph = result.get("graph") if isinstance(result.get("graph"), dict) else result
    nodes = {n["data"]["id"]: n["data"] for n in graph["nodes"]}
    edges = [e["data"] for e in graph["edges"]]

    def _parent_label(nd):
        return (nodes.get(nd.get("parent")) or {}).get("label", "")

    partner_chips = [nd for nd in nodes.values()
                     if nd.get("type") == "field"
                     and nd.get("label", "").casefold() == "data_dt"
                     and _parent_label(nd) == "bdm_pub_hsbc_acct_branch"]
    assert partner_chips, "the join partner's own data_dt chip must render"
    assert all(nd.get("is_target") in (False, None) for nd in partner_chips), (
        "the join partner's partition column is the R46a FSB phantom — never "
        "a seed claim: %s" % [(nd.get("label"), nd.get("is_target"))
                              for nd in partner_chips])
    seed_chips = [nd for nd in nodes.values()
                  if nd.get("type") == "field"
                  and nd.get("label", "").casefold() == "data_dt"
                  and _parent_label(nd) == "bdm_acc_loan_info"]
    assert seed_chips, "the searched table's own data_dt chip must render"
    assert any(nd.get("is_target") for nd in seed_chips), (
        "the searched table's own chip keeps the seed claim")
    # no ownership edge into the partner chip from the searched compound
    chip_ids = {nd["id"] for nd in partner_chips}
    searched = {nd["id"] for nd in nodes.values()
                if _parent_label(nd) == "bdm_acc_loan_info"
                or nd.get("label") == "bdm_acc_loan_info"}
    bad = [e for e in edges
           if e.get("edge_type") == "SCHEMA"
           and e["target"] in chip_ids and e["source"] in searched]
    assert not bad, "the searched compound must not own the partner chip: %s" % bad
    own = [e for e in edges
           if e.get("edge_type") == "SCHEMA" and e["target"] in chip_ids]
    assert own, "the partner chip keeps its belongs-to"
    assert all(_label(nodes, e, "source") in ("t_branch@5", "bdm_pub_hsbc_acct_branch")
               for e in own), (
        "the partner's belongs-to must come from its own instance/compound: %s"
        % [(_label(nodes, e, "source"), e.get("reason")) for e in own])

    # and the FILTERED closure of the same shape: the join-partner line
    # never enters the searched field's payload as a searched-table edge
    f_res = _build_l2_graph(WS, "J2_SYNTH.sql", sql, "bdm_acc_loan_info",
                            "data_dt", direction="downstream")
    f_graph = (f_res.get("graph") if isinstance(f_res.get("graph"), dict)
               else f_res)
    f_nodes = {n["data"]["id"]: n["data"] for n in f_graph["nodes"]}
    f_edges = [e["data"] for e in f_graph["edges"]]
    guessed = [e for e in f_edges
               if e.get("edge_type") == "SCHEMA"
               and (f_nodes.get(e["source"]) or {}).get("label") == "bdm_acc_loan_info"
               and (f_nodes.get(e["target"]) or {}).get("label", "").casefold() == "data_dt"
               and (e.get("_src_ctx") or "") != (e.get("_tgt_ctx") or "")]
    assert not guessed, (
        "the searched compound must not own a join-leg occurrence: %s"
        % [(e["id"], e.get("highlight_line"), e.get("reason")) for e in guessed])


# ── Defect C: pl↓PL — the J12-20 co-filter sibling stays served ─────────

def test_pl_filtered_view_serves_the_co_filter_sibling():
    """charge_department@265 is a documented closure member (J12-20, W4
    co-filter sibling of the seed's WHERE clause, edgeless). The filtered
    path must serve it exactly like its byte-identical DL mirror."""
    _r, nodes, edges = _build("BDM_ACC_LOAN_INFO_PL.sql",
                              "bdm_acc_loan_info", "data_dt")
    sibs = [nd for nd in nodes.values()
            if nd.get("label", "").casefold() == "charge_department"
            and nd.get("line_start") == 265]
    assert sibs, "the PL filtered view must serve charge_department@265"
    parents = {_parent_of(nodes, nd) for nd in sibs}
    assert parents == {"bdm_acc_loan_info"}, (
        "the sibling renders on the searched table's compound, got %s" % parents)
    touching = [e for e in edges
                if e["source"] in {nd["id"] for nd in sibs}
                or e["target"] in {nd["id"] for nd in sibs}]
    assert not touching, (
        "the J12-20 sibling is edgeless: %s"
        % [(e["id"], e.get("edge_type"), e.get("highlight_line")) for e in touching])


def _parent_of(nodes, nd):
    return (nodes.get(nd.get("parent")) or {}).get("label", "")


def test_pl_unfiltered_view_keeps_the_co_filter_sibling():
    """The unfiltered view never changed — the sibling is served there too
    (the adjudication's own observation)."""
    _r, nodes, edges = _build("BDM_ACC_LOAN_INFO_PL.sql",
                              "bdm_acc_loan_info", "data_dt", filtered=False)
    assert [nd for nd in nodes.values()
            if nd.get("label", "").casefold() == "charge_department"
            and nd.get("line_start") == 265], (
        "the unfiltered view keeps charge_department@265")


def test_dl_mirror_serves_the_co_filter_sibling():
    """The reference: the byte-identical DL job-log statement keeps serving
    its sibling @561 (it never regressed)."""
    _r, nodes, edges = _build("BDM_ACC_LOAN_INFO_Digitallending.sql",
                              "bdm_acc_loan_info", "data_dt")
    assert [nd for nd in nodes.values()
            if nd.get("label", "").casefold() == "charge_department"
            and nd.get("line_start") == 561], (
        "the DL mirror keeps charge_department@561 in the filtered view")


# ── No-regression: the canonical ownership rows keep serving ────────────

def test_canonical_ownership_rows_keep_serving():
    """S5 / S1+S3 / MA1+MA2 / X3 / M1 — the adjudication refuses the
    DUPLICATE rendering of one ownership fact, never the per-instance
    rendering the canonical pins."""
    # sup S5
    _r, nodes, edges = _build("BDM_ACC_LOAN_INFO_SUP_M.sql",
                              "bdm_acc_loan_info_sup", "data_dt")
    assert any(_label(nodes, e, "source") == "p2@199"
               and e.get("highlight_line") == 202
               for e in _schema_edges(edges)), "sup S5 lost"
    # bdm S1/S3 + MA1/MA2 + X3
    _r, nodes, edges = _build("BDM_ACC_LOAN_INFO_SUP_M.sql",
                              "bdm_acc_loan_info", "data_dt")
    by_anchor = {}
    for e in _schema_edges(edges):
        by_anchor.setdefault(e.get("highlight_line"), set()).add(
            _label(nodes, e, "source"))
    assert {"p1@29", "p1@84"} <= by_anchor.get(43, set()), (
        "bdm S1/S3 lost: %s" % by_anchor.get(43))
    assert {"p1@29", "p1@84"} <= by_anchor.get(158, set()), (
        "bdm MA1/MA2 lost: %s" % by_anchor.get(158))
    assert "output" in by_anchor.get(213, set()), "bdm X3 lost"
    # pl M1 — the statement-2 output frame's membership edge
    _r, nodes, edges = _build("BDM_ACC_LOAN_INFO_PL.sql",
                              "bdm_acc_loan_info", "data_dt")
    assert any(_label(nodes, e, "source") == "output"
               and e.get("highlight_line") == 254
               for e in _schema_edges(edges)), "pl M1 lost"


def test_foreign_statement_belongs_to_class_is_not_swept():
    """LFS120 (`bdm@16 → lending_ref@19`, lending_ref↓SUP_M) is a
    canonical foreign-statement belongs-to edge: this adjudicated class is
    about a DUPLICATED or GUESSED owner, never about the statement the
    instance lives in. Pinning it keeps the fold from being 'repaired'
    with a blanket foreign-statement rule."""
    _r, nodes, edges = _build("BDM_ACC_LOAN_INFO_SUP_M.sql",
                              "bdm_acc_loan_info", "lending_ref")
    assert any(_label(nodes, e, "source") == "bdm_acc_loan_info"
               and e.get("highlight_line") == 19
               for e in _schema_edges(edges)), (
        "the canonical foreign-statement belongs-to row (LFS120) must keep "
        "serving: %s" % [(_label(nodes, e, "source"), e.get("highlight_line"))
                         for e in _schema_edges(edges)])
