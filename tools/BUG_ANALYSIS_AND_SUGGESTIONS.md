# Data Flow Debugger — Open Bug List

> **Date:** 2026-07-27 | **Version:** 3.3.93 | **Active:** 2 (1 partial)
>
> Fixed bugs (1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14) moved to [`BUG_HISTORY.md`](BUG_HISTORY.md).

---

## Quick Status

| Bug | Priority | Status | Notes |
|-----|----------|--------|-------|
| Bug 3: Edge Ranges Overlap | P2 | 🔧 PARTIALLY FIXED | step3: 2 lines; step4: 1 line (same-type co-location) |
| Bug 16: Graph Shadows in Loading | P2 | Open | Likely skeleton placeholders, not real graph |

---

## Bug 3: Edge Ranges Overlap (P2) — PARTIALLY FIXED 🔧 v3.3.72

### Status

- ✅ Compound edge types split — no commas in output edges
- ✅ TABLE_FLOW+DML collision eliminated (Simplification 1)
- ⚠️ Same-type co-location remains — step3: 2 lines, step4: 1 line

### Quantitative Test Results

| Script | Overlapping lines | Max edges/line | Pattern |
|--------|-------------------|----------------|---------|
| step1 | 0 | 1 | — |
| step2 | 0 | 1 | — |
| step3 | 2 | 2 | TABLE_FLOW×2 on FROM; JOIN×2 on JOIN |
| step4 | 1 | 2 | TRANSFORM+AGGREGATE on SELECT |
| step5 | 0 | 1 | — |

### Overlap trend

| Script | v3.3.65 | v3.3.69 | v3.3.72 | Status |
|--------|---------|---------|---------|--------|
| step1 | 2 | 2 | 0 | ✅ |
| step2 | 2 | 2 | 0 | ✅ |
| step3 | 10 (max 4) | 3 (max 4) | 2 (max 2) | 🔧 |
| step4 | 3 | 3 | 1 | 🔧 |
| step5 | 0 | 0 | 0 | ✅ |

### Remaining overlap

All remaining overlaps are same-type co-location on shared SQL keywords — semantically correct behavior.

### Files Involved
- `backend/app/services/dataflow_service.py:1472-1487` — compound edge splitting
- `backend/app/services/sql_range_finder.py:557-643` — `partition_edge_ranges`

---

## Design Simplification Recommendations

### ✅ Simplification 1: Eliminate `qo_` — APPLIED v3.3.71

The qo_ node eliminated. DML edges route through existing `"⟐ output"` intermediate_table.

### Simplification 2: Split compound edges BEFORE range finding

Would resolve remaining Bug 3 overlap. Already partially done.

### Simplification 3: Extract L2 graph builder

`dataflow_service.py` at ~1950 lines → split out `l2_graph_builder.py` (~700 lines).

---

## Bug 16: Graph Shadows Visible During Loading — Confirmed

> **Found:** v3.3.89 | **Priority:** P2 | **Status:** Open

**Confirmed by pixel analysis of background.png (1905×837):**

| Graph element | Color | Pixel count | Matches |
|--------------|-------|-------------|---------|
| Blue rectangles | RGB(0,120,240) | 252 px | SCHEMA edges (#3498DB) |
| Green lines | RGB(30,240,120) | 163 px | TABLE_FLOW edges (#2ECC71) |
| Horizontal segments | ≥30px | 138 | Edge lines |
| Vertical segments | ≥10px | 1332 | Node borders |
| Total bright pixels | >dark bg | 9750 px | Graph artifacts |

The Cytoscape graph colors (blue SCHEMA, green TABLE_FLOW) are definitively present in the loading screen background. The `setL1Graph(null)` before `setLoading(true)` fix at upload/search paths isn't sufficient — the graph elements appear from a different source.

**DOM trace (first visit, during loading):** Zero canvases, zero Cytoscape containers, zero `.graph-canvas` elements. The graph is NOT persisting — it's properly cleared before loading.

**Revised analysis:** The "slight rects and lines" are likely the **skeleton component's own CSS placeholders** — `.skeleton-node` (60×24px rounded rectangles, `background:#444`) and `.skeleton-edge` (2px lines, `background:#555`). These are designed to preview the graph layout during loading. Combined with green upload buttons (#2ECC71) and blue UI accents (#3498DB) visible elsewhere on the page, they create the impression of graph shadows.

**If actual Cytoscape colors appear**: Check whether the SQL Analysis tab's `PersistentPanel` (AppShell:26-36) has a loaded graph — switching tabs uses `display:none` which hides but doesn't unmount Cytoscape. Loading new data in DataFlow tab would show the old SQL Analysis graph through the skeleton's transparent background... actually the skeleton background is opaque `#1a1a2e` now. This shouldn't happen.

**Files:** `frontend/src/styles/app.css:472-474` (skeleton styling), `frontend/src/AppShell.jsx:26-36` (PersistentPanel)
