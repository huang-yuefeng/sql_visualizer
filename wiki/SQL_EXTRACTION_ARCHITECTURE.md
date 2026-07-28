# SQL Extraction Architecture — Current State

> **Date:** 2026-07-23 | **Version:** 3.3.65 | **Module:** `sql_range_finder.py` (631 lines)

---

## 1. Current Architecture — Single System ✅

The old `_estimate_sql_range` has been **removed** from `dataflow_service.py`. 
`sql_range_finder.py` is the **single source of truth** for all SQL range extraction.

```
dataflow_service.py:_build_l2_graph()
  │
  └── find_sql_range(enriched, sql_text)   ← SINGLE entry point (line 616)
        │
        └── sql_range_finder.py
              │
              ├── SqlRangeFinder.find(edge_data)
              │     │
              │     ├── StatementParser   → sqlglot into statements with line ranges
              │     │   └── Fallback: when sqlglot converts -- → /* */ (unfindable),
              │     │       scans original lines for statement boundaries via semicolons
              │     │
              │     ├── StatementMatcher  → which statement contains edge variables?
              │     │
              │     ├── KeywordLocator    → within statement, find line by edge type
              │     │   ├── Strategy A: keyword patterns (TABLE_FLOW: FROM first)
              │     │   └── Strategy B: label search with context bonus scoring
              │     │
              │     └── RangeBuilder      → extend matched line to statement boundaries
              │           └── Edge-type-aware extension direction:
              │               ├── Forward-only: FILTER, JOIN, DML, CTE, etc.
              │               │   (keyword at clause/statement start)
              │               └── Bidirectional: TABLE_FLOW (FROM in middle)
              │
              └── partition_edge_ranges()  → priority-based line assignment
                    └── Updates both sql_range AND per-type sql_ranges
```

---

## 2. Data Flow in `_build_l2_graph` (dataflow_service.py:1122-1618)

```
# 1. Individual edges get sql_range from find_sql_range
sql_range = find_sql_range(enriched, sql_text)

# 2. Edges merged by (source,target,edge_type) — same-type edges combined
#    Keeps most specific (shortest) sql_range

# 3. Fields promoted to parent tables, edges kept separate per type
#    (No compound merging — different types = separate edges)

# 4. Bug 1 fix: DML edges routed through query_output node
#    source_table → qo(TABLE_FLOW) → qo(DML) → target_table

# 5. Dedup: merge edges with same (source,target,edge_type)

# 6. partition_edge_ranges: narrow overlapping ranges by priority
#    FILTER(1) > JOIN(2) > ... > TABLE_FLOW(9)
```

### line_num propagation (dataflow_service.py:1458-1465)

When `line_start`/`line_end` are not populated by the variable extractor, 
`dataflow_service.py` searches SQL text for the target label:

```python
if tgt_label and lines:
    tgt_clean = tgt_label.split('.')[-1].strip().lower()
    if len(tgt_clean) > 2:
        for i, line in enumerate(lines):
            if tgt_clean in line.lower():
                enriched["line_num"] = i + 1  # 1-based
                break
```

---

## 3. Edge-Type-Aware Range Extension

| Extension mode | Types | Rationale |
|----------------|-------|-----------|
| **Forward-only** | FILTER, WHERE, HAVING, JOIN, GROUP_BY, ORDER_BY, DML, CTE, CREATE, ALTER, DROP, SCHEMA, AGGREGATE, WINDOW, TRANSFORM, CASE, COMPUTED, SUBQUERY, SUBSET, ALIAS, INDIRECT, REF, CORRELATED | Keyword at clause/statement start; backward extension includes irrelevant preceding clauses |
| **Bidirectional** | TABLE_FLOW | FROM keyword is in middle of SELECT...FROM...WHERE |

---

## 4. Keyword Priority (KeywordLocator)

Edge-type keywords tried in order for first-match (line-scan top to bottom):

