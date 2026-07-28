# Data Flow Formal Definition

> For the SQL Data Flow Debugger — visualizing how data flows between scripts, tables, and fields.

## Core Concepts

### Variable
A named piece of data. Types:
- **table**: database table, temp table, foreign table
- **view**: VIEW, MATERIALIZED VIEW
- **cte**: Common Table Expression (WITH … AS)
- **column**: table.column or bare column reference
- **virtual_table**: result of a SELECT/JOIN statement (ephemeral)
- **aggregate**: SUM, COUNT, AVG, MIN, MAX
- **window**: ROW_NUMBER, RANK, LAG, SUM OVER
- **transform**: COALESCE, CAST, CONCAT result
- **expression**: computed alias like `(a+b) AS total`
- **case**: CASE WHEN … THEN … END
- **literal**: string or number constant
- **merge_target**: target table in MERGE INTO
- **union_branch**: UNION / INTERSECT / EXCEPT branch
- **subquery**: subquery in FROM/JOIN

### Script
A single SQL file. Contains statements (SELECT, INSERT, CREATE, etc.) that produce and consume variables.

### Data Flow Graph
A directed graph G = (V, E) where:
- **V** (vertices): all variables (tables, columns, CTEs, etc.) across scripts
- **E** (edges): directed relationships showing how data moves

## Edge Types (Formal)

An edge e = (source, target, type) represents a data flow relationship:

| Edge Type | Notation | Definition |
|-----------|----------|------------|
| **TABLE_FLOW** | table_A → table_B | Data flows from table_A into table_B (e.g., INSERT INTO B SELECT FROM A) |
| **SCHEMA** | table → column | Column belongs to table (structural) |
| **ALIAS** | alias → original | Alias resolves to original name |
| **REF** | usage → source_col | Direct column reference in a statement |
| **AGGREGATE** | source_col → agg_result | SUM/COUNT/AVG applied to column(s) |
| **TRANSFORM** | source_col → transform_result | COALESCE/CAST/CONCAT applied |
| **WINDOW** | source_col → window_result | Window function (ROW_NUMBER, LAG, etc.) |
| **COMPUTED** | source_cols → case_result | CASE WHEN expression |
| **INDIRECT** | having_col → select_col | HAVING clause references SELECT column |
| **FILTER** | filter_expr → filtered_target | WHERE/HAVING condition constrains data flow |
| **JOIN** | join_key_left ↔ join_key_right | JOIN key condition linking two tables |
| **CORRELATED** | outer_col → inner_ref | Correlated subquery reference |
| **DML** | source → target_table | INSERT/UPDATE/DELETE/MERGE target |
| **SET_OP** | branch_L + branch_R → union_result | UNION/INTERSECT/EXCEPT combining branches |
| **SUBSET** | disconnected_component → bridge | Connects otherwise disconnected subgraphs |

## Data Flow Path

A data flow path for a target variable v_target:

**P(v_target)** = all scripts and variables that can transitively reach or be reached by v_target through any combination of edges.

Formally: the set of all nodes V' ⊆ V and edges E' ⊆ E such that there exists a path between v_target and every node in V' through edges in E'.

## Level 1 Graph

**Nodes**: scripts + tables  
**Edges**: TABLE_FLOW between scripts (via shared tables)

For a target table.field:
- Find all scripts that reference this field
- For each script, find its input tables and output tables
- Connect: input_table → script → output_table
- Scripts sharing tables are connected

## Level 2 Graph (within a single script)

**Nodes**: tables + columns  
**Edges**: All edge types within a single script

For a target table.field within script S:
- All variables inside S related to the target
- All edges of all types connecting these variables
- The "relevant" subset shows only nodes on paths to/from the target
- The "full" graph shows all variables in the script

## Cycles

Cycles CAN exist in the data flow:
- Self-referencing updates: `UPDATE t SET x = x + 1`
- Recursive CTEs
- Circular table references across scripts (script A → table T → script B → table T)

The visualization should handle cycles by using layered layout (topological sort with back-edges rendered as curved arcs).

## Display Principles

1. **L1**: snake/dagre-layered layout — scripts as subgraphs, tables as compound nodes containing their fields
2. **L2**: same layout — tables as compound nodes, operations as edges, field-level detail
3. Edge color = edge type (16 distinct colors)
4. Directional arrows on all edges
5. Tooltips on hover for edge type descriptions

---

## Column Flow Extraction

### Purpose

After variable extraction, build a complete `table_schemas` mapping from every table to its known columns. This is the foundation for field-level data flow — a column exists in the data flow if and only if it can be inferred to belong to a table.

### Algorithm

Iterative stabilization over 8 passes. Repeat all passes until no table gains new columns:

