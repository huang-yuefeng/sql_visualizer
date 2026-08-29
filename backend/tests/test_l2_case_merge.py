"""#288 (T1) case-insensitive physical-table merge + #289 (T2) INSERT
write-alias columns land on the write target.

Team C (2026-08-24), backend only:

* T1 (#288): a physical table referenced with different cases
  (east5_stzfxxb vs EAST5_STZFXXB) must render as ONE compound node —
  the physical-table merge key is case-folded (one keeper, merged-away
  nids re-point through occ_to_id). Aliases/subqueries/CTEs STAY
  case-sensitive: a genuinely distinct case-twin alias (A vs a) is still
  a DIFFERENT alias node.
* T2 (#289): the write-target routing is a FALLBACK, and nothing in EAST5
  exercises it any more. Since the sample declares alias `a` =
  bdm_acc_entrusted_payment, every a.-qualified projection has a real
  model owner and renders there; the dis_bank_id chip on east5 comes from
  DIRECT extraction-time attribution (the transform the model pins to
  east5_stzfxxb itself), not from the fallback. Because the repaired
  sample no longer contains a phantom-sourced projection, the fallback's
  own behavior — a SELECT projection whose only source is an undeclared
  alias (no resolvable model owner) still rendering ON the INSERT write
  target — is covered by the dedicated synthetic-fixture test
  (test_t2_phantom_projection_renders_on_write_target). DML ⟐-output
  routing is untouched (no qo_ nodes, write legs still hang off each
  statement's own output VT).
"""

import io
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(BACKEND_DIR))

from app.services.workspace_service import create_workspace, delete_workspace
from app.services.l2_builder import _build_l2_graph, _classify_compound_nodes

EAST5 = "EAST5_STZFXXB_M.sql"
EAST5_PATH = BACKEND_DIR.parent / "samples" / "sql_sample_v1" / EAST5


def _east5_keeper_id(node_map):
    """Derive the east5_stzfxxb keeper compound id from the graph instead of
    hardcoding the md5 — the keeper is the single physical node whose
    table_name folds to east5_stzfxxb. The md5 id is an implementation detail
    of the physical-table merge and must not be a brittle fixture constant."""
    matches = [n["id"] for n in node_map.values()
               if n.get("table_name", "").lower() == "east5_stzfxxb"]
    assert len(matches) == 1, \
        f"expected exactly one east5_stzfxxb physical node, got {len(matches)}"
    return matches[0]


def _table_id(node_map, table_name):
    """First node id whose table_name matches exactly (None if absent) — a
    guarded lookup, no StopIteration on a missing table."""
    for n in node_map.values():
        if n.get("table_name") == table_name:
            return n["id"]
    return None


@pytest.fixture
def east5_ws():
    sql = EAST5_PATH.read_text()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(EAST5, sql)
    ws_id = create_workspace(buf.getvalue())
    yield ws_id
    delete_workspace(ws_id)


def _make_ws(script_name, sql):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(script_name, sql)
    ws_id = create_workspace(buf.getvalue())
    return ws_id


@pytest.fixture
def twin_ws():
    """A physical table with a case-twin occurrence and two case-twin
    aliases (A / a) — the aliases must NOT fold."""
    sql = "SELECT A.c1 FROM tab_a AS A;\nSELECT a.c2 FROM TAB_A AS a;"
    ws_id = _make_ws("case_twin.sql", sql)
    yield ws_id
    delete_workspace(ws_id)


def _nodes_by(graph):
    return {n["data"]["id"]: n["data"] for n in graph["nodes"]}


def _kids(nodes, parent_id):
    return {n["label"] for n in nodes.values() if n.get("parent") == parent_id}


# ── T1 (#288): physical tables merge case-insensitively ──────────────

