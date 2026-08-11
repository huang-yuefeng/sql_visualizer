# Code Review — v3.3.148 (round 11, open issues only)

> **Reviewed:** 2026-08-11 | **Version:** VERSION `3.3.148` | **HEAD:** `3590bcc` (working tree CLEAN)
> **Scope:** delta `28d8210..3590bcc` (v3.3.147 → v3.3.148): `lineage.py` +34, `variable_extractor_v2.py` +38, `l2_builder.py` +55/−, `cache_keys.py` +2, new Jaccard benchmark (+240/+286/+174), old ground-truth benchmark **deleted** (−454), orphan test cleanup, docs +48.
> **Reviewer:** Codex (read-only — no source modified) via 2 sub-agents: Euclid (code delta + closure re-probes), McClintock (tests/docs + test runs).
> Round-10 wiki replaced below: fixed items removed, open ones carried over + new v3.3.148 findings.

## Resolved since round 10 (verified behaviorally)

- **RC-1 closure explosion — behavioral fix**: walker gating in `lineage.py` (`REF/READ` walked field→holder only) → closures drop 70/66/66/85 → **10/5/5/18** (bdm data_dt 18, sup data_dt 10, charge_department/lending_ref 5). Flood gone.
- **hl=0 CONCAT edges — fixed**: `variable_extractor_v2.py:1506-1523,2294-2311` — all 7 JOIN-ON CONCAT exprs now carry real def-site lines (41/117/135/135/139/139/150); probe: 488 L2 edges, **0 with highlight_line=0**; 0 line-0 nodes.
- **Bug-31 — fixed**: SCHEMA-edge output-table-field bulk-copy pass deleted (`l2_builder.py:1077-1120`); L2 builds clean (14/7/7/24 edges).
- **RC-2 fixture path + pair 18 — fixed**: new benchmark builds A via the **served path** `_build_l2_graph("bench", …)` (not the raw graph); pair 18 is in canonical B and matched (anchor 223).
- **Orphan `sql_range_finder` imports — swept**: `test_filter_andor.py` deleted; `test_l1_l2_integration.py` orphan import + `test_sql_range_indented_column` removed; no `.py` import remains (only a docstring comment + stale `.pyc`). Collection fixed.
- **Cache prefix consistent**: `cache_keys.py` → `graph_3_2_20`; `test_c_index_pipeline.py` assertion matches (passed before the env hang).

---

## Open issues

### High

1. **D2 — WRITE_READ still field-blind** (`lineage.py:693`; `models/variable.py:120-127`). Forward DML admit remains unconditional (`admit = fwd or …`); only the backward VALUE admit is `_field_part`-gated (:694-697). Probe: `rrcdm_job_log_exec_par` is still in the `(bdm_acc_loan_info_sup, charge_department)`=5 and `lending_ref`=5 closures even though stmt2 references neither field (in `data_dt` closures its presence is legitimate but enters via the same blind admit, not field-aware routing). **Fix**: add a `read_fields` carrier on `VariableDependency` (or gate forward DML admit on `target_field` being referenced in the reader statement); never field-blind admit.
2. **Benchmark gate weakened — Jaccard floors < 1.0, live run sits exactly at floor** (`test_jaccard_benchmark.py`). `FLOORS = {bdm: nodes 1.0, edges 0.80, highlights 0.9231; sup: nodes 0.90, edges 0.7333, highlights 0.8571}`; live: bdm N=1.0000 E=0.8000 H=0.9231 │ sup N=0.9000 E=0.7333 H=0.8571 — **every value == floor, zero margin**. Passes despite: row-11 self-loop unmatched on both seeds; bdm A=24 vs B=21 edges (20 matched); sup A=14 vs B=12 (11 matched); sup 2 orphan `data_dt` nodes + duplicate `⟐ output` VT; extra hl lines 213 (bdm) / 225 (sup). All would have failed the old exact bijection. Highlights are compared set-based on distinct lines, not per-edge — an anchor drift passes if the line exists elsewhere. **Fix**: floors = 1.0 at least on nodes; add a per-edge anchor regression check (matched rows already require `hl == anchor`); assert the "16 distinct lines" invariant.
3. **RC-1 contract half remains** — no shared walkable-set constant between `dependency_graph.py` (still re-types SUBSET→REF/READ at :735-763) and `lineage.py` (`FIELD_LAND` only at :410); no cross-layer invariant test (new benchmark imports no `FIELD_LAND`/semantics constant). The fix compensates in the walker instead of Option-A (keep structural bridges non-walked + `STRUCTURAL` exclusion). This is why D2/E1/E2 (the other contract items) are still open. **Fix**: single-source the walkable/structural edge-type sets; add an invariant test that graph re-typing never promotes structural edges into walkable types.

### Medium