```python
def infer_table_schemas(variables, dependencies):
    schemas = {}  # {table_name: {column_name, ...}}
    
    changed = True
    while changed:
        prev_sizes = {t: len(c) for t, c in schemas.items()}
        
        # Pass 1: SCHEMA — table owns column
        for edge in dependencies:
            if edge.relationship == "SCHEMA":
                table = resolve_name(edge.source)
                col = resolve_name(edge.target)
                schemas.setdefault(table, set()).add(col)
        
        # Pass 2: DML — column flows into table
        for edge in dependencies:
            if edge.relationship == "DML":
                col = resolve_name(edge.source)
                table = resolve_name(edge.target)
                schemas.setdefault(table, set()).add(col)
        
        # Pass 3-5: Inheritance — output container inherits source columns
        for rel in ("TABLE_FLOW", "JOIN", "SET_OP"):
            for edge in dependencies:
                if edge.relationship == rel:
                    src = resolve_name(edge.source)
                    tgt = resolve_name(edge.target)
                    if src in schemas:
                        schemas.setdefault(tgt, set()).update(schemas[src])
        
        # Pass 6: ALIAS — original inherits to alias
        for edge in dependencies:
            if edge.relationship == "ALIAS":
                original = resolve_name(edge.source)
                alias = resolve_name(edge.target)
                if original in schemas:
                    schemas[alias] = schemas[original].copy()
        
        # Pass 7: Clean — strip "table." prefix
        cleaned = {}
        for table, cols in schemas.items():
            cleaned[table] = set()
            for col in cols:
                cleaned[table].add(col.split(".")[-1] if "." in col else col)
        schemas = cleaned
        
        # Check stabilization
        new_sizes = {t: len(c) for t, c in schemas.items()}
        if new_sizes == prev_sizes:
            changed = False
    
    return schemas
```

### Column-Carrying Edges

| Edge | Direction | Example | Pass |
|------|-----------|---------|------|
| SCHEMA | table → column | `c` owns `c.customer_id` | 1 |
| DML | column → table | `c.customer_id` flows into `stg_customers` | 2 |
| TABLE_FLOW | source → output | `c`'s columns → `⟐ output` | 3 |
| JOIN | table → output | `so`'s columns → JOIN result | 4 |
| SET_OP | branch → parent | UNION branch → combined result | 5 |
| ALIAS | original → alias | `crm_customers` inherits `c`'s schema | 6 |

Edges that do NOT carry column ownership: REF, TRANSFORM, AGGREGATE, WINDOW, COMPUTED, FILTER, INDIRECT, SUBSET, CORRELATED. These describe data flow operations but not structural column-to-table relationships.

### Iterative Propagation

Columns propagate through multi-hop chains. For example:

```
crm_customers ──[ALIAS]──> c ──[TABLE_FLOW]──> ⟐ output
                                                │
                                          [SCHEMA]
                                                ▼
                                          c.customer_id ──[DML]──> stg_customers
```

Single-pass processing fails if edges are processed out of order. The `while changed` loop guarantees all chains resolve regardless of edge order.

### Worked Example

For step2 (`INSERT INTO stg_customers SELECT c.customer_id, ... FROM crm_customers c`):

```
Iteration 1:
  Pass 1 (SCHEMA):    c → {c.customer_id, c.full_name, c.segment, c.region, c.is_active}
                       ⟐ output → {c.customer_id, c.full_name, c.segment, c.region}
  Pass 2 (DML):       stg_customers → {c.customer_id, c.full_name, c.segment, c.region}
  Pass 3-5:           (no new inheritance chains yet)
  Pass 6 (ALIAS):     crm_customers inherits c → {c.customer_id, ...c.is_active}
  Pass 7 (clean):     c → {customer_id, full_name, segment, region, is_active}
                       ⟐ output → {customer_id, full_name, segment, region}
                       stg_customers → {customer_id, full_name, segment, region}
                       crm_customers → {customer_id, full_name, segment, region, is_active}
  Sizes changed → continue

Iteration 2:
  No new edges to propagate → sizes stable → done.
  
Result:
  table_schemas = {
    "crm_customers": {customer_id, full_name, segment, region, is_active},
    "c":             {customer_id, full_name, segment, region, is_active},
    "stg_customers": {customer_id, full_name, segment, region},
    "⟐ output":      {customer_id, full_name, segment, region},
  }
```

---

## Field-Level Data Flow

When a user queries a specific field (`table=T, field=Y`), the L1 and L2 graphs are filtered to show only nodes and edges on the data flow path of field Y. UI/UX unchanged — same graph structure, same L1/L2 interactions, fewer elements.

### Lineage Set R

Given a queried field Y, the lineage set **R** is the transitive closure computed by:

