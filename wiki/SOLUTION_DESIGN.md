# Graph Construction Algorithms — Complete Overview

> **Date:** 2026-07-31 | **Version:** 3.3.115-dev | **Status:** Confirmed, pending implementation

## Core Principle

**All name resolution happens once, in the extractor.** Alias→canonical, table fields from SCHEMA edges, output table fields, `input_tables`/`output_tables` with canonical names — all resolved at graph-build time (`build_graph_data`). L1 and L2 read pre-resolved data. No downstream name parsing, no alias resolution, no field propagation.

---

## Prerequisites (must be done first)

| # | Prerequisite | Where |
|---|-------------|-------|
| P1 | Build `pair_index[(table,field)] → {scripts}` during workspace indexing | Indexer |
| P2 | `build_graph_data` resolves alias→canonical via `source_tables` | `graph_service.py` |
| P3 | `_classify_tables` uses canonical names; sets `⟐ result` for SELECT-only scripts | Extractor output |
| P4 | Record fields per table: SCHEMA edges for originals/virtuals, DML sources for targets | `graph_service.py` |
| P5 | Sync alias↔canonical fields both ways; pre-build `alias_map` in analysis output | `graph_service.py` |
| P6 | Delete fallback label matching in `compute_field_lineage` | `lineage.py` |

---

## Algorithm 1 — Per-Script Graph (Extractor)

Runs once per SQL file. Cached to disk as `analysis_{hash}.json` and `graph_3_2_15_{hash}.json`.

