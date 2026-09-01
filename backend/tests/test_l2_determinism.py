"""Hash-seed independence of the served L2 output (Team DET).

The finding (documented in test_l2_snapshot.py's module docstring): the
ANALYSIS dependency list that ``build_dependency_graph`` emits is in
PYTHONHASHSEED-dependent order — same edge SET, different ORDER — because
Phase 3 walks each target's ``source_columns``, which the extractor
materializes through ``list(set(...))``
(variable_extractor_v2._extract_source_columns). The order is
load-bearing downstream (l2_builder's first-wins dedup and the closure
walks take the FIRST candidate), so the L2 FULL view inherits the
instability and a server process (random seed) can serve differently
ordered — and differently CHOSEN — graphs across restarts.

The snapshot harness papers over this by building each L2 in a
subprocess with PYTHONHASHSEED=0. That proves the output is stable at
seed 0 only. This module measures the underlying property directly.

Two tests, both building in subprocesses (the snapshot harness's
pattern — PYTHONHASHSEED must be fixed before interpreter start):

* ``test_dependency_set_is_seed_independent`` — the emitted dependency
  list is a SET function of the SQL text across seeds. TRUE today; this
  is the soundness precondition for the fix direction the docstring
  names (a canonical sort of the dependency list can then only reorder,
  never change content). A failure here means extraction itself leaks
  hash order into edge CONTENT, and a sort would be unsound.

* ``test_l2_full_view_is_byte_identical_across_hash_seeds`` — the
  acceptance test: the served L2 full view byte-equals itself across
  PYTHONHASHSEED=0,1,2,3,7. XFAIL today (measured: 5 distinct byte
  outputs for BDM_ACC_LOAN_INFO_Digitallending across those seeds).

  Landing the canonical order turns this green — and it CANNOT be green
  together with test_l2_snapshot.py: the committed snapshots are the
  SEED-0 bytes, the seed-0 order is itself an artifact of hash order,
  and every dependency reorder measurably changes the served payload
  (edge array order everywhere, plus the first-wins representative and
  the ``reason`` hop chain on the order-sensitive edges). So this test
  flipping to XPASS is the signal to run the ONE human-reviewed
  snapshot rebaseline (L2_SNAPSHOT_UPDATE=1) in the same change — never
  before, never separately.
"""

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

SAMPLES_DIR = BACKEND_DIR.parent / "samples"

# Seeds scanned. 0 is the snapshot harness's pin; the rest are arbitrary
# (a server process gets a random one at every start).
SEEDS = ("0", "1", "2", "3", "7")

# Small sample set on purpose: the flagship scripts are the ones the
# instability was measured on (Digitallending and SUP_M both flip
# first-wins picks across seeds), and 01.sql is the stable control (its
# source-column sets are singletons, so it never varied).
SAMPLE_SCRIPTS = (
    "sql_sample_v1/BDM_ACC_LOAN_INFO_Digitallending.sql",
    "sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql",
    "tpcds_qualified/01.sql",
)


def _load_scripts():
    scripts = []
    for rel in SAMPLE_SCRIPTS:
        path = SAMPLES_DIR / rel
        if not path.exists():
            pytest.skip(f"sample not present: {rel}")
        scripts.append((path.name, path.read_text(encoding="utf-8")))
    return scripts


_SCRIPTS = _load_scripts()


# ── Child process program (test_l2_snapshot.py's pattern) ─────────────
# Reads {"name", "sql", "mode"} from stdin, prints
# "<ws_id>\n<canonical payload JSON>" to stdout; logs go to stderr.
_CHILD_PROGRAM = r"""
import io, json, sys, zipfile
sys.path.insert(0, {backend_dir!r})

from app.extractor.adapter import run_full_analysis
from app.services.l2_builder import _build_l2_graph
from app.services.workspace_service import create_workspace, delete_workspace


def _serialize(payload):
    return json.dumps(payload, sort_keys=True, default=str, indent=2) + "\n"


def _make_workspace(script_name, sql_text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(script_name, sql_text)
    return create_workspace(buf.getvalue())


def _build(script_name, sql_text, mode):
    ws_id = _make_workspace(script_name, sql_text)
    try:
        if mode == "deps":
            result = run_full_analysis(sql_text, script_name, ws_id=ws_id)
            return ws_id, _serialize({{
                "dependencies": [
                    [d["source_id"], d["target_id"], d["relationship"],
                     d["operation"], d["sql_context"], d["containment"]]
                    for d in result["dependencies"]],
            }})
        full = _build_l2_graph(ws_id, script_name, sql_text, "", "",
                               relevance_filter=False)
        return ws_id, _serialize({{"full": full}})
    finally:
        delete_workspace(ws_id)


cfg = json.load(sys.stdin)
ws_id, serialized = _build(cfg["name"], cfg["sql"], cfg.get("mode", "full"))
sys.stdout.write(ws_id + "\n" + serialized)
"""


