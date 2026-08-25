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

### Table Type Invariants

These invariant rules prevent the most common class of field-display bugs. The rules are **operations-triggered**: specific edge types in the dependency graph determine field placement — no blind inheritance, no heuristics.

#### Alias Table — Field Synchronization

An alias table (`c`, `so`, `sc`) is created via the **ALIAS edge** (`original_table → alias_table`). It is a temporary name mapping within a single script.

**Operation:** When an ALIAS edge exists, copy field nodes between the two tables in both directions. The alias and its canonical table always have identical field sets.

```
ALIAS edge detected: crm_customers → c
  → c's fields → copy to crm_customers
  → crm_customers's fields → copy to c
```

**In L1:** Aliases are script-local — resolve to canonical names. `c` → `crm_customers`. Only canonical names appear.

**In L2:** Both alias and canonical table are shown, with synchronized field sets.

#### Output Table — SCHEMA-Defined Fields

An output table (`⟐ output`) is a virtual table created for SELECT results and intermediate flows.

**Operation:** An output table's fields = {columns with a **SCHEMA edge from this output table**}. Every column that was SELECTed has a SCHEMA edge from `⟐ output`. No blind inheritance — the extractor already recorded the exact column list.

```
SCHEMA edges from ⟐ output:
  ⟐ output → c.customer_id    → field: customer_id
  ⟐ output → c.full_name      → field: full_name
  ⟐ output → c.segment        → field: segment
  ⟐ output → c.region         → field: region
No SCHEMA to c.is_active       → WHERE only, not in output
```

**In L2:** Output table compound nodes display exactly the columns listed by their outgoing SCHEMA edges. If the SCHEMA edges were filtered by lineage, only lineage-relevant fields appear.

**In L1 (R29, 2026-08-12):** tables appear without field children — L1 scale is scripts + tables only.

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
| **ROW_FLOW** | rowset_A → rowset_B | Row-level flow: the searched field's row-selection (WHERE/JOIN) selects rows that flow into the downstream statement's output, without the field's value being copied |

## Data Flow Path

A data flow path for a target variable v_target:

**P(v_target)** = all scripts and variables that can transitively reach or be reached by v_target through any combination of edges.

Formally: the set of all nodes V' ⊆ V and edges E' ⊆ E such that there exists a path between v_target and every node in V' through edges in E'.

## Level 1 Graph

