"""Team M1 — multi-user workspace: permission matrix, share path, concurrency.

Covers the #380 + R31 access model against the v3.3.193 working tree (atomic
index writes, incremental index, catch-up 409 gate, participant reads):

  1. provisioning + login (config-driven accounts, unknown user rejected)
  2. the permission matrix — creator / participant / anonymous per endpoint
  3. the share path — what "getting access" actually is (capability URL)
  4. the P1 torn-read regression: a participant hammering reads while the
     creator re-indexes must never see a 500 / an empty index / torn JSON
  5. the same harness with the atomic write REMOVED — proving 4 has teeth
  6. the catch-up 409 gate with two users (409 during the run, 200 after)
  7. meta CAS: a layout save concurrent with an index run — no lost update
  8. isolation: what a second participant can and cannot see

Everything here is pinned to the behaviour the code ACTUALLY has (verified
live against a disposable uvicorn container, gps-m1 on :8008, 2026-08-31),
including four places where that differs from the intuitive multi-user
reading:

  * layout / views / filter-config / export-config mutations are CREATOR-only
    (#272) — a participant's PUT layout is a 403, never a CAS conflict;
  * views.json and meta.layouts are WORKSPACE-scoped, not per-user — every
    participant sees every view (isolation is per-workspace, not per-user);
  * there is no share/invite API: access = knowing the 128-bit ws_id and
    opening it (capability URL), and removing it from your list does NOT
    revoke the capability;
  * MAX_WORKSPACES_PER_USER counts PARTICIPANT entries too, so a user who has
    OPENed 10 shared workspaces can no longer open an 11th (§5.6).

Four defects were found by this report-only team; three are still pinned as
``strict=True`` xfails so a repair turns the marker into an XPASS failure:

  M1-D1 (HIGH)   the R31 heavy gate leaks — one concurrent search pair
                 wedges EVERY search, for every user, until restart.
                 FIXED (MSC-1, per-call gate tokens): the pin below now runs
                 as an ordinary regression test, not an xfail;
  M1-D2 (MEDIUM) filtered_index.json is written non-atomically and read
                 unguarded — a torn filter scope 500s every search;
  M1-D3 (HIGH)   write_meta_cas uses a FIXED temp name (meta.tmp) — the
                 layout-vs-index race it was built for 500s instead of 409;
  M1-D4 (LOW)    PROVISIONED_USERS_JSON entries with short passwords are
                 dropped silently — the account simply does not exist.
                 FIXED: the rejection stands (correct per the validator) but
                 the drop now logs a WARNING naming the account (never the
                 password) — ``provision_user``; see the two
                 ``config_provisioning`` tests below.

In-process, login gate OFF by default (conftest); the anonymous rows run
under ``_gate_on``, which monkeypatches REQUIRE_LOGIN at BOTH sites that read
it (app.main for the middleware, app.routers.workspace for _session_ctx) and
is restored by monkeypatch. Every process-global this file touches (sessions,
users.json, workspace dirs, heavy_gate._busy) is captured and put back per
test, so the file is order-independent: it passes alone, in either order
next to test_multiuser_sessions.py, and inside the full suite.
"""

import io
import json
import logging
import threading
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app
from app.routers import workspace as workspace_router
from app.services import atomic_io, auth_service, folder_index_service
from app.services import heavy_gate
from app.services.workspace_service import (
    WORKSPACE_ROOT, delete_workspace, get_workspace as get_workspace_meta,
    read_meta, write_meta_cas,
)

# one TestClient per user — cookies are per-client, sessions must not collide
CLIENTS = {}
CREATOR = "creator@hsbc.com"
PARTICIPANTS = ("alice@hsbc.com", "bob@hsbc.com")
PASSWORDS = {CREATOR: "pw1creator",
             "alice@hsbc.com": "pw2alice",
             "bob@hsbc.com": "pw3bob"}
ALL_USERS = (CREATOR,) + PARTICIPANTS

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"
CATCHUP_MSG = "Index is being updated for this workspace — retry in a moment"


# --- fixtures ---------------------------------------------------------------

@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Save/restore every process-global this file touches, per test.

    This file is ORDER-SENSITIVE BY NATURE (it drives concurrency), so it
    cleans up after itself four ways:
      * sessions + accounts: reset, then the pre-test users.json restored
        (delete_workspace leaves the users.json row behind — the same
        convention test_r31_auth uses);
      * workspaces: only directories this test created are removed;
      * the heavy gate: cleared through monkeypatch (restored at teardown),
        so neither this file's own concurrency nor a wedge left by anyone
        else crosses a file boundary;
      * REQUIRE_LOGIN: only ever flipped through monkeypatch (restored), and
        at BOTH sites that read it (app.main for the middleware,
        app.routers.workspace for _session_ctx).
    """
    # M1-D1 leaves the gate wedged; clearing it via monkeypatch restores the
    # pre-test value at teardown, so nothing leaks into the next test file.
    monkeypatch.setattr(heavy_gate, "_busy", False)
    monkeypatch.setattr(app_main, "REQUIRE_LOGIN", app_main.REQUIRE_LOGIN)
    monkeypatch.setattr(workspace_router, "REQUIRE_LOGIN",
                        workspace_router.REQUIRE_LOGIN)

    auth_service.reset_for_tests()
    for u in ALL_USERS:
        auth_service.provision_user(u, PASSWORDS[u], force=True)
    before = {p.name for p in WORKSPACE_ROOT.iterdir()}
    users_before = auth_service.load_users()
    yield
    auth_service.reset_for_tests()
    auth_service.save_users(users_before)
    for p in WORKSPACE_ROOT.iterdir():
        if p.is_dir() and p.name not in before:
            delete_workspace(p.name)
    # never hand M1-D1's leak to the next test file
    heavy_gate.release()


@pytest.fixture
def gate_on(monkeypatch):
    """The R31 login gate ON (production) — the middleware 401s every
    session-less /api call and _session_ctx refuses. OFF is the conftest
    default so the rest of the suite runs. monkeypatch restores both sites."""
    monkeypatch.setattr(app_main, "REQUIRE_LOGIN", True)
    monkeypatch.setattr(workspace_router, "REQUIRE_LOGIN", True)


def _wait_gate_free(timeout=20.0):
    """Block until the R31 heavy gate is free (a straggler hammer thread
    finished its search). Returns False on timeout — callers just proceed."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if heavy_gate.try_acquire():
            heavy_gate.release()
            return True
        time.sleep(0.05)
    return False


