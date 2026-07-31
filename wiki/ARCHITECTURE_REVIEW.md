# Architecture Review & Suggestions — SQL Data Flow Visualizer

> **Date:** 2026-07-30 | **Version:** 3.3.105

---

## Quick Status

| # | Suggestion | Priority | Effort | Status |
|---|-----------|----------|--------|--------|
| S1 | Delete dead backend code (2 files) | P2 | 2 min | ✅ Done |
| S2 | Remove backup directories (30 dirs, 38MB) | P2 | 1 min | ✅ Done |
| S3 | Split `dataflow_service.py` (1997L → 429L + 716L + 903L) | P1 | ~1 hour | ✅ Done — 3-file split: l1_builder + l2_builder + slim service |
| S4 | Move edge helpers to `graph_service.py` | P3 | 15 min | ✅ Done (graph_service is source of truth; dataflow_service keeps compat copies) |
| S5 | Consolidate layout constants | P3 | 10 min | ✅ Done |
| S6 | Add layout unit tests | P3 | 1 hour | ✅ Done |
| S7 | Update CLAUDE.md | P3 | 5 min | ✅ Done (created CLAUDE.md) |
| S8 | Adaptive ELK spacing | P3 | 5 min | ✅ Done |

---

## S1 — Delete Dead Backend Code (P2)

**Files to delete:**
- `backend/app/extractor/variable_extractor.py` — 769 lines, v1 extractor. NOT imported anywhere. Replaced by `variable_extractor_v2.py`.
- `backend/app/extractor/extractor_v2.py` — 760 lines. NOT imported by any module.

**Total dead code:** 1,529 lines (2 files).

**Verification:**
```bash
grep -rn "variable_extractor\b" backend/app/ --include="*.py" | grep -v "v2" | grep "import\|from"  # → no output
grep -rn "extractor_v2\b" backend/app/ --include="*.py" | grep -v "variable_extractor_v2" | grep "import\|from"  # → no output
```

---

## S2 — Remove Backup Directories (P2)

**Directories to remove:** 30 backup directories in `backend/app/static.bak.*`, totaling **38MB**.

These are created by the frontend build deployment step:
```bash
cp -r frontend/dist/* backend/app/static/
```
Each deployment creates a timestamped backup. 30 deployments = 30 stale copies.

**Fix:** Delete all `static.bak.*` directories and add `static.bak.*` to `.gitignore`. Consider adding a `--backup` flag to the deploy script instead of auto-backup.

---

## S3 — Split `dataflow_service.py` (P1)

**Current:** ~1,989 lines. Two ~550-line builder functions (`_build_l1_graph`, `_build_l2_graph`) dominate the file.

### ⚠️ Two previous attempts failed

Both tried moving the **callers** (`create_search`, `get_level2_graph`) into new files. This created cycles because the callers need `SearchView`/`_load_views` from `dataflow_service`, which would import them back. Even extracting a `_graph_base.py` first didn't help — `graph_service` and `adapter` form additional import chains that loop when `dataflow_service` is no longer the hub.

### Correct approach: move builders only, not callers

Don't move `create_search` or `get_level2_graph`. Only move the two large pure-builder functions. Import direction is strictly one-way:

```
dataflow_service.py (keeps: callers + SearchView + views + edge helpers)
    │
    ├── from l1_builder import _build_l1_graph
    │
    └── from l2_builder import _build_l2_graph, _estimate_sql_range
```

No cycles possible — `dataflow_service` imports *from* the builders, never the reverse. The builders don't import from `dataflow_service`.

**Why this works:** `_build_l1_graph` and `_build_l2_graph` already use **inline imports** for heavy dependencies (`run_full_analysis`, `build_graph_data`, `analyze_multiple_scripts`). When moved to new files, these become normal top-level imports in `l1_builder.py`/`l2_builder.py`. Nothing imports from those files except `dataflow_service`.

**Files to create:**
- `services/l1_builder.py` (~550L): `_build_l1_graph()`, `_build_table_schemas_from_graph()`
- `services/l2_builder.py` (~650L): `_build_l2_graph()`, `_compute_highlight_ranges()`, `_estimate_sql_range()`

**Changes to `dataflow_service.py`:** ~10 lines — replace two function definitions with imports. Router unchanged. No other files touched.

**Effort:** ~1 hour. Run `pytest tests/ -v` after each move.

---

## S4 — Move Edge Helpers to `graph_service.py` (P3)

**Functions to move** (lines 1213-1284 in `dataflow_service.py`):
- `_get_edge_style(edge_type)` — returns color + line style for 16 edge types
- `_get_category(edge_type)` — maps edge type → 7 visual categories  
- `_get_category_color(edge_type)` — returns category color

These are **graph visualization helpers** — they belong in `graph_service.py` alongside `NODE_STYLES` and `build_graph_data()`. Currently they're buried between the L1 and L2 builders, making them hard to find.

**After move:** Functions live in `graph_service.py`. Kept as re-exports in `dataflow_service.py` for backward compatibility — existing callers don't break.

---

## S5 — Consolidate Layout Constants (P3)

**Files:** `config/layout.js` + `utils/layoutCore.js:16-23`

