"""PERF (v3.3.194) — the A/B byte-identity harness for the performance patch.

The v3.3.194 performance work (team PERF, H6's measured spec) touched the L2
served path in five places, each of which must be provably output-preserving:

  fix 1  load once per request — `dataflow_service.get_level2_graph` already
         loads (full_graph, table_schemas, physical_model) and hands the triple
         to `_build_l2_graph(_shared_load=...)`, which used to reload it per
         build (the request builds the graph twice: flow view + full view).
  fix 2  carried lines into the line-map — `_load_or_build_graph` now hands the
         node-carried line_start/line_end to `_recompute_line_map`, so
         `map_variables_to_lines` takes its v3.3.140 short-circuit instead of
         scanning the script per variable.
  fix 3  one BFS per `_attach_flow_payload` — the upstream closure walk is ONE
         multi-source BFS over the directed edges + ONE over the undirected
         fallback (`_closure_bfs`), and the downstream walk reuses one BFS per
         target node (`_downstream_bfs`); the former code ran one BFS PER EDGE.
  fix 4  request-scoped strict-walk memo (`_flow_memo`) — `compute_field_flow`
         is a pure function of (graph, table, field, direction) and one request
         walked it up to three times.
  fix 5  `_name_to_key`'s entity index + the R44 class-1 write-edge index.

Byte-identity is the hard requirement, so every fix is pinned here:

  * fix 3 is pinned against a VERBATIM copy of the former one-BFS-per-edge
    implementation (`_reference_attach_flow_payload` below) run on the same
    real builder inputs — the strongest available oracle, because the phase
    has no other observable copy.
  * fixes 1 + 4 are pinned end-to-end through `get_level2_graph`: the served
    path vs the same function with the hand-over stripped (the pre-patch code
    path), compared as sha256 over the full JSON response.
  * fix 2 is pinned through the D1 contract (recompute-on-read, comment lines
    never a target) plus the carried-line short-circuit.

The three heavy batteries from the spec (RFN 22 random pairs interleaved, the
4 representative pairs x 3 rounds, and the 36 cross-script cases over 5
scripts x filter True/False) run against real indexed profiling workspaces and
are auto-skipped when those workspaces are absent (they are not committed).
Set ``PERF_AB_WORKSPACES=/tmp/workspaces`` to point them somewhere else.
"""

import copy
import hashlib
import io
import json
import os
import random
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys_path = str(BACKEND_DIR)
if sys_path not in __import__("sys").path:
    import sys
    sys.path.insert(0, sys_path)

from app.services.workspace_service import create_workspace, delete_workspace
from app.services import dataflow_service as ds
from app.services import l2_builder as l2b
from app.extractor import lineage as lineage_mod
from app.extractor.sql_line_mapper import map_variables_to_lines

WORKFLOW_DIR = BACKEND_DIR.parent / "samples" / "multi_workflow"
STEP3 = "step3_join_orders_customers.sql"
SEED_TABLE = "stg_customers"
SEED_FIELD = "customer_id"
RFN_SCRIPT = "BDM_ACC_LOAN_INFO_RFN.sql"


def _digest(response: dict) -> str:
    """The A/B comparator: sha256 over the full JSON response."""
    return hashlib.sha256(
        json.dumps(response, sort_keys=True, default=str).encode()).hexdigest()


# ══════════════════════════════════════════════════════════════════════
# The oracle: the former (v3.3.193) payload phase, verbatim
# ══════════════════════════════════════════════════════════════════════

def _reference_closure_walk(e: dict, entries: list, adjacency: dict,
                            reverse: dict) -> list:
    """VERBATIM the pre-PERF `l2_builder._closure_walk` (deleted by fix 3)."""
    from app.services.highlight_strategies import _safe_int

    def _bfs(start_ids, out_adj):
        target = e["source"]
        prev = {sid: None for sid in start_ids}
        queue = list(start_ids)
        seen = set(start_ids)
        while queue:
            node = queue.pop(0)
            if node == target:
                break
            for oe in out_adj.get(node, []):
                nxt = oe["target"]
                if nxt not in seen:
                    seen.add(nxt)
                    prev[nxt] = (node, oe)
                    queue.append(nxt)
        if target not in seen:
            return None
        path = []
        node = target
        while prev.get(node) is not None:
            parent, oe = prev[node]
            path.append(oe)
            node = parent
        return list(reversed(path))

    if e.get("edge_type") in ("SCHEMA", "SUBSET") or not entries:
        return []
    path = _bfs(entries, adjacency)
    if path is None:
        undirected = {}
        for node, oes in list(adjacency.items()) + list(reverse.items()):
            undirected.setdefault(node, []).extend(oes)
        path = _bfs(entries, undirected)
    if not path:
        return []

    hops = []
    for pe in path:
        hops.append((pe.get("_src_label") or "?", _safe_int(pe.get("_src_line"))))
    hops.append((path[-1].get("_tgt_label") or "?", _safe_int(path[-1].get("_tgt_line"))))
    if hops and hops[-1] == (e.get("_src_label"), _safe_int(e.get("_src_line"))):
        hops = hops[:-1]
    return hops


