"""Unit tests for `_combine_edges` (l2_builder Phase 5) carrier preference.

Covers the two 2026-08-29 adjudications:

Fix B — the keeper-line rule treats line 0 as invalid. `node_lines`
values are `line_start` integers and 0 means "no SQL line" (a TVF alias,
a synthetic frame); a chip sitting at line 0 must never pull the anchor
onto a carrier merely because that carrier's target line matched 0 — a
non-relationship site. `want` is an int >= 0 or None, so a plain truthy
test excludes both.

Fix C — R45 Fix H is decided over the WHOLE carrier set, before the
combine loop, instead of only over carriers[1:]. The loop-side guard
never saw the first carrier, and the LFS108 residual latched `keepers`
for it, so a Fix-H carrier sitting in slot 0 (or merely ahead of the
chip-line carrier) lost its anchor and stayed locked out for good. The
latch is load-bearing: when carriers[0] IS the Fix-H carrier no swap is
visible, but the latch still stops the residual branch from stripping it.

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


# ── Fix B: a chip at line 0 is not a relationship site ─────────────────

def test_fix_b_chip_at_line_zero_never_steals_the_anchor():
    """`[{REF @41->41}, {REF @88->0}]` with chip line 0 -> the keeper keeps
    its own `_src_line` 41, so the highlight stays on line 41."""
    src, tgt = "SUP_M", "tag_branch"
    keeper = _ref(src, tgt, 41, 41)
    mis_anchor = _ref(src, tgt, 88, 0)

    out = _combine_edges([keeper, mis_anchor], {tgt: 0})

    assert len(out) == 1
    assert out[0]["_src_line"] == 41
    assert out[0]["_tgt_line"] == 41


def test_fix_b_chip_at_line_zero_is_a_refusal_not_a_reordering():
    """The same guard runs in the pre-loop Fix-H pass: a line-0 chip builds
    no `fix_h` entry. Fix B only REFUSES to let the line-0 carrier win —
    it never promotes it, so when the line-0 carrier arrives first,
    first-carrier-wins still holds and it keeps the anchor."""
    src, tgt = "SUP_M", "tag_branch"
    keeper = _ref(src, tgt, 41, 41)
    mis_anchor = _ref(src, tgt, 88, 0)

    # Reverse order: the line-0 carrier arrives FIRST.
    out = _combine_edges([mis_anchor, keeper], {tgt: 0})

    assert len(out) == 1
    assert out[0]["_src_line"] == 88
    assert out[0]["_tgt_line"] == 0


# ── Fix C: Fix H over the whole carrier set ────────────────────────────

SRC, TGT = "lending_ref", "SUBQ_OUT"
CHIP_LINE = 7


def _carrier_set():
    """One folded (source, target, REF) key with three carriers.

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
    """Carriers [claimed@41, unclaimed@48, chip@7] -> the anchor is 7.

    This order is where the old loop-side ordering actually failed: the
    residual branch adopted `unclaimed@48` first and latched `keepers`,
    so the chip carrier arriving third was locked out (anchor 48)."""
    claimed, unclaimed, chip, join = _carrier_set()

    out = _combine_edges([claimed, unclaimed, chip, join], {TGT: CHIP_LINE})

    assert len(out) == 2
    by_type = {e["edge_type"]: e for e in out}
    assert by_type["REF"]["_src_line"] == CHIP_LINE
    assert by_type["JOIN"]["_src_line"] == 41


def test_fix_c_reverse_order_anchors_the_chip_line_too():
    """The mirrored carrier order [chip@7, unclaimed@48, claimed@41] also
    anchors at 7 — order independence is the whole point of Fix C."""
    claimed, unclaimed, chip, join = _carrier_set()

    out = _combine_edges([chip, unclaimed, claimed, join], {TGT: CHIP_LINE})

    assert len(out) == 2
    by_type = {e["edge_type"]: e for e in out}
    assert by_type["REF"]["_src_line"] == CHIP_LINE


def test_fix_c_first_carrier_is_the_fix_h_carrier_stays_latched():
    """Carriers [chip@7, later@41] -> 7.

    carriers[0] IS the Fix-H carrier, so no swap is ever visible — but the
    unconditional `keepers` latch must still fire, otherwise the residual
    branch below strips the chip line for the shared-line-7 JOIN claim."""
    chip = _ref(SRC, TGT, CHIP_LINE, CHIP_LINE, field_like=True)
    later = _ref(SRC, TGT, 41, 41)
    # Line 7 is shared with a JOIN on the same pair: with the latch missing
    # the residual branch sees the keeper as "claimed together" and swaps.
    join = _edge(SRC, TGT, "JOIN", CHIP_LINE, CHIP_LINE)

    out = _combine_edges([chip, later, join], {TGT: CHIP_LINE})

    assert len(out) == 2
    by_type = {e["edge_type"]: e for e in out}
    assert by_type["REF"]["_src_line"] == CHIP_LINE
    assert by_type["JOIN"]["_src_line"] == CHIP_LINE


def test_fix_c_lfs108_three_filter_carriers_still_anchor_48():
    """LFS108's exact shape is untouched: three FILTER carriers of
    `lending_ref -> ⟐subq` (@41 the JOIN-key occurrence, @48 twice) with
    the chip at 13 — no carrier names line 13, so Fix H never fires and the
    residual still yields the anchor to the line this relationship owns."""
    subq = "subq"
    c41 = _edge(SRC, subq, "FILTER", 41, 26, field_like=True)
    c48a = _edge(SRC, subq, "FILTER", 48, 26)
    c48b = _edge(SRC, subq, "FILTER", 48, 26)
    join = _edge(SRC, subq, "JOIN", 41, 26)

    out = _combine_edges([c41, c48a, c48b, join], {subq: 13})

    assert len(out) == 2
    by_type = {e["edge_type"]: e for e in out}
    assert by_type["FILTER"]["_src_line"] == 48
    assert by_type["JOIN"]["_src_line"] == 41


# ── node_lines=None: the two direct callers' contract ──────────────────

def test_node_lines_none_keeps_plain_first_carrier_wins():
    """`node_lines=None` -> no Fix-H pass and no keeper-line rule: the first
    carrier of a key keeps its carried info (byte-identical to the previous
    behaviour for test_l1_l2_integration and test_physical_model_equivalence)."""
    claimed, unclaimed, chip, join = _carrier_set()

    out = _combine_edges([claimed, unclaimed, chip, join])

    assert len(out) == 2
    by_type = {e["edge_type"]: e for e in out}
    # No swap at all — the first carrier wins, labels still fold.
    assert by_type["REF"]["_src_line"] == 41
    assert by_type["REF"]["_tgt_line"] == 41
    assert by_type["REF"]["label"] == "REF"


def test_labels_still_fold_across_carriers():
    """The combine half of Phase 5 is untouched: every carrier's label folds
    into the surviving edge. Chip line 999 names no carrier here, so plain
    first-carrier-wins holds and the fold is directly observable."""
    a = _ref(SRC, TGT, 41, 41)
    b = _ref(SRC, TGT, 48, 48)
    b["label"] = "REF (occurrence)"

    out = _combine_edges([a, b], {TGT: 999})

    assert len(out) == 1
    assert out[0]["_src_line"] == 41
    assert out[0]["label"] == "REF, REF (occurrence)"
