"""E4 security/robustness negative tests (Team D weakness review).

All tests run IN-PROCESS via starlette TestClient or direct service calls —
never real HTTP (the deployed service may be frozen; the suite must run
anywhere). Coverage:

  1. level2 `script` path traversal  → rejected with the existing
     not-found error shape; no file contents (arbitrary-read / cross-tenant
     disclosure) ever reach the response
  2. /highlight `script_name` with `..`/traversal → 404 (was IsADirectoryError 500)
  3. autocomplete `type` whitelist → 400 for traversal/unknown kinds
  4. graph cache extractor-version stamp: mismatch → rebuilt + restamped;
     matching version → served (no rebuild); corrupt cache → treated as a miss
  5. view persistence: concurrent _persist_search_view calls lose no view
  6. logger stderr print gated behind SQL_VIZ_LOG_STDERR (default off)
"""

import asyncio
import hashlib
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
from app.services.workspace_service import (  # noqa: E402
    create_workspace, delete_workspace, get_workspace_dir,
)
from app.services.folder_index_service import index_scripts  # noqa: E402
from app.services.cache_keys import GRAPH_CACHE_PREFIX  # noqa: E402
from app.extractor.variable_extractor_v2 import EXTRACTOR_VERSION  # noqa: E402

WORKFLOW_DIR = Path(__file__).resolve().parent.parent.parent / "samples" / "multi_workflow"

STEP3 = "step3_join_orders_customers.sql"
TARGET_TABLE = "stg_customers"
TARGET_FIELD = "customer_id"

# Unit-level workspace (no index needed — get_level2_graph self-builds).
UNIT_SQL = "SELECT customer_id FROM stg_customers;\n"
UNIT_SCRIPT = "v.sql"

# Traversal target: an absolute file the test itself controls.
SECRET_PATH = Path("/tmp/e4_secret_e4test.txt")
SECRET_CONTENT = "E4SECRET-MARKER-7f3a9c"


def _make_workflow_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(WORKFLOW_DIR.glob("step*.sql")):
            zf.write(f, f.name)
    return buf.getvalue()


def _make_unit_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(UNIT_SCRIPT, UNIT_SQL)
    return buf.getvalue()


@pytest.fixture(scope="module")
def http_client():
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="module")
def secure_env(http_client):
    """Indexed multi_workflow workspace + a search view (HTTP-level setup)."""
    r = http_client.post(
        "/api/workspace",
        files={"file": ("mw.zip", _make_workflow_zip(), "application/zip")},
    )
    assert r.status_code == 200, r.text
    ws_id = r.json()["workspace_id"]
    scripts = sorted(f.name for f in WORKFLOW_DIR.glob("step*.sql"))
    idx = http_client.post(f"/api/workspace/{ws_id}/index", json={"scripts": scripts})
    assert idx.status_code == 200, idx.text
    s = http_client.post(
        f"/api/workspace/{ws_id}/search",
        json={"table": TARGET_TABLE, "field": TARGET_FIELD},
    )
    assert s.status_code == 200, s.text
    view_id = s.json()["view_id"]
    yield http_client, ws_id, view_id
    http_client.delete(f"/api/workspace/{ws_id}")


@pytest.fixture
def unit_ws():
    """Single-script workspace; get_level2_graph self-builds everything."""
    ws_id = create_workspace(_make_unit_zip())
    yield ws_id
    delete_workspace(ws_id)


def _unit_cache_paths(ws_id: str) -> tuple[Path, Path]:
    ws_dir = get_workspace_dir(ws_id)
    sql_text = (ws_dir / "scripts" / UNIT_SCRIPT).read_text(encoding="utf-8")
    # #197: the analysis-key contract is versioned (md5 over
    # (EXTRACTOR_VERSION, script_name, sql_text)) — match the write side
    # (folder_index_service) exactly or the fixture is never found.
    key = hashlib.md5(
        (EXTRACTOR_VERSION + "|" + UNIT_SCRIPT + sql_text)
        .encode()).hexdigest()[:12]
    return (ws_dir / "cache" / f"{GRAPH_CACHE_PREFIX}_{key}.json",
            ws_dir / "cache" / f"schemas_{key}.json")


