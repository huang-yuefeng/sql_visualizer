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

---

## Bug 1: Duplicate Output Nodes — FIXED ✅ v3.3.72

## Bug 1: Duplicate Output Nodes — FIXED ✅ v3.3.72

### Fix applied (three-step edge routing)

The `qo_` node has been eliminated. All edges now route through the existing `"⟐ output"` intermediate_table via three steps at `dataflow_service.py:1602-1634`:

```python
intermediate_id = None
for tn in table_nodes.values():
    if isinstance(tn, dict) and tn.get("type") == "intermediate_table":
        intermediate_id = tn.get("id"); break

dml_targets = set(); dml_sources = set()
for e in new_edges:
    if "DML" in e.get("edge_type", "").upper():
        dml_targets.add(e.get("target", ""))
        dml_sources.add(e.get("source", ""))

for e in new_edges:
    src, tgt, etype = e.get("source",""), e.get("target",""), e.get("edge_type","")
    # Step 1: Suppress TABLE_FLOW bypass edges (replaced by source→⟐→target chain)
    if (src in dml_sources and tgt in dml_targets
        and etype == "TABLE_FLOW"
        and src != intermediate_id and tgt != intermediate_id):
        continue
    # Step 2: Redirect non-DML bypass edges to ⟐ output (TRANSFORM, AGGREGATE, etc.)
    if (src in dml_sources and tgt in dml_targets
        and "DML" not in etype.upper()
        and etype != "TABLE_FLOW"
        and src != intermediate_id and tgt != intermediate_id
        and intermediate_id):
        e["target"] = intermediate_id          # redirect to output
        new_dml_edges.append(e)
        continue
    # Step 3: Replace DML edges with ⟐ output → target (TABLE_FLOW)
    if "DML" in etype.upper() and intermediate_id:
        output_edge = dict(e)
        output_edge["source"] = intermediate_id
        output_edge["edge_type"] = "TABLE_FLOW"
        new_dml_edges.append(output_edge)
    else:
        new_dml_edges.append(e)
```

### Verified topology (all 5 scripts, v3.3.72)

```
step1: raw_orders        ──[TABLE_FLOW]──> ⟐ output ──[TABLE_FLOW]──> stg_orders
step2: crm_customers     ──[TABLE_FLOW]──> ⟐ output ──[TABLE_FLOW]──> stg_customers
       crm_customers     ──[FILTER]──────> ⟐ output
step3: stg_orders        ──[TABLE_FLOW]──> ⟐ output ──[TABLE_FLOW]──> analytics_orders
       stg_customers     ──[TABLE_FLOW]──> ⟐ output
       stg_orders        ──[FILTER]──────> ⟐ output
       stg_orders        ──[JOIN]────────> ⟐ output
       stg_customers     ──[JOIN]────────> ⟐ output
step4: analytics_orders  ──[TABLE_FLOW]──> ⟐ output ──[TABLE_FLOW]──> daily_summary
       analytics_orders  ──[TRANSFORM]───> ⟐ output
       analytics_orders  ──[AGGREGATE]───> ⟐ output
step5: daily_summary     ──[TABLE_FLOW]──> ⟐ output
       daily_summary     ──[TRANSFORM]───> ⟐ output
```

All edges converge on `⟐ output` — the output node is the trunk of the data flow.

### How Step 2 catches the bypass (v3.3.72 fix)

**The output node is the trunk of the data flow.** Between source and target, all operations happen within the SELECT. The output node sits in the middle — all intermediate edges connect TO it:

Step 2 of the edge routing loop intercepts TRANSFORM/AGGREGATE edges that go directly to the DML target and redirects them to `⟐ output`:
```python
# Step 2: Redirect non-DML bypass edges to ⟐ output (TRANSFORM, AGGREGATE, etc.)
if (src in dml_sources and tgt in dml_targets
    and "DML" not in etype.upper()
    and etype != "TABLE_FLOW"
    and src != intermediate_id and tgt != intermediate_id
    and intermediate_id):
    e["target"] = intermediate_id          # redirect to output!
```

Why `analytics_orders` is in `dml_sources`: after field promotion, the DML edge `ao.region --[DML]--> daily_summary` becomes `analytics_orders --[DML]--> daily_summary` (column promoted to parent table). So `analytics_orders` is a DML source, and the TRANSFORM edge `analytics_orders --[TRANSFORM]--> daily_summary` matches the bypass condition.

