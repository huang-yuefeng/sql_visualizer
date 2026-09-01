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
  PYTHONHASHSEED=0,1,2,3,7.

  LANDED (team V8, 2026-09-02) — the xfail marker is GONE; this test is
  now a hard gate. Two halves landed together and neither is sufficient
  alone:

    1. ``build_dependency_graph`` sorts the emitted dependency list
       canonically (key: var_order[src], var_order[tgt], relationship,
       operation, sql_context, containment) — the list becomes a pure
       function of the SQL text.
    2. ``lineage.compute_field_flow`` stops taking "the first edge in
       list order" as a decision: every node's adjacency is walked in a
       canonical content order (``lineage._WALK_RANK`` — the expansion
       loop's own rule precedence first, then edge type, operation,
       neighbour id, direction) and the frontier is walked in
       registration order. This was the load-bearing half: the DML
       admit's side effects (the R29 ``_effect_cols`` recording and the
       ``_cont_cols`` continuation admission) fire only when the DML
       edge is the one that ADMITS its target, so the order of two edges
       into the same table changed WHICH edges the closure admitted —
       measured before the fix: sorting the list alone grew the four
       data_dt benchmark cases (sup↓ 14 → 18 served edges, bdm↓ 29 → 34,
       pl/dl 9 → 10; jaccard edges precision 1.0 → 0.7778).

  With both halves: the jaccard gate is 20/20 at 1.0000/1.0000, the four
  data_dt cases return to EXACTLY their pre-sort served sets, and the
  108-script L2 snapshot corpus shows ZERO semantic node-set / edge-set
  diffs — the byte diffs that remain are keeper re-picks (``fld_*`` /
  ``l2e_*`` ids are md5 of the raw var id, so a different representative
  occurrence rehashes an id without changing any served content) plus
  array reordering. So this test CAN be green together with
  test_l2_snapshot.py's baselines; the committed snapshot bytes still
  move (id rehash + order), which is what the ONE human-reviewed
  rebaseline (L2_SNAPSHOT_UPDATE=1) re-pins.
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


def _build(script_name, sql_text, mode, table="", field=""):
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
        if mode == "flow":
            # REVIEW F1 (2026-09-02): the FLOW-ONLY view is the one the
            # V8 walker fix actually serves through — the walker runs
            # only under `relevance_filter=True` (_apply_relevance_filter
            # returns the full graph untouched, and _attach_flow_roles
            # calls compute_field_flow only under the filter), so the
            # cross-seed gate must build THIS payload, not just the full
            # view.
            flow = _build_l2_graph(ws_id, script_name, sql_text, table,
                                   field, relevance_filter=True,
                                   direction="downstream")
            return ws_id, _serialize({{"flow": flow}})
        full = _build_l2_graph(ws_id, script_name, sql_text, "", "",
                               relevance_filter=False)
        return ws_id, _serialize({{"full": full}})
    finally:
        delete_workspace(ws_id)


cfg = json.load(sys.stdin)
ws_id, serialized = _build(cfg["name"], cfg["sql"], cfg.get("mode", "full"),
                           cfg.get("table", ""), cfg.get("field", ""))
sys.stdout.write(ws_id + "\n" + serialized)
"""


def _run_build(script_name: str, sql_text: str, mode: str, seed: str,
               table: str = "", field: str = "") -> str:
    """Run one build in a subprocess under an explicit hash seed."""
    program = _CHILD_PROGRAM.format(backend_dir=str(BACKEND_DIR))
    env = {**os.environ, "PYTHONHASHSEED": seed}
    proc = subprocess.run(
        [sys.executable, "-c", program],
        input=json.dumps({"name": script_name, "sql": sql_text, "mode": mode,
                          "table": table, "field": field}),
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


def test_l2_full_view_is_byte_identical_across_hash_seeds():
    for script_name, payloads in _outputs("full").items():
        for seed in SEEDS[1:]:
            assert payloads[seed] == payloads[SEEDS[0]], (
                f"{script_name}: L2 full view differs between "
                f"PYTHONHASHSEED={SEEDS[0]} and {seed} — the dependency "
                f"list order is seed-dependent and the L2 build inherits it")


# REVIEW F1 (2026-09-02): the walker — the code the V8 fix changed — runs
# only under the strict filter, so the cross-seed gate must build the
# FLOW-ONLY payload too, with a real (table, field) search per flagship.
FLOW_SEARCHES = {
    "BDM_ACC_LOAN_INFO_Digitallending.sql": ("bdm_acc_loan_info", "data_dt"),
    "BDM_ACC_LOAN_INFO_SUP_M.sql": ("bdm_acc_loan_info", "lending_ref"),
}


def test_l2_flow_view_is_byte_identical_across_hash_seeds():
    """The strict-filter (flow-only) payload — the closure the walker
    computes — byte-equals itself across PYTHONHASHSEED=0,1,2,3,7."""
    for script_name, (table, field) in FLOW_SEARCHES.items():
        sql_text = dict(_SCRIPTS)[script_name]
        payloads = {
            seed: _run_build(script_name, sql_text, "flow", seed,
                             table=table, field=field)
            for seed in SEEDS}
        for seed in SEEDS[1:]:
            assert payloads[seed] == payloads[SEEDS[0]], (
                f"{script_name} × {table}.{field}: L2 flow view differs "
                f"between PYTHONHASHSEED={SEEDS[0]} and {seed} — the "
                f"walker's admission decisions are order-sensitive")
