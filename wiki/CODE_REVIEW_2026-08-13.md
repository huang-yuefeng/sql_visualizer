# Code Review — R29 Direction-Aware Field Flow + R30 (v3.3.153, open issues only)

> **Reviewed:** 2026-08-13 | **Version:** `VERSION` = `3.3.153` | **HEAD:** `ec17cd7`
> **Scope:** `git diff c3c66f0..HEAD` — R29 (direction-aware field-flow walker, L1 directional projection, upstream/downstream query direction, row-level continuation walker fix), R30 (L2 edge flow-direction display — docs only), J12-21/22/23 records.
> **Reviewers:** Codex (read-only — no source modified) via 4 parallel sub-agents: Hubble (walker core), Ptolemy (builders/API), Beauvoir (frontend), Zeno (tests/docs). Findings consolidated and line-checked against HEAD.
> **Source delta:** `backend/app/extractor/lineage.py` +382, `backend/app/services/dataflow_service.py` +199, `backend/app/services/l1_builder.py` +233, `backend/app/services/l2_builder.py` +101, `backend/app/routers/dataflow.py` +43, frontend `DataFlowApp.jsx`/`api/client.js`/`FilterPanel.jsx`, plus tests/docs/snapshots.

## Summary

- **1 High** (documentation mislabels a shipped feature as pending).
- **10 Medium** (validation gaps, one breaking L1 schema shape change, one lost-state no-flow view, one stale frontend ref, doc-vs-implementation defaults, two ground-truth doc contradictions, two test-quality gaps).
- **~15 Low** (hardening, state-sync, stale comments, schema echo inconsistency).

All items below are NEW/OPEN as of this review. No source files were modified.

---

## High

### 1. R29 is implemented but still documented as “pending / no source change”
- **Files:** `wiki/SOLUTION_DESIGN.md:1409`, `wiki/REQUIREMENTS_TRACEABILITY.md:234-239,254-255` (and related R4.11–4.13, R5.9, R18.7, R18.1.3, R19.7 rows), `REQUIREMENTS.md` R29/R4.11/R5.9 text.
- **Problem:** the R29 header reads `Status: DEFINED (R29) — implementation pending, no source change`; the traceability rows still use 📝 “design, not implemented” and the summary counts “2 — R29 + R30” as unimplemented. But R29 source landed in this very range (`lineage.py`, `dataflow_service.py`, `l1_builder.py`, `l2_builder.py`, `routers/dataflow.py`, plus frontend), and `VERSION` is now `3.3.153`.
- **Impact:** engineering decisions made from the traceability will wrongly treat R29 as future work; the implemented/not-implemented count and version are stale.
- **Fix:** flip R29.1–R29.6 and the derived R4/R5/R18/R19 rows to ✅ with `v3.3.153`/date, update the R29 header to “implemented”, change the summary to “1 — R30 (docs pending)”, and bump the traceability version.

---

## Medium

### 2. `direction` is never validated — invalid values silently become downstream
- **Files:** `backend/app/routers/dataflow.py:148,189,242,263,287,332`; `backend/app/services/dataflow_service.py:43,143,410,617`; `backend/app/extractor/lineage.py:698-708`.
- **Problem:** every consumer only checks `direction == "upstream"`; any other value (`"UPSTREAM"`, `"up"`, typo, empty) falls through to downstream with no error. The router does not validate the POST body or query params.
- **Impact:** hard-to-diagnose wrong-direction results for direct API callers and future frontend paths.
- **Fix:** validate at the router boundary against an allowlist (`Literal["upstream","downstream"]` / `Query(pattern=...)`), return 400 on invalid input, and normalize once before the builders/walker.

### 3. No-flow search discards `matching_scripts`, breaking the direction override
- **File:** `backend/app/services/dataflow_service.py:142-148,235-269` (`_no_flow_result`).
- **Problem:** when the directional flow is empty, `create_search` returns `_no_flow_result()` with `script_ids: []` and `script_count: 0`; the real `matching_scripts` are dropped and never persisted.
- **Impact:** the persisted view has no scripts, so a later `GET /level1`/`/level2` with the opposite `direction` cannot re-project — exactly the views that need a direction switch most. Confirmed: `_no_flow_result` persists `"script_ids": []` and `"target": "table.field"` (literal).
- **Fix:** pass `matching_scripts` through and persist `script_ids`/`script_count` while keeping the `match_mode="no_flow"` banner and empty directional graph.