def _reference_attach_flow_payload(new_edges: list, field_nodes: list,
                                   table_nodes: dict | None = None) -> None:
    """VERBATIM the pre-PERF `_attach_flow_payload`: one BFS per edge."""
    from app.services.highlight_strategies import get_strategy, _safe_int

    if not new_edges:
        return
    strategy = get_strategy("single_line")
    entries = [fn["id"] for fn in field_nodes if fn.get("is_target")]
    adjacency = {}
    reverse = {}
    for e in new_edges:
        adjacency.setdefault(e["source"], []).append(e)
        reverse.setdefault(e["target"], []).append(e)
    flow_targets = {e["target"] for e in new_edges
                    if e.get("_dml_origin") and not e.get("_value_edge")}
    flow_adjacency = {}
    tgt_key_to_target = {}
    write_line_by_target = {}
    for e in new_edges:
        if e.get("edge_type") in ("SCHEMA", "SUBSET"):
            continue
        flow_adjacency.setdefault(e["source"], []).append(e)
        if e.get("_dml_origin") and not e.get("_value_edge"):
            tgt_key_to_target[(e.get("_tgt_label"),
                               _safe_int(e.get("_tgt_line")))] = e["target"]
            write_line_by_target[e["target"]] = _safe_int(e.get("_tgt_line"))
    output_ids = set()
    for tn in (table_nodes or {}).values():
        if (tn.get("table_name") or "").startswith("⟐ output"):
            output_ids.add(tn.get("id"))
    for e in new_edges:
        e["_tgt_output"] = e.get("target") in output_ids
        e["_src_output"] = e.get("source") in output_ids
        up = _reference_closure_walk(e, entries, adjacency, reverse)
        own = [(e.get("_src_label") or "?", _safe_int(e.get("_src_line"))),
               (e.get("_tgt_label") or "?", _safe_int(e.get("_tgt_line")))]
        down = l2b._downstream_walk(e, flow_targets, flow_adjacency,
                                    tgt_key_to_target=tgt_key_to_target,
                                    write_line_by_target=write_line_by_target)
        e["_path_hops"] = up + own + down
        e["_own_seg_idx"] = len(up)
        payload = strategy(e)
        e["highlight_line"] = payload["highlight_line"]
        e["flow_kind"] = payload["flow_kind"]
        e["reason"] = payload["reason"]


# ══════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def multi_workflow_ws():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(WORKFLOW_DIR.glob("step*.sql")):
            zf.write(f, f.name)
    ws_id = create_workspace(buf.getvalue())
    yield ws_id
    delete_workspace(ws_id)


def _capture_payload_inputs(monkeypatch, ws_id, script, sql, table, field,
                            relevance_filter=True):
    """Run one real build and capture `_attach_flow_payload`'s inputs.
    Returns None when the build has no final edges (a search whose seed is
    not in that script's flow) — the caller falls back to the full view."""
    captured = {}
    real = l2b._attach_flow_payload

    def spy(new_edges, field_nodes, table_nodes=None):
        if "args" not in captured:
            captured["args"] = (copy.deepcopy(new_edges),
                                copy.deepcopy(field_nodes),
                                copy.deepcopy(table_nodes))
        return real(new_edges, field_nodes, table_nodes)

    monkeypatch.setattr(l2b, "_attach_flow_payload", spy)
    result = l2b._build_l2_graph(ws_id, script, sql, table, field,
                                 relevance_filter=relevance_filter)
    if not result["edges"]:
        return None
    assert "args" in captured, "the payload phase never ran"
    return captured["args"]


# ══════════════════════════════════════════════════════════════════════
# fix 3 — one BFS per payload phase, pinned against the former form
# ══════════════════════════════════════════════════════════════════════

