# Code Review — CR1–CR11 fix round (v3.3.154, round 2, open issues only)

> **Reviewed:** 2026-08-13 | **Version:** `VERSION` = `3.3.154` | **HEAD:** `8782543`
> **Scope:** `git diff ec17cd7..HEAD` — commit `05206a5` (R29 direction default upstream + J12-23 `flow` category + CR1–CR11 round) plus the doc commits.
> **Reviewers:** Codex (read-only — no source modified) via 3 parallel sub-agents: Hooke (backend), Feynman (frontend), Aquinas (tests/docs).
> **Relation to prior file:** this is round 2 of `wiki/CODE_REVIEW_2026-08-13.md`; it re-checks the CR1–CR11 work list at `tools/BUG_ANALYSIS_AND_SUGGESTIONS.md:4784-4895`.

## Verified fixed this round

- **CR1** docs/traceability — R29.1–R29.6 + derived rows flipped to ✅ `v3.3.153`; J12-22 header `IMPLEMENTED`; 📝 count `1 — R30`.
- **CR2** `direction` validation — `_VALID_DIRECTIONS` + `_normalize_direction` in `routers/dataflow.py:27-46`, 400 on invalid.
- **CR3** no-flow persists `matching_scripts`/`script_count` — `dataflow_service.py:142-153,256-279`.
- **CR5** L1 role classification from model read/write legs — `l1_builder.py:303-308,396-414`.
- **CR7** default direction `upstream` — backend + client (`routers/dataflow.py:38`, `api/client.js:91,111`).
- **CR11 (4 of 10 backend items)** — `_stmt_of` `"}"` guard, case-insensitive upstream seed, selection-round `changed` flag, stale `compute_field_flow` docstring.
- **CR6 (L1 branch)** — `parentViewIdRef` now set on L1 navigation — but see MED-2 for a new regression.

---

## Medium

### MED-1 · `_is_spurious_ref_copy` may over-suppress legitimate flow
- **File:** `backend/app/extractor/lineage.py:449-474` (used at `:1266-1270`).
- **Problem:** every `REF`/`REFERENCE` edge whose source has `source_tables[0].startswith("⟐")` is dropped from emitted flow, based only on a source-column heuristic.
- **Impact:** a genuine parent-scope read/rename of a subquery-output column could be silently suppressed (the rule is much broader than the LFS6/LFS7 self-loop it targets).
- **Fix:** narrow the predicate to the actual self-loop shape (same-table identity + same-named read), and add a regression proving renamed copies / join-key operands still flow.

### MED-2 · Clearing `parentViewIdRef` breaks double-click from the parent L1 graph
- **File:** `frontend/src/DataFlowApp.jsx:310` (fallback at `:246`, child id at `:281`).
- **Problem:** the L2 branch clears the ref to `null` while the parent L1 graph stays on screen; a double-click on a parent-L1 script then resolves `activeViewId` (child id), `views.find` returns undefined, and `getLevel2Graph` 404s.
- **Impact:** CR6’s fix introduced a regression on a common navigation path.
- **Fix:** set `parentViewIdRef.current = entry.parent_view_id` in the L2 branch, or make `handleOpenL2` resolve the parent when `activeViewId` is a child.

### MED-3 · Field→own-table `z-index: 1` is inert without manual z-compare
- **File:** `frontend/src/utils/graphStyles.js:639-642` (tagged in `useCytoscapeGraph.js:98-99`).
- **Problem:** Cytoscape’s default `z-index-compare: auto` always draws nodes above edges, so the J12-19 field→own-parent edge stays hidden/unclickable under the opaque compound node.
- **Fix:** add `'z-index-compare': 'manual'` to the `edge.field-to-own-parent` rule (or set it on those edges).

### MED-4 · Upstream `_attach_flow_roles` still recomputes the full closure
- **File:** `backend/app/services/l2_builder.py:1572-1574`.
- **Problem:** the upstream branch runs `compute_field_flow` again even though `filter_by_field_flow` already computed the same closure — 2x the walk per upstream L2 and a drift risk.
- **Fix:** thread the closure set from the relevance filter into `_attach_flow_roles`.

### MED-5 · CR9 journey test encodes a false “only DL writes” premise (case-sensitive index under-admission)
- **Files:** `backend/tests/test_direction_http_journey.py:25,153-154,164,176`; `backend/tests/test_independent_r29_ground_truth.py:276-285`; `backend/app/services/folder_index_service.py:532-545`.
- **Problem:** the test asserts `script_ids == [DL, SUP_M]`/upstream `{DL}` “only DL WRITES the field”, but the same commit’s independent test proves PL also writes `bdm_acc_loan_info.LENDING_REF` (`a.acnw AS LENDING_REF` @21). The assertion only holds because the field index is case-sensitive, so PL’s uppercase `LENDING_REF` is indexed separately from the searched lowercase `lending_ref`.
- **Impact:** the test enshrines a silent writer-leg under-admission instead of independent ground truth.
- **Fix:** normalize field matching case-insensitively (or document the exclusion), and correct the matching-set/upstream expectations to include PL.

