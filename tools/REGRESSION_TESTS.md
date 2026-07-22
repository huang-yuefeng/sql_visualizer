# Regression Test Checklist — Fixed Bugs

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
