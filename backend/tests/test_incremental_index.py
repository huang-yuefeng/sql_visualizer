"""P1 (v3.3.194): incremental re-index + index freshness/catching-up.

USER PROBLEM: a creator re-opening an existing workspace re-ran the whole
extraction pipeline on every POST /index (measured 2.28-2.37s on the
106-script tpcds_qualified corpus, 70% of it inside run_full_analysis,
identical on every open — nothing was reused).

Design (c): the index persists, per script, the PRISTINE pre-S4b analysis
(snapshot of exactly what index_scripts consumes) keyed by
md5(EXTRACTOR_VERSION|rel_path|sql_text); a later index re-aggregates from
snapshots for unchanged scripts and re-extracts only changed/new ones. S4b
and the C-5 star expansion always re-run — they are workspace-wide.

Pinned here:
  * A/B equivalence — full index vs incremental-after-no-changes produce
    BYTE-IDENTICAL artifacts AND analysis caches (the analysis cache is
    S4b-mutated in place, so the snapshot must restore it, not reuse it);
  * idempotency — a second incremental run changes nothing;
  * edit + add + delete — only the touched script is re-extracted, the
    artifacts reflect the change, and the result equals a full re-index;
  * zero-changed index costs 0 extractions;
  * change hint (content hash) — null before the first index, zero diff
    after, honest counts after an edit/add/delete;
  * filtered_index refresh — a scope derived from the PREVIOUS index is
    dropped on re-index, never silently kept;
  * catching-up — searches during an index run get a retry-able 409, a
    zero-diff open never blocks.

In-process, login gate OFF (conftest), mirroring test_participant_reads.py.
"""

import gzip
import hashlib
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
from app.services import folder_index_service as fis  # noqa: E402
from app.services.workspace_service import (  # noqa: E402
    WORKSPACE_ROOT, create_workspace, delete_workspace, get_workspace_dir,
    read_meta,
)

client = TestClient(app)

# Two independent pipeline scripts, one DDL evidence file (S4b has schema
# evidence to work with), one star query (the C-5 pass has something to
# expand) — a small but representative index pipeline.
SQL = {
    "ddl_a.sql": "CREATE TABLE a (f INT, g INT);\n",
    "q1.sql": "SELECT f FROM a;\n",
    "q2.sql": "SELECT * FROM b;\n",
    "ddl_b.sql": "CREATE TABLE b (f INT, k INT);\n",
}


def _zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, sql in entries.items():
            zf.writestr(name, sql)
    return buf.getvalue()


def _make_ws(entries: dict) -> str:
    return create_workspace(_zip(entries), creator_username="dev-user")


@pytest.fixture(autouse=True)
def _cleanup():
    before = {p.name for p in WORKSPACE_ROOT.iterdir()}
    yield
    for p in WORKSPACE_ROOT.iterdir():
        if p.is_dir() and p.name not in before:
            delete_workspace(p.name)


def _artifact_digests(ws_id: str) -> dict:
    """sha256 of every index artifact — the byte-identity witness."""
    cache_dir = get_workspace_dir(ws_id) / "cache"
    out = {}
    for name in ("table_index.json", "field_index.json", "pair_index.json",
                 "index_report.json", "file_tree.json", "orphan_fields.json"):
        p = cache_dir / name
        if p.exists():
            out[name] = hashlib.sha256(p.read_bytes()).hexdigest()
        else:
            out[name] = None
    return out


def _analysis_digests(ws_id: str) -> dict:
    """{script_name: sha256} of every analysis cache — l1_builder's input."""
    out = {}
    for p in sorted((get_workspace_dir(ws_id) / "cache")
                    .glob("analysis_*.json")):
        data = json.loads(p.read_text())
        out[data.get("script_name", p.name)] = \
            hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _index(ws_id: str, scripts=None, **kw) -> dict:
    if scripts is None:
        pc = {}
        tree = fis.scan_folder(ws_id, parsed_cache=pc,
                               class_cache=fis.manifest_class_cache(ws_id))
        scripts = _collect(tree)
        return fis.index_scripts(ws_id, scripts, tree=tree,
                                 parsed_cache=pc, **kw)
    return fis.index_scripts(ws_id, scripts, **kw)


