"""FSC-2 (v3.3.195) — snapshot integrity: the served L2 closure must be a
pure function of the SQL text.

THE HOLE
========
Before this module's subject existed, the closure a workspace served also
depended on WHICH cache survived: the physical model the strict
table.field walker consumes was built from the analysis dict when an
analysis cache was present (the ``alias_of`` extraction truth) but from
the cached GRAPH JSON when it was not — and the graph cache serializes
nodes without ``alias_of``, so that second form falls back to
``physical_model``'s label-keyed alias rule. Same SQL, two different
models:

    measured on samples/sql_sample_v1/BDM_ACC_LOAN_INFO_RFN.sql — 28 of 74
    ``alias_by_var_id`` pairs differ between the two input forms, e.g. var
    ``15b561ec4099c7c3`` → ``bdm_acc_loan_info`` (the analysis truth) vs
    ``ODS_IFAI_FCLETWK`` (the label-rule guess); SUP_M 4 of 14.

``tests/test_l2_snapshot.py`` builds through ``_build_l2_graph`` on
never-indexed workspaces, so its second (filtered) build always took the
graph-rebuilt branch: the committed baselines encoded the lossy variant,
pinned only by PYTHONHASHSEED.

THE FIX UNDER TEST
==================
Persistence, not a smarter fallback: the build that writes a graph cache
also writes the alias truth of the SAME analysis beside it
(``cache/model_{cache_key}.json`` — graph_service.MODEL_CACHE_PREFIX), and
a graph-cache hit that cannot rebuild the model from an analysis cache
re-derives the model from that artifact instead. Every test here proves a
direction of that claim:

  1. the FSC repro — the graph-rebuild path's ``alias_by_var_id`` becomes
     the analysis-cache model's (the divergence count goes to 0);
  2. byte-identity — the served response of the analysis-cache path and
     the persisted-model path are the same bytes, on RFN and three more
     scripts, and do not depend on the caches' creation history;
  3. cross-seed stability — PYTHONHASHSEED 0..3 produce identical alias
     assignments (the artifact is read back, never re-derived per seed);
  4. old-cache fallback — a graph cache without the artifact keeps
     today's pre-FSC-2 behavior (no hard break);
  5. the artifact survives ``purge_workspace_caches`` and a re-index (it
     is the fast-open win, and it cannot serve stale data).

The seeds below are the ones the committed L2 snapshots recorded, so the
"serve" probes here exercise exactly the closure the snapshot gate pins.
"""

import io
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.physical_model import build_physical_model
from app.extractor.variable_extractor_v2 import EXTRACTOR_VERSION
from app.main import purge_workspace_caches
from app.services.dataflow_service import get_level2_graph
from app.services.folder_index_service import index_scripts
from app.services.graph_service import (
    MODEL_CACHE_FORMAT_VERSION,
    MODEL_CACHE_PREFIX,
    extract_alias_of,
    graph_with_alias_of,
    load_model_cache,
    write_model_cache,
)
from app.services.l2_builder import _load_or_build_graph
from app.services.workspace_service import (
    create_workspace,
    delete_workspace,
    get_workspace_dir,
)
from app.services.cache_keys import GRAPH_CACHE_PREFIX

SAMPLES_DIR = BACKEND_DIR.parent / "samples"
SQL_SAMPLE_DIR = SAMPLES_DIR / "sql_sample_v1"

# RFN is the FSC sample; the other three widen the byte-identity proof to
# every other alias-bearing script of the canonical regression sample.
RFN = "BDM_ACC_LOAN_INFO_RFN.sql"
SUP_M = "BDM_ACC_LOAN_INFO_SUP_M.sql"
PL = "BDM_ACC_LOAN_INFO_PL.sql"
EAST5 = "EAST5_STZFXXB_M.sql"
BYTE_IDENTITY_SCRIPTS = (RFN, SUP_M, PL, EAST5)

# The seeds the committed L2 snapshots recorded (deterministic per script).
SNAPSHOT_SEEDS = {
    RFN: ("ods_gdc_split_fg_rating_temp", "cust_no"),
    SUP_M: ("rollover_loan_info", "lending_ref"),
    PL: ("bdm_acc_loan_info", "data_dt"),
    EAST5: ("east5_stzfxxb", "p_dt"),
}

