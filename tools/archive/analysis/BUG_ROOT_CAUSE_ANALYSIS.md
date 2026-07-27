# Bug Root Cause Analysis — For Other Agent

> **Date:** 2026-07-23 | **Version:** 3.3.65

---

## Bug 1: FILTER Range [5-5] — Missing Last Line (P3)

### Symptom
step2 `WHERE c.is_active = 1` highlighted, but `AND c.region IN (...)` on next line is not.

### Root Cause
`RangeBuilder` at `sql_range_finder.py:410`:
```python
max_extend = max(1, min(3, total_lines // 10))
```
For 7-line scripts: `total_lines // 10 = 0`, so `max_extend = 1`. FILTER edge uses forward-only extension (line 429-430):
```python
start_line = max(stmt_start_0, self.matched_line)       # = 4 (WHERE line)
end_line   = min(stmt_end_0, self.matched_line + 1)     # = 5 (max 1 line forward)
```
The WHERE clause is 2 lines (L5: `WHERE...`, L6: `AND...`). `max_extend=1` only extends 1 line, missing the continuation line (AND).

### Fix
**A)** Increase `max_extend` floor from 1 to 2: `max_extend = max(2, min(3, total_lines // 10))`

**B)** Better: detect clause continuation lines (AND/OR after WHERE, additional JOIN conditions) and extend until non-continuation line:
```python
# After matched_line, while next line starts with AND/OR (continuation of same clause):
while end_line + 1 <= stmt_end_0:
    nxt = self.all_lines[end_line + 1].strip().upper()
    if nxt.startswith(('AND ', 'OR ', 'AND\n', 'OR\n')):
        end_line += 1
    else:
        break
```

---

## Bug 2: Orange Highlight Never Clears (P1)

### Symptom
After Escape, 1 orange line persists in DOM. Clicking different edges doesn't change highlight.

### Root Cause
`SqlPanel.jsx:316`:
```jsx
<div key={`${scriptName || "sql"}-${lineNum}-${isEdgeHighlighted}`} ...>
```
The key uses a **boolean** (`isEdgeHighlighted`). Two different edges with different `sql_range` values both set `isEdgeHighlighted=true` for the same lines. React sees same key → reuses DOM → old class persists.

### Fix
Include the actual range value in the key:
```jsx
<div key={`${scriptName}-${lineNum}-${sqlHighlightRange?.join('-') || 'none'}`} ...>
```
This makes the key unique per-range. When edge A's range [1,5] is replaced by edge B's range [3,6], lines 1-2 change key from `...-1-5-none` to `...-none` (unmount), and lines 3-5 change from `...-1-5-none` to `...-3-6-none` (remount with new class).

**File:** `frontend/src/components/SqlPanel.jsx`, line 316.

---

## Bug 3: Edge Ranges Overlap in step3 (P2)

### Symptom
4 lines covered by 2+ edges in step3. `FILTER` and `JOIN` edges share overlapping ranges.

### Root Cause
`partition_edge_ranges` at `sql_range_finder.py:537-596`. The partition function runs correctly (FILTER priority=1 > JOIN=2 > TABLE_FLOW=9). But the overlap persists because:

1. **All edges start from the same wide `sql_range`**: Before partitioning, `_estimate_sql_range` or `find_sql_range` produces ranges like [1,7] for multiple edges. The partition narrows them but edges still share common lines.

2. **Compound edge types not split before partition**: Edges like `"FILTER, JOIN, TABLE_FLOW"` have priority=1 (FILTER), but the edge itself covers lines meant for JOIN and TABLE_FLOW too. The partition assigns lines to the FILTER edge, but JOIN and TABLE_FLOW edges still exist with their original ranges.

### Fix
**A)** In `dataflow_service.py`, split compound edge types into separate edges before partition:
```python
# Before: one edge with type "FILTER, JOIN, TABLE_FLOW" and range [1,7]
# After: three edges each with their own type and range
```

**B)** In `partition_edge_ranges`, when an edge loses lines to higher-priority edges, narrow its `sql_range` to only its owned lines (this already happens at line 585-593). The issue may be that `sql_range` and `sql_ranges` get out of sync — check that both are updated.