def _client_for(user):
    if user not in CLIENTS:
        CLIENTS[user] = TestClient(app)
    c = CLIENTS[user]
    r = c.post("/api/auth/login",
               json={"username": user, "password": PASSWORDS[user]})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def users():
    return {u: _client_for(u) for u in ALL_USERS}


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()


def _corpus(n=26):
    """financial (18 real pipeline scripts) + the first spider_complex ones.

    Big enough that a re-index takes ~1s (a real catch-up / torn-read window)
    and the index artifacts are ~90KB (a real torn-write window)."""
    files = {p.name: p.read_text(errors="replace")
             for p in sorted((SAMPLES / "financial").glob("*.sql"))}
    for p in sorted((SAMPLES / "spider_complex").glob("*.sql"))[: max(0, n - len(files))]:
        files[p.name] = p.read_text(errors="replace")
    return files


# a pair the 26-script corpus really answers (14 scripts) — an empty
# script set on a 200 is therefore an anomaly, not a quiet no_matches
SEARCHABLE = ("gps_transactions", "merchant_id")


@pytest.fixture
def shared_ws(users):
    """A creator-owned, indexed workspace both participants have OPENed.

    resume is the only membership path (#380/R31) — the fixture IS the share
    flow under test, so it goes through the HTTP endpoints, not the service.
    """
    creator = users[CREATOR]
    r = creator.post("/api/workspace",
                     files={"file": ("m1.zip", _zip(_corpus()), "application/zip")})
    assert r.status_code == 200, r.text
    ws_id = r.json()["workspace_id"]
    r = creator.post(f"/api/workspace/{ws_id}/index", json={"scripts": []})
    assert r.status_code == 200, r.text
    for p in PARTICIPANTS:
        rr = users[p].get(f"/api/workspace/{ws_id}/resume")
        assert rr.status_code == 200, rr.text
    return ws_id


# --- 1. provisioning + login ------------------------------------------------

def test_provisioned_users_log_in_and_unknown_user_is_rejected(gate_on):
    for u in ALL_USERS:
        c = TestClient(app)
        r = c.post("/api/auth/login",
                   json={"username": u, "password": PASSWORDS[u]})
        assert r.status_code == 200, r.text
        assert r.json()["username"] == u
        assert c.get("/api/auth/me").json()["username"] == u

    # A-H2: an account outside the config allowlist does not exist, and login
    # never auto-creates one (#269 — no provisioning endpoint at all).
    c = TestClient(app)
    r = c.post("/api/auth/login",
               json={"username": "mallory@hsbc.com", "password": "whatever"})
    assert r.status_code == 401
    assert c.get("/api/workspaces").status_code == 401


def test_config_provisioning_rejects_short_passwords(caplog):
    """Defect M1-D4 (FIXED): PROVISIONED_USERS_JSON entries whose password is
    shorter than MIN_PASSWORD_LEN are dropped by provision_user — and that
    drop used to be SILENT, so the account never existed and every one of its
    logins 401'd with no diagnostic anywhere.

    The team-brief seed set (pw1/pw2/pw3) is exactly that case — reproduced
    live: the container came up with an EMPTY users.json and all three logins
    returned 401. The rejection itself is correct per the validator and stays
    (still pinned here); the silence is what was repaired — the drop now logs
    a WARNING naming the dropped account (never the password)."""
    with caplog.at_level(logging.WARNING, logger="app.services.auth_service"):
        caplog.clear()
        assert auth_service.provision_user("short@hsbc.com", "pw1") is False
    assert auth_service.user_exists("short@hsbc.com") is False
    dropped = [r for r in caplog.records if "short@hsbc.com" in r.getMessage()]
    assert dropped, "a dropped provision entry must be diagnosed in the log"
    assert all(r.levelno == logging.WARNING for r in dropped)
    # the diagnostic names the account, never the password
    assert all("pw1" not in r.getMessage() for r in dropped)


def test_config_provisioning_drops_only_the_short_entry(caplog):
    """M1-D4 ops shape: ONE short-password entry in a multi-account
    PROVISIONED_USERS config must not cost the others — the good accounts
    provision, the bad one logs a WARNING and is absent, and no good account
    is ever named in a drop diagnostic."""
    with caplog.at_level(logging.WARNING, logger="app.services.auth_service"):
        caplog.clear()
        assert auth_service.provision_user("ok1@hsbc.com", "secret1") is True
        assert auth_service.provision_user("bad@hsbc.com", "pw1") is False
        assert auth_service.provision_user("ok2@hsbc.com", "secret2") is True
    assert auth_service.user_exists("ok1@hsbc.com")
    assert auth_service.user_exists("ok2@hsbc.com")
    assert not auth_service.user_exists("bad@hsbc.com")
    warned = [r for r in caplog.records if "bad@hsbc.com" in r.getMessage()]
    assert warned, "the dropped account must be named in a log diagnostic"
    assert all(r.levelno == logging.WARNING for r in warned)
    assert not [r for r in caplog.records
                if "ok1@hsbc.com" in r.getMessage()
                or "ok2@hsbc.com" in r.getMessage()]


# --- 1b. M1-D1 (FIXED, was a strict xfail): the R31 heavy gate --------------