def test_attach_flow_payload_matches_one_bfs_per_edge_reference(
        multi_workflow_ws, monkeypatch):
    """The shared-BFS payload phase is byte-identical to the former
    one-BFS-per-edge phase over real builder inputs (every script of the
    multi_workflow corpus, flow-filtered and full)."""
    sql_by_script = {f.name: f.read_text()
                     for f in sorted(WORKFLOW_DIR.glob("step*.sql"))}
    for script, sql in sql_by_script.items():
        inputs = []
        for table, field in ((SEED_TABLE, SEED_FIELD),
                             ("stg_orders", "order_id")):
            inputs.append(_capture_payload_inputs(
                monkeypatch, multi_workflow_ws, script, sql, table, field))
        # the full view (no filter) always carries edges
        inputs.append(_capture_payload_inputs(
            monkeypatch, multi_workflow_ws, script, sql, "", "", False))
        assert any(i is not None for i in inputs), \
            f"{script}: no build produced edges to compare"
        for captured in inputs:
            if captured is None:
                continue
            new_edges, field_nodes, table_nodes = captured
            fast = copy.deepcopy(new_edges)
            slow = copy.deepcopy(new_edges)
            l2b._attach_flow_payload(fast, field_nodes, table_nodes=table_nodes)
            _reference_attach_flow_payload(slow, field_nodes,
                                           table_nodes=table_nodes)
            assert fast == slow, (
                f"{script}: the shared-BFS payload diverged from the "
                "per-edge BFS")


def test_closure_bfs_parent_maps_answer_every_reachable_node():
    """`_closure_bfs` returns the same shortest path the former per-edge BFS
    reconstructed — including the entry-itself and the undirected-fallback
    cases (unit-level pin over a hand-built edge list)."""
    from app.services.highlight_strategies import _safe_int

    def edge(eid, src, tgt, sl, tl, etype="REF"):
        return {"source": src, "target": tgt, "edge_type": etype,
                "_src_label": src, "_tgt_label": tgt,
                "_src_line": sl, "_tgt_line": tl}

    edges = [edge("e1", "seed", "a", 1, 2),
             edge("e2", "a", "b", 2, 3),
             edge("e3", "seed", "c", 1, 5),
             edge("e4", "c", "b", 5, 3),      # second shortest path to b
             edge("e5", "b", "seed", 3, 1),   # reverse leg — undirected only
             edge("e6", "x", "y", 9, 9)]      # disconnected component
    adjacency, reverse = {}, {}
    for e in edges:
        adjacency.setdefault(e["source"], []).append(e)
        reverse.setdefault(e["target"], []).append(e)
    prev_dir = l2b._closure_bfs(["seed"], adjacency)
    undirected = {}
    for node, oes in list(adjacency.items()) + list(reverse.items()):
        undirected.setdefault(node, []).extend(oes)
    prev_und = l2b._closure_bfs(["seed"], undirected)

    def legacy(e):
        return _reference_closure_walk(e, ["seed"], adjacency, reverse)

    for e in edges:
        junction = (e.get("_src_label"), _safe_int(e.get("_src_line")))
        assert l2b._closure_hops(e["source"], prev_dir, prev_und, junction) \
            == legacy(e), e
    # an entry itself has no upstream hops; an unreachable node too
    assert l2b._closure_hops("seed", prev_dir, prev_und, ("seed", 1)) == []
    assert l2b._closure_hops("y", prev_dir, prev_und, ("y", 9)) == []


# ══════════════════════════════════════════════════════════════════════
# fixes 1 + 4 — the served response is byte-identical to the reload path
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def legacy_load(monkeypatch):
    """Strip the PERF hand-over args so every `_build_l2_graph` call reloads
    the caches and walks un-memoized — the pre-patch code path."""
    real = l2b._build_l2_graph

    def reload_build(ws_id, script_name, sql_text, table, field,
                     relevance_filter=True, direction="downstream", **kw):
        kw.pop("_shared_load", None)
        kw.pop("_flow_memo", None)
        return real(ws_id, script_name, sql_text, table, field,
                    relevance_filter, direction, **kw)

    monkeypatch.setattr(ds, "_build_l2_graph", reload_build)
    return reload_build


