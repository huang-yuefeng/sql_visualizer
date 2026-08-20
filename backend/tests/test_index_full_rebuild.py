"""#257: POST /workspace/{ws_id}/index ALWAYS rebuilds the FULL workspace
index — a partial `scripts` body list must never shrink it.

Bug: index_workspace passed the body's `scripts` list straight into
index_scripts(), which OVERWRITES cache/table_index.json with exactly that
list (no merge). A caller indexing a subset silently destroyed search
coverage for every script left out (observed live:
bdm_acc_loan_info.ACCT_CLOSE_DT returned "not queried by any script" after
a partial index; a full re-index fixed it).

The endpoint now always derives the full pipeline list from scan_folder +
_collect_sql_files and IGNORES any subset in the body — the index is always
the complete workspace index; uploading a folder is the single index
update. This test pins the guarantee over real HTTP: index a 2-script
workspace with only ONE script in the body and assert BOTH scripts'
tables/fields land in the returned AND persisted indexes. Under the old
code this test fails (the subset body would shrink table_index to t1/a
only) — it is a genuine regression guard, not a re-statement of the fix.
"""

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402
from app.services.workspace_service import get_workspace_dir  # noqa: E402

SCRIPT_A = "a.sql"
SCRIPT_B = "b.sql"

SQL_A = "SELECT a FROM t1;\n"
SQL_B = "SELECT b FROM t2;\n"


def _two_sql_zip() -> bytes:
    """In-memory zip with two independent SQL scripts (distinct tables
    t1/t2 and distinct fields a/b — no S4b overlap, no ambiguity)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(SCRIPT_A, SQL_A)
        zf.writestr(SCRIPT_B, SQL_B)
    return buf.getvalue()


@pytest.fixture(scope="module")
def http_client():
    """FastAPI TestClient over the real app (starlette in the image)."""
    with TestClient(app) as client:
        yield client


def _create_ws(http_client) -> str:
    r = http_client.post(
        "/api/workspace",
        files={"file": ("two_scripts.zip", _two_sql_zip(), "application/zip")},
    )
    assert r.status_code == 200, r.text
    return r.json()["workspace_id"]


def test_index_with_partial_body_builds_full_index(http_client):
    """A subset `scripts` body must be IGNORED — the full 2-script index is
    built (both scripts' tables/fields), in the returned payload AND in the
    on-disk cache that search actually consumes."""
    ws_id = _create_ws(http_client)
    try:
        # Deliberately pass only ONE script in the body — the historical
        # shrink-the-index bug triggered exactly on this call.
        r = http_client.post(f"/api/workspace/{ws_id}/index",
                             json={"scripts": [SCRIPT_A]})
        assert r.status_code == 200, r.text
        idx = r.json()
        assert idx["errors"] == [], idx
        assert idx["script_count"] == 2, idx

        # RETURNED index carries both scripts' tables + fields.
        ti = idx["table_index"]
        assert "t1" in ti and "t2" in ti, ti
        assert ti["t1"]["scripts"] == [SCRIPT_A], ti["t1"]
        assert ti["t2"]["scripts"] == [SCRIPT_B], ti["t2"]
        fi = idx["field_index"]
        assert "a" in fi and "b" in fi, fi
        assert fi["a"]["scripts"] == [SCRIPT_A], fi["a"]
        assert fi["b"]["scripts"] == [SCRIPT_B], fi["b"]

        # PERSISTED indexes (what search consumes) agree — the subset body
        # must not have overwritten cache/table_index.json with a.sql only.
        cache_dir = get_workspace_dir(ws_id) / "cache"
        disk_ti = json.loads((cache_dir / "table_index.json").read_text())
        assert "t1" in disk_ti and "t2" in disk_ti, disk_ti
        disk_fi = json.loads((cache_dir / "field_index.json").read_text())
        assert "a" in disk_fi and "b" in disk_fi, disk_fi
    finally:
        http_client.delete(f"/api/workspace/{ws_id}")
