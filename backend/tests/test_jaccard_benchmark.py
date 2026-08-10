"""Jaccard benchmark — THE benchmark (supersedes test_ground_truth_benchmark.py).

User ruling (2026-08-10): the benchmark is A∩B / A∪B over THREE perspectives
per seed — nodes, edges, highlights — where

    A = filtered L2 output (same path as the served /views/{id}/level2)
    B = canonical ground truth (backend/tests/jaccard_canonical.py, compiled
        from tools/GROUND_TRUTH_BDM_ACC_LOAN_INFO_SUP.md §8.4/§8.5 and
        self-verified against the served output on 2026-08-10)

Seeds: bdm (bdm_acc_loan_info) and sup (bdm_acc_loan_info_sup), target data_dt.

Iteration contract (user ruling, 2026-08-10):
  1. Every iteration recomputes this benchmark.
  2. No score may regress below FLOORS — raise FLOORS as fixes land.
  3. Iterate until there is nothing left to improve: matched canonical rows
     == all canonical rows, A_highlights == B_highlights, every canonical
     node realized. Unmatched rows print below as the improvement backlog;
     rows that the ground truth itself is wrong about are repaired in the
     doc + fixture with evidence — never in the engine (2026-08-10 repair:
     rows 10/C4 merged into C2/C3, rows 12/16/17/B1 re-pinned to the
     DML-routed form, see jaccard_canonical.py point 6).

Matching (label + incident-line evidence): served node ids are opaque
build-specific hashes (l2_tbl_*), so identity is the node LABEL after
NORMALIZE_MAP, plus endpoint-line evidence — an endpoint "label@line"
matches when a response node normalizes onto the label AND line is in the
node's incident-edge highlight_line set (VT / line-0 endpoints are
label-only). Edge types are prefix-matched ("TABLE_FLOW" matches
"TABLE_FLOW/write"); each response edge may satisfy only one canonical row
(used-set, deterministic by edge id).

Invariants enforced in addition to the scores: every L2 edge carries
highlight_line >= 1; every canonical node must be realized in A.
"""

import sys
from collections import defaultdict
from pathlib import Path

# tests/ is not on sys.path in the pytest run (tests package layout) —
# jaccard_canonical is a sibling data-only module, importable by path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import jaccard_canonical as JC
from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.extractor.dependency_graph import build_dependency_graph
from app.services.l2_builder import _build_l2_graph

SQL_NAME = "BDM_ACC_LOAN_INFO_SUP_M.sql"
TARGET_FIELD = "data_dt"
SEED_TABLE = {"bdm": "bdm_acc_loan_info", "sup": "bdm_acc_loan_info_sup"}
SEEDS = ("bdm", "sup")
FEATURES = ("nodes", "edges", "highlights")

# ── Floors: no score may regress below these. Raised 2026-08-10 after the
#    walker-gating / Bug-31 / hl=0 fixes + the evidence-backed DML-routing
#    doc repair (measured live, jaccard_canonical.py point 6). Baseline
#    (pre-fix, same day): bdm 0.1345/0.0891/0.2069, sup 0.0818/0.0452/0.1250.
#    Bump a number as the next fix lands — that bump is the accepted iteration.
FLOORS = {
    "bdm": {"nodes": 1.0000, "edges": 0.8000, "highlights": 0.9231},
    "sup": {"nodes": 0.9000, "edges": 0.7333, "highlights": 0.8571},
}


def build_a(seed):
    """Filtered L2 output for the seed's target field (served semantics)."""
    sql = open("/app/samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql",
               encoding="utf-8").read()
    result = extract_variables_from_sql(sql, SQL_NAME)
    build_dependency_graph(result, sql)
    l2 = _build_l2_graph("bench", SQL_NAME, sql, SEED_TABLE[seed], TARGET_FIELD)
    g = l2.get("graph") if isinstance(l2.get("graph"), dict) else l2
    nodes = {n["data"]["id"]: n["data"] for n in g["nodes"]}
    edges = [e["data"] for e in g["edges"]]
    return nodes, edges


def _norm(label):
    return JC.NORMALIZE_MAP.get(label, label)


def _split_ep(ep):
    label, _, line = ep.rpartition("@")
    return label, (int(line) if line else None)


def _endpoint_ok(ep, node_id, nodes, inc):
    """Canonical endpoint 'label@line' vs a response node (label + incident
    line evidence; VT/line-0 endpoints are label-only)."""
    c_label, c_line = _split_ep(ep)
    if _norm(c_label) != _norm(nodes[node_id]["label"]):
        return False
    if c_line is None or c_line == 0:
        return True
    return c_line in inc[node_id]


