# Data Flow Debugger — Active Bug List

> **Date:** 2026-07-22 | **Version:** 3.3.39 | **Active:** 1

---

## Architecture Review — v3.3.39 ✅

Clean separation following the user's suggestion:

| Module | Responsibility | Lines |
|--------|---------------|:-----:|
| `layoutCore.js` | Shared: `computeFieldRelPos`, `computeTableInfo`, `applyLayout`, `stripFieldParents` | 169 |
| `snakeLayout.js` | Snake-specific: `computeSnakePositions`, `runSnakeLayout` | 107 |
| `elkLayout.js` | ELK-specific: `applyElkLayout` (tables+scripts only, falls back to snake) | 160 |

All layout algorithms share `applyLayout()` which does a single `cy.batch()`: sizes + table positions + field positions at frozen offsets. No compound relationships, no collision resolvers, no guards.

## Re-Test

| Mode | Table Overlap | Field Overlap | Offscreen | Status |
|------|:------------:|:----------:|:---------:|:------:|
| Snake | 0 | 0 | 0 | ✅ |
| Pipeline | **4** | 0 | 1 node | ❌ |

## Results

| Mode | Table Overlap | Field Overlap | Kids | Status |
|------|:------------:|:----------:|:----:|:------:|
| Snake | 0 | 0 | 0 | ✅ |
| Pipeline | **1** | 0 | 0 | ⚠️ |
| Spore | **1** | 0 | 0 | ⚠️ |

## Root Cause of the 1 Remaining Overlap

`raw_orders` ↔ `stg_orders` overlap 14×17px. Both tables at similar positions.

**Style vs Rendered mismatch:**
```
raw_orders:  style=200×290px  rendered=56×84px
stg_orders:  style=200×290px  rendered=56×84px
```
`applyLayout()` correctly sets `n.style('width','200px')` and `n.style('height','290px')`, but the rendered bounding box is only 56×84px. The inline CSS dimensions are not taking effect visually.

**Why:** Tables are no longer compound nodes (kids=0 after `stripFieldParents`). Without children, cytoscape renders them at the CSS stylesheet default (~56px for script-like nodes) rather than the inline `style()` values. The inline `height`/`width` may be ignored for non-compound nodes or overridden by the stylesheet.

**Fix:** Ensure tables match a CSS selector that respects their `_tableWidth`/`_tableHeight` data, or explicitly set `width`/`height` as CSS properties that cytoscape applies to non-compound nodes. The COMPOUND_STYLES in `graphStyles.js` may only apply to actual compound parents.