def _collect(tree: dict) -> list:
    """_collect_sql_files (imported lazily to mirror the router)."""
    from app.routers.workspace import _collect_sql_files
    return _collect_sql_files(tree)


class ExtractionCounter:
    """Count run_full_analysis calls — the "who got re-extracted" witness."""

    def __init__(self, monkeypatch):
        import app.extractor.adapter as adapter
        self.calls = []
        self._real = adapter.run_full_analysis
        self._adapter = adapter
        counter = self

        def counting(sql_text, script_name, ws_id=None):
            counter.calls.append(script_name)
            return counter._real(sql_text, script_name, ws_id=ws_id)

        monkeypatch.setattr(adapter, "run_full_analysis", counting)

    def seen(self, name) -> bool:
        return name in self.calls


# ══════════════════════════════════════════════════════════════════════
# A/B equivalence + idempotency
# ══════════════════════════════════════════════════════════════════════

def test_incremental_matches_full_reindex_byte_for_byte():
    """The core proof: a full index and an incremental index over UNCHANGED
    content produce identical bytes for every artifact and every analysis
    cache. (A naive reuse of the S4b-mutated analysis cache fails this:
    the M12 conflict detector finds no candidates left to re-test, the DDL
    evidence pass writes no analysis cache at all, and the counters drift.)"""
    ws = _make_ws(SQL)
    try:
        _index(ws)                                    # full (no evidence yet)
        full_artifacts = _artifact_digests(ws)
        full_analysis = _analysis_digests(ws)
        full_report = _index(ws)                      # incremental (replay)
        # a silent per-script failure would make both legs "identical" and
        # empty — the equivalence is only meaningful over a real index
        assert full_report["errors"] == [], full_report["errors"]
        assert full_report["script_count"] == 2
        assert _artifact_digests(ws) == full_artifacts
        assert _analysis_digests(ws) == full_analysis
        # the report values are identical too, not just the files
        for key in ("script_count", "resolution_stats",
                    "schema_candidates_summary", "schema_evidence",
                    "orphan_field_count"):
            assert full_report[key] == _index(ws)[key]
    finally:
        delete_workspace(ws)


def test_second_incremental_run_is_idempotent():
    ws = _make_ws(SQL)
    try:
        _index(ws)
        _index(ws)
        snap = _artifact_digests(ws)
        report = _index(ws)
        assert _artifact_digests(ws) == snap
        assert report["reused_scripts"] == 2 and report["extracted_scripts"] == 0
        assert fis.get_index_progress(ws)["phase"] == "done"
    finally:
        delete_workspace(ws)


def test_incremental_disabled_flag_does_full_extraction(monkeypatch):
    """`incremental=False` re-extracts everything (the A/B 'full' leg) while
    still persisting evidence."""
    ws = _make_ws(SQL)
    try:
        _index(ws)
        counter = ExtractionCounter(monkeypatch)
        _index(ws, incremental=False)
        # the two DDL evidence files go through the pipeline too (A1), so a
        # full index is 4 analyses; a replayed one is 0
        assert sorted(counter.calls) == ["ddl_a.sql", "ddl_b.sql", "q1.sql",
                                         "q2.sql"], counter.calls
    finally:
        delete_workspace(ws)


# ══════════════════════════════════════════════════════════════════════
# edit / add / delete
# ══════════════════════════════════════════════════════════════════════

def _edit_add_delete(ws_id: str) -> dict:
    """1/4 scripts edited, 1 added, 1 deleted → returns the artifacts of the
    incremental index that follows."""
    ws_dir = get_workspace_dir(ws_id)
    (ws_dir / "scripts" / "q1.sql").write_text(
        "SELECT f, g FROM a;\n")                       # EDIT
    (ws_dir / "scripts" / "q4.sql").write_text(
        "SELECT g FROM a WHERE f > 1;\n")              # ADD
    (ws_dir / "scripts" / "q2.sql").unlink()           # DELETE
    return _index(ws_id)


