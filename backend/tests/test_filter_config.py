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
