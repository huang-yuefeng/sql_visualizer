"""RC-B multi-anchor fold (fix team G8, 2026-08-31).

Root cause RC-B — the L2 display fold (`l2_builder._combine_edges`) keyed
on (source, target, edge_type) and kept ONE carrier per pair, so when N
occurrences of the searched field reached the same target the served
payload showed ONE anchor line and the other N-1 went dark. The model
CARRIED the per-occurrence edges the whole time (R44's "cover all
occurrences" ruling), the display dropped them. 10-case cross-check
evidence: SUP_M lending_ref is served at L201 only while the model holds
JOIN edges at L95 (`ON p1.lending_ref = accu.vlookup_key_value`), L156
(`ON p6.lending_ref = p1.lending_ref`), L163 (the write projection) and
L206 (`p3.lending_ref = p1.lending_ref`).

The fix: the fold key is (source, target, edge_type, ANCHOR) with ANCHOR =
the highlight_line the carrier will be served with (the payload rule
itself, evaluated on the carrier). K distinct anchor lines ⇒ K served
edges, one per line, emitted in ascending line order.

What these tests pin that the unit suite does not:
  * the END-TO-END served payload (through _build_l2_graph), not the fold
    in isolation — a carrier can be dropped before the fold (closure
    admission) and no fold change can rescue it (see the L163/L206 note);
  * the real cross-check corpus (SUP_M lending_ref);
  * the merged (`l2m_*`) view consistency — one merged edge per line;
  * the landed guards (Fix H / LFS108 / AD2-B line 0) still hold with
    multi-anchor present.
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.l2_builder import (  # noqa: E402
    _build_l2_graph,
    _combine_edges,
    build_line_merged_edges,
)

SAMPLES = BACKEND_DIR.parent / "samples" / "sql_sample_v1"
FLAGSHIP = SAMPLES / "BDM_ACC_LOAN_INFO_SUP_M.sql"

# ── synthetic fixture: one field, two join occurrences, one target ──────
#
#     L1  WITH loan_final AS (
#     L2      SELECT p1.acct_no
#     ...
#     L5      FROM bdm_main p1
#     L6      LEFT JOIN dim_a p2
#     L7          ON p1.acct_no = p2.k1        <- occurrence X
#     L8      LEFT JOIN dim_b p3
#     L9          ON p1.acct_no = p3.k2        <- occurrence Y
#     ...)
#     L11 INSERT OVERWRITE TABLE bdm_out ...
#     L12 SELECT acct_no FROM loan_final;
#
# Both ON clauses produce a JOIN edge whose folded pair is the SAME
# (acct_no chip -> loan_final VT) — exactly the shape the single-carrier
# fold collapsed to one anchor.
SYNTHETIC = """WITH loan_final AS (
    SELECT p1.acct_no
           ,p2.k1
           ,p3.k2
    FROM bdm_main p1
    LEFT JOIN dim_a p2
        ON p1.acct_no = p2.k1
    LEFT JOIN dim_b p3
        ON p1.acct_no = p3.k2
)
INSERT OVERWRITE TABLE bdm_out PARTITION(data_dt = '$(load_date)')
SELECT acct_no FROM loan_final;
"""
JOIN_X = 7          # ON p1.acct_no = p2.k1
JOIN_Y = 9          # ON p1.acct_no = p3.k2

SYNTHETIC_ONE = """WITH loan_final AS (
    SELECT p1.acct_no
           ,p2.k1
    FROM bdm_main p1
    LEFT JOIN dim_a p2
        ON p1.acct_no = p2.k1
)
INSERT OVERWRITE TABLE bdm_out PARTITION(data_dt = '$(load_date)')
SELECT acct_no FROM loan_final;
"""

JOIN_ONE = 6        # the single ON line of the one-occurrence fixture


def _line_of(sql, needle):
    """1-based line number of the (unique) line carrying `needle`."""
    hits = [i for i, line in enumerate(sql.splitlines(), 1) if needle in line]
    assert len(hits) == 1, f"{needle!r} is not a unique line marker: {hits}"
    return hits[0]


assert _line_of(SYNTHETIC, "= p2.k1") == JOIN_X
assert _line_of(SYNTHETIC, "= p3.k2") == JOIN_Y
assert _line_of(SYNTHETIC_ONE, "= p2.k1") == JOIN_ONE


def _build(sql, table="bdm_main", field="acct_no"):
    result = _build_l2_graph("g8", "g8_multi_anchor.sql", sql, table, field)
    graph = result.get("graph") if isinstance(result.get("graph"), dict) else result
    nodes = {n["data"]["id"]: n["data"] for n in graph["nodes"]}
    edges = [e["data"] for e in graph["edges"]]
    return nodes, edges


def _joins(nodes, edges, src_label, tgt_label):
    """The JOIN edges of one (source, target) label pair, with anchors."""
    out = []
    for e in edges:
        if e.get("edge_type") != "JOIN":
            continue
        if (nodes.get(e["source"], {}).get("label") == src_label
                and nodes.get(e["target"], {}).get("label") == tgt_label):
            out.append(e)
    return out


# ── 1. the defect: two occurrences -> two served anchors ────────────────

def test_two_join_occurrences_serve_two_anchors():
    """A field joining the same target at lines X and Y serves TWO edges,
    anchored X and Y (the single-carrier fold served one of them and left
    the other dark)."""
    nodes, edges = _build(SYNTHETIC)
    joins = _joins(nodes, edges, "acct_no", "loan_final")
    anchors = sorted(e["highlight_line"] for e in joins)

    assert JOIN_X in anchors, f"join occurrence @L{JOIN_X} is dark: {anchors}"
    assert JOIN_Y in anchors, f"join occurrence @L{JOIN_Y} is dark: {anchors}"
    assert len(joins) == len({e["highlight_line"] for e in joins}), (
        "two carriers on one anchor line must fold to one edge, not duplicate")
    # every served JOIN edge of the pair carries a distinct id (Cytoscape
    # keys elements by id; the benchmark's used-set consumes ids)
    assert len({e["id"] for e in joins}) == len(joins)


def test_single_occurrence_case_is_unchanged():
    """One occurrence -> its ON line is served exactly ONCE, with no
    duplicate edge on that line: multi-anchor splits distinct lines, it
    never duplicates one line's edge.

    (The second served JOIN sits on the CTE's own projection line L2 — the
    extractor's projection twin inheriting the group's join relationship,
    the LFS123 WRONG-COVERED class reported to the ledger. It is an
    extraction-time attribution, present before this fold ran, and out of
    the fold's scope.)"""
    nodes, edges = _build(SYNTHETIC_ONE)
    joins = _joins(nodes, edges, "acct_no", "loan_final")
    on_line = [e for e in joins if e["highlight_line"] == JOIN_ONE]

    assert len(on_line) == 1
    assert on_line[0]["id"].startswith("l2e_")
    assert len({e["highlight_line"] for e in joins}) == len(joins)


def test_cross_check_dark_lines_are_served_sup_m_lending_ref():
    """The 10-case cross-check evidence, pinned on the real corpus: the
    SUP_M lending_ref closure serves the adjudicated occurrence lines. L95
    (`ON p1.lending_ref = accu.vlookup_key_value`) and L156
    (`ON p6.lending_ref = p1.lending_ref`) were the dark lines; L201 was
    the single survivor that used to stand in for all of them."""
    sql = FLAGSHIP.read_text(encoding="utf-8")
    nodes, edges = _build(sql, "bdm_acc_loan_info", "lending_ref")
    anchors = {e["highlight_line"] for e in edges
               if e.get("edge_type") == "JOIN"
               and nodes.get(e["source"], {}).get("label") == "lending_ref"}

    assert {95, 156, 201} <= anchors, (
        f"cross-check dark lines re-opened: {sorted(anchors)}")


# ── 3. the landed guards still hold with multi-anchor present ───────────

def _edge(src, tgt, etype, src_line, tgt_line, field_like=False):
    return {
        "id": f"l2e_{src}_{tgt}_{etype}_{src_line}",
        "source": src, "target": tgt, "edge_type": etype, "label": etype,
        "_src_line": src_line, "_tgt_line": tgt_line,
        "_src_field_like": field_like,
    }


def test_guards_hold_with_multi_anchor_present():
    """Fix H (the chip's own line represents its anchor group), the AD2-B
    line-0 refusal (a chip at line 0 never promotes a carrier), and LFS108
    (a line another relationship claims mints no edge of its own) all hold
    in the SAME carrier set — the multi-anchor split does not weaken them.

    Carriers of `f -> chip` (REF): the chip's own line 7, a real occurrence
    at 48, and a carrier at line 41 whose line is the JOIN's site. With
    `node_lines` naming line 0 for a second chip, Fix H and AD2-B must both
    refuse."""
    chip_line_0 = "chip0"
    carriers = [
        _edge("f", "chip", "JOIN", 41, 41),                    # the line-41 claim
        _edge("f", "chip", "REF", 41, 41, field_like=True),    # borrowed site
        _edge("f", "chip", "REF", 48, 48),                     # own occurrence
        _edge("f", "chip", "REF", 7, 7),                       # Fix H's carrier
        _edge("f", chip_line_0, "REF", 88, 0),                 # line-0 chip
    ]
    out = _combine_edges(carriers, {"chip": 7, chip_line_0: 0})

    got = {(e["edge_type"], e["_src_line"]) for e in out}
    # Fix H: the chip's own line is served and carried by the line-7 carrier.
    assert ("REF", 7) in got
    # R44/multi-anchor: the relationship's own occurrence line is served.
    assert ("REF", 48) in got
    # LFS108: the JOIN-key line earns no REF edge of its own.
    assert ("REF", 41) not in got
    assert ("JOIN", 41) in got
    # AD2-B: the line-0 chip's carrier is served on ITS OWN occurrence line,
    # never promoted onto another line by a chip that carries no line.
    assert ("REF", 88) in got


# ── 4. merged-view consistency: one l2m edge per line ───────────────────

def test_merged_view_has_one_edge_per_line():
    """`build_line_merged_edges` keys on (line, unordered table pair): the
    multi-anchor served edges must produce ONE merged edge per line — never
    a duplicate pair on a line, never a line lost."""
    result = _build_l2_graph("g8", "g8_multi_anchor.sql", SYNTHETIC,
                             "bdm_main", "acct_no")
    graph = result.get("graph") if isinstance(result.get("graph"), dict) else result
    nodes = [n["data"] for n in graph["nodes"]]
    detailed = [e["data"] for e in graph["edges"]]

    merged = [e["data"] for e in build_line_merged_edges(
        [{"data": e} for e in detailed], [{"data": n} for n in nodes])]

    by_line = {}
    for e in merged:
        by_line.setdefault(e["highlight_line"], set()).add(
            tuple(sorted([e["source"], e["target"]])))
    # both join occurrence lines survived the merge …
    assert JOIN_X in by_line and JOIN_Y in by_line
    # … and no line carries the same table pair twice
    for line, pairs in by_line.items():
        assert len(pairs) == len(set(pairs)), f"duplicate pair on L{line}"
    assert len({e["id"] for e in merged}) == len(merged)


def test_merged_view_real_corpus_covers_the_cross_check_lines():
    """Same assertion on the flagship: the merged view covers L95/L156 —
    the lines the user reads in the SQL panel."""
    sql = FLAGSHIP.read_text(encoding="utf-8")
    result = _build_l2_graph("g8", "BDM_ACC_LOAN_INFO_SUP_M.sql", sql,
                             "bdm_acc_loan_info", "lending_ref")
    graph = result.get("graph") if isinstance(result.get("graph"), dict) else result
    nodes = [n["data"] for n in graph["nodes"]]
    detailed = [e["data"] for e in graph["edges"]]
    merged = [e["data"] for e in build_line_merged_edges(
        [{"data": e} for e in detailed], [{"data": n} for n in nodes])]

    assert {95, 156, 201} <= {e["highlight_line"] for e in merged}
