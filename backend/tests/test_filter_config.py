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
STEP3 = "step3_join_orders_customers.sql"

CSV1 = "SCRIPT_NAME,TABLE_NAME\n"
CSV2 = "SYSTEM,TABLE_NAME,COL_NAME,COL_COMMENT\n"


@pytest.fixture
def indexed_ws():
    """Workspace with the 5 multi_workflow scripts, indexed (real zip-upload path)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(WORKFLOW_DIR.glob("step*.sql")):
            zf.write(f, f.name)
    ws_id = create_workspace(buf.getvalue(), creator_username="dev-user")
    scripts = sorted(f.name for f in WORKFLOW_DIR.glob("step*.sql"))
    index_scripts(ws_id, scripts)
    yield ws_id
    delete_workspace(ws_id)


class _Req:
    """Minimal request stand-in for direct handler calls (no HTTP server)."""
    cookies = {}
    client = None


def _upload(ws_id: str, script_table_csv: str | None = None,
            table_col_csv: str | None = None) -> dict:
    """Call the filter-config endpoint directly (no HTTP server needed)."""
    st = (UploadFile(filename="script_table.csv",
                     file=io.BytesIO(script_table_csv.encode()))
          if script_table_csv is not None else None)
    tc = (UploadFile(filename="table_col.csv",
                     file=io.BytesIO(table_col_csv.encode()))
          if table_col_csv is not None else None)
    return asyncio.run(upload_filter_config(_Req(), ws_id, script_table=st, table_col=tc))


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

    def test_tc10_script_scope_from_table_col(self, indexed_ws):
        """User ruling (2026-08-14): the table-column CSV (File 2) is the
        single source of truth for SCRIPT scope. With both files uploaded,
        allowed_scripts = ⋃ table_index[t]["scripts"] over File 2's tables
        (raw_orders → {step1}, stg_customers → {step2, step3}) = {step1,
        step2, step3} — File 1's {step1, step2} is IGNORED for scope, so
        step3 (which joins the file-2 table stg_customers) IS in scope."""
        r = _upload(indexed_ws,
                    script_table_csv=CSV1
                    + f"{STEP1},raw_orders\n"
                    + f"{STEP2},stg_customers\n",
                    table_col_csv=CSV2
                    + "ETL,raw_orders,order_id,Order identifier\n"
                    + "ETL,stg_customers,customer_id,Staging customer id\n")
        file2_scope = {STEP1, STEP2, STEP3}
        fdata = _filtered(indexed_ws)
        scoped_scripts = set()
        for fname, finfo in fdata["field_index"].items():
            for s in finfo.get("scripts", []):
                scoped_scripts.add(s)
                assert s in file2_scope, f"{fname} script {s} outside file-2 scope"
        for tname, tinfo in fdata["table_index"].items():
            for s in tinfo.get("scripts", []):
                scoped_scripts.add(s)
                assert s in file2_scope, f"{tname} script {s} outside file-2 scope"
        assert STEP3 in scoped_scripts, \
            "step3 joins stg_customers (a file-2 table) — must be in script scope"

    def test_tc11_file2_only_script_scope_is_table_union(self, indexed_ws):
        """User ruling: uploading ONLY File 2 must scope scripts to the
        union of its tables' scripts (was: allowed_scripts = None → every
        script referencing the field). File-2-only stg_customers →
        {step2, step3} — step1 (raw_orders) is NOT in scope."""
        r = _upload(indexed_ws, table_col_csv=CSV2
                    + "ETL,stg_customers,customer_id,Staging customer id\n")
        assert r["filtered"] is True
        fdata = _filtered(indexed_ws)
        scoped_scripts = set()
        for fname, finfo in fdata["field_index"].items():
            scoped_scripts.update(finfo.get("scripts", []))
        for tname, tinfo in fdata["table_index"].items():
            scoped_scripts.update(tinfo.get("scripts", []))
        assert scoped_scripts and scoped_scripts <= {STEP2, STEP3}, scoped_scripts
        # customer_id is indexed for step1 too — but step1 is out of scope
        assert "customer_id" in _filtered_fields(indexed_ws)
        assert "order_id" not in _filtered_fields(indexed_ws)


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

    def test_f4_payload_carries_ignored_rows(self, indexed_ws):
        """F4: the response carries ignored_rows (CSV-level drops) alongside
        ignored_count/ignored_tables (intersection exclusions) and warning —
        the two counters are disjoint (rows vs tables)."""
        r = _upload(indexed_ws,
                    script_table_csv=CSV1 + f"{STEP2},stg_customers\n",
                    table_col_csv=(CSV2
                                   + "ETL,stg_customers,customer_id,Staging customer id\n"
                                   + "ETL,daily_summary,customer_id,Daily summary customer id\n"
                                   + "ETL,,no_table_col,Orphan column\n"))
        assert r["ignored_rows"] == 1, r
        assert r["ignored_count"] == 1, r
        assert r["ignored_tables"] == ["daily_summary"], r
        assert r["warning"] and "ignored" in r["warning"], r
        assert "no_table_col" not in _filtered_fields(indexed_ws)

    def test_f5_case_mismatch_table_now_matches(self, indexed_ws):
        """F5: file-1 STG_CUSTOMERS + file-2 stg_customers — case must not
        yield a silent 0/0: the A∩B intersection matches case-insensitively
        and the stored index keeps its original (lowercase) names."""
        r = _upload(indexed_ws,
                    script_table_csv=CSV1 + f"{STEP2},STG_CUSTOMERS\n",
                    table_col_csv=CSV2 + "ETL,stg_customers,customer_id,Column\n")
        assert r["filtered"] is True
        assert r["table_count"] == 1, r
        assert "stg_customers" in _filtered_tables(indexed_ws)
        assert "customer_id" in _filtered_fields(indexed_ws)
        assert r["warning"] is None, r

    def test_f5_case_mismatch_reverse_direction(self, indexed_ws):
        """F5: file-1 stg_customers + file-2 STG_CUSTOMERS also matches
        (folding is applied on BOTH sides, at parse and at predicate)."""
        r = _upload(indexed_ws,
                    script_table_csv=CSV1 + f"{STEP2},stg_customers\n",
                    table_col_csv=CSV2 + "ETL,STG_CUSTOMERS,CUSTOMER_ID,Column\n")
        assert r["filtered"] is True
        assert "stg_customers" in _filtered_tables(indexed_ws)
        assert "customer_id" in _filtered_fields(indexed_ws)
        assert "STG_CUSTOMERS" not in _filtered_tables(indexed_ws)
        assert "CUSTOMER_ID" not in _filtered_fields(indexed_ws)

    def test_f5_column_case_matches_field(self, indexed_ws):
        """F5: field-level — CUSTOMER_ID in the CSV matches the index's
        customer_id; the stored artifact keeps its original case."""
        r = _upload(indexed_ws,
                    table_col_csv=CSV2 + "ETL,stg_customers,CUSTOMER_ID,Column\n")
        assert r["filtered"] is True
        ti = _filtered(indexed_ws)["table_index"]
        assert "stg_customers" in ti
        assert "customer_id" in ti["stg_customers"]["fields"], ti
        assert "CUSTOMER_ID" not in ti["stg_customers"]["fields"], ti

    def test_f5_unconstrained_case_variant_table(self, indexed_ws):
        """F5 + R1: a blank-COL_NAME row with a case-variant table name
        unconstrains the real table — its fields all pass."""
        r = _upload(indexed_ws,
                    table_col_csv=CSV2 + "ETL,STG_CUSTOMERS,\n")
        assert r["filtered"] is True
        ti = _filtered(indexed_ws)["table_index"]
        assert "stg_customers" in ti
        assert "customer_id" in ti["stg_customers"]["fields"], ti

    def test_f3_col_name_only_rows_warned(self, monkeypatch, indexed_ws):
        """F3: rows with COL_NAME but empty TABLE_NAME are DROPPED BY DESIGN
        (cannot attach to a scope table) — counted as ignored_rows, warned
        in the R16 diag, and never leak into the filtered index."""
        diag_msgs = []

        def fake_push(ws_id, stage, message):
            diag_msgs.append(message)

        monkeypatch.setattr("app.routers.workspace._push", fake_push)
        r = _upload(indexed_ws,
                    table_col_csv=CSV2
                    + "ETL,,orphan_col,Orphan column\n"
                    + "ETL,,another_col,Another orphan\n"
                    + "ETL,stg_customers,customer_id,Staging customer id\n")
        joined = "\n".join(diag_msgs)
        assert "COL_NAME but empty TABLE_NAME" in joined, joined
        assert "2 row(s)" in joined, joined
        # F3/F4: counted in the response — one name for CSV-level drops
        assert r["ignored_rows"] == 2, r
        # Valid rows still filter normally; dropped rows never surface
        assert "stg_customers" in _filtered_tables(indexed_ws)
        assert "customer_id" in _filtered_fields(indexed_ws)
        assert "orphan_col" not in _filtered_fields(indexed_ws)
        assert "another_col" not in _filtered_fields(indexed_ws)


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
        r = asyncio.run(upload_filter_config(_Req(), indexed_ws, script_table=None, table_col=st))
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
        r = asyncio.run(upload_filter_config(_Req(), indexed_ws, script_table=st, table_col=None))
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


class TestR17BaseIndexDiagnostic:
    """BE2 (issue c): the R17 search diagnostic must distinguish a field
    absent from the BASE index (no script queries it — the filter CSVs are
    not to blame) from a field present in the base index but excluded by the
    active filter CSV (legitimate 'add to table_col.csv' hint)."""

    def _run_search(self, monkeypatch, ws_id, table, field):
        from app.routers.dataflow import search_dataflow
        diag_msgs = []

        def fake_push(ws_id_, stage, message):
            diag_msgs.append(message)

        monkeypatch.setattr("app.routers.dataflow._push", fake_push)
        result = asyncio.run(search_dataflow(ws_id, {"table": table, "field": field}))
        return result, "\n".join(diag_msgs)

    def test_r17_field_absent_from_base_index_no_csv_blame(self, monkeypatch, indexed_ws):
        """No filter active; the field is absent from the base index → the
        diagnostic says 'not queried by any indexed script', NOT 'add to
        table_col.csv' (the CSV is not the cause)."""
        result, joined = self._run_search(monkeypatch, indexed_ws,
                                          "stg_customers", "ghost_field")
        assert result["match_mode"] == "no_matches", result
        assert "SEARCH DIAGNOSTIC" in joined, joined
        assert "ghost_field is not queried by any indexed script" in joined, joined
        assert "no data flow exists" in joined, joined
        assert "table_col.csv" not in joined, joined

    def test_r17_table_absent_from_base_index_no_csv_blame(self, monkeypatch, indexed_ws):
        """No filter active; the table is absent from the base index → the
        diagnostic says the table is not queried, not a CSV hint."""
        result, joined = self._run_search(monkeypatch, indexed_ws,
                                          "ghost_table", "customer_id")
        assert result["match_mode"] == "no_matches", result
        assert "ghost_table is not queried by any indexed script" in joined, joined
        assert "no data flow exists" in joined, joined
        assert "script_table.csv" not in joined, joined

    def test_r17_field_filtered_out_keeps_csv_hint(self, monkeypatch, indexed_ws):
        """The field IS in the base index but excluded by the active filter
        CSV → keep the legitimate 'add to table_col.csv or clear filter'
        hint (this is the only case where the CSV is the cause)."""
        _upload(indexed_ws,
                script_table_csv=CSV1 + f"{STEP2},stg_customers\n",
                table_col_csv=CSV2 + "ETL,stg_customers,customer_id,Staging customer id\n")
        # "amount" is indexed (step1/step3/step4) but not in the filter scope
        result, joined = self._run_search(monkeypatch, indexed_ws,
                                          "stg_customers", "amount")
        assert result["match_mode"] == "no_matches", result
        assert "Field not in filter scope - add to table_col.csv or clear filter" in joined, joined

    def test_r17_filter_active_field_absent_from_base_not_csv_blame(self, monkeypatch, indexed_ws):
        """Filter active AND the field absent from the base index → the real
        cause is 'no script queries it', not the CSV. (The old code blamed
        the filter CSV for every field missing from the filtered index.)"""
        _upload(indexed_ws,
                script_table_csv=CSV1 + f"{STEP2},x\n",
                table_col_csv=CSV2 + "ETL,y,some_col,Column\n")
        result, joined = self._run_search(monkeypatch, indexed_ws,
                                          "stg_customers", "ghost_field")
        assert result["match_mode"] == "no_matches", result
        assert "ghost_field is not queried by any indexed script" in joined, joined
        assert "table_col.csv" not in joined, joined
        assert "script_table.csv" not in joined, joined