```
Input:  SQL text, script_name
Output: graph {nodes, edges, input_tables, output_tables}

1a. Template replacement
    "{dialect}" → "mysql"

1b. Parse SQL via sqlglot → AST

1c. Walk AST, classify each identifier by parent node role
    For each table reference:
      name, variable_type (table/view/cte/virtual_table/...),
      defined_in (FROM/JOIN/INSERT/WHERE/...),
      source_tables (empty for originals, ["crm_customers"] for alias "c")

    For each column reference:
      name ("c.customer_id"), variable_type (column/aggregate/window/...),
      defined_in (TOP/WHERE/...)

    → VariableDefinition[] (15 types)

1c′. Resolve unqualified column references (Bug 53) — SUPERSEDED
    Decision 2026-08-04: NO auto-resolution is implemented. The
    extractor stays as-is; orphan fields are REPORTED (see
    "Validation — Orphan Field Check") for human review instead of
    being fixed automatically. The analysis below is kept for
    reference.

    Problem: "SELECT customer_id FROM crm_customers" records the column
    with NO table — every consumer derives the table from the name
    prefix, so the table ends up with 0 fields despite real columns in
    the SQL. Verified: unqualified columns occur in ALL common SQL
    patterns (single-table SELECT, INSERT...SELECT, UPDATE SET,
    DELETE WHERE, aggregates, CASE, subqueries, CTE bodies).

    Mechanism — per-statement visible-table scope (threaded, not a
    global stack):
      - _walk_select computes its FROM/JOIN visible tables
        (canonical name + alias, e.g. {"crm_customers", "c"}) and
        passes them down to column registration
      - nested subqueries / CTE bodies call _walk_select recursively
        with their OWN scope (inner FROM wins — no outer leakage)
      - UPDATE/DELETE/MERGE: the target table is the scope for
        SET/WHERE columns
      - unqualified column (col.table == ""):
          exactly 1 visible table → source_tables = [canonical_name]
          ≥2 visible tables      → unattributed (ambiguous without
                                   schema — safe, no over-attribution)

    Verified scope coverage (extractor tests):
      - INSERT...SELECT / CREATE...AS SELECT columns resolve to the
        SELECT's FROM table; the Bug 41 DML cross-reference then maps
        them to the INSERT/CTAS target (targets get fields via DML)
      - INSERT column lists (INSERT INTO t (a,b)) are NOT registered
        as variables — nothing to fix there
      - subquery inner + CTE body columns resolve to their inner FROM

    Evaluated alternative — sqlglot qualify (review suggestion, verified):
      - sqlglot.optimizer.scope.columns does NOT resolve unqualified
        columns to base tables (table stays '') — wrong API for this
      - sqlglot.optimizer.qualify.qualify(stmt, schema=None,
        validate_qualify_columns=False) resolves single-source SELECT
        contexts (SELECT/INSERT...SELECT/CTE body) — battle-tested
      - BUT it does NOT resolve UPDATE/DELETE SET/WHERE columns and
        multi-table joins (stays '?'), and raises OptimizeError unless
        validate_qualify_columns=False
      - Verdict: per-statement visible-table scope (above) covers a
        superset (SELECT contexts + UPDATE/DELETE targets) with no
        sqlglot-version dependence — chosen over qualify.

    → columns like customer_id now carry source_tables=["crm_customers"]

1c″. Consumer cascade — fall back to source_tables when prefix is empty — SUPERSEDED
    (2026-08-04 decision: no fallback/patch — report-only. See the
    Orphan Field Check section.)

    The extractor fix only helps if consumers USE source_tables.
    All three currently derive the table from the name prefix only:

      | Consumer | Change |
      |----------|--------|
      | folder_index_service.py (indexer) | unqualified column → table = source_tables[0] instead of skip (Bug 49 alias resolution stays for qualified) |
      | graph_service.py build_graph_data | unqualified column → table_name = source_tables[0] (fixes L1/L2 node attachment too) |
      | lineage.py | no change needed — reads table_name/field_name from graph nodes, benefits automatically |

    DML targets (INSERT/UPDATE/CTAS) need no change: their fields come
    from the Bug 41 DML cross-reference, which reads the SELECT side.

    Future work (documented limitation): multi-table statements with
    unambiguous unqualified columns (JOIN where the column exists in
    exactly one table) remain unattributed. A post-index second pass
    using infer_table_schemas could resolve them — out of scope here.

1d. Classify input/output tables per script (canonical names only)
    For each table variable:
      resolve alias→canonical via source_tables
      "FROM"/"JOIN" in defined_in  → input_tables.add(canonical_name)
      "INSERT"/"UPDATE"/"MERGE" in defined_in → output_tables.add(canonical_name)
      "CREATE"/"SELECT INTO" → output_tables.add(canonical_name)
    SELECT-only (no DML output): output_tables.add("⟐ result")

    → input_tables:  {"crm_customers"}
    → output_tables: {"stg_customers"}

1e. Build dependency edges
    12-phase ordered construction:
      TABLE_FLOW → ALIAS → REF → AGGREGATE → TRANSFORM → WINDOW
      → COMPUTED → SCHEMA → INDIRECT → FILTER → JOIN → DML

    → VariableDependency[] (16 edge types)

1f. Build graph nodes — ALL name resolution here
    For each column variable ("c.customer_id"):
      split by "." → prefix="c", field_name="customer_id"
      resolve prefix via source_tables: "c" → "crm_customers"
      → node.table_name = "crm_customers"
      → node.field_name = "customer_id"

    For each table variable:
      record fields from outgoing SCHEMA edges:
        → crm_customers.fields = {customer_id, full_name, segment, region, is_active}
        → ⟐ output.fields = {customer_id, full_name, segment, region}
      For DML targets (stg_customers), record fields from DML sources:
        → stg_customers.fields = {customer_id, full_name, segment, region}

    For each alias (source_tables non-empty):
      sync fields both ways via ALIAS edge:
        → crm_customers.fields = c.fields
      pre-build alias_map: {"c": "crm_customers"}

    → nodes[] — with table_name, field_name, table_fields, alias_map pre-populated

1g. Cache to disk
    analysis_{hash}.json       — variables + dependencies + input_tables + output_tables + alias_map
    graph_3_2_15_{hash}.json   — Cytoscape JSON with resolved names + table_fields
```

---

## Algorithm 2 — L1 Graph (Cross-Script Pipeline)

Runs on every search. Shows the cross-script data flow pipeline.