def test_edit_add_delete_reextracts_only_touched_scripts(monkeypatch):
    ws = _make_ws(SQL)
    try:
        _index(ws)
        counter = ExtractionCounter(monkeypatch)
        _edit_add_delete(ws)
        # untouched: ddl_a + ddl_b replay their DDL evidence (no analysis)
        assert not counter.seen("ddl_a.sql"), counter.calls
        assert not counter.seen("ddl_b.sql"), counter.calls
        # touched: the edit + the addition (the deleted script is gone)
        assert counter.seen("q1.sql") and counter.seen("q4.sql"), counter.calls
        assert counter.calls.count("q1.sql") == 1
    finally:
        delete_workspace(ws)


def test_edit_add_delete_result_equals_full_reindex():
    """The incremental result after a real change set is the same index a
    full rebuild of the same content produces (byte-level)."""
    ws_inc = _make_ws(SQL)
    ws_full = _make_ws(SQL)
    try:
        _index(ws_inc)
        _edit_add_delete(ws_inc)
        inc = _artifact_digests(ws_inc)

        ws_dir = get_workspace_dir(ws_full)
        (ws_dir / "scripts" / "q1.sql").write_text("SELECT f, g FROM a;\n")
        (ws_dir / "scripts" / "q4.sql").write_text(
            "SELECT g FROM a WHERE f > 1;\n")
        (ws_dir / "scripts" / "q2.sql").unlink()
        _index(ws_full)                                # full over same content
        assert _artifact_digests(ws_full) == inc
    finally:
        delete_workspace(ws_inc)
        delete_workspace(ws_full)


def test_edited_script_is_served_by_the_new_index():
    """The artifacts reflect the change — a new field reaches search."""
    ws = _make_ws(SQL)
    try:
        _index(ws)
        fi_before = json.loads(
            (get_workspace_dir(ws) / "cache" / "field_index.json").read_text())
        assert "g" not in fi_before
        _edit_add_delete(ws)
        fi = json.loads(
            (get_workspace_dir(ws) / "cache" / "field_index.json").read_text())
        assert "g" in fi, sorted(fi)
        assert "q2.sql" not in fi["f"]["scripts"], fi["f"]
        assert "q4.sql" in fi["f"]["scripts"], fi["f"]
    finally:
        delete_workspace(ws)


def test_deleted_scripts_evidence_is_pruned():
    ws = _make_ws(SQL)
    try:
        _index(ws)
        cache_dir = get_workspace_dir(ws) / "cache"
        before = {p.name for p in cache_dir.glob("ixevidence_*.json.gz")}
        _edit_add_delete(ws)
        after = {p.name for p in cache_dir.glob("ixevidence_*.json.gz")}
        # q2.sql deleted → its evidence is gone; q4.sql added → one new file
        assert len(after) == len(before), (before, after)
    finally:
        delete_workspace(ws)


def test_zero_changed_index_costs_no_extractions(monkeypatch):
    """The common open: nothing changed → 0 extractions, index unchanged."""
    ws = _make_ws(SQL)
    try:
        _index(ws)
        counter = ExtractionCounter(monkeypatch)
        report = _index(ws)
        assert counter.calls == [], counter.calls
        assert report["reused_scripts"] == 2
        assert report["extracted_scripts"] == 0
    finally:
        delete_workspace(ws)


def test_corrupt_evidence_falls_back_to_extraction(monkeypatch):
    """A truncated/garbled evidence file is a cache MISS, never a failure."""
    ws = _make_ws(SQL)
    try:
        _index(ws)
        cache_dir = get_workspace_dir(ws) / "cache"
        for p in cache_dir.glob("ixevidence_q1*.json.gz"):
            pass
        evidence = sorted(cache_dir.glob("ixevidence_*.json.gz"))
        assert evidence
        evidence[0].write_bytes(b"not gzip at all")
        counter = ExtractionCounter(monkeypatch)
        report = _index(ws)
        assert len(counter.calls) == 1, counter.calls
        assert report["script_count"] == 2
        assert report["errors"] == []
    finally:
        delete_workspace(ws)


def test_extractor_version_bump_invalidates_evidence(monkeypatch):
    """The evidence key embeds EXTRACTOR_VERSION — a bump is a full
    re-extraction (and the stale evidence files are pruned)."""
    ws = _make_ws(SQL)
    try:
        _index(ws)
        monkeypatch.setattr(fis, "EXTRACTOR_VERSION", "9999-test-bump")
        counter = ExtractionCounter(monkeypatch)
        report = _index(ws)
        assert sorted(counter.calls) == ["ddl_a.sql", "ddl_b.sql", "q1.sql",
                                         "q2.sql"], counter.calls
        assert report["reused_scripts"] == 0
    finally:
        delete_workspace(ws)