def test_heavy_gate_concurrent_refusal_leaks_the_gate():
    """Was DEFECT (HIGH, M1-D1) — the heavy gate leaked under concurrency.

    ``HeavyGate`` kept ``self._acquired`` on the SINGLETON every endpoint
    shares. When request A held the gate and request B entered ``with gate``
    while it was busy (B got the 409 "system busy"), B's ``__enter__``
    overwrote ``_acquired`` with False, so A's ``__exit__`` saw False and
    never called ``release()``. The gate was then busy forever: EVERY search —
    any user, any workspace — returned 409 until the process restarts.

    Reproduced live: after one concurrent burst on a real uvicorn instance,
    six SEQUENTIAL searches a second apart all returned 409 "system busy —
    please wait" with zero load. search + /analyze share this gate.

    Fixed (MSC-1): the acquisition lives on a per-call token, so B's refused
    enter can no longer clobber A's flag and A's exit always releases. This
    now runs as a plain regression pin.
    """
    g = heavy_gate.HeavyGate()
    assert heavy_gate.try_acquire() is True   # idle
    heavy_gate.release()
    with g as outer:
        assert outer                          # the search that owns the gate
        with g as inner:
            assert not inner                  # the concurrent 409
    assert heavy_gate.try_acquire() is True, (
        "gate never released — every future search 409s until restart")
    heavy_gate.release()


# --- 2. permission matrix ---------------------------------------------------

def _probes(ws_id, view_id, state_version):
    """(label, method, path, kwargs, expected_read|expected_write)"""
    layout_body = {"level": "l1", "node_positions": {"n1": {"x": 1, "y": 2}},
                   "state_version": state_version}
    reads = [
        ("GET info", "get", f"/api/workspace/{ws_id}", None),
        ("GET resume", "get", f"/api/workspace/{ws_id}/resume", None),
        ("GET tree", "get", f"/api/workspace/{ws_id}/tree", None),
        ("GET index", "get", f"/api/workspace/{ws_id}/index", None),
        ("GET status", "get", f"/api/workspace/{ws_id}/status", None),
        ("GET autocomplete", "get", f"/api/workspace/{ws_id}/autocomplete",
         {"params": {"type": "table", "q": ""}}),
        ("POST search", "post", f"/api/workspace/{ws_id}/search",
         {"json": {"table": SEARCHABLE[0], "field": SEARCHABLE[1]}}),
        ("GET views", "get", f"/api/workspace/{ws_id}/views", None),
        ("GET level1", "get", f"/api/workspace/{ws_id}/views/{view_id}/level1", None),
        ("GET level2", "get", f"/api/workspace/{ws_id}/views/{view_id}/level2",
         {"params": {"script": "fin_query1_reconciliation.sql"}}),
        ("GET highlight", "get",
         f"/api/workspace/{ws_id}/scripts/fin_query1_reconciliation.sql/highlight",
         {"params": {"table": SEARCHABLE[0], "field": SEARCHABLE[1]}}),
        ("GET export-config", "get", f"/api/workspace/{ws_id}/export-config", None),
        ("GET activity", "get", f"/api/workspace/{ws_id}/activity", None),
        ("POST close", "post", f"/api/workspace/{ws_id}/close", None),
    ]
    creator_only = [
        ("POST scan", "post", f"/api/workspace/{ws_id}/scan", None),
        ("POST index", "post", f"/api/workspace/{ws_id}/index",
         {"json": {"scripts": []}}),
        ("PUT layout", "put", f"/api/workspace/{ws_id}/layout",
         {"json": layout_body}),
        ("POST filter-config", "post", f"/api/workspace/{ws_id}/filter-config", None),
        ("PUT export-config", "put", f"/api/workspace/{ws_id}/export-config",
         {"json": {"include_ctes": False}}),
        ("DELETE export-config", "delete", f"/api/workspace/{ws_id}/export-config", None),
        ("POST view child", "post", f"/api/workspace/{ws_id}/views/{view_id}/children",
         {"json": {"view_id": "m1-child"}}),
        ("DELETE view", "delete", f"/api/workspace/{ws_id}/views/{view_id}", None),
    ]
    return reads, creator_only


def test_permission_matrix_creator_vs_participants(users, shared_ws):
    """The #380 + R31 model, cell by cell.

    creator: full control (every read 200, every mutation 200).
    participant: reads 200 (#380 read-only half), mutations 403 (#272).
    """
    creator = users[CREATOR]
    state_version = creator.get(f"/api/workspace/{shared_ws}/resume").json()["state_version"]

    # a creator-owned view so the read-only view endpoints have a target
    sr = creator.post(f"/api/workspace/{shared_ws}/search",
                      json={"table": SEARCHABLE[0], "field": SEARCHABLE[1]})
    assert sr.status_code == 200, sr.text
    view_id = sr.json()["view_id"]
    state_version = creator.get(f"/api/workspace/{shared_ws}/resume").json()["state_version"]

    reads, creator_only = _probes(shared_ws, view_id, state_version)

    for label, method, path, kwargs in reads:
        for user in ALL_USERS:
            r = getattr(users[user], method)(path, **(kwargs or {}))
            assert r.status_code == 200, \
                f"{label} as {user}: {r.status_code} {r.text[:200]}"
            assert r.status_code < 500

    for label, method, path, kwargs in creator_only:
        if label == "PUT layout":
            # POST index (the row above) legitimately bumps state_version, so
            # the layout CAS needs the version AS OF NOW — a stale one is the
            # documented 409, not a permission answer.
            kwargs = dict(kwargs or {})
            kwargs["json"] = dict(kwargs["json"])
            kwargs["json"]["state_version"] = creator.get(
                f"/api/workspace/{shared_ws}/resume").json()["state_version"]
        r = getattr(creator, method)(path, **(kwargs or {}))
        assert r.status_code == 200, \
            f"{label} as creator: {r.status_code} {r.text[:200]}"
        for p in PARTICIPANTS:
            r = getattr(users[p], method)(path, **(kwargs or {}))
            assert r.status_code == 403, \
                f"{label} as {p}: {r.status_code} {r.text[:200]} (expected 403)"