def test_t1_case_insensitive_physical_merge(east5_ws):
    """#288: east5_stzfxxb and EAST5_STZFXXB render as ONE compound node
    (the case-split twin merges into the keeper)."""
    res = _build_l2_graph(east5_ws, EAST5, EAST5_PATH.read_text(),
                          "", "", False)
    nodes = _nodes_by(res)
    east5 = [n for n in nodes.values()
             if n.get("table_name", "").lower() == "east5_stzfxxb"]
    assert len(east5) == 1, \
        f"east5_stzfxxb must render as ONE node, got {len(east5)}: " \
        f"{[(n['id'], n.get('table_name')) for n in east5]}"
    keep = east5[0]
    keeper_id = _east5_keeper_id(nodes)  # derived, not a hardcoded md5
    assert keep["id"] == keeper_id
    assert keep["type"] == "source_table", keep["type"]
    # the keeper carries the canonical lowercase spelling, not the uppercase
    # twin's — pinning WHICH occurrence won the merge (not just that one node
    # survived).
    assert keep["table_name"] == "east5_stzfxxb", keep["table_name"]
    # the merged node carries the uppercase occurrence's read field (p_dt)
    assert "p_dt" in _kids(nodes, keep["id"]), \
        "the merged east5 node must carry p_dt (the EAST5_STZFXXB read)"


def test_t1_alias_case_twin_not_folded(twin_ws):
    """#288 guard: a case-twin ALIAS is a DIFFERENT alias — the physical
    table folds, the aliases A and a stay two distinct alias nodes."""
    res = _build_l2_graph(twin_ws, "case_twin.sql",
                          "SELECT A.c1 FROM tab_a AS A;\n"
                          "SELECT a.c2 FROM TAB_A AS a;",
                          "", "", False)
    nodes = _nodes_by(res)
    physical = [n for n in nodes.values()
                if n.get("type") == "source_table"
                and n.get("table_name", "").lower() == "tab_a"]
    assert len(physical) == 1, \
        f"tab_a/TAB_A must fold into ONE physical node, got {len(physical)}: " \
        f"{[(n['id'], n.get('table_name')) for n in physical]}"
    aliases = [n for n in nodes.values() if n.get("type") == "alias_table"]
    assert len(aliases) == 2, \
        f"case-twin aliases must NOT fold, got {len(aliases)}: " \
        f"{[n.get('label') for n in aliases]}"
    labels = {n.get("label") for n in aliases}
    assert "A@1" in labels and "a@2" in labels, labels


# ── T2 (#289): INSERT write columns land on the write target ──────────