```
Input:  workspace_id, target_table, target_field
Output: L1 graph {nodes, edges}

2a. Find seed scripts from pair index
    pair_index[("stg_customers","customer_id")] → {step2, step3}

2b. BFS expansion through shared tables
    Seed scripts → tables they touch → other scripts touching those tables → repeat
    visited_scripts = all scripts in the connected component

2c. Load per-script analysis (cached from step 1g)
    For each script in visited_scripts:
      → {input_tables, output_tables, graph, alias_map}
    Names already canonical. No aliases in input/output sets.

2d. Classify tables by role (cross-script rollup)
    all_inputs  = union of every script's input_tables
    all_outputs = union of every script's output_tables

    source_tables       = all_inputs - all_outputs
    intermediate_tables = all_inputs ∩ all_outputs
    output_tables       = all_outputs - all_inputs

2e. Create table + script nodes + edges
    table nodes:  {id, label, type, table_name}
    script nodes: {id, label, type, script_name}
    edges: table → script (reads_from), script → table (writes_to)

2f. Production BFS per script → lineage_field_pairs
    For each script:
      if target_table not in this script → skip
      BFS from target_table through production edges only:
        PRODUCTION = {REF, TRANSFORM, AGGREGATE, WINDOW, COMPUTED, DML, ALIAS}
        + SCHEMA↑ (column → table)
      → collect (table_name, field_name) of all reached columns

    Union across scripts + add target:
    → lineage_field_pairs = set of (table_name, field_name) in lineage

2g. Create field nodes (only for pairs in lineage_field_pairs)
    For each column in each script's graph:
      if (table_name, field_name) ∈ lineage_field_pairs:
        create field node with parent = table_node_id

2h. R18.1 Empty table cleanup
    Tables with ≥1 field → keep
    Tables with 0 fields:
      if written by a field-connected script → terminal marker → keep
      else → remove
    Outgoing edges from terminal marker → keep (manual L2 verification)
    Remove disconnected scripts

2i. Layout + return
    Topological sort → layer assignment → snake-wrap positioning
```

---

## Algorithm 3 — L2 Graph (Per-Script Detail)

Runs when user double-clicks a script node in L1.

```
Input:  workspace_id, script_name, target_table, target_field
Output: L2 graph {nodes, edges}

3a. Load full graph (cached from step 1g)
    graph_3_2_15_{hash}.json → full_graph
    Names resolved. alias_map + table_fields pre-built.

3b. Filter by lineage
    lineage = compute_field_lineage(full_graph, table, field, table_schemas)
    (SCHEMA validation works — names resolved, no fallback needed)
    → keep only nodes/edges in lineage set → graph_data

3c. Compound node construction
    table-like nodes → compound parents
      aliases shown as alias_table (visible, fields pre-synced from step 1f)
    column-like nodes → field children
      (table_name/field_name already resolved — no label parsing)
    Output table fields: already populated from step 1f (SCHEMA edges)
    DML phantom fields: copy source table fields to DML target tables

3d. Target identification
    Match nodes → target_node_ids
    BFS upstream+downstream → direct_ids (for field_group: direct/indirect)

3e. Edge handling
    Field promotion: field-level → table-level edges (SCHEMA removed)
    DML simplification: DML → TABLE_FLOW chain through ⟐ output
    sql_range: attach SQL line/column numbers to each edge
    Dedup + partition: resolve overlapping edge ranges

3f. Assemble + return
    nodes = table_nodes + field_nodes
    edges = partitioned edge list
    → {nodes, edges, total_nodes, filtered_nodes, target}
```

---

## Validation — Orphan Field Check (fields without any table)

Companion to Bug 53: a field with no table attribution cannot be found
via table→field autocomplete, cannot attach in L1/L2, and silently
vanishes from filter results. The check surfaces these so extraction
gaps are visible instead of silent.

**Signal (verified):** `field_index[field]["tables"] == []` ⇔ orphan
field. The indexer always registers fields in field_index (only the
TABLE association is gated by the name prefix), so the orphan set is
exact — confirmed on a Bug-53-style script (unqualified columns →
`customer_id`/`full_name` orphaned, both tables show `fields: []`).

**Three levels:**

