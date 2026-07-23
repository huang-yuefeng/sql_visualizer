# Bug History — Fixed Defects

> **Date:** 2026-07-23 | **Versions:** v3.3.51 – v3.3.70

---

## Bug 2: Orange Highlight Never Clears (P1) — FIXED ✅ v3.3.62

### Symptom

After pressing Escape to deselect an edge in the L2 graph, 1-2 SQL lines retained their orange highlight background. Different edges with different `sql_range` both set highlight=true for the same lines.

### Root Cause

`frontend/src/components/SqlPanel.jsx:316` used a **boolean** in the React key:
```jsx
<div key={`${scriptName}-${lineNum}-${isEdgeHighlighted}`} ...>
```
When two different edges highlighted overlapping lines (e.g., both set `isEdgeHighlighted=true` for line 4), React saw the same key and reused the DOM node without updating the CSS class. Pressing Escape cleared `sqlHighlightRange` to null, but `isEdgeHighlighted` remained stale in the closure.

### Fix Applied (committed `0a4955a`)

`frontend/src/components/SqlPanel.jsx:316`:
```jsx
// BEFORE:
key={`${scriptName}-${lineNum}-${isEdgeHighlighted}`}
// AFTER:
key={`${scriptName || "sql"}-${lineNum}-${sqlHighlightRange?.join("-") || "none"}`}
```
Now each unique range produces a unique key (e.g., `"step2-4-2-1-3-1"`), so React properly recreates the DOM element when the range changes or clears.

### Escape Handler (verified working)

`frontend/src/DataFlowApp.jsx:380-384`:
```jsx
if (e.key === "Escape") {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    setGraphLevel("L1");
    setSelectedEdge(null);
    setSqlHighlightRange(null);
}
```

### Files Involved
- `frontend/src/components/SqlPanel.jsx:316` — React key
- `frontend/src/DataFlowApp.jsx:380-384` — Escape handler

---

## Bug 4: FILTER Range Missing Continuation Lines (P3) — FIXED ✅ v3.3.69

### Symptom

In `step2_enrich_customers.sql`, clicking the FILTER edge highlighted only line 5 (`WHERE c.is_active = 1`) but missed line 6 (`AND c.region IN ('NA', 'EMEA', 'APAC')`).

### Root Cause

`sql_range_finder.py:410`:
```python
max_extend = max(1, min(3, total_lines // 10))  # = 1 for short scripts (≤20 lines)
```
FILTER used forward-only extension with `max_extend=1`, extending only 1 line from the WHERE keyword line. The WHERE clause spanned 2 lines (WHERE + AND continuation), so the AND continuation was outside the range.

### Fix Applied (two-part, working tree)

**Part A — Clause continuation** (`sql_range_finder.py:432-450`):
```python
# Clause continuation: extend forward past multi-line AND/OR clauses
clause_types = {'FILTER', 'WHERE', 'HAVING', 'JOIN', 'GROUP_BY', 'ORDER_BY'}
if edge_type in clause_types:
    stmt_keys = {'SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT', 'RIGHT',
                'INNER', 'OUTER', 'CROSS', 'FULL', 'GROUP', 'ORDER',
                'HAVING', 'LIMIT', 'UNION', 'INSERT', 'UPDATE', 'DELETE',
                'CREATE', 'ALTER', 'DROP', 'WITH'}
    while end_line + 1 <= stmt_end_0:
        nxt = self.all_lines[end_line + 1].strip()
        if not nxt or nxt.startswith('--') or nxt.startswith('/*'):
            end_line += 1; continue
        nxt_u = nxt.upper()
        if any(nxt_u.startswith(kw + ' ') or nxt_u == kw for kw in stmt_keys):
            break
        end_line += 1
```
After the initial range is determined, extends forward past blank lines, comments, and continuation lines until hitting the next SQL keyword (SELECT, FROM, WHERE, etc.).

