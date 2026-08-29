"""K4 adjudicated rulings implemented by fix team F-B1 (2026-08-28).

Covers the four rulings + the two follow-ups that landed in this batch:

  Ruling 1 (item 1)  — L2 field chips carry `line_start` (their variable's
                       I1 definition line) so an L2 node click lights the
                       definition; `line_end` is deliberately ABSENT (it
                       would re-route pickAutoEdge's priority-1 seed-zone
                       pick, frontend/src/utils/pickAutoEdge.js).
  Ruling 3 (item 2)  — the structural paren-balance check: ErrorLevel.IGNORE
                       recovers a partial tree from almost anything, so a
                       genuinely broken script reported `parse_errors: []`
                       and design rule 23's banner never fired. Extraction
                       NEVER rejects — diagnostics only.
  Ruling 4 (item 3)  — the direction default flip: omitted AND legacy
                       "upstream" coerce to "downstream"; only values
                       outside {upstream, downstream} 400.
  S4 (item 4)        — the not-in-flow banner names the truthful reason
                       (outside the searched field's downstream flow), never
                       the false "the field is not queried in this script".
  F-A follow-up (item 5) — the L2/L1 seed matching is CASE-INSENSITIVE:
                       after F-A's search union a script that wrote the
                       field in another case rendered search_matched:false
                       and lost every is_target chip.

Fixtures follow the test_search_case_insensitive.py pattern (zip-upload a
workspace, index, drive the service layer directly).
"""

import asyncio
import inspect
import io
import sys
import zipfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.dataflow_service import (  # noqa: E402
    _build_l2_graph,
    create_search,
    get_level2_graph,
)
from app.services.folder_index_service import index_scripts  # noqa: E402
from app.services.workspace_service import (  # noqa: E402
    delete_workspace,
    get_workspace_dir,
)


def _make_ws(entries: dict) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, sql in entries.items():
            zf.writestr(name, sql)
    from app.services.workspace_service import create_workspace
    return create_workspace(buf.getvalue())


def _indexed_ws(entries: dict):
    ws_id = _make_ws(entries)
    names = list(entries)
    index_scripts(ws_id, names)
    return ws_id


def _search(ws_id, table, field, direction="downstream"):
    cache_dir = get_workspace_dir(ws_id) / "cache"
    import json
    ti = json.loads((cache_dir / "table_index.json").read_text())
    fi = json.loads((cache_dir / "field_index.json").read_text())
    return asyncio.run(create_search(ws_id, table, field, ti, fi,
                                     direction=direction))


# The case-split fixture (the S1 example): one column written lowercase in
# one script and uppercase in the next, the table's casing flipping too.
PL_SQL = (
    "INSERT OVERWRITE TABLE bdm_tgt PARTITION(p_dt='2024')\n"
    "SELECT a.dm_flag2 AS dm_flag2 FROM bdm_src a;\n"
)
DL_SQL = (
    "INSERT OVERWRITE TABLE bdm_tgt PARTITION(p_dt='2024')\n"
    "SELECT B.DM_FLAG2 AS DM_FLAG2 FROM BDM_SRC B;\n"
)

# Two-statement script for the chip-def-line test: `dm_flag2` is written in
# statement 1 and read again in statement 2 — the keeper chip anchors at the
# FIRST occurrence's line.
TWO_STMT_SQL = (
    "INSERT OVERWRITE TABLE bdm_tgt PARTITION(p_dt='2024')\n"
    "SELECT a.dm_flag2 AS dm_flag2, a.acct_no FROM bdm_src a;\n"
    "\n"
    "INSERT OVERWRITE TABLE bdm_out PARTITION(p_dt='2024')\n"
    "SELECT t.dm_flag2 FROM bdm_tgt t;\n"
)

# A deliberately BROKEN script: the subquery's ')' is missing, so the first
# statement never closes — ErrorLevel.IGNORE still recovers a partial tree.
BROKEN_SQL = (
    "SELECT a.acct_no, sum(b.amt) AS total_amt\n"
    "FROM src_tbl a\n"
    "LEFT JOIN dim_tbl b ON a.acct_no = b.acct_no\n"
    "WHERE a.acct_no IN (SELECT c.acct_no FROM pick_tbl c\n"
    "GROUP BY a.acct_no;\n"
)


# ════════════════════════════════════════════════════════════════════════
# K4 ruling 1 — field chips carry line_start (never line_end)
# ════════════════════════════════════════════════════════════════════════

