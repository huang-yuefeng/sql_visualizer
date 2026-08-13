"""CW-R29 / CR9: router-level direction journey test over real HTTP.

The full-HTTP suite (test_full_http_journey.py) drives the complete user
flow end-to-end but only for the DEFAULT direction. R29 (2026-08-12)
introduced the directional projection (upstream = the field's WRITING
flow, downstream = the byte-identical legacy READING flow) and CR9 closes
the router-level gap: the direction value must be validated at the
boundary, echoed on /search, persisted on the view, restored on GET
/level1|/level2, and honored by the L2 not-in-flow message + the R29 role
flip.

This test drives the real FastAPI app through TestClient over the actual
samples/sql_sample_v1 workspace (the 3-script workspace of the four
GROUND_TRUTH docs — the R29 flagship):

  upload (zip) → index → POST /search (direction) → GET /level1 (direction
  echo + persistence + ?direction override) → GET /level2 (upstream
  writing-flow message + role flip) → no_flow case → delete

Assertions are grounded in the R29 ground truth docs, NOT in any engine
output:

  * bdm_acc_loan_info.lending_ref upstream = the transitive WRITING chain
    (GROUND_TRUTH_BDM_ACC_LOAN_INFO_LENDING_REF.md §2.1/§3.1): only
    BDM_ACC_LOAN_INFO_Digitallending.sql WRITES the field. SUP_M reads it
    (p1.lending_ref) but never writes it — it is in the matching script
    set (it touches table+field) yet absent from the upstream L1 graph,
    and its L2 renders the "not in the writing flow" state.
  * ods_hie_ipacmsp.iiapty upstream = EMPTY (ODS source, no writers —
    GROUND_TRUTH_ODS_HIE_IPACMSP.md §2.1): match_mode "no_flow", and the
    persisted view re-projects to the non-empty downstream closure when
    GET /level1 is called with ?direction=downstream (CR3).

Teardown deletes the workspace on both success and failure.
"""

import io
import sys
import zipfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
SAMPLES_DIR = BACKEND_DIR.parent / "samples"
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402

SAMPLE_DIR = SAMPLES_DIR / "sql_sample_v1"
SAMPLE_NAMES = [
    "BDM_ACC_LOAN_INFO_PL.sql",
    "BDM_ACC_LOAN_INFO_Digitallending.sql",
    "BDM_ACC_LOAN_INFO_SUP_M.sql",
]

DL = "BDM_ACC_LOAN_INFO_Digitallending.sql"
SUP_M = "BDM_ACC_LOAN_INFO_SUP_M.sql"


def _collect_sql_paths(tree: dict) -> list:
    """Collect is_sql file paths from a scan_folder-style file tree."""
    paths = []
    if tree.get("type") == "file" and tree.get("is_sql"):
        paths.append(tree["path"])
    for child in tree.get("children", []):
        paths.extend(_collect_sql_paths(child))
    return paths


