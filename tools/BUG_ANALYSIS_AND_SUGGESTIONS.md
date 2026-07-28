# Data Flow Debugger — Open Bug List

> **Date:** 2026-07-28 | **Version:** 3.3.95 | **Active:** 3 (1 partial)
>
> Fixed bugs (1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14) moved to [`BUG_HISTORY.md`](BUG_HISTORY.md).

---

## Quick Status

| Bug | Priority | Status | Notes |
|-----|----------|--------|-------|
| Bug 3: Edge Ranges Overlap | P2 | 🔧 PARTIALLY FIXED | step3: 2 lines; step4: 1 line (same-type co-location) |
| Bug 16: Graph Shadows in Loading | P2 | Open | Likely skeleton placeholders, not real graph |
| Bug 18: R18 Lineage Not Filtering | P1 | Open | lineage_mode returns same 47 nodes as full mode |

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

---

## Bug 18: R18 Lineage Not Filtering — NOT FIXED (re-test failed)

> **Found:** v3.3.95 | **Priority:** P1 | **Status:** Open

**Symptom:** `lineage_mode=true` returns same 47 nodes as `lineage_mode=false`. All fields shown.

### Root causes (3 issues)

**1. Lineage never called from L1 search pipeline.**

`dataflow.py:76` doesn't read `lineage_mode` from request body and doesn't pass it to `create_search()`. `create_search()` signature has no `lineage_mode` parameter. The three lineage functions (`compute_field_lineage`, `filter_relevant`, `filter_graph_by_lineage` at lines 897-1063) are dead code for L1.

**2. Seed matching uses fragile fuzzy rules instead of table-first lookup.**

Current seed search (lines 933-951):
```python
full_name = f"{target_table}.{target_field}"
# Rule 1: label == "stg_customers.customer_id"  → seed
# Rule 2: label == "customer_id"                → seed  
# Rule 3: label == "c.customer_id"              → seed (ANY table!)
# Rule 4: "customer_id" in source_columns       → seed
```
Rule 3 matches any table's column with the right suffix — even columns from unrelated tables. No validation that the table exists or that the field belongs to it.

**3. TABLE_FLOW in _BIDIR propagates all source tables unconditionally** (line 929):
```python
_ALWAYS_BIDIR = {"TABLE_FLOW", "CORRELATED", "INDIRECT", "SET_OP", "SUBSET"}
```
TABLE_FLOW bridges source tables into the output container → SCHEMA adds all columns → everything enters R.

### Solution — 4 steps

**Step 1 — Construct initial R (table-first validated seed):**

Find the table node by exact name. Find a field within that table connected via SCHEMA. If either missing, return empty (invalid search). Initial R = {field_node}.

**Step 2 — Expand R by BFS with edge-type rules:**

For each node in R, walk its edges. Production edges (REF/TRANSFORM/AGGREGATE/WINDOW/COMPUTED/DML/ALIAS) propagate bidirectionally. SCHEMA↑ (column→table) always, SCHEMA↓ (table→column) only if column has production edge from R. TABLE_FLOW/JOIN/FILTER conditional. R stabilizes when no new nodes added.

**Step 3 — Filter graph to R:**

Keep nodes in R, keep edges where both endpoints in R. No post-filter by name — the BFS rules intrinsically exclude unrelated fields via production-filtered propagation.

**Step 4 — Wire into pipeline:**

`dataflow.py`: extract `lineage_mode` from body, pass to `create_search`. `create_search`: when `lineage_mode=true`, call `filter_relevant()` on each script's graph.

### Implementation changes

**A — Remove post-filter** (`dataflow_service.py:1070-1093`):
Delete the entire "Post-BFS column filtering" block — it's a workaround for broken rules. With correct BFS, columns enter R only via production edges.

**B — Fix seed matching** (`dataflow_service.py:933-951`):
```python
# Step 1: Find table node
table_node = None
for n in nodes:
    nd = n.get("data", n)
    if nd.get("label") == target_table and nd.get("variable_type") == "table":
        table_node = nd; break
if not table_node: return set()

# Step 2: Find field connected to table via SCHEMA
table_id = table_node.get("id")
seed_ids = set()
for n in nodes:
    nd = n.get("data", n)
    if target_field in nd.get("label", ""):
        for e in edges:
            ed = e.get("data", e)
            if (ed.get("source") == table_id and ed.get("target") == nd.get("id")
                and ed.get("edge_type") == "SCHEMA"):
                seed_ids.add(nd.get("id")); break
if not seed_ids: return set()
```

**C — Move TABLE_FLOW out of unconditional** (line 929):
```python
_ALWAYS_BIDIR = {"CORRELATED", "INDIRECT", "SET_OP", "SUBSET"}
```

**D — Wire lineage_mode into create_search** (`dataflow.py:67-76`, `dataflow_service.py:24`):
```python
# dataflow.py
lineage_mode = body.get("lineage_mode", False)
result = create_search(ws_id, table, field, ti, fi, lineage_mode=lineage_mode)

# dataflow_service.py
def create_search(ws_id, table, field, ti, fi, lineage_mode=False):
    ...
    if lineage_mode:
        for r in results:
            r["graph"] = filter_relevant(r["graph"], table, field)
```

### Files

- `backend/app/services/dataflow_service.py:1070-1093` — **remove** post-filter block
- `backend/app/services/dataflow_service.py:933-951` — replace seed matching
- `backend/app/services/dataflow_service.py:928-929` — move TABLE_FLOW
- `backend/app/routers/dataflow.py:67-76` — extract lineage_mode
- `backend/app/services/dataflow_service.py:24-25` — accept lineage_mode
