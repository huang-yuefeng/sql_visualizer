# Code Review — v3.3.150 Wave 1+2 / round 12 (open issues only)

> **Reviewed:** 2026-08-11 | **Version:** VERSION `3.3.150` | **Reviewed HEAD:** `acb2dcf` (agents also verified against `2963641`); **repo HEAD now `034eaa2`** — J12-10 physical-model stages (2/3/4) landed **after** this review snapshot, not covered here.
> **Scope:** `git diff 3590bcc..acb2dcf` — 72 files, +6931/−1313: round-12 E-series (walker gaps 1–6, adapter N8/I4, E1 gates, Jaccard end-state, E4 security), R11-3 (mech payload, evidence panel, layout/a11y), Wave 1+2 (R19/R20 flow roles, path-scoped reasons, structure toggle).
> **Reviewer:** Codex (read-only — no source modified) via 3 sub-agents: Faraday (engine core), Confucius (tests), Kant (security/frontend/docs).
> Round-11 wiki replaced below: fixed items removed, only open/new issues kept.

## Resolved (verified behaviorally)

- **N8 parse_errors** — FIXED: `adapter.py:143` `"parse_errors": [dict(e) …]`; runtime-verified (len=2 on broken SQL). — **KEPT 2026-08-11**: still at `adapter.py:143`; l2_builder reads it via `result.get("parse_errors", [])` (l2_builder.py:142 area).
- **E1/E2 gates** — FIXED: `dependency_graph.py:273` (1c-direct `src.context != stmt` gate), `:218-221` (E2 line-order guard), `:237` (WRITE_READ targets reader var); tests + probe confirm no reversed edge. — **KEPT 2026-08-11**: gates intact at `dependency_graph.py:222-224` (E2 line-order), `:273-280` (E1 cross-statement), `:237` (WRITE_READ → reader instance, Issue-3 routing).
- **I4 alias_of** — FIXED: `adapter.py:170`; 14 vars carry exact source-id (`p1 → f27daa…`). — **KEPT 2026-08-11**: `"alias_of": v.alias_of` still in `_var_to_dict` (`adapter.py:170-172`).
- **E3a walker gaps 1–6** — FIXED & correct: UPDATE walker, Hive multi-insert arms, INSERT-target attribution, comma-join CTE guard, MERGE branches, PARTITION seed scoping; `test_walker_gaps_e3.py` **11/11**, synthetic probes confirm. — **KEPT 2026-08-11**: `test_walker_gaps_e3.py` rerun 11/11; Hive multi-insert machinery still present (`variable_extractor_v2.py:392,502-520`).
- **R19/R20 flow topology** — IMPLEMENTED, backward-compatible (additive): flow roles = node fields (`flow_source/flow_target` filtered, `flow_role source|target|waypoint` full view via `classify_flow_roles lineage.py:918`); structure toggle is client-side CSS only (SCHEMA stays in payload); path-scoped reasons `"<kind> (<role>) — <upstream> ‖own‖ <downstream>"`; `mech` 100% coverage (14/14, 27/27). — **KEPT 2026-08-11**: `classify_flow_roles` now `lineage.py:882` (moved; flow_source_id/flow_targets became model-backed J12-10 stage 3); node fields stamped at `l2_builder.py:1673,1678,1687`, `mech` at `:1647`; `test_flow_roles` + `test_mech_payload` passed.
- **Jaccard benchmark end-state** — floors **ratcheted to 1.0** (recall/precision pairs, all 1.0000); row 11 removed as degenerate (J12-1) → **zero unmatched rows**; run green (1 passed, shim for /app path). — **KEPT 2026-08-11**: rerun green — bdm/sup recall 1.0000 all features, precision ≥ 1.0000; `FLOORS` all 1.0000/1.0000 (`test_jaccard_benchmark.py:160-175`, re-pinned after Issues 2/3 landed).
- **Round-11 #14 l1_l2_integration 5 failures** — FIXED: **14/14 passed** (pair-set assertions exact, `_compute_highlight_ranges` tests rewritten to per-edge `highlight_line`). — **KEPT 2026-08-11**: rerun 14/14 passed.
- **E4 security** — FIXED: `workspace.py:189,207-210` type whitelist (400 on traversal), `resolve_script` containment (filter_service.py:47-61), `logger.py` stderr gating (`SQL_VIZ_LOG_STDERR`), cache `extractor_version` stamp + validation (`dataflow_service.py:372,435`), atomic cache writes + `_views_lock`; `test_security_negative.py` 10/10 in-process PASS (7 HTTP tests blocked by starlette/httpx/py3.14 env artifact, not logic). — **KEPT 2026-08-11**: whitelist `workspace.py:188-208`; containment now via `is_relative_to` (`filter_service.py:63-68`); gating `logger.py:12-19,40-45`; stamps `dataflow_service.py:377,404-405,433,462` + `_atomic_write_text` `:314-324,:446,:463` + `_views_lock` `:565`; `test_security_negative.py` passed in-process, full suite green.
- **N10 doc lie / dead code** — FIXED: `_pick_scope_candidate` etc. truly gone; `cache_keys.py:49` `graph_3_2_21` with explanatory comment (v3.3.145 claim now true). — **KEPT 2026-08-11**: `_pick_scope_candidate`/`_scope_distance`/`_resolve_scope_parent`/`_find_labeled`/`_find_position_scoped` all still absent (only a docstring mention at `variable_extractor_v2.py:612`); cache narrative at `cache_keys.py:43-47`.
- **C-5 case-sensitivity** — FIXED: `folder_index_service.py:760,770` lowercase star-exclusion set. — **KEPT 2026-08-11**: `_star_excluded_lower = {x.lower() ...}` at `folder_index_service.py:758-759`.
- **R11-3 frontend** — FIXED: EdgeReasonPanel code-evidence block (mech.sentence/ref_line/use_lines, missing-data safe), pickAutoEdge + structureEdges utils (12 tests), app.css layout flex fix (`.panel-inline-l2` column, reason panel never clipped), show-all re-select via `applyL2Result`+`pickAutoEdge` (DataFlowApp.jsx:372-375), a11y `role="status" aria-live="polite"`, SqlPanel `scrollToLine`, reason-panel constant height + drag handle (Issue 1). Frontend tests 81/81. — **KEPT 2026-08-11**: EdgeReasonPanel mech block + a11y (`EdgeReasonPanel.jsx:40,62`), `scrollToLine` (`SqlPanel.jsx:59-65`), `applyL2Result`+`pickAutoEdge` (`DataFlowApp.jsx:106-113,370-379`), `pickAutoEdge.js`/`structureEdges.js` utils, app.css `.panel-inline-l2` column (`:773-779`); vitest rerun **122/122** (R26-R28 additions on top of the 81).
- **sql_highlight_service guard** — FIXED (`resolve_script` None → 404-shaped error). — **KEPT 2026-08-11**: `sql_highlight_service.py:24-27` — `resolve_script` None / not-a-file → `{"error": ...}` (404-shaped), containment via shared resolver.
- **Cache prefix** — `3_2_21` consistent with `test_c_index_pipeline` (prefix pin verified standalone). — **KEPT 2026-08-11 (value advanced)**: now `graph_3_2_23` (`cache_keys.py:79`, J12-10 stages 3+4 bumps narrated at `:49-77`), pinned by `test_c_index_pipeline.py:154`; consistency mechanism intact.

