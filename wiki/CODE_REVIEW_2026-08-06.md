# Code Review — C-series/B-series Implementation (SQL Data Flow Visualizer)

> **Reviewed:** 2026-08-06 (round 4) | **Version:** v3.3.137, HEAD `03827a0` + **uncommitted working tree** (C-series/B-series implementation, ~820 insertions / 10 files + new `test_c_index_pipeline.py` 541 L)
> **Subject:** review of the new source code implementing the C-series (P1-1…P3-13) and B-series (L2 field-explosion) solution designs.
> **Reviewer:** Codex (read-only — no source modified) via 3 parallel sub-agents: Zeno (index pipeline), Wegener (extractor+lineage), Jason (L2+service+deploy). Tests run with `/tmp/r19venv` (fastapi 0.136.3 available).

## Overall verdict

Implementation is largely faithful and several round-3 warnings were correctly handled (C-9 fixed at the right layer, C-13b via token-index, C-7 nit fixed, B-Phase-2 circularity broken). **However the working tree is currently RED against the repo's own tests (≥5 regressions)** and 3 design items are only partially implemented (C-4 apply-side gate, C-5↔C-3 ordering, C-3 per-cache counters).

---

## ✅ Correctly implemented (verified empirically)

| Item | Evidence |
|---|---|
| **C-1** CTAS→script | `classify_sql_text` checks `kind==TABLE and expression is not None` before kind-set (`folder_index_service.py:69-75`); verified on sqlglot 30.8.0 — no false positives (plain CT / LIKE → schema; VIEW untouched) |
| **C-9** extractor-layer dedup (round-3 top warning) | `_add` key now `(name, type, context)` with `TOP{stmt_idx}` contexts (`variable_extractor_v2.py:419-421,633`); **empirically `SUM(x) AS total; SUM(y) AS total` → 2 vars (was 1)**; `stmt_idx` carried into graph JSON (`graph_service.py:100-117,192-198`) |
| **C-13(a)** parse-once reuse | mysql parse reused for classification + star detection (`folder_index_service.py:258-280,383-389,402`); SET-preamble DDL semantics preserved (still "script"); tests assert single parse |
| **C-13(b)** anchor rewrite (round-3 false-sqlglot-premise avoided) | no `expr.start/end` used; **first-token position index** + subsequence fallback (`variable_extractor_v2.py:479-491,568-605`) — exactly the suggested alternative; semantics-preserving (anchor-index == linear-scan test passes) |
| **C-7** deploy guard nit fixed | reset advice gated `FETCH_OK && BEHIND>0 && AHEAD==0` (`target_deploy.sh:88-101`); missing `RELEASE.txt` → red error + `exit 1` (:63-64); `bash -n` OK |
| **C-10** second analysis eliminated | graph cache written on miss with `format_version=3` (`dataflow_service.py:359-363`, `l2_builder.py:108-122`); not_in_flow rebuild is now a cache hit; highlight flood correctly left as deliberate (round-3 diagnosis) |
| **B-Phase 2** join-key expression nodes + circularity broken | expressions materialized (`variable_extractor_v2.py:1019-1103`), `JOIN_KEY` edges (`dependency_graph.py:385-399`), expression JOIN partners admitted unconditionally (`lineage.py:273`); on-sample R 112→65, constants gone, 6 CONCAT key parts kept |
| **C-2(b)** L2 miss path from S4b-mutated analysis cache | `l2_builder.py:108-122` + `dataflow_service.py:338-362` read `analysis_{key}.json` (S4b-mutated), fall back to `run_full_analysis`, write `format_version=3` |

---

## ⚠️ Partial / flawed

| Item | Issue | Evidence |
|---|---|---|
| **C-4** | **Apply-side `n_attributed>0` gate NOT implemented** — persisted `resolved_by["schema"] += 1` still gated only on `field in ul` (M13 context-mismatch still mutates persisted counters). Only revoke side has `n_revoked>0` gate. Becomes load-bearing since C-2(b) makes analysis caches the L2 source | `folder_index_service.py:1099-1106` vs :732-734, :1176 |
| **C-5** | Star expansion runs **after** C-3 revocation → can resurrect revoked/ambiguous fields into `field_index`; search finds scripts the resolution report marks ambiguous | `folder_index_service.py:748-781` |
| **C-3** | **Multi-script counter drift**: `field not in ul` guard is global but `resolved_by["schema"]` is per-cache → revoking 2 scripts decrements only the first; cross-run sweep only covers fields absent from current `field_index` (prior-run caches keep stale attribution); cross-run fields never added to `extractor_unresolved` | `folder_index_service.py:1125-1198`, :687-711 |
| **B3** | Parent fallback `_resolve_scope_parent` works layer-wise (SCHEMA-neighbor confirmed unreachable) and removes all `<NOPARENT>`, but p2 columns land on the **first of 7 same-named "p2" nodes** or the enclosing CTE — "no floating" but wrong/context-unstable parenting; rule-1 (subquery-context match) effectively dead for derived tables | `l2_builder.py:208-240,379-386` |
| **B5** | `⟐ ` prefix stripped → **`⟐ output` becomes `output`, breaking the pinned renderer contract** (2 integration tests assert `'⟐ output'`); also creates 7 duplicate "p2" table labels; query_output rename-to-target not implemented | `l2_builder.py:330-336` |
| **C-9 vs B-series conflict** | per-statement dedup re-creates same-name fields (2 `lending_ref` on sample; 4 `total` in a 2-stmt mini-script) — partially reverses B-series field-reduction; no acceptance threshold test | `l2_builder.py:418-419,470-471` |
| **B-Phase 1** | shipped **global SUBSET exclusion** (`always_bidir: False`, `lineage.py:46`) instead of the designed type-set stopgap — calibrated on one script; any node reachable *only* via SUBSET bridge is silently pruned; residual false-negative: `accu.vlookup_key_value` absent from R; 2/8 sample join expressions got no pair (string-match pairing brittle, `variable_extractor_v2.py:1096-1101`) | `lineage.py:46,79-82,273` |