# ══════════════════════════════════════════════════════════════════════
# scan parse reuse (content-keyed A1 classes)
# ══════════════════════════════════════════════════════════════════════

class TestScanClassCache:
    def test_unchanged_file_is_not_reparsed(self, monkeypatch):
        ws = _make_ws({"a.sql": "SELECT 1;\n"})
        try:
            _index(ws)
            calls = []
            real_parse = fis.sqlglot.parse

            def counting(*args, **kwargs):
                calls.append(args)
                return real_parse(*args, **kwargs)

            monkeypatch.setattr(fis.sqlglot, "parse", counting)
            pc = {}
            tree = fis.scan_folder(ws, parsed_cache=pc,
                                   class_cache=fis.manifest_class_cache(ws))
            assert calls == []                      # content unchanged → no parse
            assert tree == fis.scan_folder(ws)      # tree identical to a parse walk
        finally:
            delete_workspace(ws)

    def test_changed_file_is_reparsed_and_reclassified(self, monkeypatch):
        ws = _make_ws({"a.sql": "SELECT 1;\n"})
        try:
            _index(ws)
            (get_workspace_dir(ws) / "scripts" / "a.sql").write_text(
                "CREATE TABLE x (c INT);\n")        # script → schema
            calls = []
            real_parse = fis.sqlglot.parse

            def counting(*args, **kwargs):
                calls.append(args)
                return real_parse(*args, **kwargs)

            monkeypatch.setattr(fis.sqlglot, "parse", counting)
            tree = fis.scan_folder(ws, class_cache=fis.manifest_class_cache(ws))
            assert len(calls) == 1                  # content changed → parsed
            node = next(n for n in tree["children"] if n["name"] == "a.sql")
            assert node["file_class"] == "schema"
        finally:
            delete_workspace(ws)

    def test_no_class_cache_parses_everything(self, monkeypatch):
        """POST /scan / create-path behavior is untouched without the cache."""
        ws = _make_ws({"a.sql": "SELECT 1;\n", "b.ddl": "CREATE TABLE y (d INT);\n"})
        try:
            calls = []
            real_parse = fis.sqlglot.parse

            def counting(*args, **kwargs):
                calls.append(args)
                return real_parse(*args, **kwargs)

            monkeypatch.setattr(fis.sqlglot, "parse", counting)
            fis.scan_folder(ws)
            assert len(calls) == 1                  # only a.sql (.ddl short-circuits)
        finally:
            delete_workspace(ws)


# ══════════════════════════════════════════════════════════════════════
# change hint (content hash)
# ══════════════════════════════════════════════════════════════════════

