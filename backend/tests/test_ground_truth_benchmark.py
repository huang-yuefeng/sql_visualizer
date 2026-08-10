"""Ground-truth benchmark — BDM_ACC_LOAN_INFO_SUP_M.sql closure bijection.

Asserts the COMPLETE L2 closure of the canonical sample against the formal
definition tools/GROUND_TRUTH_BDM_ACC_LOAN_INFO_SUP.md §8.5 (REQUIREMENTS
R25 item 7): for each of the two closure seeds — `bdm_acc_loan_info` and
`bdm_acc_loan_info_sup`, both on field `data_dt` — the closure's NODES,
EDGES, and per-edge highlight anchors are asserted EXACTLY, both directions
(no missing, no extra):

- Nodes:  bdm seed 16 nodes / sup seed 8 nodes (probe-pinned 2026-08-10;
          includes the ⟐ synthetic VT nodes).
- Edges:  bdm seed 24 edges / sup seed 12 edges — canonical endpoint
          normalization (alias → source table on the same line, `_canon_key`;
          the ALIAS hops E1–E3 map onto the canonical tables, and E1/E2
          become self-loops in canonical space). Compared as MULTISETS so a
          future canonical-pair collision can never mask a missing or extra
          edge.
- Lines:  the 33-entry CANONICAL_EDGE_LINES table (§8.5): every closure edge
          must exist with payload `highlight_line` == its pinned anchor
          (exact, and >= 1). The payload fields (highlight_line / flow_kind /
          reason) are the in-flight W5 work — until they land,
          `test_edge_lines` and `test_payload_integrity` fail EXPECTED
          (written against the spec, not the current payload).
- Pair 18 (`data_dt@225 → bdm_acc_loan_info_sup@223`): KNOWN GAP (Defect 5)
  — asserted ABSENT today; the flip is ONE constant (PAIR18_KNOWN_GAP).

Run:  cd /app/backend && python3 -m pytest tests/test_ground_truth_benchmark.py -v
Each test prints its diff section; assertions fail on any MISSING or EXTRA
canonical item.
"""

import sys
from collections import Counter
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.extractor.variable_extractor_v2 import extract_variables_from_sql
from app.extractor.dependency_graph import build_dependency_graph
from app.services.graph_service import build_graph_data
from app.services.dataflow_service import filter_by_field_flow

SAMPLE = "BDM_ACC_LOAN_INFO_SUP_M.sql"

# ── Pair 18 — KNOWN GAP (Defect 5; extractor fix W2 in flight) ─────────────
# §8.5 pair 18: `data_dt@225 → bdm_acc_loan_info_sup@223` (read, anchor 223).
# It is ABSENT today AND `data_dt@225` is not extracted at all — the
# WHERE-clause read at L225 is mis-stamped 213 (same root cause as the
# duplicate `data_dt@213`; bug list §v3.3.147 addendum 4).
# THE FLIP IS ONE LINE: set PAIR18_KNOWN_GAP = False once the token-run fix
# lands — pair 18 then activates in CANONICAL_EDGE_LINES (anchor 223),
# `test_edge_lines` asserts it, and the sup closure must grow to 9 nodes /
# 13 edges (the integration updates the pinned node set at that point).
# That flip is the integration's job, not the benchmark's.
PAIR18_KNOWN_GAP = True

# ── Canonical spec (§8.5, probe-pinned 2026-08-10) ────────────────────────
# Closure seeds: bdm seed → 16 nodes / 24 edges; sup seed → 8 nodes / 12
# edges (+ pair 18 post-fix). No single seed covers all 33 entries; the
# Seed column states where each entry is asserted.
SEED_TABLE_FIELD = {
    "bdm": ("bdm_acc_loan_info", "data_dt"),
    "sup": ("bdm_acc_loan_info_sup", "data_dt"),
}

# Node sets — RAW (name, line) keys, exactly as the probe lists them (aliases
# p1@29 / p1@84 / p2@199 are distinct closure nodes; no normalization).
BDM_CANONICAL_NODES = {
    ("⟐ subq1", 0), ("⟐ subq", 0), ("⟐ output", 0),
    ("rollover_loan_info", 9), ("bdm_acc_loan_info", 16), ("data_dt", 18),
    ("bdm_acc_loan_info", 29), ("p1", 29), ("p1.data_dt", 43),
    ("loan_final", 64), ("bdm_acc_loan_info", 84), ("p1", 84),
    ("p1.data_dt", 158), ("bdm_acc_loan_info_sup", 160), ("data_dt", 160),
    ("rrcdm_job_log_exec_par", 211),
}

