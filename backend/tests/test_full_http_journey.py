"""CW10: full-HTTP journey test (P2 gap from the 08-04 code review).

The suite had 495 unit tests but NO test simulating the complete user
flow over real HTTP. This test drives the FastAPI app through
TestClient (starlette) end-to-end, using the actual
samples/multi_workflow.zip artifact:

  upload (multipart) → index → search → L1 graph → L2 graph → delete

Everything runs over HTTP (no direct service calls), with workspace
teardown on both success and failure. Fixture pattern mirrors
test_filter_config.py / test_l1_l2_integration.py (zip upload +
delete_workspace teardown), but through the HTTP layer.
"""

import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402

# The real upload artifact (exists in the repo and inside the container
# at the same relative path — /app/samples/multi_workflow.zip).
ZIP_PATH = Path(__file__).resolve().parent.parent.parent / "samples" / "multi_workflow.zip"

TARGET_TABLE = "stg_customers"
TARGET_FIELD = "customer_id"
STEP3 = "multi_workflow/step3_join_orders_customers.sql"

# Tree paths of the 5 SQL scripts inside multi_workflow.zip (verified
# against unzip -l; the zip keeps its top-level multi_workflow/ dir).
EXPECTED_SCRIPTS = [
    "multi_workflow/step1_load_orders.sql",
    "multi_workflow/step2_enrich_customers.sql",
    "multi_workflow/step3_join_orders_customers.sql",
    "multi_workflow/step4_aggregate_daily.sql",
    "multi_workflow/step5_final_report.sql",
]


def _collect_sql_paths(tree: dict) -> list:
    """Collect is_sql file paths from a scan_folder-style file tree."""
    paths = []
    if tree.get("type") == "file" and tree.get("is_sql"):
        paths.append(tree["path"])
    for child in tree.get("children", []):
        paths.extend(_collect_sql_paths(child))
    return paths


def _collect_non_sql_paths(tree: dict) -> list:
    """Collect non-SQL file paths from a scan_folder-style file tree."""
    paths = []
    if tree.get("type") == "file" and not tree.get("is_sql"):
        paths.append(tree["path"])
    for child in tree.get("children", []):
        paths.extend(_collect_non_sql_paths(child))
    return paths


