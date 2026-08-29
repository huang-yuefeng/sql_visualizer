"""ISSUE-6 / R32 — L2 line-merged views: the benchmark.

This pins the canonical merged closure for the L2 line-merged pass
(`l2_builder.build_line_merged_edges`), the NEW views emitted by
`dataflow_service.get_level2_graph` as `flow_only_merged` / `full_merged`
(one SQL line ≈ one edge: field→table promotion, same-line same-table-pair
merge, type removed to an untyped FLOW edge, self-loops kept only as a
line's sole edge, lineless edges dropped, >2 tables → one edge per pair).

Case under benchmark
--------------------
  script = samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql
  seed   = bdm_acc_loan_info_sup . data_dt  (the "sup" seed), direction
           "downstream" — the SAME case the existing Jaccard benchmark pins
           (test_jaccard_benchmark.py CASES[1], jaccard_canonical.py).

The merged views are verified through the REAL served path —
`get_level2_graph` on a throwaway workspace — so the `flow_only_merged` /
`full_merged` keys are read back exactly as the /views/{id}/level2 endpoint
emits them (never a re-implementation of the merge). The scratch workspace
is deleted in a `finally`.

INDEPENDENCE (the two ground-truth rules)
-----------------------------------------
The canonical merged closure B is derived by READING THE SQL — which lines
reference which table pairs — then applying the DOCUMENTED merge semantics
(promote field endpoint → parent table; one untyped edge per (line,
unordered table pair); double arrow iff both directions; self-loop only as
a line's sole edge). It is never copied from the engine's merged output.
The engine is used only to PROBE the served shape so the canonical rows can
be pinned (BENCHMARK_CASE_BUILD_METHOD.md Step 2). The derivation is
reproduced line-by-line in the comments of CANONICAL_MERGED_FLOW below.

SET EQUALITY, not size: the case passes iff recall AND precision are both
1.0 (|A∩B|/|B| == 1 AND |A∩B|/|A| == 1). A size match with disjoint sets
is a FAIL.

KNOWN GAP — parentless field (documented, NOT patched)
------------------------------------------------------
The merge pass promotes a field endpoint to its PARENT TABLE by reading the
field node's `parent` id. A field node whose parent table is NOT in the
node set (a "parentless" field) has no table to promote to, so its endpoint
stays a field node id — an edge that is not a clean table→table edge. The
pass cannot recover the parent from the stripped L2 payload (the classifier
gap is upstream of this pass; per the project's diagnostics-not-fix rule it
must not be worked around here). This gap does NOT manifest in the sup seed
(its flow closure and its full graph have zero parentless fields — every
field's parent is in the node set, so every endpoint promotes). It DOES
manifest in other scripts' FULL graphs, e.g. BDM_ACC_LOAN_INFO_Digitallending
.sql (fields cb_pointer, lrr_key, account, product, cust_no, CUST_TYPE with
parent=None) and BDM_ACC_LOAN_INFO_PL.sql (HKZH, "HKZH, 1, 9)"), where the
merged full view keeps those field ids as endpoints. The invariant check
below therefore runs a "no field endpoint" guard for THIS script only, and
notes the DL/PL gap in the docstring rather than patching the source.

SCOPING — why `flow_only_merged` is pinned by set equality but `full_merged`
is pinned structurally
---------------------------------------------------------------------------
The flow closure is independently pinnable: its field-level ground truth
(jaccard_canonical.py CANONICAL_EDGES) is derived from the ground-truth
docs' REQUIREMENT sections, so its merged form is an independent set. The
FULL graph, by contrast, is DEFINED as "everything the extractor found"
(all 16 edge types across the whole script) — there is no canonical full
graph distinct from the engine's own output (the existing benchmark pins
only the flow closure for exactly this reason). So `full_merged`'s CONTENT
has no independent canonical pin; it is verified structurally instead:
  (a) its node set is IDENTICAL to the served full graph's node set (the
      merge pass never touches nodes),
  (b) the merge rules hold on it (untyped FLOW edges, one edge per
      (line, table-pair), self-loop sole-only, no lineless edge, no field
      endpoint for this parentless-free script),
  (c) it COVERS the canonical flow edges — every canonical flow edge's
      (line, unordered node pair) is present in full_merged with an arrow
      set that is a superset of the flow edge's arrows (the full build's
      extra edges can only widen a pair's direction, never narrow it).

ADJUDICATION (2026-08-29, F-D) — the rule-4 self-loop invariant and SUP_M
line 59
-------------------------------------------------------------------------
This benchmark's rule-4 check fired after the family-3 occurrence twins
(EXTRACTOR_VERSION 2026-08-28.6) minted a second SCHEMA belongs-to edge on
SUP_M line 59 (`GROUP BY lending_ref`). Verdict, after reading
`l2_builder.build_line_merged_edges`: the INVARIANT is amended, the
builder is NOT asked to dedup harder, and the intent survives intact.

  * The builder's rule 4 carries its own recorded ruling (L-E5): a self-loop
    is absorbed only into the line's NON-SELF edge(s); a line whose edges
    are ALL self-loops keeps every one of them, because two distinct
    self-loops (T1→T1 + T2→T2) are each their own table's sole edge. The
    check below still enforced the pre-L-E5 form (`len(les) > 1`), so the
    builder and its benchmark disagreed — the check was stale, not the
    builder. Amended to the L-E5 semantics (self-loop + non-self edge on
    one line ⇒ must be absorbed), which is the invariant's actual intent:
    a table's loop must never silently disappear among a line's other
    table-pair edges.
  * What line 59 actually carries, SQL-verified: L59 `GROUP BY lending_ref`
    belongs to the ENCLOSING subq (the NOT-IN subquery
    `SELECT DISTINCT lending_ref FROM bdm_evt_loan_trans a WHERE …` closes
    at L58), whose only source is p1 = bdm_acc_loan_info — so
    (a) `bdm_acc_loan_info → lending_ref@59` (canonical LFS106, the #387
    GROUP-BY occurrence twin) is genuine, and
    (b) `bdm_evt_loan_trans → lending_ref@59` is an extractor DEFECT (the
    twin inherited subq2's owner for an occurrence outside subq2's parens;
    family 3's "never a guessed owner" contract). Reported to the
    extractor owner, never canonicalized; fixed by F-E2 (Fixes C/G/E/F,
    2026-08-28.8) — the L59 GROUP-BY defect reasoning lives in this file's
    docstring above and the equivalence docstring; the IID18 note in
    jaccard_canonical.py is now the L201 plain-alias twin removal note
    (a different defect). When L59-class bugs are fixed, line 59 keeps
    exactly one self-loop — and the amended rule keeps it.
"""