SUP_CANONICAL_NODES = {
    ("⟐ output", 0),
    ("bdm_acc_loan_info_sup", 160), ("data_dt", 160),
    ("p2", 199), ("p2.data_dt", 202),
    ("rrcdm_job_log_exec_par", 211), ("data_dt", 213),
    ("bdm_acc_loan_info_sup", 223),
}

CANONICAL_SINKS = {"bdm_acc_loan_info_sup", "rrcdm_job_log_exec_par"}

# Flow-kind names — the §8.7/§8.8.1 canonical set (label = kind only).
FLOW_KINDS = {"chain", "field flow", "read", "write", "filter",
              "structure", "bridge"}


# ── CANONICAL_EDGE_LINES — the complete 33-entry table (§8.5) ─────────────
# Entry: (seeds, id, canonical_src, canonical_tgt, expected_anchor, rel_hint)
# — one table row per §8.5 entry; `seeds` is the tuple of closure seeds the
# row is asserted on (pairs 11/12/15/16 carry seed "bdm+sup" — ONE row,
# asserted on BOTH closures). rel_hint names the edge's relationship (e.g.
# "ALIAS" for the E1–E3 hops, "SCHEMA" for S1–S5, "TABLE_FLOW" for the pair-11
# SELF_JOIN): with today's probe every canonical endpoint pair is unique, so
# the hint is exact-edge documentation and collision safety — if a future
# change ever collapses two closure edges onto one pair, the hint decides
# which edge's anchor the row asserts.
def _E(seeds, eid, src_name, src_line, tgt_name, tgt_line, anchor, rel=None):
    if isinstance(seeds, str):
        seeds = (seeds,)
    return (seeds, eid, (src_name, src_line), (tgt_name, tgt_line), anchor, rel)