class TestChangeHint:
    def test_null_before_first_index(self):
        ws = _make_ws(SQL)
        try:
            assert fis.get_index_freshness(ws) is None
        finally:
            delete_workspace(ws)

    def test_zero_diff_after_index(self):
        ws = _make_ws(SQL)
        try:
            _index(ws)
            hint = fis.get_index_freshness(ws)
            assert hint["changed_count"] == 0
            assert hint["changed_scripts"] == 0      # P2 alias
            assert hint["added_count"] == 0
            assert hint["removed_count"] == 0
            assert hint["schema_changed_count"] == 0
            assert hint["stale"] is False and hint["reason"] is None
            assert hint["total"] == 2               # pipeline scripts only
        finally:
            delete_workspace(ws)

    def test_counts_edit_add_delete(self):
        ws = _make_ws(SQL)
        try:
            _index(ws)
            ws_dir = get_workspace_dir(ws)
            (ws_dir / "scripts" / "q1.sql").write_text("SELECT f, g FROM a;\n")
            (ws_dir / "scripts" / "new.sql").write_text("SELECT 1 FROM a;\n")
            (ws_dir / "scripts" / "q2.sql").unlink()
            hint = fis.get_index_freshness(ws)
            assert hint["changed_count"] == 1        # the edited q1.sql
            assert hint["added_count"] == 1          # new.sql (class unknown yet)
            assert hint["removed_count"] == 1        # the deleted q2.sql
            assert hint["total"] == 2
            assert hint["stale"] is True
            assert hint["reason"] == "scripts_changed"
        finally:
            delete_workspace(ws)

    def test_ddl_only_change_is_reported_separately(self):
        """DDL churn is evidence-only (never in progress.total), but it still
        makes the index stale — lost DDL evidence changes S4b resolution."""
        ws = _make_ws(SQL)
        try:
            _index(ws)
            ws_dir = get_workspace_dir(ws)
            (ws_dir / "scripts" / "ddl_b.sql").write_text(
                "CREATE TABLE b (f INT, k INT, m INT);\n")
            hint = fis.get_index_freshness(ws)
            assert hint["changed_count"] == 0        # no pipeline script touched
            assert hint["schema_changed_count"] == 1
            assert hint["stale"] is True
            assert hint["reason"] == "scripts_changed"
        finally:
            delete_workspace(ws)

    def test_mtime_alone_never_fools_the_reuse(self, monkeypatch):
        """Reuse is content-keyed: a same-content file whose mtime moved is
        still replayed (0 extractions); an edited file is re-extracted even
        if a tool restored the old mtime."""
        ws = _make_ws({"q.sql": "SELECT f FROM a;\n",
                       "ddl.sql": "CREATE TABLE a (f INT);\n"})
        try:
            _index(ws)
            sp = get_workspace_dir(ws) / "scripts" / "q.sql"
            stat = sp.stat()
            os_touch(sp)                            # mtime moves, content does not
            counter = ExtractionCounter(monkeypatch)
            _index(ws)
            assert counter.calls == [], counter.calls
            sp.write_text("SELECT f FROM a; -- edited\n")
            _restore_mtime(sp, stat.st_atime_ns, stat.st_mtime_ns)
            counter2 = ExtractionCounter(monkeypatch)
            _index(ws)
            assert counter2.calls == ["q.sql"], counter2.calls
        finally:
            delete_workspace(ws)

    def test_served_over_http(self):
        ws = _make_ws(SQL)
        try:
            body = client.get(f"/api/workspace/{ws}/index").json()
            assert body["freshness"] is None        # never indexed
            assert body["catching_up"] is False
            _index(ws)
            body = client.get(f"/api/workspace/{ws}/index").json()
            assert body["freshness"]["total"] == 2
            assert body["freshness"]["stale"] is False
            resume = client.get(f"/api/workspace/{ws}/resume").json()
            assert resume["index_change"]["changed_count"] == 0
            status = client.get(f"/api/workspace/{ws}/status").json()
            assert status["index_change"]["total"] == 2
            assert status["catching_up"] is False
        finally:
            delete_workspace(ws)


def os_touch(path: Path) -> None:
    import os
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


def _restore_mtime(path: Path, atime_ns: int, mtime_ns: int) -> None:
    import os
    os.utime(path, ns=(atime_ns, mtime_ns))


# ══════════════════════════════════════════════════════════════════════
# filtered_index refresh + atomic writes
# ══════════════════════════════════════════════════════════════════════

def test_filtered_index_is_refreshed_on_reindex():
    """A filter scope derived from the PREVIOUS index must not survive a
    re-index: _load_index PREFERS filtered_index.json, so a kept scope would
    silently run every search inside stale boundaries."""
    ws = _make_ws(SQL)
    try:
        _index(ws)
        cache_dir = get_workspace_dir(ws) / "cache"
        (cache_dir / "filtered_index.json").write_text(
            json.dumps({"table_index": {}, "field_index": {}}))
        report = _index(ws)
        assert report["filtered_index_cleared"] is True
        assert not (cache_dir / "filtered_index.json").exists()
        # and a second index with no filter present reports nothing cleared
        report2 = _index(ws)
        assert report2["filtered_index_cleared"] is False
    finally:
        delete_workspace(ws)


