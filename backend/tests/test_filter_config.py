"""Filter config tests (Bug 51/R19) — two-file intersection + single-file behavior.

TC1–TC10 per tools/BUG_ANALYSIS_AND_SUGGESTIONS.md "Bug 51" design.
Fixture: samples/multi_workflow zip upload + index (same pattern as
test_l1_l2_integration.py).
"""

import asyncio
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
from starlette.datastructures import UploadFile

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.routers.workspace import upload_filter_config
from app.services.workspace_service import (
    create_workspace,
    delete_workspace,
    get_workspace_dir,
)
from app.services.folder_index_service import index_scripts

WORKFLOW_DIR = Path(__file__).resolve().parent.parent.parent / "samples" / "multi_workflow"

STEP1 = "step1_load_orders.sql"
STEP2 = "step2_enrich_customers.sql"

CSV1 = "SCRIPT_NAME,TABLE_NAME\n"
CSV2 = "SYSTEM,TABLE_NAME,COL_NAME,COL_COMMENT\n"


@pytest.fixture
def indexed_ws():
    """Workspace with the 5 multi_workflow scripts, indexed (real zip-upload path)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(WORKFLOW_DIR.glob("step*.sql")):
            zf.write(f, f.name)
    ws_id = create_workspace(buf.getvalue())
    scripts = sorted(f.name for f in WORKFLOW_DIR.glob("step*.sql"))
    index_scripts(ws_id, scripts)
    yield ws_id
    delete_workspace(ws_id)


def _upload(ws_id: str, script_table_csv: str | None = None,
            table_col_csv: str | None = None) -> dict:
    """Call the filter-config endpoint directly (no HTTP server needed)."""
    st = (UploadFile(filename="script_table.csv",
                     file=io.BytesIO(script_table_csv.encode()))
          if script_table_csv is not None else None)
    tc = (UploadFile(filename="table_col.csv",
                     file=io.BytesIO(table_col_csv.encode()))
          if table_col_csv is not None else None)
    return asyncio.run(upload_filter_config(ws_id, script_table=st, table_col=tc))


def _filtered(ws_id: str) -> dict:
    fp = get_workspace_dir(ws_id) / "cache" / "filtered_index.json"
    assert fp.exists(), "filtered_index.json should exist"
    return json.loads(fp.read_text())


def _filtered_tables(ws_id: str) -> set:
    return set(_filtered(ws_id)["table_index"].keys())


def _filtered_fields(ws_id: str) -> set:
    return set(_filtered(ws_id)["field_index"].keys())


class TestTwoFileIntersection:
    """Bug 51/R19: two-file filter is an INTERSECTION, not a union."""

    def test_tc1_table_in_both_files_kept(self, indexed_ws):
        r = _upload(indexed_ws,
                    script_table_csv=CSV1 + f"{STEP2},stg_customers\n",
                    table_col_csv=CSV2 + "ETL,stg_customers,customer_id,Staging customer id\n")
        assert r["filtered"] is True
        assert "stg_customers" in _filtered_tables(indexed_ws)

    def test_tc2_table_only_in_table_col_excluded(self, indexed_ws):
        # daily_summary is a REAL index table (produced by step4) that is NOT in
        # the script_table scope — the old union code would have included it.
        r = _upload(indexed_ws,
                    script_table_csv=CSV1 + f"{STEP2},stg_customers\n",
                    table_col_csv=(CSV2
                                   + "ETL,stg_customers,customer_id,Staging customer id\n"
                                   + "ETL,daily_summary,customer_id,Daily summary customer id\n"))
        tables = _filtered_tables(indexed_ws)
        assert "stg_customers" in tables
        assert "daily_summary" not in tables, "table only in table_col must be excluded"

    def test_tc3_table_only_in_script_table_excluded(self, indexed_ws):
        r = _upload(indexed_ws,
                    script_table_csv=CSV1
                    + f"{STEP1},raw_orders\n"
                    + f"{STEP2},stg_customers\n",
                    table_col_csv=CSV2 + "ETL,stg_customers,customer_id,Staging customer id\n")
        tables = _filtered_tables(indexed_ws)
        assert "stg_customers" in tables
        assert "raw_orders" not in tables, "table only in script_table must be excluded (symmetric)"

    def test_tc4_column_of_excluded_table_dropped(self, indexed_ws):
        # order_date is a REAL index field of daily_summary (excluded table) —
        # the old union code would have kept it in the filtered field index.
        r = _upload(indexed_ws,
                    script_table_csv=CSV1 + f"{STEP2},stg_customers\n",
                    table_col_csv=(CSV2
                                   + "ETL,daily_summary,order_date,Daily summary order date\n"
                                   + "ETL,stg_customers,customer_id,Staging customer id\n"))
        fields = _filtered_fields(indexed_ws)
        assert "customer_id" in fields
        assert "order_date" not in fields, "column of excluded table must be dropped"

    def test_tc5_column_of_intersection_table_kept(self, indexed_ws):
        r = _upload(indexed_ws,
                    script_table_csv=CSV1 + f"{STEP2},stg_customers\n",
                    table_col_csv=CSV2 + "ETL,stg_customers,customer_id,Staging customer id\n")
        assert "customer_id" in _filtered_fields(indexed_ws)

    def test_tc6_file1_only_unchanged(self, indexed_ws):
        r = _upload(indexed_ws, script_table_csv=CSV1
                    + f"{STEP1},raw_orders\n"
                    + f"{STEP2},stg_customers\n")
        assert _filtered_tables(indexed_ws) == {"raw_orders", "stg_customers"}

    def test_tc7_file2_only_unchanged(self, indexed_ws):
        r = _upload(indexed_ws, table_col_csv=CSV2
                    + "ETL,stg_customers,customer_id,Staging customer id\n"
                    + "ETL,crm_customers,full_name,Customer full name\n")
        assert _filtered_tables(indexed_ws) == {"stg_customers", "crm_customers"}
        fields = _filtered_fields(indexed_ws)
        assert "customer_id" in fields
        assert "full_name" in fields

    def test_tc8_no_files_clears_filter(self, indexed_ws):
        _upload(indexed_ws, script_table_csv=CSV1 + f"{STEP2},stg_customers\n")
        assert (get_workspace_dir(indexed_ws) / "cache" / "filtered_index.json").exists()
        r = _upload(indexed_ws)
        assert r["filtered"] is False
        assert not (get_workspace_dir(indexed_ws) / "cache" / "filtered_index.json").exists()

    def test_tc9_empty_intersection(self, indexed_ws):
        r = _upload(indexed_ws,
                    script_table_csv=CSV1 + f"{STEP2},x\n",
                    table_col_csv=CSV2 + "ETL,y,some_col,Column\n")
        assert r["filtered"] is True, "empty intersection keeps the filter active"
        assert r["table_count"] == 0
        assert r["field_count"] == 0
        assert _filtered_tables(indexed_ws) == set()
        assert _filtered_fields(indexed_ws) == set()

    def test_tc10_script_scope_still_from_file1(self, indexed_ws):
        r = _upload(indexed_ws,
                    script_table_csv=CSV1
                    + f"{STEP1},raw_orders\n"
                    + f"{STEP2},stg_customers\n",
                    table_col_csv=CSV2
                    + "ETL,raw_orders,order_id,Order identifier\n"
                    + "ETL,stg_customers,customer_id,Staging customer id\n")
        file1_scripts = {STEP1, STEP2}
        fdata = _filtered(indexed_ws)
        for fname, finfo in fdata["field_index"].items():
            for s in finfo.get("scripts", []):
                assert s in file1_scripts, f"{fname} script {s} outside file-1 scope"
        for tname, tinfo in fdata["table_index"].items():
            for s in tinfo.get("scripts", []):
                assert s in file1_scripts, f"{tname} script {s} outside file-1 scope"


class TestFilterEdgeCases:
    """F1/F2/F4/F5 — search-after-empty-filter, empty-set guards, payload."""

    def test_f1_search_after_empty_intersection(self, indexed_ws):
        """F1: filter active but empty (disjoint CSVs) → search returns a
        successful empty result, not a 400."""
        _upload(indexed_ws,
                script_table_csv=CSV1 + f"{STEP2},x\n",
                table_col_csv=CSV2 + "ETL,y,some_col,Column\n")
        assert _filtered_tables(indexed_ws) == set()
        from app.routers.dataflow import search_dataflow
        result = asyncio.run(search_dataflow(
            indexed_ws, {"table": "stg_customers", "field": "customer_id"}))
        assert result["match_mode"] == "no_matches", result
        assert result["script_ids"] == []
        assert result["l1_graph"]["nodes"] == []
        assert result["message"] == "Filter active — no tables in scope"

    def test_f1_search_unindexed_still_400(self):
        """F1: genuinely unindexed workspace (no filtered_index.json) still 400s."""
        import fastapi
        from app.routers.dataflow import search_dataflow
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("a.sql", "SELECT 1;\n")
        ws_id = create_workspace(buf.getvalue())
        try:
            with pytest.raises(fastapi.HTTPException) as ei:
                asyncio.run(search_dataflow(ws_id, {"table": "a", "field": "b"}))
            assert ei.value.status_code == 400
        finally:
            delete_workspace(ws_id)

    def test_f2_file1_only_zero_table_rows_matches_nothing(self, indexed_ws):
        """F2: script_table.csv with script rows but ZERO table rows → empty
        allowed_tables set must match nothing (was: all tables kept)."""
        r = _upload(indexed_ws, script_table_csv=CSV1 + f"{STEP1},\n")
        assert r["filtered"] is True
        assert r["table_count"] == 0
        assert _filtered_tables(indexed_ws) == set()

    def test_f4_payload_reports_ignored_tables(self, indexed_ws):
        """F4: return payload carries ignored_count/ignored_tables/warning."""
        r = _upload(indexed_ws,
                    script_table_csv=CSV1 + f"{STEP2},stg_customers\n",
                    table_col_csv=(CSV2
                                   + "ETL,stg_customers,customer_id,Staging customer id\n"
                                   + "ETL,daily_summary,customer_id,Daily summary customer id\n"))
        assert r["ignored_count"] == 1
        assert r["ignored_tables"] == ["daily_summary"]
        assert r["warning"] and "ignored" in r["warning"]

    def test_f4_payload_warning_on_empty_intersection(self, indexed_ws):
        """F4: warning present when A∩B is empty; ignored = B − A."""
        r = _upload(indexed_ws,
                    script_table_csv=CSV1 + f"{STEP2},x\n",
                    table_col_csv=CSV2 + "ETL,y,some_col,Column\n")
        assert r["ignored_count"] == 1
        assert r["ignored_tables"] == ["y"]
        assert r["warning"] and "No common tables" in r["warning"]

    def test_f5_case_mismatch_hint_on_empty_intersection(self, monkeypatch, indexed_ws):
        """F5: disjoint CSVs differing only by case produce a hint line."""
        diag_msgs = []

        def fake_push(ws_id, stage, message):
            diag_msgs.append(message)

        monkeypatch.setattr("app.routers.workspace._push", fake_push)
        _upload(indexed_ws,
                script_table_csv=CSV1 + f"{STEP2},STG_CUSTOMERS\n",
                table_col_csv=CSV2 + "ETL,stg_customers,customer_id,Column\n")
        joined = "\n".join(diag_msgs)
        assert "case mismatch" in joined, joined
        assert "STG_CUSTOMERS" in joined and "stg_customers" in joined, joined

    def test_f3_col_name_only_rows_warned(self, monkeypatch, indexed_ws):
        """F3: rows with COL_NAME but empty TABLE_NAME produce a warning line."""
        diag_msgs = []

        def fake_push(ws_id, stage, message):
            diag_msgs.append(message)

        monkeypatch.setattr("app.routers.workspace._push", fake_push)
        _upload(indexed_ws,
                table_col_csv=CSV2
                + "ETL,,orphan_col,Orphan column\n"
                + "ETL,,another_col,Another orphan\n"
                + "ETL,stg_customers,customer_id,Staging customer id\n")
        joined = "\n".join(diag_msgs)
        assert "COL_NAME but empty TABLE_NAME" in joined, joined
        assert "2 row(s)" in joined, joined
        # Valid rows still filter normally
        assert "stg_customers" in _filtered_tables(indexed_ws)


class TestR1BlankColName:
    """R1: a row with TABLE_NAME but blank COL_NAME = table with NO column
    constraint — all its fields pass the field filter (restores pre-F2
    behavior; matches R19's 'single-file uploads unchanged' principle)."""

    def _full_table_fields(self, ws_id: str, tname: str) -> set:
        """Fields of tname in the UNFILTERED table_index (the ground truth)."""
        fp = get_workspace_dir(ws_id) / "cache" / "table_index.json"
        ti = json.loads(fp.read_text())
        return set(ti.get(tname, {}).get("fields", []))

    def test_r1_file2_only_blank_col_name_keeps_all_fields(self, indexed_ws):
        """'stg_customers,' (blank COL_NAME) → table kept with ALL its fields."""
        r = _upload(indexed_ws, table_col_csv=CSV2 + "ETL,stg_customers,\n")
        assert r["filtered"] is True
        assert "stg_customers" in _filtered_tables(indexed_ws)
        ti = _filtered(indexed_ws)["table_index"]
        full = self._full_table_fields(indexed_ws, "stg_customers")
        assert full, "fixture table must have indexed fields"
        assert set(ti["stg_customers"]["fields"]) == full, ti["stg_customers"]
        # field index passes every field of that table too
        fi = _filtered(indexed_ws)["field_index"]
        for f in full:
            assert f in fi, f"{f} must pass the field filter (unconstrained table)"

    def test_r1_blank_row_overrides_column_rows(self, indexed_ws):
        """Table in BOTH a COL_NAME row and a blank-COL_NAME row → the blank
        row wins: the column rows' union plus everything else = unconstrained."""
        r = _upload(indexed_ws, table_col_csv=CSV2
                    + "ETL,stg_customers,customer_id,Staging customer id\n"
                    + "ETL,stg_customers,\n")
        assert r["filtered"] is True
        ti = _filtered(indexed_ws)["table_index"]
        full = self._full_table_fields(indexed_ws, "stg_customers")
        assert set(ti["stg_customers"]["fields"]) == full, ti["stg_customers"]
        fi = _filtered(indexed_ws)["field_index"]
        assert "customer_id" in fi
        for f in full:
            assert f in fi, f"{f} must pass (table unconstrained)"

    def test_r1_two_file_intersection_respects_blank_row(self, indexed_ws):
        """A∩B keeps an unconstrained intersection table; its fields survive."""
        r = _upload(indexed_ws,
                    script_table_csv=CSV1 + f"{STEP2},stg_customers\n",
                    table_col_csv=CSV2 + "ETL,stg_customers,\n")
        assert "stg_customers" in _filtered_tables(indexed_ws)
        ti = _filtered(indexed_ws)["table_index"]
        full = self._full_table_fields(indexed_ws, "stg_customers")
        assert set(ti["stg_customers"]["fields"]) == full, ti["stg_customers"]

    def test_r1_blank_row_does_not_leak_outside_intersection(self, indexed_ws):
        """A blank row for a table OUTSIDE the effective scope must not let
        its fields leak into the filtered field index (R19 intersection)."""
        r = _upload(indexed_ws,
                    script_table_csv=CSV1 + f"{STEP2},stg_customers\n",
                    table_col_csv=(CSV2
                                   + "ETL,stg_customers,customer_id,Staging customer id\n"
                                   + "ETL,daily_summary,\n"))  # blank row, table not in A
        assert "daily_summary" not in _filtered_tables(indexed_ws)
        ignored_fields = self._full_table_fields(indexed_ws, "daily_summary")
        assert ignored_fields, "fixture must have daily_summary fields"
        fi = _filtered(indexed_ws)["field_index"]
        for f in ignored_fields:
            assert f not in fi, f"{f} of ignored table must not leak"


class TestH1ScriptPathContainment:
    """H1 (P0): resolve_script must never resolve outside the scripts dir.

    `name` is user-controlled via the filter CSV SCRIPT_NAME column — an
    absolute path or `../` chain must return None, not an arbitrary file.
    """

    def test_h1_absolute_path_rejected(self, indexed_ws):
        from app.services.filter_service import resolve_script
        assert resolve_script(indexed_ws, "/etc/passwd") is None
        assert resolve_script(indexed_ws, "/etc/hostname.sql") is None

    def test_h1_parent_traversal_rejected(self, indexed_ws):
        from app.services.filter_service import resolve_script
        assert resolve_script(indexed_ws, "../secret.sql") is None
        assert resolve_script(indexed_ws, "sub/../../etc/passwd") is None
        assert resolve_script(indexed_ws, "../../../etc/passwd.sql") is None
        assert resolve_script(indexed_ws, "..\\..\\secret.sql") is None

    def test_h1_legit_variants_still_resolve(self, indexed_ws):
        """Basename and ±.sql tolerance is preserved for in-scope names."""
        from app.services.filter_service import resolve_script
        p = resolve_script(indexed_ws, STEP2)
        assert p is not None and p.exists()
        assert resolve_script(indexed_ws, "step2_enrich_customers.sql") is not None
        assert resolve_script(indexed_ws, "step2_enrich_customers") is not None
        scripts_root = (get_workspace_dir(indexed_ws) / "scripts").resolve()
        assert p.resolve().is_relative_to(scripts_root)

    def test_h1_missing_name_returns_none(self, indexed_ws):
        from app.services.filter_service import resolve_script
        assert resolve_script(indexed_ws, "") is None
        assert resolve_script(indexed_ws, "no_such_script.sql") is None


class TestM5MalformedCsv:
    """M5: short rows (missing trailing fields) must never 500."""

    def test_m5_short_row_script_table_graceful(self, indexed_ws):
        """'foo' (1 column, 2 declared headers) parses gracefully."""
        r = _upload(indexed_ws, script_table_csv=CSV1 + "foo\n")
        assert r["filtered"] is True
        assert r["table_count"] == 0

    def test_m5_short_row_table_col_graceful(self, indexed_ws):
        """'ETL,stg_customers' (2 of 4 columns) parses gracefully — the
        missing COL_NAME makes the table unconstrained (R1)."""
        r = _upload(indexed_ws, table_col_csv=CSV2 + "ETL,stg_customers\n")
        assert r["filtered"] is True
        assert "stg_customers" in _filtered_tables(indexed_ws)

    def test_m5_oversized_field_400(self, indexed_ws):
        """A field beyond the csv module's limit raises csv.Error inside the
        parse loop → HTTPException(400), not an unhandled 500."""
        import fastapi
        with pytest.raises(fastapi.HTTPException) as ei:
            _upload(indexed_ws, script_table_csv=CSV1 + "x" * 200_000 + ",c\n")
        assert ei.value.status_code == 400
        assert "Invalid script_table.csv" in ei.value.detail

    def test_m5_oversized_field_table_col_400(self, indexed_ws):
        import fastapi
        with pytest.raises(fastapi.HTTPException) as ei:
            _upload(indexed_ws, table_col_csv=CSV2 + "ETL,stg_customers," + "x" * 200_000 + "\n")
        assert ei.value.status_code == 400
        assert "Invalid table_col.csv" in ei.value.detail


class TestM6FieldTableSymmetry:
    """M6: filtered_fi[f]["tables"] must mirror filtered_ti[t]["fields"]."""

    def test_m6_shared_field_excludes_constrained_table(self, indexed_ws):
        """Field f shared by unconstrained U and constrained C (both allowed):
        filtered_fi[f]["tables"] lists U, NOT C (old code listed both)."""
        cache = get_workspace_dir(indexed_ws) / "cache"
        ti = json.loads((cache / "table_index.json").read_text())
        fi = json.loads((cache / "field_index.json").read_text())
        shared = [(f, fd.get("tables", [])) for f, fd in fi.items()
                  if len(fd.get("tables", [])) >= 2]
        assert shared, "fixture must have a field shared by ≥2 tables"
        fname, tables = shared[0]
        U, C = tables[0], tables[1]
        c_fields = [f for f in ti[C].get("fields", []) if f != fname]
        assert c_fields, "constrained table needs another field to constrain to"
        other = c_fields[0]
        r = _upload(indexed_ws, table_col_csv=CSV2
                    + f"ETL,{U},,\n"                        # U: blank COL_NAME → unconstrained
                    + f"ETL,{C},{other},{other} comment\n")  # C: constrained to `other`
        assert r["filtered"] is True
        filtered = _filtered(indexed_ws)
        # the field survives via U...
        assert fname in filtered["field_index"], fname
        # ...but C must not claim it (symmetric with filtered_ti[C]["fields"])
        assert C not in filtered["field_index"][fname]["tables"], filtered["field_index"][fname]
        assert U in filtered["field_index"][fname]["tables"]
        # full symmetry invariant: every field→table claim has the field in
        # that table's own filtered entry
        for f, fd in filtered["field_index"].items():
            for t in fd.get("tables", []):
                assert f in filtered["table_index"][t]["fields"], (f, t)
        # mirror: C's table entry omits fname
        assert fname not in filtered["table_index"][C]["fields"]

    def test_m6_pure_column_filter_unaffected(self, indexed_ws):
        """No unconstrained tables → behavior identical to before."""
        r = _upload(indexed_ws, table_col_csv=CSV2
                    + "ETL,stg_customers,customer_id,Staging customer id\n")
        assert r["filtered"] is True
        filtered = _filtered(indexed_ws)
        assert "customer_id" in filtered["field_index"]
        tables = filtered["field_index"]["customer_id"]["tables"]
        assert "stg_customers" in tables
        assert set(tables) <= set(filtered["table_index"])


class TestN6BlankRowWinsDiagnostic:
    """N6: a table with BOTH a blank-COL_NAME row and column rows gets a
    diagnostic naming it (the blank row silently wins)."""

    def test_n6_blank_row_wins_diagnostic(self, monkeypatch, indexed_ws):
        diag_msgs = []

        def fake_push(ws_id, stage, message):
            diag_msgs.append(message)

        monkeypatch.setattr("app.routers.workspace._push", fake_push)
        _upload(indexed_ws, table_col_csv=CSV2
                + "ETL,stg_customers,customer_id,Staging customer id\n"
                + "ETL,stg_customers,\n")
        joined = "\n".join(diag_msgs)
        assert "blank row wins for: stg_customers" in joined, joined

    def test_n6_no_blank_wins_line_when_clean(self, monkeypatch, indexed_ws):
        diag_msgs = []

        def fake_push(ws_id, stage, message):
            diag_msgs.append(message)

        monkeypatch.setattr("app.routers.workspace._push", fake_push)
        _upload(indexed_ws, table_col_csv=CSV2
                + "ETL,stg_customers,customer_id,Staging customer id\n")
        joined = "\n".join(diag_msgs)
        assert "blank row wins" not in joined, joined


class TestL10CsvSizeCap:
    """L10: filter CSVs are size-capped → HTTPException(400) on oversize."""

    def test_l10_script_table_cap(self, indexed_ws, monkeypatch):
        import fastapi
        import app.services.filter_service as fs
        monkeypatch.setattr(fs, "MAX_FILTER_CSV_BYTES", 5)
        with pytest.raises(fastapi.HTTPException) as ei:
            _upload(indexed_ws, script_table_csv=CSV1 + f"{STEP2},stg_customers\n")
        assert ei.value.status_code == 400
        assert "too large" in ei.value.detail

    def test_l10_table_col_cap(self, indexed_ws, monkeypatch):
        import fastapi
        import app.services.filter_service as fs
        monkeypatch.setattr(fs, "MAX_FILTER_CSV_BYTES", 5)
        with pytest.raises(fastapi.HTTPException) as ei:
            _upload(indexed_ws, table_col_csv=CSV2 + "ETL,stg_customers,customer_id,Comment\n")
        assert ei.value.status_code == 400
        assert "too large" in ei.value.detail


class TestL11CsvEncoding:
    """L11: non-UTF-8 (GBK/BOM) CSVs decode via fallbacks, with a hint."""

    def test_l11_decode_gbk(self):
        from app.services.filter_service import _decode_csv
        text, enc = _decode_csv("客户,customer\n".encode("gbk"))
        assert enc == "gb18030"
        assert text == "客户,customer\n"
        text, enc = _decode_csv(b"\xef\xbb\xbfSCRIPT_NAME,TABLE_NAME\nfoo\n")
        assert enc == "utf-8-sig"
        assert text.startswith("SCRIPT_NAME")
        text, enc = _decode_csv(bytes(range(128, 256)))
        assert enc == "latin-1"
        assert len(text) == 128

    def test_l11_gbk_upload_decodes_with_hint(self, monkeypatch, indexed_ws):
        """A GBK-encoded table_col.csv filters correctly, names intact, and
        the R16 diag notes the encoding instead of silently corrupting."""
        diag_msgs = []

        def fake_push(ws_id, stage, message):
            diag_msgs.append(message)

        monkeypatch.setattr("app.routers.workspace._push", fake_push)
        csv_bytes = ("SYSTEM,TABLE_NAME,COL_NAME,COL_COMMENT\n"
                     "ETL,客户表,名称,备注\n"
                     "ETL,stg_customers,customer_id,Staging customer id\n").encode("gbk")
        st = UploadFile(filename="table_col.csv", file=io.BytesIO(csv_bytes))
        r = asyncio.run(upload_filter_config(indexed_ws, script_table=None, table_col=st))
        assert r["filtered"] is True
        assert "stg_customers" in _filtered_tables(indexed_ws)
        joined = "\n".join(diag_msgs)
        assert "客户表" in joined, joined       # decoded, not mojibake
        assert "gb18030" in joined, joined     # encoding hint emitted
        assert "�" not in joined, joined   # no silent U+FFFD corruption

    def test_l11_utf8_bom_upload_still_filters(self, indexed_ws):
        """A UTF-8 BOM must not break parsing (utf-8-sig strips it)."""
        st = UploadFile(filename="script_table.csv",
                        file=io.BytesIO(("﻿" + CSV1 + f"{STEP2},stg_customers\n").encode()))
        r = asyncio.run(upload_filter_config(indexed_ws, script_table=st, table_col=None))
        assert r["filtered"] is True
        assert "stg_customers" in _filtered_tables(indexed_ws)


class TestR3NoMatchesDiagnostic:
    """R3: the F1 no_matches search path also emits the R17 diagnostic."""

    def test_r3_no_matches_search_emits_diagnostic(self, monkeypatch, indexed_ws):
        """Search on a filter-active-but-empty workspace pushes an R17 block."""
        _upload(indexed_ws,
                script_table_csv=CSV1 + f"{STEP2},x\n",
                table_col_csv=CSV2 + "ETL,y,some_col,Column\n")
        from app.routers.dataflow import search_dataflow
        diag_msgs = []

        def fake_push(ws_id, stage, message):
            diag_msgs.append(message)

        monkeypatch.setattr("app.routers.dataflow._push", fake_push)
        result = asyncio.run(search_dataflow(
            indexed_ws, {"table": "stg_customers", "field": "customer_id"}))
        assert result["match_mode"] == "no_matches", result
        joined = "\n".join(diag_msgs)
        assert "SEARCH DIAGNOSTIC" in joined, joined
        assert "Filter active: YES  (0 tables, 0 fields in scope)" in joined, joined
        assert "Table in index: NO" in joined, joined
        assert "Matching scripts: 0" in joined, joined
        assert "Table not in filter scope" in joined, joined

    def test_r3_no_matches_view_persisted(self, indexed_ws):
        """The F1 no-matches view is persisted to views.json like any search.

        N4: l1_graph_cache carries `target` for shape parity with regular
        views. M8: match_mode + message are saved so the frontend can show
        the no-match banner after a reload.
        """
        _upload(indexed_ws,
                script_table_csv=CSV1 + f"{STEP2},x\n",
                table_col_csv=CSV2 + "ETL,y,some_col,Column\n")
        from app.routers.dataflow import search_dataflow
        from app.services.dataflow_service import list_views
        result = asyncio.run(search_dataflow(
            indexed_ws, {"table": "stg_customers", "field": "customer_id"}))
        assert result["match_mode"] == "no_matches", result
        views = list_views(indexed_ws)
        saved = [v for v in views if v["view_id"] == result["view_id"]]
        assert len(saved) == 1, views
        assert saved[0]["script_ids"] == [], saved[0]
        assert saved[0]["l1_graph_cache"] == {"nodes": [], "edges": [],
                                              "target": "table.field"}, saved[0]
        assert saved[0]["match_mode"] == "no_matches", saved[0]
        assert saved[0]["message"] == "Filter active — no tables in scope", saved[0]

    def test_r3_no_matches_persisted_view_shape_matches_regular(self, indexed_ws):
        """N4: no_matches cache shape (incl. target) is identical to a
        regular search view's cache keys."""
        _upload(indexed_ws,
                script_table_csv=CSV1 + f"{STEP2},x\n",
                table_col_csv=CSV2 + "ETL,y,some_col,Column\n")
        from app.routers.dataflow import search_dataflow
        from app.services.dataflow_service import list_views
        result = asyncio.run(search_dataflow(
            indexed_ws, {"table": "stg_customers", "field": "customer_id"}))
        views = list_views(indexed_ws)
        saved = [v for v in views if v["view_id"] == result["view_id"]][0]
        assert "target" in saved["l1_graph_cache"], saved["l1_graph_cache"]

    def test_m8_regular_search_view_persists_match_mode(self, indexed_ws):
        """M8: create_search's persisted view carries match_mode so the
        frontend can restore the search mode after a reload."""
        from app.routers.dataflow import search_dataflow
        from app.services.dataflow_service import list_views
        result = asyncio.run(search_dataflow(
            indexed_ws, {"table": "stg_customers", "field": "customer_id"}))
        assert result["match_mode"] in ("exact", "expanded", "fallback"), result
        views = list_views(indexed_ws)
        saved = [v for v in views if v["view_id"] == result["view_id"]]
        assert len(saved) == 1, views
        assert saved[0]["match_mode"] == result["match_mode"], saved[0]

    def test_l8_diagnostic_scope_counts_come_from_loaded_index(self, monkeypatch, indexed_ws):
        """L8: the R17 diagnostic's scope counts match the loaded (filtered)
        index — no second read of filtered_index.json inside the search."""
        _upload(indexed_ws,
                script_table_csv=CSV1 + f"{STEP2},stg_customers\n",
                table_col_csv=CSV2 + "ETL,stg_customers,customer_id,Staging customer id\n")
        from app.routers.dataflow import search_dataflow
        diag_msgs = []

        def fake_push(ws_id, stage, message):
            diag_msgs.append(message)

        monkeypatch.setattr("app.routers.dataflow._push", fake_push)
        result = asyncio.run(search_dataflow(
            indexed_ws, {"table": "stg_customers", "field": "customer_id"}))
        assert result["match_mode"] != "no_matches", result
        joined = "\n".join(diag_msgs)
        assert "Filter active: YES  (1 tables, 1 fields in scope)" in joined, joined