| Level | Where | What it reports |
|-------|-------|-----------------|
| 1. Extraction (per script) | R15 profile "Vars:" line | `orphan=N` — column variables with no prefix AND no `source_tables`; instant per-script visibility at analysis time |
| 2. Index (per workspace) | `index_scripts()` | compute orphans → persist `cache/orphan_fields.json` `{field: [scripts]}`; return `orphan_field_count` + samples in the index response; push an R16-style diagnostic block ("⚠ N fields have no table attribution — check scripts […]") |
| 3. Filter (R19 diagnostic) | `upload_filter_config` | one line: fields in the filtered field_index that carry no tables (survived via scripts only) + samples |

**Use:** pairs with the existing "tables without fields" per-table
diagnostics — the two sets pinpoint the exact extractor divergence
(Bug 53 exposure). An orphan spike after any extractor change is a
regression signal. Levels 1+2 are the primary check; level 3 covers
the filter path.

**Action on detection — SUPERSEDED (2026-08-04, revised):** the
report-only stance was replaced by the automatic resolution design
below ("Orphan Resolution — Understand Any SQL"). The report remains
as the RESIDUAL layer: only orphans the code genuinely cannot resolve
are listed, with their script segments, for human review. The report
MUST include, per orphan field, the corresponding script segment (the
SQL lines where the field appears).

Report format (R16-style block, pushed after extraction):
```
┌─ ORPHAN FIELD REPORT ────────────────────────────────────────────┐
│ 3 fields have no table attribution (check SQL, then re-index)     │
│ ───────────────────────────────────────────────────────────────── │
│ field: customer_id    script: load_customers.sql                  │
│    L2: INSERT INTO stg_customers (customer_id, full_name)         │
│    L3: SELECT customer_id, full_name FROM crm_customers;          │
│ field: full_name      script: load_customers.sql                  │
│    L2: INSERT INTO stg_customers (customer_id, full_name)         │
│    L3: SELECT customer_id, full_name FROM crm_customers;          │
└───────────────────────────────────────────────────────────────────┘
```
Implementation: for each orphan field, its scripts come from
`field_index[field]["scripts"]`; the SQL lines come from a
case-insensitive line search of the field name in the script file
(same mechanism as the filter's SQL-evidence diagnostic).

---

## Orphan Resolution — "Understand Any SQL" (2026-08-04, official design)

**Goal:** the extractor attributes EVERY column to its table — the
solution must understand any SQL, not require the SQL to be mended.
Based on the consolidated classification of 659 orphans across all
samples (unq_multi 57.5%, expr_alias 22.3%, plain_alias 14.9%,
unq_single 4.7%, other 0.6%, sys_table 1.2%).

### Resolution pipeline — two phases, all inside extraction

All resolution happens in the extraction phase (per script + a
post-index pass); no SQL is mended. Phase 1 needs no schema; phase 2
uses the workspace schemas once all scripts are parsed.

**Phase 1 — per-script extraction (`variable_extractor_v2.py`):**

**S1 — plain_alias (14.9%): alias inherits the source column's table.**
`sb.total_amount AS batch_total` → `batch_total` gets `total_amount`'s
attribution. The extractor already stores `source_columns`/
`sql_expression` on alias vars — walk the source qualifier through the
Bug-49 alias map. CHEAP (mostly consuming existing fields).

**S2 — expr_alias (22.3%): attribute expression output to the
statement's output context.**
- CTE body → the CTE's output column set (so downstream unqualified
  refs to the CTE column resolve to the CTE)
- top-level SELECT → ⟐ output
- INSERT…SELECT → the INSERT target (Bug 41 DML mapping already works)

**S3 — unq_single (4.7%): bare column, exactly ONE physical table in
the NEAREST enclosing SELECT scope → scope resolution** (the old 1c′
with the D1 fix — count distinct PHYSICAL tables, not alias+canonical).
Verified: nearest-scope is the correct measure (statement-level
counting zeroes unq_single in TPC-DS — every statement nests subqueries).

**Phase 2 — post-index schema pass (index time, after all scripts
parsed + `infer_table_schemas`):**

**S4 — unq_multi (57.5%): bare column, ≥2 physical tables → schema-based
resolution.** exact/word-boundary name match (R4 invariant — `id` must
never match `customer_id`); unique owner → attribute; multiple/unknown
→ leave unattributed + report. The big lever for TPC-DS (join
predicates `wr_web_page_sk = wp_web_page_sk`, filters `d_year=1999`).