def test_index_response_clears_catching_up_explicitly():
    """P2 item 1: the incremental's own response says catching_up: false —
    no absence-detection needed on the client."""
    ws = _make_ws(SQL)
    try:
        client.post(f"/api/workspace/{ws}/index", json={"scripts": []})
        r = client.post(f"/api/workspace/{ws}/index", json={"scripts": []})
        assert r.json()["catching_up"] is False
        assert fis.is_index_catching_up(ws) is False
    finally:
        delete_workspace(ws)


def test_index_response_carries_freshness_after_the_index():
    """P2 (cosmetic): POST /index carries the freshness object so a UI that
    just triggered a catch-up renders "Indexed Xm ago" immediately — computed
    AFTER this index wrote its manifest, so it reports the new indexed_at and
    a zero diff (the run this response describes is already durable)."""
    ws = _make_ws(SQL)
    try:
        r = client.post(f"/api/workspace/{ws}/index", json={"scripts": []})
        fr = r.json()["freshness"]
        assert fr == fis.get_index_freshness(ws), fr
        assert fr["stale"] is False and fr["changed_count"] == 0
        assert fr["total"] == 2
        manifest = json.loads(
            (get_workspace_dir(ws) / "cache" / fis.MANIFEST_NAME).read_text())
        assert fr["indexed_at"] == manifest["indexed_at"]
        # an edit re-indexed in the same request reports itself as current
        (get_workspace_dir(ws) / "scripts" / "q1.sql").write_text(
            "SELECT f, g FROM a;\n")
        fr2 = client.post(f"/api/workspace/{ws}/index",
                          json={"scripts": []}).json()["freshness"]
        assert fr2["stale"] is False
        assert fr2["changed_count"] == 0
        assert fr2["indexed_at"] != fr["indexed_at"]
    finally:
        delete_workspace(ws)


def test_all_index_writes_are_atomic(monkeypatch):
    """Item 3-i: a torn cache file is a live 500/silent-empty-index hazard —
    every write in the index path must be temp + os.replace."""
    ws = _make_ws(SQL)
    try:
        replaces = []
        real_replace = __import__("os").replace

        def counting_replace(src, dst):
            replaces.append(Path(dst).name)
            return real_replace(src, dst)

        monkeypatch.setattr("app.services.atomic_io.os.replace",
                            counting_replace)
        _index(ws)
        cache_dir = get_workspace_dir(ws) / "cache"
        written = {p.name for p in cache_dir.iterdir() if not p.name.startswith(".")}
        # every artifact + every analysis/schemas cache landed via os.replace
        for name in ("table_index.json", "field_index.json", "pair_index.json",
                     "index_report.json", "file_tree.json",
                     "orphan_fields.json", fis.MANIFEST_NAME):
            assert name in replaces, (name, sorted(replaces))
        for name in written:
            if name.startswith(("analysis_", "schemas_")):
                assert name in replaces, (name, sorted(replaces))
        assert not list(cache_dir.glob(".*.tmp")), "temp files leaked"
        # evidence too
        assert any(n.startswith("ixevidence_") for n in replaces), replaces
    finally:
        delete_workspace(ws)


def test_meta_write_survives_a_concurrent_state_version_bump(monkeypatch):
    """Item 4: the index's meta update must not clobber a concurrent layout
    save's state_version bump — it merges onto the stored meta via CAS."""
    ws = _make_ws(SQL)
    try:
        _index(ws)
        real_cas = fis.write_meta_cas
        calls = {"n": 0}

        def racy_cas(ws_id, meta, expected):
            calls["n"] += 1
            if calls["n"] == 1:
                # a concurrent layout save lands first, bumping state_version
                fresh = read_meta(ws_id)
                assert real_cas(ws_id, {**fresh, "layouts": {"l1": {"n1": [1, 2]}}},
                                expected)
                return False                      # our write is now stale
            return real_cas(ws_id, meta, expected)

        monkeypatch.setattr(fis, "write_meta_cas", racy_cas)
        _index(ws)
        meta = read_meta(ws)
        assert meta["layouts"] == {"l1": {"n1": [1, 2]}}   # the save survived
        assert meta["indexed"] is True                     # and so did ours
        assert meta["indexed_scripts"] == ["q1.sql", "q2.sql"]
    finally:
        delete_workspace(ws)


# ══════════════════════════════════════════════════════════════════════
# catching-up window
# ══════════════════════════════════════════════════════════════════════