import io
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.services.workspace_service import create_workspace, delete_workspace
from app.services.dataflow_service import get_level2_graph

SCRIPT = "BDM_ACC_LOAN_INFO_SUP_M.sql"
SEED_TABLE = "bdm_acc_loan_info_sup"
TARGET_FIELD = "data_dt"
DIRECTION = "downstream"

# Served-label → canonical-endpoint alignment for THIS seed. The output
# virtual tables are distinguished by statement context (the two `output`
# nodes share the label "output" but belong to TOP0 = the INSERT OVERWRITE
# into bdm_acc_loan_info_sup @160, and TOP1 = the INSERT INTO
# rrcdm_job_log_exec_par @211) — exactly the endpoint-identity evidence the
# existing Jaccard harness tracks via context/line_start.
_LABEL_NORM = {
    "bdm_acc_loan_info_sup": "sup",
    "rrcdm_job_log_exec_par": "rrcdm",
    "p2@199": "p2",
}


def _ep_key(nd):
    """Canonical endpoint key for a served node (dict). Output VTs are
    qualified by statement so the two `output` nodes stay distinct. The
    statement is the `TOPn` prefix of the context — sub-branch suffixes
    after the first `/` are ignored, mirroring `_stmt_of_node` (L-BM3)."""
    if nd.get("label") == "output":
        ctx = nd.get("context") or ""
        stmt = ctx.split("/")[0] if ctx.startswith("TOP") else "?"
        return "output@" + stmt
    return _LABEL_NORM.get(nd.get("label"), nd.get("label"))


