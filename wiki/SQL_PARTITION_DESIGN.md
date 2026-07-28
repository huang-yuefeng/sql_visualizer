# SQL Partition Algorithm — Design

> **Date:** 2026-07-22

---

## Goal

Given a SQL script and its data flow edges, verify that edge `sql_range` values form a **valid partition**: every line belongs to exactly one edge, no overlaps, no gaps (except comments).

---

## 1. The Partition Property

A set of ranges `R = {r₁, r₂, ..., rₙ}` forms a valid partition of a SQL script with `N` lines if:

| Property | Definition | Target |
|----------|-----------|:------:|
| **Coverage** | `|∪ R| / N` | ≥ 90% (comments/blanks may be uncovered) |
| **Disjointness** | `∀i≠j: rᵢ ∩ rⱼ = ∅` | 100% |
| **Completeness** | Every non-comment, non-blank line is covered | Yes |

---

## 2. Why Overlap Happens

Current `_estimate_sql_range` produces ranges like this for a 7-line script:

```
Line 1: -- comment
Line 2: INSERT INTO stg_orders (...)      ← DML edge [2,6]  ┐
Line 3: SELECT o.order_id, ...            ← DML edge [2,6]  │ overlap
Line 4: FROM raw_orders o                 ← TABLE_FLOW [2,6] │ on
Line 5: WHERE o.order_date >= ...         ← FILTER [5,6]     │ lines
Line 6:   AND o.status IN (...);          ← FILTER [5,6]    ┘
Line 7: (blank)
```

Three edges all cover lines 2-6. The ideal partition would be:

```
Line 1: -- comment                       [uncovered — OK]
Line 2: INSERT INTO stg_orders (...)      [DML]
Line 3: SELECT o.order_id, ...            [SELECT]
Line 4: FROM raw_orders o                 [TABLE_FLOW]
Line 5: WHERE o.order_date >= ...         [FILTER]
Line 6:   AND o.status IN (...);          [FILTER]
Line 7: (blank)                           [uncovered — OK]
```

---

## 3. Algorithm: Clause-Anchored Partition

### Step 1 — Find Clause Boundaries

Scan the SQL line-by-line. A line starts a new clause if it begins with a SQL keyword (ignoring leading whitespace):

```
Keywords: SELECT, FROM, WHERE, JOIN, GROUP, HAVING, ORDER, LIMIT,
          INSERT, UPDATE, DELETE, MERGE, WITH, UNION, CREATE, DROP, ALTER
```

This produces boundary lines: `B = [2, 3, 4, 5]` (lines where INSERT, SELECT, FROM, WHERE start).

### Step 2 — Build Segments

Each segment spans from its boundary line to (next boundary − 1):

```
Segment 1: L2-L2   INSERT keyword   → type DML
Segment 2: L3-L3   SELECT keyword   → type SELECT
Segment 3: L4-L4   FROM keyword     → type TABLE_FLOW
Segment 4: L5-L6   WHERE keyword    → type FILTER
```

Lines before the first boundary (L1: comment) and after the last boundary (L7: blank) are gaps — acceptable if they're comments or blanks.

### Step 3 — Type Assignment

Map each clause keyword to an edge type:

| Keyword | Edge Type | Rationale |
|---------|-----------|-----------|
| INSERT, UPDATE, DELETE, MERGE | DML | Data modification |
| SELECT | SELECT | Column projection |
| FROM | TABLE_FLOW | Data source identification |
| JOIN, INNER, LEFT, RIGHT | JOIN | Table combination |
| WHERE, HAVING | FILTER | Row filtering |
| GROUP | GROUP | Aggregation grouping |
| ORDER | ORDER | Result ordering |
| LIMIT | LIMIT | Row count restriction |
| WITH | CTE | Common table expression |
| UNION | UNION | Set combination |
| CREATE, DROP, ALTER | DDL | Schema modification |

### Step 4 — Verify Against Edges

For each edge `e` with type `T` and range `[L_start, L_end]`:

1. Find all atoms of type `T` in the partition
2. Check: `edge_range ⊇ atom_range` for each atom (the edge covers its atoms)
3. Check: `edge_range` does not extend beyond `atom_range ± 1` into adjacent atoms