```
R = {Y}
repeat until R stabilizes:
    for each node N in R:
        for each edge E incident to N:
            apply the edge-type-specific rule
            if rule fires, add the other endpoint to R
```

Nodes not in R are excluded from the graph. Edges where either endpoint is absent from R are excluded.

### Edge-Type Rules

Each of the 16 edge types has a specific rule. Direction: **↑** = upstream (backward from Y — "where does Y come from?"), **↓** = downstream (forward from Y — "where does Y go?").

---

#### 1. SCHEMA — column belongs to table

```
table ──[SCHEMA]──> column
```

| Direction | Rule | Meaning |
|-----------|------|---------|
| ↑ | column ∈ R → add table | The table contains this field |
| ↓ | table ∈ R → add columns **with a production edge from R** | Only columns connected to Y's chain via REF/TRANSFORM/AGGREGATE/WINDOW/COMPUTED/DML |

The ↓ direction is **production-filtered**: it does NOT blindly add all columns. A column is added only if it is the target of a production edge from a node already in R. This prevents unrelated same-table columns from entering the lineage.

---

#### 2. REF — direct column value reference

```
source_column ──[REF]──> target_expression
```

| Direction | Rule |
|-----------|------|
| ↑ | target ∈ R → add source_column |
| ↓ | source_column ∈ R → add target |

Bidirectional. Primary carrier of field values through the graph.

---

#### 3. TRANSFORM — function applied to column

```
source_column ──[TRANSFORM]──> transform_result
```

| Direction | Rule |
|-----------|------|
| ↑ | result ∈ R → add source_column |
| ↓ | source_column ∈ R → add result |

Bidirectional. `DATE(order_date) AS dt` — if `dt` ∈ R, source `order_date` is added.

---

#### 4. AGGREGATE — column consumed by aggregation

```
source_column ──[AGGREGATE]──> aggregate_result
```

| Direction | Rule |
|-----------|------|
| ↑ | result ∈ R → add source_column |
| ↓ | source_column ∈ R → add result |

Bidirectional. `SUM(amount) AS total` — if `total` ∈ R, source `amount` is added.

---

#### 5. WINDOW — column consumed by window function

```
source_column ──[WINDOW]──> window_result
```

| Direction | Rule |
|-----------|------|
| ↑ | result ∈ R → add source_column |
| ↓ | source_column ∈ R → add result |

Bidirectional. `ROW_NUMBER() OVER (PARTITION BY dept) AS rn`.

---

#### 6. COMPUTED — column consumed by CASE expression

```
source_column ──[COMPUTED]──> case_result
```

| Direction | Rule |
|-----------|------|
| ↑ | result ∈ R → add source_column |
| ↓ | source_column ∈ R → add result |

Bidirectional. `CASE WHEN amount > 100 THEN 'high' END AS tier`.

---

#### 7. TABLE_FLOW — table data feeds into output

```
table_alias ──[TABLE_FLOW]──> output_container
```

| Direction | Rule |
|-----------|------|
| ↑ | output ∈ R → add table_alias |
| ↓ | table_alias ∈ R → add output |

Bidirectional. Bridges table-level structure.

---

#### 8. ALIAS — name resolution

```
original_table ──[ALIAS]──> alias_table
```

| Direction | Rule |
|-----------|------|
| ↑ | alias ∈ R → add original |
| ↓ | original ∈ R → add alias |

Always bidirectional — purely naming, no data flow semantics.

---

#### 9. DML — data modification target

```
source ──[DML]──> target_table
```

| Direction | Rule |
|-----------|------|
| ↑ | target_table ∈ R → add source |
| ↓ | source ∈ R → add target_table |

Bidirectional. `c.customer_id ──[DML]──> stg_customers`.

---

#### 10. JOIN — table participates in JOIN

```
table ──[JOIN]──> output_container
```

| Direction | Rule |
|-----------|------|
| ↔ | **Conditional**: if table ∈ R AND at least one of its columns ∈ R via a production edge, add output_container |

JOIN does NOT propagate by itself. JOIN keys (`so.customer_id = sc.customer_id`) combine rows but don't produce new field values. Included only when columns are already in Y's chain.

---

#### 11. FILTER — WHERE/HAVING condition

```
column ──[FILTER]──> output_container
```

| Direction | Rule |
|-----------|------|
| ↔ | **Conditional**: if column ∈ R via a production edge, add output_container |

FILTER does NOT produce field values. `WHERE region = 'NA'` filters rows but doesn't contribute to any field's value. FILTER columns appear only if already in R.

---

#### 12. CORRELATED — correlated subquery reference

```
outer_col ──[CORRELATED]──> inner_ref
```

