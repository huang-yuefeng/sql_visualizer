"""Byte-identity snapshot harness for L2 output (J12-10 Wave A).

The staged physical-model refactor (wiki/SOLUTION_DESIGN.md §J12-10, stages
1-4) must keep L2 output byte-identical through the node-construction
stages. This harness pins the CURRENT L2 output as committed snapshots:
every run rebuilds each script's L2 graph — relevance-filtered with a
deterministic representative seed, plus the full view — and asserts the
canonically serialized response byte-equals the committed snapshot file.
Stages 2-4 run this same file as the gate that proves "ids/labels
byte-identical" (per-node ids are content-derived hashes, so any change
to node/edge construction shows up as a diff here).

Hash-seed pinning: the pipeline's ANALYSIS dependency list is emitted in
PYTHONHASHSEED-dependent order (same edge set, different order — the L2
full view inherits the instability via first-wins dedup and closure-walk
choices). To make the snapshot byte-stable across runs and machines, each
build runs in a SUBPROCESS with PYTHONHASHSEED=0 — the canonical output
bytes are then fully deterministic. This is a harness-level pin, NOT a
product change; the underlying instability is tracked as a separate
finding (fix direction: canonical sort of the dependency list).

Rebaseline ONLY on intentional output changes:
  L2_SNAPSHOT_UPDATE=1 python3 -m pytest tests/test_l2_snapshot.py -q
"""

import io
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

SAMPLES_DIR = BACKEND_DIR.parent / "samples"
SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"

# Runtime cap (~12 scripts × a few seconds each): sql_sample_v1 first (the
# canonical regression sample), then tpcds_qualified.
MAX_SCRIPTS = 12
# Seed scan cap: candidates are walked in deterministic order (L2 table
# index, then each table's fields in classification order); the first
# candidate whose strict filter matches wins, otherwise the first
# candidate is used (the deterministic negative outcome is snapshotted).
MAX_SEED_ATTEMPTS = 200

# L2 compound node types that represent tables (parents of field nodes).
TABLE_NODE_TYPES = ("source_table", "intermediate_table", "output_table",
                    "alias_table", "cte_table")

# Fixed hash seed: the canonical byte output (see module docstring).
FIXED_HASH_SEED = "0"

UPDATE_SNAPSHOTS = os.environ.get("L2_SNAPSHOT_UPDATE") == "1"


def _collect_scripts() -> list:
    """Deterministic script list for the harness.

    sql_sample_v1/*.sql (the canonical regression sample) then
    tpcds_qualified/*.sql when present, sorted by name, capped at
    MAX_SCRIPTS total for runtime.
    """
    scripts = []
    for d in (SAMPLES_DIR / "sql_sample_v1", SAMPLES_DIR / "tpcds_qualified"):
        if not d.exists():
            continue
        for p in sorted(d.glob("*.sql")):
            scripts.append((p.name, p.read_text()))
    if not scripts:
        raise FileNotFoundError(f"no sample scripts under {SAMPLES_DIR}")
    return scripts[:MAX_SCRIPTS]


_SCRIPTS = _collect_scripts()

# ── Child process program ──────────────────────────────────────────────
# Each build runs here with PYTHONHASHSEED=FIXED_HASH_SEED so the output
# bytes are canonical. Reads {"name", "sql", "mode"} from stdin, prints
# "<ws_id>\n<canonical payload JSON>" to stdout (logs go to stderr).
_BUILD_PROGRAM = r"""
import io, json, sys, zipfile
sys.path.insert(0, {backend_dir!r})

from app.services.l2_builder import _build_l2_graph
from app.services.workspace_service import create_workspace, delete_workspace

TABLE_NODE_TYPES = ("source_table", "intermediate_table", "output_table",
                    "alias_table", "cte_table")
MAX_SEED_ATTEMPTS = {max_seed_attempts}


def _make_workspace(script_name, sql_text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(script_name, sql_text)
    return create_workspace(buf.getvalue())


def _serialize(payload):
    return json.dumps(payload, sort_keys=True, default=str, indent=2) + "\n"


def _pick_seed(ws_id, script_name, sql_text, full_result):
    # First table.field in the L2 table index whose strict filter
    # matches (search_matched True, non-empty closure) — deterministic;
    # falls back to the first candidate when nothing matches.
    field_by_parent = {{}}
    for n in full_result["nodes"]:
        nd = n["data"]
        if nd.get("type") == "field" and nd.get("parent"):
            field_by_parent.setdefault(nd["parent"], []).append(nd)
    candidates = []
    for n in full_result["nodes"]:
        nd = n["data"]
        if nd.get("type") not in TABLE_NODE_TYPES:
            continue
        fields = field_by_parent.get(nd.get("id", ""))
        if not fields:
            continue
        tbl = nd.get("table_name") or nd.get("label", "")
        clean = [f["label"] for f in fields
                 if "." not in f.get("label", "")
                 and not f.get("label", "").endswith(" ·")]
        dotted = [f["label"] for f in fields
                  if "." in f.get("label", "")
                  or f.get("label", "").endswith(" ·")]
        for lab in clean + dotted:
            candidates.append((tbl, lab))
    for tbl, lab in candidates[:MAX_SEED_ATTEMPTS]:
        res = _build_l2_graph(ws_id, script_name, sql_text, tbl, lab,
                              relevance_filter=True)
        if res.get("search_matched") and res["nodes"]:
            return tbl, lab
    if candidates:
        return candidates[0]
    return "", ""


def _build(script_name, sql_text, mode):
    ws_id = _make_workspace(script_name, sql_text)
    try:
        full = _build_l2_graph(ws_id, script_name, sql_text, "", "",
                               relevance_filter=False)
        if mode == "full":
            return ws_id, _serialize({{"full": full}})
        table, field = _pick_seed(ws_id, script_name, sql_text, full)
        filtered = _build_l2_graph(ws_id, script_name, sql_text, table,
                                   field, relevance_filter=True)
        payload = {{
            "script_name": script_name,
            "seed": {{"table": table, "field": field}},
            "filtered": filtered,  # relevance_filter=True with the seed
            "full": full,          # relevance_filter=False (full view)
        }}
        return ws_id, _serialize(payload)
    finally:
        delete_workspace(ws_id)


cfg = json.load(sys.stdin)
ws_id, serialized = _build(cfg["name"], cfg["sql"], cfg.get("mode", "pair"))
sys.stdout.write(ws_id + "\n" + serialized)
"""