# ═══════════════════ 1. level2 script path traversal ═══════════════════

class TestLevel2ScriptTraversal:
    def test_absolute_path_rejected(self, secure_env, tmp_path):
        client, ws_id, view_id = secure_env
        SECRET_PATH.write_text(SECRET_CONTENT)
        try:
            r = client.get(
                f"/api/workspace/{ws_id}/views/{view_id}/level2",
                params={"script": str(SECRET_PATH)},
            )
        finally:
            SECRET_PATH.unlink(missing_ok=True)
        assert r.status_code == 200, r.text  # existing error shape, not a 500
        assert r.json() == {"error": f"Script '{SECRET_PATH}' not found"}, r.text
        assert SECRET_CONTENT not in r.text, "arbitrary file contents leaked"

    def test_dotdot_chain_rejected(self, secure_env):
        client, ws_id, view_id = secure_env
        SECRET_PATH.write_text(SECRET_CONTENT)
        try:
            # from <ws>/scripts, ../../../ reaches /tmp where the secret lives
            r = client.get(
                f"/api/workspace/{ws_id}/views/{view_id}/level2",
                params={"script": f"../../../{SECRET_PATH.name}"},
            )
        finally:
            SECRET_PATH.unlink(missing_ok=True)
        assert r.status_code == 200, r.text
        assert "error" in r.json(), r.text
        assert SECRET_CONTENT not in r.text

    def test_cross_workspace_script_rejected(self, secure_env):
        """`../../<other_ws>/scripts/x.sql` must not read another workspace."""
        client, ws_id, view_id = secure_env
        other_id = create_workspace(_make_unit_zip())
        try:
            other_script = get_workspace_dir(other_id) / "scripts" / UNIT_SCRIPT
            marker = "E4CROSSWS-9c21"
            other_script.write_text(f"-- {marker}\n" + UNIT_SQL)
            r = client.get(
                f"/api/workspace/{ws_id}/views/{view_id}/level2",
                params={"script": f"../../{other_id}/scripts/{UNIT_SCRIPT}"},
            )
        finally:
            delete_workspace(other_id)
        assert r.status_code == 200, r.text
        assert "error" in r.json(), r.text
        assert "E4CROSSWS-9c21" not in r.text, "other workspace's SQL leaked"

    def test_bare_dotdot_rejected(self, secure_env):
        client, ws_id, view_id = secure_env
        r = client.get(
            f"/api/workspace/{ws_id}/views/{view_id}/level2",
            params={"script": ".."},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"error": "Script '..' not found"}, r.text

    def test_missing_script_keeps_existing_error_shape(self, secure_env):
        client, ws_id, view_id = secure_env
        r = client.get(
            f"/api/workspace/{ws_id}/views/{view_id}/level2",
            params={"script": "no_such_file.sql"},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"error": "Script 'no_such_file.sql' not found"}, r.text

    def test_valid_script_still_works(self, secure_env):
        """Positive control — the happy path is unchanged."""
        client, ws_id, view_id = secure_env
        r = client.get(
            f"/api/workspace/{ws_id}/views/{view_id}/level2",
            params={"script": STEP3, "filter": "true"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["script_name"] == STEP3, body
        assert body["graph"]["nodes"], body
        assert body["graph"]["edges"], body


# ═══════════════════ 2. /highlight traversal → 404 ═══════════════════

class TestHighlightTraversal:
    def test_encoded_dotdot_slash_rejected_404(self, secure_env):
        """%2F-encoded traversal reaches the handler as one segment; the old
        code read the secret file and returned it (200); now → 404."""
        client, ws_id, _ = secure_env
        SECRET_PATH.write_text(SECRET_CONTENT)
        try:
            r = client.get(
                f"/api/workspace/{ws_id}/scripts/"
                f"..%2F..%2F..%2F{SECRET_PATH.name}/highlight",
                params={"table": "t", "field": "f"},
            )
        finally:
            SECRET_PATH.unlink(missing_ok=True)
        assert r.status_code == 404, r.text
        assert SECRET_CONTENT not in r.text

    def test_bare_dotdot_rejected_404(self, secure_env):
        client, ws_id, _ = secure_env
        r = client.get(
            f"/api/workspace/{ws_id}/scripts/%2E%2E/highlight",
            params={"table": "t", "field": "f"},
        )
        assert r.status_code == 404, r.text

    def test_missing_script_404(self, secure_env):
        client, ws_id, _ = secure_env
        r = client.get(
            f"/api/workspace/{ws_id}/scripts/no_such.sql/highlight",
            params={"table": "t", "field": "f"},
        )
        assert r.status_code == 404, r.text


# ═══════════════════ 3. autocomplete type whitelist ═══════════════════

class TestAutocompleteTypeWhitelist:
    def test_traversal_type_400(self, secure_env):
        client, ws_id, _ = secure_env
        r = client.get(
            f"/api/workspace/{ws_id}/autocomplete",
            params={"type": "../../../other_ws/cache/table", "q": ""},
        )
        assert r.status_code == 400, r.text

    def test_unknown_type_400(self, secure_env):
        client, ws_id, _ = secure_env
        r = client.get(
            f"/api/workspace/{ws_id}/autocomplete",
            params={"type": "script", "q": ""},
        )
        assert r.status_code == 400, r.text

    def test_valid_table_type_200(self, secure_env):
        client, ws_id, _ = secure_env
        r = client.get(
            f"/api/workspace/{ws_id}/autocomplete",
            params={"type": "table", "q": ""},
        )
        assert r.status_code == 200, r.text
        assert "suggestions" in r.json()


# ═══════════════════ 4. graph cache extractor-version stamp ═══════════════════

class TestGraphCacheExtractorVersion:
    def _cold_call(self, ws_id: str) -> dict:
        from app.services.dataflow_service import get_level2_graph
        return get_level2_graph(ws_id, "v", UNIT_SCRIPT, TARGET_TABLE, TARGET_FIELD, False)

    def test_mismatched_version_rebuilds_and_restamps(self, unit_ws):
        gpath, _spath = _unit_cache_paths(unit_ws)
        gpath.write_text(json.dumps({
            "format_version": 4,
            "extractor_version": "1970-01-01.0",  # stale extractor
            "nodes": [], "edges": [], "parse_errors": [],
        }))
        r = self._cold_call(unit_ws)
        assert "error" not in r, r
        stamped = json.loads(gpath.read_text())
        assert stamped.get("extractor_version") == EXTRACTOR_VERSION, stamped

    def test_matching_version_serves_cache_without_rewrite(self, unit_ws):
        gpath, _spath = _unit_cache_paths(unit_ws)
        r1 = self._cold_call(unit_ws)  # cold build → stamps the cache
        assert "error" not in r1, r1
        data = json.loads(gpath.read_text())
        assert data.get("extractor_version") == EXTRACTOR_VERSION
        data["e4_marker"] = "hit"
        gpath.write_text(json.dumps(data))
        r2 = self._cold_call(unit_ws)
        assert "error" not in r2, r2
        served = json.loads(gpath.read_text())
        assert served.get("e4_marker") == "hit", "cache rewritten on a version match"

    def test_corrupt_cache_treated_as_miss(self, unit_ws):
        gpath, _spath = _unit_cache_paths(unit_ws)
        gpath.write_text("{definitely not json")
        r = self._cold_call(unit_ws)
        assert "error" not in r, r  # corrupt cache must not 500
        stamped = json.loads(gpath.read_text())
        assert stamped.get("extractor_version") == EXTRACTOR_VERSION, stamped


# ═══════════════════ 5. view persistence lost-update lock ═══════════════════

class TestViewPersistenceConcurrency:
    def test_concurrent_persists_lose_no_view(self, unit_ws):
        from app.services.dataflow_service import (
            _persist_search_view, _load_views,
        )

        async def persist_all():
            await asyncio.gather(*[
                _persist_search_view(unit_ws, {"view_id": f"e4v{i}", "type": "search"})
                for i in range(5)
            ])

        asyncio.run(persist_all())
        ids = {v.get("view_id") for v in _load_views(unit_ws)}
        assert {f"e4v{i}" for i in range(5)} <= ids, ids


# ═══════════════════ 6. logger stderr gating ═══════════════════

class TestLoggerStderrGating:
    def test_stderr_quiet_by_default_loud_with_flag(self, monkeypatch, capsys):
        import importlib
        import app.services.logger as lm

        monkeypatch.delenv("SQL_VIZ_LOG_STDERR", raising=False)
        importlib.reload(lm)
        lm._push(None, "info", "e4-quiet-check")
        assert "e4-quiet-check" not in capsys.readouterr().err

        monkeypatch.setenv("SQL_VIZ_LOG_STDERR", "1")
        importlib.reload(lm)
        lm._push(None, "info", "e4-loud-check")
        assert "e4-loud-check" in capsys.readouterr().err

        # Restore the default (env unset) for the rest of the suite.
        monkeypatch.delenv("SQL_VIZ_LOG_STDERR", raising=False)
        importlib.reload(lm)


# ═══════════════════ 7. zip upload path-traversal members dropped ═══════════════════

class TestZipTraversalDropped:
    """create_workspace must never write outside <ws>/scripts.

    The old guard was a string-prefix check (`str(target).startswith(
    str(scripts_dir))`) — component-blind, so a member like
    `../scripts_evil/evil.sql` (a sibling dir whose name merely *starts
    with* "scripts") resolved inside the workspace yet passed, and any
    sibling workspace whose id string-prefixes this one's would have been
    writable too. The guard is now component-wise (is_relative_to, the
    same idiom as get_script_path).
    """

    def _zip_with(self, members: dict[str, str]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, content in members.items():
                zf.writestr(name, content)
        return buf.getvalue()

    def test_sibling_scripts_dir_member_dropped(self):
        """`../scripts_evil/…` was the string-prefix false-accept — must drop."""
        ws_id = create_workspace(self._zip_with({
            "ok.sql": UNIT_SQL,
            "../scripts_evil/evil.sql": "-- evil\n",
            "../escape.sql": "-- escape\n",
            "../cache/evil.json": "{}\n",
        }))
        try:
            ws_dir = get_workspace_dir(ws_id)
            assert (ws_dir / "scripts" / "ok.sql").exists(), "legit member lost"
            assert not (ws_dir / "scripts_evil").exists(), (
                "sibling `scripts*` dir write accepted")
            assert not (ws_dir / "escape.sql").exists(), (
                "member escaped scripts/ into the ws root")
            assert not (ws_dir / "cache" / "evil.json").exists(), (
                "member escaped into the ws cache dir")
        finally:
            delete_workspace(ws_id)

    def test_deep_dotdot_chain_dropped(self):
        """`../../` climbs to WORKSPACE_ROOT — must drop."""
        ws_id = create_workspace(self._zip_with({
            "../../evil_root.sql": "-- evil\n",
        }))
        try:
            ws_dir = get_workspace_dir(ws_id)
            assert not (ws_dir.parent / "evil_root.sql").exists()
            assert not (ws_dir / "scripts" / "evil_root.sql").exists()
        finally:
            delete_workspace(ws_id)

    def test_absolute_member_dropped(self):
        """An absolute-path member must never be extracted (zipfile lets
        namelist carry absolute names; pathlib would join-and-resolve)."""
        ws_id = create_workspace(self._zip_with({
            "/tmp/e4_zip_abs_abs.sql": "-- evil\n",
        }))
        try:
            ws_dir = get_workspace_dir(ws_id)
            assert not list(ws_dir.rglob("e4_zip_abs_abs.sql")), (
                "absolute member extracted")
            assert not Path("/tmp/e4_zip_abs_abs.sql").exists()
        finally:
            delete_workspace(ws_id)
