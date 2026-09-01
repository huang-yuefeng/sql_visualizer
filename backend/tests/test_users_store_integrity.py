"""P2 — the two users.json store defects the 2026-09-01 audit accepted.

Both live in the same durable store (``WORKSPACE_ROOT/users.json``: one JSON
object per username → ``{salt, password_hash, created_at, last_login_ip,
workspaces:[…]}``) and both were SILENT — nothing crashed, data disappeared:

  DEFECT 1 — ``login()`` rode a whole-store read-modify-write to record
  ``last_login_ip``. A concurrent ``provision_user`` (the R31.35 startup
  force-sync racing a user's first login) or a second login could interleave
  its own load→mutate→save cycle and the loser's write was dropped: a freshly
  synced password reverts, a newly provisioned account vanishes. The store's
  RMWs are serialized behind ``auth_service._users_lock`` (the fix the
  ``CODE_REVIEW_2026-08-24.md`` item "users.json RMW has no lock" asked for),
  so the tests here pin the GUARANTEE — the login's effect and the
  provision's effect both land, on the same record and on different records —
  and ``test_pre_fix_whole_store_write_drops_the_provision`` replays the
  pre-fix whole-store write by hand (deterministically, no thread timing) to
  show those assertions really do detect the loss.

  DEFECT 2 — ``delete_workspace()`` only rmtree'd the directory: the per-user
  index entries were purged only by the API path
  (routers → ``remove_from_my_history`` → ``remove_ws_from_all_indexes``).
  Any out-of-band delete (the test janitor, a manual ``rm``, a future admin
  tool) left EVERY user's entry pointing at a deleted workspace FOREVER — and
  each dead entry still consumed ``MAX_WORKSPACES_PER_USER``, so dead entries
  could lock a real user out of opening a new workspace. Both existing test
  files already documented the symptom
  (``test_r31_auth._cleanup`` / ``test_participant_reads._cleanup``:
  "delete_workspace leaves the creator's users.json index row behind").
  ``delete_workspace`` now runs the same purge itself.

Conventions mirror ``test_r31_auth._cleanup`` / ``test_multiuser_workspace
._env``: the session store, users.json and the workspace dirs this file
creates are captured and put back per test, so the file is
order-independent — it passes alone and inside the full suite.
"""

import io
import threading
import zipfile

import pytest

from app.services import auth_service
from app.services.workspace_service import (
    WORKSPACE_ROOT, create_workspace, delete_workspace,
)

CAROL = "carol@hsbc.com"
DAVE = "dave@hsbc.com"
ERIN = "erin@hsbc.com"

CAROL_PW = "carol-pw"
CAROL_PW_SYNCED = "carol-pw-synced"          # the R31.35 force-sync value
DAVE_PW = "dave-pw"
DAVE_PW_SYNCED = "dave-pw-synced"
ERIN_PW = "erin-pw"

LOGIN_IP = "10.1.2.3"


# --- harness ----------------------------------------------------------------

def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("t1.sql", "SELECT a FROM t1;\n")
    return buf.getvalue()