def _served_merged_key(e, id_to_node):
    """Normalize a served merged edge to its canonical key. For a single-arrow
    edge the emitted (source, target) IS the arrow direction (the pass emits
    `source=a,target=b` when only a→b is present); for a double-arrow edge the
    pair is unordered."""
    d = e["data"]
    s = _ep_key(id_to_node[d["source"]])
    t = _ep_key(id_to_node[d["target"]])
    line = d["highlight_line"]
    if d["bidirectional"]:
        return ("both", line, frozenset((s, t)))
    return ("one", line, s, t)


def _canonical_key(row):
    if row["bidir"]:
        return ("both", row["line"], frozenset((row["src"], row["dst"])))
    return ("one", row["line"], row["src"], row["dst"])


# ── Canonical merged closure for the sup seed (downstream) — 10 edges. ──
# Derived by reading BDM_ACC_LOAN_INFO_SUP_M.sql (lines named below) and
# applying the merge semantics. Each row: {line, src, dst, bidir} where
# src→dst is the ARROW direction (bidir = both directions).
CANONICAL_MERGED_FLOW = [
    # L160 `INSERT OVERWRITE TABLE bdm_acc_loan_info_sup PARTITION(data_dt=…)`:
    # the write leg output→sup + the partition read sup→output (both
    # directions on one line → ONE double-arrow edge), and the self-join
    # ALIAS sup→p2 (@199, anchored @160).
    {"line": 160, "src": "sup", "dst": "output@TOP0", "bidir": True},
    {"line": 160, "src": "sup", "dst": "p2", "bidir": False},
    # L199 `LEFT JOIN bdm_acc_loan_info_sup p2`: the read data_dt→p2 and the
    # FROM hop p2→output.
    {"line": 199, "src": "sup", "dst": "p2", "bidir": False},
    {"line": 199, "src": "p2", "dst": "output@TOP0", "bidir": False},
    # L202 `AND p2.data_dt = DATEADD(…)` (the p2 self-join ON): the field
    # membership p2→data_dt(sup) and the join admission data_dt→output.
    {"line": 202, "src": "p2", "dst": "sup", "bidir": False},
    {"line": 202, "src": "sup", "dst": "output@TOP0", "bidir": False},
    # L211 `INSERT INTO TABLE rrcdm_job_log_exec_par(…)`: the write leg.
    {"line": 211, "src": "output@TOP1", "dst": "rrcdm", "bidir": False},
    # L213 `'$(load_date)' AS data_dt` (the job-log output column): the
    # output-VT membership output→data_dt(rrcdm) + the value write
    # data_dt(rrcdm)→output → ONE double-arrow edge.
    {"line": 213, "src": "output@TOP1", "dst": "rrcdm", "bidir": True},
    # L223 `FROM bdm_acc_loan_info_sup` (the job-log read): the read leg.
    {"line": 223, "src": "sup", "dst": "output@TOP1", "bidir": False},
    # L225 `WHERE data_dt = '$(load_date)'`: the FILTER read data_dt→sup
    # promotes to a sup self-loop — the SOLE edge of line 225, so it is KEPT.
    {"line": 225, "src": "sup", "dst": "sup", "bidir": False},
]


def _serve(ws_id):
    """Call the real served path and return the response's merged views."""
    resp = get_level2_graph(ws_id, "bench_view", SCRIPT, SEED_TABLE,
                            TARGET_FIELD, True, DIRECTION)
    return resp


def _node_id_set(view):
    return {n["data"]["id"] for n in view["nodes"] if n.get("data", {}).get("id")}


def _id_to_node(view):
    return {n["data"]["id"]: n["data"] for n in view["nodes"]}


