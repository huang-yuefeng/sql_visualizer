# SQL Script Segment Extraction — Analysis & Improvement Advice

> **Date:** 2026-07-20
> **Function:** `_estimate_sql_range()` in `backend/app/services/dataflow_service.py:1583`
> **Frontend consumer:** `SqlPanel.jsx:56-59`

---

## 1. Overview of the Pipeline

```
SQL text ──→ sqlglot parser ──→ AST walk ──→ VariableDefinition[]
                                                   │
                                          dependency_graph.py
                                                   │
                                          VariableDependency[] (edges)
                                                   │
                                          _build_l2_graph()
                                                   │
                                          _estimate_sql_range(edge, sql_lines)
                                                   │
                                          sql_range: [start_l, start_c, end_l, end_c]
                                                   │
                                          SqlPanel.jsx — highlights lines
```

## 2. Current Approach (5 strategies, tried in order)

| # | Strategy | What it does | Reliability |
|---|----------|-------------|-------------|
| 1 | `line_num` from edge metadata | Uses explicit line number | **Best** — but edge metadata never has `line_num` |
| 2 | `defined_in` search | Searches SQL for the CTE/context name | Good for CTE-defined variables |
| 3 | Edge-type → keyword regex | Matches SQL keywords like JOIN, WHERE, SUM() | Medium — single match → extended to statement |
| 4 | Source/target label search | Searches SQL for variable/table names | Low — common names match everywhere |
| 5 | Fallback | Returns full script range `[1,1,N,len]` | Poor — highlights everything |

Each successful strategy then calls `_extend_to_statement(matched_line)` to expand the single-line match into a multi-line SQL statement.

---

## 3. Bug: `_extend_to_statement` Backward Extension Is Broken

### Current code (`dataflow_service.py:1599-1630`):

```python
stmt_start_kw = ('SELECT', 'WITH', 'INSERT', 'UPDATE', 'DELETE', 'MERGE', 'CREATE',
                 'ALTER', 'DROP', 'TRUNCATE', 'FROM', 'JOIN', 'WHERE', 'GROUP',
                 'ORDER', 'HAVING', 'UNION', 'LIMIT')

# Backward extension:
while start_line > 0:
    prev = lines[start_line - 1].strip().upper()
    if not prev or prev.startswith('--'):
        break
    if any(prev.startswith(kw) for kw in stmt_start_kw):  # ← BUG HERE
        break
    start_line -= 1
```

### The problem:

`FROM`, `JOIN`, `WHERE`, `GROUP`, `ORDER`, `HAVING`, `LIMIT` are **clause-level** keywords, not **statement-level** keywords. Including them in `stmt_start_kw` causes the backward extension to stop prematurely.

### Verified test case (step3_join_orders_customers.sql):

```sql
L1: -- Step 3: Join orders with customer data into analytics table
L2: INSERT INTO analytics_orders (order_id, customer_name, amount, segment, region, order_date)
L3: SELECT so.order_id, sc.name, so.amount, sc.segment, sc.region, so.order_date
L4: FROM stg_orders so
L5: JOIN stg_customers sc ON so.customer_id = sc.customer_id
L6: WHERE so.status = 'completed';
```

| Match on | Current result | Should be |
|----------|---------------|-----------|
| `JOIN` (L5) | L5-L6 only (JOIN+WHERE) | L2-L6 (full INSERT...SELECT) |
| `WHERE` (L6) | L6 only | L2-L6 |
| `FROM` (L4) | L4-L6 | L2-L6 |
| `SELECT` (L3) | L3-L6 (missing INSERT) | L2-L6 |

### Fix:

Split the keyword list into two:
- **Statement-start** (for backward stop): `SELECT`, `WITH`, `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`, `ALTER`, `DROP`, `TRUNCATE`, `UNION`
- **Clause-level** (should NOT stop backward extension): `FROM`, `JOIN`, `WHERE`, `GROUP`, `ORDER`, `HAVING`, `LIMIT`

```python
# Keywords that start entirely NEW statements (stop backward extension here)
STMT_START_KW = ('SELECT', 'WITH', 'INSERT', 'UPDATE', 'DELETE', 'MERGE',
                 'CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'UNION')

# Backward: only stop at true statement starts
while start_line > 0:
    prev = lines[start_line - 1].strip().upper()
    if not prev or prev.startswith('--'):
        break
    if any(prev.startswith(kw) for kw in STMT_START_KW):
        break
    start_line -= 1

# Forward: also stop at statement starts (same list is correct)
while end_line < len(lines) - 1:
    nxt = lines[end_line + 1].strip()
    # ... check STMT_START_KW for the line after blank/comment ...
```

This would produce `[2, 1, 6, 30]` for any match within lines 2-6 — the full INSERT...SELECT...FROM...JOIN...WHERE statement.

