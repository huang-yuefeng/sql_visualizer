# Node Creation Algorithm — Complete Overview

> **Date:** 2026-07-23 | **Version:** 3.3.65

---

## Architecture

```
SQL Text
  │
  ├── variable_extractor_v2.py   → VariableDefinition[] (15 types)
  │     └── sqlglot parse → AST walk → classify each identifier
  │
  ├── dependency_graph.py        → VariableDependency[] (13 edge types)
  │     └── 12-phase edge creation: TABLE_FLOW → ALIAS → REF → AGGREGATE → ...
  │
  └── graph_service.py           → Cytoscape JSON (nodes + edges)
        │
        ├── _build_l1_graph()          → Cross-script pipeline view
        │     └── dataflow_service.py:340-500
        │
        └── _build_l2_graph()          → Per-script detail view  
              └── dataflow_service.py:1122-1630
```

---

## L1 Graph — Cross-Script Pipeline View

### Step 1: Classify tables by role

For each script, collect `input_tables` and `output_tables`:

```
all_inputs  = union of all scripts' input_tables
all_outputs = union of all scripts' output_tables

source_tables       = all_inputs - all_outputs   (only consumed, never produced)
intermediate_tables = all_inputs ∩ all_outputs   (both consumed and produced)
output_tables       = all_outputs - all_inputs   (only produced, never consumed)
```

### Step 2: Create table nodes

| Role | Node Type | Example |
|------|-----------|---------|
| source_tables | `source_table` | `raw_orders`, `crm_customers` |
| intermediate_tables | `intermediate_table` | `stg_orders`, `stg_customers` |
| output_tables | `output_table` or `query_output` | `daily_summary`, `⟐ output` |

Rules:
- ~~Skip names ≤3 lowercase letters (SQL aliases like `so`, `c`)~~ **TOO ROUGH — see issue below**
- Skip names starting with `⟐` (virtual tables — handled separately)
- A table is `query_output` if its name starts with `⟐` (virtual SELECT result)

### ⚠️ Issue: Alias Filter Too Aggressive

`len(tname) <= 3 and tname.islower() and tname.isalpha()` at lines 397, 404, 411 filters out all 3-letter lowercase names. This catches SQL aliases like `so`, `c`, `t` but also filters legitimate table names: `app`, `job`, `dim`, `log`, `tag`, `fee`, `tax`, `url`, `day`.

**Suggested fix — use `alias_map` instead of length heuristic:**

L2 already builds an `alias_map` at lines 1241-1264 by checking:
- Variable has exactly 1 `source_table` (it references another table, not standalone)
- Short name has an ALIAS edge in the dependency graph

Apply the same logic for L1: instead of filtering by length, check if the name appears in the script metadata as an alias of another table:

```python
# Before creating L1 table nodes, build alias set from script metadata:
aliases = set()
for s in all_scripts:
    for t in s.get("input_tables", []):
        if t.startswith("⟐"): continue
        # Check if this is an alias by looking at graph data
        graph = s.get("graph", {})
        for n in graph.get("nodes", []):
            nd = n.get("data", n)
            if nd.get("label") == t:
                src_tables = nd.get("source_tables", [])
                if len(src_tables) == 1 and src_tables[0] != t:
                    aliases.add(t)  # t is an alias, not a real table

# Then filter: skip aliases, not short names
for tname in source_tables:
    if tname in aliases: continue  # replaces len(tname) <= 3 check
```

### Step 3: Create script nodes + edges

For each script:
```
Node: { id: script_hash, type: "script_node", label: script_name }
Edges:
  table → script   "reads_from"    (for each input_table)
  script → table   "writes_to"     (for each output_table)
```

### Step 4: Virtual output for SELECT-only scripts

If a script has inputs but NO outputs (pure SELECT query):
```
Create: terminal node { type: "query_output", label: "Query Result" }
Edge:   script → terminal  "writes_to"
```

This ensures the pipeline graph is complete — every data flow has a visible endpoint.

---

## L2 Graph — Per-Script Detail View

### Phase 0: Alias Detection

