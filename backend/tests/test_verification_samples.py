"""Verification samples — WINDOW / SET_OP / INDIRECT anchors (§8.9, §8.7).

The canonical sample (BDM_ACC_LOAN_INFO_SUP_M.sql) exercises only a subset
of the 16 edge types; §8.9 pins one real-SQL sample per type absent there.
For each pinned row below, asserts that the edge EXISTS — in the closure of
SOME seed of the script (candidate seeds are swept; any seed's closure
counts), or in the UNFILTERED graph for edges no closure admits — and that
its payload `highlight_line` == the pinned anchor (>= 1).

Probe-pinned 2026-08-10 (W1 probe round; the coordinator's read-only probe
team; §8.9 corrected accordingly):

  WINDOW   dialect_test/snowflake_qualify.sql
           order_date@4 → rn@6            anchor 4  (rule 1 — appearance)
           customer_id@3 → rn@6           anchor 3
  SET_OP   tpcds_qualified/86.sql
           union_result@0 → results_rollup@14  anchor 15  (rule 4 — the
           set-op expression's first token; the CTE header line 14 supports
           no rule; §8.9's original "14" was wrong). This edge sits in NO
           seed closure — union_branch VTs are reachable only via SET_OP +
           SUBSET bridges, neither crossed by the field closure walk — so
           it is asserted on the unfiltered graph (full L2, no seed filter).
  WINDOW   tpcds_qualified/86.sql — the 4 rank() inputs, all anchor 15
           (rule 1 — appearance at line 15)
  INDIRECT spider_complex/046_pets_1_s6.sql
           T1.stuid@3 → T1.stuid@3        anchor 3  (endpoint-decided — the
           field's token sits at both endpoints). Sibling self-loops
           (T2.stuid/T2.petid/T3.petid/T3.pettype) all anchor 3.
           CORRELATED is NEVER a relationship — correlated subqueries are
           INDIRECT with operation CORRELATED/CORRELATED_OUT
           (dependency_graph.py:487/495); the CORRELATED_OUT representative
           row is asserted on the unfiltered graph (subquery-interior
           outputs stay outside every field closure).

KNOWN state (probe 2026-08-10): every row's edge EXISTS today. The anchor
assertions need the W5 per-edge payload (`highlight_line`) — until it lands
they fail loudly; that is EXPECTED against in-flight work, not a
regression. Edge-existence rows that ever regress fail immediately.
"""

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.extractor.dependency_graph import build_dependency_graph
from app.services.graph_service import build_graph_data
from app.services.dataflow_service import filter_by_field_flow

TABLE_LIKE = {"table", "view", "cte", "virtual_table", "subquery", "merge_target"}

# ── Pinned expectations (§8.9, probe-pinned 2026-08-10) ────────────────────
# Row: (sample, eid, src, tgt, relationship, anchor, mode)
#   mode "closure"    — edge must exist with the anchor in SOME seed closure.
#   mode "full_graph" — edge exists only in the unfiltered graph
#                       (build_graph_data output / L2 without seed filter).
PINNED_ROWS = [
    # ── WINDOW — snowflake_qualify.sql (rule 1: source field's appearance) ──
    dict(sample="dialect_test/snowflake_qualify.sql", eid="WINDOW-1",
         src=("order_date", 4), tgt=("rn", 6), rel="WINDOW", anchor=4,
         mode="closure"),
    dict(sample="dialect_test/snowflake_qualify.sql", eid="WINDOW-2",
         src=("customer_id", 3), tgt=("rn", 6), rel="WINDOW", anchor=3,
         mode="closure"),
    # ── SET_OP — 86.sql (rule 4: set-op expression's first token, L15) ─────
    dict(sample="tpcds_qualified/86.sql", eid="SET_OP-1",
         src=("union_result", 0), tgt=("results_rollup", 14), rel="SET_OP",
         anchor=15, mode="full_graph"),
    # ── WINDOW — 86.sql (rule 1: appearance at line 15) ────────────────────
    dict(sample="tpcds_qualified/86.sql", eid="WINDOW-3",
         src=("total_sum", 15), tgt=("rank_within_parent", 25), rel="WINDOW",
         anchor=15, mode="closure"),
    dict(sample="tpcds_qualified/86.sql", eid="WINDOW-4",
         src=("g_class", 15), tgt=("rank_within_parent", 25), rel="WINDOW",
         anchor=15, mode="closure"),
    dict(sample="tpcds_qualified/86.sql", eid="WINDOW-5",
         src=("i_category", 15), tgt=("rank_within_parent", 25), rel="WINDOW",
         anchor=15, mode="closure"),
    dict(sample="tpcds_qualified/86.sql", eid="WINDOW-6",
         src=("lochierarchy", 15), tgt=("rank_within_parent", 25), rel="WINDOW",
         anchor=15, mode="closure"),
    # ── INDIRECT — 046_pets_1_s6.sql (endpoint-decided: token at both
    #    endpoints → anchor 3) ──────────────────────────────────────────────
    dict(sample="spider_complex/046_pets_1_s6.sql", eid="INDIRECT-1",
         src=("T1.stuid", 3), tgt=("T1.stuid", 3), rel="INDIRECT", anchor=3,
         mode="closure"),
    dict(sample="spider_complex/046_pets_1_s6.sql", eid="INDIRECT-2",
         src=("T2.stuid", 3), tgt=("T2.stuid", 3), rel="INDIRECT", anchor=3,
         mode="closure"),
    dict(sample="spider_complex/046_pets_1_s6.sql", eid="INDIRECT-3",
         src=("T2.petid", 3), tgt=("T2.petid", 3), rel="INDIRECT", anchor=3,
         mode="closure"),
    dict(sample="spider_complex/046_pets_1_s6.sql", eid="INDIRECT-4",
         src=("T3.petid", 3), tgt=("T3.petid", 3), rel="INDIRECT", anchor=3,
         mode="closure"),
    dict(sample="spider_complex/046_pets_1_s6.sql", eid="INDIRECT-5",
         src=("T3.pettype", 3), tgt=("T3.pettype", 3), rel="INDIRECT", anchor=3,
         mode="closure"),
    # ── CORRELATED_OUT representative (full-graph-only) ────────────────────
    dict(sample="spider_complex/046_pets_1_s6.sql", eid="CORRELATED_OUT-1",
         src=("T1.stuid", 3), tgt=("T1.fname", 3), rel="INDIRECT", anchor=3,
         mode="full_graph"),
]


