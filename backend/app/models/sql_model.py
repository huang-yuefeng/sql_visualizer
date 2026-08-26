"""
SQL Data Model Taxonomy
========================
Canonical reference mapping node types and edge types to SQL data objects.

This file documents the complete type system used by the GPS SQL Data Flow
Visualizer. It serves as the single source of truth for:

1. Node types (variables) — what each named thing in SQL IS
2. Edge types (dependencies) — how data FLOWS between variables
3. SQL data objects — the SQL language constructs each type represents

Loading this file is sufficient to understand the semantic model without
reading any extraction or graph-building code.

## Node Types (VariableType)

Each variable extracted from SQL is classified into one of 14 types,
grouped into 6 categories aligned with SQL data object semantics.

### Category: Data Sources
Table-like objects that serve as sources or targets of data movement.

| Type | enum | SQL Objects Covered |
|------|------|---------------------|
| `table` | `VariableType.TABLE` | TABLE, TEMPORARY TABLE, FOREIGN DATA WRAPPER / LINKED SERVER |
| `view` | `VariableType.VIEW` | VIEW, MATERIALIZED VIEW (virtual source only, no stored data) |
| `cte` | `VariableType.CTE` | CTE (Common Table Expression, WITH ... AS) |
| `subquery` | `VariableType.SUBQUERY` | SUBQUERY (nested SELECT in FROM / JOIN) |
| `virtual_table` | `VariableType.VIRTUAL_TABLE` | SELECT output, JOIN result — a conceptual result set |
| `function_table` | `VariableType.FUNCTION_TABLE` | Table-valued function call used as a row source (FROM/JOIN) |

### Category: Column References
Column-level references that carry individual data values.

| Type | enum | SQL Objects Covered |
|------|------|---------------------|
| `column` | `VariableType.COLUMN` | Column reference: table.column or bare column name |
| `cte_column` | `VariableType.CTE_COLUMN` | Column defined inside a CTE's SELECT list |

### Category: DML Targets
Tables that are the target of data-modifying operations.

| Type | enum | SQL Objects Covered |
|------|------|---------------------|
| `merge_target` | `VariableType.MERGE_TARGET` | MERGE target table (INSERT/UPDATE/DELETE targets use `table` with defined_in) |

### Category: Set Operations
Structures produced by SQL set operators.

| Type | enum | SQL Objects Covered |
|------|------|---------------------|
| `union_branch` | `VariableType.UNION_BRANCH` | UNION / INTERSECT / EXCEPT: one arm of a set operation |

### Category: Computed Values
Values produced by evaluating SQL expressions.

| Type | enum | SQL Operations Covered |
|------|------|------------------------|
| `aggregate` | `VariableType.AGGREGATE` | SUM, COUNT, AVG, MIN, MAX, GROUP_CONCAT |
| `window` | `VariableType.WINDOW` | ROW_NUMBER, RANK, DENSE_RANK, LAG, LEAD, SUM() OVER(), etc. |
| `case` | `VariableType.CASE` | CASE WHEN ... THEN ... ELSE ... END |
| `transform` | `VariableType.TRANSFORM` | COALESCE, CAST, CONCAT, JSON_EXTRACT, DATE functions, math functions |
| `expression` | `VariableType.EXPRESSION` | Generic computed expression alias: (a+b) AS total, subquery scalar |

### Category: Literals
Constant values embedded in the SQL text.

| Type | enum | SQL Operations Covered |
|------|------|------------------------|
| `literal` | `VariableType.LITERAL` | String/number literals: 'active', 100, NULL |

---

## Edge Types (relationship field)

Each dependency edge is classified into one of 14 types representing
specific SQL data flow semantics. See dependency_graph.py for creation logic.

### Data Flow Edges
Direct data movement between nodes.

| Edge Type | Meaning | SQL Context |
|-----------|---------|-------------|
| `REF` | Direct column value reference | `t.amount` used in an expression |
| `AGGREGATE` | Column consumed by aggregation | `SUM(t.amount)` → reads from `t.amount` |
| `TRANSFORM` | Column consumed by function | `COALESCE(t.tax, 0)` → reads from `t.tax` |
| `WINDOW` | Column consumed by window function | `ROW_NUMBER() OVER (PARTITION BY t.batch)` |
| `COMPUTED` | Column consumed by CASE expression | `CASE WHEN t.amount > 100` → reads from `t.amount` |

### Structural Edges
Schema and naming relationships.

| Edge Type | Meaning | SQL Context |
|-----------|---------|-------------|
| `SCHEMA` | Column belongs to table/CTE/VT | `t.amount` belongs to table alias `t` |
| `ALIAS` | Alias points to original name | `FROM users u` → `u` is alias for `users` |

### Query Structure Edges
Connect data sources to query output.

| Edge Type | Meaning | SQL Context |
|-----------|---------|-------------|
| `SELECT` | FROM table feeds into SELECT output | `FROM t` without column bridging → `t` → VT |
| `JOIN` | JOIN table participates in output | `LEFT JOIN orders o` → `o` → VT |
| `SET_OP` | Set operation branch feeds output | `UNION ALL` branch → parent VT |
| `DML` | Data modification source→target | MERGE source columns → target table |
| `SUBSET` | Cross-component bridge | Subquery/CTE boundary when no named column shared |

### Flow Control Edges
Conditional and indirect data influences.

| Edge Type | Meaning | SQL Context |
|-----------|---------|-------------|
| `INDIRECT` | Defined variable → bare name ref | `cnt` in HAVING referencing `COUNT(*) AS cnt` in SELECT |
| `FILTER` | WHERE/HAVING condition | `WHERE t.status = 'active'` — filter controls row flow |
| `ROW_FLOW` | Row-level flow bridge (R29 continuation) | Searched field's row-selection effect into a downstream statement's rows (e.g. subquery output `⟐ t` → CTE `temp_kmbh_gl`); the field's VALUE does not flow — which ROWS flow. Emitted by the L2 walker (#226), never by the dependency builder |

---

## SQL Data Objects Mapping

This section maps the user's SQL data object knowledge to our node/edge types.

| SQL Data Object | Primary Node Type | Edge Types Involved | Detection |
|-----------------|-------------------|---------------------|-----------|
| TABLE | `table` | SCHEMA→columns, SELECT/JOIN→VT | FROM clause, JOIN clause |
| TEMPORARY TABLE | `table` | Same as TABLE | CREATE TEMP TABLE (same as TABLE to sqlglot) |
| VIEW | `table` | SCHEMA→columns, SELECT→VT | FROM clause (appears as table) |
| MATERIALIZED VIEW | `table` | Same as VIEW | FROM clause (appears as table) |
| CTE | `cte` | SCHEMA→inner vars, SELECT→VT | WITH clause |
| SUBQUERY | `subquery` | SELECT→VT, SCHEMA→columns | FROM/JOIN (SELECT ...) |
| SELECT | `virtual_table` | SCHEMA→output columns | Top-level or nested SELECT |
| JOIN | `virtual_table` | JOIN edges from JOIN tables | JOIN clause |
| UNION/INTERSECT/EXCEPT | `union_branch` | SET_OP→VT | Set operation branches |
| INSERT | `table` (target) | DML edges | INSERT INTO statement |
| UPDATE | `table` (target) | TRANSFORM→target | UPDATE statement |
| DELETE | `table` (target) | FILTER→target | DELETE FROM statement |
| MERGE | `merge_target` | DML edges | MERGE INTO statement |
| CTAS | `table` | SELECT→VT→new table | CREATE TABLE ... AS SELECT |
| SELECT INTO | `table` | SELECT→VT→new table | SELECT ... INTO ... FROM |
| TRIGGER | (not extracted) | N/A | Not yet supported |
| FOREIGN KEY CASCADE | (not extracted) | N/A | Not yet supported |
| CURSOR | (not extracted) | N/A | Not yet supported |
| TABLE VARIABLE | `table` | Same as TABLE | DECLARE @t TABLE (if supported by dialect) |
| FOREIGN DATA WRAPPER | `table` | Same as TABLE | FROM external_table (appears as table) |

---

## Categories

Node types are grouped into these categories for frontend filtering:

| Category | Types | Color Theme |
|----------|-------|-------------|
| Data Source | table, cte, subquery, virtual_table, function_table | Blue/Green |
| Column Reference | column, cte_column | Light Blue/Green |
| DML Target | merge_target | Red |
| Set Operation | union_branch | Grey |
| Computed Value | aggregate, window, case, transform, expression | Teal/Purple/Orange/Pink/Yellow |
| Literal | literal | Grey |
"""
