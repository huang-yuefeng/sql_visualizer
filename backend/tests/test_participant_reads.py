"""#380 (AD2-A, participant reads): GET /workspace/{ws_id}/tree + /index.

Defect: #380 made POST /scan + POST /index creator-only (correct per the
ruling — both rewrite shared workspace state) but they were the ONLY
endpoints serving the file tree and the table/field indexes, so a
PARTICIPANT clicking Open on a shared workspace 403'd and the workspace
never opened (AD2 verified live: /resume, /views, /autocomplete already 200
for a participant; scan/index 403).

Fix (read-only half): ``index_scripts`` persists the tree it covered
(cache/file_tree.json — the scan_folder shape including A1 ``file_class``)
and the derived report fields nothing on disk carried
(cache/index_report.json — script_count/errors/orphans/resolution_stats/
schema_candidates_summary/schema_evidence); the two GETs serve those
artifacts to ANY session with the /resume gates and NO creator check.

POST /scan stays creator-only — pinned here so the read endpoints cannot be
read as a relaxation of the #380 ruling.

In-process, login gate OFF (conftest), mirroring test_r31_auth.py.
"""

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402
from app.services import auth_service  # noqa: E402
from app.services.folder_index_service import scan_folder  # noqa: E402
from app.services.workspace_service import (  # noqa: E402
    WORKSPACE_ROOT, create_workspace, delete_workspace, get_workspace_dir,
)

client = TestClient(app)

OWNER = "owner@hsbc.com"
PARTICIPANT = "alice@hsbc.com"
PASSWORD = "secret1"

NO_TREE_MSG = ("This workspace has no stored file tree yet — "
               "the creator needs to open it once")

SCRIPTS = {
    "a.sql": "SELECT a FROM t1;\n",
    "b.sql": "SELECT b FROM t2;\n",
    # A1: a DDL-only file — the persisted tree must carry file_class so a
    # participant's script auto-select excludes it exactly like the
    # creator's inline tree does.
    "s.ddl": "CREATE TABLE s1 (c1 INT);\n",
}


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, sql in SCRIPTS.items():
            zf.writestr(name, sql)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _cleanup():
    """Restore the in-memory session store, the on-disk account index, and
    drop any test workspaces (same convention as test_r31_auth._cleanup —
    delete_workspace leaves the creator's users.json index row behind)."""
    auth_service.reset_for_tests()
    before = set(p.name for p in WORKSPACE_ROOT.iterdir())
    users_before = auth_service.load_users()
    yield
    auth_service.reset_for_tests()
    auth_service.save_users(users_before)
    for p in WORKSPACE_ROOT.iterdir():
        if p.is_dir() and p.name not in before:
            delete_workspace(p.name)


def _login(username):
    auth_service.provision_user(username, PASSWORD, force=True)
    r = client.post("/api/auth/login",
                    json={"username": username, "password": PASSWORD})
    assert r.status_code == 200, r.text


def _creator_indexes():
    """Creator uploads + indexes a real 3-file workspace (the Open flow the
    frontend runs today: POST /index → creator-only, writes the caches)."""
    ws_id = create_workspace(_zip_bytes(), creator_username=OWNER)
    _login(OWNER)
    r = client.post(f"/api/workspace/{ws_id}/index", json={"scripts": []})
    assert r.status_code == 200, r.text
    return ws_id, r.json()


# --- the participant Open path ---------------------------------------------

def test_participant_reads_tree_and_index():
    """The participant half of Open: both reads 200 with real content."""
    ws_id, created = _creator_indexes()
    _login(PARTICIPANT)

    r = client.get(f"/api/workspace/{ws_id}/tree")
    assert r.status_code == 200, r.text
    tree = r.json()
    # the persisted tree IS the tree the index covered — identical to a
    # fresh scan_folder of the same workspace (sorted, A1 file_class kept)
    assert tree == scan_folder(ws_id)
    classes = {n["name"]: n.get("file_class") for n in tree["children"]}
    assert classes == {"a.sql": "script", "b.sql": "script",
                       "s.ddl": "schema"}, classes

    r = client.get(f"/api/workspace/{ws_id}/index")
    assert r.status_code == 200, r.text
    idx = r.json()
    # real index content, not {} padding
    assert set(idx["table_index"]) == {"t1", "t2"}, idx["table_index"]
    assert set(idx["field_index"]) == {"a", "b"}, idx["field_index"]
    assert idx["table_index"]["t1"]["scripts"] == ["a.sql"]
    assert idx["field_index"]["b"]["scripts"] == ["b.sql"]
    # index status is served, so the UI knows the workspace is indexed
    assert idx["indexed"]["indexed"] is True
    assert idx["indexed"]["script_count"] == 2
    # the derived report fields survive for the participant — a blank
    # ResolutionReport is the defect this endpoint closes
    assert idx["script_count"] == 2
    assert idx["errors"] == []
    assert idx["orphan_field_count"] == 0
    assert idx["orphan_field_samples"] == []
    assert idx["schema_candidates_summary"] == {"total": 0, "unique_owner": 0,
                                                "r6_collision": 0}
    assert idx["schema_evidence"]["present"] is True
    assert idx["schema_evidence"]["tables"] == 1  # s1, from the DDL evidence
    # the served report equals the creator's POST /index report — one dict,
    # two consumers, never a divergent copy
    assert idx["resolution_stats"] == created["resolution_stats"]
    assert idx["orphan_field_samples"] == created["orphan_field_samples"]
    assert idx["schema_evidence"] == created["schema_evidence"]