---

## Open issues

### High

1. **D2 — WRITE_READ still field-blind** (`lineage.py:721-734`). Forward DML admit remains unconditional (`admit = fwd or (…)`); the REF `read` flag (:132/:601) fixed the RC-1 sibling-flood, not D2. Probe: `rrcdm@211` **still in** closure(sup,charge_department)=7 and closure(sup,lending_ref)=7; L2 search `(sup,charge_department)` renders `rrcdm_job_log_exec_par` as a flow_target table with an hl=211 write edge, though stmt2 references neither field. Leak path: seed `p2.charge_department@203 →⟐output@160` (JOIN) → DML fwd → `sup@160` → Issue-3 identity admission `sup@223` → TABLE_FLOW (identity-in-chain) → `⟐output@211` → blind DML fwd → `rrcdm@211`. **Fix**: `read_fields` carrier on `VariableDependency` (or gate forward DML admit on the reader statement referencing `target_field`); never field-blind admit.

    **STILL-OPEN 2026-08-11** — forward DML admit remains unconditional at `lineage.py:693-697` (`admit = fwd or (…)`); no `read_fields` carrier exists anywhere (`models/variable.py`, `dependency_graph.py` — grep empty); WRITE_READ still emitted without field gating (`dependency_graph.py:237`). Re-probed on `BDM_ACC_LOAN_INFO_SUP_M.sql` via the served `_build_l2_graph` path: the `rrcdm_job_log_exec_par` table node is STILL in the L2 closure for (sup, charge_department)=6, (sup, lending_ref)=6, (sup, data_dt)=7 nodes — stmt2 references none of those fields. Counts moved 7→6 (physical-model assembly + J12-15/16), leak mechanism unchanged.

### Medium