CANONICAL_EDGE_LINES = [
    # ── bdm-only rows (bdm_acc_loan_info.data_dt): pairs 1–10, 13, 14 + E1/E2 + S1–S4 + C1/C2 ──
    _E("bdm", "1", "data_dt", 18, "bdm_acc_loan_info", 16, 18),             # §8.5 #1  field flow (FILTER/REF promoted)
    _E("bdm", "2", "bdm_acc_loan_info", 16, "rollover_loan_info", 9, 16),   # §8.5 #2  chain (TABLE_FLOW promoted)
    _E("bdm", "3", "p1.data_dt", 43, "⟐ subq", 0, 43),                      # §8.5 #3  field flow (FILTER/CONDITION)
    _E("bdm", "4", "bdm_acc_loan_info", 29, "⟐ subq", 0, 29),               # §8.5 #4  chain (p1@29 → FROM hop)
    _E("bdm", "5", "⟐ subq", 0, "⟐ subq1", 0, 26),                          # §8.5 #5  chain (SUBSELECT; VT creation 26)
    _E("bdm", "6", "⟐ subq1", 0, "rollover_loan_info", 9, 22),              # §8.5 #6  chain (SUBSELECT; VT creation 22)
    _E("bdm", "7", "p1.data_dt", 158, "loan_final", 64, 158),               # §8.5 #7  field flow (FILTER/CONDITION)
    _E("bdm", "8", "bdm_acc_loan_info", 84, "loan_final", 64, 84),          # §8.5 #8  chain (p1@84 → FROM hop)
    _E("bdm", "9", "rollover_loan_info", 9, "loan_final", 64, 9),           # §8.5 #9  chain (REFERENCE)
    _E("bdm", "10", "loan_final", 64, "bdm_acc_loan_info_sup", 160, 64),    # §8.5 #10 chain (INSERT)
    _E("bdm", "13", "p1.data_dt", 43, "bdm_acc_loan_info", 29, 29),         # §8.5 #13 READ (read promoted)
    _E("bdm", "14", "p1.data_dt", 158, "bdm_acc_loan_info", 84, 84),        # §8.5 #14 READ (read promoted)
    _E("bdm", "E1", "bdm_acc_loan_info", 29, "bdm_acc_loan_info", 29, 29, rel="ALIAS"),   # bdm@29 → p1@29
    _E("bdm", "E2", "bdm_acc_loan_info", 84, "bdm_acc_loan_info", 84, 84, rel="ALIAS"),   # bdm@84 → p1@84
    _E("bdm", "S1", "bdm_acc_loan_info", 29, "p1.data_dt", 43, 43, rel="SCHEMA"),         # p1@29 → p1.data_dt@43
    _E("bdm", "S2", "bdm_acc_loan_info", 29, "p1.data_dt", 158, 158, rel="SCHEMA"),       # p1@29 → p1.data_dt@158
    _E("bdm", "S3", "bdm_acc_loan_info", 84, "p1.data_dt", 43, 43, rel="SCHEMA"),         # p1@84 → p1.data_dt@43
    _E("bdm", "S4", "bdm_acc_loan_info", 84, "p1.data_dt", 158, 158, rel="SCHEMA"),       # p1@84 → p1.data_dt@158
    _E("bdm", "C1", "rollover_loan_info", 9, "⟐ output", 0, 9),             # §8.5 C1 chain (REFERENCE)
    _E("bdm", "C2", "loan_final", 64, "⟐ output", 0, 64),                   # §8.5 C2 chain (REFERENCE)
    # ── both seeds (bdm+sup): pairs 11, 12, 15, 16 — ONE row, asserted on
    #    each closure (§8.5 Seed column "bdm+sup") ──
    _E(("bdm", "sup"), "11", "bdm_acc_loan_info_sup", 160, "bdm_acc_loan_info_sup", 160, 160, rel="TABLE_FLOW"),  # §8.5 #11 chain (SELF_JOIN)
    _E(("bdm", "sup"), "12", "data_dt", 160, "bdm_acc_loan_info_sup", 160, 160),  # §8.5 #12 field flow (value-write promoted)
    _E(("bdm", "sup"), "15", "⟐ output", 0, "bdm_acc_loan_info_sup", 160, 160),    # §8.5 #15 chain (synthetic, INSERT)
    _E(("bdm", "sup"), "16", "bdm_acc_loan_info_sup", 160, "rrcdm_job_log_exec_par", 211, 211),  # §8.5 #16 write (DML/WRITE_READ)
    # ── sup-only rows (bdm_acc_loan_info_sup.data_dt): pairs 17, 19 + E3/E4 + S5 + B1 + C3/C4 ──
    _E("sup", "17", "data_dt", 213, "rrcdm_job_log_exec_par", 211, 213),    # §8.5 #17 value (value-write promoted)
    _E("sup", "19", "p2.data_dt", 202, "bdm_acc_loan_info_sup", 199, 199),  # §8.5 #19 READ (p2@199; join-key read promoted)
    _E("sup", "E3", "bdm_acc_loan_info_sup", 160, "bdm_acc_loan_info_sup", 199, 160, rel="ALIAS"),  # sup@160 → p2@199
    _E("sup", "E4", "p2.data_dt", 202, "⟐ output", 0, 202),                 # §8.5 E4 JOIN cond
    _E("sup", "S5", "bdm_acc_loan_info_sup", 199, "p2.data_dt", 202, 202, rel="SCHEMA"),  # p2@199 → p2.data_dt@202
    _E("sup", "B1", "bdm_acc_loan_info_sup", 223, "rrcdm_job_log_exec_par", 211, 223),    # §8.5 B1 residual bridge
    _E("sup", "C3", "bdm_acc_loan_info_sup", 199, "⟐ output", 0, 199),      # §8.5 C3 chain (p2@199 → FROM)
    _E("sup", "C4", "bdm_acc_loan_info_sup", 199, "bdm_acc_loan_info_sup", 160, 199),     # §8.5 C4 chain (p2@199 → INSERT)
]
if not PAIR18_KNOWN_GAP:
    # §8.5 pair 18 activates only after the Defect-5 fix (W2) — see the
    # KNOWN GAP block above; the flip is the PAIR18_KNOWN_GAP constant.
    CANONICAL_EDGE_LINES.append(
        _E("sup", "18", "data_dt", 225, "bdm_acc_loan_info_sup", 223, 223))  # §8.5 #18 READ (post-fix, promoted)

# 33 entries = 19 canonical pairs + 4 extras (E1–E4) + 6 SCHEMA/bridge
# (S1–S5, B1) + 4 chain-completeness (C1–C4) → 16 distinct lines (§8.4).
assert len(CANONICAL_EDGE_LINES) == (33 if not PAIR18_KNOWN_GAP else 32), \
    "CANONICAL_EDGE_LINES must be the complete 33-entry §8.5 table"


