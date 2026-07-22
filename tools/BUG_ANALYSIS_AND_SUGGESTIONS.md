# Data Flow Debugger — Bug List

> **Date:** 2026-07-22 | **Version:** 3.3.56 | **Active:** 3

---

## Bug 1: L2 Edge Click — NONE sql_range — FIXED ✅ v3.3.56

0/5 scripts have NONE-range edges.

---

## Bug 2: Taxi Edge Invisible at dx=0 — FIXED ✅ v3.3.57

Changed to `curve-style: bezier`, minScreenPx=1.87 — visible.

---

## Bug 3: Orange Highlight Never Changes or Disappears (P1)

**Symptom:** Clicking any edge highlights the entire 7-line script in orange. Clicking a different edge shows the same orange — no visual change. Pressing Escape or clicking repeatedly doesn't clear it.

**Evidence (step3):** All 4 edges have `sql_range=[1,7]` — every edge highlights the ENTIRE script. Click #1→#4 all show the same 7 orange lines.

**Root cause — two issues:**
1. `_estimate_sql_range` gives all edges the same wide range `[1,7]` — no specificity per edge type
2. `SqlPanel.jsx` uses `data-line` as implicit React key. When `sqlHighlightRange` changes, React reuses DOM nodes without updating the `edge-highlighted` CSS class

**Fix:**
- **Part 1:** `dataflow_service.py` — partition edge ranges by type (FILTER→L5-6, JOIN→L5, TABLE_FLOW→L4)
- **Part 2:** `SqlPanel.jsx:315` — add unique key: `key={${scriptName}-${lineNum}-${isEdgeHighlighted}}`

---

## Historical — Clean

| Check | Result |
|-------|:------:|
| Pipeline==Spore | ✅ Fixed |
| Partition overlap | ✅ 19/19 pass |
| L2 collapse | ✅ Fixed |
| Spore overlaps | ✅ Fixed |
| Regression (21 checks) | ✅ All pass |