A **PASS** means the edge covers exactly its atoms and nothing else.

A **FAIL** means the edge spills into atoms of different types (overlap).

---

## 4. Handling Nested Structures

### Subqueries

```
SELECT ... FROM (
    SELECT ... FROM t2 WHERE ...    ← inner SELECT/FROM/WHERE
) AS sub WHERE ...                  ← outer WHERE
```

The inner subquery has its own clause boundaries. Partition recursively: the outer SELECT is one segment, the inner `(...)` is a nested partition.

### CTEs (WITH clause)

```
WITH cte1 AS (
    SELECT ... FROM t1 WHERE ...    ← CTE body
)
SELECT ... FROM cte1 WHERE ...      ← main query
```

The WITH keyword starts a CTE segment. The `AS (...)` body is a nested partition.

### UNION

```
SELECT ... FROM t1 WHERE ...
UNION ALL
SELECT ... FROM t2 WHERE ...
```

UNION splits the statement into two branches. Each branch is an independent partition.

---

## 5. Edge Type Hierarchy

Some edge types are **containers** — they naturally span multiple atoms:

| Edge Type | Spans | Example |
|-----------|-------|---------|
| TABLE_FLOW | FROM atom only | L4-L4 |
| DML | INSERT atom + SELECT atom | L2-L3 |
| FILTER | WHERE/HAVING atom | L5-L6 |
| JOIN | JOIN atom only | L5-L5 |
| AGGREGATE | GROUP atom + aggregate functions | L5-L5 |

TABLE_FLOW should NOT cover the entire SELECT...FROM...WHERE. It should cover **only** the FROM clause — the table that data flows from.

---

## 6. Validation Rules

For each edge `e` with type `T`:

- **Rule 1 (Containment):** Every atom of type `T` must be fully inside `e.range`
- **Rule 2 (No Excess):** No atom of a different type may be inside `e.range`
- **Rule 3 (No Gaps):** Every non-comment SQL line belongs to at least one edge

Violation of Rule 2 = **overlap** (two edges covering the same line with different types).
Violation of Rule 3 = **gap** (SQL line not covered by any edge — may be OK for comments).

---

## 7. Formal Algorithm Specification

```
Algorithm: PartitionSQL(sql_text)
Input:  Raw SQL text with N lines
Output: List of atoms {start, end, type}

1.  L ← split sql_text by '\n'
2.  N ← len(L)
3.  B ← []  // boundary list: (line_number, keyword, atom_type)
4.  
5.  // Pass 1: Find clause boundaries
6.  for i ← 1 to N do
7.      stripped ← L[i].strip().upper()
8.      for kw in CLAUSE_KEYWORDS do  // sorted by length descending
9.          if stripped starts with kw AND (next char is space/tab/'(' or EOL) then
10.             B.append((i, kw, KEYWORD_TO_TYPE[kw]))
11.             break
12.         end if
13.     end for
14. end for
15.
16. // Pass 2: Build segments
17. S ← []  // segment list
18. for j ← 0 to |B|-1 do
19.     start ← B[j].line
20.     end   ← B[j+1].line - 1 if j+1 < |B| else N
21.     type  ← B[j].type
22.     sql   ← join(L[start..end], '\n')
23.     if sql is not empty then
24.         S.append({start, end, type, sql})
25.     end if
26. end for
27.
28. // Pass 3: Handle leading gap (comments before first keyword)
29. if B is not empty AND B[0].line > 1 then
30.     pre_sql ← join(L[1..B[0].line-1], '\n')
31.     if pre_sql contains non-comment, non-blank text then
32.         S.prepend({1, B[0].line-1, 'OTHER', pre_sql})
33.     end if
34. end if
35.
36. // Pass 4: Handle trailing gap
37. last_end ← S.last.end if S not empty else N
38. if last_end < N then
39.     post_sql ← join(L[last_end+1..N], '\n')
40.     if post_sql contains non-comment, non-blank text then
41.         S.append({last_end+1, N, 'OTHER', post_sql})
42.     end if
43. end if
44.
45. return S
```

### Complexity

- **Time:** O(N × K) where N = lines, K = keywords (≈20). Effectively O(N).
- **Space:** O(N) for storing segments.
- **Single pass** over the text, no AST needed.

### Keyword Priority