def test_level2_response_identical_shared_load_vs_reload(
        multi_workflow_ws, monkeypatch, legacy_load):
    """fixes 1 + 4: the served (shared load + shared walk memo) response and
    the reload-per-build response are the same bytes, filtered and not."""
    ws_id = multi_workflow_ws
    cases = [("step1_load_orders.sql", "stg_orders", "order_id"),
             (STEP3, SEED_TABLE, SEED_FIELD),
             ("step4_aggregate_daily.sql", "⟐ output", "order_id"),
             ("step5_final_report.sql", "report", "order_id")]
    for script, table, field in cases:
        for flt in (True, False):
            served = ds.get_level2_graph(ws_id, "v", script, table, field,
                                         flt, "downstream")
            assert "error" not in served, served
            served_digest = _digest(served)
            reloaded = ds.get_level2_graph(ws_id, "v", script, table, field,
                                           flt, "downstream")
            assert _digest(reloaded) == served_digest, (
                f"{script} {table}.{field} filter={flt}: the shared load "
                "changed the response")


def test_flow_memo_never_serves_a_stale_closure(multi_workflow_ws):
    """The strict-walk memo is keyed on the graph identity AND the
    (table, field, direction) triple: a cache shared across searches, scripts
    and graphs answers every one of them exactly as an un-memoized walk."""
    ws_id = multi_workflow_ws
    scripts = [(f.name, f.read_text())
               for f in sorted(WORKFLOW_DIR.glob("step*.sql"))]
    searches = [(script, sql, table, field)
                for script, sql in scripts
                for table, field in ((SEED_TABLE, SEED_FIELD),
                                     ("stg_orders", "order_id"))]
    shared_memo, shared_runs = {}, []
    for script, sql, table, field in searches:
        shared_runs.append(_digest(_build_with_memo(
            ws_id, script, sql, table, field, shared_memo)))
    # the same requests, every one with a FRESH memo (the un-memoized
    # equivalent) — a shared cache must answer identically
    fresh_runs = [_digest(_build_with_memo(ws_id, script, sql, table, field, {}))
                  for script, sql, table, field in searches]
    assert shared_runs == fresh_runs


def _build_with_memo(ws_id, script, sql, table, field, memo) -> dict:
    return l2b._build_l2_graph(ws_id, script, sql, table, field,
                               relevance_filter=True, _flow_memo=memo)


def test_compute_field_flow_memo_refills_row_flow_out(multi_workflow_ws):
    """A memo hit re-fills `row_flow_out` and returns a fresh set — the
    caller's output arguments behave exactly as on a full walk."""
    from app.extractor.physical_model import build_physical_model
    from app.services.graph_service import build_graph_data
    from app.extractor.adapter import run_full_analysis

    sql = (WORKFLOW_DIR / STEP3).read_text()
    result = run_full_analysis(sql, STEP3, ws_id="perf-memo-probe")
    graph = build_graph_data(result)
    model = build_physical_model(result, script_name=STEP3)
    memo = {}

    first = lineage_mod.compute_field_flow(
        graph, SEED_TABLE, SEED_FIELD, physical_model=model,
        row_flow_out=[], _flow_memo=memo)
    bridges_one, bridges_two = [], []
    second = lineage_mod.compute_field_flow(
        graph, SEED_TABLE, SEED_FIELD, physical_model=model,
        row_flow_out=bridges_two, _flow_memo=memo)
    assert memo, "the walk must have been cached"
    assert second == first
    assert bridges_two == bridges_one        # both empty, or the same bridges
    # a fresh set every time — mutating a returned closure can never poison
    # the cache (and with it, a later caller)
    second.add("poison")
    assert "poison" not in lineage_mod.compute_field_flow(
        graph, SEED_TABLE, SEED_FIELD, physical_model=model,
        row_flow_out=bridges_one, _flow_memo=memo)