class TestFieldChipLineStart:
    def test_every_field_chip_carries_line_start(self):
        ws_id = _indexed_ws({"two_stmt.sql": TWO_STMT_SQL})
        try:
            res = _build_l2_graph(ws_id, "two_stmt.sql", TWO_STMT_SQL,
                                  "bdm_src", "dm_flag2")
            # R4 L (2026-08-29): the old `assert res.get("error") is None`
            # was a tautology — `_build_l2_graph` never emits an `error` key
            # (it returns {nodes, edges, ...} or raises), so the assert could
            # not fail. The chip guards below are the real contract.
            fields = [n["data"] for n in res["nodes"]
                      if n["data"].get("type") == "field"]
            assert fields, res
            for f in fields:
                assert isinstance(f.get("line_start"), int), f
                assert f["line_start"] >= 1, f
        finally:
            delete_workspace(ws_id)

    def test_field_chip_never_carries_line_end(self):
        """line_end would re-route pickAutoEdge's priority-1 seed-zone pick
        (it requires BOTH endpoints on the is_target node) — the ruling
        forbids it on chips."""
        ws_id = _indexed_ws({"two_stmt.sql": TWO_STMT_SQL})
        try:
            res = _build_l2_graph(ws_id, "two_stmt.sql", TWO_STMT_SQL,
                                  "bdm_src", "dm_flag2")
            # R4 L (2026-08-29): without this guard the loop below can be
            # vacuous — a builder that emitted zero field chips passed.
            fields = [n["data"] for n in res["nodes"]
                      if n["data"].get("type") == "field"]
            assert fields, res
            for f in fields:
                assert "line_end" not in f, f
        finally:
            delete_workspace(ws_id)

    def test_seed_chip_anchors_at_first_occurrence_line(self):
        """Keeper = first occurrence (the existing dedup convention): the
        searched field is written at line 2 (statement 1) and read again at
        line 5 (statement 2) — the chip on the searched table's own compound
        carries 2, never 5. (The write-projection copies on the write-target
        compounds legitimately carry their own statement's line.)"""
        ws_id = _indexed_ws({"two_stmt.sql": TWO_STMT_SQL})
        try:
            res = _build_l2_graph(ws_id, "two_stmt.sql", TWO_STMT_SQL,
                                  "bdm_src", "dm_flag2")
            src_keeper = next(n["data"]["id"] for n in res["nodes"]
                              if n["data"].get("type") == "source_table"
                              and n["data"].get("table_name") == "bdm_src")
            seed = next(n["data"] for n in res["nodes"]
                        if n["data"].get("type") == "field"
                        and n["data"].get("is_target")
                        and n["data"].get("parent") == src_keeper)
            assert seed["label"] == "dm_flag2", seed
            assert seed["line_start"] == 2, seed
        finally:
            delete_workspace(ws_id)

    def test_chip_line_lights_the_definition_via_level2_response(self):
        """The served L2 response (what the R37 click channel consumes)
        carries the same chip lines."""
        ws_id = _indexed_ws({"two_stmt.sql": TWO_STMT_SQL})
        try:
            sr = _search(ws_id, "bdm_src", "dm_flag2")
            res = get_level2_graph(ws_id, sr["view_id"], "two_stmt.sql",
                                   "bdm_src", "dm_flag2")
            fields = [n["data"] for n in res["graph"]["nodes"]
                      if n["data"].get("type") == "field"]
            assert fields, res
            assert all(isinstance(f.get("line_start"), int)
                       and f["line_start"] >= 1 for f in fields), fields
        finally:
            delete_workspace(ws_id)


# ════════════════════════════════════════════════════════════════════════
# K4 ruling 3 — structural paren-balance parse_errors
# ════════════════════════════════════════════════════════════════════════