### Design note (for reference)

The root cause was that field promotion assigns computed fields (`dt`, `cnt`, `total`) to the wrong parent table when `source_tables=[]`. The Step 2 redirect fixes this at the edge level. A cleaner approach would fix it at the parent assignment level — see [Anatomy of the problem](#anatomy-of-the-problem) below.

### The output node as the trunk

```
analytics_orders                           daily_summary
       │                                         ▲
       │  ┌──────────────────────────┐           │
       ├─>│ DATE()  TRANSFORM → dt   │──┐        │
       ├─>│ SUM()   AGGREGATE → total│──┤        │
       │  └──────────────────────────┘  │        │
       │                                ▼        │
       └────────[TABLE_FLOW]────────> ⟐ output ──┘
                                      (trunk)
```

The `⟐ output` node is not a branch — it exists to **complete the chain** between source and target. Without it, intermediate operations (TRANSFORM, AGGREGATE) have nowhere to connect in the middle. They shouldn't bypass the trunk and connect directly to the target.

**Actual topology (v3.3.71):**
```
analytics_orders ──[TABLE_FLOW]──> ⟐ output ──[TABLE_FLOW]──> daily_summary    ✅ trunk
analytics_orders ──[TRANSFORM ]──> daily_summary                                 ❌ bypasses trunk
analytics_orders ──[AGGREGATE ]──> daily_summary                                 ❌ bypasses trunk
```

**Expected topology:**
```
analytics_orders ──[TABLE_FLOW]──> ⟐ output ──[TABLE_FLOW]──> daily_summary    ✅ trunk
analytics_orders ──[TRANSFORM ]──> ⟐ output                                     ✅ into trunk
analytics_orders ──[AGGREGATE ]──> ⟐ output                                     ✅ into trunk
```

### Root cause at the syntax tree level

The extractor produces these edges at field level:
```
ao.order_date --[TRANSFORM]--> dt       (dt = DATE(ao.order_date))
ao.amount     --[AGGREGATE]--> total    (total = SUM(ao.amount))
dt            --[DML]-------> daily_summary
total         --[DML]-------> daily_summary
```

And these SCHEMA ownership edges:
```
⟐ output --[SCHEMA]--> dt      ("dt is a column of the SELECT result")
⟐ output --[SCHEMA]--> total   ("total is a column of the SELECT result")
```

The SCHEMA edges already tell us: **`dt` and `total` belong to `⟐ output`**. When fields are promoted to their parent tables, the parent should be determined by **who owns the field**, not by iteration order.

**The bug at `_build_l2_graph:1358-1360`:**
```python
if not parent_table_id and table_nodes:
    parent_table_id = list(table_nodes.values())[0]["id"]  # arbitrary first table
```

`dt` and `total` have no `source_tables`. The code picks the first table in dict order. For INSERT scripts, `daily_summary` happens to be first → wrong parent → after field promotion, TRANSFORM/AGGREGATE edges bypass the trunk.

### Fix: use SCHEMA edges to determine parent

When a computed field has no `source_tables`, use the incoming SCHEMA edge to find who owns it. `⟐ output --[SCHEMA]--> dt` means `dt`'s parent is `⟐ output`. This is deterministic and semantic:

```python
# Line 1358-1360 — replace arbitrary first-table with SCHEMA-based lookup
if not parent_table_id and table_nodes:
    # Find which table OWNS this field via incoming SCHEMA edges
    for e in edges:
        ed = e.get("data", e)
        if ed.get("target") == nid and ed.get("relationship") == "SCHEMA":
            owner_id = ed.get("source")
            for tid, tn in table_nodes.items():
                if tn.get("original_id") == owner_id:
                    parent_table_id = tn["id"]
                    break
            if parent_table_id:
                break
    # Fallback: prefer intermediate_table
    if not parent_table_id:
        for tid, tn in table_nodes.items():
            if tn.get("type") == "intermediate_table":
                parent_table_id = tn["id"]; break
    # Last resort
    if not parent_table_id:
        parent_table_id = list(table_nodes.values())[0]["id"]
```

**Why this is correct:** After fixing parent assignment, field promotion naturally produces `analytics_orders --[TRANSFORM]--> ⟐ output` (not `daily_summary`). The `⟐ output` node becomes the trunk — ALL intermediate operations connect INTO it, and the output→target chain carries the result forward. No post-promotion edge redirection needed.

### Anatomy of the problem

The data flow graph is built in two layers, and the gap between them causes the bypass:

**Layer 1 — Extractor** (`variable_extractor_v2.py`) walks the SQL syntax tree at field level:

```
Step 4 SQL:
  INSERT INTO daily_summary
  SELECT DATE(ao.order_date) AS dt, COUNT(*) AS cnt, SUM(ao.amount) AS total
  FROM analytics_orders ao

Extractor produces:
  Variables:
    daily_summary     table        defined_in=INSERT
    analytics_orders   table        defined_in=FROM
    ao                 table        defined_in=FROM    source_tables=[analytics_orders]
    ⟐ output           virtual_table defined_in=TOP
    dt                 transform    is_output=True     source_tables=[]
    cnt                aggregate    is_output=True     source_tables=[]
    total              aggregate    is_output=True     source_tables=[]

  Dependencies:
    ao      --[TABLE_FLOW]--> ⟐ output       "data flows from alias into SELECT result"
    ⟐ output --[SCHEMA]-----> dt              "SELECT result OWNS the transform output"
    ⟐ output --[SCHEMA]-----> cnt             "SELECT result OWNS the aggregate output"
    ⟐ output --[SCHEMA]-----> total           "SELECT result OWNS the aggregate output"
    dt      --[DML]---------> daily_summary    "transform result is INSERTED into target"
    cnt     --[DML]---------> daily_summary    "aggregate result is INSERTED into target"
    total   --[DML]---------> daily_summary    "aggregate result is INSERTED into target"
    ao.order_date --[TRANSFORM]--> dt          "DATE() operates on order_date"
    ao.amount --[AGGREGATE]-----> total         "SUM() operates on amount"
```

The extractor does two things correctly:
1. Creates `⟐ output` and connects SCHEMA edges to output fields — *it knows who owns each field*
2. Creates DML edges from output fields to the INSERT target — *it knows where the data goes*

The extractor does one thing wrong:
- `dt` and `total` have `source_tables=[]` because `_extract_table_names` (line 182) only finds `exp.Table` nodes, not column prefixes like `ao` in `ao.order_date`

**Layer 2 — Graph builder** (`dataflow_service.py:_build_l2_graph`) promotes fields to table level:

```
Field promotion ("who does this field belong to?"):
  ao.order_date → parent=analytics_orders  (found via prefix "ao")
  dt            → parent=???                (no source_tables, no prefix)
  cnt           → parent=???                (no source_tables, no prefix)
  total         → parent=???                (no source_tables, no prefix)
```

For columns (`ao.order_date`), the parent is found via the dot prefix: `ao` → resolved to `analytics_orders`. For computed fields (`dt`, `cnt`, `total`), there's no dot prefix and no `source_tables`. The code falls through to line 1358-1360:

```python
if not parent_table_id and table_nodes:
    parent_table_id = list(table_nodes.values())[0]["id"]  # ← arbitrary
```

`table_nodes` dict order depends on variable extraction order. For INSERT scripts, `daily_summary` (INSERT target) happens to be first → `dt`/`cnt`/`total` get `parent=daily_summary`.

**After promotion with wrong parent:**
```
ao.order_date → parent=analytics_orders
dt            → parent=daily_summary     ← WRONG
cnt           → parent=daily_summary     ← WRONG
total         → parent=daily_summary     ← WRONG
```

Edges are promoted to their parents' level:
```
ao.order_date --[TRANSFORM]--> dt
  ↓ parent=analytics_orders     ↓ parent=daily_summary
  = analytics_orders --[TRANSFORM]--> daily_summary   ← bypass!
```

**Layer 3 — Simplification 1** converts DML edges but doesn't touch TRANSFORM/AGGREGATE:
```python
if (src in dml_sources and tgt in dml_targets
    and etype == "TABLE_FLOW"           # ← only catches TABLE_FLOW
    and src != intermediate_id ...):
    continue
```

TRANSFORM and AGGREGATE edges don't match `etype == "TABLE_FLOW"` → pass through unfiltered → end up in the final graph as direct `analytics_orders → daily_summary` bypass edges.

### Complete data flow trace (why each edge should route through output)

For `INSERT INTO daily_summary SELECT DATE(ao.order_date) AS dt, ... FROM analytics_orders ao`:

```
Level of operation          Data flow
────────────────────────────────────────────────────
Source table:               analytics_orders
                                │
Column reference:           ao.order_date
                                │ [TRANSFORM: DATE()]
Computed value:             dt
                                │
                                ├── dt is part of ⟐ output (SCHEMA edge)
                                │
SELECT result:              ⟐ output ──────────────┐
                                │                    │
                                │ [TABLE_FLOW]       │ [TABLE_FLOW]
                                ▼                    ▼
INSERT target:              daily_summary ◄─────────┘
```

The TRANSFORM happens *within* the SELECT — `DATE(ao.order_date)` produces `dt` which is a column OF the SELECT result. The edge `analytics_orders --[TRANSFORM]--> dt` should go INTO `⟐ output` (because `dt` belongs to `⟐ output`), not directly to `daily_summary`. The `⟐ output → daily_summary` TABLE_FLOW edge (created by Simplification 1) carries the complete result forward.

### Why the SCHEMA edge is the correct signal

SCHEMA means "this table owns this column." When the extractor says:

```
⟐ output --[SCHEMA]--> dt
```

It means: *dt is a column of the SELECT result set.* Therefore, `dt`'s parent in the L2 graph should be `⟐ output`. Every computed output field has a SCHEMA edge from `⟐ output` (created at `dependency_graph.py:257-271`, Pass 4c). Using SCHEMA edges for parent assignment is:
- **Deterministic** — doesn't depend on variable iteration order
- **Semantic** — SCHEMA literally encodes the ownership relationship
- **Already correct** — the extractor already produces these edges for every output field

### Evolution

| Version | State | Symptom |
|---------|-------|---------|
| v3.3.65 | ❌ BUG | Two nodes labeled `"⟐ output"` |
| v3.3.66 | ⚠️ REGRESSION | Duplicate real-table labels |
| v3.3.69 | ❌ BROKEN | Dangling edge references |
| v3.3.70 | ❌ BROKEN | Broken topology (bypass) |
| v3.3.71 | ⚠️ PARTIAL | qo_ eliminated, steps 1-3 correct, step4 bypass remains |
| v3.3.72 | ✅ FIXED | Step 2 redirects TRANSFORM/AGGREGATE through output |

### Files Involved
- `backend/app/extractor/variable_extractor_v2.py:182-192` — `_extract_table_names` (gap: misses column prefixes)
- `backend/app/extractor/variable_extractor_v2.py:738-739` — where `src_tables` is populated for computed nodes
- `backend/app/extractor/dependency_graph.py:257-271` — Pass 4c: SCHEMA edges from output container to fields
- `backend/app/services/dataflow_service.py:1349-1360` — fallback parent assignment
- `backend/app/services/dataflow_service.py:1565-1600` — Simplification 1 (TABLE_FLOW routing)

### Two complementary fixes (extractor + graph builder)

**Fix 1 — Extractor: enhance `_extract_table_names` to capture column prefixes**

`_extract_table_names` (line 182) only finds `exp.Table` nodes. It misses table aliases inside column references:

```
DATE(ao.order_date):  extract_tables=[]     col_prefix=['ao']  ← missed!
SUM(ao.amount):       extract_tables=[]     col_prefix=['ao']  ← missed!
COUNT(*):             extract_tables=[]     col_prefix=[]       ← correct
```

Enhance it to also extract table prefixes from `exp.Column.table`:
```python
def _extract_table_names(expr: exp.Expression) -> list[str]:
    tables = set()
    if expr is None or not hasattr(expr, 'walk'):
        return []
    for node in expr.walk():
        if isinstance(node, exp.Table):
            name = _clean(node.name or "")
            if name: tables.add(name)
        elif isinstance(node, exp.Column):           # ← new
            tbl_prefix = _clean(node.table or "")     # ← new
            if tbl_prefix: tables.add(tbl_prefix)    # ← new
    return list(tables)
```

Result: `dt` gets `source_tables=["ao"]`, `total` gets `source_tables=["ao"]`. The graph builder can resolve `ao` → `analytics_orders` via the existing alias map.

**Fix 2 — Graph builder: SCHEMA-based parent lookup for `source_tables=[]` fallback**

For nodes that still have `source_tables=[]` after the extractor fix (e.g., `COUNT(*)` → `cnt`), replace the arbitrary `list(table_nodes.values())[0]` at line 1358-1360 with SCHEMA-based lookup:
```python
if not parent_table_id and table_nodes:
    # Find which table OWNS this field via incoming SCHEMA edges
    for e in edges:
        ed = e.get("data", e)
        if ed.get("target") == nid and ed.get("relationship") == "SCHEMA":
            owner_id = ed.get("source")
            for tid, tn in table_nodes.items():
                if tn.get("original_id") == owner_id:
                    parent_table_id = tn["id"]; break
            if parent_table_id: break
    # Prefer intermediate_table as fallback
    if not parent_table_id:
        for tid, tn in table_nodes.items():
            if tn.get("type") == "intermediate_table":
                parent_table_id = tn["id"]; break
    # Last resort
    if not parent_table_id:
        parent_table_id = list(table_nodes.values())[0]["id"]
```

| Node | `source_tables` after Fix 1 | Parent found by |
|------|---------------------------|-----------------|
| `dt` | `["ao"]` | `source_tables` → `ao` → `analytics_orders` |
| `total` | `["ao"]` | `source_tables` → `ao` → `analytics_orders` |
| `cnt` | `[]` (COUNT(*)) | SCHEMA edge `⟐ output → cnt` |

### Defect: missing SCHEMA edges for computed nodes

**Potential gap:** The SCHEMA-based fallback (Fix 2) relies on the extractor producing `⟐ output --[SCHEMA]--> field` edges. These are created at `dependency_graph.py:257-271` (Pass 4c) for all variables where `is_output=True` and the variable is not table-like. Currently this works for all tested scripts. However, if a computed node is ever produced with `is_output=False` (e.g., inside a subquery context, or a new edge case), it would lack a SCHEMA edge and fall through to the `intermediate_table` preference.

**Tracking:** If in the future a computed field appears in the L2 graph with the wrong parent (attached to a random table), first check whether the extractor produced a SCHEMA edge to it. If not, the extractor's Pass 4c logic needs to be broadened to cover that context.

---


## Bug 6: R15 Profile — `stmt_count` Always 0 — FIXED ✅ v3.3.74

> **Found:** v3.3.74 | **Priority:** P3 | **Status:** Closed

**Symptom:** Profile block shows `Stmts: 0` for all scripts, even those with INSERT+SELECT.

**Root cause:** `adapter.py:107`:
```python
'stmt_count': len(extract_result.statements) if hasattr(extract_result, 'statements') else 0,
```
`ExtractionResult` has no `statements` field — `hasattr` returns False → always 0.

**Fix:** Use the already-available regex counter:
```python
'stmt_count': sum(_count_statement_types(sql_text).values()),
```

---

## Bug 7: R15 Profile — Fake Timing Values — FIXED ✅ v3.3.74

> **Found:** v3.3.74 | **Priority:** P3 | **Status:** Closed

**Note:** Real per-stage timing now collected. Sub-millisecond scripts may show `0ms` — this is correct, not fake.

**Symptom:** All scripts show `Parse: 0ms` and extract/deps/graph evenly split the total.

**Root cause:** `adapter.py:114-120`:
```python
'timing': {
    'parse': 0,
    'extract': total_ms // 4,
    'deps': total_ms // 4,
    'graph': total_ms // 4,
    'total': total_ms,
},
```
No per-stage `time.time()` deltas collected — only total time tracked.

**Fix:** Collect real per-stage deltas:
```python
_t0 = time.time()
# ... parse/extract ...
_t1 = time.time()
# ... deps ...
_t2 = time.time()
# ... graph ...
_t3 = time.time()
'timing': {
    'parse': int((_t1 - _t0) * 1000),
    'extract': int((_t2 - _t1) * 1000),
    'deps': int((_t3 - _t2) * 1000),
    'graph': 0,  # line mapping is fast
    'total': int((_t3 - _t0) * 1000),
}
```

---

## Bug 8: R15 Profile — Zero-Valued Categories Hidden — FIXED ✅ v3.3.74

> **Found:** v3.3.74 | **Priority:** P3 | **Status:** Closed

**Symptom:** Profile only shows non-zero entries. Spec example shows ALL categories including zeros (e.g., `GROUP_BY=0 ORDER_BY=0 HAVING=0 CTE=0`).

**Root cause:** `logger.py:96` in `_kv()`:
```python
parts = [f"{k}={v}" for k, v in sorted(d.items()) if v > 0]
```
The `if v > 0` filter hides zero-valued categories. For remote debugging, zeros are important — they tell the developer "this script has no GROUP BY / no window functions / etc."

**Fix:** Remove the filter:
```python
parts = [f"{k}={v}" for k, v in sorted(d.items())]
```


---

## Bug 9: LogPanel Appears on Right Instead of Bottom


---

## Bug 9: LogPanel Appears on Right Instead of Bottom — FIXED ✅ v3.3.77

> **Found:** v3.3.74 | **Priority:** P2

**Symptom:** The LogPanel rendered on the right side instead of at the bottom.

**Root cause:** `.dataflow-layout` used `display: flex` (default `flex-direction: row`). The LogPanel was the last child, placed to the right.

**Fix:** Changed to `flex-direction: column` + wrapped sidebar/graph in `.dataflow-main` row:
```css
.dataflow-layout { flex-direction: column; }
.dataflow-main { display: flex; flex: 1; min-height: 0; overflow: hidden; }
```
```jsx
<div className="dataflow-layout">
  <div className="dataflow-main">
    <panel-left /> <panel-center /> <panel-inline-l2 />
  </div>
  <LogPanel wsId={wsId} visible={true} />   {/* bottom */}
</div>
```

**Files:** `frontend/src/styles/app.css`, `frontend/src/DataFlowApp.jsx`

---

## Bug 11: Log Panel Cannot Be Resized — FIXED ✅ v3.3.80

> **Found:** v3.3.79 | **Priority:** P2

**Symptom:** The log panel had a fixed height of 220px — user could only see ~10 lines before scrolling. No resize handle.

**Fix:** Added `useResizable` hook (same pattern as L2 panel and sidebar) with a draggable top resize handle:
```jsx
const [logHeight, setLogHeight] = useState(220);
const logResize = useResizable({
  direction: 'vertical', value: logHeight, defaultValue: 220, min: 44, max: 800, invert: true,
  onResize: (v) => setLogHeight(v),
});
// ...
<div className="log-resize-handle" {...logResize.handleProps} title="Drag to resize" />
```

**CSS:** `.log-resize-handle` with `cursor: ns-resize`, hover highlight `#3498DB`.

**Files:** `frontend/src/components/LogPanel.jsx`, `frontend/src/styles/app.css`

---

## Bug 12: LogPanel Resize Has No Visible Effect — FIXED ✅ v3.3.81

> **Found:** v3.3.80 | **Priority:** P2

**Symptom:** Dragging the resize handle updated `logHeight` state but the panel didn't visually resize — stayed at content height.

**Root cause:** `LogPanel.jsx:79,115` used `maxHeight` instead of `height`. `maxHeight` only caps — panel collapsed to content size regardless of drag value.

**Fix:** Changed `maxHeight` → `height`:
```jsx
// Before: style={expanded ? { maxHeight: logHeight + 'px' } : undefined}
// After:  style={expanded ? { height: logHeight + 'px' } : undefined}
```

**Verified via Chromium:** Panel height changed from 220px → 372px on drag (Δ=152px) ✅

**Files:** `frontend/src/components/LogPanel.jsx:79,115`

---

## Bug 13: SSE Logs Not Reaching Frontend (Race Condition) — FIXED ✅ v3.3.82

> **Found:** v3.3.81 | **Priority:** P1

**Symptom:** LogPanel showed 0 lines and "No logs yet" after indexing. API test confirmed logs existed but frontend received nothing.

**Root cause:** `_push()` checked `ws_id in _log_queues` before the SSE endpoint called `ensure_queue()` — messages were silently dropped during the race window.

**Fix:** Changed `_push` to call `ensure_queue(ws_id)` lazily:
```python
# Before: if ws_id and ws_id in _log_queues:
# After:  if ws_id: q = ensure_queue(ws_id)
```

**Verified:** Chromium E2E — LogPanel shows 70 log lines, SCRIPT PROFILE blocks, all pipeline stages with timestamps ✅

**Files:** `backend/app/services/logger.py:21-31`
## Bug 14: Graph Elements Visible Behind Loading Skeleton — FIXED ✅ v3.3.83

> **Found:** v3.3.82 | **Priority:** P2 | **Status:** Closed

**Symptom:** When loading a big batch of scripts, "Loading data flow..." skeleton shows, but graph rectangles and lines are visible in the background bleeding through.

**Root cause — two issues:**

**1. Old graph not cleared before loading.** `DataFlowApp.jsx:126,156`:
```jsx
const handleSearch = useCallback(async (table, field) => {
    if (!wsId) return;
    setLoading(true); setError(null);    // ← l1Graph still has old data!
```
`graphData` (`l1Graph`) retains the previous search's graph. The skeleton condition is `loading && !graphData` — since `graphData` is still truthy, the skeleton is hidden and the old graph stays rendered. User sees the old graph while a new search loads.

**Fix:** Clear `l1Graph` before setting loading:
```jsx
setL1Graph(null);  // ← clear old graph
setLoading(true); setError(null);
```
Same fix needed at `handleOpenL2` (line 156): `setL2Graph(null); setLoading(true);`

**2. Skeleton background is transparent.** `app.css:472`:
```css
.skeleton-graph { background: rgba(255,255,255,0.02); }
```
2% white opacity — essentially transparent. Any graph container or DOM remnants behind the skeleton are visible through it.

**Fix:** Use opaque dark background:
```css
.skeleton-graph { background: #1a1a2e; }
```

**Files:** `frontend/src/DataFlowApp.jsx:126,156`, `frontend/src/styles/app.css:472`
## Bug 15: Filter CSV Requires Exact Script Path Match

> **Found:** v3.3.83 | **Priority:** P2 | **Status:** Open

**Symptom:** Filter CSV parses correctly (3 scripts, 5 tables, 6 columns) but result shows "0 tables, 0 fields".

**Diagnostic block confirms:**
```
File 1: script_table.csv rows=7 headers=SCRIPT_NAME,TABLE_NAME
  Parsed: 3 scripts, 5 tables         ← CSV parsing OK
File 2: table_col.csv rows=10
  Parsed: 6 columns, 5 tables         ← CSV parsing OK
Result: 0 tables, 0 fields            ← matching FAILED
```

**Root cause:** `workspace.py:173` — exact string match between CSV script names and index script paths:
```python
filtered_scripts = [s for s in tdata.get("scripts", [])
                   if allowed_scripts is None or s in allowed_scripts]
```
- Index stores: `multi_workflow/step1_load_orders.sql` (relative path from workspace root)
- CSV has: `step1_load_orders.sql` (just filename)
- `"multi_workflow/step1_load_orders.sql" in {"step1_load_orders.sql"}` → **False** → all scripts filtered out → 0 results

**Confirmed by API test:**
- CSV with `step1_load_orders.sql` (no path) + index with `step1_load_orders.sql` → 5 tables, 6 fields ✅
- CSV with `multi_workflow/step1_load_orders.sql` (with path) + index with `step1_load_orders.sql` → 0 tables, 0 fields ❌

The path prefix presence depends on how the workspace zip is structured. User's deployment has the prefix in the index; their CSV has just filenames.

**Current fix (v3.3.88) only works one way** — `basename(index) in allowed_csv` handles index-with-path but NOT csv-with-path:
```
Index: step1_load_orders.sql    CSV: multi_workflow/step1_load_orders.sql
basename("step1_load_orders.sql") = "step1_load_orders.sql"
"step1_load_orders.sql" in {"multi_workflow/step1_load_orders.sql"} → False ❌
```

**Correct fix — add basenames to the allowed set when parsing the CSV** (works both ways):
```python
# In the CSV parsing loop (workspace.py ~line 140):
if sn: 
    allowed_scripts.add(sn)
    allowed_scripts.add(os.path.basename(sn))  # also match by filename
if tn: 
    allowed_tables.add(tn)
```

**Files:** `backend/app/routers/workspace.py:139-142`