---

## 4. Root Cause: Position Metadata Not Captured at Extraction Time

### The gap:

- `VariableDefinition` has `line_start: int = 0` and `line_end: int = 0` (model line 112-113)
- `VariableDependency` has **no position fields at all** (model line 119-125)
- The extractor (`variable_extractor_v2.py`) **never sets** `line_start`/`line_end` on variables
- The dependency graph (`dependency_graph.py`) **never sets** line numbers on edges

### Why this matters:

sqlglot expressions carry implicit position information. Every AST node knows where it came from in the source SQL. If the extractor captured this during the initial AST walk, every edge could have an **exact** `[start_line, start_col, end_line, end_col]` range — no estimation needed.

### What to capture:

On `VariableDefinition`:
```python
line_start: int = 0   # ← already in model, just never set
line_end: int = 0     # ← already in model, just never set
col_start: int = 0    # ← could add for column-level precision
col_end: int = 0      # ← could add for column-level precision
```

On `VariableDependency`:
```python
# The SQL expression that CREATED this dependency
sql_span_start_line: int = 0
sql_span_end_line: int = 0
```

### How to capture (using sqlglot):

```python
# In variable_extractor_v2.py, when creating a variable:
# sqlglot expressions often have position info accessible via:
# - expr.find(exp.Table) has a reference point
# - The original SQL text can be searched for the expression's sql() output

# Simple approach: after classifying the variable, record where it was found:
def _get_expression_span(expr, sql_lines):
    """Find which lines contain this expression."""
    expr_sql = expr.sql(dialect='mysql')
    # Search for the expression in the SQL text
    for i, line in enumerate(sql_lines):
        if expr_sql.strip() in line:
            return i + 1, i + 1  # start_line, end_line
    return 0, 0
```

### Better approach (if sqlglot version supports it):

Some sqlglot versions expose position through internal metadata:
```python
# sqlglot may track source position in some versions
# Check expr.__class__ for any position-related attributes
if hasattr(expr, 'source_start'):
    line_start = expr.source_start
```

---

## 5. Keyword Matching: Type-Specific vs Multi-Type Edges

### Current issue:

Edges often have compound types like `"AGGREGATE, COMPUTED, JOIN, TABLE_FLOW, TRANSFORM"`. The `_estimate_sql_range` function splits on comma and tries each type's keywords:

```python
# Line 1680-1682:
keywords = _SQL_KEYWORDS.get(edge_type, [])
if not keywords:
    keywords = _SQL_KEYWORDS.get(label.upper(), [])
```

But `edge_type` is the FULL compound string like `"AGGREGATE, COMPUTED, JOIN, TABLE_FLOW, TRANSFORM"`, and `_SQL_KEYWORDS` only has entries for single types like `"JOIN"`. So `_SQL_KEYWORDS.get("AGGREGATE, COMPUTED, JOIN, TABLE_FLOW, TRANSFORM")` returns `[]` — no match.

Then it tries `label.upper()` which is also empty (the label is just `edge_type`). So it falls through to strategy 4 (label search).

### Fix:

Split compound edge types and try each:

```python
# Split compound types and try each
edge_types = [t.strip() for t in edge_type.split(",")]
for et in edge_types:
    keywords = _SQL_KEYWORDS.get(et, [])
    if keywords:
        for pat in keywords:
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith('--'):
                    continue
                if re.search(pat, line, re.IGNORECASE):
                    return _extend_to_statement(i)
```

But even better: **prioritize the most specific edge type**. For `"AGGREGATE, COMPUTED, JOIN, TABLE_FLOW"`, JOIN is the most visually identifiable operation.

Suggested priority order:
```python
EDGE_TYPE_PRIORITY = [
    "JOIN", "FILTER", "DML", "AGGREGATE", "WINDOW", "CASE",
    "UNION", "CTE", "TRANSFORM", "COMPUTED", "TABLE_FLOW", "REF", "ALIAS"
]
```

---

## 6. Label Search: Too Broad, Wrong First Match

### Current issue:

When keyword matching fails, strategy 4 searches for source/target variable names in the SQL. For common column names like `order_id`, `amount`, or `customer_id`, this matches many lines. The function returns the **first** occurrence, which may be:

- A comment mentioning the table name
- A column list, not the data flow operation
- The wrong statement entirely (e.g., a different CTE that happens to reference the same column)

### Example from test data:

For an edge with `src_label = "raw_orders"`, searching for `"raw_orders"` in `step1_load_orders.sql`:

