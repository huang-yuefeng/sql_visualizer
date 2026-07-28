# SQL Partition Metrics — Mathematical Verification

> **Date:** 2026-07-22

---

## Core Invariant

Edges in a data flow graph should form a **partition** of the SQL source text:

```
Every SQL line ∈ exactly one data flow operation segment
```

Two mathematical properties:

| Property | Formula | Target |
|----------|---------|:------:|
| **Completeness** | `Coverage = \|Union(all segments)\| / \|SQL\|` | **100%** |
| **Disjointness** | `Overlap = \|Intersection between any two segments\|` | **0** |

Where `\|S\|` = number of lines in segment S.

---

## Algorithm: Partition-Based Verification

### Step 1: Collect all edge ranges

For a given script and its L2 graph edges `{e₁, e₂, ..., eₙ}`:

```
R = { [e₁.start, e₁.end], [e₂.start, e₂.end], ..., [eₙ.start, eₙ.end] }
```

### Step 2: Build coverage bitmap

For each line Lᵢ in the SQL (1 to N):

```
CoveredBy[i] = { edge_ids that cover line i }
```

### Step 3: Compute metrics

```python
SQL_LINES = len(sql_text.split('\n'))

# Coverage: lines covered by at least one edge
covered_lines = sum(1 for i in 1..SQL_LINES if len(CoveredBy[i]) > 0)
coverage = covered_lines / SQL_LINES

# Overlap: lines covered by 2+ edges
overlap_lines = sum(1 for i in 1..SQL_LINES if len(CoveredBy[i]) > 1)
overlap_rate = overlap_lines / SQL_LINES

# Gap: lines not covered by any edge
gap_lines = sum(1 for i in 1..SQL_LINES if len(CoveredBy[i]) == 0)
gap_rate = gap_lines / SQL_LINES

# Redundancy: average edges per covered line
redundancy = (sum of |CoveredBy[i]| for all i) / max(covered_lines, 1)
```

### Step 4: Verify invariant

| Metric | Formula | Pass Threshold |
|--------|---------|:-------------:|
| Coverage | `covered_lines / total_lines` | ≥ 90% |
| Overlap | `overlap_lines / total_lines` | = 0% |
| Gaps | `gap_lines / total_lines` | ≤ 10% (blank lines, comments OK) |
| Redundancy | `avg(|CoveredBy[i]|)` | = 1.0 (exactly one edge per line) |

---

## Visualization: Coverage Heatmap

For each SQL line, show which edge(s) cover it:

```
Line 1:  -- Step 1: Load raw orders    [NO EDGE — comment, OK]
Line 2:  INSERT INTO stg_orders (...)  [DML edge only]           ✓
Line 3:  SELECT o.order_id, ...        [DML edge only]           ✓
Line 4:  FROM raw_orders o             [DML edge only]           ✓
Line 5:  WHERE o.order_date >= ...     [DML edge + FILTER edge]  ❌ OVERLAP
Line 6:    AND o.status IN (...)       [DML edge + FILTER edge]  ❌ OVERLAP
```

This immediately shows:
- Line 5-6 DOUBLE-COUNTED — DML and FILTER edges overlap
- The DML edge should cover lines 2-6 (full INSERT...SELECT)
- The FILTER edge should cover lines 5-6 only (or be a subset)

---

## Edge Type → Expected Segment Size

Different edge types should produce different-sized segments:

| Edge Type | Expected Lines | Tolerance |
|-----------|:-------------:|:---------:|
| JOIN | 1-2 | ±1 |
| FILTER | 1-3 | ±1 |
| AGGREGATE | 1-2 | ±1 |
| WINDOW | 1-2 | ±1 |
| DML | 2-10 | ±3 |
| TABLE_FLOW | 3-15 | ±3 |
| CTE | 3-20 | ±5 |
| REF | 1 only | 0 |

## Compound Edge Types

Edges like `"FILTER, TABLE_FLOW"` should have their range determined by the most **specific** type:
- FILTER is more specific than TABLE_FLOW → range should be 1-3 lines (FILTER range)
- TABLE_FLOW spans the full SELECT → range should be 3-15 lines

The partition approach means compound edges need to decide: does this edge represent a FILTER operation (1-3 lines) or a TABLE_FLOW operation (3-15 lines)? The answer determines the segment size.

---

## Implementation Sketch

```python
def verify_partition(edges, sql_text):
    lines = sql_text.split('\n')
    N = len(lines)
    covered_by = {i: set() for i in range(1, N+1)}
    
    for edge in edges:
        sr = edge.get('sql_range')
        if not sr: continue
        for li in range(sr[0], sr[1]+1):
            if 1 <= li <= N:
                covered_by[li].add(edge['id'])
    
    # Compute metrics
    covered = sum(1 for s in covered_by.values() if s)
    overlap_lines = sum(1 for s in covered_by.values() if len(s) > 1)
    gap_lines = sum(1 for s in covered_by.values() if len(s) == 0)
    
    # Gap analysis: are gaps only comments/blanks?
    gaps_are_comments = all(
        lines[i-1].strip().startswith('--') or lines[i-1].strip() == ''
        for i in covered_by if len(covered_by[i]) == 0
    )
    
    return {
        'coverage': covered / N,
        'overlap_rate': overlap_lines / N,
        'gap_rate': gap_lines / N,
        'gaps_are_comments': gaps_are_comments,
        'redundancy': sum(len(s) for s in covered_by.values()) / max(covered, 1),
        'pass': overlap_lines == 0 and (gap_lines == 0 or gaps_are_comments),
    }
```