### MED-6 · CR8 doc correction left a refuted “PL is not a writer” claim
- **File:** `tools/GROUND_TRUTH_BDM_ACC_LOAN_INFO_LENDING_REF.md:13,28`.
- **Problem:** the ground-truth doc still says PL has “0 occurrences of `lending_ref`” / “not a writer”, directly contradicted by the new independent test.
- **Fix:** update §1/§2.1/§4 to state PL writes `bdm_acc_loan_info.LENDING_REF`, and reconcile the L1/closure expectations.

### MED-7 · CR10 pending rows remain in the scored benchmark gate
- **Files:** `backend/tests/jaccard_canonical.py:757-1051` (11 `"pending": True` rows); `backend/tests/test_jaccard_benchmark.py:834-859,967-972`.
- **Problem:** the pending rows are still included in the `rows` used as B, so the 1.0000/1.0000 floors still assert the engine emits them; the new code only prints them distinctly.
- **Impact:** the “engine == engine” circular gate remains active for exactly the rows CR10 was meant to break.
- **Fix:** exclude pending rows from the scored B (or disable their floors) until independently re-derived from SQL text.

---

## Low

- **CR11 not fixed — `_no_flow_result` literal target** — `dataflow_service.py:258` still `"target": "table.field"`. Use `f"{table}.{field}"`.
- **CR11 not fixed — l1_builder failure counting** — `l1_builder.py:315-316` skips missing model/graph without `failures += 1`; build failures masquerade as “no flow”.
- **CR11 not fixed — `flow_empty` early return** — `l1_builder.py:482-484` stamps `flow_empty: True` even for table-only searches. Use `bool(field)`.
- **CR11 not fixed — `search_matched` node-count proxy** — `l2_builder.py:1780-1781`. Retain/check the actual closure set.
- **CR11 not fixed — `get_level2` does not echo direction** — `routers/dataflow.py:371-373` (L1 echoes at `:313`). Echo it in L2 or document why not.
- **CR11 not fixed (frontend)** — direction reset/sync on L1 navigation (`DataFlowApp.jsx:323-338`), storing backend-echoed direction (`:221,227`), and FilterPanel state lift (`FilterPanel.jsx:43`).
- **J12-23 partially fixed** — flow→green recolor landed, but structure gray, `mid-target-arrow-shape`, and click flow-cone classes are still missing (`graphStyles.js:615,622-629`).
- **NEW — `debug_graph_layout` silently flips to upstream** — `routers/dataflow.py:434-435` calls `create_search` without direction; validate/normalize `body.get("direction")` and pass it explicitly.
- **NEW — upstream/downstream seed casing asymmetric** — `lineage.py:722` (downstream) still case-sensitive vs `:729-733` (upstream now case-insensitive). Same input can find write seeds but miss read seeds.
- **NEW — `TABLE_FLOW` category docs stale** — `frontend/src/utils/structureEdges.js:10-11` and `l2_builder.py:1697` still list `TABLE_FLOW` under “structure” and omit `flow`.
- **CR10 partial — independent assertion validates, not re-derives** — `test_independent_r29_ground_truth.py:92-107` checks base-label presence + line range, not exact `(label,line)` nor edge/closure membership.
- **CR9 partial — no GET `/level2` direction echo coverage** — `test_direction_http_journey.py:197-243` never asserts `l2["direction"]`.
- **Snapshot repins remain a self-consistency gate** — `backend/tests/snapshots/*` repins match the intentional changes but `test_l2_snapshot.py` still only asserts engine==snapshot.
- **NEW — traceability ✅ count stale** — `wiki/REQUIREMENTS_TRACEABILITY.md:253` “114 (all)” contradicts the flipped R29 rows / `📝 1 — R30`.
- **NEW — “7 categories” references stale** — `wiki/REQUIREMENTS_TRACEABILITY.md:67-68,92,260,263`; code/tests now use 8 categories, and `CATEGORY_MAP` lives in `graph_service.py`, not `dataflow_service.py`.
- **NEW — stale “no automated L1 check” claim** — `wiki/SOLUTION_DESIGN.md:1518-1519`.
- **NEW — stale test method name** — `backend/tests/test_dataflow/test_category_mapping.py:16` says `13` edge types but iterates `16`.

---

## Verification method

- Three read-only sub-agents reviewed disjoint slices in parallel: backend fixes/regressions, frontend fixes/regressions, tests/docs.
- Static analysis only (Python 3.14 sandbox can hang on `asyncio.to_thread`/`TestClient`); no source files were modified.
