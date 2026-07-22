# Data Flow Debugger — Bug List

> **Date:** 2026-07-22 | **Version:** 3.3.56 | **Active:** 3

---

## Bug 1: L2 Edge Click — NONE sql_range — FIXED ✅ v3.3.56

0/5 scripts have NONE-range edges.

---

## Bug 2: Taxi Edge Invisible at dx=0 — FIXED ✅ v3.3.57

Changed to `curve-style: bezier`, minScreenPx=1.87 — visible.

---

## Bug 3: Orange Highlight Never Disappears (P1) — BROKEN v3.3.59

**Trend:** v3.3.55=7, v3.3.58=4, v3.3.59=7 lines (regressed).

**Two root causes:**
1. All edges share same wide `sql_range` → clicking different edges shows same highlight
2. React doesn't clear `edge-highlighted` CSS class on Escape — DOM class persists after state change

**Fix:** Part 1: `dataflow_service.py` — per-edge-type ranges. Part 2: `SqlPanel.jsx:315` — unique React key with highlight state.

---

## Historical — Clean

| Check | Result |
|-------|:------:|
| Pipeline==Spore | ✅ Fixed |
| Partition overlap | ✅ 19/19 pass |
| L2 collapse | ✅ Fixed |
| Spore overlaps | ✅ Fixed |
| Regression (21 checks) | ✅ All pass |
