"""R31 multi-user login — auth service, sessions, workspace ownership,
remove-from-history, layout CAS, config provisioning.

These run IN-PROCESS with the login gate OFF (REQUIRE_LOGIN fails closed by
default; backend/tests/conftest.py forces it OFF before any app import so the
rest of the suite stays green): the session routes still enforce their own
auth via `require_login`, and the workspace router treats the caller as the
synthetic "dev-user". Gate-ON behavior is covered two ways:
the `_gate_on` monkeypatch fixture (below) flips `app.main.REQUIRE_LOGIN`
in-process to exercise the #293 public-exemption surface, and
test_r31_gate.py runs a subprocess with REQUIRE_LOGIN=true for the
end-to-end gate itself.

Settled design: wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md +
wiki/R31_IMPLEMENTATION.md.
"""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app
from app.services import auth_service
from app.services.audit_service import read_activity, read_audit
from app.services.workspace_service import (
    WORKSPACE_ROOT, create_workspace, delete_workspace,
    get_workspace_dir, read_meta, write_meta_cas,
)

client = TestClient(app)

DEV_USER = "dev-user"


def _zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("t1.sql", "SELECT a FROM t1;\n")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _cleanup():
    """Restore the in-memory session store, the on-disk account index, and drop
    any test workspaces.

    ``delete_workspace()`` only rmtree's the directory — it leaves the creator's
    users.json index row behind, so repeated runs of these HTTP-path tests
    (``client.post("/api/workspace")`` → ``add_workspace_to_index``) accumulate
    orphaned index rows and fill ``MAX_WORKSPACES_PER_USER`` → later creates
    return 409. Snapshot/restore the account store alongside the dir sweep.
    """
    auth_service.reset_for_tests()
    before = set(p.name for p in WORKSPACE_ROOT.iterdir())
    users_before = auth_service.load_users()
    yield
    auth_service.reset_for_tests()
    auth_service.save_users(users_before)
    for p in WORKSPACE_ROOT.iterdir():
        if p.is_dir() and p.name not in before:
            delete_workspace(p.name)


@pytest.fixture
def _provisioned_user():
    auth_service.provision_user("alice@hsbc.com", "secret1", force=True)
    return "alice@hsbc.com"