Keywords are matched in **length-descending** order to prevent false matches:
`INSERT` before `IN`, `ORDER` before `OR`, `LIMIT` before `LIKE`, etc.

---

## 8. Error Recovery

### Missing Clause Boundaries

If no clause boundaries are found (e.g., the SQL is a single-line expression):

**Fallback A:** Try parsing with sqlglot. If it produces statements, use the first keyword of each statement's SQL text.

**Fallback B:** Split by semicolons: each `;` terminates a segment.

**Fallback C:** Return the entire SQL as a single segment with type `OTHER`.

### Unclassified Keywords

Keywords not in the type map (e.g., `EXPLAIN`, `ANALYZE`, `TRUNCATE`) get type `OTHER`. They don't break the partition — they're just not assigned to any edge.

### Multi-Statement Scripts

Scripts with multiple SQL statements (separated by `;`) are handled naturally: each statement's first clause keyword starts a new partition. The final `;` terminates the last segment.

---

## 9. Edge Cases

| Case | Handling |
|------|----------|
| Keyword inside string literal | Not at line start → not matched |
| Keyword inside comment | Line starts with `--` → not in `stripped` check (but `--` itself is not a keyword) |
| Multi-word keywords | `GROUP BY` → matched as `GROUP`, `BY` matches separately or not |
| `ORDER BY` | `ORDER` is the keyword, `BY` is continuation |
| `LEFT JOIN` / `INNER JOIN` | `LEFT`/`INNER` matched as modifier, `JOIN` matched as the join keyword |
| `INSERT INTO` | `INSERT` starts DML segment, `INTO` is part of it |
| `ON` clause (JOIN condition) | Not a standalone keyword — absorbed into the preceding JOIN segment |
| `SET` clause (UPDATE) | Not a clause boundary — part of UPDATE |
| `VALUES` clause | Not a clause boundary — part of INSERT |
| Dollar-quoted strings (PostgreSQL) | Lines between `$$` tags skipped entirely |
| `BEGIN...END` blocks (PL/SQL) | Treated as atomic — no internal partitioning |

---

## 10. Integration with Edge Verification

Once the partition `S` is built, compare against edge ranges:

```
Algorithm: VerifyEdges(script, edges, partition S)
Output: {pass: bool, violations: [{line, edge_a, edge_b, issue}]}

1.  covered_by ← map[line → set[edge_ids]]
2.  
3.  for each edge e in edges do
4.      for line in e.range do
5.          covered_by[line].add(e.id)
6.      end for
7.  end for
8.
9.  violations ← []
10. for line ← 1 to N do
11.     edges_on_line ← covered_by[line]
12.     if |edges_on_line| > 1 then
13.         violations.append({line, overlapping: edges_on_line,
14.                            issue: "OVERLAP"})
15.     else if |edges_on_line| = 0 AND L[line] is not comment/blank then
16.         violations.append({line, issue: "GAP"})
17.     end if
18. end for
19.
20. pass ← (violations is empty)
21. return {pass, violations}
```

---

## 11. Type Mapping Table (Complete)

| SQL Keyword | Atom Type | Expected Edge Type(s) |
|-------------|-----------|----------------------|
| INSERT | DML | DML |
| UPDATE | DML | DML |
| DELETE | DML | DML |
| MERGE | DML | DML |
| SELECT | SELECT | REF, TRANSFORM, COMPUTED |
| FROM | TABLE_FLOW | TABLE_FLOW |
| JOIN, INNER JOIN, LEFT JOIN, RIGHT JOIN, CROSS JOIN, FULL JOIN | JOIN | JOIN |
| WHERE | FILTER | FILTER |
| HAVING | FILTER | FILTER |
| GROUP BY | GROUP | AGGREGATE |
| ORDER BY | ORDER | — (no direct edge, presentation only) |
| LIMIT | LIMIT | — (no direct edge) |
| WITH | CTE | CTE |
| UNION, UNION ALL | UNION | UNION, SET_OP |
| CREATE | DDL | — (schema, not data flow) |
| DROP | DDL | — |
| ALTER | DDL | — |

Note: Atoms with no direct edge type are still part of the partition — they belong to the script but don't correspond to data flow operations. This is correct: not every SQL clause is a data flow operation.
