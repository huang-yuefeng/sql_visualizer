"""Unit tests for `_combine_edges` (l2_builder Phase 5) carrier preference.

Covers the 2026-08-29 adjudications (Fix B / Fix C / LFS108) under the
RC-B multi-anchor contract (2026-08-31, fix team G8):

RC-B — the fold key is (source, target, edge_type, ANCHOR) where ANCHOR is
the highlight_line the carrier will be SERVED with. A pair whose carriers
sit at K distinct anchor lines serves K edges, one per line, instead of one
carrier standing in for all of them (the 10-case cross-check: SUP_M
lending_ref @95/@156/@163/@206 all folded into the @201 carrier while the
model carried all four JOIN edges).

Fix B — the keeper-line rule treats line 0 as invalid. `node_lines` values
are `line_start` integers and 0 means "no SQL line" (a TVF alias, a
synthetic frame); a chip sitting at line 0 must never pull a carrier onto
it merely because that carrier's target line matched 0 — a
non-relationship site. `want` is an int >= 0 or None, so a plain truthy
test excludes both. Under multi-anchor the guard is a REFUSAL to build a
`fix_h` entry, never a promotion.

Fix C — R45 Fix H is decided over the WHOLE carrier set, before the
combine loop, instead of only over carriers[1:]. The latch is load-bearing
and is now per anchor group: Fix H picks the representative OF a line, it
never erases the other lines any more.

LFS108 — a carrier whose field-side line another relationship already
claims on the same (source, target) pair is that other relationship's
site, so it does not mint an edge of its own when the pair has a carrier
whose line is this relationship's alone (Fix H's carrier stays immune).
Under multi-anchor the "yield the anchor" form became "do not mint an
anchor": `lending_ref -> ⟐subq (FILTER)` keeps exactly one served edge,
anchored at 48, and the JOIN-key line 41 gains no phantom FILTER.

The `node_lines=None` invocation shape mirrors the two existing direct
call sites (test_l1_l2_integration.py, test_physical_model_equivalence.py).
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.l2_builder import _combine_edges  # noqa: E402


def _edge(src, tgt, etype, src_line, tgt_line, field_like=False):
    """A minimal carrier with the keys `_combine_edges` actually reads —
    the same carried shape `_carry_edge_info` stamps on real edges."""
    return {
        "id": f"l2e_{src}_{tgt}_{etype}_{src_line}",
        "source": src,
        "target": tgt,
        "edge_type": etype,
        "label": etype,
        "_src_line": src_line,
        "_tgt_line": tgt_line,
        "_src_field_like": field_like,
    }


def _ref(src, tgt, src_line, tgt_line, field_like=False):
    return _edge(src, tgt, "REF", src_line, tgt_line, field_like)


def _anchors(out):
    """{(edge_type, _src_line)} of the folded output — the multi-anchor
    shape assertion (which type survived on which occurrence line)."""
    return {(e["edge_type"], e["_src_line"]) for e in out}


# ── Fix B: a chip at line 0 is not a relationship site ─────────────────

def test_fix_b_chip_at_line_zero_never_steals_the_anchor():
    """`[{REF @41->41}, {REF @88->0}]` with chip line 0 -> the 41 group
    keeps its own carrier (`_src_line` 41), so the highlight stays on line
    41. The line-0 chip builds no `fix_h` entry, so it cannot promote the
    @88 carrier into the 41 group either — the two carriers are two
    occurrence lines (RC-B), and neither is re-anchored onto the chip."""
    src, tgt = "SUP_M", "tag_branch"
    keeper = _ref(src, tgt, 41, 41)
    mis_anchor = _ref(src, tgt, 88, 0)

    out = _combine_edges([keeper, mis_anchor], {tgt: 0})

    assert len(out) == 2                          # two occurrence lines
    assert _anchors(out) == {("REF", 41), ("REF", 88)}
    by_line = {e["_src_line"]: e for e in out}
    assert by_line[41] is keeper                  # not re-anchored
    assert by_line[88] is mis_anchor              # not promoted either


def test_fix_b_chip_at_line_zero_is_a_refusal_not_a_reordering():
    """The same guard runs in the pre-loop Fix-H pass: a line-0 chip builds
    no `fix_h` entry. Fix B only REFUSES to let the line-0 carrier win —
    it never promotes it, so each occurrence line keeps the carrier that
    arrived first for it (order-independent: both orders keep the same
    carrier per line)."""
    src, tgt = "SUP_M", "tag_branch"
    keeper = _ref(src, tgt, 41, 41)
    mis_anchor = _ref(src, tgt, 88, 0)

    # Reverse order: the line-0 carrier arrives FIRST.
    out = _combine_edges([mis_anchor, keeper], {tgt: 0})

    assert len(out) == 2
    assert _anchors(out) == {("REF", 41), ("REF", 88)}
    by_line = {e["_src_line"]: e for e in out}
    assert by_line[41] is keeper
    assert by_line[88] is mis_anchor
    assert by_line[88]["_tgt_line"] == 0          # never re-anchored to 41


# ── Fix C: Fix H over the whole carrier set ────────────────────────────

SRC, TGT = "lending_ref", "SUBQ_OUT"
CHIP_LINE = 7


def _carrier_set():
    """One folded (source, target, REF) pair with three carriers.

    `claimed`  — its occurrence line 41 is shared with a JOIN on the same
                 pair (another relationship's site).
    `unclaimed`— its occurrence line 48 is this relationship's alone.
    `chip`     — the carrier whose target line IS the keeper chip's line 7.

    Returns the edge list plus the chip line the target node carries.
    """
    claimed = _ref(SRC, TGT, 41, 41, field_like=True)
    unclaimed = _ref(SRC, TGT, 48, 48)
    chip = _ref(SRC, TGT, CHIP_LINE, CHIP_LINE)
    # A different type on the same pair at line 41 — this is what makes
    # line 41 "claimed together" and arms the LFS108 residual.
    join = _edge(SRC, TGT, "JOIN", 41, 41)
    return claimed, unclaimed, chip, join


def test_fix_c_carrier_order_does_not_decide_the_anchor():
    """Carriers [claimed@41, unclaimed@48, chip@7] -> the chip's own line 7
    is served (Fix H's carrier), the relationship's own line 48 is served,
    and the claimed JOIN-key line 41 mints NO REF edge (LFS108, generalized
    by RC-B: a borrowed site does not earn an anchor).

    This order is where the old loop-side ordering actually failed: the
    residual branch adopted `unclaimed@48` first and latched `keepers`,
    so the chip carrier arriving third was locked out (anchor 48)."""
    claimed, unclaimed, chip, join = _carrier_set()

    out = _combine_edges([claimed, unclaimed, chip, join], {TGT: CHIP_LINE})

    assert len(out) == 3
    assert _anchors(out) == {("REF", CHIP_LINE), ("REF", 48), ("JOIN", 41)}
    by_line = {(e["edge_type"], e["_src_line"]): e for e in out}
    assert by_line[("REF", CHIP_LINE)] is chip
    assert by_line[("REF", 48)] is unclaimed


def test_fix_c_reverse_order_anchors_the_chip_line_too():
    """The mirrored carrier order [chip@7, unclaimed@48, claimed@41] keeps
    the same three served edges — order independence is the whole point of
    Fix C, and RC-B extends it to the per-line group membership."""
    claimed, unclaimed, chip, join = _carrier_set()

    out = _combine_edges([chip, unclaimed, claimed, join], {TGT: CHIP_LINE})

    assert len(out) == 3
    assert _anchors(out) == {("REF", CHIP_LINE), ("REF", 48), ("JOIN", 41)}
    by_line = {(e["edge_type"], e["_src_line"]): e for e in out}
    assert by_line[("REF", CHIP_LINE)] is chip
    assert by_line[("REF", 48)] is unclaimed


def test_fix_c_first_carrier_is_the_fix_h_carrier_stays_latched():
    """Carriers [chip@7, later@41] -> both lines are served.

    carriers[0] IS the Fix-H carrier, so no swap is ever visible — but the
    unconditional `keepers` latch must still fire, otherwise the residual
    branch sees the keeper as "claimed together" (line 7 is shared with the
    JOIN on the same pair) and strips the chip's own line. Fix H's carrier
    is IMMUNE to the RC-B drop for the same reason: it is the chip's own
    occurrence, never a borrowed site."""
    chip = _ref(SRC, TGT, CHIP_LINE, CHIP_LINE, field_like=True)
    later = _ref(SRC, TGT, 41, 41)
    # Line 7 is shared with a JOIN on the same pair: with the latch missing
    # the residual branch sees the keeper as "claimed together" and swaps.
    join = _edge(SRC, TGT, "JOIN", CHIP_LINE, CHIP_LINE)

    out = _combine_edges([chip, later, join], {TGT: CHIP_LINE})

    assert len(out) == 3
    assert _anchors(out) == {("REF", CHIP_LINE), ("REF", 41),
                             ("JOIN", CHIP_LINE)}
    by_line = {(e["edge_type"], e["_src_line"]): e for e in out}
    assert by_line[("REF", CHIP_LINE)] is chip


def test_fix_c_lfs108_three_filter_carriers_still_anchor_48():
    """LFS108's exact shape is untouched: three FILTER carriers of
    `lending_ref -> ⟐subq` (@41 the JOIN-key occurrence, @48 twice) with
    the chip at 13 — no carrier names line 13, so Fix H never fires and the
    claimed JOIN-key line 41 mints no FILTER edge of its own; the anchor
    stays on the line this relationship owns."""
    subq = "subq"
    c41 = _edge(SRC, subq, "FILTER", 41, 26, field_like=True)
    c48a = _edge(SRC, subq, "FILTER", 48, 26)
    c48b = _edge(SRC, subq, "FILTER", 48, 26)
    join = _edge(SRC, subq, "JOIN", 41, 26)

    out = _combine_edges([c41, c48a, c48b, join], {subq: 13})

    assert len(out) == 2
    assert _anchors(out) == {("FILTER", 48), ("JOIN", 41)}
    by_type = {e["edge_type"]: e for e in out}
    assert by_type["FILTER"]["_src_line"] == 48
    assert by_type["JOIN"]["_src_line"] == 41


def test_lfs108_claimed_line_earns_no_edge_of_its_own():
    """The RC-B generalization of LFS108, asserted from the multi-anchor
    side: with carriers at two UNCLAIMED lines plus one claimed line, the
    claimed line is the only one that must not appear — the two real
    occurrences both do (R44: cover all occurrences)."""
    subq = "subq"
    claimed = _edge(SRC, subq, "FILTER", 41, 26, field_like=True)
    own_a = _edge(SRC, subq, "FILTER", 48, 26)
    own_b = _edge(SRC, subq, "FILTER", 52, 26)
    join = _edge(SRC, subq, "JOIN", 41, 26)

    out = _combine_edges([claimed, own_a, own_b, join], {subq: 13})

    assert _anchors(out) == {("FILTER", 48), ("FILTER", 52), ("JOIN", 41)}
    assert ("FILTER", 41) not in _anchors(out)


# ── node_lines=None: the two direct callers' contract ──────────────────

def test_node_lines_none_keeps_plain_first_carrier_wins():
    """`node_lines=None` -> no Fix-H pass and no keeper-line rule: the first
    carrier of an anchor group keeps its carried info. RC-B still splits the
    distinct occurrence lines (the fold's semantics, not a `node_lines`
    feature) — the two direct callers see the same split, they only skip the
    chip-line guards."""
    claimed, unclaimed, chip, join = _carrier_set()

    out = _combine_edges([claimed, unclaimed, chip, join])

    assert len(out) == 4
    assert _anchors(out) == {("REF", 41), ("REF", 48), ("REF", CHIP_LINE),
                             ("JOIN", 41)}
    by_line = {(e["edge_type"], e["_src_line"]): e for e in out}
    assert by_line[("REF", 41)] is claimed
    assert by_line[("REF", 48)] is unclaimed
    assert by_line[("REF", CHIP_LINE)] is chip
    assert by_line[("REF", 41)]["label"] == "REF"


def test_labels_still_fold_across_carriers():
    """The combine half of Phase 5 is untouched: every carrier of ONE anchor
    group folds its label into the surviving edge. Chip line 999 names no
    carrier here, so plain first-carrier-wins holds within the group and
    the fold is directly observable."""
    a = _ref(SRC, TGT, 41, 41)
    b = _ref(SRC, TGT, 41, 41)
    b["label"] = "REF (occurrence)"

    out = _combine_edges([a, b], {TGT: 999})

    assert len(out) == 1
    assert out[0]["_src_line"] == 41
    assert out[0]["label"] == "REF, REF (occurrence)"


# ── RC-B: the multi-anchor contract itself ─────────────────────────────

def test_two_occurrence_lines_serve_two_edges_sorted_by_line():
    """The defect: N occurrences of one field reaching one target under ONE
    type. Two carriers at lines 48 and 88 -> two served edges, emitted in
    ascending line order regardless of carrier order, each stamped with the
    anchor its group was keyed on (`_fold_anchor`, consumed by the Phase 9
    dedup) and carrying a DISTINCT id (the raw id is pair-derived, so the
    split carriers must not collide on it)."""
    a = _ref(SRC, TGT, 88, 88)
    b = _ref(SRC, TGT, 48, 48)

    out = _combine_edges([a, b], {TGT: 7})

    assert len(out) == 2
    assert [e["_src_line"] for e in out] == [48, 88]          # sorted by line
    assert [e["_fold_anchor"] for e in out] == [48, 88]
    assert out[0]["id"] != out[1]["id"]

    out_rev = _combine_edges([b, a], {TGT: 7})
    assert [e["_src_line"] for e in out_rev] == [48, 88]      # order-independent
    assert [e["id"] for e in out_rev] == [e["id"] for e in out]


def test_dml_rewrite_id_suffixes_survive_the_split_reid():
    """The DML rewrite suffixes (`*_dml_out`, `*_value`) are payload
    contract keys (flow-role / benchmark matching): a split carrier that
    needs a fresh id keeps its suffix."""
    a = _edge(SRC, TGT, "TABLE_FLOW", 48, 48)
    a["id"] = "l2e_abc_def_dml_out"
    b = _edge(SRC, TGT, "TABLE_FLOW", 88, 88)
    b["id"] = "l2e_abc_def_dml_out"

    out = _combine_edges([a, b], {TGT: 7})

    assert len(out) == 2
    assert out[0]["id"].endswith("_dml_out")
    assert out[1]["id"].endswith("_dml_out")
    assert out[0]["id"] != out[1]["id"]