```sql
L1: -- Step 1: Load raw orders from source into staging   ← matches "raw orders"
L2: INSERT INTO stg_orders ...
L3: SELECT o.order_id, o.customer_id, o.amount, o.order_date, o.status
L4: FROM raw_orders o                                     ← matches "raw_orders"
L5: WHERE o.order_date >= '2024-01-01'
L6:   AND o.status IN ('completed', 'pending');
```

With the comment-filter fix already applied, line 1 is skipped. But line 4 is found first, and `_extend_to_statement` expands backward from there... which stops at `FROM` (a clause keyword in `stmt_start_kw`). Result: `L4-L6` — missing SELECT and INSERT.

### Fix:

1. After finding ALL matching lines, prefer the one that yields the **widest** statement after extension
2. Or: prefer lines that contain **multiple** search terms (e.g., both `src_label` AND `tgt_label`)
3. Or: score each match by how many edge-type keywords are also present nearby

```python
# Instead of returning the first match, score all matches:
best_match = None
best_score = -1
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith('--'):
        continue
    score = 0
    for term in search_terms:
        if term.lower() in line.lower():
            score += 1
    if score > best_score:
        best_score = score
        best_match = i

if best_match is not None:
    return _extend_to_statement(best_match)
```

---

## 7. Missing `line_num` in Edge Metadata

### Current state:

The `_estimate_sql_range` first tries `edge_data.get("line_num")`, but the edge building code at line 1464-1469 never populates this:

```python
enriched = dict(ed)
enriched["source_label"] = src_label
enriched["target_label"] = tgt_label
# ← line_num/line_number/line is NEVER set
sql_range = _estimate_sql_range(enriched, lines)
```

The original edge `ed` comes from `dependency_graph.py` which creates `VariableDependency` objects with fields: `source_id`, `target_id`, `relationship`, `operation`, `sql_context`. None of these carry position info either.

### Fix:

At extraction time, capture the line number where the dependency was created. The simplest approach:

In the dependency graph, when creating an edge between two variables, record the `line_start` of the **target** variable (the one consuming data). This is most often where the SQL operation occurs.

```python
# In dataflow_service.py, when building L2 edges:
src_var = variables_by_id.get(src_orig)
tgt_var = variables_by_id.get(tgt_orig)
if tgt_var and tgt_var.line_start:
    enriched["line_num"] = tgt_var.line_start
if src_var and src_var.line_start and not enriched.get("line_num"):
    enriched["line_num"] = src_var.line_start
```

But this requires `line_start` to actually be populated by the extractor (see section 4).

---

## 8. L1 Edges — No `sql_range` (By Design)

L1 edges (`reads_from`, `writes_to`) represent cross-script pipeline flow — e.g., "script A writes to table X, script B reads from table X". These are synthesized connections between scripts, not individual SQL operations within a single script. Since they span multiple scripts, there is no single SQL fragment to highlight. **This is intentional and correct** — L1 edge clicks should not trigger SQL highlighting.

If navigation from L1 to L2 is desired, the user can double-click a script node to open its per-script detail view (L2), where each edge's `sql_range` corresponds to a specific SQL operation within that script.

---

## 9. Summary of All Improvements

| Priority | Issue | Location | Fix |
|----------|-------|----------|-----|
| **P0** | `_extend_to_statement` stops at clause keywords | `dataflow_service.py:1604-1606` | Remove `FROM,JOIN,WHERE,GROUP,ORDER,HAVING,LIMIT` from backward `stmt_start_kw` |
| **P1** | Position metadata not captured at extraction time | `variable_extractor_v2.py` + `models/variable.py` | Set `line_start`/`line_end` on VariableDefinition from sqlglot AST positions |
| **P1** | Edge metadata missing `line_num` | `dataflow_service.py:1464-1469` | Propagate `line_start` from source/target variable to edge's `enriched` dict |
| **P2** | Compound edge types not split for keyword matching | `dataflow_service.py:1680-1682` | Split `edge_type` by comma, try each type with priority ordering |
| **P2** | Label search returns first match, not best match | `dataflow_service.py:1696-1711` | Score all matches by term count, return the best one |
| **P3** | No column-level precision | `dataflow_service.py:1630` | Use `col_start`/`col_end` from variable model for precise column highlighting |

---

## 10. Recommended Implementation Order

1. **Fix `_extend_to_statement`** (10 lines, immediate impact) — makes the existing keyword+label matching produce correct multi-line ranges instead of broken partial statements.

2. **Capture `line_start`/`line_end` in the extractor** (~30 lines) — gives every variable an exact position. This cascades through the entire highlighting pipeline, making all strategies more accurate.

3. **Propagate `line_num` to edge metadata** (~5 lines) — once variables have positions, edges get them for free. Strategy 1 (explicit line number) becomes the primary method, replacing estimation entirely for most edges.

4. **Split compound edge types** (~15 lines) — ensures every compound type can find its keyword match.