class TestCatchingUp:
    def test_never_set_without_a_run(self):
        ws = _make_ws(SQL)
        try:
            _index(ws)                              # service-level: no marking
            assert fis.is_index_catching_up(ws) is False
            r = client.post(f"/api/workspace/{ws}/search",
                            json={"table": "a", "field": "f"})
            assert r.status_code == 200, r.text
        finally:
            delete_workspace(ws)

    def test_search_409s_during_a_run_then_recovers(self):
        """The open-time re-index (POST /index) blocks index-derived searches
        for its duration — a false no_matches is worse than a short wait."""
        ws = _make_ws(SQL)
        try:
            _index(ws)
            # an un-indexed change → the open path would now re-index
            (get_workspace_dir(ws) / "scripts" / "q5.sql").write_text(
                "SELECT g FROM a;\n")

            import threading
            started = threading.Event()
            release = threading.Event()
            real = fis.index_scripts

            def slow_index(*a, **kw):
                started.set()
                release.wait(timeout=10)
                return real(*a, **kw)

            import app.routers.workspace as wr
            monkey_index = slow_index
            original = wr.index_scripts
            wr.index_scripts = monkey_index
            try:
                import threading as th
                t = th.Thread(target=lambda: client.post(
                    f"/api/workspace/{ws}/index", json={"scripts": []}))
                t.start()
                assert started.wait(timeout=10)
                r = client.post(f"/api/workspace/{ws}/search",
                                json={"table": "a", "field": "f"})
                assert r.status_code == 409, r.text
                assert "retry" in r.json()["detail"].lower()
                st = client.get(f"/api/workspace/{ws}/status").json()
                assert st["catching_up"] is True
                assert client.get(f"/api/workspace/{ws}/index").json()[
                    "catching_up"] is True
                release.set()
                t.join(timeout=30)
            finally:
                wr.index_scripts = original

            assert fis.is_index_catching_up(ws) is False
            r = client.post(f"/api/workspace/{ws}/search",
                            json={"table": "a", "field": "g"})
            assert r.status_code == 200, r.text
            # the newly indexed script is now searchable
            assert "q5.sql" in json.loads(
                (get_workspace_dir(ws) / "cache" / "field_index.json")
                .read_text())["g"]["scripts"]
        finally:
            delete_workspace(ws)

    def test_zero_diff_open_never_marks(self):
        """POST /index over unchanged content still runs (and unblocks
        immediately after) — but a zero-diff open never calls it, so no
        block in the common case."""
        ws = _make_ws(SQL)
        try:
            _index(ws)
            assert fis.is_index_catching_up(ws) is False
            assert client.get(f"/api/workspace/{ws}/index").json()[
                "catching_up"] is False
        finally:
            delete_workspace(ws)

    def test_flag_holds_until_the_last_concurrent_run_ends(self):
        """X2 (review): the in-flight mark is a COUNT, not a set. Two
        concurrent runs for one workspace are reachable without malice — the
        fast-open auto-fires POST /index on a stale/never-indexed workspace,
        so two tabs of the same creator both fire — and the FIRST finisher
        must not lift the search 409 gate while the second is mid-flight."""
        ws = _make_ws(SQL)
        try:
            fis.begin_index_run(ws)
            fis.begin_index_run(ws)
            assert fis.is_index_catching_up(ws) is True
            fis.end_index_run(ws)
            assert fis.is_index_catching_up(ws) is True, \
                "the first finisher handed search back onto a half-written index"
            fis.end_index_run(ws)
            assert fis.is_index_catching_up(ws) is False
            # an unbalanced end (a run that never began, or a double finally)
            # never sticks the flag ON nor drives the count negative
            fis.end_index_run(ws)
            assert fis.is_index_catching_up(ws) is False
        finally:
            fis.end_index_run(ws)
            assert fis.is_index_catching_up(ws) is False


# ══════════════════════════════════════════════════════════════════════
# evidence snapshot shape
# ══════════════════════════════════════════════════════════════════════