# ── Pipeline ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def samples():
    """One pipeline per sample script: extract → deps → graph (the level2
    API path; the probe's entrypoints)."""
    out = {}
    for row in PINNED_ROWS:
        p = row["sample"]
        if p in out:
            continue
        sql_text = _load_sample(p)
        result = extract_variables_from_sql(sql_text, p)
        deps = build_dependency_graph(result, sql_text)
        by_id = {v.id: v for v in result.variables}
        analysis = {
            "variables": [v.model_dump() for v in result.variables],
            "dependencies": [d.model_dump() for d in deps],
        }
        graph = build_graph_data(analysis)
        out[p] = (sql_text, result, by_id, graph)
    return out


def _load_sample(rel_path: str) -> str:
    for base in (BACKEND_DIR.parent / "samples", Path("/app/samples")):
        p = base / rel_path
        if p.exists():
            return p.read_text(encoding="utf-8")
    pytest.fail(f"sample not found: {rel_path}")


def _canon_key(var) -> tuple:
    """I1 normalization (same as the benchmark): alias reads map to their
    canonical table (same line)."""
    name = var.name
    line = var.line_start
    if var.variable_type.value in ("column", "aggregate", "transform", "window",
                                   "window_computed"):
        return (name, line)
    if var.source_tables and var.source_tables[0]:
        return (var.source_tables[0], line)
    return (name, line)


def _fmt(key) -> str:
    return f"{key[0]}@{key[1]}"


def _edge_canon_pair(e, by_id):
    """Canonical (src, tgt) endpoint pair of an edge."""
    d = e["data"]
    src, tgt = by_id.get(d["source"]), by_id.get(d["target"])
    if src is None or tgt is None:
        return None
    return (_canon_key(src), _canon_key(tgt))


def _candidate_seeds(result) -> set:
    """(table, field) seed candidates: every column's owner table × its field
    name, plus table-like names (aliases map to their source table)."""
    cands = set()
    for v in result.variables:
        field = v.name.rsplit(".", 1)[-1]
        if v.source_tables and v.source_tables[0]:
            cands.add((v.source_tables[0], field))
        if v.variable_type.value in TABLE_LIKE:
            cands.add((v.name, field))
    return cands


# ── The pinned expectations ───────────────────────────────────────────────

@pytest.mark.parametrize("row", PINNED_ROWS, ids=[r["eid"] for r in PINNED_ROWS])
def test_pinned_edge(samples, row):
    """§8.9 — the pinned edge must exist (in SOME seed closure, or in the
    unfiltered graph) with payload highlight_line == the pinned anchor.

    NOTE: the anchor assertions need the W5 per-edge payload; until it
    lands they fail EXPECTED (written against the spec)."""
    _, result, by_id, graph = samples[row["sample"]]
    target = (row["src"], row["tgt"])
    rel = row["rel"]

    hits = []
    if row["mode"] == "closure":
        for (t, f) in sorted(_candidate_seeds(result)):
            res = filter_by_field_flow(graph, t, f, table_schemas=None)
            for e in res["edges"]:
                d = e["data"]
                if (_edge_canon_pair(e, by_id) == target
                        and d.get("relationship", "").startswith(rel)):
                    hits.append((f"{t}.{f}", d.get("highlight_line")))
    else:  # full_graph — the unfiltered L2 (build_graph_data output)
        for e in graph["edges"]:
            d = e["data"]
            if (_edge_canon_pair(e, by_id) == target
                    and d.get("relationship", "").startswith(rel)):
                hits.append(("<full graph>", d.get("highlight_line")))

    print(f"\n── {row['eid']}: {_fmt(row['src'])} → {_fmt(row['tgt'])} "
          f"({rel}, mode={row['mode']}, anchor={row['anchor']}) ──")
    for seed, hl in hits:
        print(f"  in {seed}: highlight_line={hl}")

    assert hits, (f"{row['eid']}: pinned edge {_fmt(row['src'])} → "
                  f"{_fmt(row['tgt'])} ({rel}) "
                  + ("missing from EVERY seed closure"
                     if row["mode"] == "closure"
                     else "missing from the unfiltered graph"))
    hl = hits[0][1]
    assert hl is not None, (f"{row['eid']}: edge present but payload has no "
                            f"highlight_line (W5 per-edge payload not landed "
                            f"yet — expected until it does)")
    assert hl >= 1, f"{row['eid']}: highlight_line {hl} is a defect (rule: >= 1)"
    assert hl == row["anchor"], (f"{row['eid']}: anchor mismatch — expected "
                                 f"{row['anchor']}, payload {hl}")
