"""MSC-3 — the multi-user audit trail (the History panel's "who did what").

GET /activity shipped labels for visit_start / visit_end / search / l2_opened
/ layout_saved, but the trail was CREATION-ONLY: #285 dropped visit logging and
the other actions were never written, so a workspace could be opened,
searched, indexed, laid out and closed by two people and still hold exactly
one record (`workspace_created`). The trail now records every action the
server actually performs, for real sessions only, and is BOUNDED.

Covers here:
* the record set (create / visit_start / search / l2_opened / layout_saved /
  visit_end / creator scan+index) with the right actor on each record;
* what must NOT be recorded (participant reads, refused writes, dev-mode
  traffic with the login gate off — synthetic "dev-user" is not an actor);
* the MSC-4 shape promise: {username, ip, ts, action, detail} — the R31 shape
  the History panel already renders, no new PII;
* the MSC-5 lesson: the trail is capped, and concurrent appends (the append
  path IS the R31 O_APPEND append) lose nothing while a trim runs under them.

Runs IN-PROCESS with the login gate flipped ON per test (the same technique
test_multiuser_sessions.py uses) — records are written for real sessions only,
so the gate must be on for the HTTP-path tests to have an actor.
"""

import io
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app
from app.routers import workspace as workspace_router
from app.services import audit_service, auth_service
from app.services.audit_service import append_activity, read_activity
from app.services.workspace_service import (
    WORKSPACE_ROOT, create_workspace, delete_workspace,
)

client = TestClient(app)

USERS = {
    "creator@hsbc.com": "creator-pass-1",
    "alice@hsbc.com": "alice-pass-1",
}


# ── fixtures / helpers ────────────────────────────────────────────────────


@pytest.fixture()
def _gate_on(monkeypatch):
    """Force the login gate ON for the request middleware AND `_session_ctx`."""
    monkeypatch.setattr(app_main, "REQUIRE_LOGIN", True)
    monkeypatch.setattr(workspace_router, "REQUIRE_LOGIN", True)


@pytest.fixture()
def _accounts(_gate_on):
    """Provision the two accounts; restore every piece of process-global state."""
    users_before = auth_service.load_users()
    for name, pw in USERS.items():
        assert auth_service.provision_user(name, pw, force=True)
    users = auth_service.load_users()
    for name in USERS:
        users.setdefault(name, {})["workspaces"] = []
    auth_service.save_users(users)
    auth_service.reset_for_tests()
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


def _user(username):
    c = TestClient(app)
    _login(c, username)
    return c


