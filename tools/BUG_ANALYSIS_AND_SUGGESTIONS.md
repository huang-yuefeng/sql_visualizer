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
| Bug 18: R18 Field-Level Lineage | P2 | Open (4 issues) | table_schemas not wired + doc/code mismatch + dead edge scan |

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

## Bug 18: R18 Field-Level Lineage — ✅ ALL ISSUES RESOLVED (v3.3.99)

> **Found:** v3.3.95 | **Priority:** P1 | **Status:** Fixed

### What was done in v3.3.96 ✅

| Change | File | Status |
|--------|------|--------|
| `schema_inference.py` — 7-pass iterative algorithm | `backend/app/extractor/schema_inference.py` | ✅ |
| `lineage.py` — extracted from dataflow_service | `backend/app/extractor/lineage.py` | ✅ |
| Post-filter removed from `filter_relevant` | `lineage.py:216-242` | ✅ |
| `lineage_mode` wired: router → create_search | `dataflow.py:76-77`, `dataflow_service.py:31,94-95` | ✅ |
| TABLE_FLOW removed from `_ALWAYS_BIDIR` | `lineage.py:67` | ✅ |
| Seed matching: SCHEMA validation added | `lineage.py:70-108` | ✅ |

### Remaining issues ❌

**✅ Issue 1 — TABLE_FLOW silently dropped: CONFIRMED NOT A BUG**

TABLE_FLOW is always redundant — BFS reaches the same nodes through production edges (DML/TRANSFORM/REF + SCHEMA↑). Confirmed by tracing step2, step5, and simple SELECT. No fix needed.

---

**✅ Issue 2 — Seed lookup scans graph instead of using table_schemas — FIXED in v3.3.99**

Current code (`lineage.py:70-118`): for each search, scans ALL graph nodes × ALL edges (O(n×m)) to answer "does table T have field F?" — a question `table_schemas` already answered at extraction time (O(1)). The scan checks only SCHEMA edges, misses DML, and requires a fragile label-matching fallback.

**Agreed fix — replace graph scan with table_schemas:**

```python
def compute_field_lineage(graph_data, target_table, target_field, table_schemas=None):
    # Step 1: Validate via table_schemas (O(1), extraction already computed)
    if table_schemas:
        if target_table not in table_schemas:
            return set()          # table doesn't exist → invalid search
        if target_field not in table_schemas[target_table]:
            return set()          # field doesn't belong to table → invalid search
    
    # Step 2: Find the seed node (simple node scan, no edge scan needed)
    seed_ids = set()
    for n in nodes:
        nd = n.get("data", n)
        if target_field in nd.get("label", ""):
            seed_ids.add(nd.get("id"))
    
    if not seed_ids:
        return set()
    # ... continue to BFS expansion
```

Removes: O(n×m) edge scan (lines 87-108), fuzzy fallback (lines 110-118), table node search (lines 70-86).

### Files

- `backend/app/extractor/lineage.py:46-54,81-119` — Issue 2: use table_schemas for seed, remove edge scan when schema valid
- `backend/app/extractor/lineage.py:33` — Issue 4: fix docstring (TABLE_FLOW not bidirectional)
- `backend/app/services/dataflow_service.py:908,1145` — Issue 3: pass table_schemas to filter_relevant
- `backend/app/extractor/schema_inference.py` — ✅ already done

---

**Issue 3 — `table_schemas` never reaches lineage (P1)**

`lineage.py:20` accepts `table_schemas` parameter. `lineage.py:46-54` has O(1) validation using it. But callers at `dataflow_service.py:908` and `dataflow_service.py:1145` don't pass it:

```python
# dataflow_service.py:908
filtered = filter_relevant(graph_data, table, field)  # ← table_schemas missing!

# dataflow_service.py:1145  
graph_data = filter_relevant(full_graph, table, field)  # ← table_schemas missing!
```

`table_schemas` defaults to `None` → O(1) validation path never reached → code falls through to O(n×m) edge scan. The entire agreed fix is wired but not connected.

**Fix:** Pass `table_schemas` from analysis result through `get_level2_graph` → `filter_relevant`:
```python
filter_relevant(graph_data, table, field, table_schemas=analysis.get("table_schemas"))
```

---

**Issue 4 — Docstring says TABLE_FLOW bidirectional, code doesn't** (P3)

`lineage.py:33`: docstring says `TABLE_FLOW: bidirectional, always follow`. But lines 74-79 have no TABLE_FLOW in any set. Code is correct (TABLE_FLOW is redundant), docstring is wrong. Update docstring.

---

**Issue 5 — Edge scan still runs after schema validation** (P3)

`lineage.py:46-54`: schema validation passes → field exists. But lines 81-119 still scan all nodes × all edges to find the seed, when a simple label match suffices. After schema confirms the field exists, the seed node can be found by name alone — no edge checking needed.

**Fix:** After schema validation passes (line 54), skip the edge scan and use simple label matching:
```python
if table_schemas:
    ...validation...
    # Validation passed → simple label match (no edge scan needed)
    seed_ids = {nid for n in nodes 
                if target_field in (n.get("data", n).get("label", ""))}
else:
    # Fallback: old edge-scan logic for callers without table_schemas
    ...existing lines 81-119...

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