Before classifying nodes, build `alias_map`:
- Variables of type `table/view/cte/subquery/virtual_table` with exactly 1 `source_table` → alias
- Short lowercase names (≤3 chars) with ALIAS edge → alias

This prevents creating duplicate table nodes for `raw_orders` and its alias `o`.

### Phase 1: Node Classification by VariableType

Each `VariableDefinition` is classified:

| VariableType | L2 Node Type | Description |
|-------------|-------------|-------------|
| `table`, `view` | `source_table` | Physical table (read-only in this script) |
| `cte` | `cte_table` | Common Table Expression |
| `subquery` | `intermediate_table` | Subquery result |
| `virtual_table` | `intermediate_table` | SELECT/JOIN output |
| `merge_target` | `intermediate_table` | MERGE target |
| `union_branch` | `intermediate_table` | UNION branch result |
| `column` | `field` (child of table) | Column reference |
| `cte_column` | `field` (child of table) | CTE column |
| `aggregate` | `field` (child of table) | Aggregation result |
| `window` | `field` (child of table) | Window function result |
| `case` | `field` (child of table) | CASE result |
| `transform` | `field` (child of table) | Transformation result |
| `expression` | `field` (child of table) | Computed expression |
| `literal` | `field` (child of table) | Literal value |

### Phase 2: Target Identification

Given the search `table.field`:
1. Match nodes where `label == field` or `label == table.field`
2. BFS upstream and downstream from targets → `direct_ids`
3. All other nodes → `indirect` (dimmed in display)

### Phase 3: Compound Structure

Table nodes become **compound parents**. Field nodes become **children** positioned inside them.

### Phase 4: Edge Creation with sql_range

For each dependency edge:
1. Map source/target IDs to L2 node IDs
2. Classify edge type → category (copy, compute, aggregate, filter, etc.)
3. Call `find_sql_range()` → `sql_range_finder.py`
4. Attach `sql_range` to edge data

### Phase 4.5: Field Promotion

Fields attached to alias tables are promoted to the canonical table. Edges from aliases are remapped to canonical table nodes.

### Phase 5: DML Edge Routing (Bug 1 Fix)

For each DML edge (`INSERT/UPDATE/DELETE/MERGE`):
```
Original: source_table ──DML──→ target_table

After fix:
  source_table ──TABLE_FLOW──→ qo_node (⟐ output) ──DML──→ target_table
```

The `qo_node` represents the SELECT result that feeds the INSERT. Created at line 1572 with:
- Type: `query_output`
- Label: `⟐ output`
- Dedup key: `(target_table)` — one qo per DML target

### Phase 6: Dedup + Partition

1. Merge edges with same `(source, target, edge_type)` — keep shortest `sql_range`
2. `partition_edge_ranges()` — priority-based line assignment (FILTER > JOIN > ... > TABLE_FLOW)

### ⚠️ BUG: Duplicate Output Nodes

Two mechanisms independently create output-labeled nodes for the same data:

```
Mechanism A (Phase 1, line 1294):
  is_output_node flag → creates "output_table" node for SELECT result
  Label: "⟐ output"

Mechanism B (Phase 5, line 1572):
  DML edge routing → creates "query_output" qo_ node for INSERT target  
  Label: "⟐ output"
```

When a script has `INSERT INTO ... SELECT ...`, BOTH fire → **two `⟐ output` nodes** in step3.

---

## Node ID Naming Convention

| Node Type | ID Pattern | Example |
|-----------|-----------|---------|
| Table (L1) | `tbl_{table_name}` | `tbl_raw_orders` |
| Table (L2) | `l2_tbl_{hash[:10]}` | `l2_tbl_e736ae68ef` |
| Field (L2) | `fld_{hash[:10]}` | `fld_b568c13cd3` |
| Script | `{script_hash}` | `9f15a331ed4d` |
| Query output (L1) | `tbl_⟐result_{hash[:8]}` | `tbl_⟐result_9f15a331` |
| Query output (L2) | `qo_{src}_{target}` | `qo_tbl_raw_orders_tbl_stg_orders` |
| Edge (L2) | `l2e_{hash[:12]}` | `l2e_ae2a3cdc6e5e` |


---

