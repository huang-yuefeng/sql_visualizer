"""Flow-only line invariants (user requirement, 2026-08-27; R43 2026-08-28).

For a searched table.field, the downstream Flow-only closure must satisfy:

  INV-1  every SQL line that references the target field AS A DATA REFERENCE
         (DML contexts — INSERT/SELECT/WHERE) carries at least one closure
         edge anchored on that line.

  INV-2  every closure edge is assigned a SQL line (highlight_line is an
         integer >= 1). Edges without lines are unanchorable in the SQL
         panel and unrenderable in the merged views (R32 rule 5).

R43 (2026-08-28, task #384, user ruling): partition-DDL statements
(`ALTER TABLE … ADD PARTITION`) are dropped from the L2 graph entirely —
"they are folder names, not dataflow." There is no DDL exception to INV-1
anymore: those statement frames never enter the graph, so the test asserts
no closure edge anchors on a partition-DDL line — the R43 regression guard
(frames or edges reappearing there fails loudly).

Fixture: EAST5_STZFXXB_M.sql, search east5_stzfxxb.p_dt, downstream.
"""

import io
import re
import zipfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(BACKEND_DIR))

from app.services.dataflow_service import get_level2_graph
from app.services.workspace_service import create_workspace, delete_workspace

SCRIPT = "EAST5_STZFXXB_M.sql"
SAMPLE = (BACKEND_DIR.parent / "samples" / "sql_sample_v1" / SCRIPT)
TABLE, FIELD = "east5_stzfxxb", "p_dt"
# DDL lines are exactly the ALTER TABLE … ADD PARTITION statements (R43:
# their statement frames are dropped from the L2 graph — folder names, not
# dataflow — so a field reference there never produces a closure edge).
DDL_LINE = re.compile(r"^\s*ALTER\s+TABLE\b", re.IGNORECASE)


def _closure(tmp_ws_factory):
    sql = SAMPLE.read_text()
    ws_id = tmp_ws_factory(SCRIPT, sql)
    try:
        resp = get_level2_graph(ws_id, "auto", "sql_sample_v1/" + SCRIPT,
                                TABLE, FIELD, True, "downstream")
        assert "graph" in resp, resp.get("error")
        return sql, resp["graph"]
    finally:
        delete_workspace(ws_id)


def _make_ws_factory():
    def factory(name, sql):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("sql_sample_v1/" + name, sql)
        return create_workspace(buf.getvalue())
    return factory


def test_inv2_every_closure_edge_has_a_sql_line():
    _, graph = _closure(_make_ws_factory())
    lineless = [e["data"] for e in graph["edges"]
                if not isinstance(e["data"].get("highlight_line"), int)
                or e["data"]["highlight_line"] < 1]
    assert not lineless, (
        "INV-2 violated — closure edges without a SQL line "
        "(unanchorable in the SQL panel, unrenderable in merged views): "
        f"{[(d.get('source'), d.get('edge_type')) for d in lineless]}")


def test_inv1_every_dml_field_line_has_an_edge_and_ddl_stays_excluded():
    sql, graph = _closure(_make_ws_factory())
    lines = sql.splitlines()
    field_lines = [i + 1 for i, t in enumerate(lines)
                   if re.search(r"\b%s\b" % re.escape(FIELD), t, re.IGNORECASE)]
    assert field_lines, "fixture lost its target-field references"

    edge_lines = {e["data"].get("highlight_line") for e in graph["edges"]}

    # R43 guard sanity: the fixture must actually contain partition-DDL
    # lines that reference the target field — otherwise `ddl_covered` is
    # trivially empty and the guard below silently stops testing.
    ddl_field_lines = [ln for ln in field_lines
                       if DDL_LINE.match(lines[ln - 1])]
    assert ddl_field_lines, \
        "fixture lost its ALTER TABLE … p_dt lines — the R43 guard is vacuous"

    dml_uncovered, ddl_covered = [], []
    for ln in field_lines:
        if DDL_LINE.match(lines[ln - 1]):
            # R43 regression guard: partition-DDL statement frames are
            # dropped from the L2 graph entirely — no closure edge may
            # anchor on an ALTER line. An edge here means the frames
            # regressed into the display; surface it, never silently pass.
            if ln in edge_lines:
                ddl_covered.append(ln)
        elif ln not in edge_lines:
            dml_uncovered.append(ln)

    assert not dml_uncovered, (
        "INV-1 violated — DML lines referencing the searched field carry no "
        f"closure edge: {dml_uncovered}")
    assert not ddl_covered, (
        "R43 violated — partition-DDL (ALTER TABLE … ADD PARTITION) frames "
        f"reappeared in the L2 graph (folder names, not dataflow): "
        f"{ddl_covered}")
