# Code Review — v3.3.145 (round 8, open issues only)

> **Reviewed:** 2026-08-08 | **Version:** VERSION `3.3.145` | **HEAD:** `1750423` (clean tree; "Ground truth v2 + benchmark test")
> **Scope:** `git diff 85aac05..1750423` — v3.3.145 I1–I5 implementation + display module + parse-errors banner + highlight strategies + ground-truth benchmark + docs (+1985/−173, 27 files)
> **Reviewer:** Codex (read-only — no source modified) via 3 sub-agents: Ohm (end-to-end dead-ends), Faraday (old-advice re-verify), Sagan (docs) + main-thread probes.
> ⚠️ Round-7 wiki (committed by the team in `849f032`) replaced below; fixed items removed, only open/new issues kept.

## Resolved since round 7 (removed from open list)

- **N1** HEAD un-buildable without untracked `highlight_strategies.py` → **FIXED** (committed `c9b35bd`; fresh `git archive` checkout imports OK).
- **B3 / N3** parentless-field regression → **FIXED** (`test_b3_zero_parentless_fields` passes at HEAD; CTE-body + `⟐ subq` container attribution added).
- **N2** pinned-test breaks → **FIXED** (`test_dependency_count` anchor → 649; `test_same_table_4_contexts_single_node` re-scoped; both pass).
- **N7** I5 containment dead end-to-end → **FIXED** (`adapter.py:177`, `graph_service.py:243`, consumed `lineage.py:414-424,570,688`; 10 sample edges carry `containment:true`; cache bumped `3_2_19`).
- **N12** `tools/HIGHLIGHT_REVIEW_SAMPLE.sql` unreferenced → **FIXED** (consumed by `tests/test_i1_definition_lines.py:70,89,108`).
- **N10** cache-bump comment "pickers deleted" false → **FIXED** (`_pick_scope_candidate`/`_scope_distance`/`_resolve_scope_parent` genuinely gone; grep clean).
- Alias/DML stmt_idx sync, and cache-prefix docs in `CLAUDE.md:31/148` (→ `3_2_19`) → **FIXED**.

---

## Open issues

### High

1. **C-3 — cross-run stale caches (still open, unchanged since round 6).** `folder_index_service.py:687` adds `_f` to `extractor_unresolved` only inside `if _fdata:`; the cross-run branch `:694-698` (`else` → glob `analysis_*.json` → `_revoke_s4b_cache_update`) **never re-adds the field**, so the R20 orphan report (`:818-821`, gate `fname in extractor_unresolved`) omits it. Analysis cache key `:408` is `md5(rel_path + sql_text)` with **no run/config discriminator**; revocation matches by `name` only (`:1165-1177`). → Fix: add the field in the cross-run branch (or surface revoked fields separately); include `extractor_version` in the key.

2. **N8 — A3 `parse_errors` still dead end-to-end (one-line gap).** Extractor records it (`variable_extractor_v2.py:274,436`) and the frontend banner is fully wired (`frontend/src/DataFlowApp.jsx:45,95,629-633`; built bundle renders "⚠️ SQL parse error…"), but `adapter.run_full_analysis` return dict (`adapter.py:130-145`) **never copies `parse_errors`** → `dataflow_service.py:384` / `l2_builder.py:156` `result.get("parse_errors", [])` always `[]` → the banner can never fire. → Fix: add `"parse_errors": [dict(e) for e in extract_result.parse_errors]` to the adapter return dict.

### Medium

3. **D1/D2 — line anchoring still incomplete.** `sql_line_mapper.py:54,84` still write `(0,0)` placeholders; probe: **19/253 vars line-0** (12 `virtual_table` synthetic by design + 7 `CONCAT(...)` join-key expressions — unchanged since round 7). Unguarded consumers still assume `line_start ≥ 1`: `routers/variables.py:33-34,59-60`, `sql_highlight_service.py:47-49` (appends `[0,0]`), `export_config_service.py:160,203`, `sql_snippet_service.py:64-65,122`. Only the L2 highlights path is guarded (`highlight_strategies.py:51-55`). → Fix: guard every consumer; anchor the 7 CONCAT join-key vars via I1 def-site runs.