def _zip_bytes(n_scripts=6, tag="a"):
    """A small but real multi-script workspace (pipeline SQL only)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i in range(2):
            zf.writestr(f"dim_{tag}{i}.sql",
                        f"CREATE TABLE dim_{tag}{i} (id INT, code STRING);\n")
        for i in range(n_scripts):
            j = i % 2
            zf.writestr(
                f"q_{tag}{i}.sql",
                f"INSERT INTO out_{tag}{i} SELECT id, code FROM dim_{tag}{j} "
                f"WHERE code = '{i}';\n"
                f"SELECT id, code FROM out_{tag}{i} WHERE id > {i};\n")
    return buf.getvalue()


@pytest.fixture()
def shared_ws(_accounts):
    """creator owns an indexed workspace; alice is a participant (has resumed)."""
    creator = _user("creator@hsbc.com")
    r = creator.post("/api/workspace",
                     files={"file": ("at.zip", _zip_bytes(), "application/zip")})
    assert r.status_code == 200, r.text
    ws_id = r.json()["workspace_id"]
    assert creator.post(f"/api/workspace/{ws_id}/index",
                        json={"scripts": []}).status_code == 200
    alice = _user("alice@hsbc.com")
    assert alice.get(f"/api/workspace/{ws_id}/resume").status_code == 200
    return creator, alice, ws_id


def _actions(ws_id):
    return [r["action"] for r in read_activity(ws_id)]


# ── 1. the records themselves ─────────────────────────────────────────────


def test_creator_create_records_workspace_created(_accounts):
    creator = _user("creator@hsbc.com")
    r = creator.post("/api/workspace",
                     files={"file": ("cr.zip", _zip_bytes(), "application/zip")})
    assert r.status_code == 200
    ws_id = r.json()["workspace_id"]

    trail = read_activity(ws_id)
    assert [t["action"] for t in trail][0] == "workspace_created"
    assert trail[0]["username"] == "creator@hsbc.com"
    assert "creator@hsbc.com" in (trail[0]["detail"] or "")
    assert trail[0]["ip"], "MSC-4: the existing record shape keeps the client ip"
    assert trail[0]["ts"]


def test_participant_open_records_visit_start_with_username(shared_ws):
    _creator, alice, ws_id = shared_ws
    # shared_ws already resumed; resume once more — every open is a visit
    assert alice.get(f"/api/workspace/{ws_id}/resume").status_code == 200
    records = [r for r in read_activity(ws_id) if r["action"] == "visit_start"]
    assert records, "an open/resume must leave a visit_start record"
    assert records[-1]["username"] == "alice@hsbc.com"
    assert records[-1]["ip"]


def test_searches_record_search(shared_ws):
    creator, alice, ws_id = shared_ws
    assert alice.post(f"/api/workspace/{ws_id}/search",
                      json={"table": "dim_a0", "field": "code"}).status_code == 200
    assert alice.post(f"/api/workspace/{ws_id}/search",
                      json={"table": "dim_a1", "field": "code"}).status_code == 200
    searches = [r for r in read_activity(ws_id) if r["action"] == "search"]
    assert [s["detail"] for s in searches] == ["dim_a0.code", "dim_a1.code"]
    assert {s["username"] for s in searches} == {"alice@hsbc.com"}

    # a refused search is nobody's action — nothing is recorded for it
    before = len(read_activity(ws_id))
    assert alice.post(f"/api/workspace/{ws_id}/search",
                      json={"table": "", "field": ""}).status_code == 400
    assert len(read_activity(ws_id)) == before


def test_layout_save_records_layout_saved(shared_ws):
    creator, alice, ws_id = shared_ws
    assert creator.put(f"/api/workspace/{ws_id}/layout",
                       json={"level": "l1",
                             "node_positions": {"a": [1, 2]}}).status_code == 200
    saved = [r for r in read_activity(ws_id) if r["action"] == "layout_saved"]
    assert len(saved) == 1
    assert saved[0]["username"] == "creator@hsbc.com"
    assert saved[0]["detail"] == "l1"

    # an L2 layout names its script
    assert creator.put(f"/api/workspace/{ws_id}/layout",
                       json={"level": "l2", "script": "q_a0.sql",
                             "node_positions": {}}).status_code == 200
    saved = [r for r in read_activity(ws_id) if r["action"] == "layout_saved"]
    assert saved[-1]["detail"] == "l2:q_a0.sql"

    # a refused write (participant, #272) records nothing
    before = len(read_activity(ws_id))
    assert alice.put(f"/api/workspace/{ws_id}/layout",
                     json={"level": "l1", "node_positions": {}}).status_code == 403
    assert len(read_activity(ws_id)) == before


def test_close_records_visit_end(shared_ws):
    _creator, alice, ws_id = shared_ws
    assert alice.post(f"/api/workspace/{ws_id}/close").status_code == 200
    ends = [r for r in read_activity(ws_id) if r["action"] == "visit_end"]
    assert len(ends) == 1
    assert ends[0]["username"] == "alice@hsbc.com"
    assert ends[0]["ip"]
    # the visit is bookended: her visit_start came first
    trail = _actions(ws_id)
    assert trail.index("visit_start") < trail.index("visit_end")


def test_l2_open_records_l2_opened(shared_ws):
    _creator, alice, ws_id = shared_ws
    assert alice.post(f"/api/workspace/{ws_id}/search",
                      json={"table": "dim_a0", "field": "code"}).status_code == 200
    views = alice.get(f"/api/workspace/{ws_id}/views").json()["views"]
    vid = views[-1]["view_id"]
    assert alice.get(
        f"/api/workspace/{ws_id}/views/{vid}/level2?script=q_a0.sql").status_code == 200
    opens = [r for r in read_activity(ws_id) if r["action"] == "l2_opened"]
    assert len(opens) == 1
    assert opens[0]["username"] == "alice@hsbc.com"
    assert opens[0]["detail"] == "q_a0.sql"


def test_creator_scan_and_index_are_recorded(shared_ws):
    creator, alice, ws_id = shared_ws
    before = len(read_activity(ws_id))   # the fixture already indexed once
    assert creator.post(f"/api/workspace/{ws_id}/scan").status_code == 200
    assert creator.post(f"/api/workspace/{ws_id}/index",
                        json={"scripts": []}).status_code == 200
    trail = read_activity(ws_id)[before:]
    assert [r["action"] for r in trail] == ["scan", "index"]
    assert {r["username"] for r in trail} == {"creator@hsbc.com"}
    assert trail[1]["detail"].endswith("scripts")
    # a participant cannot trigger either (#380) — and is not recorded trying
    assert alice.post(f"/api/workspace/{ws_id}/scan").status_code == 403
    assert alice.post(f"/api/workspace/{ws_id}/index",
                      json={"scripts": []}).status_code == 403
    assert len(read_activity(ws_id)) == before + 2


def test_participant_reads_and_dev_mode_are_not_recorded(_accounts, monkeypatch):
    """Reads are not actions, and dev mode (gate off, synthetic "dev-user") is
    not an actor — the whole existing suite runs in that world and must not
    start filling trails with synthetic records."""
    monkeypatch.setattr(app_main, "REQUIRE_LOGIN", False)
    monkeypatch.setattr(workspace_router, "REQUIRE_LOGIN", False)
    ws_id = create_workspace(_zip_bytes(), creator_username="seed@hsbc.com")
    try:
        anon = TestClient(app)  # no session — the gate is OFF here
        assert anon.get(f"/api/workspace/{ws_id}/resume").status_code == 200
        assert anon.post(f"/api/workspace/{ws_id}/close").status_code == 200
        assert read_activity(ws_id) == []
    finally:
        delete_workspace(ws_id)


def test_full_participant_visit_leaves_a_readable_trail(shared_ws):
    """The original MSC-3 defect, end to end: creator creates + indexes,
    participant opens, searches, opens an L2, closes — the History panel can
    answer who did what."""
    creator, alice, ws_id = shared_ws
    assert alice.post(f"/api/workspace/{ws_id}/search",
                      json={"table": "dim_a0", "field": "code"}).status_code == 200
    views = alice.get(f"/api/workspace/{ws_id}/views").json()["views"]
    vid = views[-1]["view_id"]
    assert alice.get(
        f"/api/workspace/{ws_id}/views/{vid}/level2?script=q_a0.sql").status_code == 200
    assert alice.post(f"/api/workspace/{ws_id}/close").status_code == 200

    trail = read_activity(ws_id)
    assert [r["action"] for r in trail] == [
        "workspace_created", "index", "visit_start", "search", "l2_opened",
        "visit_end"]
    assert [r["username"] for r in trail] == [
        "creator@hsbc.com", "creator@hsbc.com", "alice@hsbc.com",
        "alice@hsbc.com", "alice@hsbc.com", "alice@hsbc.com"]
    # MSC-4: the panel's existing record shape, unchanged — and a participant
    # reads the shared trail (kept as-is, consistent with the read-only model)
    assert all(set(r) == {"username", "ip", "ts", "action", "detail"} for r in trail)
    assert alice.get(f"/api/workspace/{ws_id}/activity").json()["activity"] == trail
    assert creator.get(f"/api/workspace/{ws_id}/activity").json()["activity"] == trail


# ── 2. the trail is bounded (MSC-5's views.json lesson) ───────────────────


def test_trail_is_bounded_at_the_cap(monkeypatch, _accounts):
    """A busy shared workspace cannot grow activity.json without limit: the
    trail holds exactly the last ACTIVITY_CAP records — no more."""
    ws_id = create_workspace(_zip_bytes(), creator_username="seed@hsbc.com")
    try:
        monkeypatch.setattr(audit_service, "ACTIVITY_CAP", 10)
        for i in range(60):
            append_activity(ws_id, "u@hsbc.com", "127.0.0.1", "search", f"#{i}")
        trail = read_activity(ws_id)
        assert len(trail) == 10
        # the OLDEST records are the ones dropped — the trail is a window on
        # the recent past, not a random sample
        assert [t["detail"] for t in trail] == [f"#{i}" for i in range(50, 60)]
    finally:
        delete_workspace(ws_id)


def test_appends_past_the_cap_keep_landing(monkeypatch, _accounts):
    """The cap trims history, it never blocks a new record: the newest action
    is always present, on a trail that stays parseable throughout."""
    ws_id = create_workspace(_zip_bytes(), creator_username="seed@hsbc.com")
    try:
        monkeypatch.setattr(audit_service, "ACTIVITY_CAP", 20)
        for i in range(60):
            append_activity(ws_id, "u@hsbc.com", "127.0.0.1", "search", f"#{i}")
            trail = read_activity(ws_id)
            assert len(trail) <= 20
        trail = read_activity(ws_id)
        assert len(trail) == 20
        assert trail[-1]["detail"] == "#59"
        assert all(t["action"] == "search" for t in trail)
    finally:
        delete_workspace(ws_id)


def test_nonzero_slack_batches_the_rewrites(monkeypatch, _accounts):
    """The opt-in trade: _ACTIVITY_TRIM_SLACK lets a trail at the cap absorb
    SLACK records before it is rewritten (it then oscillates CAP..CAP+SLACK
    and still never grows without bound)."""
    ws_id = create_workspace(_zip_bytes(), creator_username="seed@hsbc.com")
    try:
        monkeypatch.setattr(audit_service, "ACTIVITY_CAP", 20)
        monkeypatch.setattr(audit_service, "_ACTIVITY_TRIM_SLACK", 10)
        for i in range(20 + audit_service._ACTIVITY_TRIM_SLACK):
            append_activity(ws_id, "u@hsbc.com", "127.0.0.1", "search", f"#{i}")
        # the threshold is exactly reached, so nothing was rewritten yet
        assert len(read_activity(ws_id)) == 30
        append_activity(ws_id, "u@hsbc.com", "127.0.0.1", "search", "#last")
        trail = read_activity(ws_id)
        assert len(trail) == 20
        assert trail[-1]["detail"] == "#last"
    finally:
        delete_workspace(ws_id)


def test_long_detail_is_clipped(_accounts):
    """One huge payload must not blow the cap: a detail string is clipped."""
    ws_id = create_workspace(_zip_bytes(), creator_username="seed@hsbc.com")
    try:
        append_activity(ws_id, "u@hsbc.com", "127.0.0.1", "search", "x" * 5000)
        record = read_activity(ws_id)[0]
        assert len(record["detail"]) == audit_service._DETAIL_MAX
    finally:
        delete_workspace(ws_id)


def test_record_file_stays_0600(_accounts):
    """The capped trail keeps the R31 #318 permission (mode 0600)."""
    ws_id = create_workspace(_zip_bytes(), creator_username="seed@hsbc.com")
    try:
        append_activity(ws_id, "u@hsbc.com", "127.0.0.1", "search", "d")
        path = WORKSPACE_ROOT / ws_id / "activity.json"
        assert (path.stat().st_mode & 0o777) == 0o600
        assert ((WORKSPACE_ROOT / ws_id / audit_service._TRAIL_LOCK_NAME)
                .stat().st_mode & 0o777) == 0o600
    finally:
        delete_workspace(ws_id)