| Direction | Rule |
|-----------|------|
| ↑ | inner_ref ∈ R → add outer_col |
| ↓ | outer_col ∈ R → add inner_ref |

Bidirectional. Follows the reference between outer and inner query scopes.

---

#### 13. INDIRECT — HAVING→SELECT name reference

```
defined_var ──[INDIRECT]──> bare_ref
```

| Direction | Rule |
|-----------|------|
| ↑ | bare_ref ∈ R → add defined_var |
| ↓ | defined_var ∈ R → add bare_ref |

Bidirectional. Resolves name references within query scopes.

---

#### 14. SUBSET — disconnected component bridge

```
component ──[SUBSET]──> main
```

| Direction | Rule |
|-----------|------|
| ↔ | Always follow both ways |

Safety-net bridge. No semantic value for lineage, but always followed to prevent graph disconnection.

---

#### 15. SET_OP — UNION/INTERSECT/EXCEPT branch

```
branch ──[SET_OP]──> parent
```

| Direction | Rule |
|-----------|------|
| ↑ | parent ∈ R → add branch |
| ↓ | branch ∈ R → add parent |

Bidirectional. All UNION branches contribute to the combined output.

---

### Rules Summary

| Edge Type | Upstream | Downstream | Conditional? |
|-----------|----------|------------|--------------|
| SCHEMA | table ← column | table → column (production-filtered) | ↓ conditional |
| REF | source ← target | source → target | No |
| TRANSFORM | source ← result | source → result | No |
| AGGREGATE | source ← result | source → result | No |
| WINDOW | source ← result | source → result | No |
| COMPUTED | source ← result | source → result | No |
| TABLE_FLOW | alias ← output | alias → output | No |
| ALIAS | original ← alias | original → alias | No |
| DML | source ← target | source → target | No |
| JOIN | — | — | Yes — both directions |
| FILTER | — | — | Yes — both directions |
| CORRELATED | outer ← inner | outer → inner | No |
| INDIRECT | defined ← ref | defined → ref | No |
| SUBSET | component ↔ main | component ↔ main | No (always) |
| SET_OP | branch ← parent | branch → parent | No |

### Worked Example

```sql
INSERT INTO stg_customers (customer_id, name, segment, region)
SELECT c.customer_id, c.full_name, c.segment, c.region
FROM crm_customers c
WHERE c.is_active = 1 AND c.region IN ('NA', 'EMEA');
```

**Query:** `table=stg_customers, field=customer_id`

```
Step 1: Seed — R = {stg_customers.customer_id}

Step 2: SCHEMA ↑ — stg_customers.customer_id ∈ R
    Add: stg_customers (table)

Step 3: DML ↑ — stg_customers ∈ R
    Find: c.customer_id ──[DML]──> stg_customers
    Add: c.customer_id

Step 4: SCHEMA ↑ — c.customer_id ∈ R
    Add: c (alias table)

Step 5: ALIAS ↑ — c ∈ R
    Add: crm_customers

Step 6: TABLE_FLOW ↓ — c ∈ R
    Add: ⟐ output

Step 7: SCHEMA ↓ (production-filtered) — ⟐ output ∈ R
    ⟐ output columns: c.customer_id, c.full_name, c.segment, c.region
    Production check for each:
    - c.customer_id: has DML ↑ from R → PASSES (already in R)
    - c.full_name: no production edge from R → SKIPPED
    - c.segment: no production edge from R → SKIPPED
    - c.region: no production edge from R → SKIPPED
      (FILTER c.region → ⟐ output exists, but region ∉ R via production)
    R stabilizes.

Final R: {
    stg_customers.customer_id, stg_customers,
    c.customer_id, c,
    crm_customers,
    ⟐ output
}

Excluded: c.full_name, c.segment, c.region, c.is_active
```

### Design Framework

```
┌──────────────────────────────────────────────────────────┐
│ EXISTING                                                  │
│ search_dataflow(table, field)                             │
│   → find scripts involving table                         │
│   → build L1 graph (scripts + table nodes)               │
│   → build L2 graph (per-script: tables + fields + edges) │
├──────────────────────────────────────────────────────────┤
│ NEW                                                       │
│ compute_field_lineage(Y, graph)                           │
│   → BFS from Y through 16 edge-type-specific rules       │
│   → returns lineage set R (fields + tables + scripts)    │
│                                                           │
│ filter_graph(graph, R)                                    │
│   → keep nodes ∈ R, drop rest                            │
│   → keep edges where both endpoints ∈ R                  │
│   → same structure, fewer elements                       │
└──────────────────────────────────────────────────────────┘
```

### Backward Compatibility

When no specific field is queried (table-only search), or when `lineage_mode` is off, the full table-level graph is shown — behavior unchanged from the current definition.
