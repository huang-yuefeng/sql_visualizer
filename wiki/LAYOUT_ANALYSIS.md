# Data Flow Debugger — Layout Analysis & Recommendations (v7)

> **Date:** 2026-07-20 | **Reviewed:** 2026-07-30
> **Version:** 3.2.25 (analysis) / 3.3.104 (review)
> **Status:** ✅ All 6 defects fixed as of v3.3.104. This document is a historical reference.
>
> - Defect 1 (resize inversion): fixed — `invert: true` added to `l2Resize`/`sqlResize`
> - Defects 2-3 (layers/edges/turn-edges): fixed — layout rewritten to interleave by layer; `pipelineLayout.js` removed
> - Defect 4 (param mismatch): fixed — backend positions now consistent
>
> **Test case:** `multi_workflow` (5 scripts, 12 top-level nodes, 11 edges)
> **Method:** API data extraction + frontend layout logic analysis + chromium screenshot

---

## 1. Resize Handle Direction — Confirmed Bug

### Root cause

`DataFlowApp.jsx:51-57` — `l2Resize` and `sqlResize` missing `invert: true`.

### Layout diagram:

```
┌───────────┬────┬──────────────────┬────┬───────────┐
│   LEFT    │ ║  │     CENTER       │ ║  │    L2     │
│  (260px)  │ ║  │    (flex:1)      │ ║  │  (420px)  │
│           │ ║  │                  │ ║  ├───────────┤
│           │ ║  │                  │ ║  │   SQL     │
│           │ ║  │                  │ ║  │  (250px)  │
└───────────┴────┴──────────────────┴────┴───────────┘
  leftResize      l2Resize            sqlResize
  (OK)            (NEEDS invert)      (NEEDS invert)
```

| Handle | Panel controlled | Drag direction | Expected value change | Without invert | With invert |
|--------|-----------------|---------------|----------------------|----------------|-------------|
| `leftResize` | Left panel (left of handle) | Right → wider | Increase | `startValue + delta` ↑ ✅ | — |
| `l2Resize` | L2 panel (right of handle) | Right → narrower | **Decrease** | `startValue + delta` ↑ ❌ | `startValue - delta` ↓ ✅ |
| `sqlResize` | SQL panel (below handle) | Down → shorter | **Decrease** | `startValue + delta` ↑ ❌ | `startValue - delta` ↓ ✅ |

**Fix:**
```
DataFlowApp.jsx line 51:  add `invert: true` to l2Resize
DataFlowApp.jsx line 55:  add `invert: true` to sqlResize
```

---

## 2. Snake Mode Display — Verified Defects

### Test data: multi_workflow (5-step pipeline)

Expected pipeline flow:
```
raw_orders(L0) → step1(L1) → stg_orders(L2) → step3(L3) → analytics_orders(L4) → step4(L5) → daily_summary(L6) → step5(L7) → output(L8)
crm_customers(L0) → step2(L1) → stg_customers(L2) → step3(L3)
```

Nodes should be arranged left-to-right by layer, with related nodes near each other.

### Defect 2.1: Layers are scrambled — pipeline order is broken

Actual backend snake-wrap positions:

```
Row 0 (y= 60): (100) crm_customers[L0]  (420) raw_orders[L0]  (740) stg_customers[L2]  ← L2 with L0!
Row 1 (y=340): (420) stg_orders[L2]
Row 2 (y=650): (100) analytics_orders[L4]  (100) step1[L1]  (420) step2[L1]  (740) step3[L3]  ← chaos!
Row 3 (y=900): (420) daily_summary[L6]
Row 4 (y=980): (420) step4[L5]  ← L5 AFTER L6!
Row 5 (y=1280):(100) step5[L7]
Row 6 (y=1580):(420) output[L8]
```

**Problems visible:**
- `stg_customers[L2]` sits in Row 0 with source tables, far from `step2[L1]` that produces it
- Row 2 mixes L1, L3, L4 nodes at the same Y level — no visual pipeline ordering
- `step4[L5]` at y=980 is **below** `daily_summary[L6]` at y=900 — the pipeline order is visually inverted!
- Pipeline stages are not readable left-to-right

**Root cause:** `dataflow_service.py:647-658` separates tables and scripts into two independent lists, places each with independent snake-wrap, then concatenates the rows. The `layer` field is used for sorting **within** each group, but tables and scripts never interleave.

### Defect 2.2: Edges span huge vertical distances — massive overlap

```
raw_orders(420,60)  →  step1(100,680)    dy=620px (spans 6+ rows)
step1(100,680)      →  stg_orders(420,340)  dy=340px (crosses back UP)
step2(420,680)      →  stg_customers(740,60) dy=620px (crosses back UP to row 0!)
step3(740,680)      →  analytics_orders(100,620) dx=640px (crosses 3 columns LEFT)
```

Because tables and scripts are in separate row groups, every table↔script edge spans multiple rows. With `curve-style: bezier`, these long diagonal edges overlap in the center of the graph, creating a tangled mess.

In particular: `step2 → stg_customers` goes from y=680 all the way back UP to y=60 — this 620px vertical edge crosses through 6 other node rows.

### Defect 2.3: Snake reversal creates meaningless R→L rows

Rows with only 1 node (Rows 1, 3, 4, 5, 6) are flagged as `R→L` (snake reversal), but with a single node, the reversal just nudges its X position. The alternating direction adds no value and makes the layout harder to scan.

