# Code Review — ROW_FLOW / L2 row-level flow round (v3.3.158, round 3, open issues only)

> **Reviewed:** 2026-08-13 | **Version:** `VERSION` = `3.3.158` | **HEAD:** `2a210e0`
> **Scope:** `git diff 8782543..2a210e0` — ROW_FLOW edge type (#226), L2 row-level flow, #221–#225 frontend, Structure-off toggle removal, L2 uniform edge/table-node style redesign, legend changes.
> **Reviewers:** Codex (read-only — no source modified) via 4 parallel sub-agents: Ampere (walker), Gibbs (services/tests), Kuhn (frontend), Cicero (tests/docs).

## Summary

- **1 High** — `requirements_v2.md` marks four shipped features “NOT yet implemented”.
- **5 Medium** — two ROW_FLOW bridge correctness gaps, one frontend flow-cone UX bug, two doc/code contract contradictions.
- **~17 Low** — stale comments/counts, test-coverage gaps, an O(n²) BFS, engine-derived benchmark aliases.

No source files were modified. Snapshot repins this round are label-only (`X` → `output(X)`) with no structural/edge changes.

---

## High

### H1 · `requirements_v2.md` still marks four implemented changes “NOT yet implemented”
- **File:** `requirements_v2.md:64,87,105,177`.
- **Problem:** click-edge flow cone (#222), `output(X)` display label (#223), uniform L2 edge style + mid-point arrow (#224/#225), and `ROW_FLOW` (#226) are all committed and wired at HEAD, yet their amendments read `Status: NOT yet implemented` (and one still claims “code uses `target-arrow-shape: triangle`”).
- **Impact:** the requirements source of truth contradicts code, tests (`test_physical_model.py` asserts 17 edge types; `test_highlight_strategies.py` asserts the 8th “row flow” kind), and `wiki/SOLUTION_DESIGN.md`.
- **Fix:** flip each status to implemented with the landing version, and remove the stale arrow-shape claim.

---

## Medium

### M1 · ROW_FLOW bridge connectivity ignores `_is_spurious_ref_copy` (suppressed bridge)
- **File:** `backend/app/extractor/lineage.py:1271-1283` (component BFS) vs `:1351-1357` (spurious-REF removal).
- **Problem:** components are computed over the full `adjacency` (including `REF` edges whose source is `⟐`-prefixed), while `_is_spurious_ref_copy` drops those edges later. Two components joined only by such an edge look connected to the bridge logic, so no ROW_FLOW bridge is emitted — then the connecting edge is removed, leaving the rendered L2 graph disconnected.
- **Fix:** compute bridge-eligibility from the post-`_is_spurious_ref_copy` filtered edge set, or move bridge emission into `filter_by_field_flow` after `filtered_edges` is known.

### M2 · Only the first seed component is bridged (nondeterministic/incomplete)
- **File:** `backend/app/extractor/lineage.py:1285-1289`.
- **Problem:** `_seed_comp` is the first element of a `set`, so iteration order is hash-randomized; when the same field appears in two independent statements (two components), only one component gets ROW_FLOW bridges and which one varies across runs.
- **Fix:** iterate every component containing a seed (deterministic order), or explicitly assert/handle the single-seed-component invariant.

### M3 · `applyFlowCone` fires on non-flow structure edges
- **Files:** `frontend/src/components/DataFlowGraph.jsx:109-123` (`applyFlowCone`) and `:166` (`onEdgeTap`).
- **Problem:** clicking a still-visible ALIAS/SUBSET structure edge applies the flow-cone focus (gold pivot + dim everything), even though `computeFlowCone` correctly returns an empty cone for structure edges. Users get a misleading whole-graph dim with a non-flow edge highlighted.
- **Fix:** guard the call with `isValueFlowEdge(edgeData)`, or early-return/clear focus when the clicked edge is not value-flow; add a test asserting no `flow-cone-*` classes for structure edges.

### M4 · L2 edge styling docs contradict the shipped uniform style
- **File:** `wiki/DATAFLOW_FORMAL_DEFINITION.md:212,226`.
- **Problem:** the doc still says “edge color = edge type … structure edges gray” / “Value flow renders per-type color”, but v3.3.157 ships a single uniform `#7F8C8D` line for every L2 edge (no per-type color), as `requirements_v2.md:91-107` states.
- **Fix:** update Display Principles item 3 and the “Two edge classes” Value-flow row to the uniform style (and note structure edges are always hidden).

### M5 · `ROW_FLOW` walkability doc contradicts `NEVER_WALKED`
- **File:** `wiki/DATAFLOW_FORMAL_DEFINITION.md:702` vs `backend/app/extractor/walkable_set.py`.
- **Problem:** the Rules Summary row says `Conditional? = Yes — row-selection only`, implying the walker follows it under a condition; code puts `ROW_FLOW` in `NEVER_WALKED` (“emitted after the closure fixpoint, never a walk input”), and `test_walkable_set.py` enforces that.
- **Fix:** change the cell to `No — emitted as an output edge, never followed`.

---

## Low

- **`lineage.py:1290-1311`** — ROW_FLOW bridge is not gated on R29 continuation evidence; structural/nested ancestors can over-emit. Restrict to `_effect_cols`/`_sel_stmts`/`_cont_cols`-evidenced containers.
- **`lineage.py:1302-1311,1362-1367`** — emitted raw `row_flow_out` is minimal; the `dataflow_service` fallback path returns an under-populated edge (no `flow_kind`/`reason`/`highlight_line`). Populate carried fields at emission or document ROW_FLOW as L2-only.
- **Stale edge-count comments (16→17)** — `lineage.py:4,24,75,361`, `physical_model.py:36`, `test_physical_model.py:8`. Update to 17 and note ROW_FLOW is walker-emitted only.
- **`graph_service.py:133`** — `get_category` docstring still says “7 visual categories” (now 8).
- **`l2_builder.py:820-825,851-852`** — SCHEMA comments say “kept as-is / stays visible”, implying a toggle that no longer exists. Reword to “kept for counts; client always hides SCHEMA”.
- **`l2_builder.py:1504-1508`** — `_closure_walk` uses unfiltered adjacency (includes SCHEMA/SUBSET), so a ROW_FLOW reason can route through bridge hops. Build a flow-only adjacency.
- **`test_b_series_l2.py:161,187-199`** — test only asserts display `label` (`output(...)`), not `table_name`; add an assertion that `table_name` keeps the internal `⟐ X`.
- **`physical_model.py:130` vs `l2_builder`** — `PhysicalTable.display_label` still uses `name[2:]` (`subq1`) while the L2 builder now yields `output(subq1)`; the two “display label” definitions have diverged. Align and test `⟐ subq1 → "output(subq1)"`.
- **`test_category_mapping.py:62-67`** — `test_no_duplicate_categories_in_map` is a tautology (dict→dict can’t duplicate keys). Drop or assert against the canonical 17-edge set.
- **`structureEdges.js:5-8`, `DataFlowGraph.jsx:149`, `graphStyles.js:749,936-938`** — stale comments describe the removed Structure-off toggle and node-role legend. Update.
- **`DataFlowGraph.jsx:71,91`** — `computeFlowCone` BFS uses `queue.shift()` (O(n²)). Use a head index.
- **`FilterPanel.test.jsx:95-130`** — direction tests don’t verify `onSearch(t,f,'downstream')` forwarding or pin/history re-search. Add those assertions.
- **`jaccard_canonical.py:1104-1106,1091-1092`** — new `NORMALIZE_MAP` `output(X)` keys are engine-derived display aliases; bare `subq/subq1` keys are now dead. Normalize on `(label, variable_type)` for VT entries.
- **`requirements_v2.md:87`** — “no extractor or benchmark impact” is false for `output(X)` (snapshots repinned + NORMALIZE_MAP entries added). Reword.
- **`_jaccard_selfverify.py:147`** — diagnostic prints “NORMALIZE_MAP 13 entries” but the map is ~23. Use `len()`.
- **`DATAFLOW_FORMAL_DEFINITION.md:457,682`** — `ROW_FLOW` has no per-type rule subsection (sections stop at §15). Add `#### 16. ROW_FLOW`.
- **`requirements_v2.md:132`** — the 17th-edge-type decision is buried in the legend amendment; promote to its own `### Amendment`.

---

## Verification method

- Four read-only sub-agents reviewed disjoint slices in parallel: extractor/walker, services/tests, frontend, tests/docs.
- Static analysis only (Python 3.14 sandbox can hang on `asyncio.to_thread`/`TestClient`); no source files modified.
- Snapshot repins verified as label-only (`X` → `output(X)`), no structural/edge drift.