## Architecture: Extractor → L1/L2 Pipeline (v3.4)

```
SQL Text
  │
  ├── variable_extractor_v2.py   → variables + dependencies
  │     │
  │     └── schema_inference()          ← NEW: build table_schemas
  │           │
  │           └── table_schemas: {table_name: {col1, col2, ...}}
  │
  ├── dependency_graph.py        → edges (13 types)
  │
  └── L1/L2 builders             → read table_schemas directly
        │
        ├── L1: scripts + tables (field filtering from table_schemas)
        └── L2: tables + fields (field visibility from table_schemas)
```

The extractor owns all SQL semantics. L1/L2 are pure visualization layers — they read the extractor's output, format for Cytoscape, and filter by table_schemas.

---

## Schema Inference Algorithm (R18)

### Purpose

After variable extraction, build a complete `table_schemas` dict mapping every table to its known columns. This eliminates multi-path seed lookup complexity and makes field-level filtering a simple dict check.

### Algorithm

```python
def infer_table_schemas(variables, dependencies):
    """
    Build table_schemas: {table_name: {column_name, ...}}
    
    Edges that carry column-to-table relationships:
      SCHEMA:       table ──→ column     "table owns this column"   (source tables, VTs)
      DML:          column ──→ table     "column flows into table"  (INSERT targets)
      TABLE_FLOW:   alias ──→ output     "data carries over"        (SELECT output, CTAS)
      JOIN:         table ──→ output     "data carries over"        (JOIN source tables)
      SET_OP:       branch ──→ parent    "data carries over"        (UNION branches)
    """
    schemas = {}
    
    # ── Iterative stabilization ──
    # Columns propagate through multi-hop chains (e.g. ALIAS → TABLE_FLOW → DML).
    # Single-pass processing may miss chains if edges are processed out of order.
    # Solution: repeat all passes until schemas stop changing.
    
    changed = True
    while changed:
        changed = False
        prev_sizes = {t: len(c) for t, c in schemas.items()}
    
    # Pass 1: Collect columns from SCHEMA edges (table → column)
    for edge in dependencies:
        if edge.relationship == "SCHEMA":
            table_name = resolve_name(edge.source_id)
            col_name = resolve_name(edge.target_id)
            schemas.setdefault(table_name, set()).add(col_name)
    
    # Pass 2: Collect columns from DML edges (column → table)
    for edge in dependencies:
        if edge.relationship == "DML":
            col_name = resolve_name(edge.source_id)
            table_name = resolve_name(edge.target_id)
            schemas.setdefault(table_name, set()).add(col_name)
    
    # Pass 3: Collect from TABLE_FLOW edges (alias → output)
    for edge in dependencies:
        if edge.relationship == "TABLE_FLOW":
            source_name = resolve_name(edge.source_id)
            target_name = resolve_name(edge.target_id)
            if source_name in schemas:
                schemas.setdefault(target_name, set()).update(schemas[source_name])
            elif target_name in schemas:
                schemas.setdefault(source_name, set()).update(schemas[target_name])
    
    # Pass 4: Collect from JOIN edges (table → output)
    # JOIN carries source table columns into the JOIN output, same as TABLE_FLOW
    for edge in dependencies:
        if edge.relationship == "JOIN":
            source_name = resolve_name(edge.source_id)
            target_name = resolve_name(edge.target_id)
            if source_name in schemas:
                schemas.setdefault(target_name, set()).update(schemas[source_name])
            elif target_name in schemas:
                schemas.setdefault(source_name, set()).update(schemas[target_name])
    
    # Pass 5: Collect from SET_OP edges (branch → parent)
    # UNION/INTERSECT/EXCEPT parent inherits columns from all branches
    for edge in dependencies:
        if edge.relationship == "SET_OP":
            source_name = resolve_name(edge.source_id)   # branch
            target_name = resolve_name(edge.target_id)   # parent
            if source_name in schemas:
                schemas.setdefault(target_name, set()).update(schemas[source_name])
    
    # Pass 7: Resolve aliases — alias inherits columns from original
    for edge in dependencies:
        if edge.relationship == "ALIAS":
            original = resolve_name(edge.source_id)  # crm_customers
            alias = resolve_name(edge.target_id)      # c
            if original in schemas:
                schemas[alias] = schemas[original].copy()
    
    # Pass 8: Clean column names — strip table prefix
    cleaned = {}
    for table, cols in schemas.items():
        cleaned[table] = set()
        for col in cols:
            cleaned[table].add(col.split(".")[-1] if "." in col else col)
    
    # ── Stabilization check ──
    for t, cols in cleaned.items():
        if len(cols) != prev_sizes.get(t, 0):
            changed = True
            break
    schemas = cleaned  # start next iteration with cleaned names
    
    return cleaned
```