class TestParenBalanceErrors:
    def test_unclosed_paren_reported_with_script_line(self):
        from app.extractor.variable_extractor_v2 import _paren_balance_errors
        sql = ("SELECT a FROM (\n"
               "SELECT b FROM t\n"
               "WHERE c IN (SELECT d FROM u;\n"
               "SELECT 1;")
        errs = _paren_balance_errors(sql, "hive", 2)
        assert len(errs) == 1, errs
        assert errs[0]["stmt_idx"] == 0, errs
        assert "2 '(' left open" in errs[0]["detail"], errs
        # L = the split's FIRST-token line (original script numbering).
        assert "(script line 1)" in errs[0]["detail"], errs
        assert "graph may be incomplete" in errs[0]["detail"], errs

    def test_balanced_script_reports_nothing(self):
        from app.extractor.variable_extractor_v2 import _paren_balance_errors
        assert _paren_balance_errors("SELECT a FROM t WHERE b IN (1, 2);",
                                     "mysql", 1) == []

    def test_strings_and_comments_do_not_count(self):
        """The tokenizer pass is string/comment aware: parens inside either
        never count toward the balance."""
        from app.extractor.variable_extractor_v2 import _paren_balance_errors
        sql = ("SELECT ')' AS close_only, '-- fake (' AS c1 FROM t; -- ( (\n"
               "SELECT 1;")
        assert _paren_balance_errors(sql, "mysql", 2) == []

    def test_extra_close_paren_not_reported_here(self):
        """A dangling ')' leaves a real hole in sqlglot's statement list —
        the None-hole record owns that diagnostic; net<0 is not a
        paren-balance finding."""
        from app.extractor.variable_extractor_v2 import _paren_balance_errors
        assert _paren_balance_errors("SELECT 1;\n);\n", "mysql", 2) == []

    def test_split_index_maps_through_offset(self):
        """Preprocessing drops leading SET statements, so the tokenizer may
        split MORE statements than sqlglot parsed (here 2 splits vs 1 parsed
        statement) — the tail alignment (offset = 1) maps the broken split
        onto parsed statement 0, and the SET split (stmt_idx -1) is skipped."""
        from app.extractor.variable_extractor_v2 import _paren_balance_errors
        sql = "SET hive.exec.dynamic.partition=true;\nSELECT a FROM (SELECT b FROM t;"
        errs = _paren_balance_errors(sql, "hive", 1)
        assert len(errs) == 1, errs
        assert errs[0]["stmt_idx"] == 0, errs
        assert "(script line 2)" in errs[0]["detail"], errs

    def test_extraction_never_rejects_and_records_error(self):
        """The banner contract (design rule 23): a genuinely broken script
        reports the paren diagnostic — extraction still completes (the
        recovered partial tree still walks)."""
        from app.extractor.adapter import run_full_analysis
        result = run_full_analysis(BROKEN_SQL, "broken.sql")
        assert result.get("variables") is not None, result
        errs = result.get("parse_errors")
        assert errs, result.get("parse_errors")
        assert any("unbalanced parentheses" in (e.get("detail") or "")
                   for e in errs), errs
        assert any(e.get("stmt_idx") == 0 for e in errs), errs

    def test_clean_script_still_reports_nothing(self):
        from app.extractor.adapter import run_full_analysis
        result = run_full_analysis("SELECT a FROM t WHERE b IN (1, 2);",
                                   "clean.sql")
        assert result["parse_errors"] == [], result["parse_errors"]

    def test_dangling_close_keeps_only_the_none_hole_record(self):
        """No duplicate record for the same statement (the ruling's dedup):
        the `);` script reports the statement hole once, unbalanced-paren
        text absent (net < 0)."""
        from app.extractor.adapter import run_full_analysis
        result = run_full_analysis("SELECT 1;\n);\n", "broken2.sql")
        errs = result["parse_errors"]
        assert len(errs) == 1, errs
        assert errs[0]["stmt_idx"] == 1, errs

    def test_parse_error_reaches_the_level2_response(self):
        """The banner's backend contract end to end: parse_errors ride the
        graph cache stamp into the level2 response."""
        ws_id = _indexed_ws({"broken.sql": BROKEN_SQL})
        try:
            sr = _search(ws_id, "src_tbl", "acct_no")
            res = get_level2_graph(ws_id, sr["view_id"], "broken.sql",
                                   "src_tbl", "acct_no")
            assert res.get("error") is None, res
            errs = res.get("parse_errors")
            assert errs, res.get("parse_errors")
            assert any("unbalanced parentheses" in (e.get("detail") or "")
                       for e in errs), errs
        finally:
            delete_workspace(ws_id)

    def test_extractor_version_bumped(self):
        """2026-08-28.7 — the batch that taught the extractor the structural
        check; analysis/graph caches written by 2026-08-28.6 are stale."""
        from app.extractor.variable_extractor_v2 import EXTRACTOR_VERSION
        assert EXTRACTOR_VERSION >= "2026-08-28.7", EXTRACTOR_VERSION