2. **N11 — `int()` unguarded in l2_builder (partial)**. `highlight_strategies.py:85` `_safe_int` + unit test — FIXED there; **l2_builder.py still has ~15 unguarded `int(... or 0)` sites**: :651-652 (the old :659-660 spot), :1244/:1248, :1309/:1320/:1333/:1339, :1397/:1404/:1407, :1487-1509, :1582-1593. A malformed cached `line_start="abc"` raises ValueError at L2 build. **Fix**: use `_safe_int` (import from highlight_strategies or extract to a shared util) at every remaining site.

    **STILL-OPEN 2026-08-11** — `_safe_int` still exists only in `highlight_strategies.py:85`; `l2_builder.py` still carries ~25 unguarded `int(x or 0)` sites — the cited ones all remain (now at :436, :682-683, :1260-1261, :1264, :1325, :1336, :1349-1355, :1403, :1408, :1415-1418, :1435, :1498-1520, :1593-1604; line numbers shifted with the J12-10 assembly, count grew past the ~15 cited). l2_builder imports from highlight_strategies only `get_strategy, FIELD_LIKE_TYPES` (`l2_builder.py:28`) — `_safe_int` never imported.

3. **C-3 — cross-run stale caches (carryover, untouched)**. `folder_index_service.py:687,694-698` — cross-run branch still never re-adds fields to `extractor_unresolved`; analysis cache key still `md5(rel_path+sql_text)` with no version discriminator (the +7 change was C-5, not C-3). **Fix**: add cross-run fields; include `extractor_version` in the analysis-cache key (graph cache already stamped).

    **STILL-OPEN 2026-08-11** — cache key still `hashlib.md5((rel_path + sql_text).encode())` with no version discriminator (`folder_index_service.py:408`); cross-run revoke branch (`:693-698`) still never re-adds the field to `extractor_unresolved` (only the current-index branch does, `:687`). Consumers' load-time `extractor_version` check (`l2_builder.py:123-124`, `dataflow_service.py:404-405`) mitigates stale-cache SERVING but neither adds the cross-run fields nor discriminates the key — the issue's two asks are both unaddressed.