**Part B — edge_type propagation** (`dataflow_service.py:1454`):
```python
enriched["edge_type"] = edge_type  # 🔧 Bug 4 fix: edge_type was missing from enriched
```
The `enriched` dict (passed to `find_sql_range`) was missing `edge_type`, so the range finder couldn't apply type-specific logic. Now explicitly propagated.

### Verification

Before: FILTER range `[5, 1, 5, 1]` — only line 5
After: FILTER range `[5, 1, 6, 1]` — lines 5-6 (WHERE + AND)

### Files Involved
- `backend/app/services/sql_range_finder.py:410` — max_extend
- `backend/app/services/sql_range_finder.py:432-450` — clause continuation
- `backend/app/services/dataflow_service.py:1454` — edge_type propagation

---

## Bug 5: Alias Length Filter Drops Legitimate Tables (P3) — FIXED ✅ v3.3.69

### Symptom

Short table names like `app`, `job`, `dim`, `log`, `tag`, `fee` were silently dropped from the L1 overview graph. Only actual aliases like `so`, `c`, `t` should be filtered.

### Root Cause

`dataflow_service.py` used a naive length heuristic at 4 locations:
```python
if len(name) <= 3 and name.islower() and name.isalpha():
    # blindly treat ALL 3-letter lowercase names as aliases
```
This heuristic was redundant with the semantic alias check already present at line 374:
```python
if src_tables:
    aliases.add(name)  # correctly identifies aliases by source_tables relationship
```

### Fix Applied (working tree)

All 4 length-heuristic instances replaced with semantic `tname in aliases` checks:

| Location | Old (v3.3.65) | New (v3.3.66) |
|----------|--------------|----------------|
| Line 377 | `if name and len(name) <= 3 and name.islower() ... aliases.add(name)` | Removed (comment: "Bug 5 fix: removed length heuristic") |
| Line 397 | `if len(tname) <= 3 and tname.islower() ... continue` | `if tname in aliases: continue` |
| Line 404 | `if len(tname) <= 3 and tname.islower() ... continue` | `if tname in aliases: continue` |
| Line 411 | `if len(tname) <= 3 and tname.islower() ... continue` | `if tname in aliases: continue` |

The `aliases` set is populated at line 374 by the semantic check — only variables with `source_tables` pointing to another table are added. The length heuristic was an over-approximation that caught real aliases (`so`, `c`, `t`) but also false-positived on legitimate short table names.

### Note: Line 1253

A similar `len(label) <= 3 and label.islower()` heuristic remains at line 1253 in `_build_l2_graph`. This is a **different context** — it detects aliases within the L2 per-script graph by checking column-to-table SCHEMA edges. It operates on the `label` field of L2 nodes (not L1 table names) and is guarded by `vt in ("table", "view")`. This instance may be harmless but should be evaluated separately.

### Files Involved
- `backend/app/services/dataflow_service.py:374-378` — alias detection (semantic + old heuristic)
- `backend/app/services/dataflow_service.py:397-412` — L1 table node filtering
- `backend/app/services/dataflow_service.py:1253` — L2 alias detection (separate context)

### How to Verify

```bash
cd backend && grep -n 'len(.*) <= 3.*islower' app/services/dataflow_service.py
# Should only show line 1253 (L2 context), not 377/397/404/411
```

---

## Bug 2: Original Root Cause Analysis (from original doc)

**Symptom:** 1-2 orange lines persist after Escape across all scripts.

**Root cause:** `SqlPanel.jsx:316`:
```jsx
<div key={`${scriptName}-${lineNum}-${isEdgeHighlighted}`} ...>
```
The key uses a **boolean**. Two different edges with different `sql_range` both set `isEdgeHighlighted=true` for the same lines → React sees same key → reuses DOM without updating class.

**Fix (`SqlPanel.jsx:316`):**
```jsx
key={`${scriptName}-${lineNum}-${sqlHighlightRange?.join('-') || 'none'}`}
```

---

## Bug 3: Original Root Cause Analysis (from original doc)

**Symptom:** 4/5 scripts have 3-4 lines covered by 2+ edges.