def test_non_ascii_records_round_trip_through_the_readers(_accounts, monkeypatch):
    """X2 (review): `_append_record` writes `ensure_ascii=False` — raw UTF-8
    bytes — so the readers must NAME the encoding. A locale-dependent read
    (`Path.read_text()` with no encoding) decodes correctly only where the
    preferred encoding happens to be UTF-8; under a C/POSIX locale the first
    non-ASCII detail (a Chinese table name in a search's detail, a UTF-8
    username) raises UnicodeDecodeError, which the readers' blanket
    `except Exception` swallows into `[]` — the History panel goes silently
    blank instead of showing the trail, and `_trim_to_cap` silently stops
    trimming (the cap would leak).

    The hazard cannot be reproduced by a mere round-trip on a UTF-8 host (the
    container's preferred encoding IS UTF-8), so the encoding itself is spied
    on: every trail read must pass encoding='utf-8' explicitly."""
    from pathlib import Path
    ws_id = create_workspace(_zip_bytes(), creator_username="seed@hsbc.com")
    try:
        append_activity(ws_id, "用户@hsbc.com", "127.0.0.1", "search", "表.t_column")
        seen: dict = {}
        real_read_text = Path.read_text

        def spy_read_text(self, *args, **kwargs):
            enc = kwargs.get("encoding")
            seen[enc] = seen.get(enc, 0) + 1
            return real_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", spy_read_text)

        trail = read_activity(ws_id)
        assert len(trail) == 1, "one non-ASCII record must not blank the trail"
        assert trail[0]["username"] == "用户@hsbc.com"
        assert trail[0]["detail"] == "表.t_column"
        assert seen.get("utf-8"), f"the trail read names no encoding: {seen}"
        assert None not in seen, f"locale-dependent read on the trail: {seen}"

        # the cap trim rewrites the file too — the non-ASCII record survives it
        monkeypatch.undo()
        append_activity(ws_id, "u2@hsbc.com", "127.0.0.1", "search", "ascii")
        assert [t["detail"] for t in read_activity(ws_id)] \
            == ["表.t_column", "ascii"]
        # the server-global audit log is read back the same way
        audit_service.append_audit("用户@hsbc.com", "127.0.0.1", ws_id,
                                   "workspace deleted")
        assert audit_service.read_audit()[-1]["username"] == "用户@hsbc.com"
    finally:
        delete_workspace(ws_id)


