"""Direction contract over real HTTP — K4 ruling 4 (2026-08-28).

R29 (2026-08-12) introduced the directional projection (upstream = the
field's WRITING flow, downstream = the byte-identical legacy READING flow)
and defaulted the API to "upstream". R38 (v3.3.180) then removed the
frontend Upstream/Downstream switch and declared "downstream" the only
direction — but the API kept defaulting to, and honoring, "upstream", so a
direct API caller (or any client still sending the legacy value) got a
DIFFERENT graph than the UI for the same search.

K4 ruling 4 closes that gap at the router boundary:

  * an ABSENT `direction` → "downstream";
  * a legacy "upstream" → COERCED to "downstream" (accepted, never
    honored — the R38 legacy treatment);
  * "downstream" → unchanged;
  * anything else ("UPSTREAM", a typo, an empty string, a non-string JSON
    value such as a dict/list) → 400.

The upstream walker machinery below the router is untouched
(API-unreachable now; its retirement is a separate work item). The
explicit-upstream journey tests that used to live here were RETIRED with
this ruling — they pinned the pre-R38 default and are unreachable over
HTTP; the ONE coercion test below keeps the whole journey covered.

This test drives the real FastAPI app through TestClient over the actual
samples/sql_sample_v1 workspace (the 3-script workspace of the four
GROUND_TRUTH docs — the R29 flagship):

  upload (zip) → index → POST /search (direction) → GET /level1 (direction
  echo + persistence + ?direction override) → delete

Assertions are grounded in the R29 ground truth docs, NOT in any engine
output: bdm_acc_loan_info.lending_ref downstream = the transitive reading
closure (GROUND_TRUTH_BDM_ACC_LOAN_INFO_LENDING_REF.md §2.2) = {DL, PL,
SUP_M}; rrcdm_job_log_exec_par.data_dt downstream = the writer's own leg
(GROUND_TRUTH_RRCDM_JOB_LOG_EXEC_PAR.md §2.2), never empty.

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
PL = "BDM_ACC_LOAN_INFO_PL.sql"
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
    http_client.delete(f"/api/me/workspaces/{ws_id}")


def _search(client, ws_id, table, field, direction):
    r = client.post(f"/api/workspace/{ws_id}/search",
                    json={"table": table, "field": field, "direction": direction})
    assert r.status_code == 200, r.text
    return r.json()


def _script_labels(graph) -> set:
    return {n["data"]["label"] for n in graph["nodes"]
            if n["data"]["type"] == "script_node"}


# ══════════════════════════════════════════════════════════════════════
# CR2: direction validated once at the router boundary (400 on anything
# outside {upstream, downstream}); absent → "downstream" (K4 ruling 4).
# ══════════════════════════════════════════════════════════════════════

def test_search_invalid_direction_400(r29_ws):
    """CR2: a typo / uppercase / empty direction is a 400, never a silent
    fall-through to a branch."""
    client, ws_id, _ = r29_ws
    for bad in ("UPSTREAM", "sideways", ""):
        r = client.post(f"/api/workspace/{ws_id}/search",
                        json={"table": "bdm_acc_loan_info",
                              "field": "lending_ref",
                              "direction": bad})
        assert r.status_code == 400, (bad, r.status_code, r.text)
    # Absent direction → "downstream" (K4 ruling 4 — the only direction).
    r = client.post(f"/api/workspace/{ws_id}/search",
                    json={"table": "bdm_acc_loan_info", "field": "lending_ref"})
    assert r.status_code == 200, r.text
    assert r.json()["direction"] == "downstream", r.json()


def test_search_non_string_direction_400_not_500(r29_ws):
    """A JSON body may carry a NON-STRING `direction` (dict / list / number /
    bool — `body: dict` passes them straight through). The guard must type-
    check BEFORE the allowlist membership test: `{"x": 1} in {"upstream",
    "downstream"}` raises TypeError (unhashable operand) and surfaced as a
    500 instead of the contract 400.
    """
    client, ws_id, _ = r29_ws
    for bad in ({"x": 1}, ["upstream"], {"direction": "upstream"}, 7, True):
        r = client.post(f"/api/workspace/{ws_id}/search",
                        json={"table": "bdm_acc_loan_info",
                              "field": "lending_ref",
                              "direction": bad})
        assert r.status_code == 400, (bad, r.status_code, r.text)
        assert "must be 'downstream'" in r.json()["detail"], (bad, r.text)


# ══════════════════════════════════════════════════════════════════════
# K4 ruling 4: a legacy "upstream" request is COERCED — accepted, never
# honored. The one journey test that survives the ruling.
# ══════════════════════════════════════════════════════════════════════

def test_search_upstream_request_coerced_to_downstream(r29_ws):
    """direction:"upstream" → the DOWNSTREAM graph + a "downstream" echo.

    Seed: bdm_acc_loan_info.lending_ref downstream = the transitive reading
    closure (GROUND_TRUTH_BDM_ACC_LOAN_INFO_LENDING_REF.md §2.2) — the
    writer DL (A.acctnbr AS LENDING_REF @101), the writer PL (LENDING_REF
    @21) and the reader SUP_M (p1.lending_ref). The pre-ruling upstream
    projection kept the reader OUT (writers only) — the coercion must NOT
    return that graph. F5 (audit #383, R2.10) resolves the field
    CASE-INSENSITIVELY, so the matching set is the union of the case
    variants = doc §2.2's {DL, PL, SUP_M}.
    """
    client, ws_id, _ = r29_ws

    s = _search(client, ws_id, "bdm_acc_loan_info", "lending_ref", "upstream")
    assert s["direction"] == "downstream", s
    assert s["match_mode"] == "exact", s
    assert s["script_ids"] == [DL, PL, SUP_M], s
    l1 = s["l1_graph"]
    assert l1.get("flow_empty") is False, l1
    # The reading closure — NOT the writers-only upstream projection.
    assert _script_labels(l1) == {DL, PL, SUP_M}, l1
    view_id = s["view_id"]

    # The coerced value is what persists, so a reload restores downstream.
    r = client.get(f"/api/workspace/{ws_id}/views/{view_id}/level1")
    assert r.status_code == 200, r.text
    l1r = r.json()
    assert l1r["direction"] == "downstream", l1r
    assert _script_labels(l1r["l1_graph"]) == {DL, PL, SUP_M}, l1r

    # A legacy ?direction=upstream override on the SAME view is coerced too.
    r = client.get(f"/api/workspace/{ws_id}/views/{view_id}/level1",
                   params={"direction": "upstream"})
    assert r.status_code == 200, r.text
    l1o = r.json()
    assert l1o["direction"] == "downstream", l1o
    assert _script_labels(l1o["l1_graph"]) == {DL, PL, SUP_M}, l1o


# ══════════════════════════════════════════════════════════════════════
# Downstream guard (explicit downstream — unchanged by the ruling): the
# writer's own leg is a real reading flow, never a false "no flow" pin.
# ══════════════════════════════════════════════════════════════════════

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
    assert _script_labels(l1) == set(SAMPLE_NAMES), l1
    assert {n["data"].get("table_name") for n in l1["nodes"]
            if n["data"].get("table_name")} == {"rrcdm_job_log_exec_par"}, l1
