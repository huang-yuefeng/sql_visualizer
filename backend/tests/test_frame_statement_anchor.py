"""THE FRAME STATEMENT ANCHOR — an ⟐ output frame carries ITS OWN statement's line.

THE DEFECT (Team REVIEW-L2 + VERIFY-199, extractor 2026-08-28.14)
=================================================================
An ⟐ output frame compound's ``line_start`` could belong to a DIFFERENT
statement than the frame's own context/edges. Measured on
``BDM_ACC_LOAN_INFO_RFN.sql``: the frame whose context is TOP1 (the
statement at line 1168) carried ``line_start = 1429`` while the frame whose
context is TOP2 (the statement at line 1429) carried ``line_start = 1168`` —
the two frames had swapped lines.

ROOT CAUSE
----------
The frame VT's line is its def-site resolution in ``_add``. For a
statement-level frame that resolution anchors on ``_statement_anchor`` of the
enclosing DML node, and ``_statement_anchor`` matches the node's RENDERED
head against the source token stream. sqlglot's Insert node has no argument
for the Hive/ODPS ``TABLE`` keyword, so ``INSERT INTO TABLE t`` renders
``INSERT INTO t`` in EVERY dialect and the head never matches the stream —
the statement anchored 0. The def-site floor then fell back to
``_stmt_anchor_for(context)``, which is LAST-WINS (I1) and had been
overwritten by the body SELECT's walk, so the range floor was one line PAST
the DML keyword and the full head could not match inside it. The generic
2-token run (``head_run[:2]`` = ``["insert", "into"]``, W6's own
render-dropped-keyword mitigation) then matched whichever OTHER statement's
INSERT came next in the stream — the swap.

THE FIX (extractor 2026-08-28.15)
---------------------------------
``_statement_anchor`` also tries the source-faithful spelling
(``insert into table …``) after the plain head, so the DML statement anchors
on its OWN keyword line. The frame's def-site floor is then the statement's
own line and the frame carries it. The context → statement line is published
as ``ExtractionResult.statement_anchor_lines`` (the statement IDENTITY —
``_stmt_anchor_lines`` stays LAST-WINS as the def-site RANGE floor and
deliberately differs: RFN TOP1 records 1168 there, not the SELECT's 1169).

Downstream this is what makes ``l2_builder._apply_field_involvement``'s
statement-level frame test STRONG instead of worked-around: ``own_frame_keys``
is built from ``(frame_label, frame_line)`` pairs read off the edges' carried
``_tgt_line``, and before the fix two frames of one script could share a line
(RFN 1429), so the test compared different statements by construction.

Corpus: ``sql_sample_v1`` + ``tpcds_qualified`` — the L2 snapshot harness's
own script set (the flagship frame-heavy scripts are all in ``sql_sample_v1``).
The wider workspace corpus was measured separately: 338 scripts / 457
⟐ output frames, 6 frames outside their own statement before the fix, 0 after.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.extractor.variable_extractor_v2 import (
    EXTRACTOR_VERSION,
    extract_variables_from_sql,
)

# The same path convention test_l2_snapshot.py uses.
BACKEND_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = BACKEND_DIR.parent / "samples"

# The snapshot harness's corpus (deterministic, repo-shipped).
_CORPUS_DIRS = ("sql_sample_v1", "tpcds_qualified")
MAX_SCRIPTS = 120

# W6: the synthetic frame name — "⟐ output" exactly when the context is a
# bare statement context (CTE{…} labels the CTE, ":join:" the derived alias,
# "/" the subquery), so this name IS the statement-level frame family.
FRAME_NAME = "⟐ output"

# The DML keywords whose output frame must anchor on the statement's own
# keyword line. MERGE/CREATE are deliberately excluded: their frame is the
# USING/body SELECT's own line, inside the statement but not at its head.
_DML_STATEMENTS = ("INSERT", "UPDATE", "DELETE")


def _collect_scripts() -> list[tuple[str, str]]:
    scripts: list[tuple[str, str]] = []
    for d in _CORPUS_DIRS:
        base = SAMPLES_DIR / d
        if not base.exists():
            continue
        for p in sorted(base.glob("*.sql")):
            scripts.append((p.name, p.read_text(encoding="utf-8")))
    if not scripts:
        raise FileNotFoundError(f"no sample scripts under {SAMPLES_DIR}")
    return scripts[:MAX_SCRIPTS]


_SCRIPTS = _collect_scripts()


def _frames(result):
    """[(context, line_start)] of the script's statement-level frames."""
    return [
        (v.context, int(v.line_start or 0))
        for v in result.variables
        if str(getattr(v.variable_type, "value", v.variable_type)) == "virtual_table"
        and v.name == FRAME_NAME
    ]