# The var id FSC quoted when it measured the divergence (RFN).
FSC_EXAMPLE_VAR = "15b561ec4099c7c3"


def _sql_of(script_name: str) -> str:
    return (SQL_SAMPLE_DIR / script_name).read_text(encoding="utf-8")


def _make_workspace(files: dict) -> str:
    """Workspace through the real zip-upload path."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, sql in files.items():
            zf.writestr(name, sql)
    return create_workspace(buf.getvalue())


def _cache_dir(ws_id: str) -> Path:
    return get_workspace_dir(ws_id) / "cache"


def _cache_key(script_name: str, sql_text: str) -> str:
    """The cache contract both read paths use (l2_builder + dataflow_service).
    Identical to folder_index_service's write-side key for a top-level
    script, which is what makes an indexed workspace's analysis cache
    discoverable here."""
    import hashlib
    return hashlib.md5(
        (EXTRACTOR_VERSION + "|" + script_name + sql_text).encode()
    ).hexdigest()[:12]


def _model_cache_path(ws_id: str, script_name: str, sql_text: str) -> Path:
    return (_cache_dir(ws_id) / f"{MODEL_CACHE_PREFIX}"
            f"_{_cache_key(script_name, sql_text)}.json")


def _drop_analysis_caches(ws_id: str) -> int:
    """Force the graph-rebuild path: the analysis caches are the ONLY thing
    that distinguishes it from the analysis-cache path."""
    n = 0
    for p in _cache_dir(ws_id).glob("analysis_*.json"):
        p.unlink()
        n += 1
    return n


def _alias_pairs(model) -> dict:
    return dict(model.alias_by_var_id)


def _diverging_pairs(a: dict, b: dict) -> list:
    keys = set(a) | set(b)
    return [(k, a.get(k), b.get(k)) for k in sorted(keys)
            if a.get(k) != b.get(k)]


def _assert_same_response(a: str, b: str, label: str) -> None:
    """Byte-equality of two served responses — WITHOUT handing pytest a
    multi-megabyte string pair to diff.

    A bare ``assert huge_a == huge_b`` is fine while it holds; the moment it
    FAILS, pytest's assertion repr diffs the two operands character by
    character (_pytest.assertion.compare_text._diff_text). RFN's canonical
    level2 response is ~5 MB, and that diff does not finish — the suite
    looks HUNG (V5's flag; reproduced here: minutes of CPU inside the repr,
    no output, no traceback). So: compare with ``==`` (a plain C-level
    compare, no repr machinery) and, only on a mismatch, report bounded
    facts — lengths, first differing offset, digests, 160 chars of context.
    """
    if a == b:
        return
    first = next((i for i in range(min(len(a), len(b)))
                  if a[i] != b[i]), min(len(a), len(b)))
    pytest.fail(
        f"{label}: the two responses are not the same bytes — "
        f"len {len(a)} vs {len(b)}, first diff at char {first}, "
        f"sha {hashlib.sha256(a.encode()).hexdigest()[:12]} vs "
        f"{hashlib.sha256(b.encode()).hexdigest()[:12]}\n"
        f"  A …{a[max(0, first - 80):first + 80]!r}\n"
        f"  B …{b[max(0, first - 80):first + 80]!r}",
        pytrace=False)


def _serve(ws_id: str, script_name: str, seed) -> str:
    """The canonical bytes of the served level2 response (the filtered view
    — the one whose closure the physical model drives)."""
    res = get_level2_graph(ws_id, "test-view", script_name,
                           seed[0], seed[1], filter_relevant_nodes=True)
    assert "error" not in res, res.get("error")
    return json.dumps(res, sort_keys=True, default=str)


# ── State isolation (suite hygiene): every workspace this file creates is
# born in a PRIVATE root, never in the shared /tmp/workspaces volume. Two
# reasons: a failed test must not leak a workspace + a multi-MB graph cache
# into the volume other suites and the live service share, and this file
# must stay order-independent next to suites that reset workspace state
# (test_multiuser_workspace). Both services that hold the root read the
# module attribute at call time — audit_service holds its own by-value
# binding, so it is patched too.
@pytest.fixture(autouse=True)
def _private_workspace_root(monkeypatch, tmp_path):
    import app.services.audit_service as _audit
    import app.services.workspace_service as _ws
    root = tmp_path / "workspaces"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_ws, "WORKSPACE_ROOT", root)
    monkeypatch.setattr(_audit, "WORKSPACE_ROOT", root)
    yield


def _indexed_workspace(files: dict):
    """Workspace + a real index (the analysis caches the repro needs)."""
    ws_id = _make_workspace(files)
    report = index_scripts(ws_id, list(files))
    assert report.get("script_count") == len(files), report.get("errors")
    return ws_id


# A stuck child is a failure, not a hang: every subprocess is killed at this
# bound (chosen ~3x the measured cost of one RFN build on an idle box, so a
# loaded machine still passes and a real deadlock still fails fast).
_SUBPROCESS_TIMEOUT = 240


@pytest.fixture(scope="session")
def _seed_ws_root(tmp_path_factory):
    """Private workspace root for the cross-seed subprocesses (they cannot
    see the in-process monkeypatch, so the root travels in the payload)."""
    return tmp_path_factory.mktemp("fsc2_cross_seed")


# ══════════════════════════════════════════════════════════════════════
# 1. The FSC repro: the graph-rebuild path regains the analysis truth
# ══════════════════════════════════════════════════════════════════════

def test_fsc_repro_graph_rebuild_path_matches_analysis_truth():
    """The 40/40-style alias divergence goes to 0.

    Index (analysis cache exists) → capture the analysis-path model →
    serve once (writes the graph cache + its alias-truth companion) →
    delete the analysis caches to force the graph-rebuild path → the model
    the loader returns must assign every alias EXACTLY as the analysis
    path did.
    """
    sql = _sql_of(RFN)
    ws_id = _indexed_workspace({RFN: sql})
    try:
        # ── the analysis-cache path: the extraction truth ──
        _, _, truth_model = _load_or_build_graph(ws_id, RFN, sql)
        truth = _alias_pairs(truth_model)
        assert truth, "RFN carries no aliases — the FSC sample is gone"
        assert FSC_EXAMPLE_VAR in truth, (
            "the var id FSC quoted is no longer an alias of RFN — revisit "
            "this test's sample premise")

        # ── the persisted-model path ──
        artifact = _model_cache_path(ws_id, RFN, sql)
        assert _drop_analysis_caches(ws_id) == 1
        _, _, persisted_model = _load_or_build_graph(ws_id, RFN, sql)
        assert artifact.exists(), (
            "the graph cache's alias-truth companion was not written")
        diffs = _diverging_pairs(truth, _alias_pairs(persisted_model))
        assert diffs == [], (
            f"{len(diffs)} alias assignments still depend on which cache "
            f"survived (FSC-2 unresolved): {diffs[:3]}")
        assert _alias_pairs(persisted_model) == truth
        # FSC's example resolves to the analysis truth, not the label guess
        assert persisted_model.alias_by_var_id[FSC_EXAMPLE_VAR] == \
            truth[FSC_EXAMPLE_VAR]
    finally:
        delete_workspace(ws_id)


def test_persisted_model_is_byte_identical_to_the_analysis_model():
    """Not just the alias map — the WHOLE physical model the walker consumes.

    The artifact carries the minimal truth (alias_of per var id); this
    proves that minimal truth is SUFFICIENT: every table, field, edge,
    occurrence and role the analysis-path model derives is re-derived
    identically from graph data + the artifact.
    """
    sql = _sql_of(RFN)
    ws_id = _indexed_workspace({RFN: sql})
    try:
        _, _, truth = _load_or_build_graph(ws_id, RFN, sql)
        assert _drop_analysis_caches(ws_id) == 1
        _, _, persisted = _load_or_build_graph(ws_id, RFN, sql)
        # Bounded compares only: these structures hold thousands of entries
        # (RFN: 93 tables, 887 fields, 10714 edges, 203 occurrences), so a
        # bare `assert a == b` on them would hand pytest a giant repr to
        # diff on failure — the same hang this file once had.
        def _same(what, a, b):
            if a == b:
                return
            extra = _diverging_pairs(a, b) if isinstance(a, dict) else []
            pytest.fail(f"{what}: the persisted-truth model differs from the "
                        f"analysis model ({len(extra)} entries): "
                        f"{extra[:4]}", pytrace=False)

        _same("alias_by_var_id", truth.alias_by_var_id,
              persisted.alias_by_var_id)
        _same("entity_of_id", truth.entity_of_id, persisted.entity_of_id)
        _same("table names", {k: t.name for k, t in truth.tables.items()},
              {k: t.name for k, t in persisted.tables.items()})
        _same("table roles", {k: t.roles for k, t in truth.tables.items()},
              {k: t.roles for k, t in persisted.tables.items()})
        _same("alias views", {k: t.alias_views for k, t in truth.tables.items()},
              {k: t.alias_views for k, t in persisted.tables.items()})
        _same("field occurrences",
              {k: f.occurrence_ids for k, f in truth.fields.items()},
              {k: f.occurrence_ids for k, f in persisted.fields.items()})
        assert len(truth.edges) == len(persisted.edges)
        _same("edges",
              [(e.edge_type, e.source, e.target, e.highlight_line)
               for e in truth.edges],
              [(e.edge_type, e.source, e.target, e.highlight_line)
               for e in persisted.edges])
        _same("occurrence index", truth.occurrences, persisted.occurrences)
    finally:
        delete_workspace(ws_id)


# ══════════════════════════════════════════════════════════════════════
# 2. Byte-identity of the SERVED response
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("script_name", BYTE_IDENTITY_SCRIPTS)
def test_served_response_identical_across_cache_paths(script_name):
    """The analysis-cache path and the persisted-model path serve the same
    bytes — RFN plus the three other alias-bearing sample scripts.

    Where the lossy variant was wrong (the alias assignments) the response
    now carries the analysis-cache truth; everything else is unchanged.
    """
    sql = _sql_of(script_name)
    seed = SNAPSHOT_SEEDS[script_name]
    ws_id = _indexed_workspace({script_name: sql})
    try:
        served_on_analysis_cache = _serve(ws_id, script_name, seed)
        assert _drop_analysis_caches(ws_id) >= 1
        served_on_persisted_model = _serve(ws_id, script_name, seed)
        _assert_same_response(
            served_on_analysis_cache, served_on_persisted_model,
            f"{script_name}: the served L2 response depends on which cache "
            "survived (FSC-2)")
    finally:
        delete_workspace(ws_id)


def test_served_response_independent_of_cache_creation_history():
    """Two independent workspaces, two cache histories, one answer.

    Workspace A: index → serve (analysis-cache path) → drop the analysis
    cache → serve (persisted-model path). Workspace B: never indexed at
    all — a cold build writes the graph cache, and the SECOND serve takes
    the graph-cache hit with no analysis cache ever having existed. All
    three responses must be the same bytes.
    """
    sql = _sql_of(RFN)
    seed = SNAPSHOT_SEEDS[RFN]
    ws_a = _indexed_workspace({RFN: sql})
    try:
        on_analysis = _serve(ws_a, RFN, seed)
        _drop_analysis_caches(ws_a)
        on_persisted = _serve(ws_a, RFN, seed)
        _assert_same_response(on_persisted, on_analysis,
                              "workspace A: analysis-cache vs persisted-model")

        ws_b = _make_workspace({RFN: sql})
        try:
            _serve(ws_b, RFN, seed)          # cold build → writes the caches
            on_cold_then_hit = _serve(ws_b, RFN, seed)
            _assert_same_response(
                on_cold_then_hit, on_analysis,
                "the served response depends on the caches' creation "
                "history — the closure is not a pure function of the SQL")
        finally:
            delete_workspace(ws_b)
    finally:
        delete_workspace(ws_a)


# The searches the lossy variant answered WRONG: their seed is reachable
# only through an alias's owning entity (the walker's #399 alias seed
# expansion, which consumes `alias_by_var_id`), so a mis-resolved alias
# left no seed at all — `search_matched: false` and the WHOLE graph as the
# answer. Measured on the pre-FSC-2 loader: RFN `a.cust_no` served the
# full 1053-node/6764-edge fallback instead of the 78-node/221-edge
# closure; SUP_M `p3.lending_ref` 219/679 instead of 9/13.
ALIAS_SEED_SEARCHES = (
    (RFN, ("a", "cust_no")),
    (RFN, ("A", "CUST_NO")),          # the case-insensitive spelling of it
    (SUP_M, ("p3", "lending_ref")),
)


@pytest.mark.parametrize(("script_name", "seed"), ALIAS_SEED_SEARCHES)
def test_alias_seed_searches_no_longer_lost_to_full_graph_fallback(script_name, seed):
    """A search that needs the alias truth gets the SAME answer whichever
    cache path serves it — and that answer is the analysis-path one (the
    seed matched), never the "not in flow, showing the full graph"
    fallback.
    """
    sql = _sql_of(script_name)
    ws_id = _indexed_workspace({script_name: sql})
    try:
        served_analysis = _serve(ws_id, script_name, seed)
        on_analysis = json.loads(served_analysis)
        assert on_analysis.get("search_matched") is not False, (
            f"{script_name} {seed[0]}.{seed[1]}: the analysis path itself no "
            "longer matches this alias seed — the search above is stale, "
            "pick another one that still exercises the alias expansion")
        _drop_analysis_caches(ws_id)
        served_persisted = _serve(ws_id, script_name, seed)
        on_persisted = json.loads(served_persisted)
        _assert_same_response(
            served_persisted, served_analysis,
            f"{script_name} {seed[0]}.{seed[1]}: the answer to this search "
            "depends on which cache survived (FSC-2)")
        assert on_persisted.get("search_matched") is not False, (
            "the persisted-model path lost the alias seed the analysis path "
            "matched — the fallback regressed to the full-graph answer")
        # The user-visible shape: a real closure, not the whole graph.
        assert len(on_persisted["graph"]["nodes"]) <= \
            on_analysis["total_nodes"], "closure larger than the graph"
    finally:
        delete_workspace(ws_id)


# ══════════════════════════════════════════════════════════════════════
# 3. Cross-seed stability
# ══════════════════════════════════════════════════════════════════════

_CROSS_SEED_PROGRAM = r"""
import io, json, sys, zipfile
from pathlib import Path
sys.path.insert(0, {backend_dir!r})