def test_participant_scan_still_creator_only():
    """#380 stands: the reads are additive, POST /scan + /index stay 403."""
    ws_id, _ = _creator_indexes()
    _login(PARTICIPANT)
    r = client.post(f"/api/workspace/{ws_id}/scan")
    assert r.status_code == 403
    assert "creator" in r.json()["detail"]
    assert client.post(f"/api/workspace/{ws_id}/index",
                       json={"scripts": []}).status_code == 403


# --- missing / malformed states --------------------------------------------

def test_tree_missing_before_first_index():
    """A pre-existing workspace (uploaded, never indexed by this build) has
    no cache/file_tree.json — 409 with the actionable message, not 403."""
    ws_id = create_workspace(_zip_bytes(), creator_username=OWNER)
    _login(PARTICIPANT)
    r = client.get(f"/api/workspace/{ws_id}/tree")
    assert r.status_code == 409
    assert r.json()["detail"] == NO_TREE_MSG
    # the index read does NOT 409 — empty indexes + honest not-indexed status
    r = client.get(f"/api/workspace/{ws_id}/index")
    assert r.status_code == 200
    body = r.json()
    assert body["table_index"] == {} and body["field_index"] == {}
    assert body["indexed"]["indexed"] is False
    # no report on disk → no invented zeros (no padding)
    assert "resolution_stats" not in body and "script_count" not in body


def test_corrupt_index_cache_reads_empty_never_500():
    """A corrupt table_index.json reads as {} — the same convention as
    /autocomplete; a poisoned cache must not break the participant's Open."""
    ws_id, _ = _creator_indexes()
    cache_dir = get_workspace_dir(ws_id) / "cache"
    (cache_dir / "table_index.json").write_text("{not json")
    (cache_dir / "index_report.json").write_text("[]")  # wrong shape, valid JSON
    _login(PARTICIPANT)
    r = client.get(f"/api/workspace/{ws_id}/index")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["table_index"] == {}
    assert body["field_index"]  # the uncorrupted sibling is still served
    # a non-dict index_report is treated as absent — no report fields
    assert "resolution_stats" not in body


def test_corrupt_tree_file_reads_409_not_500():
    ws_id, _ = _creator_indexes()
    (get_workspace_dir(ws_id) / "cache" / "file_tree.json").write_text("{oops")
    _login(PARTICIPANT)
    r = client.get(f"/api/workspace/{ws_id}/tree")
    assert r.status_code == 409
    assert r.json()["detail"] == NO_TREE_MSG


# --- gate parity with /resume ----------------------------------------------

@pytest.mark.parametrize("path", ["/tree", "/index"])
def test_invalid_ws_id_400(path):
    _login(PARTICIPANT)
    assert client.get(f"/api/workspace/not-a-valid-id{path}").status_code == 400


@pytest.mark.parametrize("path", ["/tree", "/index"])
def test_unknown_workspace_404(path):
    _login(PARTICIPANT)
    assert client.get(f"/api/workspace/{'0' * 32}{path}").status_code == 404


@pytest.mark.parametrize("path", ["/tree", "/index"])
def test_gate_on_requires_session(monkeypatch, path):
    """401 gate parity with /resume: no valid session under REQUIRE_LOGIN →
    401 before any workspace lookup (the autouse cleanup has already emptied
    the session store, so a stale cookie from an earlier login is dead)."""
    monkeypatch.setattr("app.routers.workspace.REQUIRE_LOGIN", True)
    assert client.get(f"/api/workspace/{'a' * 32}{path}").status_code == 401


def test_index_report_on_disk_carries_resolution_stats():
    """The persistence half of the fix: cache/index_report.json is written
    next to table_index.json and carries resolution_stats — the fields
    nothing else on disk holds (orphan_fields.json has the orphan set only,
    meta.json only the indexed flag), so a participant's report is not blank
    even without an index-time HTTP response to read."""
    ws_id, created = _creator_indexes()
    report = json.loads(
        (get_workspace_dir(ws_id) / "cache" / "index_report.json").read_text())
    assert set(report) == {
        "script_count", "errors", "orphan_field_count",
        "orphan_field_samples", "resolution_stats",
        "schema_candidates_summary", "schema_evidence",
    }
    rs = report["resolution_stats"]
    assert rs["total_columns"] == 2, rs
    assert rs["resolved"] == 2 and rs["unresolved"] == 0
    assert rs["coverage_pct"] == 100.0
    assert "ambiguous" in rs and "by_strategy" in rs
    assert report == {k: created[k] for k in report}
    # the tree on disk is the tree this index covered
    tree = json.loads(
        (get_workspace_dir(ws_id) / "cache" / "file_tree.json").read_text())
    assert tree == scan_folder(ws_id)