def match_seed(seed, nodes, edges):
    """Per-row canonical match; returns {row_id: edge_id}. The response
    builds deterministically (sorted candidate order, used-set per edge),
    so the test is stable across runs."""
    inc = defaultdict(set)
    for e in edges:
        inc[e["source"]].add(e["highlight_line"])
        inc[e["target"]].add(e["highlight_line"])
    used = set()
    matched = {}

    def candidates(anchor, prefix):
        out = [e for e in edges
               if e["highlight_line"] == anchor
               and (e["edge_type"] or "").startswith(prefix)]
        out.sort(key=lambda e: e["id"])
        return out

    for entry in JC.CANONICAL_EDGES:
        if entry["seed"] != seed:
            continue
        anchor, typ, spec = entry["anchor"], entry["type"], entry["spec"]
        hit = None
        if spec == "anchor_rel":
            for e in candidates(anchor, typ):
                if e["id"] not in used:
                    hit = e
                    break
        elif spec == "anchor_rel_ep":
            for e in candidates(anchor, typ):
                if e["id"] in used:
                    continue
                if (_endpoint_ok(entry["src"], e["source"], nodes, inc)
                        and _endpoint_ok(entry["dst"], e["target"], nodes, inc)):
                    hit = e
                    break
        elif spec == "two_hop":
            has_alias = any(e["highlight_line"] == anchor
                            and (e["edge_type"] or "").startswith("ALIAS")
                            for e in edges)
            for e in candidates(anchor, "TABLE_FLOW"):
                if e["id"] not in used:
                    hit = e
                    break
            if not has_alias:
                hit = None
        elif spec == "ref_alias":
            for e in candidates(anchor, "REF"):
                if e["id"] not in used:
                    hit = e
                    break
        if hit is not None:
            used.add(hit["id"])
            matched[entry["row"]] = hit["id"]
    return matched


def node_realized(c_label, c_line, nodes, inc):
    for nid, nd in nodes.items():
        if _norm(nd["label"]) != _norm(c_label):
            continue
        if c_line is None or c_line == 0:
            return True
        if c_line in inc[nid]:
            return True
    return False


def compute_seed(seed):
    nodes, edges = build_a(seed)
    inc = defaultdict(set)
    for e in edges:
        inc[e["source"]].add(e["highlight_line"])
        inc[e["target"]].add(e["highlight_line"])
    matched = match_seed(seed, nodes, edges)
    rows = [e for e in JC.CANONICAL_EDGES if e["seed"] == seed]
    canon_nodes = JC.CANONICAL_NODES[seed]
    realized = [c for c in canon_nodes
                if node_realized(c["label"], c["line"], nodes, inc)]
    hl_a = {e["highlight_line"] for e in edges if e["highlight_line"] >= 1}
    hl_b = {e["anchor"] for e in rows}
    counts = {
        "nodes": (len(nodes), len(canon_nodes), len(realized)),
        "edges": (len(edges), len(rows), len(matched)),
        "highlights": (len(hl_a), len(hl_b), len(hl_a & hl_b)),
    }
    jaccard = {f: ni / (na + nb - ni) for f, (na, nb, ni) in counts.items()}
    return {
        "edges": edges,
        "matched": matched,
        "unmatched": [r for r in rows if r["row"] not in matched],
        "unrealized": [c for c in canon_nodes if c not in realized],
        "counts": counts,
        "jaccard": jaccard,
    }


def test_jaccard_benchmark(capsys):
    results = {}
    problems = []
    for seed in SEEDS:
        r = compute_seed(seed)
        results[seed] = r
        if r["unrealized"]:
            problems.append(f"{seed}: {len(r['unrealized'])} canonical nodes "
                            f"NOT realized: {r['unrealized']}")
        bad = [e for e in r["edges"] if int(e.get("highlight_line") or 0) < 1]
        if bad:
            problems.append(
                f"{seed}: {len(bad)} edges with highlight_line < 1 "
                f"(first: {[(e.get('id'), e.get('highlight_line')) for e in bad[:5]]})")
    with capsys.disabled():
        print("\n════════════ JACCARD BENCHMARK — THE benchmark (target: data_dt) ════════════")
        print(f"{'seed':5}{'feature':11}{'|A|':>6}{'|B|':>6}{'A∩B':>6}{'A∪B':>6}{'Jaccard':>9}   floor")
        for seed in SEEDS:
            r = results[seed]
            for feat in FEATURES:
                a, b, i = r["counts"][feat]
                j = r["jaccard"][feat]
                flag = "" if round(j, 4) >= FLOORS[seed][feat] else "   ← REGRESSION"
                print(f"{seed:5}{feat:11}{a:6}{b:6}{i:6}{a + b - i:6}{j:9.4f}   {FLOORS[seed][feat]:.4f}{flag}")
        for seed in SEEDS:
            r = results[seed]
            if r["unmatched"]:
                print(f"\n{seed} — improvement backlog: {len(r['unmatched'])} canonical edges unmatched: "
                      f"{[x['row'] for x in r['unmatched']]}")
                for x in r["unmatched"]:
                    print(f"    row={x['row']} anchor={x['anchor']} rel={x['type']}  "
                          f"{x['src']} -> {x['dst']}")
        summary = "  |  ".join(
            f"{seed} " + " ".join(f"{feat[:1].upper()}={results[seed]['jaccard'][feat]:.4f}"
                                  for feat in FEATURES)
            for seed in SEEDS)
        print(f"\nJACCARD: {summary}")
        print("════════════════════════════════════════════════════════════════════════════")
    for seed in SEEDS:
        for feat in FEATURES:
            assert round(results[seed]["jaccard"][feat], 4) >= FLOORS[seed][feat], (
                f"REGRESSION {seed}/{feat}: {results[seed]['jaccard'][feat]:.4f} "
                f"< floor {FLOORS[seed][feat]:.4f}")
    assert not problems, "benchmark invariants violated:\n" + "\n".join(problems)