**Classification (both phases):**

**S5 — sys_table (1.2%): INFORMATION_SCHEMA & system tables — exclude/
mark as system, never a defect (excluded from the unresolved count).**

**S6 — other (0.6%): pseudocolumns (LEVEL), trigger vars (new/old) —
dialect exclusion lists; marked expected (excluded from the unresolved
count).**

**Two-hop aliases** (`(select d_year AS ss_sold_year)`, ~48/sample in
tpcds): chain S1 → S3/S4 (alias → source column → table).

### Coverage report (R20 — extraction feedback loop)

After all scripts are parsed (index time), the diagnostic reports the
resolution coverage so humans can confirm and discover bad cases:

```
┌─ ORPHAN RESOLUTION REPORT ────────────────────────────────────────┐
│ column vars: 320 | resolved: 313 (97.8%) | unresolved: 7           │
│   by strategy: plain_alias=98 expr_alias=147 scope=31 schema=37    │
│ ────────────────────────────────────────────────────────────────── │
│ UNRESOLVED orphans — possible bad cases, check SQL:                │
│ field: LEVEL   script: oracle_decode_nvl.sql                       │
│    L9: SELECT LEVEL AS org_level FROM dual CONNECT BY LEVEL <= 10  │
│ ... (up to 10 fields, then '... N more')                           │
└───────────────────────────────────────────────────────────────────┘
```

- **Coverage %** = resolved / total column variables (resolved counted
  per strategy via extractor counters S1–S4 aggregated at index time).
- **Unresolved** = fields still with `tables == []` after S1–S6,
  EXCLUDING S5/S6 marked-expected entries. Listed with their SQL
  segments (the existing ORPHAN FIELD REPORT mechanism).
- **Purpose**: a coverage drop after an extractor change = regression
  signal; real usage surfaces bad cases for the extraction to learn
  from (new SQL patterns → new strategies).

### Coverage (verified from the classification)

| Strategy | tpcds | financial group |
|----------|------:|----------------:|
| S1+S2 (alias attribution) | 31–35% | 68.5% |
| S4 (schema-based) | 59–64% | 24.7% |
| S3 (scope) | ~5% | 1.4% (~12% with nearest-scope) |
| **S1+S2+S3+S4 combined** | **~95%** | **~93%** |

### Invariants
- **R4**: every name match (schema, alias inheritance) is exact/
  word-boundary — `id` never matches `customer_id`.
- **R6**: field-name == table-name collisions are never auto-attributed.
- **Never guess**: unresolved orphans stay visible in the report.
- Consumers unchanged (indexer, graph_service read `source_tables`/
  prefix as today).

---

## What Gets Removed (After Prerequisites)

| Current code | Why removable |
|-------------|---------------|
| `l1_builder.py:278-282` alias filtering in L1 | P3: input/output sets use canonical names |
| `l1_builder.py:701-755` naive `compute_field_lineage` union | Production BFS alone is sufficient (step 2f) |
| `l1_builder.py:765-781` alias resolution via `global_alias_map` | P2: names resolved at source |
| `l1_builder.py:787-874` field propagation + constrained union | P4: fields pre-recorded per table |
| `l2_builder.py:185-210` alias detection scan | P5: alias_map pre-built |
| `lineage.py:121-137` fallback label matching | P2+P6: SCHEMA validation works with resolved names |
| `multi_script_service.py:71-72` `⟐ result` patch | P3: extractor sets it |
| `dataflow_service.py:163-177` `lineage_field_pairs` from graph dict | Simplified to production BFS output |

---

## Architecture

```
SQL Text
  │
  ├── variable_extractor_v2.py   → VariableDefinition[] (15 types)
  │     └── sqlglot parse → AST walk → classify each identifier
  │
  ├── dependency_graph.py        → VariableDependency[] (16 edge types)
  │     └── 12-phase ordered edge creation
  │
  └── graph_service.py           → Cytoscape JSON (nodes + edges)
        │
        │  build_graph_data():
        │    • splits "c.customer_id" → table_name + field_name
        │    • resolves alias→canonical via source_tables
        │    • records table fields from SCHEMA/DML edges
        │    • syncs alias↔canonical field sets
        │    • pre-builds alias_map
        │    • sets input_tables/output_tables with canonical names
        │
        ├── l1_builder.py             → Cross-script pipeline view
        │     └── production BFS → lineage_field_pairs → filter
        │
        └── l2_builder.py             → Per-script detail view
              └── filter_relevant → compound nodes → edge handling
```