Layout constants are split across two files:
- `config/layout.js` — spacing, row/col limits, sizes
- `layoutCore.js:16-23` — `TBL_W`, `FIELD_H`, `TABLE_SELECTOR`, `FIELD_SELECTOR`

**Fix:** Move the 4 constants from `layoutCore.js` to `config/layout.js`. Update imports. The `config/layout.js` comment already says "single source of truth" — make it true.

---

## S6 — Add Layout Unit Tests (P3)

**New files:** `frontend/src/utils/__tests__/layoutCore.test.js`, `snakeLayout.test.js`

Layout functions are pure math — testable with plain Node.js, no browser needed:

```js
// layoutCore.test.js
expect(tableHeight(5)).toBe(290);              // 5 fields → 290px
expect(tableHeight(0)).toBe(80);               // empty → minimum height
expect(tableHeight(20)).toBeGreaterThan(600);  // large table scales

// snakeLayout.test.js  
const positions = computeSnakePositions(nodes, tableInfo);
expect(positions.every(p => p.x >= 0 && p.y >= 0)).toBe(true);
expect(new Set(positions.map(p => `${p.x},${p.y}`)).size).toBe(positions.length); // no overlaps
```

Currently these functions are only tested implicitly when someone opens the app and looks. A regression in layout math goes unnoticed until visual inspection.

---

## S7 — Update CLAUDE.md (P3)

**File:** `CLAUDE.md`

References outdated file sizes and names:
- `App.jsx ~370L` → now `DataFlowApp.jsx ~591L`
- Missing: `lineage.py` (282L), `schema_inference.py` (180L)

Update with current module map including the new R18 files.

---

## S8 — Adaptive ELK Spacing (P3)

**File:** `utils/elkLayout.js:38-40`

Hardcoded `spacingNodeNode: 250` is too tight for 100+ node graphs (overlap) and wastes space on 5-node graphs.

```js
// Before:
spacingNodeNode: 250,

// After:
spacingNodeNode: Math.max(250, (cy.container()?.offsetWidth || 1440) / 6),
```

---

## Previously Completed

| # | Suggestion | Priority | Resolution |
|---|-----------|----------|------------|
| — | Fix table render size | P1 | ✅ OK — `data(_tableWidth)`/`data(_tableHeight)` mappers work on non-compound nodes |
| — | Remove dead JS layout files | P2 | ✅ Done — `workflowLayout.js`, `pipelineLayout.js`, `compoundLayout.js` deleted |
| — | Fix resize handle inversion | P2 | ✅ Done — `invert: true` added |
| — | Fix layout interleaving | P2 | ✅ Done — tables+scripts interleaved by layer |
| — | Remove `static.bak.*` directories | P2 | ✅ Done — 30 dirs removed |

---

## Current Architecture

### Backend

| Layer | File | Lines | Role |
|-------|------|-------|------|
| API | `routers/dataflow.py` | 352 | Search, L1, L2 endpoints |
| API | `routers/workspace.py` | 336 | Upload, index, filter config |
| Orchestrator | `services/dataflow_service.py` | 429 | Search, views, edge helpers, orchestrates L1/L2 builders |
| L1 Builder | `services/l1_builder.py` | 716 | `_build_l1_graph`, `detect_role`, `_classify_table_node` |
| L2 Builder | `services/l2_builder.py` | 903 | `_build_l2_graph`, `_estimate_sql_range`, `_compute_highlight_ranges` |
| Lineage | `extractor/lineage.py` | 282 | `compute_field_lineage`, `filter_relevant` |
| Schema | `extractor/schema_inference.py` | 180 | `infer_table_schemas` (7-pass) |
| Extraction | `extractor/variable_extractor_v2.py` | 885 | SQL → variables |
| Extraction | `extractor/dependency_graph.py` | 479 | Variables → edges |
| Graph | `services/graph_service.py` | 149 | Cytoscape JSON builder |
| Range | `services/sql_range_finder.py` | 663 | SQL line-level ranges |


### Frontend

| Layer | File | Lines | Role |
|-------|------|-------|------|
| App shell | `AppShell.jsx` | — | Tab routing (SQL Analysis / Data Flow) |
| SQL Analysis | `App.jsx` | 857 | Legacy single-script debugger |
| Data Flow | `DataFlowApp.jsx` | 591 | Multi-script pipeline debugger |
| Graph | `components/DataFlowGraph.jsx` | 180 | Cytoscape renderer |
| SQL | `components/SqlPanel.jsx` | 326 | SQL display + highlights |
| Layout | `utils/layoutCore.js` | 206 | Shared: field rel pos, table sizing, apply |
| Layout | `utils/snakeLayout.js` | 107 | Snake/wrapping positions |
| Layout | `utils/elkLayout.js` | 239 | ELK layered positions |
| Cytoscape | `hooks/useCytoscapeGraph.js` | 158 | Lifecycle: init, drag, layout dispatch |
| Config | `config/layout.js` | 49 | Layout constants |

Key design: `stripFieldParents()` renames `parent → _tableParent` before Cytoscape sees nodes. No compound → no auto-centering. Fields positioned at `table.position + frozen_offset`.