from app.services import workspace_service
from app.services.l2_builder import _load_or_build_graph
from app.services.workspace_service import (
    create_workspace, delete_workspace, get_workspace_dir,
)

cfg = json.load(sys.stdin)
# Private root: the child cannot see the parent's monkeypatch, so the root
# is handed in explicitly and installed before anything touches the disk.
# audit_service holds its own by-value binding — patched for the same reason.
import app.services.audit_service as _audit
workspace_service.WORKSPACE_ROOT = Path(cfg["ws_root"])
_audit.WORKSPACE_ROOT = Path(cfg["ws_root"])
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
    for name, sql in cfg["files"].items():
        zf.writestr(name, sql)
ws_id = create_workspace(buf.getvalue())
try:
    # (a) the model the BUILD path derives straight from the analysis (a
    # fresh workspace has no analysis cache, so the loader extracts and
    # builds the model from that analysis) — the alias truth must not move
    # with the hash seed;
    direct = _load_or_build_graph(ws_id, cfg["name"], cfg["sql"])[2]
    # (b) the model a graph-cache hit re-derives from the persisted
    # artifact (the analysis caches are gone, so the hit cannot rebuild
    # the model from them).
    for p in (get_workspace_dir(ws_id) / "cache").glob("analysis_*.json"):
        p.unlink()
    persisted = _load_or_build_graph(ws_id, cfg["name"], cfg["sql"])[2]
    print(json.dumps({{
        "direct": sorted(direct.alias_by_var_id.items()),
        "persisted": sorted(persisted.alias_by_var_id.items()),
    }}))