### Worked Example

Input: step2 (`INSERT INTO stg_customers SELECT c.customer_id, ... FROM crm_customers c`)

```
Pass 1 (SCHEMA):
  c        → {c.customer_id, c.full_name, c.segment, c.region, c.is_active}
  ⟐ output → {c.customer_id, c.full_name, c.segment, c.region}

Pass 2 (DML):
  stg_customers → {c.customer_id, c.full_name, c.segment, c.region}

Pass 3 (TABLE_FLOW):
  c ──[TABLE_FLOW]──> ⟐ output
  c has schema → ⟐ output inherits: {c.customer_id, c.full_name, c.segment, c.region, c.is_active}
  (already has these from SCHEMA pass — merge)

Pass 4 (JOIN):
  (step2 has no JOIN edges — shown here from step3:)
  so ──[JOIN]──> ⟐ output: so has schema → ⟐ output inherits so's columns
  sc ──[JOIN]──> ⟐ output: sc has schema → ⟐ output inherits sc's columns

Pass 5 (SET_OP):
  (shown from a UNION example:)
  branch ──[SET_OP]──> union_result: branch has schema → parent inherits

Pass 7 (ALIAS):
  crm_customers inherits c's schema:
  crm_customers → {c.customer_id, c.full_name, c.segment, c.region, c.is_active}

Pass 8 (clean prefixes):
  crm_customers:  {customer_id, full_name, segment, region, is_active}
  c:              {customer_id, full_name, segment, region, is_active}
  stg_customers:  {customer_id, full_name, segment, region}
  ⟐ output:       {customer_id, full_name, segment, region}
```

### Architecture Change

| Component | Current | New |
|-----------|---------|-----|
| Extractor output | variables + edges | variables + edges + **table_schemas** |
| Seed lookup | 4-rule fuzzy label matching | **O(1) dict check** in table_schemas |
| L2 field parent | 3 paths (SCHEMA, DML, parent) | **1 check**: table_schemas |
| Post-filter | Name-based column filter (lines 1070-1093) | **Removed** — BFS rules handle it |
| L1 lineage | Not wired | **Wired**: create_search → filter_relevant |

### Field-Level Lineage Steps

```
Step 1: Construct initial R
    └── lookup table in table_schemas, validate field, find seed node

Step 2: Expand R by BFS
    └── walk edges with type-specific rules (see DATAFLOW_FORMAL_DEFINITION.md)

Step 3: Filter graph
    └── keep nodes/edges in R, drop rest. No name-based post-filter needed.

Step 4: Wire into pipeline
    └── create_search accepts lineage_mode, calls filter_relevant()
```

### Seed Lookup (after schema inference)

```python
def find_seed(table, field, table_schemas, nodes, edges):
    # Validate
    if table not in table_schemas:
        return None  # table not found
    if field not in table_schemas[table]:
        return None  # field not in table
    
    # Find the node sourcing this field for this table
    # Check both direct SCHEMA and DML-based ownership
    for n in nodes:
        nd = n.get("data", n)
        if field in nd.get("label", ""):
            # Is this field owned by the table? (SCHEMA)
            for e in edges:
                ed = e.get("data", e)
                if ed.get("source") == table_id and ed.get("target") == nd["id"]:
                    return nd["id"]
            # Does this field flow into the table? (DML)
            for e in edges:
                ed = e.get("data", e)
                if ed.get("target") == table_id and ed.get("source") == nd["id"]:
                    return nd["id"]
    return None
```