**Root cause:** `sql_range_finder.py:537` `partition_edge_ranges` runs after `find_sql_range` but edges with compound types like `"FILTER,JOIN,TABLE_FLOW"` share the same initial range before partitioning. Post-partition narrowing can't fully separate them because original ranges were identical.

**Fix:** Split compound edge types into separate edges BEFORE `find_sql_range`, so each single-type edge gets its own range from the start:
```python
# In dataflow_service.py, before find_sql_range:
for e in edges:
    etype = e.get('edge_type', '')
    if ',' in etype:
        for part in etype.split(','):
            single_edge = {**e, 'edge_type': part.strip()}
            # compute range for this single type
```

---

## Bug 4: Original Root Cause Analysis (from original doc)

**Symptom:** step2 FILTER highlights `WHERE c.is_active = 1` but misses `AND c.region IN (...)`.

**Root cause:** `sql_range_finder.py:410`:
```python
max_extend = max(1, min(3, total_lines // 10))  # = 1 for short scripts
```
FILTER uses forward-only extension (line 429): extends only 1 line from WHERE keyword. The WHERE clause is 2 lines (WHERE + AND continuation).

**Fix (`sql_range_finder.py`, after line 430):**
```python
# Extend while next line is a continuation of the same clause
while end_line + 1 <= stmt_end_0:
    nxt = self.all_lines[end_line + 1].strip().upper()
    if nxt.startswith(('AND ', 'OR ')):
        end_line += 1
    else:
        break
```

---

## Bug 5: Original Root Cause Analysis (from original doc)

**Symptom:** Short table names like `app`, `job`, `dim`, `log`, `tag`, `fee` silently dropped from L1 graph. Only aliases like `so`, `c`, `t` should be filtered.

**Root cause:** `dataflow_service.py:377` — `len(name) <= 3 and name.islower()` adds ALL 3-letter lowercase names to alias set, regardless of whether they're actually aliases. Same heuristic repeated at lines 397, 404, 411.

**Evidence:** A semantic alias check already exists at line 374 (`if src_tables: aliases.add(name)`) — if a variable has `source_tables` pointing to another table, it IS an alias. The length heuristic is redundant AND wrong.

**Fix — delete 4 lines:**
```
Line 377: DELETE  if name and len(name) <= 3 and name.islower() and name.isalpha():
Line 378: DELETE      aliases.add(name)
Line 397: DELETE  if len(tname) <= 3 and tname.islower() and tname.isalpha():
Line 398: DELETE      continue
Line 404: DELETE  if len(tname) <= 3 and tname.islower() and tname.isalpha():
Line 405: DELETE      continue  
Line 411: DELETE  if len(tname) <= 3 and tname.islower() and tname.isalpha():
Line 412: DELETE      continue
```
The semantic check at line 374 already handles alias detection correctly.

---

## Fixed (Chronological)

| Bug | Version | Commit |
|-----|:------:|--------|
| Taxi edge invisible | v3.3.57 | — |
| NONE sql_range | v3.3.56 | — |
| Pipeline==Spore | v3.3.51 | — |
| L2 collapse | v3.3.53 | — |
| Spore overlaps | v3.3.53 | — |
| DML edge direction | v3.3.64 | — |
| Architecture unified (single sql_range_finder) | v3.3.65 | — |
| Orange highlight persistence (Bug 2) | v3.3.62 | `0a4955a` |
| FILTER range continuation (Bug 4) | v3.3.69 | working tree |
| Alias length filter (Bug 5) | v3.3.69 | working tree |
---

# Older Fixed Bugs (v3.3.1) — Regression Test Checklist

> **Date:** 2026-07-20 | **Version:** 3.3.1 | **Bugs fixed:** 10
> **Re-run command:** `python3 /tmp/regression_test.py` (API) + E2E `node simulated_user.js --quick`

---

## R1: Resize Handle Direction (Bug #1.1)