def test_t2_insert_write_columns_on_target(east5_ws):
    """#289 + R44 (2026-08-28): every EAST5 projection is DIRECTLY
    attributed by the model — and the write side now renders TOO.

    Probed truth (v3.3.170 repair): alias `a` = bdm_acc_entrusted_payment,
    so the a.-qualified projections (bz / TAG_* / CHARGE_DEPARTMENT /
    COM_RESERVED_1 / RESERVED_2/4/6 / PRIMARY_SRC_SYSTEM) carry their real
    owner in ``source_tables`` and land on bdm_acc_entrusted_payment. The
    dis_bank_id chip on east5 comes from the SAME kind of direct
    attribution: the model pins the output TRANSFORM var to east5_stzfxxb
    itself (``source_tables=['east5_stzfxxb']``, anchored L76 —
    ``b.org_no As dis_bank_id``; L77's ``nvl(b.dis_bank_id,
    'CNHSBC900Z')`` collapses into it — extraction-time DML-target
    attribution), so classification resolves it through the ordinary
    source-table parent match. ``write_field_target.get()`` never fires for
    it: no EAST5 projection is phantom-sourced any more. Its twin
    ``b.org_no As dis_bank_id`` reads bdm_acc_loan_info and therefore shows
    a second dis_bank_id chip there.

    R44 amendment (2026-08-28, user ruling "walker occurrence coverage"):
    every is_output projection of the east5-writing statement @41 ALSO
    materializes its WRITE-SIDE TWIN ``{east5_stzfxxb}.{projection}``
    (extraction-time, ``source_tables=['east5_stzfxxb']``, same line) —
    so each written column now renders TWICE: on its model owner (the
    value's read source) AND on the write target east5_stzfxxb (the write
    slot it occupies). bz did NOT move: both instances exist (probe:
    ``bz`` st=['bdm_acc_entrusted_payment'] L47 +
    ``east5_stzfxxb.bz`` st=['east5_stzfxxb'] L47). The pre-R44
    exclusivity pins ("must NOT land on east5") are superseded by
    twin-coexistence pins."""
    res = _build_l2_graph(east5_ws, EAST5, EAST5_PATH.read_text(),
                          "", "", False)
    nodes = _nodes_by(res)
    keeper_id = _east5_keeper_id(nodes)
    kids = _kids(nodes, keeper_id)
    bdm_id = _table_id(nodes, "bdm_acc_loan_info")
    assert bdm_id is not None, "bdm_acc_loan_info table not found"
    bdm_kids = _kids(nodes, bdm_id)
    ep_id = _table_id(nodes, "bdm_acc_entrusted_payment")
    assert ep_id is not None, "bdm_acc_entrusted_payment table not found"
    ep_kids = _kids(nodes, ep_id)
    # dis_bank_id reaches east5 through DIRECT model attribution (the
    # transform is pinned to east5_stzfxxb at extraction time) — never via
    # write_field_target: its b.org_no twin lands on its own reader.
    for wc in ("dis_bank_id",):
        assert wc in kids, \
            f"write column {wc} must land on the east5 target node"
        assert wc in bdm_kids, \
            f"{wc}'s b.org_no twin must stay on bdm_acc_loan_info (its reader)"
    # a.-qualified projections render on their model owner
    # bdm_acc_entrusted_payment (alias a), and since R44 ALSO as their
    # write-side twins on east5 (the INSERT @41 write target).
    for wc in ("bz", "TAG_COUNTRY", "TAG_ENTITY",
               "TAG_BRANCH", "TAG_GBGF", "TAG_RESERVE",
               "TAG_PRIMARY_ACCOUNTABLE_PARTY", "TAG_RESPONSIBLE_PARTY",
               "COM_RESERVED_1",
               "RESERVED_2", "RESERVED_4", "RESERVED_6",
               "PRIMARY_SRC_SYSTEM"):
        assert wc in ep_kids, \
            f"{wc} must land on bdm_acc_entrusted_payment (its model owner)"
        assert wc in kids, \
            f"{wc} must ALSO land on east5 as its R44 write-side twin"
    # CHARGE_DEPARTMENT spellings are case-sensitive BY DESIGN (#288 folds
    # only physical tables; column/alias identities keep their case):
    #   • bdm_acc_entrusted_payment owns the UPPERCASE projection
    #     (a.CHARGE_DEPARTMENT AS CHARGE_DEPARTMENT) and also the lowercase
    #     a.charge_department reads inside the partition-driven CASE arms;
    #   • east5_stzfxxb owns the lowercase partition twin — the
    #     PARTITION(... ,charge_department) spec @41 (+ ALTER ADD
    #     PARTITIONs), attributed directly to it as a read — and since R44
    #     ALSO the UPPERCASE write twin of the projection.
    assert "CHARGE_DEPARTMENT" in ep_kids, \
        "bdm_acc_entrusted_payment must own the uppercase CHARGE_DEPARTMENT projection"
    assert "charge_department" in kids and "CHARGE_DEPARTMENT" in kids, \
        ("east5_stzfxxb must carry the lowercase partition twin "
         "'charge_department' AND the uppercase R44 write twin "
         "'CHARGE_DEPARTMENT'")
    # model-aligned: the model attributes nbjgh/xdhth/xdjjh/dkje to
    # bdm_acc_loan_info — and since R44 their write twins land on east5.
    for wc in ("nbjgh", "xdhth", "xdjjh", "dkje"):
        assert wc in bdm_kids, \
            f"{wc} must land on bdm_acc_loan_info (its model owner)"
        assert wc in kids, \
            f"{wc} must ALSO land on east5 as its R44 write-side twin"