def _statement_keyword(sql_text: str, line: int) -> str:
    """First keyword-ish token of `line`, comment lines skipped upward."""
    lines = sql_text.split("\n")
    while 0 < line <= len(lines):
        text = lines[line - 1].strip()
        if text and not text.startswith("--") and not text.startswith("#"):
            return text.split(None, 1)[0].strip("(").upper()
        line -= 1
    return ""


def _extract(sql_text: str, name: str):
    return extract_variables_from_sql(sql_text, name)


# ═══════════════════════════════════════════════════════════════════════
# the corpus pin — per-frame context → statement membership
# ═══════════════════════════════════════════════════════════════════════

def test_every_frame_line_is_inside_its_own_statement():
    """Every ⟐ output frame's line lies inside the statement its context
    names: [that statement's own anchor, the next statement's anchor).

    Before the fix RFN's TOP2 frame sat at 1168 — a line of TOP1's
    statement, outside its own [1430, …) span — and EAST5's TOP11 frame sat
    at 179 against an own span starting at 180."""
    checked = 0
    violations: list[str] = []
    for name, sql in _SCRIPTS:
        result = _extract(sql, name)
        anchors = result.statement_anchor_lines
        items = list(anchors.items())
        for ctx, line in _frames(result):
            own = [l for c, l in items
                   if ctx == c or ctx.startswith(c + "/") or ctx.startswith(c + ":")]
            if not own:
                continue  # the statement never anchored (never a swap risk)
            lo = min(own)
            others = sorted(l for c, l in items
                            if not (ctx == c or ctx.startswith(c + "/")
                                    or ctx.startswith(c + ":")) and l > lo)
            hi = others[0] if others else 10 ** 9
            checked += 1
            if not lo <= line < hi:
                violations.append(
                    f"{name}: {FRAME_NAME} ctx={ctx} line={line} "
                    f"outside its own statement span [{lo},{hi})")
    assert checked > 100, f"corpus produced only {checked} anchored frames"
    assert not violations, (
        f"{len(violations)} frame(s) carry another statement's line:\n  "
        + "\n  ".join(violations))


def test_dml_write_frame_carries_the_statement_anchor_line():
    """The reported family: a frame of an INSERT/UPDATE/DELETE statement
    carries the statement's OWN keyword line — never another statement's.

    The frame's line is what an edge carries as ``_tgt_line``, so a frame on
    a foreign statement's line is what let two frames of one script share a
    line (RFN 1429) and made l2_builder's statement-level frame test compare
    different statements by construction."""
    checked = 0
    bad: list[str] = []
    for name, sql in _SCRIPTS:
        result = _extract(sql, name)
        anchors = result.statement_anchor_lines
        for ctx, line in _frames(result):
            if ctx not in anchors:
                continue
            keyword = _statement_keyword(sql, anchors[ctx])
            if keyword not in _DML_STATEMENTS:
                continue
            checked += 1
            if line != anchors[ctx]:
                bad.append(f"{name}: {ctx} frame@{line} != statement@{anchors[ctx]}")
    assert not bad, (
        f"{len(bad)} DML write frame(s) off their own statement anchor:\n  "
        + "\n  ".join(bad))
    assert checked > 5, f"corpus produced only {checked} DML write frames"


# ═══════════════════════════════════════════════════════════════════════
# the measured swap — BDM_ACC_LOAN_INFO_RFN.sql
# ═══════════════════════════════════════════════════════════════════════

def test_rfn_frames_carry_their_own_statement_lines():
    """RFN's three statements: ⟐output@867 (INSERT OVERWRITE TABLE), the
    frame of the statement at 1168 (``INSERT INTO TABLE bdm_acc_loan_info``)
    and the frame of the job-log statement at 1429. Before the fix the two
    ``INSERT INTO TABLE`` frames carried each OTHER's line (TOP1 1429, TOP2
    1168) because the render drops the TABLE keyword and both statements
    anchored 0."""
    name = "BDM_ACC_LOAN_INFO_RFN.sql"
    sql = (SAMPLES_DIR / "sql_sample_v1" / name).read_text(encoding="utf-8")
    result = _extract(sql, name)
    frames = dict(_frames(result))
    assert set(frames) == {"TOP0", "TOP1", "TOP2"}, sorted(frames)
    assert frames["TOP0"] == 867, frames
    assert frames["TOP1"] == 1168, (
        f"RFN TOP1 frame is @L{frames['TOP1']} — the job-log statement's "
        f"line, not its own INSERT INTO TABLE @1168 (the swap)")
    assert frames["TOP2"] == 1429, (
        f"RFN TOP2 frame is @L{frames['TOP2']} — the back-fill statement's "
        f"line, not its own job-log INSERT @1429 (the swap)")
    # the published statement identity agrees, so the frame line IS the
    # statement's own line and no two frames of one script share one
    assert result.statement_anchor_lines["TOP1"] == frames["TOP1"]
    assert result.statement_anchor_lines["TOP2"] == frames["TOP2"]
    assert len(set(frames.values())) == len(frames), (
        f"two statements' frames share a line: {frames}")