@pytest.fixture(scope="module")
def http_client():
    """FastAPI TestClient over the real app (starlette in the image)."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def r29_ws(http_client):
    """R29 flagship workspace over HTTP: the 3 sql_sample_v1 scripts.

    Uploads samples/sql_sample_v1 as a zip (top-level file names) then
    indexes all three. Yields (client, ws_id, sql_paths). Teardown DELETEs
    the workspace over HTTP (idempotent).
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in SAMPLE_NAMES:
            zf.write(SAMPLE_DIR / name, name)
    r = http_client.post(
        "/api/workspace",
        files={"file": ("sql_sample_v1.zip", buf.getvalue(), "application/zip")},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    ws_id = payload["workspace_id"]
    sql_paths = _collect_sql_paths(payload["file_tree"])
    assert set(sql_paths) == set(SAMPLE_NAMES), sql_paths
    r = http_client.post(f"/api/workspace/{ws_id}/index",
                         json={"scripts": sql_paths})
    assert r.status_code == 200, r.text
    assert r.json().get("script_count") == 3, r.text
    yield http_client, ws_id, sql_paths
    http_client.delete(f"/api/workspace/{ws_id}")


def _search(client, ws_id, table, field, direction):
    r = client.post(f"/api/workspace/{ws_id}/search",
                    json={"table": table, "field": field, "direction": direction})
    assert r.status_code == 200, r.text
    return r.json()


def _table_node_by_name(graph, table_name):
    return next((n["data"] for n in graph["nodes"]
                 if n["data"].get("table_name") == table_name), None)


# ══════════════════════════════════════════════════════════════════════
# CR2: direction validated once at the router boundary (400 on anything
# outside {upstream, downstream}); default when absent is "upstream".
# ══════════════════════════════════════════════════════════════════════

def test_search_invalid_direction_400(r29_ws):
    """CR2: a typo / uppercase / empty direction is a 400, never a silent
    fall-through to the downstream branch."""
    client, ws_id, _ = r29_ws
    for bad in ("UPSTREAM", "sideways", ""):
        r = client.post(f"/api/workspace/{ws_id}/search",
                        json={"table": "bdm_acc_loan_info",
                              "field": "lending_ref",
                              "direction": bad})
        assert r.status_code == 400, (bad, r.status_code, r.text)
    # Absent direction defaults to upstream (the documented R29 default).
    r = client.post(f"/api/workspace/{ws_id}/search",
                    json={"table": "bdm_acc_loan_info", "field": "lending_ref"})
    assert r.status_code == 200, r.text
    assert r.json()["direction"] == "upstream", r.json()


# ══════════════════════════════════════════════════════════════════════
# Direction echo + persistence + override over the real HTTP journey.
# ══════════════════════════════════════════════════════════════════════

def test_search_direction_echo_persist_and_l1_override(r29_ws):
    """POST /search echoes direction; GET /level1 restores the persisted
    direction on reload and honors an explicit ?direction override.

    Seed: bdm_acc_loan_info.lending_ref upstream = the WRITING chain
    (GROUND_TRUTH_BDM_ACC_LOAN_INFO_LENDING_REF.md §2.1). Matching script
    set = {DL, SUP_M} (both touch table+field), but the upstream L1
    projection contains ONLY the writer DL — SUP_M reads the field, it is
    not in the writing flow.
    """
    client, ws_id, _ = r29_ws

    s = _search(client, ws_id, "bdm_acc_loan_info", "lending_ref", "upstream")
    assert s["direction"] == "upstream", s
    assert s["match_mode"] == "exact", s
    # The matching set (field ∩ table scripts), NOT the directional graph's
    # script set — SUP_M touches the field but is absent from the upstream
    # L1 graph (asserted below).
    assert s["script_ids"] == [DL, SUP_M], s
    l1 = s["l1_graph"]
    assert l1.get("flow_empty") is False, l1
    assert {n["data"]["label"] for n in l1["nodes"]
            if n["data"]["type"] == "script_node"} == {DL}, l1
    view_id = s["view_id"]

    # GET /level1 without a direction param restores the persisted one.
    r = client.get(f"/api/workspace/{ws_id}/views/{view_id}/level1")
    assert r.status_code == 200, r.text
    l1r = r.json()
    assert l1r["direction"] == "upstream", l1r
    assert l1r["script_ids"] == [DL, SUP_M], l1r
    assert l1r["l1_graph"].get("flow_empty") is False, l1r
    assert {n["data"]["label"] for n in l1r["l1_graph"]["nodes"]
            if n["data"]["type"] == "script_node"} == {DL}, l1r

    # GET /level1 with an explicit ?direction override re-projects.
    r = client.get(f"/api/workspace/{ws_id}/views/{view_id}/level1",
                   params={"direction": "downstream"})
    assert r.status_code == 200, r.text
    l1d = r.json()
    assert l1d["direction"] == "downstream", l1d
    # Downstream lending_ref = the transitive effect scope (doc §2.2,
    # REPAIRED 2026-08-12): the READING flow starts at the READ instances,
    # which live ONLY in SUP_M (the sup-write statement's join-key usages).
    # DL/PL carry the seed's WRITE instance (the upstream side) — the
    # mirror of the upstream projection.
    assert {n["data"]["label"] for n in l1d["l1_graph"]["nodes"]
            if n["data"]["type"] == "script_node"} == {SUP_M}, l1d


# ══════════════════════════════════════════════════════════════════════
# Upstream L2: the "not in the writing flow" message + the R29 role flip.
# ══════════════════════════════════════════════════════════════════════

def test_l2_upstream_writing_flow_message(r29_ws):
    """GET /level2 on the upstream view for a script that READS but never
    WRITES the seed → search_matched False + the writing-flow message
    (dataflow_service._not_in_flow branch), with the full graph fallback.
    """
    client, ws_id, _ = r29_ws
    s = _search(client, ws_id, "bdm_acc_loan_info", "lending_ref", "upstream")
    view_id = s["view_id"]

    r = client.get(f"/api/workspace/{ws_id}/views/{view_id}/level2",
                   params={"script": SUP_M, "filter": "true"})
    assert r.status_code == 200, r.text
    l2 = r.json()
    assert l2["search_matched"] is False, l2
    assert l2["message"] == (
        f"Script {SUP_M} is not in the writing flow of "
        "bdm_acc_loan_info.lending_ref — the field is not written in this "
        "script. Showing the full script graph."
    ), l2
    # The not-in-flow fallback keeps the panel useful: the FULL graph.
    assert l2["graph"]["nodes"] and l2["graph"]["edges"], l2


def test_l2_upstream_writing_flow_role_flip(r29_ws):
    """R29 role flip on the upstream L2 (l2_builder._attach_flow_roles):
    the searched table's WRITE instance is the flow_target, and the
    producing tables (the writing chain start) are the flow_sources —
    the inverse of the downstream reading-flow roles.

    Seed: bdm_acc_loan_info.lending_ref upstream inside
    BDM_ACC_LOAN_INFO_Digitallending.sql (doc §3.1): the chain runs
    ods_ccb_cb_loan_acctloan (A) → LENDING_REF → bdm_acc_loan_info.
    """
    client, ws_id, _ = r29_ws
    s = _search(client, ws_id, "bdm_acc_loan_info", "lending_ref", "upstream")
    view_id = s["view_id"]

    r = client.get(f"/api/workspace/{ws_id}/views/{view_id}/level2",
                   params={"script": DL, "filter": "true"})
    assert r.status_code == 200, r.text
    l2 = r.json()
    assert l2.get("search_matched", True) is not False, l2
    graph = l2["graph"]
    assert graph["nodes"] and graph["edges"], l2

    # The write target compound is the flow target (writing flow ENDS at
    # the write).
    bdm = _table_node_by_name(graph, "bdm_acc_loan_info")
    assert bdm is not None, graph
    assert bdm.get("flow_target") is True, bdm
    # The producing ODS source compound is the flow source (the chain
    # start — nobody in the workspace writes it).
    ods = _table_node_by_name(graph, "ods_ccb_cb_loan_acctloan")
    assert ods is not None, graph
    assert ods.get("flow_source") is True, ods


# ══════════════════════════════════════════════════════════════════════
# no_flow: the field IS in the scripts but the directional closure is
# empty → match_mode "no_flow" (message, not an error), and the persisted
# view re-projects to the opposite direction (CR3).
# ══════════════════════════════════════════════════════════════════════

def test_search_no_flow_upstream_and_downstream_reproject(r29_ws):
    """ods_hie_ipacmsp.iiapty upstream = EMPTY (ODS source, no writers —
    GROUND_TRUTH_ODS_HIE_IPACMSP.md §2.1). The search returns match_mode
    "no_flow" with the real matching scripts kept on the view (CR3), the
    L1 graph empty; a later GET /level1?direction=downstream re-projects
    to the non-empty reading closure.
    """
    client, ws_id, _ = r29_ws

    s = _search(client, ws_id, "ods_hie_ipacmsp", "iiapty", "upstream")
    assert s["match_mode"] == "no_flow", s
    assert s["message"] == "No writing flow for ods_hie_ipacmsp.iiapty", s
    assert s["direction"] == "upstream", s
    # CR3: the real matching scripts ride the no-flow view (SUP_M is the
    # only script that touches the field) so a direction switch re-projects.
    assert s["script_ids"] == [SUP_M], s
    assert s["l1_graph"]["nodes"] == [] and s["l1_graph"]["edges"] == [], s
    view_id = s["view_id"]

    # The persisted no-flow view restores the empty upstream projection.
    r = client.get(f"/api/workspace/{ws_id}/views/{view_id}/level1")
    assert r.status_code == 200, r.text
    l1 = r.json()
    assert l1["direction"] == "upstream", l1
    assert l1["l1_graph"].get("flow_empty") is True, l1
    assert l1["l1_graph"]["nodes"] == [], l1

    # CR3: the opposite direction on the SAME view re-projects to the
    # downstream closure (doc §2.2 — SUP_M reads iiapty as a join key).
    r = client.get(f"/api/workspace/{ws_id}/views/{view_id}/level1",
                   params={"direction": "downstream"})
    assert r.status_code == 200, r.text
    l1d = r.json()
    assert l1d["direction"] == "downstream", l1d
    assert l1d["script_ids"] == [SUP_M], l1d
    assert l1d["l1_graph"].get("flow_empty") is False, l1d
    assert {n["data"]["label"] for n in l1d["l1_graph"]["nodes"]
            if n["data"]["type"] == "script_node"} == {SUP_M}, l1d


def test_search_rrcdm_downstream_writers_own_leg_not_no_flow(r29_ws):
    """Guard against a false "no reading flow" pin: rrcdm_job_log_exec_par.
    data_dt is WRITTEN by all three scripts but never READ — yet the
    downstream projection is the WRITER'S OWN LEG (legacy W1 field-like
    semantics, GROUND_TRUTH_RRCDM_JOB_LOG_EXEC_PAR.md §2.2), NOT empty.
    match_mode is "exact", flow_empty is False (mirror of the pinned
    test_r29_rrcdm_data_dt_downstream_empty_matches_doc).
    """
    client, ws_id, _ = r29_ws
    s = _search(client, ws_id, "rrcdm_job_log_exec_par", "data_dt", "downstream")
    assert s["direction"] == "downstream", s
    assert s["match_mode"] == "exact", s
    assert "message" not in s, s
    assert set(s["script_ids"]) == set(SAMPLE_NAMES), s
    assert s["l1_graph"].get("flow_empty") is False, s
    # The writer's-own-leg projection = the three writing scripts + the
    # rrcdm table (the log statements' FROM inputs stay OUT).
    l1 = s["l1_graph"]
    assert {n["data"]["label"] for n in l1["nodes"]
            if n["data"]["type"] == "script_node"} == set(SAMPLE_NAMES), l1
    assert {n["data"].get("table_name") for n in l1["nodes"]
            if n["data"].get("table_name")} == {"rrcdm_job_log_exec_par"}, l1