def test_t2_write_target_parent_at_classification(east5_ws):
    """#289 (phase-level probe): every EAST5 write column parents to its
    MODEL owner during _classify_compound_nodes — none of them through
    write_field_target. The dis_bank_id chip lands on the east5 keeper
    because the extractor ALREADY pinned that transform to east5_stzfxxb
    (``source_tables=['east5_stzfxxb']``), so classification resolves it by
    the ordinary source-table parent match; and alias `a` =
    bdm_acc_entrusted_payment means bz / TAG_COUNTRY / RESERVED_2 parent to
    bdm_acc_entrusted_payment. The fallback routing itself is exercised by
    test_t2_phantom_projection_renders_on_write_target."""
    import app.services.l2_builder as l2b
    sql = EAST5_PATH.read_text()
    full_graph, _, pm = l2b._load_or_build_graph(east5_ws, EAST5, sql)
    nodes = full_graph.get("nodes", [])
    target_ids, direct_ids = l2b._compute_target_and_direct_ids(
        nodes, full_graph.get("edges", []), "", "", physical_model=pm)
    table_nodes, field_nodes, _alias_map, _occ = _classify_compound_nodes(
        nodes, full_graph, EAST5, target_ids, direct_ids, None, pm)
    keeper_id = _east5_keeper_id(table_nodes)
    for probe in ("dis_bank_id",):
        got = [fn for fn in field_nodes
               if fn.get("label") == probe
               and fn.get("parent") == keeper_id]
        assert got, \
            f"{probe} must be a field node parented to the east5 keeper " \
            f"(direct model attribution, not fallback routing)"
    # a.-qualified projections parent to their model owner bdm_acc_entrusted_payment.
    ep_id = _table_id(table_nodes, "bdm_acc_entrusted_payment")
    assert ep_id is not None, "bdm_acc_entrusted_payment table not found"
    for probe in ("bz", "TAG_COUNTRY", "RESERVED_2"):
        got = [fn for fn in field_nodes
               if fn.get("label") == probe
               and fn.get("parent") == ep_id]
        assert got, \
            f"{probe} must be a field node parented to bdm_acc_entrusted_payment"
    # model-aligned: nbjgh is attributed to bdm_acc_loan_info, not east5
    bdm_id = _table_id(table_nodes, "bdm_acc_loan_info")
    assert bdm_id is not None, "bdm_acc_loan_info table not found"
    nbjgh = [fn for fn in field_nodes if fn.get("label") == "nbjgh"]
    assert nbjgh, "nbjgh not found as a field node"
    assert nbjgh[0].get("parent") == bdm_id, \
        f"nbjgh field parent must be bdm_acc_loan_info, " \
        f"got {nbjgh[0].get('parent')}"


def test_t2_dml_qo_routing_untouched(east5_ws):
    """#289: DML write legs still route through each statement's own ⟐
    output VT — no qo_ nodes, no synthetic edges."""
    res = _build_l2_graph(east5_ws, EAST5, EAST5_PATH.read_text(),
                          "", "", False)
    nodes = _nodes_by(res)
    assert not any(n["id"].startswith("qo_") for n in nodes.values()), \
        "no qo_ intermediate nodes may exist"
    east5_id = _table_id(nodes, "east5_stzfxxb")
    assert east5_id is not None, "east5_stzfxxb table not found"
    write_legs = [e["data"] for e in res["edges"]
                  if e["data"].get("id", "").endswith("_dml_out")
                  and e["data"].get("target") == east5_id]
    assert write_legs, "east5 must have a DML write leg"
    for ed in write_legs:
        src = nodes.get(ed["source"])
        assert src is not None and (src.get("table_name") or "").startswith("⟐ "), \
            f"write leg into east5 must route through a ⟐ output VT, got {ed}"


# ── T3 (table-dup audit 2026-08-28): MERGE target folds into the physical
# keeper — a table that is MERGE-INTO'd in one statement and read in
# another is ONE compound node (family-6 duplicate: source_table twin
# beside an intermediate_table twin). The model already keys merge_target
# occurrences by the raw physical name (kind "physical", roles
# {merge_target, read}); the display fold now includes them.
T3_MERGE_TWIN_SQL = """\
MERGE INTO acc_master t
USING acc_delta s
ON t.acct_no = s.acct_no
WHEN MATCHED THEN UPDATE SET t.balance = s.balance;
SELECT a.balance FROM acc_master a;
"""
T3_MERGE_SCRIPT = "t3_merge_twin.sql"


@pytest.fixture
def merge_twin_ws():
    ws_id = _make_ws(T3_MERGE_SCRIPT, T3_MERGE_TWIN_SQL)
    yield ws_id
    delete_workspace(ws_id)


def test_t3_merge_target_folds_into_physical_keeper(merge_twin_ws):
    """acc_master (MERGE target @TOP0 + read @TOP1) renders as ONE node
    carrying BOTH statements' fields — the merge_target occurrence joins
    the #288 case-folded physical fold. The keeper is a physical table in
    either order: a non-output merge_target is a source_table (M7 — the
    order-dependent intermediate_table classification was the bug)."""
    res = _build_l2_graph(merge_twin_ws, T3_MERGE_SCRIPT, T3_MERGE_TWIN_SQL,
                          "", "", False)
    nodes = _nodes_by(res)
    twins = [n for n in nodes.values()
             if (n.get("table_name") or "").lower() == "acc_master"]
    assert len(twins) == 1, \
        f"acc_master must render as ONE node (MERGE target + read), " \
        f"got {[(n['id'], n.get('type')) for n in twins]}"
    keep = twins[0]
    assert keep["type"] == "source_table", keep["type"]
    assert {"acct_no", "balance"} <= _kids(nodes, keep["id"]), \
        "the merged acc_master node must carry the MERGE-side fields"