# ════════════════════════════════════════════════════════════════════════
# K4 ruling 4 — direction default flip (FIX-DEFECT)
# ════════════════════════════════════════════════════════════════════════

class TestDirectionDefaultDownstream:
    def _norm(self, value):
        from fastapi import HTTPException
        from app.routers.dataflow import _normalize_direction
        try:
            return _normalize_direction(value), None
        except HTTPException as e:
            return None, e

    def test_absent_defaults_to_downstream(self):
        out, err = self._norm(None)
        assert err is None, err
        assert out == "downstream", out

    def test_legacy_upstream_is_coerced(self):
        out, err = self._norm("upstream")
        assert err is None, err
        assert out == "downstream", out

    def test_downstream_unchanged(self):
        out, err = self._norm("downstream")
        assert err is None, err
        assert out == "downstream", out

    def test_outside_allowlist_is_400(self):
        for bad in ("UPSTREAM", "sideways", "", "Upstream"):
            out, err = self._norm(bad)
            assert out is None, (bad, out)
            assert err is not None and err.status_code == 400, (bad, err)

    def test_service_and_builder_defaults_flipped(self):
        """The six defaults the ruling names — the router boundary is not
        the only place the old default lived."""
        import app.services.dataflow_service as dfs
        import app.services.l1_builder as l1b
        checks = [
            (dfs.create_search, "direction"),
            (dfs._no_matches_result, "direction"),
            (dfs._no_flow_result, "direction"),
            (dfs.get_level2_graph, "direction"),
            (l1b._build_l1_graph, "direction"),
            (l1b._build_l1_graph_uncached, "direction"),
        ]
        for fn, param in checks:
            default = inspect.signature(fn).parameters[param].default
            assert default == "downstream", (fn.__name__, default)

    def test_search_without_direction_runs_downstream(self):
        """A direct service-layer caller (no router in the way) gets the
        downstream projection by default."""
        ws_id = _indexed_ws({"pl.sql": PL_SQL, "dl.sql": DL_SQL})
        try:
            r = _search(ws_id, "bdm_src", "dm_flag2")
            assert r["direction"] == "downstream", r
        finally:
            delete_workspace(ws_id)


# ════════════════════════════════════════════════════════════════════════
# S4 — the not-in-flow banner names the truthful reason
# ════════════════════════════════════════════════════════════════════════

class TestNotInFlowMessage:
    def test_message_says_downstream_flow_not_not_queried(self):
        """`other.sql` touches the searched TABLE but never the FIELD — it
        is outside the field's downstream closure while the field IS queried
        (in writer.sql). The old text ("the field is not queried in this
        script") was factually wrong for exactly this shape."""
        ws_id = _indexed_ws({
            "writer.sql": (
                "INSERT OVERWRITE TABLE bdm_tgt PARTITION(p_dt='2024')\n"
                "SELECT a.dm_flag2 AS dm_flag2 FROM bdm_src a;\n"
            ),
            "other.sql": (
                "INSERT OVERWRITE TABLE bdm_out PARTITION(p_dt='2024')\n"
                "SELECT t.acct_no FROM bdm_src t;\n"
            ),
        })
        try:
            sr = _search(ws_id, "bdm_src", "dm_flag2")
            res = get_level2_graph(ws_id, sr["view_id"], "other.sql",
                                   "bdm_src", "dm_flag2")
            assert res.get("search_matched") is False, res
            msg = res.get("message", "")
            assert "not in the downstream flow" in msg, msg
            assert "bdm_src.dm_flag2" in msg, msg
            assert "showing the full graph" in msg, msg
            # The retired false claim never comes back.
            assert "not queried in this script" not in msg, msg
            # Not-in-flow keeps the panel useful: the FULL graph.
            assert res["graph"]["nodes"] and res["graph"]["edges"], res
        finally:
            delete_workspace(ws_id)


# ════════════════════════════════════════════════════════════════════════
# F-A follow-up — the L2/L1 seed matching is case-insensitive
# ════════════════════════════════════════════════════════════════════════