**Nodes**: scripts + tables (the tables on the queried field's flow, between scripts — no fields, no intra-script detail)  
**Edges**: reads_from (table → script), writes_to (script → table)

L1 shows the **data flow of the queried field** — the same field-level semantic as L2 — projected to cross-script scale. It is not a table-level pipeline around the queried table: a script or table appears in L1 **iff** it carries a field in the queried field's flow.

For a target table.field Y, in the query direction D (upstream by default):
- Compute Y's field flow with the **same strict field-level walker L2 uses**, restricted to direction D
- **Writing/upstream flow**: the fields that WRITE (produce) Y — walked backward from Y
- **Reading/downstream flow**: the fields that READ Y — walked forward from Y
- A script participates iff its script contains ≥1 field of the directional flow
- A table participates iff it carries ≥1 field of the directional flow
- Scripts and tables that only read or write the queried TABLE (not the queried field's flow) are **not** included

**Query direction (requirement change 2026-08-12, R29):** the direction is a **query setting in the query panel** — upstream (writing data flow, **default**) / downstream (reading data flow). L1 renders the flow in that direction; L2 follows the same direction automatically — L2 is the zoom-in of L1.

## Level 2 Graph (within a single script)

**Nodes**: tables + columns  
**Edges**: All edge types within a single script

For a target table.field within script S:
- All variables inside S related to the target
- All edges of all types connecting these variables
- The "relevant" subset shows only nodes on paths to/from the target
- The "full" graph shows all variables in the script

L2 is the **zoom-in of L1**: it shows the same field flow of Y, in the same query direction (upstream/writing or downstream/reading), inside the clicked script. No separate direction control — the direction is carried from the query panel (R29, 2026-08-12).

### L2 Table Node Styling (display-only) — 2026-08-13 (v3.3.157)

A **display-only** redesign of the 5 L2 table-compound node types. Backend `type`
strings are **unchanged** (`source_table` / `output_table` / `cte_table` /
`intermediate_table` / `alias_table`) — no cache, benchmark, or snapshot impact;
L1 untouched.

**Display names** (`L2_TABLE_TYPE_NAMES` in `frontend/src/utils/graphStyles.js`):

| Type | Display name |
|------|--------------|
| `source_table` | Source table |
| `output_table` | Target table |
| `cte_table` | With table |
| `intermediate_table` | Anonymous table |
| `alias_table` | Alias table |

**Shape:** all 5 L2 table compounds render as **solid rectangles** (dashed borders
removed); differentiation is by **color only**.

**Color palette** (single-sourced as `L2_TABLE_COLORS`):

| Type | Display name | Fill | Border |
|------|--------------|------|--------|
| `source_table` | Source table | blue `#4A90D9` | `#5DADE2` |
| `output_table` | Target table | green `#2ECC71` | `#58D68D` |
| `cte_table` | With table | purple `#9B59B6` | `#AF7AC5` |
| `intermediate_table` | Anonymous table | gray `#5a5a7a` | `#7a7a9a` |
| `alias_table` | Alias table | cyan `#17A2B8` | `#3BB9C9` |

- **With table** border changed from green to purple (`#AF7AC5`) — no longer
  collides with Target.
- **Alias table** changed from orange to cyan (`#3BB9C9`) — no longer reads as the
  searched-field gold `#FFD700`.

**Legend** (`DataFlowLegend.jsx`) regrouped **by level** into three groups:
- **L2 Node Types** — the 5 types + display names + their colors.
- **L2 Node Roles** — Source / Target / Waypoint (unchanged).
- **Field Marker** — the searched field, gold, field-level.

Fixes the v3.3.156 mislabel: that legend entry called the gold/yellow nodes
"Searched field", but those nodes are **alias tables** (orange); the searched-field
gold is a **field-level marker only**. Grouping types/roles/field-marker separately
means no level is presented as a peer of another.

**Status: implemented 2026-08-13 (v3.3.157).** `L2_TABLE_TYPE_NAMES` +
`L2_TABLE_COLORS` added to `frontend/src/utils/graphStyles.js` (placed before
`COMPOUND_STYLES`, which consumes them — the 5 compound rules now reference the
palette); the legacy green/dashed `cte_table` override in `L2_DETAIL_STYLES` was
removed (it assembled after `COMPOUND_STYLES` and would have won the cascade).
`DataFlowLegend.jsx` + `DataFlowLegend.test.jsx` regrouped by level. Display-only:
L2 node `type` strings, caches, snapshots, benchmark unchanged; L1 untouched.

> **Superseded 2026-08-13 (v3.3.158):** the 3-group legend (L2 Node Types / L2 Node
> Roles / Field Marker) described above was superseded — the **L2 Node Roles** and
> **Field Marker** groups were removed in v3.3.158 by user decision; the legend now
> shows only the 5 table node types. See the next section.

### L2 Legend — only the 5 table node types (2026-08-13, v3.3.158)

The L2 legend renders only the 5 table-node types (display names + colors from
`L2_TABLE_COLORS`). The **"L2 Node Roles"** group (Source / Target / Waypoint,
R28) and the **"Field Marker"** searched-field group were **removed** from the
legend by user ruling (2026-08-13). Node role badges on the graph and the gold
`#FFD700` searched-field node styling are **unchanged** — only the legend entries
were removed. Files: `frontend/src/components/DataFlowLegend.jsx` (+ test).

## Cycles

Cycles CAN exist in the data flow:
- Self-referencing updates: `UPDATE t SET x = x + 1`
- Recursive CTEs
- Circular table references across scripts (script A → table T → script B → table T)

The visualization should handle cycles by using layered layout (topological sort with back-edges rendered as curved arcs).

## Display Principles

1. **L1**: snake/dagre-layered layout — scripts as subgraphs, tables as compound nodes on the queried field's flow (no field children; R29, 2026-08-12)
2. **L2**: same layout — tables as compound nodes, operations as edges, field-level detail
3. Edge color = edge type for **value flow**; **structure** edges (SCHEMA/ALIAS/SUBSET) share one uniform gray (R30, 2026-08-13)
4. **Mid-point** direction arrows on **value-flow** edges (`source → target`); structure edges carry no arrow (R30, 2026-08-13)
5. Tooltips on hover for edge type descriptions

## Edge Direction Display (R30, 2026-08-13)

The L2 graph separates **value-flow** edges from **structure** edges and shows each
value-flow edge's direction with a **mid-point arrow**; a click on a value-flow edge
reveals its **flow cone** in two colors — a static highlight, no animation.

### Two edge classes

| Class | Edge types | Rendering |
|-------|-----------|-----------|
| **Value flow** | `TABLE_FLOW, DML, TRANSFORM, COMPUTED, AGGREGATE, WINDOW, REF, FILTER, JOIN, SET_OP, SUBQUERY, CORRELATED, INDIRECT` | per-type color; **mid-point arrow**; highlightable |
| **Row-level flow** | `ROW_FLOW` | flow-class (arrow + highlightable); named so the user sees it is row-level, not value, flow |
| **Structure** | `SCHEMA, ALIAS, SUBSET` | one uniform gray (`#7F8C8D`); no arrow; never highlighted |

`TABLE_FLOW` ("table feeds output") is a **value-flow** edge — not a structure edge.
`graph_service.CATEGORY_MAP` maps `TABLE_FLOW` to `"flow"` (J12-23/R30), so it renders
with the value-flow treatment, not the structure gray.

### Mid-point arrow

Each value-flow edge renders its direction arrow at the **midpoint** of the line
(native `mid-target-arrow-shape`), oriented along `source → target` — the direction
value flows. The arrow is placed mid-line so it is never covered by the node label
that sits at the line end.

### Click-edge flow cone

Clicking a value-flow edge `u → v` highlights its flow cone in two colors, anchored
to the edge's own `source → target` direction (independent of the query's
upstream/downstream switch):

- **Before** (green `#2ECC71`) = the value-flow edges **upstream** of `u` — the flow
  that enters the clicked edge ("where the data came from").
- **After** (blue `#2196F3`) = the value-flow edges **downstream** of `v` — the flow
  the clicked edge feeds ("where the data goes").
- The clicked edge itself is the **pivot** (red `#FF3B30`, class `flow-cone-pivot`).
- Non-cone edges are dimmed (focus mode).

The cone is **value-flow only** — structure edges are never part of it. The
"before/after" split is relative to the clicked edge, so it composes with the query
direction switch without conflict: the switch decides which closure the whole view
shows (upstream/writing vs downstream/reading of the seed); the click decides which
local sub-flow to highlight.

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

When a user queries a specific field (`table=T, field=Y`), the L1 and L2 graphs show the **data flow of field Y** — the fields writing Y (upstream) and the fields using Y (downstream — the effect scope, see below). Both levels share the same field-level semantic (the strict table.field flow walker); they differ only in scale:

- **L1** — cross-script projection: scripts + the tables between them that carry the flow. No fields, no intra-script structure.
- **L2** — per-script zoom-in: tables + fields + edges inside the clicked script.

**Flow direction (requirement change 2026-08-12, R29):** the direction is a **query setting in the query panel**, not an L1 panel control. **Both directions are transitive chains (user ruling 2026-08-12):** upstream back to the START, downstream down to the END:

- **Upstream (writing data flow, default)** — the fields that WRITE the queried field Y: the **transitive writing chain** (user ruling 2026-08-12) — the fields writing Y, the fields writing *those fields*, back to the START ("where does Y come from"). The chain terminates at source tables not written in the workspace, or at literals. Walked backward from Y.
- **Downstream (reading data flow)** — the fields that USE Y (user ruling 2026-08-12: the downstream flow is the **transitive effect scope** of Y): reads, WHERE clauses, filters, any usage — "where does Y's usage reach". A statement that uses Y carries the flow into everything it writes, even when the written column value is a literal (the usage selects the rows); the chain continues while a later statement uses a field written in the effect, and terminates at write targets nothing further uses — down to the END. Walked forward from Y.

L1 renders the flow in the query direction; L2 follows automatically (zoom-in). Tables that only read or write the queried TABLE — without carrying any field of Y's directional flow — are excluded from L1 (no table-level inclusion).

**Source/target anchoring in the L2 flow reason (user ruling 2026-08-12, R29):** the direction fixes which end of the flow the queried field Y anchors:

- **Downstream (reading)** — Y is the flow **SOURCE**: the flow starts at Y (the R19.1 framing, unchanged).
- **Upstream (writing)** — Y is the flow **TARGET**: the flow converges on Y; the sources are the fields writing it.

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

Additionally, after filtering by R: **table nodes with zero remaining field children are removed from the graph**, with one exception: the **immediate downstream table** (direct output of a script that has ≥1 lineage field) is kept as a **termination marker**. This table appears empty (no field children) to visually indicate: "the field's value reaches this script but does not propagate into this table's columns." The edge from the producing script to this terminal table is also kept.

**Scripts connected to the terminal marker are kept** — even though their output tables are removed. The edges from the terminal marker to these scripts are preserved. This allows users to open each connected script's L2 view and manually verify that the queried field is not used in data-producing operations (e.g., used only in JOIN, not INSERT). The terminal marker shows where automatic lineage tracing stops; the connected scripts enable manual confirmation.

All further downstream tables (outputs of terminal-connected scripts) are removed.

### Name ≠ Lineage

Fields with the **same name** as the queried field are not automatically in the lineage. Edge-type-specific BFS rules determine membership in R. Example: querying `stg_customers.customer_id` — `raw_orders.customer_id` has the same name but is produced independently in a different branch (step1 → stg_orders → JOIN). It is NOT in `stg_customers.customer_id`'s lineage because the JOIN edge is conditional (both ends must be in R via production). Name matching is never a substitute for lineage computation.

This enforces the principle that lineage follows the data flow of the field's **value**: if the queried field Y does not reach a table's columns (e.g., used only in a JOIN condition but not INSERTed), that table is structurally downstream but not in Y's lineage. The termination marker is the sole exception — it provides visual confirmation of where the flow ends.

### Table Identity ≠ Field Flow (J12-21, 2026-08-13)

**Sharing the same physical table is not lineage.** A node enters R only if it is on the queried field Y's **flow path** — it produces, consumes, or carries Y (or a field derived from Y). Referencing the same physical table as Y is **necessary but not sufficient**.

A bare table instance `T@L` inside an unrelated CTE/subquery is admitted only when its scope is on Y's flow path (an ancestor-or-equal scope of a visited field var carrying Y). If `T@L` reads `T.other_col` while Y is `T.target_col` referenced only elsewhere, `T@L` is **out** — even though it is the same physical table T.

Example: querying `ODS_CUPD_CLD_ACCTMASTER_NEW.BNQXYE` (referenced once, in the main statement) while the script also holds a CTE `temp_kmbh_gl` whose inner subquery reads `FROM ODS_CUPD_CLD_ACCTMASTER_NEW p1` (producing `acnw`/`MXKMBH`, never `BNQXYE`). The CTE branch (`p1@65`, `⟐ t@62`, `temp_kmbh_gl@58`) must **not** enter R. Only the main-statement path (`p1@487 → … → ⟐ output@99`), which actually carries `BNQXYE`, is in R.

Display note: the physical table merges to one node (R22), but per-context aliases/CTEs/subqueries do **not** merge — those are the nodes an unscoped table-identity admission would leak in. This is the field-level analogue of the L1 "no table-level expansion" rule.

### Writer's Own Leg (standard downstream case, 2026-08-13)

**A field that is written but never read still has a downstream projection** — "no readers" is not "empty". Downstream = all FIELD_LIKE occurrences of Y, and the write site itself is a FIELD_LIKE occurrence of Y, so it is always in the downstream flow.

In this case the downstream projection is the **writer's own leg** — the writing statement's own 3-node chain, produced by no reader:

```
write column Y ──(SCHEMA)──▶ statement output ──(TABLE_FLOW)──▶ DML target table
```

The writing statement's FROM inputs stay out (different field instance). Upstream in the same case terminates at the literal (no producing field to back-trace).

This is a **standard case, not an edge case** — it arises for every written-only sink/log/audit table. Canonical example: `rrcdm_job_log_exec_par.data_dt` (written from a literal `'$(load_date)'` by all three scripts, read by none); its L2 downstream is the writer's own leg, non-empty.

### Edge-Type Rules

Each of the 17 edge types has a specific rule. Direction: **↑** = upstream (backward from Y — "where does Y come from?"), **↓** = downstream (forward from Y — "where does Y go?").

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
| ROW_FLOW | rowset ← consumer | rowset → consumer | Yes — row-selection only |

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
│ field_flow(Y, graph, direction)                           │
│   → strict field-level walker (compute_field_flow class) │
│   → direction: upstream (fields WRITING Y) /             │
│                downstream (fields READING Y)             │
│   → returns the directional flow F (fields + tables)     │
│                                                           │
│ L1: project F to scripts + tables (R29, 2026-08-12)      │
│ L2: keep nodes ∈ F, drop rest                            │
│   → post-cleanup: remove table nodes with 0 flow fields  │
│   → L1 scale = scripts + tables; L2 scale = fields       │
└──────────────────────────────────────────────────────────┘
```

### Cross-Script Projection (L1, requirement change 2026-08-12, R29)

L1 spans multiple scripts. Each script runs the **same strict field-flow walker as L2** (per-instance table.field identity, restricted to the query direction — upstream/writing or downstream/reading), yielding the directional flow Fᵢ inside that script. L1 is the **projection** of the per-script flows onto script+table level:

- A script node appears iff its script contains ≥1 field in its directional flow Fᵢ.
- A table node appears iff it carries ≥1 field in Fᵢ — a table read/written by a script for OTHER fields is not enough; only the queried field's flow counts.
- **No table-level expansion**: a script that merely reads or writes the queried TABLE without carrying the queried field's flow is excluded.

This supersedes the earlier constrained-union formulation and the table-level production BFS (which admitted table-neighborhood scripts — e.g. a script reading `bdm_acc_loan_info` appeared for a `ODS_CUPD_CLD_ACCTMASTER_NEW.BNQXYE` search although it touches neither BNQXYE nor any BNQXYE-derived field).

### Termination (L1, requirement change 2026-08-12, R29)

The directional flow terminates at the **last table that carries a flow field** — the END of the transitive chain (user ruling 2026-08-12): the chain continues while a later statement uses a field written in the effect, and stops at write targets nothing further uses. Tables beyond that point — including tables that only read or write the queried TABLE — are **not** included: no table-level inclusion, no terminal-marker table. This supersedes the earlier terminal-marker rules (R18.1) for L1:

- Tables with ≥1 flow field → **kept**
- Tables with 0 flow fields → **removed** (no exception — the old "first downstream table that lacks the field" marker is exactly a table outside the queried field's flow)
- Scripts with no remaining table connection (no carried flow field) → **removed** from L1

Manual verification of absent fields is served by L2's not-in-flow response (R22.3): opening the script shows the banner "not in the data flow of T.F" plus the full graph — no marker table needed in L1.

### Single Lineage Engine

Both L1 and L2 must use the **same strict field-flow walker** (`compute_field_flow` — the field-level, per-instance table.field walker; the legacy table-level `compute_field_lineage` covers only the no-field-query path). Name matching is never a substitute for lineage computation. L1's flow is the direction-aware projection of the per-script walker results (R29, 2026-08-12) — not an independent table-level filtering algorithm.

### Backward Compatibility

When no specific field is queried (table-only search), or when `lineage_mode` is off, the full table-level graph is shown — behavior unchanged from the current definition. The upstream/downstream query direction applies only to field queries (R29, 2026-08-12).

## Multi-User & Workspace Model (2026-08-19; IMPLEMENTED v3.3.164, 2026-08-24)

Full decision log: `wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md`. This section formally defines the
multi-user collaboration entities and their invariants (R31.1–R31.29, shipped v3.3.164).

**Login gate:** the login middleware guards every `/api/*` path not in `PUBLIC_API_PREFIXES`
(`/api/health`, `/api/auth/login`, `/api/analyze`, `/api/analyze_multi`, `/api/scripts` — the last
three keep **SQL Analysis** usable logged-out, #293). The Data Flow Debugger requires a session; the
login form is embedded in the debugger's left panel (#293), not a separate page.

### User Account
A durable local identity.
- `username`: string, MUST match the locked format **`*@hsbc.com`** (`user_name@hsbc.com`) — an
  **identifier only**; no mail is ever sent. The charset is enforced by
  `^[A-Za-z0-9._%+-]+@hsbc\.com$` (`auth_service.py`, `_USERNAME_RE`). Accounts are
  **pre-provisioned from CONFIG** (`PROVISIONED_USERS`, #269) — an unknown username is rejected at
  login; there is no self-registration.
- `password_hash`, `salt`: PBKDF2-HMAC; minimum password length **6**.
- `created_at`, `last_login_ip`.
- `workspaces`: index entries `{ws_id, role ∈ {creator, participant}, first_opened, last_opened}`.
- Invariant: `|workspaces| ≤ MAX_WORKSPACES_PER_USER` (default **10**). At the cap, adding a
  workspace (create or id-open not already indexed) is rejected (HTTP 409).
- Recovery: accounts are **config-provisioned only** — there is no re-register endpoint (#269). A
  forgotten password is **admin-mediated** (A-H1): contact the administrator for a reset. Workspaces
  are unaffected by account recovery.

### Session
`token → {username, ip, last_active}`; identity carried by an `HttpOnly` cookie.
- Invariant: sessions are **ZERO-expiry (#279)** — no idle timeout; a session lives until logout or
  server restart (browser drops the cookie on close).
- Every authenticated API call extends `last_active`; a completed long-running search also extends it.
- Store is in-memory; lost on container restart (**accepted**).

### Open Visit
`(username, ws_id) → {opened_at, last_active}`. A user may hold several visits at once (multiple
tabs). A visit ends on the first of:
1. explicit **Close workspace**,
2. **logout**,
3. **session idle expiry**.

### Workspace (collaboration view)
`ws_id` → `WORKSPACE_ROOT/{ws_id}/` holds the scripts plus two state files with a **state split**:
- **`meta.json`** — the lightweight state **registry**:
  - `creator_username` — fixed at creation (immutable).
  - `created_at`.
  - `state_version` — **monotonic**, bumped on every state write.
  - the last-search **reference** (exactly **one L1**, the last search) + the **opened-L2 registry** —
    each opened L2 view with its persisted `{node_id: [x, y]}` positions (the current L1's positions
    too).
  - Node x/y are autosaved **at most once per second** while dragging, with a **final write on
    workspace close**; positions are **current-state only** (replaced on each save, never appended —
    the file never grows). On resume, saved positions are re-applied; ids that no longer exist are
    skipped, not errors. Zoom/pan is intentionally not saved.
- **`cache/views.json`** — the search/filter result **payloads** (search views), unchanged. Payloads
  stay here; `meta.json` holds only the registry above.

Shared, current-state-only; **last-writer-wins**; resume-by-id shows the current state, never a
personal history.

### Activity Event
`{username, ip, ts, action, detail}`, appended to `activity.json` (append-only). Actions include:
visit start, search performed, L2 opened, layout saved, visit end, workspace deleted. This is the
IP-audited "who modified this" record, readable by any opener.

### Notification
`{id, kind ∈ {memo, alert}, title, body, read, created_at}`, in
`notifications/{username}.json` (one file per user). Title = 
`[SQL Data Flow Visualizer] Workspace {ws_id} · {YYYY-MM-DD HH:MM}`. Records are **kept forever**.
Pull model: seen on next login (unread badge + inbox).

### Access & Deletion Rules
- **Open-by-id**: any logged-in user with a valid `ws_id` may open and edit; the creator is alerted
  in-app afterwards.
- **Remove-from-own-history** (any user): removes the entry from *that user's index only* — never
  the server copy, never another user's index.
- **Physical delete** (creator only): removes `WORKSPACE_ROOT/{ws_id}` (scripts, `meta.json`,
  `activity.json`, `views.json`) and the entry from **every** user's index. Non-creators have no
  physical-delete path.

### Heavy-Operation Gate
One **global** gate over the debugger **search** and `/analyze` + `/analyze_multi`. At most one
CPU-heavy operation runs at a time; a new one while one is running is refused with HTTP 409
"system busy — please wait" (no parallel heavy CPU load).

### Invariants
- `creator_username` is immutable after creation.
- `state_version` strictly increases on every state write.
- Layout files hold **current positions only** (never history); the activity log holds history only.
- All file writes are atomic (write-temp + rename); a concurrent same-file race may drop the losing
  update (**accepted**, low concurrency) but can never corrupt a file.
- Username uniqueness is per `users.json`; **no mail is ever sent**.