# ── Pipeline ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pipeline():
    """extract → deps → graph — exactly the level2 API pipeline (the probe's
    entrypoints, /tmp/probe_seed.py: filter_by_field_flow on this graph)."""
    sql_text = _load_sample()
    result = extract_variables_from_sql(sql_text, SAMPLE)
    deps = build_dependency_graph(result, sql_text)
    by_id = {v.id: v for v in result.variables}
    analysis = {
        "variables": [v.model_dump() for v in result.variables],
        "dependencies": [d.model_dump() for d in deps],
    }
    graph = build_graph_data(analysis)
    return sql_text, result, deps, by_id, graph


def _load_sample() -> str:
    for base in (BACKEND_DIR.parent / "samples" / "sql_sample_v1",
                 Path("/app/samples/sql_sample_v1")):
        p = base / SAMPLE
        if p.exists():
            return p.read_text(encoding="utf-8")
    pytest.fail(f"sample not found: {SAMPLE}")


def _canon_key(var) -> tuple:
    """I1 normalization: alias reads map to their canonical table (same line)."""
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


def _closure(by_id, graph, table, field):
    """The L2 search-view closure, exactly as the level2 API computes it."""
    return filter_by_field_flow(graph, table, field, table_schemas=None)


def _closure_nodes(by_id, result) -> set:
    """RAW (name, line) node keys — no alias normalization (the probe lists
    p1@29 and bdm@29 as distinct closure nodes)."""
    out = set()
    for n in result["nodes"]:
        v = by_id.get(n["data"]["id"])
        if v is not None:
            out.add((v.name, v.line_start))
    return out


def _edge_canon_pair(e, by_id):
    """Canonical (src, tgt) endpoint pair of a closure edge."""
    d = e["data"]
    src, tgt = by_id.get(d["source"]), by_id.get(d["target"])
    if src is None or tgt is None:
        return None
    return (_canon_key(src), _canon_key(tgt))


def _closure_edges(by_id, result) -> list:
    """(canonical pair, relationship) per closure edge."""
    out = []
    for e in result["edges"]:
        pair = _edge_canon_pair(e, by_id)
        if pair is None:
            continue
        out.append((pair, e["data"].get("relationship", "?")))
    return out


# ── Nodes bijection ───────────────────────────────────────────────────────

def _assert_nodes(pipeline, seed, expected):
    _, _, _, by_id, graph = pipeline
    res = _closure(by_id, graph, *SEED_TABLE_FIELD[seed])
    got = _closure_nodes(by_id, res)
    missing = expected - got
    extra = got - expected
    print(f"\n── NODE DIFF ({seed} seed, {len(got)} nodes) ──")
    print("  closure:", sorted(_fmt(k) for k in got))
    print("  MISSING:", sorted(_fmt(k) for k in missing))
    print("  EXTRA:  ", sorted(_fmt(k) for k in extra))
    assert not missing, f"[{seed}] canonical nodes missing: {sorted(_fmt(k) for k in missing)}"
    assert not extra, f"[{seed}] extra nodes (bijection violated): {sorted(_fmt(k) for k in extra)}"


def test_nodes_bijection_bdm(pipeline):
    """bdm seed: exact 16-node set — no missing, no extra (probe listing)."""
    _assert_nodes(pipeline, "bdm", BDM_CANONICAL_NODES)


def test_nodes_bijection_sup(pipeline):
    """sup seed: exact 8-node set — no missing, no extra (probe listing)."""
    _assert_nodes(pipeline, "sup", SUP_CANONICAL_NODES)


# ── Edges bijection ───────────────────────────────────────────────────────

def _expected_pairs(seed) -> Counter:
    """Expected canonical endpoint pairs of one seed's closure — the multiset
    over every §8.5 row asserted on that seed (shared bdm+sup rows count on
    both)."""
    out = Counter()
    for (seeds, eid, cs, ct, anchor, rel) in CANONICAL_EDGE_LINES:
        if seed in seeds:
            out[(cs, ct)] += 1
    return out