class TestF2DeleteWorkspaceValidation:
    """F2: DELETE /me/workspaces/{ws_id} (R31/A-M1) validates ws_id before
    touching disk — 400 for a malformed id (path-traversal guard), 404 for a
    valid-format but nonexistent workspace, and a real delete for an
    existing one."""

    def _delete(self, ws_id: str):
        from app.routers.workspace import remove_from_my_history_endpoint

        class _Req:
            cookies = {}
            client = None

        return asyncio.run(remove_from_my_history_endpoint(_Req(), ws_id))

    def test_f2_invalid_ws_id_400(self):
        import fastapi
        for bad in ("../etc/passwd", "0d4ae2cefe6a/../x", "ZZZ",
                    "0d4ae2cefe6", "0d4ae2cefe6aX", "0d4AE2CEFE6A",
                    "0d4ae2cefe6a!", ""):
            with pytest.raises(fastapi.HTTPException) as ei:
                self._delete(bad)
            assert ei.value.status_code == 400, bad

    def test_f2_valid_format_missing_404(self):
        import fastapi
        # R31/A-H4: ws_id is full UUID4 hex (32 chars) — a 12-char id is now
        # malformed (400); use a well-formed but nonexistent id for the 404.
        with pytest.raises(fastapi.HTTPException) as ei:
            self._delete("0d4ae2cefe6a1234567890abcdef1234")
        assert ei.value.status_code == 404

    def test_f2_existing_workspace_deleted(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("a.sql", "SELECT 1;\n")
        # R31: only the CREATOR's remove physically deletes. Gate-off caller
        # is "dev-user", so stamp it as creator to exercise the delete path.
        ws_id = create_workspace(buf.getvalue(), creator_username="dev-user")
        ws_dir = get_workspace_dir(ws_id)
        assert ws_dir.exists()
        r = self._delete(ws_id)
        assert r["deleted"] is True, r
        assert not ws_dir.exists(), "workspace directory must be gone"