def _merge_shape_problems(view, name):
    """The documented merge rules as invariants. Returns problem strings."""
    problems = []
    edges = view["edges"]
    id_to_node = _id_to_node(view)
    # rule 3 — untyped FLOW edge.
    for e in edges:
        d = e["data"]
        if d.get("edge_type") != "FLOW" or d.get("label") != "FLOW":
            problems.append(
                f"{name}: merged edge {d.get('id')} must be untyped FLOW, "
                f"got type={d.get('edge_type')!r} label={d.get('label')!r}")
            break
    # rule 5 — no lineless edge.
    for e in edges:
        if int(e["data"].get("highlight_line") or 0) < 1:
            problems.append(
                f"{name}: merged edge {e['data'].get('id')} has no SQL-line "
                f"reference (highlight_line < 1)")
    # rule 2 — one edge per (line, unordered table pair); per node-id pair.
    seen = {}
    for e in edges:
        d = e["data"]
        key = (d["highlight_line"], frozenset((d["source"], d["target"])))
        if key in seen:
            problems.append(
                f"{name}: two merged edges share (line, table pair) "
                f"{key}: {seen[key]} and {d.get('id')}")
        seen[key] = d.get("id")
    # rule 4 — a self-loop survives only when its line carries NO non-self
    # edge (l2_builder.build_line_merged_edges rule 4 / L-E5): a line whose
    # edges are ALL self-loops keeps every one of them — two distinct
    # self-loops (T1→T1 + T2→T2) are each their own table's sole edge —
    # while a self-loop sharing its line with a non-self table pair is
    # absorbed into that pair. (The pre-L-E5 form of this check used
    # `len(les) > 1`, which also fired on a line of two distinct self-loops
    # and demanded the builder dedup harder — the exact check L-E5
    # replaced; its one live trigger was line 59 of SUP_M, see the module
    # note below.)
    by_line = defaultdict(list)
    for e in edges:
        by_line[e["data"]["highlight_line"]].append(e["data"])
    for line, les in by_line.items():
        self_loops = [d for d in les if d["source"] == d["target"]]
        non_self = [d for d in les if d["source"] != d["target"]]
        if self_loops and non_self:
            for d in self_loops:
                problems.append(
                    f"{name}: self-loop {d.get('id')} on line {line} shares "
                    f"its line with {len(non_self)} non-self edge(s) — must "
                    f"be absorbed")
    # field→table promotion — no field endpoint may survive (THIS script has
    # no parentless fields; see the parentless-field KNOWN GAP in the module
    # docstring for the DL/PL scripts where this does NOT hold).
    for e in edges:
        d = e["data"]
        for side in ("source", "target"):
            nd = id_to_node.get(d[side], {})
            if nd.get("type") == "field":
                problems.append(
                    f"{name}: merged edge {d.get('id')} still has a FIELD "
                    f"endpoint {d[side]} ({nd.get('label')}) — not promoted "
                    f"to a table edge")
    return problems


def _flow_covered_by_full(flow_view, full_view):
    """(c) coverage: each flow merged edge's (line, unordered node pair) has a
    full_merged edge whose arrow set is a superset of the flow edge's arrows.
    The full build only ADDS edges, so a pair's direction can only widen
    (single → double); it can never disappear (a non-self-loop pair cannot be
    absorbed). Returns problem strings."""
    problems = []
    full_by_pair = defaultdict(list)
    for e in full_view["edges"]:
        d = e["data"]
        full_by_pair[(d["highlight_line"],
                      frozenset((d["source"], d["target"])))].append(d)
    for e in flow_view["edges"]:
        d = e["data"]
        # L-BM2: a SELF-loop (source == target) can legitimately be absorbed
        # by the full build (rule 4 — absorbed when the line gains another
        # table pair), so it has no guaranteed full_merged counterpart. Only
        # non-self pairs are guaranteed to survive; skip self-loops.
        if d["source"] == d["target"]:
            continue
        key = (d["highlight_line"], frozenset((d["source"], d["target"])))
        matches = full_by_pair.get(key, [])
        if not matches:
            problems.append(
                f"coverage: flow merged edge {d.get('id')} (line "
                f"{d['highlight_line']}, pair {key}) has NO full_merged "
                f"counterpart")
            continue
        need_bidir = d["bidirectional"]
        if need_bidir and not any(m["bidirectional"] for m in matches):
            problems.append(
                f"coverage: flow merged edge {d.get('id')} is double-arrow "
                f"but full_merged only carries a single arrow on line "
                f"{d['highlight_line']} pair {key}")
    return problems


