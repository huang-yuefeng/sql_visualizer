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
