# Architecture Review & Suggestions — SQL Data Flow Visualizer

> **Date:** 2026-07-22 | **Version:** 3.3.45

---

## Current Architecture — Clean ✅

3-layer layout system:

| Layer | File | Role |
|-------|------|------|
| Orchestrator | `hooks/useCytoscapeGraph.js` (157L) | Create cy, strip parents, delegate layout, drag, events |
| Algorithms | `utils/snakeLayout.js` (106L) + `utils/elkLayout.js` (239L) | Compute table positions only |
| Shared core | `utils/layoutCore.js` (191L) | Field rel coords, table sizing, single `applyLayout()` batch |

Key design: `stripFieldParents()` at `useCytoscapeGraph.js:55` renames `parent → _tableParent` before Cytoscape sees nodes. No compound → no auto-centering. Fields positioned at `table.position + frozen_offset`.

---

## Suggestion 1: Fix Table Render Size (P1)

**Files:** `utils/layoutCore.js:119`, `utils/graphStyles.js` (COMPOUND_STYLES), `hooks/useCytoscapeGraph.js:55`

**Problem:** `applyLayout()` sets `n.style('width','200px')` / `n.style('height','290px')` but tables render at 56×84px. After `stripFieldParents()`, tables are no longer compound nodes, so COMPOUND_STYLES CSS selectors (`height: data(_tableHeight)`) may not apply.

**Fix:** Add explicit table sizing CSS for non-compound nodes, or add `min-width`/`min-height` alongside the `style()` calls.

---

## Suggestion 2: Remove Dead Code (P2)

**Files:** `utils/workflowLayout.js` (59L), `utils/pipelineLayout.js` (315L), `utils/compoundLayout.js` (104L)

These are superseded by `snakeLayout.js` + `elkLayout.js` + `layoutCore.js` and not imported by any active code.

---

## Suggestion 3: Consolidate Layout Constants (P2)

**Files:** `config/layout.js`, `utils/layoutCore.js:16-23`

Constants split across two files. Move `TBL_W`, `FIELD_H`, `TABLE_SELECTOR`, etc. from `layoutCore.js` to `config/layout.js`.

---

## Suggestion 4: Add Layout Unit Tests (P2)

**Files:** (new) `frontend/src/utils/__tests__/layoutCore.test.js`, `snakeLayout.test.js`

Pure functions are testable without browser:
- `tableHeight(5) === 290`
- `computeFieldRelPos(cy)` returns correct offsets
- `computeSnakePositions(topNodes, tableInfo)` produces non-overlapping positions

---

## Suggestion 5: Update CLAUDE.md (P3)

**File:** `CLAUDE.md`

References old file sizes (e.g., `App.jsx ~370L` → now `DataFlowApp.jsx ~549L`). Update with current module map.

---

## Suggestion 6: Adaptive ELK Spacing (P3)

**File:** `utils/elkLayout.js:38-40`

Fixed `spacingNodeNode=250` may be too tight for dense graphs. Make viewport-responsive:
```js
const vw = cy.container()?.offsetWidth || 1440;
const adaptive = Math.max(250, vw / 6);
```