def _assert_edges(pipeline, seed):
    _, _, _, by_id, graph = pipeline
    res = _closure(by_id, graph, *SEED_TABLE_FIELD[seed])
    got = Counter(pair for pair, _ in _closure_edges(by_id, res))
    expected = _expected_pairs(seed)
    missing = expected - got
    extra = got - expected
    print(f"\n── EDGE DIFF ({seed} seed, {sum(got.values())} edges) ──")
    print("  canonical pairs (multiset):")
    for (cs, ct), n in sorted(expected.items()):
        mark = "OK " if got.get((cs, ct), 0) == n else "DIFF"
        print(f"    [{mark}] {n}x {_fmt(cs)} → {_fmt(ct)}  (closure: {got.get((cs, ct), 0)})")
    print("  MISSING:", [f"{n}x {_fmt(a)} → {_fmt(b)}" for (a, b), n in missing.items()] or "—")
    print("  EXTRA:  ", [f"{n}x {_fmt(a)} → {_fmt(b)}" for (a, b), n in extra.items()] or "—")
    assert not missing, f"[{seed}] canonical edges missing: {dict(missing)}"
    assert not extra, f"[{seed}] extra edges (bijection violated): {dict(extra)}"


def test_edges_bijection_bdm(pipeline):
    """bdm seed: exactly the 24 canonical edges (multiset) — no missing, no extra."""
    _assert_edges(pipeline, "bdm")


def test_edges_bijection_sup(pipeline):
    """sup seed: exactly the 12 canonical edges (multiset) — no missing, no extra."""
    _assert_edges(pipeline, "sup")


# ── Per-edge highlight lines (§8.5 assertion spec) ────────────────────────

def _check_entry(entry, by_id, graph):
    """§8.5 assertion spec per entry: (a) the edge EXISTS in the closure
    (canonical endpoints; rel_hint disambiguates colliding pairs); (b) its
    payload highlight_line == the expected anchor — exact match required, a
    fallback line FAILS as a solution defect; (c) highlight_line >= 1 (line 0
    is a defect)."""
    seeds, eid, cs, ct, anchor, rel_hint = entry
    for seed in seeds:
        res = _closure(by_id, graph, *SEED_TABLE_FIELD[seed])
        matches = [e for e in res["edges"] if _edge_canon_pair(e, by_id) == (cs, ct)]
        if rel_hint:
            matches = [e for e in matches
                       if e["data"].get("relationship", "").startswith(rel_hint)]
        assert matches, (f"{seed}:{eid} — edge {_fmt(cs)} → {_fmt(ct)} MISSING from "
                         f"the {seed} closure")
        if not rel_hint:
            assert len(matches) == 1, (f"{seed}:{eid} — {len(matches)} closure edges "
                                       f"share canonical pair {_fmt(cs)} → {_fmt(ct)}; "
                                       f"add a rel_hint")
        d = matches[0]["data"]
        hl = d.get("highlight_line")
        assert hl is not None, (f"{seed}:{eid} — edge exists but payload has no "
                                f"highlight_line (W5 per-edge payload not landed yet)")
        assert hl >= 1, f"{seed}:{eid} — highlight_line {hl} is a defect (rule: >= 1)"
        assert hl == anchor, (f"{seed}:{eid} — anchor mismatch: expected {anchor}, "
                              f"payload {hl} (a fallback line fails as a solution defect)")


@pytest.mark.parametrize("entry", CANONICAL_EDGE_LINES,
                         ids=["+".join(s) + ":" + eid
                              for (s, eid, *_r) in CANONICAL_EDGE_LINES])
def test_edge_lines(pipeline, entry):
    """§8.5 — the complete 33-entry CANONICAL_EDGE_LINES: per row, on that
    seed's closure the edge EXISTS and its payload highlight_line == the
    expected anchor (>= 1). NOTE: fails until W5 (per-edge payload) lands —
    expected, the spec is the contract."""
    _, _, _, by_id, graph = pipeline
    _check_entry(entry, by_id, graph)


def test_pair18_known_gap(pipeline):
    """Pair 18 — KNOWN GAP (Defect 5, fix W2 in flight): asserted ABSENT.

    Edge `data_dt@225 → bdm_acc_loan_info_sup@223` absent AND the
    `data_dt@225` var not extracted (L225's WHERE read is mis-stamped 213).
    THE FLIP IS ONE LINE: set PAIR18_KNOWN_GAP = False above — pair 18 then
    activates in CANONICAL_EDGE_LINES and is asserted by test_edge_lines.
    """
    _, result, _, by_id, graph = pipeline
    if PAIR18_KNOWN_GAP:
        res = _closure(by_id, graph, *SEED_TABLE_FIELD["sup"])
        pairs = {pair for pair, _ in _closure_edges(by_id, res)}
        gap_edge = (("data_dt", 225), ("bdm_acc_loan_info_sup", 223))
        var_lines = {v.line_start for v in result.variables}
        print("\n── PAIR 18 — KNOWN GAP (Defect 5, fix W2 in flight) ──")
        print(f"  edge {_fmt(gap_edge[0])} → {_fmt(gap_edge[1])} present: "
              f"{gap_edge in pairs} | var at L225 present: {225 in var_lines}")
        assert gap_edge not in pairs, (
            "pair 18 edge present?! — the extractor fix (W2) landed: flip "
            "PAIR18_KNOWN_GAP = False and let the integration update the "
            "sup node/edge sets")
        assert 225 not in var_lines, (
            "var at L225 present?! — the extractor fix (W2) landed: flip "
            "PAIR18_KNOWN_GAP = False and let the integration update the "
            "sup node/edge sets")
    else:
        # Post-fix state: pair 18 must be present with the exact anchor (223)
        # — test_edge_lines already covers it via CANONICAL_EDGE_LINES;
        # this branch is the flip's gate.
        _check_entry(_E("sup", "18", "data_dt", 225,
                        "bdm_acc_loan_info_sup", 223, 223), by_id, graph)