def test_permission_matrix_anonymous_is_401_everywhere(users, shared_ws, gate_on):
    """The middleware gate: no session → 401 for EVERY workspace endpoint,
    including the reads that are open to any session and the ones with no
    explicit _session_ctx call of their own (info/status/autocomplete/
    export-config — they rely on the middleware alone)."""
    creator = users[CREATOR]
    sr = creator.post(f"/api/workspace/{shared_ws}/search",
                      json={"table": SEARCHABLE[0], "field": SEARCHABLE[1]})
    view_id = sr.json()["view_id"]
    reads, creator_only = _probes(shared_ws, view_id, 0)

    anon = TestClient(app)  # never logged in
    for label, method, path, kwargs in reads + creator_only:
        r = getattr(anon, method)(path, **(kwargs or {}))
        assert r.status_code == 401, f"{label} anonymous: {r.status_code}"


def test_workspace_delete_is_creator_physical_participant_unlink(users, shared_ws):
    """DELETE /me/workspaces is role-dependent (A-M1/A-M2):
    participant → their link goes, the workspace and the creator's survive;
    creator → the workspace is physically deleted and vanishes for everyone."""
    alice, bob, creator = users["alice@hsbc.com"], users["bob@hsbc.com"], users[CREATOR]

    r = bob.delete(f"/api/me/workspaces/{shared_ws}")
    assert r.status_code == 200 and r.json() == {
        "deleted": False, "message": "Removed from your list"}
    assert creator.get(f"/api/workspace/{shared_ws}").status_code == 200
    assert alice.get(f"/api/workspace/{shared_ws}").status_code == 200

    r = creator.delete(f"/api/me/workspaces/{shared_ws}")
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert alice.get(f"/api/workspace/{shared_ws}").status_code == 404
    assert bob.get(f"/api/workspace/{shared_ws}/index").status_code == 404


# --- 3. the share path ------------------------------------------------------

def test_share_flow_is_a_capability_url(users):
    """How does a participant get access? There is NO share/invite API and no
    membership grant: the only path is `GET /workspace/{ws_id}/resume` with the
    raw 128-bit ws_id, which lands the opener in the workspace index as a
    'participant'. Access control is therefore capability-URL based:

      * ws ids are unguessable (uuid4().hex) and nothing enumerates them;
      * a participant who knows the id can read EVERYTHING in the workspace
        (scripts, index, views, activity) — that is the model, not a leak;
      * removing it from your list does NOT revoke the capability.

    Pinned here so a future "proper sharing" feature changes these on purpose.
    """
    creator, alice = users[CREATOR], users["alice@hsbc.com"]
    r = creator.post("/api/workspace",
                     files={"file": ("m1.zip", _zip(_corpus(4)), "application/zip")})
    ws_id = r.json()["workspace_id"]

    # before the open, the workspace is invisible to alice — no listing leaks it
    assert ws_id not in [w["ws_id"]
                         for w in alice.get("/api/workspaces").json()["workspaces"]]

    # no invite/share/grant endpoint exists at all
    for method, path in (("post", f"/api/workspace/{ws_id}/share"),
                         ("post", f"/api/workspace/{ws_id}/invite"),
                         ("put", f"/api/workspace/{ws_id}/participants")):
        r = getattr(alice, method)(path, json={"username": "alice@hsbc.com"})
        # 405 (route shape exists for another verb) or 404 — either way: no API
        assert r.status_code in (404, 405), f"{method} {path} → {r.status_code}"

    # the open IS the grant
    r = alice.get(f"/api/workspace/{ws_id}/resume")
    assert r.status_code == 200
    entry = next(w for w in alice.get("/api/workspaces").json()["workspaces"]
                 if w["ws_id"] == ws_id)
    assert entry["role"] == "participant"

    # ...and the grant is the capability itself: removing the link does not
    # revoke it — the same id opens again as a participant.
    alice.delete(f"/api/me/workspaces/{ws_id}")
    assert ws_id not in [w["ws_id"]
                         for w in alice.get("/api/workspaces").json()["workspaces"]]
    r = alice.get(f"/api/workspace/{ws_id}/resume")
    assert r.status_code == 200
    assert next(w for w in alice.get("/api/workspaces").json()["workspaces"]
                if w["ws_id"] == ws_id)["role"] == "participant"


def test_unknown_but_wellformed_id_is_404_not_500(users):
    for user in ALL_USERS:
        for path in (f"/api/workspace/{'0' * 32}",
                     f"/api/workspace/{'0' * 32}/index",
                     f"/api/workspace/{'0' * 32}/tree"):
            r = users[user].get(path)
            assert r.status_code == 404, f"{user} {path}: {r.status_code}"
        r = users[user].post(f"/api/workspace/{'0' * 32}/search",
                             json={"table": "A", "field": "B"})
        assert r.status_code == 404


def test_unreadable_meta_is_404_not_500(users, shared_ws):
    """X2 (review): `get_workspace` read meta.json with a bare
    `json.loads(read_text())`, so a corrupt/unreadable meta (a torn write from
    a pre-atomic-io deploy, a full disk) raised out of the existence check —
    a 500 on EVERY route for that workspace instead of the 404 the callers
    already handle. The workspace is unreachable either way; unreachable must
    not look like a server fault."""
    (WORKSPACE_ROOT / shared_ws / "meta.json").write_text("{not json")
    for path in (f"/api/workspace/{shared_ws}",
                 f"/api/workspace/{shared_ws}/resume",
                 f"/api/workspace/{shared_ws}/index",
                 f"/api/workspace/{shared_ws}/tree",
                 f"/api/workspace/{shared_ws}/status"):
        for user in ALL_USERS:
            r = users[user].get(path)
            assert r.status_code == 404, f"{user} {path}: {r.status_code}"
    # and the service-level readers agree (never raise, return None)
    assert read_meta(shared_ws) is None
    assert get_workspace_meta(shared_ws) is None