4. **I4 `alias_of` not serialized (latent).** `adapter._var_to_dict` (`adapter.py:147-164`) omits `alias_of`; only `containment` is copied (`:177`). The exact-alias edge works in-memory (`dependency_graph.py:194-199`) but cached analysis dicts lose the field. → Fix: add `"alias_of": v.alias_of` to `_var_to_dict`.

5. **Duplicate display labels (non-alias).** Aliases get `@line` disambiguation, but non-alias VT/subquery intermediates still collide (292-node L2 probe): `p2`×2, `output`×2, `accu`×2, `branch`×2, `p4`×2 (e.g. `⟐ output` in TOP0 vs TOP1; subquery `accu` vs VT `⟐ accu` in the same context). → Fix: extend the `@line`/context suffix (`l2_builder.py:364` display-label path) to non-alias intermediates.

6. **Join-key pairing name-brittle.** `variable_extractor_v2.py:1433,1438` pair join keys by rendered name only (`by_name.setdefault(v.name, v)` first-var-wins); sample still yields **2 mutual JOIN 2-cycles (4 directed edges)** — `CONCAT(a.iidcptl,…) ↔ CONCAT(b.ihdcptl,…)` and `CONCAT(c.ibctcd,…) ↔ CONCAT(b.ihctcd,…)` in `CTE{loan_final}:join:p4`. → Fix: pair by the underlying comparison-node id/line, dedupe by source-column set.

### Low

7. **C-5 — exclusion case-sensitivity.** `folder_index_service.py:755,765` — `_c in _star_excluded` exact-match, no `.lower()`; evidence columns are original-case (`:955-956`), unresolved names are `v.name` original-case. A case-variant mismatch resurrects a revoked field via star expansion. → Fix: normalize both sides.

8. **C-4 — in-memory/persisted divergence.** `folder_index_service.py:709-712` in-memory attribution is unconditional per plan; persisted apply `:1093-1101` is context-scoped (M13) with `n_attributed > 0` gate `:1110` → when no cached var matches, in-memory resolves the field but the cache keeps it unresolved; L1/L2 diverge. → Fix: apply the same M13 context gate to the in-memory path.

9. **N11 — `highlight_strategies.py:41` `int(nd.get("line_start") or 0)`** raises `ValueError` on a malformed/non-numeric cache value → 500, no try/except. The `line < 1` guard is in, but malformed values are unhandled. → Fix: wrap in try/except, skip on non-numeric.

### Process / release

10. **`docker_image/RELEASE.txt` stale vs VERSION.** VERSION = `3.3.145`; `docker_image/RELEASE.txt` still `VERSION=3.3.140 COMMIT=1046522` (last regenerated at the v3.3.140 release). `target_deploy.sh` version guard will fail fast until `release.sh` regenerates — intentional per the deploy-holds-for-review note, but must not be forgotten before deploy.

---

## Doc ↔ code discrepancies (still open)

