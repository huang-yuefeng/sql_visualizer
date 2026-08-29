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
    # R31/A-M1: the remove-from-my-history endpoint (creator → physical delete)
    http_client.delete(f"/api/me/workspaces/{ws_id}")


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
    assert len(ws_id) == 32 and ws_id.isalnum(), ws_id  # R31/A-H4
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
    # R44 (2026-08-28, user ruling "walker occurrence coverage"): 26 → 44.
    # 26 source reads + 16 write-target twins + 2 GROUP BY twins.
    # +16 write-target twins — every DML-written column now exists as a
    # column var ({target}.{projection}: stg_orders ×5, stg_customers ×4,
    # analytics_orders ×6, daily_summary ×1). Naming a column in an INSERT
    # list / writing a projection into a target is authored SQL text =
    # positive evidence, NOT a guess: INSERT-target attribution is allowed
    # under the occurrence-coverage ruling; the s4 never-guess principle
    # governs scope-INFERRED attribution only.
    # +2 GROUP BY twins (EXTRACTOR_VERSION 2026-08-28.4, `_register_groupby_twins`,
    # R44 family #3): step4's `GROUP BY DATE(ao.order_date), ao.region` (L5)
    # registers `analytics_orders.order_date` + `analytics_orders.region` —
    # each GROUP BY item names a real column with a resolved physical owner
    # (authored SQL text, same positive-evidence basis as the INSERT list).
    # +10 R45 family-3 occurrence-line twins (EXTRACTOR_VERSION
    # 2026-08-28.6, `_register_flow_occurrence_twins` family 3): a column
    # referenced twice inside one statement used to register ONE var (the
    # `_add` (name, type, context) dedup), so the second occurrence — a 2nd
    # WHEN arm, an NVL fallback operand, a byte-identical projection, a
    # later JOIN-key leg — left no node at its own line. Family 3 re-anchors
    # each collapsed occurrence as an occurrence-side twin attributed to the
    # same owner the surviving var resolved to (same positive-evidence basis
    # as the write-target and GROUP BY twins above: authored SQL text, never
    # a scope-inferred guess).
    # 8, not 10 (EXTRACTOR_VERSION 2026-08-28.8, R45 Fixes C–G — ruling):
    # the .6 handout minted 2 twins that were NOT occurrences of the group
    # it handed them to — one grabbed a line OUTSIDE its own paren scope,
    # one was the group's duplicate registration of a field whose line was
    # already anchored, and both stole the free line a genuine occurrence
    # needed. Fixes C/G bound the line search to the group's own scope and
    # its own qualifier's occurrences, Fix F treats a line any same-field
    # var anchors as taken, Fix E pairs a collapsed occurrence to a line of
    # ITS OWN clause. Nothing replaced the two: a line where the field does
    # not occur is not an occurrence. Each of the 8 remaining twins sits on
    # a line where its field textually occurs, in the clause its
    # `defined_in` names — SQL-true, verified per script.
    # 52 = 26 source reads + 16 write twins (stg_orders ×5,
    # stg_customers ×4, analytics_orders ×6, daily_summary ×1)
    # + 2 GROUP BY twins + 8 occurrence twins — re-derived from the tree
    # 2026-08-29 (R4 L): every bucket counted off the extracted vars, and
    # the write-twin per-target split matches the list above.
    assert rs["total_columns"] == 52, rs                # 5 fixed scripts
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
                    json={"table": TARGET_TABLE, "field": TARGET_FIELD,
                          # R29 (2026-08-13): the router default direction
                          # is now "upstream"; this journey pins the
                          # DOWNSTREAM (reading) projection — step2 writes
                          # the seed + step3 reads it as a join key.
                          "direction": "downstream"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["table"] == TARGET_TABLE and s["field"] == TARGET_FIELD, s
    # R29 (2026-08-12): the search returns the queried field's strict
    # directional flow projection (match_mode "exact" — the R22
    # no-matches/legacy marker, not a closure-size label). `script_ids`
    # is the MATCHING set (field ∩ table scripts) — direction
    # independent: step2 writes the seed AND step3 reads it as a join
    # key, so both match. The L1 GRAPH below is the downstream (reading)
    # projection: per the formal definition, downstream = the fields that
    # USE Y (the transitive effect scope), walked forward from Y — so the
    # downstream L1 carries only the CONSUMING script (step3); the
    # producing script (step2) is the upstream side.
    assert s["match_mode"] == "exact", s
    assert s["script_ids"] == [
        "multi_workflow/step2_enrich_customers.sql",
        "multi_workflow/step3_join_orders_customers.sql",
    ], s
    assert s["l1_graph"]["nodes"] and s["l1_graph"]["edges"], s
    view_id = s["view_id"]
    assert view_id, s

    # ── Step 4: L1 graph (fresh rebuild from the saved view) ───────────
    r = client.get(f"/api/workspace/{ws_id}/views/{view_id}/level1")
    assert r.status_code == 200, r.text
    l1 = r.json()
    assert l1["view_id"] == view_id, l1
    assert l1["table"] == TARGET_TABLE and l1["field"] == TARGET_FIELD, l1
    assert l1["script_ids"] == [
        "multi_workflow/step2_enrich_customers.sql",
        "multi_workflow/step3_join_orders_customers.sql",
    ], l1
    nodes, edges = l1["l1_graph"]["nodes"], l1["l1_graph"]["edges"]
    assert nodes and edges, l1
    node_types = {n["data"]["type"] for n in nodes}
    assert "script_node" in node_types, node_types
    assert node_types & {"source_table", "intermediate_table", "query_output",
                         "output_table"}, node_types
    for e in edges:
        assert e["data"]["edge_type"] in ("reads_from", "writes_to"), e
    # R29 + R44 (2026-08-28): the downstream L1 is the seed's occurrence
    # projection. R29 kept it to the CONSUMING script only (step3: the
    # seed read as a join key → analytics_orders). R44's occurrence
    # coverage adds the seed's WRITE occurrence: the write-side twin
    # stg_customers.customer_id (step2's INSERT projection) is an
    # occurrence of the searched field, so step2's table-level write leg
    # renders (write-completion) together with its feeding read
    # (crm_customers.customer_id — the value's origin): crm_customers
    # →(step2)→ stg_customers →(step3)→ analytics_orders, 5 hops.
    # step1/4/5 never touch the field.
    assert {n["data"]["label"] for n in nodes
            if n["data"]["type"] == "script_node"} == {
        "multi_workflow/step2_enrich_customers.sql",
        "multi_workflow/step3_join_orders_customers.sql",
    }, nodes
    assert {n["data"].get("table_name") for n in nodes
            if n["data"]["type"] != "script_node"} == {
        "crm_customers", "stg_orders", "stg_customers", "analytics_orders"}, nodes
    assert len(edges) == 5, len(edges)

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
    # W5/R25: the response-level `highlights` list is GONE — every edge
    # carries its own payload (highlight_line / flow_kind / reason), and the
    # level2 response adds statement-level parse_errors diagnostics.
    assert "highlights" not in l2, l2
    assert isinstance(l2.get("parse_errors"), list), l2
    for e in graph["edges"]:
        d = e["data"]
        assert d.get("highlight_line", 0) >= 1, d
        assert d.get("flow_kind"), d
        assert d.get("reason"), d

    # ── Step 6: teardown — workspace really deleted ────────────────────
    # R31/A-M1: role-dependent remove — the HTTP-created workspace belongs
    # to dev-user (its creator), so this is a physical delete.
    r = client.delete(f"/api/me/workspaces/{ws_id}")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True, r.text
    r = client.get(f"/api/workspace/{ws_id}")
    assert r.status_code == 404, r.text