| Edge Type | Keywords (in priority order) |
|-----------|------------------------------|
| TABLE_FLOW | `FROM` (first, most specific to data flow), `INSERT...SELECT` |
| FILTER | `WHERE`, `HAVING` |
| JOIN | `(LEFT\|RIGHT\|INNER\|...)?\s*JOIN` |
| DML | `INSERT\s+(INTO\s+)?`, `UPDATE\s+`, `DELETE\s+FROM\s+`, `MERGE\s+INTO\s+` |

---

## 5. Partition Priority

Lower number = higher priority. More specific operations own lines:

| Priority | Types |
|----------|-------|
| 1 | FILTER, WHERE, HAVING |
| 2 | JOIN |
| 3 | GROUP_BY |
| 4 | ORDER_BY |
| 5 | AGGREGATE, WINDOW |
| 6 | TRANSFORM, CASE, COMPUTED |
| 7 | CTE, UNION, SUBQUERY |
| 8 | DML, INSERT, UPDATE, DELETE |
| 9 | TABLE_FLOW |
| 10 | SCHEMA, CREATE, ALTER, DROP |
| 11 | ALIAS |
| 12 | INDIRECT, SUBSET, REF, CORRELATED |

---

## 6. StatementParser Fallback

sqlglot converts `-- comments` to `/* comments */`, making the output unfindable in original text. When `idx < 0`:

1. Scan from approximate position for first non-comment, non-blank line → `start_line`
2. Scan forward from `start_line` for semicolons → `end_line`
3. No keyword-based statement detection (avoids false positives like SELECT in INSERT...SELECT)

---

## 7. CTE Boundary Handling (RangeBuilder)

RangeBuilder extends matched lines to statement boundaries but respects CTE 
boundaries (`)`, `),`) — same logic as the old `_extend_to_statement`:

```python
# Forward: stop at CTE closure
for i in range(self.matched_line + 1, end_line + 1):
    if nxt.startswith(')') and (len(nxt) <= 3 or nxt.startswith('),')):
        end_line = i - 1
        break

# Backward: start after CTE closure  
for i in range(start_line, self.matched_line):
    if prev.startswith(')') and (len(prev) <= 3 or prev.startswith('),')):
        start_line = i + 1
```

---

## 8. Key Design Decisions (v3.3.65)

1. **Single entry point**: `find_sql_range()` from `sql_range_finder.py` — no more dual systems
2. **No compound edge merging**: Different edge types between same nodes remain separate edges, each with its own `sql_range`
3. **DML → query_output**: DML edges route through a virtual `⟐ output` node for correct data flow semantics
4. **Forward-only extension**: Clause-start types extend forward from keyword, avoiding irrelevant preceding clauses
5. **Dedup by (source,target,type)**: Final pass ensures no duplicate edges after query_output insertion
6. **Edge-type-aware fields promotion**: Fields promoted to parent tables but edges kept separate per type

---

## 9. Traceability: SQL_EXTRACTION_ANALYSIS.md Recommendations

Mapping of recommendations from `tools/SQL_EXTRACTION_ANALYSIS.md` (2026-07-20) to current state:

| # | Recommendation | Status | Notes |
|---|---------------|--------|-------|
| 1 | Fix `_extend_to_statement` clause-keyword bug | ✅ **Addressed** | RangeBuilder uses edge-type-aware extension (forward-only vs bidirectional). StatementParser detects boundaries via sqlglot, not heuristic keywords. |
| 2 | Capture `line_start`/`line_end` in variable extractor | ⚠️ **Deferred** | `variable.py` has `line_start`/`line_end` fields (default 0) but no extractor populates them. `dataflow_service.py:1458` uses a label-search workaround. |
| 3 | Propagate `line_num` to edge metadata | ⚠️ **Partial** | `dataflow_service.py:1458` searches for target label in SQL. This works for unique names but fails for common names like `id`, `name`. |
| 4 | Split compound edge types for keyword matching | ✅ **Addressed** | `partition_edge_ranges` handles compound types by using highest priority. |
| 5 | Label search: score all matches, not first match | ⚠️ **Not addressed** | KeywordLocator uses first-match strategy. Multi-match scoring would improve accuracy for common labels. |
| 6 | Column-level precision | ⚠️ **Deferred** | All ranges are line-level. Column information is not extracted or used for highlighting. |
| 7 | Comment-filter in label search | ✅ **Addressed** | StatementParser handles sqlglot comment conversion with fallback. Label search skips `--` comment lines. |
| 8 | Remove `_estimate_sql_range` | ✅ **Done** | Removed from `dataflow_service.py`. `find_sql_range()` is the single entry point. |
| 9 | L1 edges no `sql_range` by design | ✅ **Confirmed** | L1 edges span multiple scripts; no single SQL fragment to highlight. |