| # | Doc (file:line) | Code truth |
|---|---|---|
| D1 | `wiki/SOLUTION_DESIGN.md:908` and `tools/BUG_ANALYSIS_AND_SUGGESTIONS.md:3053` still say cache prefix `graph_3_2_18` | `cache_keys.py:43` = `graph_3_2_19` (CLAUDE.md:31/148 fixed; these two not) |
| D2 | `SOLUTION_DESIGN.md:859-860` §4 FIELD_LIKE lists `{…, computed, window, variable}` | `VariableType` has no `computed`/`variable`; code uses `{…, case, transform, window}` (`lineage.py:403-404`) |
| D3 | `BUG_ANALYSIS:3270-3271` v3.3.144 "`alias_of` (:104) / `containment` (:126) already exist — no new fields needed" | Both are **new** (added `c9b35bd`, now `variable.py:111/127`); doc line numbers stale |
| D4 | `BUG_ANALYSIS:3074,3080,3084-3088` — S1/S2/S3 + I1–I4 marked "NOT fixed / deferred / analysis only" | All implemented (I1 def-sites `variable_extractor_v2.py:1071,1188,…`; I2 `:1662`; I3 `dependency_graph.py:451-481`; I4 `alias_of` `:1490-1520`; I5 containment) |
| D5 | `BUG_ANALYSIS:3213` + `CLAUDE.md:36,142-143` "B machinery DELETED / text-search DELETED" | `_find_position_scoped` still exists (`variable_extractor_v2.py:724`) and is **called** as fallback (`:873`) |
| D6 | `BUG_ANALYSIS:3190-3203` (v3.3.143 I3 line-containment) vs `:3260-3268` (v3.3.144 max-≤ tie-break) | Code implements v3.3.144; v3.3.143 design **never marked superseded** |
| D7 | `CLAUDE.md` file map line counts stale for 10 files (l2_builder 1317→1297, dataflow_service 485→527, cache_keys 32→43, variable_extractor_v2 2120→2462, dependency_graph 566→640, lineage 683→693, …); note 19 cites deleted `_scope_distance`/`_pick_scope_candidate` without caveat | HEAD line counts above |
| D8 | Phantom-dedup "before" numbers (344/1102) in docs don't reproduce | Measured 354/1126 at `6a19c43` (sqlglot 30.8.0 vs doc's 30.12.0); after-numbers verified |

---

## Test results @ HEAD `1750423`

| Scope | Result |
|---|---|
| 36 non-async test files (~600 tests) | **All pass** — incl. `test_b3_zero_parentless_fields`, `test_same_table_4_contexts_single_node`, `test_sample_v1_repro` (649 deps), new `test_ground_truth_benchmark` + `test_highlight_strategies` + `test_i1_definition_lines` (13) |
| Async service-layer files (`test_search`, `test_single_script_l1`, `test_filter_andor`, `test_filter_config`, `test_full_http_journey`) | Hang in sandbox — `asyncio.to_thread` under Python 3.14/bwrap, **environmental**; CI must pin Python ≤ 3.12 |
| `test_c_index_pipeline.py` | Excluded — same known hang |
| Highlights | Byte-exact `[[18,18],[43,43],[158,158],[160,160]]`; all `start ≥ 1` |

## Priority advice (no source modified)

1. **N8 one-liner first**: surface `parse_errors` in `adapter.run_full_analysis` — the shipped "parse-errors banner" is otherwise inert.
2. **C-3** (highest old item): add cross-run fields to `extractor_unresolved` + include `extractor_version` in the analysis cache key.
3. **I4 persistence**: add `alias_of` to `adapter._var_to_dict`.
4. **D1/D2**: guard all line consumers (`≥ 1`) and anchor the 7 CONCAT join-key expressions.
5. **Labels**: extend `@line`/context disambiguation to non-alias VT/subquery intermediates.
6. **Docs**: fix D1–D8 (single-source the cache prefix from `cache_keys.GRAPH_CACHE_PREFIX`; mark v3.3.143 superseded; flip S1–S3/I1–I5 statuses; refresh CLAUDE.md map).
7. **Before deploy**: run `release.sh` to regenerate `docker_image/` (RELEASE.txt 3.3.140 → 3.3.145).

## Verification method

- 3 sub-agents in parallel (Ohm: end-to-end N1/N7/N8 + frontend scan; Faraday: old-advice re-verify incl. live pipeline probes on `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql`; Sagan: doc↔code audit), plus main-thread per-file pytest sweep (~36 files), new-benchmark test run, and adapter return-dict inspection.
- No source files modified.