def test_east5_job_log_frame_carries_its_own_line():
    """EAST5's TOP11 job-log statement (``INSERT INTO TABLE
    rrcdm_job_log_exec_par(…)`` @179) keeps its frame at 179 — the line its
    legs carry — while the searched table's own write frame stays @41."""
    name = "EAST5_STZFXXB_M.sql"
    sql = (SAMPLES_DIR / "sql_sample_v1" / name).read_text(encoding="utf-8")
    result = _extract(sql, name)
    frames = dict(_frames(result))
    assert frames.get("TOP0") == 41, frames
    assert frames.get("TOP11") == 179, (
        f"EAST5 TOP11 (the job-log INSERT @179) frame is @L{frames.get('TOP11')}")
    assert result.statement_anchor_lines["TOP11"] == 179
    assert len(set(frames.values())) == len(frames), (
        f"two statements' frames share a line: {frames}")


# ═══════════════════════════════════════════════════════════════════════
# the mechanism — two INSERT INTO TABLE statements in one script
# ═══════════════════════════════════════════════════════════════════════

def test_two_insert_into_table_statements_keep_their_own_frames():
    """The smallest reproduction of the swap: two ``INSERT INTO TABLE``
    statements whose renders drop the TABLE keyword. Each statement's frame
    must carry ITS OWN INSERT line — before the fix the second statement's
    generic 2-token run matched the first statement's INSERT (or the reverse)."""
    sql = (
        "-- first write\n"
        "INSERT INTO TABLE alpha_part PARTITION (data_dt = '1')\n"
        "SELECT a.cust_no FROM src_a a;\n"
        "\n"
        "-- second write\n"
        "INSERT INTO TABLE beta_part PARTITION (data_dt = '2')\n"
        "SELECT b.cust_no FROM src_b b;\n"
    )
    result = _extract(sql, "frame_swap_probe.sql")
    frames = dict(_frames(result))
    assert set(frames) == {"TOP0", "TOP1"}, sorted(frames)
    assert frames["TOP0"] == 2, (
        f"first statement's frame is @L{frames['TOP0']}, expected its own "
        f"INSERT @2")
    assert frames["TOP1"] == 6, (
        f"second statement's frame is @L{frames['TOP1']}, expected its own "
        f"INSERT @6 (the two statements swapped)")
    assert result.statement_anchor_lines["TOP0"] == 2
    assert result.statement_anchor_lines["TOP1"] == 6


# ═══════════════════════════════════════════════════════════════════════
# the published statement identity
# ═══════════════════════════════════════════════════════════════════════

def test_statement_anchor_lines_are_published_and_sane():
    """``statement_anchor_lines`` carries one line per bare statement
    context, every line ≥ 1, ascending with the statement index — the
    identity the frames above are pinned against."""
    for name, sql in _SCRIPTS:
        result = _extract(sql, name)
        tops = {c: l for c, l in result.statement_anchor_lines.items()
                if c.startswith("TOP") and c[3:].isdigit()}
        for c, l in tops.items():
            assert isinstance(l, int) and l >= 1, (name, c, l)
        ordered = [tops[f"TOP{i}"] for i in range(len(tops)) if f"TOP{i}" in tops]
        assert ordered == sorted(ordered), (name, ordered)


def test_extractor_version_bumped_for_the_frame_anchor():
    """The frame anchor changes EXTRACTION output (frame lines and the DML
    statements' anchors), so version-matched caches must invalidate."""
    assert EXTRACTOR_VERSION >= "2026-08-28.15", (
        f"EXTRACTOR_VERSION is {EXTRACTOR_VERSION!r} — the frame statement "
        f"anchor changes extraction output and must keep the version past .14")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
