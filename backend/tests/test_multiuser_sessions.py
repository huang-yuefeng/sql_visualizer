"""MSC — multi-user session lifecycle, capability isolation, and scale.

Team MSC verification suite (2026-08-31), run against a live service in
process with the login gate FORCED ON (conftest.py forces REQUIRE_LOGIN=false
before any app import; the `_gate_on` fixture flips it back in-process, the
same technique test_r31_auth.py uses for the #293 public-exemption surface).

Covers the three multi-user dimensions nothing else exercises:

1. Session lifecycle — login → use → logout → 401 everywhere → re-login;
   forged/absent cookies on every endpoint class, including the handlers
   that do NOT call `_session_ctx` themselves (they are covered only by the
   login_gate middleware in main.py).
2. Capability isolation — what a participant who was handed one workspace id
   can and cannot reach: another user's workspace by id, forged ids, the
   per-user "my workspaces" index, and the activity/audit trail.
3. Scale — 5 participants reading a shared workspace while the creator
   re-indexes it (the atomic-index-write + catch-up-gate guarantees), and
   view/meta isolation under concurrency.

Two tests used to be marked ``xfail(strict=False)`` because they pinned the
MSC-1 defect found by this suite. MSC-1 is FIXED now (per-call gate tokens),
so both run as ordinary regression pins:

* MSC-1 — ``HeavyGate`` used to store per-call state (``self._acquired``) on
  the module-level singleton. Two overlapping acquisitions lost the release
  and the module-global ``_busy`` stayed True forever: every search (and
  every /analyze) service-wide returned 409 "system busy — please wait" until
  the process restarted. Both tests still restore ``heavy_gate._busy`` in a
  ``finally`` so a regression can never wedge the rest of the suite.
"""

import hashlib
import io
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app
from app.routers import workspace as workspace_router
from app.services import auth_service, heavy_gate
from app.services.workspace_service import WORKSPACE_ROOT, delete_workspace

client = TestClient(app)

USERS = {
    "creator@hsbc.com": "creator-pass-1",
    "alice@hsbc.com": "alice-pass-1",
    "bob@hsbc.com": "bob-pass-1",
    "carol@hsbc.com": "carol-pass-1",
    "dave@hsbc.com": "dave-pass-1",
    "erin@hsbc.com": "erin-pass-1",
}


# ── fixtures / helpers ────────────────────────────────────────────────────


@pytest.fixture()
def _gate_on(monkeypatch):
    """Force the login gate ON for the request middleware AND `_session_ctx`."""
    monkeypatch.setattr(app_main, "REQUIRE_LOGIN", True)
    monkeypatch.setattr(workspace_router, "REQUIRE_LOGIN", True)


@pytest.fixture()
def _clean(_gate_on, monkeypatch):
    """Provision the MSC accounts; restore every piece of process-global state.

    Order-independence rules this fixture follows:
    * the account store is snapshotted BEFORE provisioning and restored
      verbatim, so whatever another test file left behind survives this file;
    * the heavy gate is forced idle through monkeypatch — a gate wedged by an
      earlier test in the same process (MSC-1) must not turn every search in
      this file into a 409, and whatever this file inherits is what the next
      file sees (monkeypatch restores it, so nothing leaks in either
      direction);
    * workspaces created here are removed here.
    """
    users_before = auth_service.load_users()   # snapshot BEFORE provisioning
    for name, pw in USERS.items():
        assert auth_service.provision_user(name, pw, force=True)
    # The MSC accounts must start with an EMPTY workspace index: in a
    # long-lived test container a reused account can already sit at the
    # MAX_WORKSPACES_PER_USER cap, which turns every create into a 409.
    users = auth_service.load_users()
    for name in USERS:
        users.setdefault(name, {})["workspaces"] = []
    auth_service.save_users(users)
    auth_service.reset_for_tests()          # drop sessions created by setup
    monkeypatch.setattr(heavy_gate, "_busy", False)
    before = {p.name for p in WORKSPACE_ROOT.iterdir()}
    yield
    auth_service.reset_for_tests()
    auth_service.save_users(users_before)
    for name in {p.name for p in WORKSPACE_ROOT.iterdir()} - before:
        delete_workspace(name)