---

## 10. Known Limitations

### 10.1 Line-Level Only (No Column Precision)
All ranges operate at line granularity: `[start_line, 1, end_line, 1]`. Column positions 
are always set to 1. This means highlighting always covers entire lines, never sub-line 
fragments. Column-level precision requires the variable extractor to populate 
`col_start`/`col_end` on `VariableDefinition`.

### 10.2 Label-Search Workaround for Missing Position Metadata
The variable extractor doesn't populate `line_start`/`line_end` on `VariableDefinition`. 
The fallback in `dataflow_service.py:1458` searches SQL for the target label string.
This works for distinctive names (e.g., `stg_customers`) but can match wrong lines for 
common names (e.g., `id`, `name`, `date`).

### 10.3 sqlglot Comment Conversion Fallback
When sqlglot converts `--` to `/* */`, the transformed text can't be found in the 
original. The fallback scans for semicolons as statement boundaries, which may 
group multiple statements together if semicolons are inconsistently used.

### 10.4 First-Match Keyword Strategy
`KeywordLocator` returns the first matching keyword line. For scripts with multiple 
clauses of the same type (e.g., multiple JOINs), the first one is always selected 
even if a later one is more relevant to the specific edge's variables.

### 10.5 No Formal Test Suite for sql_range_finder.py
There is no dedicated test file for `sql_range_finder.py`. SQL extraction accuracy is 
tested indirectly through integration tests (`test_edge_types.py`, 
`test_complex_samples.py`). Unit tests for the 4-layer pipeline would improve 
regression resistance.

---

## 11. Test Coverage

| Test File | Coverage Type | sql_range verification |
|-----------|--------------|----------------------|
| `test_edge_types.py` | Edge type classification | Indirect (checks edge type, not range accuracy) |
| `test_complex_samples.py` | Multi-workflow integration | Indirect (checks graph structure) |
| `test_github_inspired_samples.py` | GitHub SQL patterns | Indirect |
| `test_analytical_samples.py` | Analytical SQL patterns | Indirect |
| `test_compound_l2.py` | L2 compound nodes | Checks sql_range exists, not accuracy |
| `test_graph_integrity.py` | Graph structure | Checks edge existence |

**Missing**: No dedicated unit tests for `StatementParser`, `StatementMatcher`, 
`KeywordLocator`, `RangeBuilder`, or `partition_edge_ranges`. All testing is 
integration-level.

---

## 12. Module Map

| File | Lines | Role |
|------|-------|------|
| `backend/app/services/sql_range_finder.py` | 631 | SQL range extraction engine |
| `backend/app/services/dataflow_service.py` | ~1800 | L1/L2 graph building, calls `find_sql_range()` |
| `backend/app/models/variable.py` | ~120 | Variable model with `line_start`/`line_end` fields |
| `frontend/src/components/SqlPanel.jsx` | ~350 | SQL display with range-based highlighting |
| `frontend/src/DataFlowApp.jsx` | ~550 | `pickBestSqlRange()` selects per-type ranges |
| `tools/SQL_EXTRACTION_ANALYSIS.md` | — | Older analysis (2026-07-20) of predecessor system |
| `tools/BUG_ANALYSIS_AND_SUGGESTIONS.md` | — | Active bug list (user-maintained, read-only) |