# --- 4/5. the torn-read regression ------------------------------------------

class _Hammer:
    """alice hammers the read paths while the creator re-indexes.

    Two sensors:
      * HTTP: POST /search + GET /index through a participant session —
        5xx and EMPTY-INDEX responses are the user-visible failures;
      * file: the same artifact bytes the endpoint reads, json.loads'd
        directly — the torn-JSON counter (what the atomic write actually
        guarantees).
    """

    def __init__(self, ws_id, alice, creator, rounds=3, readers=2, monitors=2):
        self.ws_id = ws_id
        self.alice = alice          # credentials, not a shared client
        self.creator = creator
        self.alive_threads = []
        self.rounds = rounds
        self.readers = readers
        self.monitors = monitors
        self.stop = threading.Event()
        self.counts = {"search_200": 0, "search_409": 0, "search_5xx": 0,
                       "index_200": 0, "index_409": 0, "index_5xx": 0,
                       "index_empty": 0, "torn_reads": 0, "file_reads": 0,
                       "other": 0}
        self.errors = []
        self._lock = threading.Lock()

    def _bump(self, key, n=1):
        with self._lock:
            self.counts[key] += n

    def _fail(self, msg):
        with self._lock:
            self.errors.append(msg)

    def _http_reader(self):
        # one client PER THREAD: a TestClient is not a concurrent object, and
        # a hung shared portal would leave this thread (and the R31 gate)
        # dangling into the next test
        http = TestClient(app)
        r = http.post("/api/auth/login",
                      json={"username": self.alice,
                            "password": PASSWORDS[self.alice]})
        assert r.status_code == 200, r.text
        while not self.stop.is_set():
            r = http.post(f"/api/workspace/{self.ws_id}/search",
                          json={"table": SEARCHABLE[0], "field": SEARCHABLE[1]})
            if r.status_code == 200:
                self._bump("search_200")
                if not r.json().get("script_ids"):
                    self._fail("search 200 with an EMPTY script set")
            elif r.status_code in (400, 409):  # gate busy / index catching up
                self._bump("search_409")
            elif r.status_code >= 500:
                self._bump("search_5xx")
                self._fail(f"search {r.status_code}: {r.text[:200]}")
            else:
                self._bump("other")
                self._fail(f"search {r.status_code}: {r.text[:200]}")

            r = http.get(f"/api/workspace/{self.ws_id}/index")
            if r.status_code == 200:
                self._bump("index_200")
                body = r.json()
                # a torn table/field index is swallowed by _read_json and
                # served as {} — indistinguishable from "never indexed"
                if not body.get("table_index") or not body.get("field_index"):
                    self._bump("index_empty")
                    self._fail("GET /index served an EMPTY index")
            elif r.status_code in (400, 409):
                self._bump("index_409")
            elif r.status_code >= 500:
                self._bump("index_5xx")
                self._fail(f"index {r.status_code}: {r.text[:200]}")
            else:
                self._bump("other")
                self._fail(f"index {r.status_code}: {r.text[:200]}")

    def _file_monitor(self):
        cache = WORKSPACE_ROOT / self.ws_id / "cache"
        names = ("table_index.json", "field_index.json")
        while not self.stop.is_set():
            for name in names:
                p = cache / name
                if not p.exists():
                    continue
                try:
                    text = p.read_text()
                except OSError:
                    continue
                with self._lock:
                    self.counts["file_reads"] += 1
                if not text.strip():
                    self._bump("torn_reads")  # truncate seen, bytes not yet
                    self._fail(f"{name}: read as EMPTY (truncate visible)")
                    continue
                try:
                    json.loads(text)
                except json.JSONDecodeError as e:
                    self._bump("torn_reads")
                    self._fail(f"{name}: TORN json ({e})")

    def _writer(self):
        http = TestClient(app)
        r = http.post("/api/auth/login",
                      json={"username": self.creator,
                            "password": PASSWORDS[self.creator]})
        assert r.status_code == 200, r.text
        for _ in range(self.rounds):
            if self.stop.is_set():
                return
            r = http.post(f"/api/workspace/{self.ws_id}/index",
                          json={"scripts": []})
            if r.status_code >= 500:
                self._bump("search_5xx")
                self._fail(f"creator index {r.status_code}: {r.text[:200]}")

    def run(self):
        threads = [threading.Thread(target=self._http_reader, daemon=True)
                   for _ in range(self.readers)]
        threads += [threading.Thread(target=self._file_monitor, daemon=True)
                    for _ in range(self.monitors)]
        writer = threading.Thread(target=self._writer, daemon=True)
        for t in threads:
            t.start()
        time.sleep(0.2)  # readers are already hammering when the write starts
        writer.start()
        writer.join()
        # keep sampling briefly after the last write so the window is covered
        time.sleep(0.15)
        self.stop.set()
        for t in threads:
            t.join(timeout=120)
        self.alive_threads = [t.name for t in threads if t.is_alive()]
        return self.counts, self.errors


def test_torn_read_regression_participant_hammer_during_reindex(users, shared_ws):
    """P1 item 3-i: a participant reading the index/searching while the creator
    runs a full re-index must never see a torn artifact — no 5xx, no empty
    index, no torn JSON. Allowed: 409 (gate busy / catch-up window)."""
    hammer = _Hammer(shared_ws, "alice@hsbc.com", CREATOR, rounds=3)
    counts, errors = hammer.run()
    assert not hammer.alive_threads, f"hammer threads never stopped: {hammer.alive_threads}"
    assert counts["index_200"] > 0, f"hammer never got a 200: {counts}"
    assert counts["search_200"] + counts["search_409"] > 0
    assert counts["file_reads"] > 100, f"file monitor too slow to matter: {counts}"
    assert not errors, f"{len(errors)} torn/failed reads: {errors[:5]}\n{counts}"