---

## 🔴 Test regressions (working tree is RED)

| Suite | Result |
|---|---|
| `test_l1_l2_integration.py` | **3 failed / 7 passed** (10 passed at HEAD) — B5 `⟐ output` ×2, C-2(a) graph-cache deletion ×1 |
| `test_s4b_resolution.py` | **2 failed** — `test_m13_cache_attribution_context_scoped` (C-9 `TOP{idx}` context change), `test_a1_ddl_only_sql_is_schema_evidence_not_script` (C-2(a) deletes graph caches) |
| `test_l2_table_dedup.py` | 6 passed ✅ |
| extractor/lineage/dependency scope | 106 passed ✅ |
| new untracked B-series suites (anchor/join_keys/l2) | 21 passed ✅ (but **untracked** — must be committed) |
| `test_c_index_pipeline.py` (32 new) | hangs in sandbox (env: `asyncio.to_thread` never resolves under Python 3.14/bwrap; `_persist_search_view` await) — **32/32 pass with `to_thread` stubbed**; CI must pin a working Python (e.g. 3.12) |

---

## 📌 Other findings

- `test_l2_table_dedup.py:133` references **`test_b_series_c9.py` which does not exist** → C-9 / C-2(b) / C-10 have zero real automated coverage.
- New B-series test files (`test_b_series_anchor.py`, `test_b_series_join_keys.py`, `test_b_series_l2.py`) are **untracked** — commit with the feature or coverage is lost.
- Index-time graph precompute is now **dead work** (build → write → delete every index run; `precomputed_count` still reports 1) — `folder_index_service.py:475-486`.
- Deploy still blocked: repo VERSION 3.3.137 vs `docker_image/RELEASE.txt` 3.3.134 (pre-existing guard exits 1; `release.sh` must regenerate pieces first).
- Stale annotation `variable_extractor_v2.py:448` (`set[tuple[str,str]]` — keys are now 3-tuples).
- C-9 context rename `TOP`→`TOP{idx}` changes node identity (2 `⟐ output` VTs per script, per-statement `_seen` scoping); consumers using `context == "TOP"` break — mitigated by `GRAPH_CACHE_PREFIX` bump to `3_2_17` (`cache_keys.py:32`).
- Anchor silent-0 remains: rendered head not literally in original stream yields `line=0` without loud failure (same as pre-change; docstring overstates).

---

## Priority actions (advice only — no source modified)

1. **B5 label collision**: keep the `⟐` marker (or type-scope disambiguation) for output/duplicate labels — unblocks 2 integration tests.
2. **Re-scope the 2 C-2(a) graph-cache tests** to the analysis-cache path (assert same pairs from the S4b-mutated cache instead of `graph_*.json` presence).
3. **C-4 apply-side gate**: gate persisted `resolved_by["schema"] += 1` + unresolved-drop on `n_attributed > 0` in `_apply_s4b_cache_update`.
4. **Order C-5 before C-3 revocation** (or exclude revoked/ambiguous fields from expansion).
5. **C-3 per-cache counters**: move the membership guard into each script's cache (per-cache `ul`), not a shared set.
6. **Commit untracked B-series tests**; add real tests for C-9 split, C-2(b) miss path, C-10 single-analysis counter.
7. Re-measure L2 field count on the **other** `sql_sample_v1` scripts before trusting the ≤35 bar (global SUBSET exclusion is calibrated on one script).

## Verification method

- 3 sub-agents in parallel, each verifying the working-tree diff against the C/B-series designs and round-3 advice; empirical probes (C-9 two-statement extract, sqlglot 30.8.0 behavior, B-series R measurement on `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql`).
- Tests: `test_l2_table_dedup` 6✅, `test_l1_l2_integration` 3❌/7✅, `test_s4b_resolution` 2❌, extractor/lineage 106✅, untracked B-series 21✅; `test_c_index_pipeline` 32✅ (stubbed) / env-hang real.
- Note: `asyncio.to_thread` hangs under this sandbox's Python 3.14 (environmental; minimal repro confirmed) — not a C-series code defect.