**Was:** Dragging L2 divider right expanded L2 instead of shrinking it.
**Fix:** `DataFlowApp.jsx:52,56` — added `invert: true` to `l2Resize` and `sqlResize`.

**Test:** Drag L2 handle right → L2 panel shrinks. Drag SQL handle down → SQL panel shrinks.
```js
// Verification:
const box = await page.locator('.resize-handle').nth(1).boundingBox();
const before = await page.evaluate(() => document.querySelector('.panel-inline-l2')?.offsetWidth);
await page.mouse.move(box.x + 4, box.y + box.height/2);
await page.mouse.down();
await page.mouse.move(box.x + 4 + 80, box.y + box.height/2, { steps: 5 });
await page.mouse.up();
const after = await page.evaluate(() => document.querySelector('.panel-inline-l2')?.offsetWidth);
// after < before → PASS
```

---

## R2: sql_range Comment-Only Highlights (Bug #1.2a)

**Was:** Clicking L2 edge highlighted `-- Step 1: Load raw orders` (comment lines).
**Fix:** `dataflow_service.py:1687` — added `if stripped.startswith('--'): continue` in keyword matching.

**Test:** Open any L2 script, click an edge, verify no highlighted lines are comment-only.
```python
# API verification:
l2 = requests.get(f"{BASE}/workspace/{ws}/views/{view_id}/level2", params={"script": script, "filter": "false"})
for e in l2.json()["graph"]["edges"]:
    sr = e["data"].get("sql_range")
    if sr:
        hl = sql_lines[sr[0]-1:sr[2]]
        assert not all(l.strip().startswith('--') for l in hl), f"Comment-only range: {sr}"
```

---

## R3: _extend_to_statement Clause Keywords (Bug #1.2b)