4. **N8 — parse_errors still dead end-to-end** (`adapter.py:132-146`; `dataflow_service.py:382`; `l2_builder.py:142`). Runtime-probed: `"parse_errors" in run_full_analysis_result == False` → consumers always `[]`; frontend banner inert. **Fix**: add `"parse_errors": [dict(e) for e in extract_result.parse_errors]` to the adapter return dict (+ unit test with a deliberately broken statement).
5. **N11 — `int()` ValueError still unguarded** (`l2_builder.py:659-660`; `highlight_strategies.py:91-92`). `int(x or 0)` guards only None; no try/except anywhere in the delta. **Fix**: `try: int(x) except (TypeError, ValueError): 0` + malformed-cache unit tests (`_src_line="abc"`).
6. **E1 — 1c-direct cross-statement CTE gate still missing** (`dependency_graph.py:258-266`): statement-level branch checks only `(tbl_var.context or "TOP") != stmt` (:262), never `src.context` (mirror gate exists only in the body-CTE branch :257). **Fix**: add `if (src.context or "TOP") != stmt: continue`.
7. **E2 — 1c-cross no time/line-order guard** (`dependency_graph.py:181-229`): `_add_edge(…, "DML", "WRITE_READ")` at :229 still has no `line_start` order guard → write-after-read phantom edges. **Fix**: skip when writer line_start > reader line_start.

### Low

8. **Cache bump `3_2_20` undocumented** (`cache_keys.py:43`): constant changed but the docstring still ends at the v3.3.145/3_2_19 entry (:40-42); justified by EXTRACTOR_VERSION 2026-08-08.1 → 2026-08-10.1 (`variable_extractor_v2.py:34`) but the comment claims nothing. **Fix**: add the 3_2_20 entry.
9. **`test_jaccard_benchmark.py` hardcodes `/app/samples/...`** — no repo-relative fallback (the old `_load_sample()` had one) → fails outside the container (`FileNotFoundError`). **Fix**: `Path(__file__)`-relative samples lookup.
10. **`jaccard_canonical.py` is a hardcoded oracle** — 31 `CANONICAL_ROWS`/33 `CANONICAL_EDGES` (21 bdm + 12 sup) never read from the .md at runtime; docstring count "22/13" stale (real 21/12). **Fix**: load from the .md or assert equality (round-9 L2 advice, still open).
11. **`_jaccard_selfverify.py` is an orphan manual harness** — `main()` under `__main__` only, zero references (grep empty; `_`-prefixed not collected). **Fix**: wire into CI or delete.
12. **`tools/run_benchmark.sh:8` + `GROUND_TRUTH…md:304,401` still invoke the DELETED `test_ground_truth_benchmark.py`** → loop script broken. **Fix**: repoint to `test_jaccard_benchmark.py`.
13. **`GROUND_TRUTH…md §8.5` stale** — still describes the deleted `test_edge_lines` + `PAIR18_KNOWN_GAP` (~:812-822); counts at :827/:829 say "16 nodes / 22 edges" and "9 nodes / 13 edges" (machine B is 21/12); Jaccard metric/FLOORS documented nowhere (only in the test docstring). **Fix**: rewrite §8.5 assertion spec to the Jaccard contract.
14. **`test_l1_l2_integration.py` 5 pre-existing failures** (reproduced identically against 28d8210 code — not caused by this delta, but block "tree green"): `test_l1_lineage_pairs_stg_customers`/`test_l1_pairs_covered_by_table_fields` (L1 field flood: extra pairs `('crm_customers','region')` etc.), `test_l2_phases_compose_to_same_graph` (edge `highlight_line` 5 vs 2 / reason endpoints), `test_d2_…`/`test_data_dt_…` (`AttributeError: module 'app.services.l2_builder' has no attribute '_compute_highlight_ranges'` — never existed). **Fix**: update or delete the stale assertions.

---

## Test results (v3.3.148)

| Scope | Result |
|---|---|
| `test_jaccard_benchmark.py` | 1 passed (with path shim; hardcoded `/app` path otherwise) |
| `test_c_index_pipeline.py` | 24/34 then hang — `asyncio.to_thread` py3.14 sandbox (environmental, unchanged) |
| `test_l1_l2_integration.py` | 9 passed / 5 failed (pre-existing, see #14) |
| `test_filter_andor.py` | deleted (orphan sweep) |
| Closure probes | 253 nodes / 781 edges; `(sup,data_dt)`=10, `(bdm,data_dt)`=18, charge_department/lending_ref=5; 0 line-0 edges |

## Priority advice (no source modified)

1. **D2 (#1)** — the last correctness leak in the strict walker; the `read_fields` carrier is the clean fix (also closes the "every closure contains rrcdm" objection).
2. **Benchmark ratchet (#2/#9/#10)** — floors to 1.0 on nodes, per-edge anchor check, repo-relative path, oracle from the .md; otherwise v3.3.149 can regress silently.
3. **Finish the contract (#3)** — shared walkable-set constant + invariant test (prevents D2/E1/E2 class of issues recurring).
4. **One-liners (#4/#5/#6/#7/#8)** — N8 adapter, N11 try/except, E1/E2 gates, cache comment.
5. **Docs/scripts (#12/#13)** — repoint `run_benchmark.sh`, rewrite §8.5 to the Jaccard contract; sweep `test_l1_l2_integration` stale tests (#14).

## Verification method

- 2 sub-agents in parallel (Euclid: code delta + 4 closure re-probes + per-item verdicts; McClintock: tests/docs, ran the Jaccard/c_index/l1_l2 suites with a path shim), plus main-thread git scoping.
- No source files modified.