## Table Type Invariants

- **Alias Field Synchronization**: When ALIAS edge exists, fields copied both ways. `crm_customers.fields = c.fields`.
- **Output Table — SCHEMA-Defined Fields**: An output table's fields = {columns with SCHEMA edge FROM that output table}.
- **DML Target Fields**: A DML target table's fields = {columns of DML source tables}. Recorded at extraction time (step 1f).
- **Column Resolution (Bug 53)**: Every column reference carries the table that owns it. Qualified columns resolve via the name prefix; unqualified columns resolve via the visible-table scope stack (step 1c′). A table shows 0 fields in the index only if (a) its columns are referenced ambiguously (≥2 visible tables — documented limitation, schema-based resolution is future work), (b) it is not used by any uploaded script, or (c) it appears only in comments.

---

## Residual-Orphan Fixes — Confirmed Cases (2026-08-06)

**Principle (reinforced):** uncertain cases (multi-table bare columns with no
unique schema owner — types 1a/1b) are NEVER guessed. They are reported in
the ORPHAN RESOLUTION REPORT for human review — a reported uncertainty is
better than a hidden error, and manual power improves accuracy over time.
Only CONFIRMED-resolution cases get automatic fixes:

### Fix A — 1c: S3 set-op scope edge (UNION/EXCEPT/INTERSECT in subqueries)

Verified: `SELECT DestAirport FROM Flights` inside `NOT IN (SELECT ... UNION
SELECT DestAirport ...)` — a SINGLE-table scope still fails to attribute.
Root cause to confirm during implementation: `_walk_setop` branch scopes
and/or the `_in_scope_owner` guard (branch Select vs Union owner).

Design: when walking a set-op (UNION/EXCEPT/INTERSECT), each branch SELECT
pushes its own `_SelectScope`; the owner guard must accept the branch Select
as owner. Fix `_walk_setop` + `_in_scope_owner`; test with the spider 052
fixture (DestAirport must attribute to Flights).

### Fix B — 2a: implicit aliases of qualified columns (S1 extension)

Verified: `cc_call_center_id Call_Center` (implicit alias, no AS) — the
alias var exists but the alias→source-column→table chain is not followed.

Design: extend S1 to implicit aliases (sqlglot represents them via
`alias_or_name` on the projection, no exp.Alias node). When an implicit alias
of a plain qualified column is found, attribute the alias var to the source
column's table (same as explicit S1). ~dozens of tpcds fields.

### Fix C — 2b: expression aliases referenced downstream (S2 extension, two-hop)

Verified: `... END act_sales` inside a derived subquery, then `sum(act_sales)`
in the outer query — the outer bare reference should chain to the subquery's
output column.

Design: extend S2's output-column mechanism (currently CTE-only,
`_cte_output_columns`) to DERIVED TABLES (aliased subqueries): record each
derived table's output column names (its projections' aliases); when a bare
column matches a visible derived table's output column, attribute to the
derived alias (same semantics as the CTE case). Then chain: if the output
column is itself an alias of a plain column (two-hop), follow S1 to the
source table.

### Expected impact

| Fix | Orphans addressed | Sample evidence |
|-----|-------------------|-----------------|
| A (set-op scope) | spider DestAirport + similar | 052/053, 057 |
| B (implicit alias) | Call_Center, Call_Center_Name, Manager + ~dozens | q91 |
| C (derived-table two-hop) | act_sales, amc, average_sales, agg1-7, bought_city + ~40 | q93, q14, q90, 18 |

After A+B+C, re-run the coverage sweep; the remaining residuals should be
1a/1b (schema-required — reported, never guessed), type 3 (pseudocolumn
aliases, genuinely unresolvable), and any NEW patterns the report surfaces
(the feedback loop).