def _login(username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    return r


# --- accounts & sessions ---------------------------------------------------

def test_provision_and_login_roundtrip(_provisioned_user):
    r = _login("alice@hsbc.com", "secret1")
    assert r.status_code == 200
    assert r.json()["username"] == "alice@hsbc.com"
    assert "session" in client.cookies

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "alice@hsbc.com"

    # logout destroys the session; /auth/me 401s again
    out = client.post("/api/auth/logout")
    assert out.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_unknown_username_rejected():
    r = _login("ghost@hsbc.com", "whatever1")
    assert r.status_code == 401


def test_wrong_password_rejected(_provisioned_user):
    assert _login("alice@hsbc.com", "wrong-pw").status_code == 401


def test_login_backoff_async_nonblocking_roundtrip(_provisioned_user):
    # H-S1: the failed-login backoff + PBKDF2 verify run off the event loop
    # (asyncio.to_thread / asyncio.sleep). Repeated failed logins still return
    # 401 (the backoff sleep is awaited, not time.sleep), and a correct login
    # still opens a session afterwards.
    assert _login("alice@hsbc.com", "wrong-pw").status_code == 401
    assert _login("alice@hsbc.com", "wrong-pw").status_code == 401
    r = _login("alice@hsbc.com", "secret1")
    assert r.status_code == 200
    assert r.json()["username"] == "alice@hsbc.com"


def test_username_format_validation():
    assert not auth_service.verify_username_format("alice@gmail.com")
    assert not auth_service.verify_username_format("alice@hsbc.comx")
    assert auth_service.verify_username_format("a.b+c@hsbc.com")


def test_config_provisioned_user_can_login():
    # R31 (#269): config provisioning is the ONLY provisioning path — the
    # default allowlist is {"admin@hsbc.com": "123456"}. force-syncing it to
    # config makes the default admin login work (idempotent across runs).
    from app.config import PROVISIONED_USERS
    assert PROVISIONED_USERS.get("admin@hsbc.com") == "123456"
    assert auth_service.provision_user("admin@hsbc.com", "123456", force=True)
    assert _login("admin@hsbc.com", "123456").status_code == 200


def test_config_provisioning_force_syncs_password():
    # Each deploy re-syncs every PROVISIONED_USERS entry to config — a
    # drifted password is overwritten back to the config value.
    auth_service.provision_user("admin@hsbc.com", "999999", force=True)  # simulate drift
    assert _login("admin@hsbc.com", "123456").status_code == 401  # drifted value live
    assert auth_service.provision_user("admin@hsbc.com", "123456", force=True)
    assert _login("admin@hsbc.com", "123456").status_code == 200
    assert _login("admin@hsbc.com", "999999").status_code == 401  # old password dead


def test_admin_bootstrap_endpoint_is_gone():
    # R31 (#269): the gate-exempt POST /api/admin/users is REMOVED — there is
    # no HTTP endpoint that provisions or resets accounts (config only). The
    # path now falls through to the static frontend (405 for POST / 404 GET —
    # never 200), and the call must NOT change any password.
    auth_service.provision_user("admin@hsbc.com", "123456", force=True)
    assert _login("admin@hsbc.com", "123456").status_code == 200
    r = client.post("/api/admin/users",
                    json={"username": "admin@hsbc.com", "password": "pwned", "force": True})
    assert r.status_code in (404, 405)  # no such endpoint (never 200)
    # the attempted reset did not touch the account
    assert _login("admin@hsbc.com", "123456").status_code == 200
    assert _login("admin@hsbc.com", "pwned").status_code == 401


# --- workspace ownership & quota ------------------------------------------

def test_workspace_create_sets_creator_and_index(_provisioned_user):
    # A real session (token present) is required for index maintenance; log
    # in so the cookie is sent on the create.
    assert _login("alice@hsbc.com", "secret1").status_code == 200
    r = client.post("/api/workspace", files={"file": ("w.zip", _zip_bytes(), "application/zip")})
    assert r.status_code == 200
    ws_id = r.json()["workspace_id"]
    assert len(ws_id) == 32 and all(c in "0123456789abcdef" for c in ws_id)

    meta = read_meta(ws_id)
    assert meta["creator_username"] == "alice@hsbc.com"

    mine = client.get("/api/workspaces")
    assert mine.status_code == 200
    body = mine.json()
    assert body["cap"] == 10
    assert any(w["ws_id"] == ws_id and w["role"] == "creator" for w in body["workspaces"])


def test_quota_refused_with_409(_provisioned_user):
    assert _login("alice@hsbc.com", "secret1").status_code == 200
    saved = list(auth_service._index_of("alice@hsbc.com"))
    try:
        for i in range(10):
            auth_service.add_workspace_to_index("alice@hsbc.com", f"deadbeef{i:024x}", "creator")
        r = client.post("/api/workspace",
                        files={"file": ("w.zip", _zip_bytes(), "application/zip")})
        assert r.status_code == 409
    finally:
        # restore the original index (workspaces list only, keeps the record)
        from app.services.auth_service import _save_index
        _save_index("alice@hsbc.com", saved)


def test_creator_remove_physically_deletes_with_audit():
    ws_id = create_workspace(_zip_bytes(), creator_username=DEV_USER)
    from app.services.workspace_service import remove_from_my_history
    ok, message, deleted = remove_from_my_history(ws_id, DEV_USER, "127.0.0.1")
    assert ok and deleted and message == "Workspace deleted"
    assert not get_workspace_dir(ws_id).exists()
    # A-H3: server-global audit entry written BEFORE removal
    assert any(r["ws_id"] == ws_id and r["action"] == "workspace deleted"
               for r in read_audit())


def test_participant_remove_keeps_workspace():
    ws_id = create_workspace(_zip_bytes(), creator_username="owner@hsbc.com")
    auth_service.add_workspace_to_index("visitor@hsbc.com", ws_id, "participant")
    from app.services.workspace_service import remove_from_my_history
    ok, message, deleted = remove_from_my_history(ws_id, "visitor@hsbc.com", "127.0.0.1")
    assert ok and not deleted and message == "Removed from your list"
    assert get_workspace_dir(ws_id).exists()  # files survive
    assert all(w["ws_id"] != ws_id for w in auth_service._index_of("visitor@hsbc.com"))
    # recorded in the workspace's activity log
    assert any(r["action"] == "removed-from-own-list" for r in read_activity(ws_id))
    delete_workspace(ws_id)


# --- layout CAS ------------------------------------------------------------

def test_layout_cas_bumps_version_and_rejects_stale():
    ws_id = create_workspace(_zip_bytes(), creator_username=DEV_USER)
    r = client.put(f"/api/workspace/{ws_id}/layout", json={
        "level": "l1",
        "node_positions": {"a": [10, 20]},
        "state_version": 0,
    })
    assert r.status_code == 200
    assert r.json()["state_version"] == 1

    # stale write (still claims version 0) → 409 with fresh state
    r = client.put(f"/api/workspace/{ws_id}/layout", json={
        "level": "l1",
        "node_positions": {"b": [1, 2]},
        "state_version": 0,
    })
    assert r.status_code == 409
    fresh = r.json()["detail"]["fresh"]  # FastAPI wraps the dict detail
    assert fresh["state_version"] == 1

    # correct CAS write lands
    r = client.put(f"/api/workspace/{ws_id}/layout", json={
        "level": "l1",
        "node_positions": {"b": [1, 2]},
        "state_version": 1,
    })
    assert r.status_code == 200
    assert read_meta(ws_id)["layouts"]["l1"] == {"b": [1, 2]}

    # E-H4 (#272): an l2:{script} layout key SURVIVES the save — the old
    # opened_l2s prune (opened_l2s is never written → the filter set was
    # always empty) dropped every l2 key, so L2 layout persistence was dead.
    r = client.put(f"/api/workspace/{ws_id}/layout", json={
        "level": "l2",
        "script": "t1.sql",
        "node_positions": {"n1": [5, 6]},
        "state_version": 2,
    })
    assert r.status_code == 200
    assert read_meta(ws_id)["layouts"]["l2:t1.sql"] == {"n1": [5, 6]}
    # the l1 entry survived alongside the new l2 key
    assert read_meta(ws_id)["layouts"]["l1"] == {"b": [1, 2]}


def test_layout_non_creator_rejected_with_403():
    # R31 (#272): creator-only layout editing — a non-creator session PUT
    # layout → 403; the creator's own session can still save.
    ws_id = create_workspace(_zip_bytes(), creator_username="owner@hsbc.com")
    auth_service.provision_user("alice@hsbc.com", "secret1", force=True)
    assert _login("alice@hsbc.com", "secret1").status_code == 200
    r = client.put(f"/api/workspace/{ws_id}/layout", json={
        "level": "l1",
        "node_positions": {"a": [1, 2]},
        "state_version": 0,
    })
    assert r.status_code == 403

    auth_service.provision_user("owner@hsbc.com", "secret1", force=True)
    assert _login("owner@hsbc.com", "secret1").status_code == 200
    r = client.put(f"/api/workspace/{ws_id}/layout", json={
        "level": "l1",
        "node_positions": {"a": [1, 2]},
        "state_version": 0,
    })
    assert r.status_code == 200


def test_export_config_non_creator_rejected_with_403():
    # #317 M-Po5: export-config mutation is creator-only — a non-creator
    # session PUT/DELETE export config → 403; the creator's own session can
    # still save and reset.
    ws_id = create_workspace(_zip_bytes(), creator_username="owner@hsbc.com")
    auth_service.provision_user("alice@hsbc.com", "secret1", force=True)
    assert _login("alice@hsbc.com", "secret1").status_code == 200

    assert client.put(f"/api/workspace/{ws_id}/export-config",
                      json={"row_limit": 50}).status_code == 403
    assert client.delete(f"/api/workspace/{ws_id}/export-config").status_code == 403

    auth_service.provision_user("owner@hsbc.com", "secret1", force=True)
    assert _login("owner@hsbc.com", "secret1").status_code == 200
    assert client.put(f"/api/workspace/{ws_id}/export-config",
                      json={"row_limit": 50}).status_code == 200
    assert client.delete(f"/api/workspace/{ws_id}/export-config").status_code == 200


def test_view_mutation_non_creator_rejected_with_403():
    # #317 M-Po5: the view child-add / view-delete endpoints are creator-only
    # — a non-creator session is refused 403 (checked before any view lookup).
    ws_id = create_workspace(_zip_bytes(), creator_username="owner@hsbc.com")
    auth_service.provision_user("alice@hsbc.com", "secret1", force=True)
    assert _login("alice@hsbc.com", "secret1").status_code == 200

    assert client.post(f"/api/workspace/{ws_id}/views/fakeview/children",
                       json={"view_id": "c1"}).status_code == 403
    assert client.delete(f"/api/workspace/{ws_id}/views/fakeview").status_code == 403


def test_activity_and_audit_records_capture_client_ip(_provisioned_user):
    # #316 M-Po4: activity + audit records carry the real client IP (from
    # request.client.host), never "".
    assert _login("alice@hsbc.com", "secret1").status_code == 200
    r = client.post("/api/workspace",
                    files={"file": ("w.zip", _zip_bytes(), "application/zip")})
    assert r.status_code == 200
    ws_id = r.json()["workspace_id"]

    created = read_activity(ws_id)
    assert created and created[0]["action"] == "workspace_created"
    assert created[0]["ip"], "workspace_created activity ip must be non-empty"

    # creator remove-from-history physically deletes; the audit entry is
    # written BEFORE removal and carries the client IP.
    out = client.delete(f"/api/me/workspaces/{ws_id}")
    assert out.status_code == 200
    audited = next((rec for rec in read_audit()
                    if rec["ws_id"] == ws_id and rec["action"] == "workspace deleted"),
                   None)
    assert audited and audited["ip"], "workspace deleted audit ip must be non-empty"


def test_resume_returns_shared_state():
    ws_id = create_workspace(_zip_bytes(), creator_username=DEV_USER)
    r = client.get(f"/api/workspace/{ws_id}/resume")
    assert r.status_code == 200
    body = r.json()
    assert body["workspace_id"] == ws_id
    assert body["creator_username"] == DEV_USER
    assert body["state_version"] == 0
    assert "layouts" in body and "opened_l2s" in body


def test_resume_membership_and_quota(_provisioned_user):
    """R31 §5.5/§5.6: an id-open lands the workspace in the opener's index as
    a participant (membership = created + visited); at the cap a NEW id-open
    is blocked with 409 ("remove one from your list first"), but reopening an
    already-indexed workspace at the cap always succeeds (existing-entry
    refresh never hits the quota branch)."""
    username = "resumer@hsbc.com"
    auth_service.provision_user(username, "secret1", force=True)
    assert _login(username, "secret1").status_code == 200

    ws_id = create_workspace(_zip_bytes(), creator_username="owner@hsbc.com")
    other = create_workspace(_zip_bytes(), creator_username="owner@hsbc.com")
    saved = list(auth_service._index_of(username))
    try:
        # id-open of a workspace the user did not create → added as participant
        r = client.get(f"/api/workspace/{ws_id}/resume")
        assert r.status_code == 200
        entry = next(w for w in auth_service._index_of(username)
                     if w["ws_id"] == ws_id)
        assert entry["role"] == "participant"

        # fill the index to the cap; a NEW id-open is blocked with 409
        cap = auth_service.MAX_WORKSPACES_PER_USER
        fill = cap - len(auth_service._index_of(username))
        for i in range(fill):
            auth_service.add_workspace_to_index(
                username, f"deadbeef{i:024x}", "participant")
        assert client.get(f"/api/workspace/{other}/resume").status_code == 409

        # reopening the already-indexed workspace at the cap still succeeds
        assert client.get(f"/api/workspace/{ws_id}/resume").status_code == 200
    finally:
        from app.services.auth_service import _save_index
        _save_index(username, saved)
        delete_workspace(ws_id)
        delete_workspace(other)


# --- notifications removed (#322) ------------------------------------------

def test_notification_endpoints_removed(_provisioned_user):
    # The in-app notification subsystem is removed entirely — the endpoints
    # no longer exist (404/405, never 200).
    assert _login("alice@hsbc.com", "secret1").status_code == 200
    assert client.get("/api/notifications").status_code in (404, 405)
    assert client.post("/api/notifications/abc123/read").status_code in (404, 405)


# --- password change revokes sessions (#319 M-Po7) -------------------------

def test_password_change_revokes_sessions(_provisioned_user):
    assert _login("alice@hsbc.com", "secret1").status_code == 200
    token = client.cookies.get("session")
    assert token and auth_service.get_session(token) is not None

    # force re-provision of an EXISTING account overwrites the password → the
    # old session is revoked (no expiry added, #279 stays).
    assert auth_service.provision_user("alice@hsbc.com", "secret2", force=True)
    assert auth_service.get_session(token) is None
    assert client.get("/api/auth/me").status_code == 401

    # old password dead, new password works
    assert _login("alice@hsbc.com", "secret1").status_code == 401
    assert _login("alice@hsbc.com", "secret2").status_code == 200

    # restore the fixture password for any later test
    auth_service.provision_user("alice@hsbc.com", "secret1", force=True)


# --- audit/activity file permissions (#318 M-Po6) --------------------------

def test_activity_file_created_0600():
    # _append_record creates log files mode 0600 (activity.json and the
    # server-global audit.json both flow through it).
    import os
    from app.services import audit_service
    ws_id = create_workspace(_zip_bytes(), creator_username=DEV_USER)
    try:
        audit_service.append_activity(ws_id, DEV_USER, "127.0.0.1", "test")
        path = WORKSPACE_ROOT / ws_id / "activity.json"
        assert (path.stat().st_mode & 0o777) == 0o600
    finally:
        delete_workspace(ws_id)


# --- #293: SQL Analysis is public (login-gate exempt) --------------------

# The gate reads REQUIRE_LOGIN as a module-level global in app.main (imported
# by value from app.config), so toggling it in-process must rebind the name on
# app.main. The rest of this module runs with the gate OFF (default); these
# tests force it ON for their own scope and rely on the autouse _cleanup
# fixture to guarantee an empty session store (no session cookie).

@pytest.fixture
def _gate_on(monkeypatch):
    """Force the login gate ON for the test (REQUIRE_LOGIN=true)."""
    monkeypatch.setattr(app_main, "REQUIRE_LOGIN", True)


def test_analysis_list_scripts_public_while_gate_on(_gate_on):
    """#293: GET /api/scripts is reachable without a session."""
    r = client.get("/api/scripts")
    assert r.status_code == 200


def test_analyze_public_while_gate_on(_gate_on):
    """#293: POST /api/analyze is reachable without a session (not 401)."""
    r = client.post("/api/analyze", data={"sql_text": "SELECT 1"})
    assert r.status_code == 200


def test_gate_still_covers_protected_endpoint(_gate_on):
    """#293: Data Flow Debugger routes stay gated without a session."""
    r = client.get("/api/workspace")
    assert r.status_code == 401


def test_scan_and_index_non_creator_rejected_with_403():
    # #380 (user ruling 2026-08-28): POST scan/index mutate shared
    # workspace state — creator-only, like layout/filter-config (#272).
    # Participant → 403 on both; the creator's own session → 200.
    ws_id = create_workspace(_zip_bytes(), creator_username="owner@hsbc.com")
    auth_service.provision_user("alice@hsbc.com", "secret1", force=True)
    assert _login("alice@hsbc.com", "secret1").status_code == 200
    assert client.post(f"/api/workspace/{ws_id}/scan").status_code == 403
    assert client.post(f"/api/workspace/{ws_id}/index",
                       json={"scripts": []}).status_code == 403

    auth_service.provision_user("owner@hsbc.com", "secret1", force=True)
    assert _login("owner@hsbc.com", "secret1").status_code == 200
    assert client.post(f"/api/workspace/{ws_id}/scan").status_code == 200
    assert client.post(f"/api/workspace/{ws_id}/index",
                       json={"scripts": []}).status_code == 200