# ── 3. concurrent appends lose nothing (atomic) ───────────────────────────


def _burst(ws_id, threads, per_thread, tag):
    def one(i):
        for j in range(per_thread):
            append_activity(ws_id, f"u{i}@hsbc.com", "127.0.0.1", "search",
                            f"{tag}-{i}-{j}")
    with ThreadPoolExecutor(max_workers=threads) as pool:
        list(pool.map(one, range(threads)))


def test_concurrent_appends_all_land_intact(monkeypatch, _accounts):
    """8 threads × 40 appends, cap out of the way → every record present,
    every line parseable, none torn or duplicated."""
    ws_id = create_workspace(_zip_bytes(), creator_username="seed@hsbc.com")
    try:
        monkeypatch.setattr(audit_service, "ACTIVITY_CAP", 10_000)
        _burst(ws_id, threads=8, per_thread=40, tag="raw")
        trail = read_activity(ws_id)
        assert len(trail) == 8 * 40
        assert len({t["detail"] for t in trail}) == 8 * 40
        assert {t["username"] for t in trail} == {f"u{i}@hsbc.com" for i in range(8)}
    finally:
        delete_workspace(ws_id)


def test_concurrent_appends_survive_a_simultaneous_trim(monkeypatch, _accounts):
    """The dangerous window: the cap trim IS a read-modify-write, so appends
    landing while a trim runs must be serialized — the file ends up with
    exactly the last ACTIVITY_CAP records, every one of them intact."""
    ws_id = create_workspace(_zip_bytes(), creator_username="seed@hsbc.com")
    try:
        monkeypatch.setattr(audit_service, "ACTIVITY_CAP", 50)
        _burst(ws_id, threads=8, per_thread=40, tag="cap")   # 320 ≫ cap
        raw = (WORKSPACE_ROOT / ws_id / "activity.json").read_text()
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        # bounded: a trim runs under nearly every one of those appends
        assert len(lines) == 50, len(lines)
        trail = read_activity(ws_id)
        assert len(trail) == len(lines)      # every stored line parses — none torn
        assert len({t["detail"] for t in trail}) == len(trail)  # none duplicated
        # the survivors are the tail of the burst, not its head: some thread's
        # final append (j == 39) is still on the trail (the last writer is
        # whichever thread the executor scheduled last, so only the max binds)
        last_rounds = [int(t["detail"].rsplit("-", 1)[1]) for t in trail]
        assert max(last_rounds) == 39
    finally:
        delete_workspace(ws_id)