class TestCaseInsensitiveSeedMatching:
    def test_case_variant_writer_keeps_search_matched(self):
        """Searching `dm_flag2` (the lowercase index key, canonical by the
        exact-key rule) must still seed dl.sql, whose script wrote
        `DM_FLAG2`. Pre-fix: search_matched False + the full-graph fallback
        + no is_target chip."""
        ws_id = _indexed_ws({"pl.sql": PL_SQL, "dl.sql": DL_SQL})
        try:
            sr = _search(ws_id, "bdm_src", "dm_flag2")
            assert sr["script_ids"] == ["dl.sql", "pl.sql"], sr
            res = get_level2_graph(ws_id, sr["view_id"], "dl.sql",
                                   "bdm_src", "dm_flag2")
            # R4 L (2026-08-29): `get_level2_graph` writes `search_matched`
            # ONLY as False (absent ⇒ matched), so the old `is not False`
            # could never fail. The honest form asserts the matched default.
            assert res.get("search_matched", True) is True, res
            seeds = [n["data"] for n in res["graph"]["nodes"]
                     if n["data"].get("type") == "field"
                     and n["data"].get("is_target")]
            assert seeds, res
        finally:
            delete_workspace(ws_id)

    def test_case_variant_writer_keeps_search_matched_reversed(self):
        """The mirror search: canonical `DM_FLAG2` against pl.sql's
        lowercase `dm_flag2`."""
        ws_id = _indexed_ws({"pl.sql": PL_SQL, "dl.sql": DL_SQL})
        try:
            sr = _search(ws_id, "BDM_SRC", "DM_FLAG2")
            assert sr["script_ids"] == ["dl.sql", "pl.sql"], sr
            res = get_level2_graph(ws_id, sr["view_id"], "pl.sql",
                                   "BDM_SRC", "DM_FLAG2")
            assert res.get("search_matched", True) is True, res
            seeds = [n["data"] for n in res["graph"]["nodes"]
                     if n["data"].get("type") == "field"
                     and n["data"].get("is_target")]
            assert seeds, res
        finally:
            delete_workspace(ws_id)

    def test_l1_case_variant_writer_still_participates(self):
        """L1 is the directional field flow (R29 item 8 — no field nodes on
        L1), so the case-split contract here is PARTICIPATION: the script
        that wrote the field in the other case stays in the downstream L1
        projection, together with the searched table's keeper."""
        ws_id = _indexed_ws({"pl.sql": PL_SQL, "dl.sql": DL_SQL})
        try:
            from app.services.dataflow_service import _build_l1_graph
            l1 = _build_l1_graph(ws_id, ["dl.sql", "pl.sql"],
                                 "bdm_src", "dm_flag2")
            assert l1.get("flow_empty") is False, l1
            scripts = {n["data"]["label"] for n in l1["nodes"]
                       if n["data"]["type"] == "script_node"}
            assert scripts == {"dl.sql", "pl.sql"}, l1
            tables = {n["data"].get("table_name") for n in l1["nodes"]
                      if n["data"].get("table_name")}
            assert {t.casefold() for t in tables} >= {"bdm_src", "bdm_tgt"}, l1
        finally:
            delete_workspace(ws_id)

    def test_l1_builder_seed_is_case_insensitive(self):
        """LIMITATION (R4 L, 2026-08-29): the casefold of l1_builder's
        field-children enrichment seed CANNOT be asserted as behaviour, so
        this test pins the reason instead of the source text.

        R29 item 8 makes the path unreachable for a FIELD query: every
        field search returns early through `_build_l1_directional_field_flow`
        (L1 carries no field nodes), so no fixture can drive the enrichment
        seed through the service layer — a source-text assert on it could
        only ever re-test the source, not the system, and is dropped. The
        reachability fact itself IS assertable behaviour, and that is what
        this test now pins: an L1 built for a field query carries only
        script/table nodes, never a field node. The casefold stays
        correctness for the table-only enrichment path and future-proofing
        for any caller that reaches it with a truthy field; the
        user-visible case-split contract is the L2 one tested above.
        """
        ws_id = _indexed_ws({"pl.sql": PL_SQL, "dl.sql": DL_SQL})
        try:
            from app.services.dataflow_service import _build_l1_graph
            l1 = _build_l1_graph(ws_id, ["dl.sql", "pl.sql"],
                                 "bdm_src", "dm_flag2")
            assert l1.get("flow_empty") is False, l1
            node_types = {n["data"]["type"] for n in l1["nodes"]}
            assert node_types, l1
            assert node_types <= {"script_node", "source_table",
                                  "intermediate_table", "output_table",
                                  "query_output"}, node_types
            assert not (node_types & {"field", "column"}), (
                "a FIELD query reached the field-node path on L1 — R29 "
                f"item 8's early return no longer holds: {node_types}")
        finally:
            delete_workspace(ws_id)