def _run_build(script_name: str, sql_text: str, mode: str = "pair") -> tuple:
    """Run the L2 build in a subprocess under the fixed hash seed.

    Returns (ws_id, serialized) — ws_id is returned so tests can assert
    it never leaks into the output.
    """
    program = _BUILD_PROGRAM.format(
        backend_dir=str(BACKEND_DIR), max_seed_attempts=MAX_SEED_ATTEMPTS)
    env = {**os.environ, "PYTHONHASHSEED": FIXED_HASH_SEED}
    proc = subprocess.run(
        [sys.executable, "-c", program],
        input=json.dumps({"name": script_name, "sql": sql_text, "mode": mode}),
        capture_output=True, text=True, env=env, timeout=180)
    if proc.returncode != 0:
        raise AssertionError(
            f"L2 build subprocess failed for {script_name}:\n"
            f"{proc.stderr[-2000:]}")
    ws_id, _, serialized = proc.stdout.partition("\n")
    assert ws_id and serialized, (
        f"build subprocess produced no output for {script_name}")
    return ws_id, serialized


def _snapshot_path(idx: int, script_name: str) -> Path:
    """l2_snapshot_<idx>_<script>.json — one file per script holding both
    views (filtered = relevance-filtered with the recorded seed, full =
    relevance_filter=False)."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", script_name)
    return SNAPSHOT_DIR / f"l2_snapshot_{idx:02d}_{safe}.json"


@pytest.mark.parametrize(
    ("idx", "script_name", "sql_text"),
    [pytest.param(i, name, sql, id=f"{i:02d}_{name}")
     for i, (name, sql) in enumerate(_SCRIPTS)],
)
def test_l2_snapshot(idx, script_name, sql_text):
    """L2 output for this script byte-equals the committed snapshot.

    This is the gate stages 2-4 of the physical-model refactor run to
    prove "ids/labels byte-identical": any change to node/edge
    construction, ordering, or the seed selection shows up as a diff.
    Rebaseline ONLY intentional changes (L2_SNAPSHOT_UPDATE=1).
    """
    ws_id, serialized = _run_build(script_name, sql_text)
    assert ws_id not in serialized, (
        f"ws_id leaked into the {script_name} L2 output")
    path = _snapshot_path(idx, script_name)
    if UPDATE_SNAPSHOTS:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized)
        return
    assert path.exists(), (
        f"missing snapshot {path.name} — run with L2_SNAPSHOT_UPDATE=1")
    assert path.read_text() == serialized, (
        f"L2 output diverged from snapshot {path.name} — if the change is "
        f"intentional, rebaseline with L2_SNAPSHOT_UPDATE=1")


def test_full_l2_output_is_deterministic_across_workspaces():
    """Node ids are content-derived hashes — the full-view L2 build must
    be byte-identical across independent workspaces.

    ws_id must never leak into the output (no per-workspace field may vary
    the serialization) — this test proves the snapshot baseline is
    ws-independent, so the committed files hold on any machine.
    """
    for script_name, sql_text in _SCRIPTS:
        ws_a, serialized_a = _run_build(script_name, sql_text, mode="full")
        ws_b, serialized_b = _run_build(script_name, sql_text, mode="full")
        assert serialized_a == serialized_b, (
            f"L2 output for {script_name} differs across workspaces — "
            f"a per-ws value leaked into the graph")
        assert ws_a not in serialized_a and ws_b not in serialized_b, (
            f"ws_id leaked into the {script_name} L2 output")