# ── Payload integrity (R25 / §8.7 / §8.8) ─────────────────────────────────

def test_payload_integrity(pipeline):
    """Every edge in BOTH closures carries highlight_line >= 1, a flow_kind
    from the §8.7 canonical set, and a reason string starting with
    '<kind> — ' (§8.8.3 format). NOTE: W5 (per-edge payload) is in-flight in
    parallel — this test fails until it lands; that failure is EXPECTED,
    not a regression (written against the spec)."""
    _, _, _, by_id, graph = pipeline
    bad = []
    for seed, (table, field) in SEED_TABLE_FIELD.items():
        res = _closure(by_id, graph, table, field)
        for e in res["edges"]:
            d = e["data"]
            pair = _edge_canon_pair(e, by_id)
            hl = d.get("highlight_line")
            kind = d.get("flow_kind")
            reason = d.get("reason")
            ok = (isinstance(hl, int) and hl >= 1
                  and kind in FLOW_KINDS
                  and isinstance(reason, str)
                  and reason.startswith(f"{kind} — "))
            if not ok:
                bad.append((seed, _fmt(pair[0]) if pair else "?",
                            _fmt(pair[1]) if pair else "?",
                            d.get("relationship"), hl, kind, reason))
    print("\n── PAYLOAD INTEGRITY (both closures) ──")
    for row in bad:
        seed, s, t, rel, hl, kind, reason = row
        print(f"  [{seed}] {rel} {s} → {t}: highlight_line={hl} flow_kind={kind!r} "
              f"reason={reason!r}")
    assert not bad, (f"{len(bad)} closure edges fail the §8.7/§8.8 payload "
                     f"contract (W5 payload work not landed yet — expected "
                     f"until it does): {len(bad)} edge(s), first: {bad[0]}")


# ── Sinks ────────────────────────────────────────────────────────────────

def test_sinks(pipeline):
    """Both closures end at the same two sinks (unchanged contract)."""
    _, _, _, by_id, graph = pipeline
    for seed, (table, field) in SEED_TABLE_FIELD.items():
        res = _closure(by_id, graph, table, field)
        names = {by_id[n["data"]["id"]].name for n in res["nodes"]
                 if by_id.get(n["data"]["id"]) is not None}
        missing = CANONICAL_SINKS - names
        print(f"\n── SINKS ({seed} seed) ──")
        print("  found:", sorted(CANONICAL_SINKS & names),
              "| missing:", sorted(missing))
        assert not missing, f"[{seed}] sinks missing: {missing}"


# ── Verdict ──────────────────────────────────────────────────────────────

def test_global_sanity(pipeline):
    """Extraction invariants the benchmark depends on.

    NOTE: variable/dependency COUNTS are deliberately NOT asserted — they are
    snapshots that legitimately change when extraction rules change. The old
    253-vars / 737-deps pin was dropped for exactly this reason: treat any
    count delta as a finding to classify (solution bug vs snapshot update),
    never as an automatic failure. Only true invariants are asserted:
    parse_errors == [] (the canonical sample must parse), and the closure
    node/edge counts pinned by the §8.5 table (asserted by the bijection
    tests above).
    """
    _, result, deps, _, _ = pipeline
    assert result.parse_errors == []
    print("\n── GLOBAL ──")
    print(f"  vars={len(result.variables)} deps={len(deps)} "
          f"parse_errors={result.parse_errors} (counts are snapshots — "
          f"not asserted)")
    print("VERDICT: closure bijection asserted per test above")