finally:
    delete_workspace(ws_id)
"""


def _cross_seed_run(hash_seed: str, script_name: str, ws_root: Path) -> dict:
    """One subprocess build under a pinned PYTHONHASHSEED.

    Hard-bounded: a stuck child is killed after ``_SUBPROCESS_TIMEOUT``
    seconds (a bound, never a hang) and the failure carries the child's own
    tail so the cause is diagnosable.
    """
    program = _CROSS_SEED_PROGRAM.format(backend_dir=str(BACKEND_DIR))
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}
    payload = json.dumps({"name": script_name,
                          "sql": _sql_of(script_name),
                          "files": {script_name: _sql_of(script_name)},
                          "ws_root": str(ws_root)})
    try:
        proc = subprocess.run([sys.executable, "-c", program], input=payload,
                              capture_output=True, text=True, env=env,
                              timeout=_SUBPROCESS_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        tail = (exc.stderr or "")[-800:] if isinstance(exc.stderr, str) else ""
        pytest.fail(
            f"the PYTHONHASHSEED={hash_seed} build did not finish within "
            f"{_SUBPROCESS_TIMEOUT}s — killed; child tail:\n{tail}",
            pytrace=False)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


def test_cross_seed_alias_stability(_seed_ws_root):
    """PYTHONHASHSEED 0..3 → identical alias assignments, both as derived
    from the analysis and as re-derived from the persisted artifact.

    The snapshot harness pins PYTHONHASHSEED=0 because the ANALYSIS
    dependency list is seed-dependent; the alias truth must not be — this
    is what lets the persisted artifact be written on one machine and
    consumed on another.

    Each run is a bounded subprocess in a private workspace root (both
    passed in explicitly — the child cannot see a monkeypatch), and the
    compared payloads are the small alias lists, never a served response.
    """
    runs = {}
    for seed in ("0", "1", "2", "3"):
        got = _cross_seed_run(seed, RFN, _seed_ws_root)
        # Within a seed: the analysis truth and the artifact-derived model
        # are the same assignments.
        if got["direct"] != got["persisted"]:
            diffs = _diverging_pairs(dict(got["direct"]),
                                     dict(got["persisted"]))
            pytest.fail(
                f"PYTHONHASHSEED={seed}: the persisted alias truth differs "
                f"from the analysis truth ({len(diffs)} pairs): "
                f"{diffs[:5]}", pytrace=False)
        runs[seed] = got
    first = runs["0"]
    assert first["direct"], "RFN carries no aliases — sample premise gone"
    for seed, got in runs.items():
        assert got["direct"] == first["direct"], (
            f"PYTHONHASHSEED={seed} derives different alias assignments")
        assert got["persisted"] == first["persisted"], (
            f"PYTHONHASHSEED={seed} re-derives different alias assignments")


# ══════════════════════════════════════════════════════════════════════
# 4. Old-cache fallback (no hard break)
# ══════════════════════════════════════════════════════════════════════

def test_graph_cache_without_model_artifact_keeps_today_rebuild():
    """A graph cache written BEFORE the artifact existed (no sibling file)
    falls back to today's graph-data rebuild — no exception, a usable
    model, and exactly the model ``build_physical_model(graph)`` makes.

    That fallback is the pre-FSC-2 behavior, kept so upgrading never
    breaks a workspace: its alias assignments may differ from the truth
    (that is the hole), but nothing crashes and the graph still serves.
    """
    sql = _sql_of(RFN)
    seed = SNAPSHOT_SEEDS[RFN]
    ws_id = _make_workspace({RFN: sql})
    try:
        # Cold build: writes graph cache + schemas + (new) model artifact.
        served_cold = _serve(ws_id, RFN, seed)
        cache_dir = _cache_dir(ws_id)
        graph_cache = next(cache_dir.glob(f"{GRAPH_CACHE_PREFIX}_*.json"))
        artifact = _model_cache_path(ws_id, RFN, sql)
        assert artifact.exists()
        # Roll the workspace back to a pre-FSC-2 shape: the graph cache
        # survives, its companion and the analysis caches are gone.
        artifact.unlink()
        _drop_analysis_caches(ws_id)

        # Loader: no hard break, and the model IS the graph-data rebuild.
        _, _, model = _load_or_build_graph(ws_id, RFN, sql)
        cached_graph = json.loads(graph_cache.read_text())
        legacy = build_physical_model(cached_graph, script_name=RFN)
        assert model.alias_by_var_id == legacy.alias_by_var_id
        assert model.entity_of_id == legacy.entity_of_id

        # Serving works, and repeated FALLBACK hits agree with each other.
        # (They are NOT expected to agree with `served_cold`: the fallback
        # is the documented lossy variant, so its closure may legitimately
        # differ from the truth-built one — that is the hole, not a bug.)
        served_fallback_1 = _serve(ws_id, RFN, seed)
        served_fallback_2 = _serve(ws_id, RFN, seed)
        _assert_same_response(served_fallback_1, served_fallback_2,
                              "two identical fallback hits drifted")

        # A version-gated artifact (other contract version) is ignored the
        # same way — the fallback, never a guess from foreign data.
        write_model_cache(artifact, _cache_key(RFN, sql), "0.0.0-wrong", {})
        assert load_model_cache(artifact, _cache_key(RFN, sql),
                                EXTRACTOR_VERSION) == {}
        _, _, model2 = _load_or_build_graph(ws_id, RFN, sql)
        assert model2.alias_by_var_id == legacy.alias_by_var_id
        _assert_same_response(_serve(ws_id, RFN, seed), served_fallback_1,
                              "a version-gated artifact changed the answer")
    finally:
        delete_workspace(ws_id)


def test_old_cache_fallback_is_the_documented_loss():
    """Sensitivity premise of this module: on the FSC sample the fallback
    (graph data, no artifact) still MIS-ASSIGNS aliases — which is exactly
    why the artifact had to be persisted rather than the label rule
    repaired.

    If this assert ever stops holding, the two input forms have converged
    (an extractor change), the FSC finding is void on the current sample,
    and test 1/2 above lose their discriminating power — revisit them with
    a sample that still diverges.
    """
    sql = _sql_of(RFN)
    ws_id = _indexed_workspace({RFN: sql})
    try:
        _, _, truth = _load_or_build_graph(ws_id, RFN, sql)
        artifact = _model_cache_path(ws_id, RFN, sql)
        assert _drop_analysis_caches(ws_id) == 1
        artifact.unlink()                      # the pre-FSC-2 shape
        _, _, lossy = _load_or_build_graph(ws_id, RFN, sql)
        diffs = _diverging_pairs(_alias_pairs(truth), _alias_pairs(lossy))
        assert diffs, (
            "the label-keyed fallback now agrees with the analysis truth "
            "on RFN — this module's sensitivity premise changed")
        assert FSC_EXAMPLE_VAR in {k for k, _, _ in diffs}
    finally:
        delete_workspace(ws_id)


# ══════════════════════════════════════════════════════════════════════
# 5. The artifact's lifecycle: purge, re-index, and its own guards
# ══════════════════════════════════════════════════════════════════════

def test_purge_workspace_caches_keeps_the_model_artifact(tmp_path):
    """``purge_workspace_caches`` removes graph/analysis/schemas caches and
    NEVER the alias-truth companion (FSC-2 contract, stated in its
    docstring): deleting it would push any surviving graph cache back onto
    the label-keyed guess, and it cannot serve stale data anyway (its
    reader version-gates it).
    """
    ws = tmp_path / "ws1"
    cache = ws / "cache"
    cache.mkdir(parents=True)
    kept = cache / f"{MODEL_CACHE_PREFIX}_abc123.json"
    kept.write_text("{}")
    removed_kinds = {
        "graph_abc123.json": f"{GRAPH_CACHE_PREFIX}abc123.json",
        "analysis_abc123.json": "analysis_abc123.json",
        "schemas_abc123.json": "schemas_abc123.json",
    }
    for name in removed_kinds.values():
        (cache / name).write_text("{}")
    untouched = {"views.json": cache / "views.json",
                 "model_artifact": kept,
                 "index_manifest": cache / "index_manifest.json",
                 "evidence": cache / "ixevidence_abc123.json.gz"}
    for f in untouched.values():
        f.write_text("{}")

    removed = purge_workspace_caches(root=tmp_path)

    assert removed == len(removed_kinds), removed
    for name in removed_kinds.values():
        assert not (cache / name).exists()
    for label, f in untouched.items():
        assert f.exists(), f"purge deleted {label} — it must not"


def test_reindex_keeps_the_model_artifact_and_rewrites_it_on_next_l2():
    """P1 interplay: an incremental re-index invalidates the graph caches
    but leaves the model artifact alone (it is not evidence, not manifest,
    not an analysis cache) — and the next L2 rewrites it from the same
    analysis, so the artifact can never describe a foreign graph."""
    sql = _sql_of(RFN)
    seed = SNAPSHOT_SEEDS[RFN]
    ws_id = _indexed_workspace({RFN: sql})
    try:
        _serve(ws_id, RFN, seed)               # writes graph cache + artifact
        artifact = _model_cache_path(ws_id, RFN, sql)
        before = artifact.read_bytes()
        assert artifact.exists()

        report = index_scripts(ws_id, [RFN])   # incremental re-index
        assert report.get("script_count") == 1, report.get("errors")
        assert artifact.exists(), (
            "the re-index deleted the alias-truth companion — the fast-open "
            "win and the FSC-2 guarantee die with it")
        assert artifact.read_bytes() == before

        for p in _cache_dir(ws_id).glob(f"{GRAPH_CACHE_PREFIX}_*.json"):
            p.unlink()                         # the re-index's own invalidation
        _serve(ws_id, RFN, seed)
        assert artifact.exists()
        assert artifact.read_bytes() == before, (
            "the rebuilt graph cache is paired with a DIFFERENT alias truth")
    finally:
        delete_workspace(ws_id)


def test_model_cache_roundtrip_and_version_gates(tmp_path):
    """The artifact cannot serve stale data — the property the purge
    contract leans on. Every guard failure reads as an absent file."""
    path = tmp_path / "model_x.json"
    analysis = {"variables": [{"id": "a", "alias_of": "t"},
                              {"id": "b"}, {"id": "c", "alias_of": ""}]}
    assert extract_alias_of(analysis) == {"a": "t"}

    assert write_model_cache(path, "key1", EXTRACTOR_VERSION, analysis) == 1
    assert load_model_cache(path, "key1", EXTRACTOR_VERSION) == {"a": "t"}
    # … any other cache key / extractor / contract version / shape → {}
    assert load_model_cache(path, "other", EXTRACTOR_VERSION) == {}
    assert load_model_cache(path, "key1", "other-version") == {}
    assert load_model_cache(path, "key1", EXTRACTOR_VERSION) == {"a": "t"}
    stale = json.loads(path.read_text())
    stale["format_version"] = MODEL_CACHE_FORMAT_VERSION + 1
    path.write_text(json.dumps(stale))
    assert load_model_cache(path, "key1", EXTRACTOR_VERSION) == {}
    stale["format_version"] = MODEL_CACHE_FORMAT_VERSION
    stale["alias_of"] = {"a": 7}               # wrong payload shape
    path.write_text(json.dumps(stale))
    assert load_model_cache(path, "key1", EXTRACTOR_VERSION) == {}
    path.write_text("{not json")
    assert load_model_cache(path, "key1", EXTRACTOR_VERSION) == {}
    assert load_model_cache(tmp_path / "missing.json", "key1",
                            EXTRACTOR_VERSION) == {}
    # An alias-free script still writes its (empty) companion: presence is
    # what says "this graph cache carries its truth".
    empty = tmp_path / "model_empty.json"
    assert write_model_cache(empty, "k", EXTRACTOR_VERSION,
                             {"variables": [{"id": "x"}]}) == 0
    assert empty.exists()
    assert load_model_cache(empty, "k", EXTRACTOR_VERSION) == {}


def test_graph_with_alias_of_never_mutates_the_served_graph():
    """The enriched graph is a COPY: the cached graph object is also the
    served payload, so the persisted fact must stay a model-build input and
    must never leak ``alias_of`` into a response."""
    graph = {
        "script_name": "s.sql",
        "nodes": [{"data": {"id": "a", "label": "A", "variable_type": "table"}},
                  {"data": {"id": "t", "label": "T", "variable_type": "table"}},
                  {"data": {"id": "n", "label": "N", "variable_type": "column"}}],
        "edges": [{"data": {"source": "t", "target": "a"}}],
    }
    import copy
    snapshot = copy.deepcopy(graph)

    enriched = graph_with_alias_of(graph, {"a": "t"})
    assert graph == snapshot, "the input graph was mutated"

    enriched_nodes = {n["data"]["id"]: n["data"] for n in enriched["nodes"]}
    assert enriched_nodes["a"]["alias_of"] == "t"
    # Ids absent from the truth keep their dicts untouched (the same object
    # the graph cache holds — nothing is invented for them).
    assert "alias_of" not in enriched_nodes["n"]
    assert "alias_of" not in enriched_nodes["t"]
    assert enriched_nodes["n"] is graph["nodes"][2]["data"]
    assert enriched["edges"] == graph["edges"]
    assert enriched["script_name"] == "s.sql"
    # And the model built from it resolves the alias (the artifact's job).
    model = build_physical_model(enriched, script_name="s.sql")
    assert model.alias_by_var_id.get("a") == model.entity_of_id.get("t")
    # No truth → the graph comes back as-is (same object, nothing copied).
    assert graph_with_alias_of(graph, {}) is graph