def test_t3_read_first_order_folds_too(merge_twin_ws):
    """Occurrence order must not matter: read @TOP0 + MERGE @TOP1 is still
    ONE acc_master node (keeper type source_table — the read came first).

    M10: the statements are swapped WHOLE (never line-reversed — reversing
    lines produced invalid SQL where the WHEN MATCHED clause preceded the
    MERGE INTO head, so the "read first" order was never actually
    exercised)."""
    stmt1, stmt2 = T3_MERGE_TWIN_SQL.strip().split(";\n")
    sql = f"{stmt2};\n{stmt1};\n"
    name = "t3_merge_twin_rev.sql"
    ws_id = _make_ws(name, sql)
    try:
        res = _build_l2_graph(ws_id, name, sql, "", "", False)
        nodes = _nodes_by(res)
        twins = [n for n in nodes.values()
                 if (n.get("table_name") or "").lower() == "acc_master"]
        assert len(twins) == 1, \
            f"acc_master must be ONE node in either order, got {len(twins)}"
        assert twins[0]["type"] == "source_table", twins[0]["type"]
        assert "balance" in _kids(nodes, twins[0]["id"])
    finally:
        delete_workspace(ws_id)


def test_t3_one_char_apart_tables_stay_distinct():
    """Fold guard: bdm_acc_loan_info vs bdm_acc_loan_inf2 (Levenshtein 1)
    are DIFFERENT tables — exactly two nodes, no cross-attribution."""
    sql = ("SELECT a.c1 FROM bdm_acc_loan_info a;\n"
           "SELECT b.c2 FROM bdm_acc_loan_inf2 b;\n")
    name = "t3_onechar.sql"
    ws_id = _make_ws(name, sql)
    try:
        res = _build_l2_graph(ws_id, name, sql, "", "", False)
        nodes = _nodes_by(res)
        counts = {}
        for n in nodes.values():
            key = (n.get("table_name") or "").lower()
            if n.get("type") == "source_table" and key.startswith("bdm_acc_loan_inf"):
                counts[key] = counts.get(key, 0) + 1
        assert counts.get("bdm_acc_loan_info") == 1, counts
        assert counts.get("bdm_acc_loan_inf2") == 1, counts
        info_id = _table_id(nodes, "bdm_acc_loan_info")
        inf2_id = _table_id(nodes, "bdm_acc_loan_inf2")
        assert _kids(nodes, info_id) == {"c1"}, \
            "c1 belongs to bdm_acc_loan_info only"
        assert _kids(nodes, inf2_id) == {"c2"}, \
            "c2 belongs to bdm_acc_loan_inf2 only"
    finally:
        delete_workspace(ws_id)


# ── T2 (#289): the phantom-projection → write-target FALLBACK itself ──
# EAST5 no longer contains a phantom-sourced projection (alias `a` resolves
# to bdm_acc_entrusted_payment), so the fallback branch of
# _classify_compound_nodes needs its own minimal fixture: an INSERT...SELECT
# whose projection is qualified by an alias declared NOWHERE (`z`) — a
# phantom with no model owner — beside one ordinary, resolvable projection.
T2B_FALLBACK_SQL = """\
INSERT INTO dwd_pay_detail
SELECT z.phantom_col AS carried_amt, r.keep_col AS kept_amt
FROM real_src r;
"""
T2B_SCRIPT = "t2_phantom_fallback.sql"


@pytest.fixture
def phantom_ws():
    ws_id = _make_ws(T2B_SCRIPT, T2B_FALLBACK_SQL)
    yield ws_id
    delete_workspace(ws_id)