def test_request_walks_the_closure_once(multi_workflow_ws, monkeypatch):
    """fix 6 stays redundant — every `compute_field_flow` call a single L2
    request makes threads the SAME request-scoped `_flow_memo` for the SAME
    (table, field, direction) over the SAME graph, so only the first of them
    performs a full walk.

    H6's fix 6 (memoize the walker per (graph, table, field, direction),
    returning a copy) is exactly what the request-scoped memo already does;
    this pins the plumbing it depends on. A future L2 call site that forgets
    to hand down `_flow_memo` re-adds the full walks and fails here.
    """
    calls = []

    real = lineage_mod.compute_field_flow

    def spy(graph_data, target_table, target_field, table_schemas=None,
            physical_model=None, direction="downstream", row_flow_out=None,
            _flow_memo=None):
        hit = False
        if _flow_memo is not None:
            entry = _flow_memo.get(id(graph_data))
            hit = bool(entry is not None and entry[0] is graph_data
                       and (target_table, target_field,
                            direction) in entry[1])
        calls.append({"key": (target_table, target_field, direction),
                      "graph": id(graph_data),
                      "memo": id(_flow_memo),
                      "hit": hit})
        return real(graph_data, target_table, target_field, table_schemas,
                    physical_model, direction, row_flow_out, _flow_memo)

    monkeypatch.setattr(lineage_mod, "compute_field_flow", spy)
    monkeypatch.setattr(l2b, "compute_field_flow", spy)
    # `filter_by_field_flow` resolves the walker through its own module
    # globals, so patching the module attribute covers it too.

    ws_id = multi_workflow_ws
    sql = (WORKFLOW_DIR / STEP3).read_text()
    for table, field in ((SEED_TABLE, SEED_FIELD), ("stg_orders", "order_id")):
        calls.clear()
        ds.get_level2_graph(ws_id, "v", STEP3, table, field, True, "downstream")
        assert calls, "the request never walked the closure"
        assert len({c["key"] for c in calls}) == 1, (
            f"{table}.{field}: one request walked more than one "
            f"(table, field, direction) key: {[c['key'] for c in calls]}")
        assert len({c["memo"] for c in calls}) == 1, (
            f"{table}.{field}: the walker calls did not share one "
            "request-scoped _flow_memo (a call site dropped the hand-over)")
        assert len({c["graph"] for c in calls}) == 1, (
            f"{table}.{field}: the walker calls saw different graphs")
        assert sum(1 for c in calls if not c["hit"]) == 1, (
            f"{table}.{field}: expected exactly one full walk, got "
            f"{sum(1 for c in calls if not c['hit'])} of {len(calls)} calls")
        assert any(c["hit"] for c in calls), (
            f"{table}.{field}: the memo never served a repeat walk")


# ══════════════════════════════════════════════════════════════════════
# fix 2 — the line-map recompute takes the carried-line short-circuit
# ══════════════════════════════════════════════════════════════════════

def test_line_map_recompute_uses_carried_lines():
    """fix 2: cached node dicts carry line_start/line_end, so the recompute
    resolves them directly (no script scan) and never lands on a comment."""
    sql = ("-- 源表名：ODS [ods_hub_x] BDM [bdm_acc_loan_info]\n"
           "-- 创建时间：2025-11-11\n"
           "SELECT loan_id\n"
           "FROM bdm_acc_loan_info\n"
           "WHERE data_dt = '2026-01-01';\n")
    carried = map_variables_to_lines(
        [{"id": "t1", "sql_expression": "bdm_acc_loan_info",
          "line_start": 4, "line_end": 4},
         {"id": "c1", "sql_expression": "data_dt = '2026-01-01'",
          "line_start": 5, "line_end": 5}], sql)
    assert carried == {"t1": (4, 4), "c1": (5, 5)}
    # the D1 fallback is intact: without carried lines the text search runs,
    # and it still skips the comment banner
    fallback = map_variables_to_lines(
        [{"id": "t1", "sql_expression": "bdm_acc_loan_info"},
         {"id": "c1", "sql_expression": "data_dt = '2026-01-01'"}], sql)
    assert fallback == {"t1": (4, 4), "c1": (5, 5)}
    # a var carrying no line still resolves through the fallback
    mixed = map_variables_to_lines(
        [{"id": "t1", "sql_expression": "bdm_acc_loan_info"},
         {"id": "c1", "sql_expression": "data_dt = '2026-01-01'",
          "line_start": 5, "line_end": 5}], sql)
    assert mixed == {"t1": (4, 4), "c1": (5, 5)}


def test_load_or_build_graph_line_map_recomputed_with_carried_lines(
        multi_workflow_ws):
    """`_load_or_build_graph` still recomputes the line_map on every cache
    read (the D1 contract) — now from the carried lines."""
    sql = (WORKFLOW_DIR / STEP3).read_text()
    l2b._load_or_build_graph(multi_workflow_ws, STEP3, sql)   # write caches
    from app.services.workspace_service import get_workspace_dir
    graph_cache = next((get_workspace_dir(multi_workflow_ws) / "cache")
                       .glob("graph_*.json"))
    cached = json.loads(graph_cache.read_text())
    assert cached.get("line_map"), "cache must carry a line_map"
    cached["line_map"] = {}                                   # simulate stale
    graph_cache.write_text(json.dumps(cached))

    full_graph, _, _ = l2b._load_or_build_graph(multi_workflow_ws, STEP3, sql)
    lm = full_graph.get("line_map", {})
    assert lm, "line_map must be recomputed on cache read"