@pytest.fixture(scope="module")
def http_client():
    """FastAPI TestClient over the real app (starlette in the image)."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def journey_ws(http_client):
    """Workspace created by uploading samples/multi_workflow.zip over HTTP.

    Yields (client, ws_id, file_tree). Teardown DELETEs the workspace over
    HTTP — runs on both success and failure (idempotent: after the test
    body's own step-6 delete it is a 404 no-op).
    """
    zip_bytes = ZIP_PATH.read_bytes()
    r = http_client.post(
        "/api/workspace",
        files={"file": ("multi_workflow.zip", zip_bytes, "application/zip")},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    ws_id = payload["workspace_id"]
    yield http_client, ws_id, payload["file_tree"]
    http_client.delete(f"/api/workspace/{ws_id}")


def test_full_http_journey(journey_ws):
    """The complete user flow over real HTTP, in order:

    1. POST /api/workspace  — multipart zip upload → workspace_id + file_tree
    2. POST /api/workspace/{id}/index — index the 5 SQL scripts →
       resolution_stats / orphan_field_count contract
    3. POST /api/workspace/{id}/search — stg_customers.customer_id →
       view_id + L1 graph
    4. GET  /api/workspace/{id}/views/{view_id}/level1 — L1 graph with
       script + table nodes
    5. GET  /api/workspace/{id}/views/{view_id}/level2 — L2 graph with
       table + field nodes
    6. DELETE /api/workspace/{id} — teardown, workspace really gone
    """
    client, ws_id, file_tree = journey_ws

    # ── Step 1: upload response shape ──────────────────────────────────
    assert len(ws_id) == 12 and ws_id.isalnum(), ws_id
    assert file_tree["type"] == "directory"
    sql_paths = _collect_sql_paths(file_tree)
    assert sql_paths == EXPECTED_SCRIPTS, sql_paths
    # The zip's CSV is present but must NOT be flagged as SQL
    assert "multi_workflow/filter_tables.csv" in _collect_non_sql_paths(file_tree)

    # ── Step 2: index ──────────────────────────────────────────────────
    r = client.post(f"/api/workspace/{ws_id}/index", json={"scripts": sql_paths})
    assert r.status_code == 200, r.text
    idx = r.json()
    assert idx["script_count"] == len(EXPECTED_SCRIPTS), idx
    assert idx["errors"] == [], idx
    # R20 contract: orphan count + resolution_stats (keys match the
    # current folder_index_service.index_scripts response)
    assert idx["orphan_field_count"] == 0, idx          # MWF is fully qualified
    assert idx["orphan_field_samples"] == [], idx
    rs = idx["resolution_stats"]
    assert rs["total_columns"] == 26, rs                # 5 fixed scripts
    assert rs["resolved"] + rs["unresolved"] == rs["total_columns"], rs
    assert rs["unresolved"] == 0, rs
    assert rs["coverage_pct"] == 100.0, rs
    assert set(rs["by_strategy"]) == {
        "plain_alias", "expr_alias", "scope", "schema", "sys", "other",
    }, rs
    assert rs["by_strategy"]["expr_alias"] > 0, rs      # alias-qualified workflow
    scs = idx["schema_candidates_summary"]
    assert set(scs) == {"total", "unique_owner", "r6_collision"}, scs
    # The index actually contains the target table.field
    assert "stg_customers" in idx["table_index"], idx["table_index"]
    assert "customer_id" in idx["field_index"], idx["field_index"]

    # ── Step 3: search ─────────────────────────────────────────────────
    r = client.post(f"/api/workspace/{ws_id}/search",
                    json={"table": TARGET_TABLE, "field": TARGET_FIELD})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["table"] == TARGET_TABLE and s["field"] == TARGET_FIELD, s
    # Transitive closure pulls in all 5 scripts (step1..step5 are one
    # table-flow component), so the fixed fixture is deterministic here.
    assert s["match_mode"] == "expanded", s
    assert s["script_ids"] == EXPECTED_SCRIPTS, s
    assert s["l1_graph"]["nodes"] and s["l1_graph"]["edges"], s
    view_id = s["view_id"]
    assert view_id, s

    # ── Step 4: L1 graph (fresh rebuild from the saved view) ───────────
    r = client.get(f"/api/workspace/{ws_id}/views/{view_id}/level1")
    assert r.status_code == 200, r.text
    l1 = r.json()
    assert l1["view_id"] == view_id, l1
    assert l1["table"] == TARGET_TABLE and l1["field"] == TARGET_FIELD, l1
    assert l1["script_ids"] == EXPECTED_SCRIPTS, l1
    nodes, edges = l1["l1_graph"]["nodes"], l1["l1_graph"]["edges"]
    assert nodes and edges, l1
    node_types = {n["data"]["type"] for n in nodes}
    assert "script_node" in node_types, node_types
    assert node_types & {"source_table", "intermediate_table", "query_output",
                         "output_table"}, node_types
    for e in edges:
        assert e["data"]["edge_type"] in ("reads_from", "writes_to"), e

    # ── Step 5: L2 graph for the JOIN script ───────────────────────────
    r = client.get(f"/api/workspace/{ws_id}/views/{view_id}/level2",
                   params={"script": STEP3, "filter": "true"})
    assert r.status_code == 200, r.text
    l2 = r.json()
    assert l2["script_name"] == STEP3, l2
    assert "JOIN stg_customers sc ON" in l2["sql_text"], l2
    graph = l2["graph"]
    assert graph["nodes"] and graph["edges"], l2
    l2_types = {n["data"]["type"] for n in graph["nodes"]}
    assert "field" in l2_types, l2_types
    assert l2_types & {"source_table", "intermediate_table", "alias_table"}, l2_types
    assert l2["total_edges"] == len(graph["edges"]), l2
    assert isinstance(l2["highlights"], list) and l2["highlights"], l2

    # ── Step 6: teardown — workspace really deleted ────────────────────
    r = client.delete(f"/api/workspace/{ws_id}")
    assert r.status_code == 200, r.text
    assert r.json() == {"deleted": True}, r.text
    r = client.get(f"/api/workspace/{ws_id}")
    assert r.status_code == 404, r.text