def _password_ok(username: str, password: str) -> bool:
    """Does the on-disk record for `username` still verify `password`?"""
    rec = auth_service.load_users().get(username) or {}
    return auth_service._verify_password(
        password, rec.get("salt", ""), rec.get("password_hash", ""))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Save/restore the process globals this file touches, per test.

    users.json is snapshotted and put back (the store is durable and shared by
    the whole container), the in-memory session/backoff state is reset, and
    only workspace dirs THIS file created are removed.
    """
    monkeypatch.setattr(auth_service, "_PBKDF2_ITERATIONS", 2000)  # fast verify
    auth_service.reset_for_tests()
    before = {p.name for p in WORKSPACE_ROOT.iterdir()}
    users_before = auth_service.load_users()
    yield
    auth_service.reset_for_tests()
    auth_service.save_users(users_before)
    for p in WORKSPACE_ROOT.iterdir():
        if p.is_dir() and p.name not in before:
            try:
                delete_workspace(p.name)
            except OSError:
                pass


def _run_together(*bodies) -> list:
    """Run the callables concurrently, return their return values in order.

    A body that raises is recorded and re-raised after the join (a dead thread
    must not wedge the barrier for the others), and every ``barrier.wait`` is
    bounded so a crashed sibling can never hang the test.
    """
    barrier = threading.Barrier(len(bodies))
    results, errors = [None] * len(bodies), []

    def body(i, fn):
        try:
            barrier.wait(timeout=30)
            results[i] = fn()
        except Exception as exc:                     # a 500-by-any-other-name
            errors.append((i, repr(exc)))
            barrier.abort()

    threads = [threading.Thread(target=body, args=(i, fn))
               for i, fn in enumerate(bodies)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not any(t.is_alive() for t in threads), "a writer never finished"
    assert not errors, f"concurrent writer(s) raised: {errors}"
    return results


# --- DEFECT 1: login vs provision_user — no lost update ---------------------

def _reset_store(extra: tuple = ()) -> None:
    """Put the store back to a known state (NO threads running here — this is
    an unlocked test-side write, like test_multiuser_workspace's
    ``_establish_accounts``)."""
    auth_service.reset_for_tests()
    auth_service.save_users({})
    assert auth_service.provision_user(CAROL, CAROL_PW, force=True)
    for username in extra:
        assert auth_service.provision_user(username, DAVE_PW, force=True)


def test_login_concurrent_with_provision_loses_nothing():
    """The audit's scenario, driven through the REAL service functions in
    threads: a login racing the R31.35-style force-sync must lose NOTHING.

    Three shapes, each repeated (a single pass can pass by luck of the
    scheduler; the loss needs one writer's load→mutate→save to straddle the
    other's):

      * SAME record — login(CAROL) rides provision_user(CAROL, force=True).
        The two writers touch the SAME user record, so this is the sharp form:
        the writes must MERGE (last_login_ip recorded AND the synced password
        kept), never clobber.
      * SAME record, ambiguous acceptance — the login supplies the POST-sync
        password, so it is accepted when it reads the synced record and
        rejected when it reads the pre-sync one. Either is correct; what is
        NEVER correct is the store ending up holding the stale password again,
        or an accepted login losing its IP.
      * DIFFERENT records — login(CAROL) rides a password re-sync (DAVE) and a
        fresh create (ERIN). The create is the account that "vanishes".
    """
    for _ in range(25):
        _reset_store()
        _run_together(
            lambda: auth_service.login(CAROL, CAROL_PW, LOGIN_IP),
            lambda: auth_service.provision_user(CAROL, CAROL_PW_SYNCED, force=True),
        )
        assert _password_ok(CAROL, CAROL_PW_SYNCED), \
            "the synced password reverted — the login's write clobbered the sync"
        assert not _password_ok(CAROL, CAROL_PW), \
            "the stale password came back — the sync's write was dropped"

    for _ in range(25):
        _reset_store()
        results = _run_together(
            lambda: auth_service.login(CAROL, CAROL_PW_SYNCED, LOGIN_IP),
            lambda: auth_service.provision_user(CAROL, CAROL_PW_SYNCED, force=True),
        )
        token = results[0]
        assert token is None or auth_service.get_session(token)["username"] == CAROL
        assert _password_ok(CAROL, CAROL_PW_SYNCED), "the synced password reverted"
        assert not _password_ok(CAROL, CAROL_PW), "the stale password came back"
        if token is not None:
            assert auth_service.load_users()[CAROL]["last_login_ip"] == LOGIN_IP, \
                "an accepted login lost its last_login_ip to the force-sync"

    for _ in range(25):
        _reset_store(extra=(DAVE,))
        _run_together(
            lambda: auth_service.login(CAROL, CAROL_PW, LOGIN_IP),
            lambda: auth_service.provision_user(DAVE, DAVE_PW_SYNCED, force=True),
            lambda: auth_service.provision_user(ERIN, ERIN_PW, force=True),
        )
        users = auth_service.load_users()
        assert set(users) == {CAROL, DAVE, ERIN}, \
            f"an account vanished: {sorted(set(users) ^ {CAROL, DAVE, ERIN})}"
        assert users[CAROL]["last_login_ip"] == LOGIN_IP, "login's write was dropped"
        assert _password_ok(DAVE, DAVE_PW_SYNCED), "the re-sync was dropped"
        assert _password_ok(ERIN, ERIN_PW), "the fresh account was dropped"
        assert _password_ok(CAROL, CAROL_PW), "an unrelated account was touched"


def test_pre_fix_whole_store_write_drops_the_provision():
    """TEETH — the assertions above must be able to FAIL.

    The defect is a stale whole-store snapshot written back over a newer
    store. Reproduced deterministically (no thread timing): take login's
    read, land both provisions on top of it, then replay the pre-v3.3.165
    login write from that stale snapshot — exactly what ``login`` did before
    the store RMW was serialized. Both audit symptoms appear at once: the
    freshly synced password reverts AND the newly provisioned account
    vanishes.
    """
    auth_service.provision_user(CAROL, CAROL_PW, force=True)
    stale = auth_service.load_users()                       # login's read

    assert auth_service.provision_user(CAROL, CAROL_PW_SYNCED, force=True)
    assert auth_service.provision_user(DAVE, DAVE_PW, force=True)

    rec = stale.get(CAROL)                                  # pre-fix login:
    rec["last_login_ip"] = LOGIN_IP                         # its OWN record,
    stale[CAROL] = rec                                      # whole store back
    auth_service.save_users(stale)

    users = auth_service.load_users()
    assert DAVE not in users, "pre-fix shape unexpectedly kept the new account"
    assert _password_ok(CAROL, CAROL_PW), "pre-fix shape unexpectedly kept the sync"
    assert not _password_ok(CAROL, CAROL_PW_SYNCED), "stale write did not revert"
    assert users[CAROL]["last_login_ip"] == LOGIN_IP        # the only survivor


# --- DEFECT 2: delete_workspace purges every user's index -------------------

def test_delete_workspace_purges_every_users_index_and_frees_the_quota():
    """Out-of-band delete (service call, NOT the API path): the workspace
    disappears from EVERY user's index and the quota it consumed is freed.

    Before the fix the entries survived forever — each one still counted
    against MAX_WORKSPACES_PER_USER, so enough dead entries locked a real
    user out of opening a new workspace (409 "list is full")."""
    auth_service.provision_user(CAROL, CAROL_PW, force=True)
    auth_service.provision_user(DAVE, DAVE_PW, force=True)
    auth_service.provision_user(ERIN, ERIN_PW, force=True)

    ws_id = create_workspace(_zip_bytes(), creator_username=CAROL)
    assert auth_service.add_workspace_to_index(CAROL, ws_id, "creator")
    assert auth_service.add_workspace_to_index(DAVE, ws_id, "participant")
    assert auth_service.add_workspace_to_index(ERIN, ws_id, "participant")

    # carol sits exactly at the cap with the doomed entry plus fillers, so the
    # test can see the quota actually FREE (not just the entry disappear).
    cap = auth_service.MAX_WORKSPACES_PER_USER
    fillers = [f"deadbeef{i:024x}" for i in range(cap - 1)]
    for filler in fillers:
        assert auth_service.add_workspace_to_index(CAROL, filler, "creator")
    assert len(auth_service._index_of(CAROL)) == cap
    assert not auth_service.index_has_room(CAROL)

    assert delete_workspace(ws_id) is True
    assert not (WORKSPACE_ROOT / ws_id).exists()

    for username in (CAROL, DAVE, ERIN):
        entries = auth_service._index_of(username)
        assert all(w["ws_id"] != ws_id for w in entries), (
            f"{username} still indexes the deleted workspace "
            f"({sum(1 for w in entries if w['ws_id'] == ws_id)} dead entries)")
    assert [w["ws_id"] for w in auth_service._index_of(CAROL)] == fillers, \
        "the purge took unrelated entries with it"
    assert len(auth_service._index_of(CAROL)) == cap - 1
    assert auth_service.index_has_room(CAROL), "the dead entry kept its quota slot"


def test_out_of_band_delete_leaves_no_dead_entry_behind_at_the_cap():
    """The lock-out the audit described, end to end: a user at the cap whose
    LAST slot is a dead entry can open a new workspace again once the purging
    delete ran (``add_workspace_to_index`` used to answer False forever)."""
    auth_service.provision_user(CAROL, CAROL_PW, force=True)
    cap = auth_service.MAX_WORKSPACES_PER_USER

    doomed = create_workspace(_zip_bytes(), creator_username=CAROL)
    for i in range(cap - 1):
        assert auth_service.add_workspace_to_index(
            CAROL, f"cafe0000{i:021x}", "creator")
    assert auth_service.add_workspace_to_index(CAROL, doomed, "creator")
    assert not auth_service.index_has_room(CAROL)

    # a manual rm / the janitor: the DIRECTORY goes, nothing else does
    delete_workspace(doomed)
    assert auth_service.index_has_room(CAROL)

    fresh = create_workspace(_zip_bytes(), creator_username=CAROL)
    assert auth_service.add_workspace_to_index(CAROL, fresh, "creator"), \
        "the dead entry still consumed the last quota slot"
    assert all(w["ws_id"] != doomed for w in auth_service._index_of(CAROL))