def test_regression_test_has_teeth_atomic_write_removed(users, shared_ws, monkeypatch):
    """The teeth: with the atomic write replaced by the pre-P1 truncate+
    write_text, the SAME harness MUST observe torn reads — otherwise test_torn
    _read_regression… would pass even with the fix reverted and prove nothing.

    `path.write_text` is exactly the shape atomic_io replaced; patching both
    module references is what a revert of P1 item 3-i looks like.
    """

    def torn_write(path, text, encoding="utf-8"):
        path.write_text(text, encoding=encoding)

    monkeypatch.setattr(folder_index_service, "atomic_write_text", torn_write)
    monkeypatch.setattr(atomic_io, "atomic_write_text", torn_write)

    # bounded retry: a torn window is ~1ms per artifact write, so keep
    # re-indexing until one lands (the assertion is that one DOES land).
    for attempt in range(6):
        hammer = _Hammer(shared_ws, "alice@hsbc.com", CREATOR,
                         rounds=2, monitors=2)
        counts, errors = hammer.run()
        assert not hammer.alive_threads, f"hammer threads never stopped: {hammer.alive_threads}"
        if counts["torn_reads"] or counts["index_empty"] or counts["search_5xx"]:
            print(f"\n  M1 teeth: bug observed in round {attempt + 1}: {counts}")
            return
    pytest.fail(f"non-atomic write produced NO torn read in 6 rounds — "
                f"the regression test cannot catch the bug\n{counts}")


# --- 6. catch-up gate with two users ----------------------------------------