### 4. Field-search L1 drops `lineage_field_pairs` and field nodes (breaking schema, no version bump)
- **Files:** `backend/app/services/l1_builder.py:420-433` (non-empty) and `:333-336` (empty); `backend/app/services/dataflow_service.py:150-154`.
- **Problem:** pre-R29 field queries returned the table-level L1 including field children and `lineage_field_pairs`. The new directional projection returns neither; `flow_empty`/`no_flow` are also new states.
- **Impact:** breaking response-shape change for `/search` and `/level1` consumers built on the old field-node shape, with no `format_version`/schema marker.
- **Fix:** keep `"lineage_field_pairs": []` present (and optionally a schema/`format_version` marker), and document the `no_flow` match mode; confirm all shipped clients consume the new shape.

### 5. L1 table classification defaults unmatched tables to `source_table`
- **File:** `backend/app/services/l1_builder.py:385-392`.
- **Problem:** participating tables are classified from scripts’ raw `input_tables`/`output_tables`; any table whose name does not match a script IO slot is appended to `source_tables`.
- **Impact:** qualified-vs-unqualified or alias/canonical name divergence mislabels an intermediate/output table as a source, corrupting the directional display.
- **Fix:** derive the role from the closure/model edges (walk direction + PhysicalModel roles/write legs) rather than defaulting to source.

### 6. Frontend L2 fetch uses stale `parentViewIdRef`, now carrying the wrong direction too
- **File:** `frontend/src/DataFlowApp.jsx:246-249` (assigned only at `:225`, cleared at `:439`).
- **Problem:** `parentViewIdRef.current` is only set in `handleSearch`; `handleViewTreeClick` never updates it when navigating to an L1 search view. The new `searchView = views.find(...)` + direction lookup therefore resolves the last-searched view — wrong parent and wrong direction — after a view switch.
- **Impact:** double-clicking an L1 script node after switching views fetches L2 for the wrong view/direction.
- **Fix:** set `parentViewIdRef.current = viewId` in the L1 branch of `handleViewTreeClick` (and clear it on child navigation), or derive the parent from the active/displayed view.

### 7. Direction default contradicts the documented contract
- **Files:** docs say `default upstream` (`wiki/SOLUTION_DESIGN.md:177,238,1460`, `REQUIREMENTS.md` R29), but implementation defaults to `downstream`: `backend/app/services/dataflow_service.py:43,410`, `backend/app/services/l1_builder.py:437`, `backend/app/routers/dataflow.py:189,263,332`, `frontend/src/api/client.js:90,110`.
- **Problem:** the UI (`FilterPanel.jsx:43`) compensates by always sending upstream, so the user-facing default is upstream — but a direct API caller or missed frontend path gets downstream.
- **Fix:** either change backend/client defaults to `"upstream"` (with legacy-compat checks) or amend docs to explicitly separate “UI default = upstream” from “API default = downstream”, and add a test asserting the UI always passes it.

### 8. Stale ground-truth claims contradict the repaired ground truth
- **Files:** `REQUIREMENTS.md:1438`, `wiki/SOLUTION_DESIGN.md:1493-1495`, `tools/GROUND_TRUTH_BDM_ACC_LOAN_INFO_LENDING_REF.md:10,22,40,54`.
- **Problem:** docs still say `rrcdm_job_log_exec_par.data_dt` is “upstream-only, empty downstream” and `lending_ref` chain is `acnw → lending_ref`. The repaired ground truth and new tests say the opposite: rrcdm downstream is the non-empty writer’s-own-leg chain, and lending_ref starts at `ods_ccb_cb_loan_acctloan.acctnbr` (SQL `A.acctnbr AS LENDING_REF`); the LENDING_REF doc mixes `acnw`/`acctnbr`.
- **Fix:** update the bullets to the repaired 2026-08-12 behavior and use `acctnbr` consistently in the LENDING_REF doc.

### 9. Missing router/API-level tests for the new direction paths
- **Files:** `backend/tests/test_full_http_journey.py:145-199`, `backend/tests/test_dataflow/test_search.py:318-345`.
- **Problem:** direction is exercised only at service level; there is no POST `/search` → `GET /level1|/level2` journey asserting direction echo/persistence, `match_mode="no_flow"`, or the upstream L2 “not in the writing flow…” message and role flip.
- **Fix:** add a small router-level upstream journey + a `no_flow` case.

