"""R31 login gate — verified in a SUBPROCESS with REQUIRE_LOGIN=true.

The gate is a module-import-time config read (app.config / main.py /
workspace.py), so it can only be exercised in a fresh process. Running the
probe as a subprocess keeps the main suite (gate OFF) untouched and gives
the gate-on behavior a real, isolated test.
"""

import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services import heavy_gate
from app.services.workspace_service import (
    WORKSPACE_ROOT, create_workspace, delete_workspace, get_workspace_dir,
    read_meta,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROBE = Path(__file__).resolve().parent / "r31_probe.py"

client = TestClient(app)


def _zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("t1.sql", "SELECT a FROM t1;\n")
    return buf.getvalue()


def _make_indexed_workspace() -> str:
    """A workspace whose meta says indexed + hand-written cache index files,
    enough for POST .../search to reach the heavy-op gate."""
    ws_id = create_workspace(_zip_bytes(), creator_username="dev-user")
    meta = read_meta(ws_id)
    meta["indexed"] = True
    (WORKSPACE_ROOT / ws_id / "meta.json").write_text(json.dumps(meta))
    cache_dir = get_workspace_dir(ws_id) / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "table_index.json").write_text(
        json.dumps({"t1": {"scripts": ["t1.sql"]}}))
    (cache_dir / "field_index.json").write_text(
        json.dumps({"a": {"scripts": ["t1.sql"]}}))
    return ws_id


# --- R31 (#273): the heavy-op gate ----------------------------------------

def test_heavy_gate_serializes():
    assert heavy_gate.try_acquire() is True
    assert heavy_gate.try_acquire() is False
    heavy_gate.release()
    assert heavy_gate.try_acquire() is True
    heavy_gate.release()


def test_analyze_busy_returns_409_then_succeeds():
    # While the gate is held, /api/analyze returns 409 "system busy"; after
    # release the same call succeeds — proves the gate is wired into the
    # handler and released (the handler only releases what it acquired).
    assert heavy_gate.try_acquire() is True
    try:
        r = client.post("/api/analyze", data={"sql_text": "SELECT 1"})
        assert r.status_code == 409
        assert r.json()["detail"] == "system busy — please wait"
    finally:
        heavy_gate.release()
    r = client.post("/api/analyze", data={"sql_text": "SELECT 1"})
    assert r.status_code == 200


def test_search_busy_returns_409_then_succeeds():
    # A held gate refuses a debugger search with 409 BEFORE any graph build;
    # after release the same search succeeds.
    ws_id = _make_indexed_workspace()
    try:
        assert heavy_gate.try_acquire() is True
        try:
            r = client.post(f"/api/workspace/{ws_id}/search",
                            json={"table": "t1", "field": "a"})
            assert r.status_code == 409
            assert r.json()["detail"] == "system busy — please wait"
        finally:
            heavy_gate.release()
        r = client.post(f"/api/workspace/{ws_id}/search",
                        json={"table": "t1", "field": "a"})
        assert r.status_code == 200
    finally:
        delete_workspace(ws_id)


def test_login_gate_contract():
    env = dict(os.environ)
    env["REQUIRE_LOGIN"] = "true"
    env["PYTHONPATH"] = str(BACKEND_DIR)
    r = subprocess.run(
        [sys.executable, str(PROBE)],
        capture_output=True, text=True, env=env, timeout=180,
    )
    assert r.returncode == 0, f"gate probe failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    assert "GATE PROBE PASS" in r.stdout