def test_t2_phantom_projection_renders_on_write_target(phantom_ws):
    """#289 BEHAVIORAL: a SELECT projection sourced to an alias with NO
    resolvable owner still renders ON the INSERT write target.

    `z` is qualified in the projection but never declared — it owns no
    node, no physical name and no alias_map entry. Classification therefore
    cannot resolve a parent from ``source_tables=['z']`` and falls through
    to ``write_field_target`` (the SCHEMA-member × DML-target association of
    _classify_compound_nodes), which parents the projection onto the write
    target's keeper. The sibling projection reading a REAL table (kept_amt)
    keeps its model owner real_src — the fallback never hijacks resolved
    sources — and since R44 (2026-08-28, user ruling "walker occurrence
    coverage") ALSO renders its write-side twin
    ``dwd_pay_detail.kept_amt`` on the write target (two instances: source
    parent + write twin). A trailing no-INSERT contrast probe re-runs the
    same projection as a bare SELECT: with no DML-target association nothing
    parents it, proving the write target (not the projection itself) is
    what fires the fallback."""
    # Extraction truth first: carried_amt IS phantom-sourced — its single
    # source entry names the undeclared alias, which owns no visible node.
    import app.services.l2_builder as l2b
    full_graph, _, _pm = l2b._load_or_build_graph(
        phantom_ws, T2B_SCRIPT, T2B_FALLBACK_SQL)
    proj = [nd.get("data", nd) for nd in full_graph.get("nodes", [])
            if nd.get("data", nd).get("label") == "carried_amt"]
    assert len(proj) == 1, \
        f"expected exactly one carried_amt var, got {len(proj)}"
    assert proj[0].get("variable_type") == "column", \
        f"carried_amt must be a plain column projection, got {proj[0]}"
    assert proj[0].get("source_tables") == ["z"], \
        ("carried_amt must be sourced to the undeclared alias z "
         "(the phantom precondition), got "
         f"{proj[0].get('source_tables')}")

    res = _build_l2_graph(phantom_ws, T2B_SCRIPT, T2B_FALLBACK_SQL,
                          "", "", False)
    nodes = _nodes_by(res)
    ghost_nodes = [d for d in nodes.values()
                   if d.get("type") != "field"
                   and (d.get("table_name") or d.get("label")) == "z"]
    assert not ghost_nodes, f"`z` must own no display node, got {ghost_nodes}"

    def _chip_owner(label):
        got = {d.get("parent") for d in nodes.values()
               if d.get("type") == "field" and d.get("label") == label}
        assert len(got) == 1, f"{label} expected under exactly ONE parent, got {got}"
        return got.pop()

    def _chip_owners(label):
        return {d.get("parent") for d in nodes.values()
                if d.get("type") == "field" and d.get("label") == label}

    target_id = _table_id(nodes, "dwd_pay_detail")
    assert target_id is not None, "write target dwd_pay_detail not found"
    src_id = _table_id(nodes, "real_src")
    assert src_id is not None, "real_src table not found"
    # the phantom-sourced write column renders ON THE WRITE TARGET — and
    # since R44 its write-side twin dwd_pay_detail.carried_amt lands on the
    # SAME parent, so carried_amt stays single-parented.
    assert _chip_owner("carried_amt") == target_id, \
        "phantom-sourced carried_amt must render on the write target " \
        "dwd_pay_detail (the #289 fallback)"
    # control: a resolvable projection keeps its real model owner — and
    # since R44 (2026-08-28, user ruling "walker occurrence coverage") it
    # ALSO renders its write-side twin dwd_pay_detail.kept_amt on the write
    # target: TWO distinct instances (source parent + write twin — two
    # field nodes, two parents), NOT one node flickering between parents.
    assert _chip_owners("kept_amt") == {src_id, target_id}, \
        "kept_amt must render on BOTH real_src (model owner) and " \
        "dwd_pay_detail (R44 write twin)"

    # Contrast probe (no DML → no fallback): the SAME phantom projection in
    # a bare SELECT (no INSERT) owns no write target — write_field_target
    # stays empty, so NO table parents carried_amt (the chip renders
    # parentless or is dropped). The write target is what pulls it in:
    # genuinely #289 routing, not an accident of the projection itself.
    noins_name = "t2_no_insert.sql"
    noins_sql = T2B_FALLBACK_SQL.split("\n", 1)[1]
    noins_ws = _make_ws(noins_name, noins_sql)
    try:
        res2 = _build_l2_graph(noins_ws, noins_name, noins_sql,
                               "", "", False)
        owners = {d.get("parent") for d in _nodes_by(res2).values()
                  if d.get("type") == "field"
                  and d.get("label") == "carried_amt"}
        assert owners <= {None}, \
            f"without the INSERT no table may own carried_amt, got {owners}"
    finally:
        delete_workspace(noins_ws)