### 10. Direction ground truth and the L2 snapshot were repinned from served closures
- **Files:** `backend/tests/jaccard_canonical.py:321-390`, `backend/tests/test_l1_physical_model.py:246-262`, `backend/tests/snapshots/l2_snapshot_02_BDM_ACC_LOAN_INFO_SUP_M.sql.json`.
- **Problem:** comments state several downstream L1 projections and jaccard rows were “repinned to the engine truth”/served closures; the 02_SUP_M filtered snapshot was regenerated (5/7 → 13/20). With floors at exactly 1.0000/1.0000, these now largely assert the engine matches its own output.
- **Impact:** silent over/under-admission (the J12-21 class the benchmark explicitly cannot see) would be enshrined as correct.
- **Fix:** re-derive canonical rows from SQL/textual evidence where possible; keep a distinct independent assertion for repinned seeds; document that the 13/20 rebaseline pins the repaired LENDING_REF ground truth.

---

## Low

- **`backend/app/extractor/lineage.py:679`** — `_stmt_of()` does `_top.index("}")` on `CTE{...` without guarding `"}" in _top` (adjacent rule at `:1113` guards correctly). A malformed context would raise `ValueError` and 500 the L2 build. Fix: guard before slicing.
- **`backend/app/extractor/lineage.py:698-708`** — upstream seed uses case-sensitive table-name equality while field-part logic lowercases; searched-table casing differences can miss seeds. Fix: case-insensitive comparison or documented canonical casing.
- **`backend/app/extractor/lineage.py:1068-1073`** — selection round grows `_sel_stmts` but never sets `changed = True`; termination currently relies on a different progress signal. Fix: mark `changed` when a new statement is recorded.
- **`backend/app/extractor/lineage.py:548-584`** — `compute_field_flow` docstring still claims downstream is “byte-identical” to pre-R29, but `c037885` changed downstream closures. Fix: update the docstring.
- **`backend/app/services/dataflow_service.py:246`** — `_no_flow_result` sets `l1_graph["target"] = "table.field"` (literal) instead of `f"{table}.{field}"`. Fix: use the real value.
- **`backend/app/services/l1_builder.py:310`** — scripts with missing model/graph are skipped without incrementing `failures`, so “could not build” masquerades as “no flow”. Fix: count/log the failure.
- **`backend/app/services/l1_builder.py:461-462`** — early `len(script_names) < 1` return stamps `flow_empty: True` unconditionally, contradicting the table-only “never flow empty” contract. Fix: `flow_empty: bool(field)`.
- **`backend/app/services/l2_builder.py:1554-1558`** — upstream `_attach_flow_roles` recomputes the closure already produced by the relevance filter (2–3 full walks per L2). Fix: compute once and pass through.
- **`backend/app/services/l2_builder.py:1761-1763`** — upstream `search_matched` uses `bool(graph_data.get("nodes"))` as a closure proxy, coupled to the filter’s output shape. Fix: retain/check the actual closure set.
- **`backend/app/routers/dataflow.py:263` vs `:332`** — `get_level1` echoes resolved `direction`, but `get_level2` does not. Fix: echo it in L2 or document why not.
- **`frontend/src/DataFlowApp.jsx:324-333`** — `direction` state is not reset/synced when navigating to an existing L1 view, so older views fall back to the last search direction. Fix: `setDirection(entry.direction || 'upstream')` on navigation and reset on delete/upload.
- **`frontend/src/DataFlowApp.jsx:221,227`** — `handleSearch` stores the client-supplied direction instead of the backend-echoed `result.direction`. Fix: store `result.direction ?? direction`.
- **`frontend/src/components/FilterPanel.jsx:43,101-107,287-300`** — `direction` is a second uncontrolled copy, not recorded in history/pins; re-running a saved search uses the current toggle. Fix: lift state up and optionally store direction per history/pin entry.
- **`backend/tests/test_l1_physical_model.py:429`** — test name `..._downstream_empty_...` asserts `flow_empty is False` (opposite of its name). Fix: rename to `..._writer_own_leg_...`.
- **`wiki/SOLUTION_DESIGN.md:1488-1490`** — still says L1 is “verified manually … no automated L1 check” despite new `test_r29_*` L1 tests. Fix: reword to “pinned by `test_r29_*` directional ground-truth tests”.

---

## Verification method

- Four read-only sub-agents reviewed disjoint slices in parallel: walker core, builders/API, frontend, tests/docs.
- Key findings line-checked against `ec17cd7`: `_stmt_of` unguarded parse, `_no_flow_result` literal target/empty `script_ids`, `direction` downstream defaults (backend + client), and the R29 “implementation pending” docs confirmed.
- Full test suite not re-run here (Python 3.14 sandbox can hang on `asyncio.to_thread`/`TestClient`); findings are static-analysis based.
- No source files were modified.