def test_evidence_snapshot_is_pre_s4b_and_restores_the_analysis_cache():
    """The snapshot holds the PRISTINE analysis (pre-S4b) — the on-disk
    analysis cache is the S4b-mutated serving copy, so a replay must RESET
    it, not reuse it. After S4b attributes a var in the cache, the snapshot
    still carries it unattributed with its candidate record intact."""
    ws = _make_ws(SQL)
    try:
        _index(ws)
        cache_dir = get_workspace_dir(ws) / "cache"
        manifest = json.loads((cache_dir / fis.MANIFEST_NAME).read_text())
        q1 = manifest["scripts"]["q1.sql"]
        payload = json.loads(
            gzip.decompress(
                (cache_dir / fis._evidence_name(q1["cache_key"])).read_bytes()
            ).decode("utf-8"))
        assert payload["cache_key"] == q1["cache_key"]
        assert payload["file_class"] == "script"
        assert payload["sql_md5"] == q1["sql_md5"]
        assert payload["extractor_version"] == fis.EXTRACTOR_VERSION
        analysis = payload["analysis"]
        assert analysis["script_name"] == "q1.sql"
        assert isinstance(analysis["variables"], list)
        assert isinstance(analysis["resolution_stats"], dict)
        # the S4b inputs survive verbatim — this is what a mutated cache loses
        assert analysis["resolution_stats"].get("schema_candidates") \
            is not None or analysis["resolution_stats"].get("unresolved") == []
        # and a re-index restores the cache to exactly these bytes
        _index(ws)
        restored = json.loads(
            (cache_dir / f"analysis_{q1['cache_key']}.json").read_text())
        assert restored == analysis
    finally:
        delete_workspace(ws)


def test_manifest_records_every_covered_sql_file():
    ws = _make_ws(SQL)
    try:
        _index(ws)
        manifest = json.loads(
            (get_workspace_dir(ws) / "cache" / fis.MANIFEST_NAME).read_text())
        assert set(manifest["scripts"]) == set(SQL)
        assert manifest["schema_files"] == 2
        assert manifest["extractor_version"] == fis.EXTRACTOR_VERSION
        assert manifest["indexed_at"]
        for rec in manifest["scripts"].values():
            assert set(rec) == {"cache_key", "sql_md5", "file_class",
                                "size", "mtime_ns"}
    finally:
        delete_workspace(ws)


def test_report_gate_is_any_script_carrying_stats():
    """X2 (review): `stats_seen` is `ANY script carried resolution_stats`, so
    the LAST-indexed script's analysis must not decide the gate for the whole
    report. A mixed corpus — here modelled by stripping the key from the last
    script's evidence snapshot, exactly what a snapshot from an engine that
    predates resolution_stats replays — used to flip the report to the
    tables==[] fallback: the container-resolved output alias `z` was reported
    as an UNRESOLVED orphan and coverage lost its container bucket, order-
    dependently."""
    ws = _make_ws({**SQL, "zz.sql": "SELECT 1 AS z;\n"})
    try:
        _index(ws)
        cache_dir = get_workspace_dir(ws) / "cache"
        # sanity: z is container-resolved (no table), never an orphan, while
        # every script still carries stats
        base = _index(ws)
        assert base["orphan_field_count"] == 0, base["orphan_field_samples"]
        assert base["resolution_stats"]["container_resolved"] == 1

        # an older engine's snapshot: the LAST script's analysis has no
        # resolution_stats at all
        manifest = json.loads((cache_dir / fis.MANIFEST_NAME).read_text())
        key = manifest["scripts"]["zz.sql"]["cache_key"]
        path = cache_dir / fis._evidence_name(key)
        payload = json.loads(gzip.decompress(path.read_bytes()).decode("utf-8"))
        payload["analysis"].pop("resolution_stats")
        path.write_bytes(gzip.compress(json.dumps(payload).encode("utf-8"),
                                      fis._GZIP_LEVEL))

        report = _index(ws)
        assert report["errors"] == [], report["errors"]
        assert report["reused_scripts"] == 3
        # the extractor-driven report stands: z stays container-resolved and
        # the earlier scripts' counts are still aggregated
        assert report["orphan_field_count"] == 0, report["orphan_field_samples"]
        assert report["resolution_stats"]["container_resolved"] == 1
        assert report["resolution_stats"]["total_columns"] == 1
    finally:
        delete_workspace(ws)
