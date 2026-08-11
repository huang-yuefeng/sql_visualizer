# Code Review — v3.3.150 Wave 1+2 / round 12 (open issues only)

> **Reviewed:** 2026-08-11 | **Version:** VERSION `3.3.150` | **Reviewed HEAD:** `acb2dcf` (agents also verified against `2963641`); **repo HEAD now `034eaa2`** — J12-10 physical-model stages (2/3/4) landed **after** this review snapshot, not covered here.
> **Scope:** `git diff 3590bcc..acb2dcf` — 72 files, +6931/−1313: round-12 E-series (walker gaps 1–6, adapter N8/I4, E1 gates, Jaccard end-state, E4 security), R11-3 (mech payload, evidence panel, layout/a11y), Wave 1+2 (R19/R20 flow roles, path-scoped reasons, structure toggle).
> **Reviewer:** Codex (read-only — no source modified) via 3 sub-agents: Faraday (engine core), Confucius (tests), Kant (security/frontend/docs).
> Round-11 wiki replaced below: fixed items removed, only open/new issues kept.

## Resolved (verified behaviorally)

- **N8 parse_errors** — FIXED: `adapter.py:143` `"parse_errors": [dict(e) …]`; runtime-verified (len=2 on broken SQL).
- **E1/E2 gates** — FIXED: `dependency_graph.py:273` (1c-direct `src.context != stmt` gate), `:218-221` (E2 line-order guard), `:237` (WRITE_READ targets reader var); tests + probe confirm no reversed edge.
- **I4 alias_of** — FIXED: `adapter.py:170`; 14 vars carry exact source-id (`p1 → f27daa…`).
- **E3a walker gaps 1–6** — FIXED & correct: UPDATE walker, Hive multi-insert arms, INSERT-target attribution, comma-join CTE guard, MERGE branches, PARTITION seed scoping; `test_walker_gaps_e3.py` **11/11**, synthetic probes confirm.
- **R19/R20 flow topology** — IMPLEMENTED, backward-compatible (additive): flow roles = node fields (`flow_source/flow_target` filtered, `flow_role source|target|waypoint` full view via `classify_flow_roles lineage.py:918`); structure toggle is client-side CSS only (SCHEMA stays in payload); path-scoped reasons `"<kind> (<role>) — <upstream> ‖own‖ <downstream>"`; `mech` 100% coverage (14/14, 27/27).
- **Jaccard benchmark end-state** — floors **ratcheted to 1.0** (recall/precision pairs, all 1.0000); row 11 removed as degenerate (J12-1) → **zero unmatched rows**; run green (1 passed, shim for /app path).
- **Round-11 #14 l1_l2_integration 5 failures** — FIXED: **14/14 passed** (pair-set assertions exact, `_compute_highlight_ranges` tests rewritten to per-edge `highlight_line`).
- **E4 security** — FIXED: `workspace.py:189,207-210` type whitelist (400 on traversal), `resolve_script` containment (filter_service.py:47-61), `logger.py` stderr gating (`SQL_VIZ_LOG_STDERR`), cache `extractor_version` stamp + validation (`dataflow_service.py:372,435`), atomic cache writes + `_views_lock`; `test_security_negative.py` 10/10 in-process PASS (7 HTTP tests blocked by starlette/httpx/py3.14 env artifact, not logic).
- **N10 doc lie / dead code** — FIXED: `_pick_scope_candidate` etc. truly gone; `cache_keys.py:49` `graph_3_2_21` with explanatory comment (v3.3.145 claim now true).
- **C-5 case-sensitivity** — FIXED: `folder_index_service.py:760,770` lowercase star-exclusion set.
- **R11-3 frontend** — FIXED: EdgeReasonPanel code-evidence block (mech.sentence/ref_line/use_lines, missing-data safe), pickAutoEdge + structureEdges utils (12 tests), app.css layout flex fix (`.panel-inline-l2` column, reason panel never clipped), show-all re-select via `applyL2Result`+`pickAutoEdge` (DataFlowApp.jsx:372-375), a11y `role="status" aria-live="polite"`, SqlPanel `scrollToLine`, reason-panel constant height + drag handle (Issue 1). Frontend tests 81/81.
- **sql_highlight_service guard** — FIXED (`resolve_script` None → 404-shaped error).
- **Cache prefix** — `3_2_21` consistent with `test_c_index_pipeline` (prefix pin verified standalone).

