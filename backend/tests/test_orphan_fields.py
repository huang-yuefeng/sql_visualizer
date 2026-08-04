"""Orphan field report tests (Bug 54).

TC-A–TC-D per spec. Fixture pattern from test_l1_l2_integration.py
(zip upload + index_scripts on the real workspace path).
"""

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.workspace_service import (
    create_workspace,
    delete_workspace,
    get_workspace_dir,
)
from app.services.folder_index_service import index_scripts

# TC-A: unqualified columns (no table qualifier) → no table attribution.
TC_A_SQL = (
    "-- load customers\n"
    "INSERT INTO stg_customers (customer_id, full_name) "
    "SELECT customer_id, full_name FROM crm_customers;\n"
)
# TC-B: qualified columns → attribution via alias map (c → crm_customers).
TC_B_SQL = "SELECT c.customer_id FROM crm_customers c;\n"


def _make_ws(sql: str, script_name: str = "load_customers.sql") -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(script_name, sql)
    return create_workspace(buf.getvalue())


@pytest.fixture
def tc_a_ws():
    ws_id = _make_ws(TC_A_SQL)
    yield ws_id
    delete_workspace(ws_id)


@pytest.fixture
def tc_b_ws():
    ws_id = _make_ws(TC_B_SQL, "qualified.sql")
    yield ws_id
    delete_workspace(ws_id)


def test_tc_a_unqualified_columns_are_orphans(tc_a_ws):
    """Unqualified INSERT/SELECT columns register no table → orphans."""
    result = index_scripts(tc_a_ws, ["load_customers.sql"])
    assert result["orphan_field_count"] >= 2, result
    samples = result["orphan_field_samples"]
    assert "customer_id" in samples, samples
    assert "full_name" in samples, samples


def test_tc_b_qualified_columns_have_attribution(tc_b_ws):
    """c.customer_id resolves through the alias map → 0 orphans."""
    result = index_scripts(tc_b_ws, ["qualified.sql"])
    assert result["orphan_field_count"] == 0, result
    assert result["orphan_field_samples"] == []


def test_tc_c_orphan_fields_cache_file(tc_a_ws):
    """orphan_fields.json exists and only holds no-attribution fields."""
    index_scripts(tc_a_ws, ["load_customers.sql"])
    fp = get_workspace_dir(tc_a_ws) / "cache" / "orphan_fields.json"
    assert fp.exists(), "orphan_fields.json should be written next to the other index files"
    data = json.loads(fp.read_text())
    assert isinstance(data, dict), data
    assert set(data) == {"customer_id", "full_name"}, data
    for script_list in data.values():
        assert isinstance(script_list, list), script_list
    fi = json.loads((get_workspace_dir(tc_a_ws) / "cache" / "field_index.json").read_text())
    for fname in data:
        assert not fi[fname]["tables"], f"{fname} must have no table attribution"


def test_tc_d_diagnostic_contains_field_and_sql(monkeypatch, tc_a_ws):
    """Intercept _push: the report block shows the field name AND a SQL line."""
    messages = []

    def fake_push(ws_id, stage, message):
        messages.append((stage, message))

    monkeypatch.setattr("app.services.folder_index_service._push", fake_push)
    index_scripts(tc_a_ws, ["load_customers.sql"])
    joined = "\n".join(m for s, m in messages if s == "profile")
    assert "ORPHAN FIELD REPORT" in joined, "orphan report block must be pushed via _push"
    assert "field: customer_id" in joined, joined
    assert "INSERT INTO stg_customers" in joined, \
        "a SQL line mentioning the field must be shown in the report"