**Was:** Backward extension stopped at `FROM`, `JOIN`, `WHERE` — highlighting only fragments.
**Fix:** `dataflow_service.py:1619` — `STMT_START_KW` only has statement-level keywords (`WITH`, `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `UNION`). Clause keywords removed.

**Test:** Click L2 edge, verify highlighted range spans the full SQL statement (e.g., `INSERT...SELECT...FROM...WHERE`), not just a fragment (e.g., `FROM...WHERE`).
```python
# Verify range covers from INSERT/SELECT to semicolon:
assert sr[0] <= first_sql_line  # starts at or before first SQL keyword
assert sr[2] >= last_sql_line   # ends at or after last SQL clause
```

---

## R4: Cy Instance Overwritten by L2 (Bug #1.3)

**Was:** After opening L2 #1 and closing with Escape, clicking L1 script nodes for L2 #2-#5 failed with `node_not_found`.
**Fix:** `useCytoscapeGraph.js` — L1 cy instance preserved via `window.__cy1` backup/restore.

**Test:** Open→close 3+ L2 scripts sequentially. All should open with correct SQL content.
```js
// Browser test:
for (let i = 0; i < 3; i++) {
  const sn = cy.nodes('[type="script_node"]').eq(i);
  sn.emit('dbltap');
  await wait(2000);
  const l2Open = !!document.querySelector('.panel-inline-l2');
  const sqlLines = document.querySelectorAll('.sql-line').length;
  console.assert(l2Open && sqlLines > 0, `L2 #${i+1} failed`);
  pressEscape();
  await wait(1000);
}
```

---

## R5: Tables/Scripts Interleaved by Pipeline Layer (Bug #2.1)

**Was:** All tables in rows 0-1, all scripts in rows 3-6 — 620px vertical gaps.
**Fix:** `dataflow_service.py:649-667` — combined list sorted by layer, each layer gets its own row.

**Test:** Layers alternate: L0 tables → L1 scripts → L2 tables → L3 scripts (not all tables then all scripts).
```python
# Verify nodes flow by layer: tables and scripts alternate rows
layers_seen = []
for n in sorted_nodes_by_y:
    layer = n["data"]["layer"]
    is_table = n["data"]["type"].endswith("_table")
    layers_seen.append((layer, "T" if is_table else "S"))

# Verify not all tables first: count transitions
transitions = sum(1 for i in range(1, len(layers_seen)) if layers_seen[i][1] != layers_seen[i-1][1])
# With alternating layers, expect at least 4 transitions
assert transitions >= 4, f"Only {transitions} table/script transitions"
```

---

## R6: Edge Vertical Spans (Bug #2.2, multi_workflow)

**Was:** Edges spanned 620px vertically (6+ rows) — bezier curves overlapping.
**Fix:** Follows from R5 — interleaved tables+scripts means edges are mostly horizontal/same-row.

**Test:** Upload multi_workflow, verify max vertical edge distance < 400px.
```python
max_dy = 0
for e in l1["edges"]:
    sy = node_pos[e["data"]["source"]][1]
    ty = node_pos[e["data"]["target"]][1]
    max_dy = max(max_dy, abs(sy - ty))
assert max_dy < 400, f"Max edge span: {max_dy}px"
```

---

## R7: Frontend/Backend Parameter Match (Bug #2.4)

**Was:** Frontend used `maxNodesPerRow=4, nodeSpacing=220` vs backend `3, 320` — nodes jumped on mount.
**Fix:** `pipelineLayout.js:15-17` — `MAX_PER_ROW=3, NODE_SPACING=320, TABLE_ROW_H=280` matching backend.

**Test:** Verify `pipelineLayout.js` constants match `dataflow_service.py` constants.
```bash
grep "MAX_PER_ROW\|NODE_SPACING\|TABLE_ROW_H" frontend/src/utils/pipelineLayout.js
grep "MAX_PER_ROW\|NODE_SPACING\|TABLE_ROW_H" backend/app/services/dataflow_service.py
# Verify: MAX_PER_ROW=3, NODE_SPACING=320, TABLE_ROW_H=280 match
```

---

## R8: Layer Assignment for multi_workflow (Bug #5.1a)

**Was:** All 12 top-level nodes had `layer: 0` — no pipeline ordering.
**Fix:** `dataflow_service.py:602-637` — BFS layer propagation from source nodes.

**Test:** Upload multi_workflow, verify ≥5 unique layers.
```python
layers = set()
for n in l1["nodes"]:
    if not n["data"].get("parent") and n["data"].get("type") != "field":
        layers.add(n["data"].get("layer", "?"))
assert len(layers) >= 5, f"Only {len(layers)} unique layers"
```

---

## R9: sql_range Spans Entire File (Bug #5.2)

**Was:** For complex CTE scripts, all edges had `sql_range` covering the full 38-line file.
**Fix:** `_extend_to_statement` improvements — proper statement boundary detection.

**Test:** Upload tpcds_qualified, check all L2 edges — no range should span >50 lines.
```python
for e in l2["graph"]["edges"]:
    sr = e["data"].get("sql_range")
    if sr and sr[2] - sr[0] > 50:
        assert False, f"Edge {e['data']['id']} spans {sr[2]-sr[0]} lines"
```

---

## R10: SQL Panel Max-Height (Bug #19) + Snake Toggle (Bug #20)

**Was:** SQL panel capped at 300px (CSS `max-height`). Snake/Pipeline toggle did nothing (web-worker error).
**Fix:** `app.css:614` — removed `max-height: 300px`. `vite.config.js` — web-worker build config.

**Test (SQL panel):**
```js
const maxH = getComputedStyle(document.querySelector('.inline-l2-sql')).maxHeight;
console.assert(maxH === 'none', `SQL max-height is ${maxH}, expected none`);
```

**Test (Snake toggle):**
```js
const before = cy.nodes()[0].position().x;
// Click toggle, wait
const after = cy.nodes()[0].position().x;
console.assert(before !== after, 'Positions did not change after toggle');
```

---

## Automated Re-Run

```bash
# API regression tests
python3 /tmp/regression_test.py

# E2E regression tests  
cd tools/e2e_test && node simulated_user.js --quick
```