---

## Open issues

### High

1. **D2 — WRITE_READ still field-blind** (`lineage.py:721-734`). Forward DML admit remains unconditional (`admit = fwd or (…)`); the REF `read` flag (:132/:601) fixed the RC-1 sibling-flood, not D2. Probe: `rrcdm@211` **still in** closure(sup,charge_department)=7 and closure(sup,lending_ref)=7; L2 search `(sup,charge_department)` renders `rrcdm_job_log_exec_par` as a flow_target table with an hl=211 write edge, though stmt2 references neither field. Leak path: seed `p2.charge_department@203 →⟐output@160` (JOIN) → DML fwd → `sup@160` → Issue-3 identity admission `sup@223` → TABLE_FLOW (identity-in-chain) → `⟐output@211` → blind DML fwd → `rrcdm@211`. **Fix**: `read_fields` carrier on `VariableDependency` (or gate forward DML admit on the reader statement referencing `target_field`); never field-blind admit.

### Medium

2. **N11 — `int()` unguarded in l2_builder (partial)**. `highlight_strategies.py:85` `_safe_int` + unit test — FIXED there; **l2_builder.py still has ~15 unguarded `int(... or 0)` sites**: :651-652 (the old :659-660 spot), :1244/:1248, :1309/:1320/:1333/:1339, :1397/:1404/:1407, :1487-1509, :1582-1593. A malformed cached `line_start="abc"` raises ValueError at L2 build. **Fix**: use `_safe_int` (import from highlight_strategies or extract to a shared util) at every remaining site.
3. **C-3 — cross-run stale caches (carryover, untouched)**. `folder_index_service.py:687,694-698` — cross-run branch still never re-adds fields to `extractor_unresolved`; analysis cache key still `md5(rel_path+sql_text)` with no version discriminator (the +7 change was C-5, not C-3). **Fix**: add cross-run fields; include `extractor_version` in the analysis-cache key (graph cache already stamped).
4. **Shared walkable-set contract (RC-1 hardening) still absent** — `FIELD_LAND`/structural sets live only in `lineage.py`; `dependency_graph.py` still re-types independently; no cross-layer invariant test landed (Jaccard benchmark doesn't import a semantics constant). This is the class-level root of D2/E1/E2 recurrences. **Fix**: single-source walkable/structural edge-type constants + invariant test.

### Low

5. **`get_highlight` still async-on-event-loop** (`routers/dataflow.py:313`) — runs `build_graph_data`+`filter_relevant` on the loop; same class as the E4 freeze fix, not covered by it. **Fix**: plain `def` (threadpool).
6. **`get_script_path` string-prefix check** (`workspace_service.py:129-137`) — `str(target).startswith(str(scripts_dir.resolve()))`; a same-workspace sibling dir named `scripts_backup` passes; cannot escape the workspace root, pre-existing, low. **Fix**: `is_relative_to` like `resolve_script`.
7. **Untracked debug probes** — `backend/probe_alias.py`, `probe_alias2.py`, `probe_edges.py` (plus earlier `_probe213`/`_check33` etc.) still present. **Fix**: delete before commit.
8. **Doc staleness (minor)** — `BUG_ANALYSIS:4330` Issue-1 header still "OPEN — awaiting user's fix pick" though the fix shipped (top summary :317 already says decided); `jaccard_canonical.py:6` docstring "sup = 10 nodes / 14 edges" vs `CANONICAL_NODES["sup"]` = 9 entries; `cache_keys` doc jumps 3_2_19 → 3_2_21 without narrating the 3_2_20 intermediate; `resizable.css:107-115` comment says SQL absorbs squeeze but the flex override makes the graph absorb it (harmless, comment mismatch). **Fix**: align the four spots.
9. **J12-10 physical-model stages (HEAD `034eaa2`) not reviewed** — 4 commits landed after this snapshot (proxies deleted, L1/L2 consume the physical model) with a modified BUG_ANALYSIS/GROUND_TRUTH doc + new probes in the tree; needs the next review pass.

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
