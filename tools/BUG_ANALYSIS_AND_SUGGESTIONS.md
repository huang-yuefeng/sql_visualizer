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
| Bug 18: R18 Field-Level Lineage | P1 | Open (3 issues) | TABLE_FLOW silently dropped + fuzzy fallback + missing table_schemas |

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

## Bug 18: R18 Field-Level Lineage — 3 remaining issues (v3.3.96)

> **Found:** v3.3.95 | **Priority:** P1 | **Status:** Open (3 issues remain)

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

**Issue 1 — TABLE_FLOW silently dropped in BFS (P1, critical)**

`lineage.py:140-178`: the if/elif chain has no clause for TABLE_FLOW. It's not in `_BIDIR`, not in DML/SCHEMA/JOIN/FILTER. Falls through → `should_add` stays False → neighbor never added.

```python
# line 151-152: _BIDIR = _PRODUCTION | _ALWAYS_BIDIR
# _PRODUCTION = {"REF","TRANSFORM","AGGREGATE","WINDOW","COMPUTED","DML","ALIAS"}
# _ALWAYS_BIDIR = {"CORRELATED","INDIRECT","SET_OP","SUBSET"}
# → TABLE_FLOW NOT in either set

# No TABLE_FLOW clause in the if/elif chain:
if etype == "DML":        ...     # line 142
elif etype in _BIDIR:     ...     # line 151 — TABLE_FLOW NOT matched
elif etype == "SCHEMA":   ...     # line 153
elif etype == "JOIN":     ...     # line 163
elif etype == "FILTER":   ...     # line 171
# TABLE_FLOW → falls through → never added
```

Impact: BFS can't cross TABLE_FLOW edges → can't reach source tables through output containers → lineage chain broken at the SELECT boundary. Fields that should be included are excluded instead.

**Fix:** Add TABLE_FLOW conditional clause before the fallthrough:
```python
elif etype == "TABLE_FLOW":
    # Conditional: only add when source has a column in R via production
    for (n2, e2, d2) in adj.get(neighbor, []):
        if n2 in R and e2 in _PRODUCTION:
            should_add = True; break
```

---

**Issue 2 — Seed matching still has fuzzy fallback (P2)**

`lineage.py:110-118`: when SCHEMA-validated lookup finds nothing, falls back to old fuzzy label matching:
```python
# Fallback: simple field-name match
if not seed_ids:
    for n in nodes:
        nd = n.get("data", n)
        label = nd.get("label", "")
        if label == full_name or label == target_field:  # ← matches ANY table
            seed_ids.add(nd.get("id"))
        elif "." in label and label.rsplit(".", 1)[-1] == target_field:
            seed_ids.add(nd.get("id"))  # ← matches ANY table's column
```
The fallback bypasses the table validation. If the queried table doesn't exist in the graph, a column from an unrelated table could silently become the seed.

**Fix:** Remove the fallback block (lines 110-118). If SCHEMA-validated lookup finds nothing, return empty — the table or field doesn't exist in this script's graph. That's correct behavior.

---

**Issue 3 — `infer_table_schemas` not used for seed lookup (P3)**

`schema_inference.py` builds `table_schemas` and stores it in the analysis result. But `compute_field_lineage` in `lineage.py` doesn't use it — it still does its own SCHEMA-based node search at lines 70-108. The spec says seed lookup should use `table_schemas` (O(1) dict check: does this table exist? does this field belong to it?).

**Fix:** Pass `table_schemas` into `compute_field_lineage` and validate there:
```python
def compute_field_lineage(graph_data, target_table, target_field, table_schemas=None):
    if table_schemas:
        if target_table not in table_schemas:
            return set()
        if target_field not in table_schemas[target_table]:
            return set()
        # table + field validated → proceed to find seed node in graph
```

### Files

- `backend/app/extractor/lineage.py:140-178` — add TABLE_FLOW clause (Issue 1)
- `backend/app/extractor/lineage.py:110-118` — remove fuzzy fallback (Issue 2)
- `backend/app/extractor/lineage.py:18-19` — accept table_schemas parameter (Issue 3)
- `backend/app/extractor/schema_inference.py` — ✅ done

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