### Defect 2.4: Frontend re-applies layout with different parameters

| Parameter | Backend | Frontend | Effect |
|-----------|---------|----------|--------|
| `MAX_PER_ROW` | 3 | 4 | Different column count |
| `NODE_SPACING` | 320 | 220 | Nodes 100px closer |
| `TABLE_ROW_H` | 280 | 180 | Tables 100px tighter vertically |
| `SCRIPT_ROW_H` | 300 | 220 | Scripts 80px tighter |

When `DataFlowGraph.jsx:84-92` fires the `layoutMode` effect (100ms after mount), it re-positions all nodes with different spacing. Nodes visibly jump from backend positions to frontend positions.

### Defect 2.5: `artificial turn edges` connect unrelated nodes

`_addTurnEdges` (`pipelineLayout.js:251-293`) connects the last node of each row to the first node of the next row. For multi_workflow, this creates 5-6 dashed orange edges between row-end and next-row-start nodes that have **no actual data flow relationship**. Users see these and try to interpret them as real dependencies.

---

## 3. Why These Defects Occur — The Architecture Problem

The core issue is the **separation of tables and scripts** in the layout algorithm:

```python
# dataflow_service.py:647-658
table_nodes = []   # All tables go here
script_nodes = []  # All scripts go here
for n in nodes:
    if t.endswith("_table"): table_nodes.append(n)
    elif t == "script_node": script_nodes.append(n)

# Position tables first (rows 0..N)
# Then position scripts (rows N+1..M)
```

This creates two independent snake-wrap sequences that are stacked vertically. A pipeline like `table → script → table → script` gets laid out as:

```
TABLE ROW 0:   table_A    table_B    table_C
TABLE ROW 1:   table_D
SCRIPT ROW 2:  script_1   script_2   script_3
SCRIPT ROW 3:  script_4   script_5
```

When it SHOULD be:

```
COL 0        COL 1        COL 2        COL 3        COL 4
table_A  →  script_1  →  table_C  →  script_3  →  table_D
table_B  →  script_2  →            →  script_4  →  script_5
```

---

## 4. Recommended Fix Approach

### Option A: Interleave tables and scripts by layer (small change, big impact)

Instead of separating into two lists, sort ALL top-level nodes by their `layer` field (which the backend already computes via topological sort), then snake-wrap the combined list:

```python
# Instead of separating:
all_nodes = table_nodes + script_nodes
all_nodes.sort(key=lambda n: n["data"].get("layer", 999))

# Snake-wrap the combined list
for idx, n in enumerate(all_nodes):
    col = idx % MAX_PER_ROW
    row = idx // MAX_PER_ROW
    n["data"]["x"] = col * NODE_SPACING + 100
    n["data"]["y"] = row * ROW_HEIGHT + 60
```

**What changes:**
- `raw_orders[L0]` and `step1[L1]` appear in the same row, connected visually
- Edges become horizontal (same-row) or short diagonals (adjacent rows)
- No more 620px vertical edges crossing 6 rows
- No need for `_addTurnEdges` — natural flow
- Kill the snake reversal (always L→R)

**Result for multi_workflow:**
```
Row 0: raw_orders[L0]  crm_customers[L0]  stg_customers[L2]
Row 1: step1[L1]       step2[L1]          stg_orders[L2]
Row 2: step3[L3]       analytics_orders[L4]
Row 3: step4[L5]       daily_summary[L6]
Row 4: step5[L7]       output[L8]
```

This is much closer to a readable pipeline. `step1` is near `raw_orders`, `step3` is near `stg_orders` and `analytics_orders`.

### Option B: Use ELK layered layout (already integrated, cleaner)

ELK.js `layered` algorithm does exactly this: topological sort → layer assignment → column placement → edge routing. It's already loaded in `elkLayout.js`. Switch `useDataLineageOrder` default to `false` to let ELK handle it.

```js
// DataFlowGraph.jsx:87-91 — change default:
{ useDataLineageOrder: false }  // let ELK do it instead of _pipelineLayout
```

### Option C: Match frontend params to backend (quick fix for jumping)

If keeping snake-wrap, at minimum match the parameters:

```js
// DataFlowGraph.jsx:87-91:
await applyWorkflowLayout(cy, { 
  rowHeight: 300,       // match SCRIPT_ROW_H
  nodeSpacing: 320,     // match NODE_SPACING
  maxNodesPerRow: 3,    // match MAX_PER_ROW
  useDataLineageOrder: true 
});
```

---

## 5. Summary

| Defect | Verified | Root cause | Recommended fix |
|--------|----------|-----------|-----------------|
| Resize inverted | Yes | Missing `invert: true` | Add 2 lines to `DataFlowApp.jsx` |
| Layers scrambled | Yes | Tables/scripts sorted separately, not interleaved | Sort combined list by layer (`Option A`) |
| Long overlapping edges | Yes | Tables and scripts in separate row groups | Interleave by layer → edges become short |
| Snake reversal R→L | Yes | Alternating direction per row | Remove reversal (always L→R) |
| Parameter mismatch | Yes | Frontend uses different spacing than backend | Match params (`Option C`) or use ELK (`Option B`) |
| Artificial turn edges | Yes | `_addTurnEdges` connects unrelated row-end nodes | Remove when switching to interleaved layout |