def _run_build(script_name: str, sql_text: str, mode: str, seed: str) -> str:
    """Run one build in a subprocess under an explicit hash seed."""
    program = _CHILD_PROGRAM.format(backend_dir=str(BACKEND_DIR))
    env = {**os.environ, "PYTHONHASHSEED": seed}
    proc = subprocess.run(
        [sys.executable, "-c", program],
        input=json.dumps({"name": script_name, "sql": sql_text, "mode": mode}),
        capture_output=True, text=True, env=env, timeout=300)
    if proc.returncode != 0:
        raise AssertionError(
            f"build subprocess failed for {script_name} "
            f"(mode={mode}, PYTHONHASHSEED={seed}):\n{proc.stderr[-2000:]}")
    ws_id, _, serialized = proc.stdout.partition("\n")
    assert ws_id and serialized, (
        f"build subprocess produced no output for {script_name}")
    return serialized


def _outputs(mode):
    """{script_name: {seed: serialized_payload}} for every seed."""
    out = {}
    for script_name, sql_text in _SCRIPTS:
        out[script_name] = {
            seed: _run_build(script_name, sql_text, mode, seed) for seed in SEEDS}
    return out


def test_dependency_set_is_seed_independent():
    """The emitted dependency list is a SET function of the SQL text.

    Holds TODAY (measured: 5 distinct orders, one set, on the two
    flagship scripts). This is what makes the docstring's fix direction
    — a canonical sort of the dependency list on stable content keys —
    a pure reordering. A failure here means hash order reached the edge
    CONTENT, and sorting would be unsound.
    """
    for script_name, payloads in _outputs("deps").items():
        reference = json.loads(payloads[SEEDS[0]])["dependencies"]
        canon = sorted(map(tuple, reference))
        for seed in SEEDS[1:]:
            other = json.loads(payloads[seed])["dependencies"]
            assert sorted(map(tuple, other)) == canon, (
                f"{script_name}: dependency CONTENT differs under "
                f"PYTHONHASHSEED={seed} — extraction leaks hash order "
                f"into the edge set, a canonical sort would be unsound")


@pytest.mark.xfail(
    reason="the dependency list order is PYTHONHASHSEED-dependent and the "
           "L2 full view inherits it. LANDS AFTER THE WALKER IS MADE "
           "ORDER-INSENSITIVE (measured 2026-09-01, post-3a-ruling): with "
           "the canonical sort at the end of build_dependency_graph "
           "(key: var_order[src], var_order[tgt], relationship, operation, "
           "sql_context, containment) the four data_dt benchmark cases "
           "gain EXTRA edges (sup E 1.0->0.7778, bdm/SUP_M ->0.8529, "
           "pl/dl ->0.9) — the walker's admission decisions themselves "
           "are order-sensitive, so sorting the list changes WHICH edges "
           "the closure admits, not just their order. Fix = content-key "
           "every order-sensitive pick/admission in compute_field_flow "
           "(the V8 walker-determinism program), then: sort + "
           "EXTRACTOR_VERSION bump + one snapshot regen + drop this "
           "marker. Earlier false pass came from stale .12 caches serving "
           "unsorted graphs — always invalidate/bump before measuring.",
    strict=False)
def test_l2_full_view_is_byte_identical_across_hash_seeds():
    """The served L2 full view byte-equals itself across hash seeds.

    Pairwise over every seed pair — a server process can serve any of
    them across restarts, so first-wins instability between ANY two is
    the defect. This is the acceptance test for the canonical-order fix.
    """
    for script_name, payloads in _outputs("full").items():
        for seed in SEEDS[1:]:
            assert payloads[seed] == payloads[SEEDS[0]], (
                f"{script_name}: L2 full view differs between "
                f"PYTHONHASHSEED={SEEDS[0]} and {seed} — the dependency "
                f"list order is seed-dependent and the L2 build inherits it")