def _login(client_, username):
    r = client_.post("/api/auth/login",
                     json={"username": username, "password": USERS[username]})
    assert r.status_code == 200, r.text
    return r


def _new_client():
    return TestClient(app)


def _creator_client():
    c = _new_client()
    _login(c, "creator@hsbc.com")
    return c


def _zip_bytes(n_scripts=12, tag="a"):
    """A small but real multi-script workspace (pipeline SQL only)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i in range(6):
            zf.writestr(f"dim_{tag}{i}.sql",
                        f"CREATE TABLE dim_{tag}{i} (id INT, code STRING);\n")
        for i in range(n_scripts):
            j = i % 6
            zf.writestr(
                f"q_{tag}{i}.sql",
                f"INSERT INTO out_{tag}{i} SELECT id, code FROM dim_{tag}{j} "
                f"WHERE code = '{i}';\n"
                f"SELECT id, code FROM out_{tag}{i} WHERE id > {i};\n")
    return buf.getvalue()


def _make_workspace(creator_client, name_tag, n_scripts=12):
    r = creator_client.post("/api/workspace",
                            files={"file": (f"{name_tag}.zip",
                                            _zip_bytes(n_scripts, name_tag),
                                            "application/zip")})
    assert r.status_code == 200, r.text
    ws_id = r.json()["workspace_id"]
    r = creator_client.post(f"/api/workspace/{ws_id}/index", json={"scripts": []})
    assert r.status_code == 200, r.text
    return ws_id, r.json().get("script_count")


# ── 1. session lifecycle ──────────────────────────────────────────────────


def test_login_use_logout_then_401_then_relogin(_clean):
    creator = _creator_client()
    ws_id, _ = _make_workspace(creator, "lc")
    s = _new_client()

    _login(s, "alice@hsbc.com")
    assert s.get(f"/api/workspace/{ws_id}/resume").status_code == 200

    assert s.post("/api/auth/logout").status_code == 200

    # the destroyed session must be rejected on every endpoint class
    for method, url, kw in [
        ("get", "/api/auth/me", None),
        ("get", "/api/workspaces", None),
        ("get", f"/api/workspace/{ws_id}/resume", None),
        ("get", f"/api/workspace/{ws_id}/views", None),
        ("get", f"/api/workspace/{ws_id}/index", None),
        ("get", f"/api/workspace/{ws_id}/activity", None),
        ("post", f"/api/workspace/{ws_id}/search",
         {"json": {"table": "dim_a0", "field": "code"}}),
    ]:
        r = getattr(s, method)(url, **(kw or {}))
        assert r.status_code == 401, f"{method} {url} -> {r.status_code}"

    # ...and a fresh login works again
    _login(s, "alice@hsbc.com")
    assert s.get(f"/api/workspace/{ws_id}/resume").status_code == 200


def test_forged_or_absent_cookie_is_401_on_every_endpoint(_clean):
    """The middleware is the ONLY gate for several handlers — spot-check them."""
    ws_id, _ = _make_workspace(_creator_client(), "ck")
    forged = _new_client()
    forged.cookies.set("session", "deadbeef" * 8)
    anonymous = _new_client()

    endpoints = [
        ("get", "/api/auth/me", None),
        ("get", "/api/workspaces", None),
        ("get", f"/api/workspace/{ws_id}", None),             # no _session_ctx
        ("get", f"/api/workspace/{ws_id}/status", None),      # no _session_ctx
        ("get", f"/api/workspace/{ws_id}/resume", None),
        ("get", f"/api/workspace/{ws_id}/tree", None),
        ("get", f"/api/workspace/{ws_id}/index", None),
        ("get", f"/api/workspace/{ws_id}/activity", None),
        ("get", f"/api/workspace/{ws_id}/views", None),
        ("get", f"/api/workspace/{ws_id}/autocomplete?type=table&q=a", None),
        ("get", f"/api/workspace/{ws_id}/export-config", None),
        ("get", f"/api/workspace/{ws_id}/logs", None),
        ("post", f"/api/workspace/{ws_id}/search",
         {"json": {"table": "dim_a0", "field": "code"}}),
        ("post", f"/api/workspace/{ws_id}/scan", None),
    ]
    for method, url, kw in endpoints:
        for who, c in (("forged-cookie", forged), ("no-cookie", anonymous)):
            r = getattr(c, method)(url, **(kw or {}))
            assert r.status_code == 401, f"{who} {method} {url} -> {r.status_code}"


def test_last_login_ip_is_recorded_and_surfaced(_clean):
    s = _new_client()
    _login(s, "alice@hsbc.com")
    me = s.get("/api/auth/me").json()
    assert me["username"] == "alice@hsbc.com"
    # TestClient requests arrive from "testclient" — the point is that the
    # login IP is captured at login and served back, not that it is any
    # particular value.
    assert me["last_login_ip"], me


# ── 2. capability isolation ───────────────────────────────────────────────


@pytest.fixture()
def shared_pair(_clean):
    """creator owns W1 (shared to alice) and W2 (never shared)."""
    creator = _new_client()
    _login(creator, "creator@hsbc.com")
    w1, _ = _make_workspace(creator, "w1")
    w2, _ = _make_workspace(creator, "w2")
    alice = _new_client()
    _login(alice, "alice@hsbc.com")
    assert alice.get(f"/api/workspace/{w1}/resume").status_code == 200
    return creator, alice, w1, w2


def test_alice_never_sees_w2_in_her_own_workspace_list(shared_pair):
    _creator, alice, w1, w2 = shared_pair
    body = alice.get("/api/workspaces").json()
    ids = [w["ws_id"] for w in body["workspaces"]]
    assert ids == [w1]                      # exactly her own entry
    assert w2 not in ids
    assert body["count"] == 1


def test_w2_is_nowhere_in_any_payload_alice_can_read(shared_pair):
    _creator, alice, shared_id, private_id = shared_pair
    for url in ("/api/workspaces",
                f"/api/workspace/{shared_id}/resume",
                f"/api/workspace/{shared_id}/activity",
                f"/api/workspace/{shared_id}/views",
                f"/api/workspace/{shared_id}/tree",
                f"/api/workspace/{shared_id}/index",
                f"/api/workspace/{shared_id}/status"):
        assert private_id not in alice.get(url).text, url


def test_forged_workspace_id_is_never_200(shared_pair):
    """One flipped hex char and a random md5 must 404 on every read path."""
    _creator, alice, w1, _w2 = shared_pair
    flipped = w1[:-1] + ("0" if w1[-1] != "0" else "1")
    bogus = [flipped, ("0" if w1[0] != "0" else "1") + w1[1:],
             hashlib.md5(b"msc").hexdigest()]
    for wid in bogus:
        for path in ("resume", "tree", "index", "activity", "views", "status",
                     "autocomplete?type=table&q=a", "export-config"):
            r = alice.get(f"/api/workspace/{wid}/{path}")
            assert r.status_code == 404, f"{wid}/{path} -> {r.status_code}"
        assert alice.get(f"/api/workspace/{wid}").status_code == 404
    # a malformed id is a 400 (validate-first), never an enumeration oracle
    assert alice.get("/api/workspace/abc/resume").status_code == 400


def test_capability_id_grants_full_read_of_an_unshared_workspace(shared_pair):
    """MSC-2 (pinned): the ws_id IS the capability.

    A participant who is handed ONE id and later obtains another id by any
    route gets FULL read access to that workspace: there is no membership
    check on any read endpoint. Only the creator-only writes return 403.
    (Design §3 / A-H4: "any logged-in user who knows the id can open it" —
    but note there is no revocation and no per-user visibility.)
    """
    _creator, alice, _w1, w2 = shared_pair
    assert alice.get(f"/api/workspace/{w2}/resume").status_code == 200   # not 404/403
    for path in ("tree", "index", "views", "activity", "status",
                 "autocomplete?type=table&q=a", "export-config"):
        assert alice.get(f"/api/workspace/{w2}/{path}").status_code == 200, path
    assert alice.get(f"/api/workspace/{w2}").status_code == 200
    # ...and she can even search it
    r = alice.post(f"/api/workspace/{w2}/search",
                   json={"table": "dim_w20", "field": "code"})
    assert r.status_code == 200
    # writes stay creator-only
    assert alice.post(f"/api/workspace/{w2}/scan").status_code == 403
    assert alice.post(f"/api/workspace/{w2}/index",
                      json={"scripts": []}).status_code == 403
    assert alice.put(f"/api/workspace/{w2}/layout",
                     json={"level": "l1", "node_positions": {}}).status_code == 403


def test_user_with_no_id_cannot_enumerate_but_id_open_still_works(shared_pair):
    _creator, _alice, w1, w2 = shared_pair
    bob = _new_client()
    _login(bob, "bob@hsbc.com")
    body = bob.get("/api/workspaces").json()
    assert body["workspaces"] == [] and body["count"] == 0
    assert w1 not in bob.get("/api/workspaces").text
    assert w2 not in bob.get("/api/workspaces").text
    # capability model: the id alone is enough, nothing else is checked
    assert bob.get(f"/api/workspace/{w1}/resume").status_code == 200


def test_activity_log_records_participant_actions(shared_pair):
    """MSC-3 (FIXED): the "who did what" trail now answers the question.

    It used to be creation-only — #285 dropped visit logging and every other
    action was never written, so the History panel's labels (visit_start /
    visit_end / search / l2_opened / layout_saved) could never fire no matter
    what a participant did. The trail now records the visit end to end.

    Read-only participant actions (GET tree/index/autocomplete/level1) stay
    OUT of the trail: they are reads, and a busy shared workspace would churn
    the trail with them (the same reason the trail is capped — see
    tests/test_audit_trail.py).
    """
    creator, alice, w1, _w2 = shared_pair
    alice.get(f"/api/workspace/{w1}/tree")
    alice.get(f"/api/workspace/{w1}/index")
    alice.get(f"/api/workspace/{w1}/autocomplete?type=table&q=a")
    assert alice.post(f"/api/workspace/{w1}/search",
                      json={"table": "dim_w10", "field": "code"}).status_code == 200
    views = alice.get(f"/api/workspace/{w1}/views").json()["views"]
    vid = views[-1]["view_id"]
    alice.get(f"/api/workspace/{w1}/views/{vid}/level1")
    # a participant may not edit the layout (#272) — and must never be blamed
    # for an action the server refused
    assert alice.put(f"/api/workspace/{w1}/layout",
                     json={"level": "l1", "node_positions": {}}).status_code == 403
    alice.post(f"/api/workspace/{w1}/close")

    activity = creator.get(f"/api/workspace/{w1}/activity").json()["activity"]
    actions = [a["action"] for a in activity]
    assert actions == ["workspace_created",   # the creator's upload
                       "index",               # the creator's index run
                       "visit_start",         # alice opened it
                       "search",              # alice searched
                       "visit_end"], actions  # alice closed it
    # the search record names the actor, the query, and the client IP
    assert activity[3]["username"] == "alice@hsbc.com"
    assert activity[3]["detail"] == "dim_w10.code"
    assert activity[3]["ip"]
    # MSC-4: the record shape is the R31 one the History panel already
    # renders — username + ip carried over, nothing new added.
    assert set(activity[0]) == {"username", "ip", "ts", "action", "detail"}
    # a participant reads the same shared trail (read-only model, as-is)
    assert alice.get(f"/api/workspace/{w1}/activity").json()["activity"] == activity


# ── MSC-1 (FIXED): the heavy gate keeps its release under concurrency ─────


def test_two_overlapping_enters_still_release(_clean):
    """MSC-1 regression pin (was xfail = defect): per-call state on a shared
    singleton used to lose the release.

    HeavyGate.__enter__ used to write ``self._acquired`` on the module-level
    ``gate`` instance, so a second (refused) entrant overwrote the first's
    True before the first unwound and neither __exit__ released — the
    module-global ``_busy`` stayed True forever. Each call now carries its own
    token, so the holder's release survives the refused entrant.
    """
    g = heavy_gate.HeavyGate()
    first = g.__enter__()
    second = g.__enter__()
    g.__exit__(None, None, None)     # the refused entrant unwinds first
    g.__exit__(None, None, None)     # the real holder unwinds — and releases
    try:
        # the per-call token is truthy iff THIS call acquired (the contract the
        # routers test with `if not acquired: raise HTTPException(409, ...)`)
        assert first
        assert not second
        assert first.acquired is True and second.acquired is False
        assert heavy_gate._busy is False, (
            "MSC-1: the gate is wedged — every future search service-wide 409s")
    finally:
        heavy_gate._busy = False


def test_two_overlapping_searches_do_not_wedge_search_service_wide(_clean):
    """MSC-1 regression pin (was xfail = defect), end to end: 5 simultaneous
    searches used to leave the gate permanently busy, so every later search
    (any user, any workspace) returned 409 "system busy — please wait" until
    the process restarted. After the burst the gate must be idle again."""
    ws_id, _ = _make_workspace(_creator_client(), "gw")

    def one(i):
        c = _new_client()
        _login(c, f"carol@hsbc.com" if i == 0 else "erin@hsbc.com")
        return c.post(f"/api/workspace/{ws_id}/search",
                      json={"table": f"dim_a{i % 6}", "field": "code"}).status_code

    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            codes = list(pool.map(one, range(5)))
        assert set(codes) <= {200, 409}, codes
        time.sleep(0.5)
        after = client.post(f"/api/workspace/{ws_id}/search",
                            json={"table": "dim_a0", "field": "code"})
        assert heavy_gate._busy is False, \
            "MSC-1: the heavy gate was left busy by one overlapping burst"
        assert not (after.status_code == 409 and "system busy" in after.text), \
            "MSC-1: search is 409 'system busy' for every user until restart"
    finally:
        heavy_gate._busy = False


# ── 3. scale: reads during a creator re-index ─────────────────────────────


def test_five_participants_read_while_creator_reindexes(_clean):
    """5 participants hammer the read paths while the creator re-indexes twice.

    Asserts the guarantees the atomic-index-write + catch-up-gate work
    promises: zero 5xx, zero empty/shrunk index reads, every catch-up 409
    inside a re-index window, and bounded latency (no threadpool starvation).
    """
    creator = _new_client()
    _login(creator, "creator@hsbc.com")
    ws_id, _ = _make_workspace(creator, "sc", n_scripts=14)

    # one search per participant so each owns a view (created serially — see MSC-1)
    fields = [(f"dim_a{i}", "code") for i in range(5)]
    vids = []
    for table, field in fields:
        r = creator.post(f"/api/workspace/{ws_id}/search",
                         json={"table": table, "field": field})
        assert r.status_code == 200, r.text
        vids.append(r.json()["view_id"])

    records = []
    lock = threading.Lock()
    stop = threading.Event()
    windows = []

    def participant(i):
        name = ["alice", "bob", "carol", "dave", "erin"][i]
        c = _new_client()
        _login(c, f"{name}@hsbc.com")
        table, field = fields[i]
        while not stop.is_set():
            for op in ("index", "tree", "views", "level2", "resume"):
                t0 = time.time()
                if op == "index":
                    r = c.get(f"/api/workspace/{ws_id}/index")
                elif op == "tree":
                    r = c.get(f"/api/workspace/{ws_id}/tree")
                elif op == "views":
                    r = c.get(f"/api/workspace/{ws_id}/views")
                elif op == "level2":
                    r = c.get(f"/api/workspace/{ws_id}/views/{vids[i]}/level2",
                              params={"script": f"q_sc{i % 6}.sql", "filter": "true"})
                else:
                    r = c.get(f"/api/workspace/{ws_id}/resume")
                with lock:
                    records.append((time.time(), name, op, r.status_code,
                                    time.time() - t0, r.text))
                if op == "index" and r.status_code == 200:
                    body = r.json()
                    assert body["table_index"], "empty table_index (torn read)"
                    assert body["field_index"], "empty field_index (torn read)"
                    assert len(body["table_index"]) >= 6, "shrunk index"

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(participant, i) for i in range(5)]
        # let the readers reach a steady state, then re-index twice; the second
        # re-index runs while the readers are live
        steady = threading.Event()
        timer = threading.Timer(0.5, steady.set)
        timer.start()
        steady.wait(5)
        timer.cancel()
        for _ in range(2):
            t0 = time.time()
            r = creator.post(f"/api/workspace/{ws_id}/index", json={"scripts": []})
            windows.append((t0, time.time()))
            assert r.status_code == 200, r.text
        # Serialized search sampling of the catch-up gate, until the readers
        # stop. The record's timestamp is the REQUEST START: a 409 means the
        # index was in flight when the request arrived, so containment is
        # judged against when it arrived, not when the answer came back.
        for _ in range(60):
            t0 = time.time()
            r = creator.post(f"/api/workspace/{ws_id}/search",
                             json={"table": "dim_a0", "field": "code"})
            with lock:
                records.append((t0, "creator", "search", r.status_code,
                                time.time() - t0, r.text))
            if stop.wait(0.05):
                break
        stop.set()
        for f in futures:
            f.result(timeout=60)

    assert records, "no traffic recorded"
    fivehundreds = [r for r in records if 500 <= r[3] < 600]
    assert not fivehundreds, fivehundreds[:3]
    timeouts = [r for r in records if r[4] > 30]
    assert not timeouts, timeouts[:3]

    # every catch-up 409 must fall inside a re-index window (0.4s tolerance)
    for ts, _who, op, status, _dt, text in records:
        if status == 409:
            assert "Index is being updated" in text or "system busy" in text, text[:80]
            if "Index is being updated" in text:
                lo = min(w[0] for w in windows) - 0.4
                hi = max(w[1] for w in windows) + 0.4
                assert lo <= ts <= hi, "catch-up 409 outside the re-index window"

    # latency bounded — report, and fail only on real starvation
    per_op = {}
    for _ts, _who, op, _status, dt, _text in records:
        per_op.setdefault(op, []).append(dt)
    report = {op: (round(sorted(v)[len(v) // 2], 3), round(sorted(v)[int(len(v) * 0.95)], 3))
              for op, v in per_op.items()}
    assert all(p95 < 10 for _, p95 in report.values()), report

    # no cross-user bleed: every participant still resolves its own view
    for i, (table, field) in enumerate(fields):
        c = _new_client()
        _login(c, f"{['alice', 'bob', 'carol', 'dave', 'erin'][i]}@hsbc.com")
        views = c.get(f"/api/workspace/{ws_id}/views").json()["views"]
        assert any(v["view_id"] == vids[i] and v["table"] == table
                   and v["field"] == field for v in views)


# ── meta/views isolation under concurrency ────────────────────────────────


def test_views_are_workspace_global_and_only_the_creator_writes(shared_pair):
    """Views are SHARED workspace state: a participant's search lands in the
    list every participant reads, and a participant may not delete it."""
    creator, alice, w1, _w2 = shared_pair
    alice.post(f"/api/workspace/{w1}/search", json={"table": "dim_w10", "field": "code"})
    bob = _new_client()
    _login(bob, "bob@hsbc.com")
    bob.get(f"/api/workspace/{w1}/resume")

    views = bob.get(f"/api/workspace/{w1}/views").json()["views"]
    assert any(v["table"] == "dim_w10" for v in views), \
        "alice's search view is not visible to bob (views are per-workspace, shared)"

    vid = views[-1]["view_id"]
    assert bob.delete(f"/api/workspace/{w1}/views/{vid}").status_code == 403
    assert alice.delete(f"/api/workspace/{w1}/views/{vid}").status_code == 403
    assert creator.delete(f"/api/workspace/{w1}/views/{vid}").status_code == 200


def test_concurrent_searches_never_lose_a_persisted_view(_clean):
    """The _views_lock lost-update fix: every 200 search must leave exactly one
    persisted view, even when several participants search at once."""
    creator = _creator_client()
    ws_id, _ = _make_workspace(creator, "vv")
    users = ["alice@hsbc.com", "bob@hsbc.com", "carol@hsbc.com",
             "dave@hsbc.com", "erin@hsbc.com"]
    results = []
    lock = threading.Lock()

    def search(i):
        c = _new_client()
        _login(c, users[i % len(users)])
        r = c.post(f"/api/workspace/{ws_id}/search",
                   json={"table": f"dim_a{i % 6}", "field": "code"})
        with lock:
            results.append(r.status_code)
        return r.status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(search, range(18)))
    ok = results.count(200)
    assert ok > 0, results
    views = creator.get(f"/api/workspace/{ws_id}/views").json()["views"]
    assert len(views) >= ok, (
        f"lost update: {ok} successful searches but {len(views)} persisted views")