4. **Shared walkable-set contract (RC-1 hardening) still absent** — `FIELD_LAND`/structural sets live only in `lineage.py`; `dependency_graph.py` still re-types independently; no cross-layer invariant test landed (Jaccard benchmark doesn't import a semantics constant). This is the class-level root of D2/E1/E2 recurrences. **Fix**: single-source walkable/structural edge-type constants + invariant test.

    **STILL-OPEN 2026-08-11** — `FIELD_LAND`/`NEVER` still live only in `lineage.py:425,430`; `dependency_graph.py` imports no lineage constants (imports: `variable.py`, `variable_extractor_v2.py` only) and still re-types independently — `_bridge_typing` (`dependency_graph.py:760-793`) promotes Phase-7 SUBSET bridges to REF/READ, FILTER, JOIN, DML per its own rules. No cross-layer invariant test exists (no test file imports the semantics constant; `test_mech_payload`/`test_physical_model_equivalence` do not).

### Low

5. **`get_highlight` still async-on-event-loop** (`routers/dataflow.py:313`) — runs `build_graph_data`+`filter_relevant` on the loop; same class as the E4 freeze fix, not covered by it. **Fix**: plain `def` (threadpool).

    **STILL-OPEN 2026-08-11** — still `async def get_highlight` at `routers/dataflow.py:313` calling `get_highlight_ranges` directly (`:328`), which runs `build_graph_data` + `filter_relevant` on the event loop (`sql_highlight_service.py:43-47`). `get_level2` was converted to plain `def` (`dataflow.py:266-275`, E4) — this route was not.
6. **`get_script_path` string-prefix check** (`workspace_service.py:129-137`) — `str(target).startswith(str(scripts_dir.resolve()))`; a same-workspace sibling dir named `scripts_backup` passes; cannot escape the workspace root, pre-existing, low. **Fix**: `is_relative_to` like `resolve_script`.

    **STILL-OPEN 2026-08-11** — `get_script_path` unchanged at `workspace_service.py:129-137`: still `str(target).startswith(str(scripts_dir.resolve()))` (`:134`). `is_relative_to` is used only in `resolve_script` (`filter_service.py:67`) and the zip-extraction check (`workspace_service.py:88`) has the same prefix pattern.
7. **Untracked debug probes** — `backend/probe_alias.py`, `probe_alias2.py`, `probe_edges.py` (plus earlier `_probe213`/`_check33` etc.) still present. **Fix**: delete before commit.

    **FIXED 2026-08-11** — `backend/probe_alias.py`, `probe_alias2.py`, `probe_edges.py` (and the older `_probe213`/`_check33` family) are gone; `backend/` root now holds only `start.py`. Caveat: the tree still carries NEW probe files — `backend/app/_e2e_probe.py`, `backend/app/_probe_issue23.py`, `backend/tests/_integration_probe.py`, `tools/probe_new_edges.py` — these are now git-tracked (committed deliberately), a fresh instance of the same class; deletion is a new housekeeping item (also flagged by #9).
8. **Doc staleness (minor)** — `BUG_ANALYSIS:4330` Issue-1 header still "OPEN — awaiting user's fix pick" though the fix shipped (top summary :317 already says decided); `jaccard_canonical.py:6` docstring "sup = 10 nodes / 14 edges" vs `CANONICAL_NODES["sup"]` = 9 entries; `cache_keys` doc jumps 3_2_19 → 3_2_21 without narrating the 3_2_20 intermediate; `resizable.css:107-115` comment says SQL absorbs squeeze but the flex override makes the graph absorb it (harmless, comment mismatch). **Fix**: align the four spots.

    **STILL-OPEN 2026-08-11 (partial — 2 of 4 spots fixed)** — (a) `BUG_ANALYSIS_AND_SUGGESTIONS.md:4330` — **FIXED**: header now reads "Issue 1 · L2 edge click → viewport refit (frontend, **FIXED 2026-08-11** — Wave 1D)". (b) `jaccard_canonical.py:10-11` docstring — **STILL-OPEN**: still says "sup = 10 nodes / 14 edges"; `CANONICAL_NODES["sup"]` = 9 (verified; J12-16 dedup-key change dropped one node — bdm 18 and sup 14 edges are correct, only the sup node count is stale). (c) `cache_keys.py:43` — **STILL-OPEN**: the R11-3 entry still jumps `3_2_19` (v3.3.145, `:37-41`) → `3_2_21` without narrating the `3_2_20` intermediate. (d) `resizable.css:107-115` — **FIXED**: the squeeze comment is deleted from resizable.css (only `flex-shrink` rules remain there); `app.css:779` carries the updated R11-3 narrative.
9. **J12-10 physical-model stages (HEAD `034eaa2`) not reviewed** — 4 commits landed after this snapshot (proxies deleted, L1/L2 consume the physical model) with a modified BUG_ANALYSIS/GROUND_TRUTH doc + new probes in the tree; needs the next review pass.

    **FIXED 2026-08-11 (review gap closed)** — the J12-10 stages 1–4 (commits `9d66229`→`32b6159`) plus E5/R26-R28 are now in HEAD (`631f388`) and covered: `test_physical_model_equivalence.py` + `test_l2_stage4.py` pin the model consumption (both pass), full backend suite rerun **797 passed / 5 skipped**, frontend vitest **122/122**, and this classification pass verified the stage-3 model-backed walker (`lineage.py:511-801`), stage-4 assembly (`l2_builder.py`), and the D2/N11/C-3/probe residuals above against the current source. Remaining carryover from this item: the new probe files (see #7 note) are still in the tree.

---

## Test results (round-12 scope, /tmp venv py3.14)

| File | Result |
|---|---|
| test_walker_gaps_e3 | **11/11** |
| test_mech_payload / test_flow_roles | **7 + 13** |
| test_dependency_graph / test_highlight_strategies | 9 + pass (39 total with flow_roles) |
| test_l1_l2_integration | **14/14** (round-11 5 failures fixed) |
| test_jaccard_benchmark | **1 passed**, recall 1.0 all features, zero unmatched rows (path shim) |
| test_security_negative | 10/10 in-process PASS; 7 HTTP blocked by starlette/httpx/py3.14 env artifact; 1 hangs (`asyncio` threadpool stall, py3.14) |
| test_c_index_pipeline | prefix pin verified standalone; suite hangs on py3.14 asyncio.to_thread (env) |
| frontend (vitest) | 81/81 (incl. 12 pickAutoEdge/structureEdges + EdgeReasonPanel 26) |
| highlight_strategies + b_series_l2 + l2_table_dedup + verification_samples | 43 passed |

## Priority advice (no source modified)

1. **D2 (#1)** — the only genuine correctness leak left; `read_fields` carrier + field-aware DML admit closes the rrcdm-in-every-closure objection and makes closures honest.
2. **N11 (#2)** — mechanical: replace all `int(... or 0)` in l2_builder with the existing `_safe_int`.
3. **C-3 (#3) + shared contract (#4)** — the two remaining architectural items; C-3 keeps the orphan report incomplete, #4 prevents recurrence of D2/E1/E2-class bugs.
4. **E4 residuals (#5/#6)** — cheap hardening, same class as the shipped fixes.
5. **Housekeeping (#7/#8)** — delete probes, align 4 doc spots.
6. **Next pass (#9)** — review the J12-10 physical-model stages (HEAD `034eaa2`) and the new probes.

## Verification method

- 3 sub-agents in parallel (Faraday: engine core + closure re-probes on `git archive acb2dcf`; Confucius: all test suites, live runs; Kant: E4 security + R11-3 frontend + docs), plus main-thread git scoping. Runtime probes: closures, WRITE_READ direction, mech payload coverage, security vectors (traversal/whitelist/version-stamp/concurrency).
- No source files modified.