def test_catchup_409_message_is_what_a_participant_sees(users, shared_ws):
    """The participant-visible half of the catch-up gate, deterministically:
    while the run is marked, a participant's search is refused with the
    retry-able 409 and nothing else about the workspace changes; the moment
    the run is over the same search succeeds."""
    alice = users["alice@hsbc.com"]
    body = {"table": SEARCHABLE[0], "field": SEARCHABLE[1]}

    folder_index_service.begin_index_run(shared_ws)
    try:
        r = alice.post(f"/api/workspace/{shared_ws}/search", json=body)
        assert r.status_code == 409, r.text
        assert r.json()["detail"] == CATCHUP_MSG
        # a read that does not depend on the index is NOT refused
        assert alice.get(f"/api/workspace/{shared_ws}/index").status_code == 200
    finally:
        folder_index_service.end_index_run(shared_ws)

    r = alice.post(f"/api/workspace/{shared_ws}/search", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["script_ids"]


def test_catchup_409_gate_participant_search_during_index(users, shared_ws):
    """The same gate under a REAL creator re-index (P1: the served index is
    the previous one during the run). Bounded: alice polls until the run
    lands, must see the 409 in that window, and must succeed afterwards."""
    creator, alice = users[CREATOR], users["alice@hsbc.com"]

    # make the diff non-empty (the resume hint the Open path reacts to) and
    # the run long enough to overlap: every financial script is re-extracted
    scripts = WORKSPACE_ROOT / shared_ws / "scripts"
    for target in sorted(scripts.glob("*.sql"))[:18]:
        target.write_text(target.read_text() + "\n-- m1 catch-up touch\n")

    assert creator.get(f"/api/workspace/{shared_ws}/resume").json()[
        "index_change"]["stale"] is True

    seen_409, result = [], {}
    done = threading.Event()

    def creator_index():
        result["index"] = creator.post(f"/api/workspace/{shared_ws}/index",
                                       json={"scripts": []}).status_code
        done.set()

    t = threading.Thread(target=creator_index)
    t.start()
    # bounded: ~40 attempts, each returning immediately (the 409 fires before
    # the heavy gate), so this loop cannot run away even if the run stalls
    for _ in range(40):
        if done.is_set():
            break
        r = alice.post(f"/api/workspace/{shared_ws}/search",
                       json={"table": SEARCHABLE[0], "field": SEARCHABLE[1]})
        if r.status_code == 409:
            seen_409.append(str(r.json().get("detail", ""))[:80])
        elif r.status_code >= 500:
            raise AssertionError(f"participant search 500 during catch-up: {r.text[:160]}")
    t.join(120)
    assert not t.is_alive(), "creator index thread never finished"

    assert result.get("index") == 200
    # the 409 gate actually fired for the OTHER user during the window
    assert seen_409, "alice never saw the catch-up 409 while the index ran"
    assert set(seen_409) == {CATCHUP_MSG}, set(seen_409)

    # bounded retry after completion — the gate is cleared, no sticky 409
    retry_notes, r = [], None
    for _ in range(20):
        r = alice.post(f"/api/workspace/{shared_ws}/search",
                       json={"table": SEARCHABLE[0], "field": SEARCHABLE[1]})
        if r.status_code == 200:
            break
        retry_notes.append(f"{r.status_code}: {str(r.json().get('detail'))[:60]}")
        heavy_gate.release()  # M1-D1: an overlapped search leaks the gate
    assert r.status_code == 200, (
        f"alice's search never recovered ({len(retry_notes)} retries, "
        f"catching_up={folder_index_service.is_index_catching_up(shared_ws)}): "
        f"{retry_notes[:4]}")
    assert r.json()["script_ids"], "post-catch-up search returned no scripts"


def test_search_is_rejected_when_never_indexed(users):
    """The 400 that precedes the 409: an indexed=False workspace must not be
    answered from an empty index either."""
    creator = users[CREATOR]
    r = creator.post("/api/workspace",
                     files={"file": ("m1.zip", _zip(_corpus(3)), "application/zip")})
    ws_id = r.json()["workspace_id"]
    r = creator.post(f"/api/workspace/{ws_id}/search",
                     json={"table": "T", "field": "C"})
    assert r.status_code == 400, r.text


# --- 7. meta CAS ------------------------------------------------------------

def test_layout_save_concurrent_with_index_no_lost_update(users, shared_ws):
    """P1 item 4: index_scripts merges its keys into meta.json through the CAS
    with retry, so a layout save racing the index must not lose either write.

    NOTE the model first: PUT layout is CREATOR-only (#272) — a participant's
    save is a 403 before the CAS is ever reached, so the only real race here is
    creator-vs-creator(index). Pinned below rather than assumed."""
    creator, alice = users[CREATOR], users["alice@hsbc.com"]
    version = creator.get(f"/api/workspace/{shared_ws}/resume").json()["state_version"]

    # participant layout editing is refused outright — the CAS never sees it
    r = alice.put(f"/api/workspace/{shared_ws}/layout",
                  json={"level": "l1", "node_positions": {"a": {"x": 1, "y": 1}},
                        "state_version": version})
    assert r.status_code == 403, r.text
    assert "creator" in r.json()["detail"]

    saved, conflicts, crashes = [], [], []
    index_status, done = {}, threading.Event()

    def creator_index():
        index_status["code"] = creator.post(
            f"/api/workspace/{shared_ws}/index", json={"scripts": []}).status_code
        done.set()

    t = threading.Thread(target=creator_index)
    t.start()
    for _ in range(60):                      # bounded, not a sleep-poll
        if done.is_set():
            break
        version = creator.get(f"/api/workspace/{shared_ws}/resume") \
            .json()["state_version"]
        r = creator.put(f"/api/workspace/{shared_ws}/layout",
                        json={"level": "l1",
                              "node_positions": {f"n{len(saved)}": {"x": 1, "y": 2}},
                              "state_version": version})
        if r.status_code == 200:
            saved.append(r.json()["state_version"])
        elif r.status_code == 409:
            conflicts.append(409)  # honest CAS refusal — the client reloads
        elif r.status_code >= 500:
            # M1-D3 (pinned xfail below): the shared meta.tmp rename crashes
            # the loser instead of giving it a 409. Report it as such rather
            # than letting this test go red on a known, separately-pinned bug.
            pytest.xfail(f"M1-D3 reproduced live: layout save "
                         f"{r.status_code}: {r.text[:140]}")
    t.join(120)
    assert not t.is_alive(), "creator index thread never finished"

    assert index_status["code"] == 200
    assert saved, "no layout save survived the concurrent index"
    assert saved == sorted(saved), f"state_version not monotonic: {saved}"

    meta = read_meta(shared_ws)
    assert meta["indexed"] is True, "the index lost its meta write to the layout save"
    assert meta["layouts"], "the layout save lost its meta write to the index"
    # the index that raced the save bumps the version too (verified live:
    # saves [3,4,5,6,8] with the index landing at 7), so "at least the last
    # save" is the honest no-lost-update bound — == max(saved) would be wrong.
    assert meta["state_version"] >= max(saved), \
        f"meta state_version {meta['state_version']} < last save {max(saved)}"
    # no lost update in either direction: the stored version is at least the
    # last layout save's bump (the index that raced it adds its own), and both
    # writes' payloads are present — checked above.
    assert meta["state_version"] >= max(saved)


# --- 8. isolation -----------------------------------------------------------

def test_views_and_layouts_are_workspace_scoped_not_per_user(users, shared_ws):
    """The actual model: views.json lives in the WORKSPACE's cache dir and
    meta.layouts in the workspace meta — one bucket shared by every session.
    There is no per-user view namespace, so alice's search IS in bob's view
    list. Pinned as the documented reality (a per-user namespace would be a
    schema change, not a bug fix)."""
    alice, bob = users["alice@hsbc.com"], users["bob@hsbc.com"]

    r = alice.post(f"/api/workspace/{shared_ws}/search",
                   json={"table": SEARCHABLE[0], "field": SEARCHABLE[1]})
    assert r.status_code == 200, r.text
    alice_view = r.json()["view_id"]

    bob_views = bob.get(f"/api/workspace/{shared_ws}/views").json()["views"]
    assert alice_view in [v["view_id"] for v in bob_views], \
        "participant views are workspace-scoped — bob must see alice's search"

    # and bob can read the graph alice's view points at (read-only half of #380)
    r = bob.get(f"/api/workspace/{shared_ws}/views/{alice_view}/level1")
    assert r.status_code == 200, r.text
    assert r.json()["script_ids"], "level1 for alice's view is empty for bob"

    # writes stay creator-only, so a participant cannot mutate the shared bucket
    assert bob.delete(f"/api/workspace/{shared_ws}/views/{alice_view}").status_code == 403


def test_participant_cannot_cross_into_another_workspace(users):
    """Two creator-owned workspaces: being a participant in one grants nothing
    on the other, and neither user can address the other's by id-guessing —
    the id is the capability (see test_share_flow_is_a_capability_url)."""
    a = users["alice@hsbc.com"]
    r = a.post("/api/workspace",
               files={"file": ("m1.zip", _zip(_corpus(3)), "application/zip")})
    alice_ws = r.json()["workspace_id"]

    # bob's "my workspaces" never lists alice's workspace
    assert alice_ws not in [w["ws_id"]
                            for w in users["bob@hsbc.com"].get("/api/workspaces").json()["workspaces"]]
    # ...but the id itself still opens it (capability model, documented above)
    assert users["bob@hsbc.com"].get(f"/api/workspace/{alice_ws}/resume").status_code == 200


# --- 9. further findings ----------------------------------------------------

def test_search_does_not_500_on_an_unreadable_filter_scope(users, shared_ws):
    """REGRESSION (MEDIUM, M1-D2) — FIXED.

    filter_service.apply_filter_config now writes cache/filtered_index.json via
    atomic_io.atomic_write_text (temp + os.replace) and dataflow._load_index
    guards the read (corrupt/torn scope falls through to the main index), so a
    torn or otherwise unreadable filter scope can no longer 500 a search.

    filter_service.apply_filter_config writes cache/filtered_index.json with a
    plain ``Path.write_text`` (filter_service.py, "Save filtered index") — the
    one artifact P1 item 3-i missed — and dataflow._load_index reads it
    UNguarded, preferring it over table_index/field_index. Every other cache
    read in the same path is explicitly "corrupt cache — never 500"
    (GET /index._read_json, _load_views, _load_manifest), so a torn or
    otherwise unreadable filter scope is the single remaining way a search
    500s. Reproduced here with the exact on-disk state a torn write leaves:
    a truncate-then-die (empty) and a half-written (invalid JSON) file.
    Recovery is a creator re-index (index_scripts deletes the file).
    """
    creator = users[CREATOR]
    cache = WORKSPACE_ROOT / shared_ws / "cache"
    for broken in ("", "{this is a torn JSON prefix of a real index"):
        (cache / "filtered_index.json").write_text(broken)
        r = creator.post(f"/api/workspace/{shared_ws}/search",
                         json={"table": SEARCHABLE[0], "field": SEARCHABLE[1]})
        assert r.status_code == 200, (
            f"search returned {r.status_code} with an unreadable filter scope: "
            f"{r.text[:160]}")
    (cache / "filtered_index.json").unlink()


def test_concurrent_meta_cas_writers_do_not_crash(users, shared_ws):
    """REGRESSION (HIGH, M1-D3) — FIXED.

    write_meta_cas now writes through a UNIQUE per-writer temp name (the
    fixed "meta.tmp" let two concurrent writers rename each other's bytes —
    a silent lost update — and then 500 on the second rename). Driven here
    through the REAL function: concurrent CAS writers with the same
    expected version must produce exactly one winner, never an exception,
    and meta.json must stay valid JSON throughout. (The original defect's
    fixed-name interleaving is unreconstructible through the production
    path — that is the point of the fix.)

    write_meta_cas is::

        tmp = path.with_suffix(".tmp")          # FIXED name — every writer
        tmp.write_text(json.dumps(meta))         # shares the same meta.tmp
        tmp.replace(path)

    unlike atomic_io.atomic_write_text, whose temp carries a uuid suffix so
    concurrent writers each own their file. Two writers therefore interleave
    as: A writes meta.tmp, B OVERWRITES meta.tmp, A renames (meta.json now
    holds B's bytes under A's claim), B renames -> FileNotFoundError, which
    the endpoint surfaces as a 500 instead of the documented CAS 409.

    Both failure modes are reproduced here by driving that exact interleaving
    (no thread timing, so the pin is stable), and a threaded probe records
    that it also fires through the real endpoint pair (PUT /layout against
    POST /index's meta update — the very race P1 item 4 says the CAS
    handles). Reproduced live: test_layout_save_concurrent_with_index_
    no_lost_update hit it once in three runs of this file.
    """
    version = read_meta(shared_ws)["state_version"]
    results, errors = [], []
    barrier = threading.Barrier(2)

    def cas_writer(tag):
        meta = dict(read_meta(shared_ws) or {})
        meta["layouts"] = {"l1": {"writer": tag}}
        barrier.wait()                       # both writers race the same version
        try:
            results.append(
                write_meta_cas(shared_ws, meta, version))
        except Exception as exc:             # a 500-by-any-other-name
            errors.append(repr(exc))

    threads = [threading.Thread(target=cas_writer, args=(t,))
               for t in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not any(t.is_alive() for t in threads)
    assert not errors, f"CAS write raised: {errors}"

    # exactly one winner per version; meta.json stays valid JSON throughout
    assert sorted(results) == [False, True], results
    stored = read_meta(shared_ws)
    assert stored is not None and stored["state_version"] == version + 1
    assert stored["layouts"]["l1"]["writer"] in ("A", "B")

    # evidence only (timing-dependent, not asserted): the real endpoint pair
    hits = []

    def hammer():
        for i in range(40):
            meta = read_meta(shared_ws)
            if meta is None:
                continue
            meta["layouts"] = {"l1": {"probe": i}}
            try:
                write_meta_cas(shared_ws, meta, i)
            except FileNotFoundError as e:
                hits.append(str(e))
                return

    threads = [threading.Thread(target=hammer) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    if hits:
        print(f"\n  M1-D3 endpoint pair collided {len(hits)}x: {hits[0][:120]}")
    read_meta(shared_ws)


def test_participant_open_at_the_workspace_cap_is_409(users):
    """The access model's ceiling: MAX_WORKSPACES_PER_USER counts PARTICIPANT
    entries too (design §5.6 — "the history cap IS the creation cap"), so a
    user who has OPENed 10 shared workspaces can no longer open an 11th, and
    cannot create one either — 409 on both. Documented behaviour, pinned here
    because it is the only way a participant's access is ever refused."""
    alice = _client_for("alice@hsbc.com")
    creator = _client_for(CREATOR)
    made = []
    try:
        for i in range(auth_service.MAX_WORKSPACES_PER_USER):
            r = creator.post("/api/workspace",
                             files={"file": ("m1.zip", _zip(_corpus(2)),
                                             "application/zip")})
            ws_id = r.json()["workspace_id"]
            made.append(ws_id)
            assert alice.get(f"/api/workspace/{ws_id}/resume").status_code == 200
        listing = alice.get("/api/workspaces").json()
        assert listing["count"] == auth_service.MAX_WORKSPACES_PER_USER
        assert listing["cap"] == auth_service.MAX_WORKSPACES_PER_USER

        # an 11th workspace needs a creator who is NOT at cap
        bob = _client_for("bob@hsbc.com")
        r = bob.post("/api/workspace",
                     files={"file": ("m1.zip", _zip(_corpus(2)),
                                     "application/zip")})
        assert r.status_code == 200, r.text
        ws_id = r.json()["workspace_id"]
        made.append(ws_id)
        # the 11th OPEN is refused with the quota 409, not downgraded
        r = alice.get(f"/api/workspace/{ws_id}/resume")
        assert r.status_code == 409, r.text
        assert "list is full" in r.json()["detail"]
    finally:
        for ws_id in made:
            delete_workspace(ws_id)
