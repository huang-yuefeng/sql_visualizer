# SQL Edge Highlighting — Ground Truth Accuracy Test

> **Date:** 2026-07-20 | **Version:** 3.3.1 | **Test data:** 7 mock SQL files with known operation boundaries

---

## 1. Test Design

Created 7 SQL scripts exercising all 13 edge types with **known ground truth** — the exact line range where each operation occurs:

| File | Lines | Edge Types Tested |
|------|:-----:|-------------------|
| 01_dml_table_flow.sql | 8 | DML, TABLE_FLOW, FILTER, REF |
| 02_join_multi_table.sql | 9 | JOIN, AGGREGATE, TABLE_FLOW, FILTER |
| 03_cte_window.sql | 17 | CTE, WINDOW, COMPUTED, TABLE_FLOW |
| 04_union_subquery.sql | 13 | UNION, SUBQUERY, SET_OP |
| 05_transform_case.sql | 12 | TRANSFORM, CASE, COMPUTED |
| 06_merge_update.sql | 17 | DML, TABLE_FLOW, FILTER (MERGE variant) |
| 07_nested_cte_chain.sql | 38 | CTE chain, AGGREGATE, WINDOW, TABLE_FLOW |

Each file's ground truth is stored in `samples/mock_sql_test/ground_truth.json`.

---

## 2. Results

### Overall: 3.3% accuracy (1/30 checks pass at ≥70% overlap)

| Metric | Value |
|--------|:-----:|
| Total edge checks | 30 |
| Passed (≥70% overlap) | **1** |
| Partial (30-70%) | **18** |
| Failed (<30%) | **11** |
| No sql_range | **0** |

### By Edge Type

| Edge Type | Pass/Total | Accuracy | Issue |
|-----------|:----------:|:--------:|-------|
| DML, TABLE_FLOW | 0/2 | 0% | Range includes comment lines (L2) |
| TABLE_FLOW | 0/4 | 0% | Range covers entire file |
| JOIN, TABLE_FLOW | 0/5 | 0% | Range too wide, includes comments |
| AGGREGATE, FILTER, JOIN, TABLE_FLOW | 0/4 | 0% | 4-type compound, all share same wide range |
| AGGREGATE, WINDOW | 0/4 | 0% | Range is the full CTE definition, not just the AGGREGATE/WINDOW line |
| FILTER, TABLE_FLOW | 0/2 | 0% | Comment lines in range |
| WINDOW | 0/3 | 0% | Range is too broad |
| COMPUTED, FILTER, TABLE_FLOW, TRANSFORM | 0/2 | 0% | Covers entire file |

---

## 3. Root Cause Analysis

### Issue A: Comment lines included in ranges (50% of failures)

**Example:** `01_dml_table_flow.sql` edge `DML, TABLE_FLOW` has range `L2-L12`, but the actual SQL operations start at L4.

```
L1: -- 01_dml_table_flow.sql: INSERT-SELECT with WHERE filter
L2: -- Tests: DML, TABLE_FLOW, FILTER, REF edges     ← COMMENT in range!
L3: (blank)
L4: INSERT INTO stg_orders (...)                       ← actual DML starts here
...
L12:   AND o.order_status IN ('COMPLETED', 'PENDING'); ← actual DML ends here
```

**Root cause:** `_extend_to_statement` backward loop checks `prev.startswith('--')` at `dataflow_service.py:1625`. This should stop at L2, producing `L3-L12`. But the actual range is `L2-L12`, meaning the comment check is **not working**.

**Likely cause:** The keyword matching step finds a match on the **comment line itself** (L2 contains "DML" and "TABLE_FLOW" in the text), then extends from L2 instead of from the actual SQL keyword line. The `_estimate_sql_range` keyword search at line 1740 iterates `for i, line in enumerate(lines)` and at line 1687 checks `if stripped.startswith('--'): continue` — but this check may not be reached because the keyword matching was already successful on a different strategy.

### Issue B: Compound edge types all share the same wide range (30% of failures)

Edges like `AGGREGATE, FILTER, JOIN, TABLE_FLOW` represent 4 different data flow operations, but all get the same `sql_range` spanning the entire statement. A JOIN should highlight just the JOIN clause (1-2 lines), not the entire SELECT.

**Root cause:** The edge merging logic at `dataflow_service.py:1546-1548` combines edges with the same (source, target) pair into compound types but keeps only the **first** `sql_range`. All merged edges inherit the same range.

### Issue C: Ranges cover the entire file for complex queries (20% of failures)

Edges in CTE-heavy scripts (07_nested_cte_chain.sql) get ranges covering the full 38-line file.

**Root cause:** `_extend_to_statement` backward loop stops at statement-start keywords, but CTE chains (`WITH cte1 AS (...), cte2 AS (...) SELECT ...`) form a single logical statement. When the match is inside a CTE, it extends all the way up to the `WITH` keyword.

---

## 4. Suggested Fixes

| # | Issue | File:Line | Fix |
|---|-------|-----------|-----|
| 1 | Comment lines in ranges | `dataflow_service.py:1740` — keyword match iterates over all lines | Ensure `_estimate_sql_range` strategies 3-5 check `stripped.startswith('--')` BEFORE matching, or filter after match |
| 2 | Compound edges share same range | `dataflow_service.py:1546-1548` | Don't merge sql_range — keep the most specific (shortest) range per edge type, not the first one |
| 3 | Edge type→keyword mapping incomplete | `dataflow_service.py:1655-1678` `_SQL_KEYWORDS` | Add missing types: `TABLE_FLOW` should match `FROM`, `REF` should match column references with word boundaries |
| 4 | No per-edge-type range differentiation | `dataflow_service.py:1649-1694` | When an edge has compound type, try each sub-type's keywords in order of specificity and use the BEST match, not just the first |

---

## 5. Test Data Location

```
samples/mock_sql_test/
├── ground_truth.json          # Known line ranges for each operation
├── 01_dml_table_flow.sql      # INSERT-SELECT with WHERE
├── 02_join_multi_table.sql    # Multi-table JOIN with aggregation 
├── 03_cte_window.sql          # CTE + ROW_NUMBER + CASE
├── 04_union_subquery.sql      # UNION ALL branches
├── 05_transform_case.sql      # COALESCE, CAST, CASE transformations
├── 06_merge_update.sql        # MERGE INTO with branches
├── 07_nested_cte_chain.sql    # 3 chained CTEs with LAG/rolling sum
└── filter_tables.csv
```

**Re-run:** `python3 /tmp/test_sql_accuracy.py`
