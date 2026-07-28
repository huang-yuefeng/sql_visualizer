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