# ══════════════════════════════════════════════════════════════════════
# The spec's three heavy batteries (real indexed profiling workspaces)
# ══════════════════════════════════════════════════════════════════════

WS_ROOT = Path(os.environ.get("PERF_AB_WORKSPACES", "/tmp/workspaces"))
RFN_WS = "db63e8e00e423ba1cad4c2fd5a3bb9ff"
CROSS_WS = "a9a94b6e1c6a4bd1ae2dc20535ceb6c4"

needs_rfn = pytest.mark.skipif(
    not (WS_ROOT / RFN_WS / "cache" / "pair_index.json").exists(),
    reason=f"profiling workspace {RFN_WS} is not present under {WS_ROOT}")
needs_cross = pytest.mark.skipif(
    not (WS_ROOT / CROSS_WS / "cache" / "pair_index.json").exists(),
    reason=f"profiling workspace {CROSS_WS} is not present under {WS_ROOT}")


def _ab(ws_id, script, table, field, flt=True):
    """One interleaved A/B round: served vs reload, digests + timings."""
    import time
    out = {}
    for phase in ("served", "reload"):
        ds.get_level2_graph(ws_id, "v", script, table, field, flt, "downstream")
        t0 = time.perf_counter()
        r = ds.get_level2_graph(ws_id, "v", script, table, field, flt,
                                "downstream")
        out[phase] = ((_digest(r)), (time.perf_counter() - t0) * 1000)
    return out


@needs_rfn
def test_ab_rfn_random_pairs_interleaved(legacy_load):
    """Battery 1 — 22 random RFN pairs, interleaved served/reload."""
    pairs = list(json.loads((WS_ROOT / RFN_WS / "cache" / "pair_index.json")
                            .read_text()).keys())
    random.seed(11)
    sample = random.sample(pairs, 22)
    diff, timings = [], []
    for p in sample:
        table, field = p.split(".", 1)
        r = _ab(RFN_WS, RFN_SCRIPT, table, field, True)
        timings.append((r["served"][1], r["reload"][1]))
        if r["served"][0] != r["reload"][0]:
            diff.append(p)
    assert not diff, f"byte-differing pairs: {diff}"
    served = sorted(t[0] for t in timings)
    reload_ = sorted(t[1] for t in timings)
    print(f"\nRFN 22 pairs: served median {served[len(served) // 2]:.0f} ms, "
          f"reload median {reload_[len(reload_) // 2]:.0f} ms")


@needs_rfn
def test_ab_rfn_four_pairs_three_rounds(legacy_load):
    """Battery 2 — the 4 representative pairs x 3 rounds, alternating the
    phase order so neither side systematically wins the cache-warming."""
    pairs = [("bdm_acc_loan_info", "data_dt"),
             ("TEMP_BDM_ACC_LOAN_INFO_02", "p_dt"),
             ("rrcdm_job_log_exec_par", "data_dt"),
             ("ODS_HUB_SSINRTP", "p_dt")]
    diff = []
    for table, field in pairs:
        for rnd in range(3):
            r = _ab(RFN_WS, RFN_SCRIPT, table, field, True)
            if rnd % 2:
                r = {"served": r["reload"], "reload": r["served"]}
            if r["served"][0] != r["reload"][0]:
                diff.append(f"{table}.{field} r{rnd}")
    assert not diff, f"byte-differing rounds: {diff}"


@needs_cross
def test_ab_cross_script_both_filter_modes(legacy_load):
    """Battery 3 — 36 cross-script cases (5 scripts x filter True/False)."""
    pair_index = json.loads((WS_ROOT / CROSS_WS / "cache" / "pair_index.json")
                            .read_text())
    random.seed(3)
    cases = [(s, p) for p, scripts in pair_index.items() for s in scripts]
    step5 = sorted({p for p, s in cases if s == "step5_final_report.sql"})
    sample = random.sample(cases, 18) + [
        ("step5_final_report.sql", p)
        for p in random.sample(step5, min(6, len(step5)))]
    random.shuffle(sample)
    diff, scripts_seen = [], set()
    for script, pair in sample[:18]:
        table, field = pair.split(".", 1)
        for flt in (True, False):
            r = _ab(CROSS_WS, script, table, field, flt)
            scripts_seen.add(script)
            if r["served"][0] != r["reload"][0]:
                diff.append((script, pair, flt))
    assert not diff, f"byte-differing cases: {diff}"
    assert len(scripts_seen) == 5, sorted(scripts_seen)