def test_l2_line_merged_benchmark(capsys):
    """Pin the canonical merged closure; verify flow_only_merged by set
    equality (recall = precision = 1.0) and full_merged structurally."""
    sql = Path("/app/samples/sql_sample_v1") / SCRIPT
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(SCRIPT, sql.read_text(encoding="utf-8"))
    ws_id = create_workspace(buf.getvalue())
    try:
        resp = _serve(ws_id)
    finally:
        # scratch workspace cleanup — a leftover dir fills the per-user
        # workspace quota and breaks other tests.
        delete_workspace(ws_id)

    assert "flow_only_merged" in resp and "full_merged" in resp, \
        "served response missing the merged views"

    flow_view = resp["flow_only_merged"]
    full_view = resp["full_merged"]

    # ── node-set identity (the merge pass never touches nodes) ──
    assert _node_id_set(flow_view) == _node_id_set(resp["graph"]), \
        "flow_only_merged node set must be IDENTICAL to the L2 flow closure"
    assert _node_id_set(full_view) == _node_id_set(resp["full_graph"]), \
        "full_merged node set must be IDENTICAL to the served full graph"

    # ── set equality for flow_only_merged ──
    id_to_node = _id_to_node(flow_view)
    A = {_served_merged_key(e, id_to_node) for e in flow_view["edges"]}
    B = {_canonical_key(row) for row in CANONICAL_MERGED_FLOW}
    inter = A & B
    recall = len(inter) / len(B)
    precision = len(inter) / len(A)
    with capsys.disabled():
        print(f"\n════════ L2 LINE-MERGED BENCHMARK — {SCRIPT} / "
              f"{SEED_TABLE}.{TARGET_FIELD} / {DIRECTION} ════════")
        print(f"{'view':22}{'|A|':>6}{'|B|':>6}{'A∩B':>6}{'Recall':>9}"
              f"{'Precision':>11}")
        print(f"{'flow_only_merged':22}{len(A):6}{len(B):6}{len(inter):6}"
              f"{recall:9.4f}{precision:11.4f}")
        print("\ncanonical merged edge set (derived from SQL):")
        for row in CANONICAL_MERGED_FLOW:
            arrow = "↔" if row["bidir"] else "→"
            print(f"    @{row['line']:>4}  {row['src']} {arrow} {row['dst']}"
                  f"{'  (double arrow)' if row['bidir'] else ''}")
        if A - B:
            print(f"\nEXTRA served edges (junk — precision < 1.0): "
                  f"{sorted(str(x) for x in A - B)}")
        if B - A:
            print(f"\nMISSING canonical edges (recall < 1.0): "
                  f"{sorted(str(x) for x in B - A)}")
        print("═════════════════════════════════════════════════════════════")

    assert recall == 1.0, \
        f"flow_only_merged recall {recall} != 1.0 — missing {sorted(str(x) for x in B - A)}"
    assert precision == 1.0, \
        f"flow_only_merged precision {precision} != 1.0 — extra {sorted(str(x) for x in A - B)}"

    # ── structural invariants + coverage for full_merged ──
    problems = []
    problems += _merge_shape_problems(flow_view, "flow_only_merged")
    problems += _merge_shape_problems(full_view, "full_merged")
    problems += _flow_covered_by_full(flow_view, full_view)
    assert not problems, "merged-view invariants violated:\n" + "\n".join(problems)
