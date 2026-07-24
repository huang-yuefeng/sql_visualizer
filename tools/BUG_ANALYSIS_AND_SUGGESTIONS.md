# Data Flow Debugger — Open Bug List

> **Date:** 2026-07-23 | **Version:** 3.3.82 | **Active:** 1 partial (Bug 3)
>
> Fixed bugs (1, 2, 4, 5, 6, 7, 8) moved to [`BUG_HISTORY.md`](BUG_HISTORY.md).

---

## Quick Status

| Bug | Priority | Status | Notes |
|-----|----------|--------|-------|
| Bug 3: Edge Ranges Overlap | P2 | 🔧 PARTIALLY FIXED | step3: 2 lines; step4: 1 line (same-type co-location) |

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


