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

---

## SELECT-Side Schema Enrichment — extending S4 to SELECT-side orphans (2026-08-06)

> Status: Design confirmed, pending implementation. Appended per the 2026-08-06
> residual-orphan review (types 1a/1b: bare columns in multi-table scopes with
> no unique schema owner — the ~350 remaining unresolved columns, i.e. the
> unq_multi class, 57.5% of the 659 classified).

### Goal

Resolve class 1a/1b — bare columns in scopes with ≥2 visible physical tables —
using schema evidence, while preserving the never-guess principle (R4, R6).
Today's S4 (index time only, `folder_index_service.py` "S4: schema-based
resolution") has three structural gaps verified in code:

1. **Alias-keyed schema map** — qualified evidence attaches to alias names
   (`ss.s_store_sk` → key `ss`), never to canonical tables (`store_sales`).
   `dependency_graph.py` Pass 4a skips original (unaliased) tables; Pass 6 of
   `infer_table_schemas` copies original→alias, never alias→original. The S4
   loop can therefore attribute to alias keys (`tbl in table_index` matches
   alias table vars).
2. **Scope-blind attribution** — the unique-owner test runs against the whole
   workspace (`candidates = [tbl for tbl, fields in schema_map.items() ...]`),
   not the statement's visible tables. A field known only in table T is
   attributed to T even in statements that never reference T — a guess.
3. **Missing authoritative evidence** — DML target column lists
   (`INSERT INTO t (a,b)`) are deliberately not registered as variables (1c′
   note) and CREATE TABLE column definitions are not parsed (`_walk_create`),
   so neither contributes schema evidence.

This design enriches the schema map with SELECT-side evidence and makes the
unique-owner test scope-aware. It also fixes latent mis-attribution (gaps 1–2)
under the same never-guess principle.

### Schema sources (where the map comes from)

The S4 schema map M: **canonical table name → set of column names**. Sources,
in decreasing authority:

| # | Source | Authority | Today | Enrichment |
|---|--------|-----------|-------|------------|
| 1 | Qualified column refs in the same script (`web_returns.wr_web_page_sk`, `ss.s_store_sk`, `db.t.col`) | Observed usage (medium) | Only alias-qualified refs reach SCHEMA edges; original tables and alias→canonical mapping are lost (gap 1) | Build the per-script map directly from column variables: prefix → canonical via the script alias map (`_table_aliases`), unaliased qualified refs included, db qualifier dropped (table part only) |
| 2 | DML target column lists — `INSERT INTO t (a,b)`, `UPDATE t SET a=…`, `MERGE … SET a=…` | Authoritative (target defines its own columns) | Not extracted at all | Collect list/SET columns per target canonical name during the walk — **evidence only, NOT column variables** (`total_columns` unchanged) |
| 3 | `CREATE TABLE t (a INT, b VARCHAR)` / CTAS column lists | Authoritative (DDL) | `_walk_create` registers the table name only | Parse the Schema node's `expressions` → evidence for t; CTAS without a list → SELECT output aliases (positional, same semantics as the Bug 41 DML mapping) |
| 4 | Cross-script propagation (L1 lineage): per-script maps aggregated at index time | Aggregate of 1–3 | Partially (the scope-blind loop) | Scope-aware re-test (S4b) of S4a-remaining candidates against the workspace map |
| 5 | Existing `infer_table_schemas` | — | S4 input | Unchanged for `lineage.py`/L2; no longer the S4 attribution input (replaced by the canonical per-script map) |

**Why cross-script is load-bearing (verified):** the 101-file `samples/tpcds`
corpus contains no qualified refs, no DML, and no DDL — TPC-DS evidence exists
only in a sibling corpus (`tpcds_qualified`, e.g. `ss.s_store_sk AS id`) or
user DDL (`samples/financial/tables_financial.sql`). A per-script-only pass
would leave TPC-DS essentially unresolved; the workspace-level aggregation is
what makes source 1 effective across scripts.

Excluded from M (script-scoped, never S4 candidates): `⟐`-prefixed containers
(`⟐ output`, `⟐ subq…`), CTE names, and derived-table aliases (their columns
are S2 / Fix C territory).

### Resolution rule

**Inputs** — for each unresolved bare column var v (no prefix, no
`source_tables`, survived S1/S2/S3/S5/S6, `_in_scope_owner` passed) whose
nearest scope has **≥2 distinct physical tables** (S3's ≥2 branch):

- `visible(v)` = distinct canonical table names of physical tables in the
  nearest `_SelectScope` (already deduped by `_distinct_scope_tables`;
  self-joins count once; CTE refs excluded)
- schema map M (canonical keys)

**Rule (applied identically in S4a and S4b):**

```
1. if lower(v.name) in {lower(t) for t in visible(v)}:     # R6 guard
       count r6_collision; leave unresolved; NEVER attribute
2. owners = {t in visible(v) : v.name ∈ M[t]}
       # whole-name equality (case-insensitive) = the R4 word-boundary
       # invariant — "id" never matches "customer_id"
3. if len(owners) == 1:
       v.source_tables = [the one owner]      # canonical name, same shape as S3
       resolved_by["schema"] += 1
4. else:  # 0 owners (evidence absent / table not in M) or ≥2 (ambiguous)
       leave unresolved — stays in the ORPHAN RESOLUTION REPORT
       # never fabricate, never fall back to workspace-global uniqueness
```

**Outputs:** `source_tables` = the table's **canonical** name (graph consumers,
indexer and `build_resolution_stats` read it as today); stats bucket
`resolved_by["schema"]`; unresolved list semantics unchanged.

### Pipeline integration

**Two-tier split (decision):** the schema pass runs in BOTH places, with one
rule:

- **S4a — inside the extractor** (`extract_variables_from_sql`): a post-pass
  after the full statement walk (evidence may come from any statement,
  including later ones). Build M_script from sources 1–3; for each candidate
  stashed during the walk (the S3 "≥2 tables" branch now records
  `(var, visible, context)` instead of just leaving the var), apply the rule.
  Honors R20 ("all orphan resolution happens in the extraction phase") for
  everything the script can prove itself: the per-script analysis cache is
  self-contained and Level-1 reportable (`schema` bucket > 0 at extractor
  time for self-evident scripts).
- **S4b — index time, cross-script:** after all scripts are parsed and M_ws
  is aggregated (source 4), re-apply the rule to the still-unresolved
  candidates recorded in `resolution_stats["schema_candidates"]`
  (`{field, visible_tables, line}` — emitted by S4a, so S4b needs no re-parse
  and keeps the scope). Updates the analysis cache's var, `field_index`,
  `table_index`, and `by_strategy["schema"]` as today.
- **The existing scope-blind index loop is REPLACED by S4b.** It is strictly
  safer: it can never attribute to a table the statement doesn't reference,
  and never to alias keys. Consequence (expected): a small set of
  previously-attributed-but-wrong entries un-resolve — a correctness win, not
  a regression.

**Ordering (unchanged precedence):** S5/S6 sentinels (`⟐system`/`⟐pseudo`) are
set and returned first; then S2 (CTE output columns), then S3 (single-table
scope), then S4a (≥2-table scopes); S4b at index time only re-tests S4a
residuals. Fixes A/B/C feed S1/S2 before S4 runs, so two-hop chains landing
in multi-table scopes now complete via S4.

### Edge cases

| Case | Handling |
|------|----------|
| Self-join (`FROM orders o1 JOIN orders o2`) | Distinct-physical dedup → 1 table → S3 path; S4 never fires (existing `test_s3_scope_aliases_count_once` guards) |
| Alias vs canonical | Candidates and M keys are canonical (alias resolved via the script alias map); `ss.s_store_sk` evidence lands on `store_sales` |
| Derived tables in scope | Not physical → never S4 candidates; their output columns resolve via S2 / Fix C |
| CTEs in scope | Not physical → never S4 candidates; S2 covers CTE columns |
| DML targets | Target is NOT a visible FROM table for SELECT-side columns; its column lists feed M (source 2). `UPDATE t SET col` — `col` has scope {t} → S3; the SET list is still evidence for t in other scripts |
| Case sensitivity (R4) | Whole-name equality, both sides folded to lowercase (SQL identifiers are case-insensitive in MySQL/Hive/Postgres-unquoted); original case preserved in stored names. Clarifies R4 (word-boundary), does not weaken it |
| R6 field==table collision | `lower(field) ∈ lower(visible)` → counted in `r6_collision`, never attributed, still reported (e.g. `Call_Center` vs `call_center`) |
| Schema-absent table (1a) | Field in no visible table's M → 0 owners → unresolved. Cross-script re-test (S4b) covers evidence living in other scripts |
| Field known but not visible here | 0 owners → unresolved — never a workspace-global fallback (replaces today's scope-blind behavior) |
| Genuinely ambiguous (1b) | Field in ≥2 visible tables' M → unresolved by design (e.g. `SELECT id FROM a JOIN b ON a.id=b.id` — both `a` and `b` own `id`; existing `test_s3_multi_table_scope_left_unresolved` still passes) |
| db-qualified refs (`db.t.col`) | M keyed by bare table name (db dropped) — matches table_index/graph conventions; multi-db same-name risk documented in Open Questions |
| Subquery-copy artifacts | Only `_in_scope_owner`-authentic vars are candidates (the S3 guard already handles this) |
| Word-boundary | Whole-name set membership — `id` never matches `customer_id`; no prefix/fuzzy matching anywhere |
| Empty scope (no FROM) | `visible(v)` empty → 0 owners → unresolved (S6 covers known pseudocolumns first) |
| Old caches without `schema_candidates` | Indexer reads defensively (same pattern as the existing `stats_seen` gate) — S4b skips scripts lacking candidates |

### Stats & reporting

- **Per-script (`resolution_stats`, analysis cache):** `resolved_by["schema"]`
  now nonzero (S4a); new `schema_candidates` list `[{field, visible_tables,
  line}]` (S4b input, persisted); new `r6_collision` counter. `unresolved`
  semantics unchanged (excludes S5/S6, now also excludes S4a-resolved).
- **Index-time aggregation:** unchanged shapes — `by_strategy` sums S4a+S4b
  into `schema`; `orphan_fields.json` = post-S4 residual; coverage % formula
  unchanged.
- **ORPHAN RESOLUTION REPORT additions:** `schema candidates: N (unique
  visible owner found: M) | r6 collision: K`, and in Phase 1 the per-orphan
  candidate line (`field: x → web_sales (evidence: q14.sql L23)`) for human
  audit. R20 feedback loop unchanged: coverage drop after any change is a
  regression signal.

### Test strategy

**Unit (extend `test_orphan_resolution_extractor.py` + `test_orphan_resolution_index.py`):**
- TPC-DS join predicate, both sides bare, each unique in M → both resolve
  (`ws_sold_date_sk`→web_sales, `d_date_sk`→date_dim, `d_date`→date_dim,
  `ws_web_page_sk`→web_sales, `wp_web_page_sk`→web_page — q77 `ws`/`wr` CTE
  shape).
- Ambiguous → unresolved: existing fixture `test_s3_multi_table_scope_left_unresolved`
  (`id` in both `a` and `b`) must keep passing (this is the 1b invariant test).
- Never-guess scope-blind regression: field known only in table T that is NOT
  in the scope → unresolved (today's loop would wrongly attribute).
- Evidence sources: `INSERT INTO t (a,b) SELECT …` + bare `a` later in a
  2-table scope with t visible → resolved; INSERT list creates **no** column
  vars (`total_columns` unchanged); `CREATE TABLE t (a INT)` evidence;
  UPDATE SET list evidence.
- Canonicalization: evidence via `ss.s_store_sk` → bare `s_store_sk` in
  `{store_sales, …}` resolves (fails against today's alias-keyed map).
- R6: bare column named like a visible table → `r6_collision`, unresolved.
- Case-insensitive: DDL `Id INT` + bare `id` → resolves; `id` vs `customer_id`
  never cross-match.
- Self-join → S3 (not S4). Stats shapes: `schema > 0` extractor-side;
  `schema_candidates`; old-cache fallback.
- **Expectation-review item:** scan existing fixtures where only one side of a
  join carries schema evidence — S4a may resolve what tests assert unresolved;
  update assertions deliberately (this is the point of the fix).

**Sample-based:** q77 (ws/wr CTEs above), q14/q90/q93 (multi-join + two-hop),
spider 052/053, financial fin_query4/fin_query8 (MERGE + INSERT lists).
Re-run the consolidated classification sweep (659-columns methodology) —
expect unq_multi 57.5% → ≤15% on evidenced workspaces, and rising coverage %
in the report.

### Phased rollout

- **Phase 0 — instrumentation (no behavior change):** extractor emits
  `schema_candidates` + canonical `script_schemas`; report unchanged. Verify
  shapes and index perf on the 101-file tpcds corpus. ✅ **Done (v3.3.132)** —
  shapes verified behavior-neutral (sweep reproduced 96.60% / 291 orphans
  exactly); tpcds indexes in 0.79s.
- **Phase 1 — report-only:** ORPHAN RESOLUTION REPORT shows, per unresolved
  orphan, the unique visible owner when found (`field → table (evidence:
  script Ln)`); `r6_collision` bucket visible. Human-audit ~50 orphans across
  tpcds + financial; **this phase measures the real evidence coverage** and
  calibrates the estimate below. Zero risk. ✅ **Done (v3.3.132)** — 118
  unique-owner proposals on the combined corpus (80.3% of orphans), 52
  audited line-by-line → **100% correct**, 118/118 mechanically DDL-verified;
  reality: resolvable 76.6% (est. 55–65%), genuinely ambiguous 0% (est.
  17–27%, corpus-dependent — see 1b fixture recommendation).
- **Phase 2 — auto-resolution:** enable S4a; replace the scope-blind index
  loop with S4b. Gate on Phase-1 audit results; watch coverage drop and
  report spikes. **Gate: PASS (2026-08-06 audit) — pending user go.** Before
  enabling: (1) fix the `loc` first-occurrence caveat (q76 string-literal
  case, 2/118); (2) report the schema-evidence line (DDL/qualified ref) not
  the bare-use line; (3) add a 1b fixture corpus (shared column names) for
  sample-level never-guess validation; (4) remaining 1a classes
  (derived-table output chains q71, financial CTE-chain aliases) are S2
  extensions, not S4.
- **Phase 3 — hardening (optional):** surface DDL/DML-list evidence into
  `table_index` fields (autocomplete) and `pair_index` seeds, consistent with
  P1/P4. Note: DDL evidence proved dominant (118/118 owners confirmed by the
  DDL; bare tpcds → 0 owners) — an explicit "import schema from DDL file"
  workflow (open question 6) is the highest-value Phase-3 item.

### Open questions

1. Two-tier split (S4a extractor + S4b index) — accept as the resolution to
   the R20-vs-cross-script tension? Default: yes. ✅ **Validated by Phase-1
   audit** — extractor-level M_a = 8 vs index-level M_idx = 118: cross-script
   S4b is load-bearing (bare tpcds → 0 owners).
2. Case-insensitive matching changes today's exact (case-sensitive) S4 set
   membership — confirm this is the intended reading of R4. ✅ **Confirmed by
   real-world matches** — spider `IsOfficial`→bare `isofficial`,
   DDL `sr_return_amt_inc_tax`→`SR_RETURN_AMT_INC_TAX` (q1).
3. db-qualified refs keyed by bare table name; multi-db same-name tables →
   conservative ambiguity. Accept, or key M by (db, table)? — ✅ **Closed
   (2026-08-06): bare-table keying retained.** No multi-db sample exercises
   it; conservative ambiguity (conflicting evidence → unresolved, never
   cross-attribute) is the correct never-guess default. Revisit only if a
   multi-db same-name fixture demonstrates false positives.
4. Should DML/DDL evidence surface in `table_index` fields (autocomplete) in
   Phase 3, or remain schema-map-only? — ✅ **Closed (2026-08-06, v3.3.134):
   remain schema-map-only.** Phase 3 shipped as A1 (file_class classification,
   report-only): classify DDL files at zip
   time so they contribute evidence without pipeline pollution; report
   schema-evidence presence factually (`schema_evidence` in the index
   response). No autocomplete seeding, no
   annotation, no upload endpoint.
5. The R6 guard is scoped to S4 here; S3 (single-table scope) has the same
   theoretical collision (`SELECT call_center FROM call_center`) — extend the
   guard to S3 as a follow-up? — ✅ **Closed (2026-08-06): YES — guard
   implemented in the extractor (S3 attribution), r6_collision incremented,
   left unresolved.** (v3.3.134)
6. Workspaces with no evidence at all (bare tpcds corpus alone): S4 gains
   ~nothing until a qualified/DDL twin is indexed. Add an explicit
   "import schema from DDL file" workflow, or rely on users indexing DDL? —
   ✅ **Closed (2026-08-06): report-only.** Per user decision: all files are
   uploaded in the initial phase; no additional files exist. DDL already
   inside the zip is classified at index time (schema file class, no
   pipeline pollution, evidence merged into M_ws); a workspace with no
   schema evidence anywhere is reported factually in the diagnostics.
   Never fix, never annotate — report only. (v3.3.134)

---

# v3.3.140 — Strict table.field Data Flow (L2)

> **Date:** 2026-08-07 | **Version:** 3.3.140-dev | **Status:** Implementation (teams)

## 1. Requirement change (user-confirmed 2026-08-07)

The requirement is now **exact data flow of `table.field`** (per-instance identity),
not table-level flow around the field:

- **OLD (v3.3.139 and before):** seed by the searched field, expand by TABLE-level
  flow — TABLE_FLOW/ALIAS/SCHEMA/JOIN walk *through tables* around the field.
  Symptom: `bdm_evt_loan_trans`, `bdm_gdc_label_fin`, `bdm_sys_acc_loan_info`,
  `ods_*` etc. appear in L2 for a `bdm_acc_loan_info.data_dt` search even though
  those tables never carry the searched field (33 nodes on the sample).
- **NEW:** seed by `table.field` identity (per-instance var), expand only where the
  field itself participates (flow *of* the field). Result: ~8 nodes on the sample,
  every survivor field-adjacent.

**The old solution is kept for future use** — see §3 (architecture).

## 2. Ground truth (samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql)

Searched: `bdm_acc_loan_info.data_dt`. The field's real flow:

| Line | SQL | Role |
|------|-----|------|
| 18 | `WHERE data_dt = '$(load_date)'` (CTE{rollover_loan_info}) | read seed (owner bdm_acc_loan_info) |
| 43 | `SUBSTR(p1.data_dt,1,7) = ...` (same CTE, alias p1) | read seed via qualifier p1 |
| 84/158 | `bdm_acc_loan_info p1` (CTE{loan_final}) / `p1.data_dt = '$(load_date)'` | read seed (p1 aliases bdm_acc_loan_info, NOT loan_final) |
| 160 | `INSERT OVERWRITE TABLE bdm_acc_loan_info_sup PARTITION(data_dt=..., CHARGE_DEPARTMENT)` | write-side seed (PARTITION var) |
| 202 | `p2.data_dt = DATEADD(...)` (read on the output table at TOP0) | NOT in flow (read-side on the output, not the searched table) |
| 55/93 | `a.data_dt` / `t.data_dt` (other tables) | NOT in flow (owner ≠ searched table) |

Expected L2: ~8 compound nodes (searched physical table, p1@29, p1@84, the two CTE
containers, the L43 subquery output, the write target). Highlights byte-exact:
`[[18,18],[43,43],[158,158],[160,160]]` — single line numbers, no columns.

## 3. Architecture — old solution preserved

`backend/app/extractor/lineage.py` gains a clearly-marked second mode; the legacy
path is **byte-identical**:

```
LEGACY (v3.3.139 and before)          STRICT (v3.3.140, L2 only)
──────────────────────────────        ──────────────────────────────
compute_field_lineage()               compute_field_flow()
filter_graph_by_lineage()             filter_by_field_flow()
filter_relevant()                     (convenience wrapper)
```
- Old call sites keep calling `filter_relevant`/`filter_graph_by_lineage`
  **unchanged**: L1 (`l1_builder.py` ×2), Bug-27 pairs (`dataflow_service.py:208`),
  legacy consumers (`sql_highlight_service.py`, `dataflow_extractor.py`).
- Only the two L2 call sites switch: `l2_builder._apply_relevance_filter` and
  `dataflow_service.py:367`.
- `EDGE_SEMANTICS`/`PRODUCTION_EDGES`/`ALWAYS_BIDIR_EDGES`/`_BIDIR` untouched.
- Module section headers + docstring distinguish the two modes.

## 4. Strict walker rules (compute_field_flow)

- **Node map / adjacency** from graph_data (edge type = `edge_type` or `relationship`).
- **Field-like vars** (FIELD_LIKE): variable_type ∈ {column, cte_column, literal,
  aggregate, expression, computed, window, variable}; field part = last dotted
  label segment == target_field.
- **Seeds** = field-like vars with `_field_part == target_field` AND
  (`defined_in == "PARTITION"` OR owner == target_table).
  Owner resolution (identity-based — never walks SCHEMA edges, whose targets are
  label-keyed last-writer-wins and topologically broken):
  1. `source_tables[0]` if present;
  2. else qualifier (label/sql_expression `X.y` → `X`) → table-like var labeled `X`
     in the same context, else nearest ancestor context;
  3. else unqualified → exactly-one same-context table-like var (labels starting
     `⟐` excluded) — ambiguous → not a seed.
- **seed_zone(nid)**: BFS from the seeds over FIELD_LAND edges = {REF, TRANSFORM,
  AGGREGATE, WINDOW, COMPUTED} (both directions, memoized). Field identity flows
  through these.
- **Expansion** (visited set keyed by node ID):
  - FIELD_LAND → admit neighbor (both directions).
  - ALIAS → admit neighbor iff `neighbor.source_tables[0] == target_table`
    (excludes p1@TOP0 whose source is loan_final).
  - FILTER/JOIN → admit neighbor iff seed_zone(current) OR seed_zone(neighbor)
    (admits the L43 SUBSTR chain's output; excludes the L93/L202/L225 conditions).
  - DML → forward only (source→target).
  - **Never walked:** TABLE_FLOW, SUBQUERY, SET_OP, CORRELATED, INDIRECT, SUBSET,
    SCHEMA (SCHEMA replaced by identity resolution above).
- **Owner-holder admission** (not an edge): for every admitted field-like var,
  admit the table-like var it resolves to (per the 3-step rule above) — this puts
  p1@29, p1@84, the physical bdm_acc_loan_info, and the INSERT target into the
  closure.
- **Container (scope-companion) rule:** for every admitted var whose context
  contains `CTE{X}`, admit the CTE var labeled X (keeps rollover_loan_info and
  loan_final visible as the scopes that contain the reads).

## 5. Flaw-reduction pass (deltas vs. the earlier draft)

1. **Highlights collapse into the filter** — one rule instead of a duplicated
   criterion at response assembly: highlights = `[line_start, line_start]` of the
   closure's field-like vars (node-carried lines, computed by the extractor's
   comment-skipping line mapper). 202/16/52/118/151/204 are excluded *by
   construction*; `not_in_flow` → empty highlights.
2. **Extractor change dropped:** qualified columns no longer need
   `source_tables` — the walker resolves owners via per-instance alias vars
   (their `source_tables` are already reliable). Smaller diff, less risk.
3. **Filter rule strengthened:** "seed-class endpoint" → **seed-zone** — admits
   the SUBSTR chain output but still excludes every foreign-table condition.
4. **Phantom fix verified** against sqlglot 30.12.0: `walk()` yields a node
   before evaluating prune, so recording `id(node.this)` at the Subquery/Exists
   wrapper prunes the Select subtree before any column registers.
5. **Cache invalidation:** `EXTRACTOR_VERSION` stamped in `run_full_analysis`;
   graph caches carry `format_version 4` (node data has line_start/line_end);
   `GRAPH_CACHE_PREFIX → graph_3_2_18`.

## 6. Change list (parallel teams, disjoint files)

| Team | Files | Changes |
|------|-------|---------|
| A (foundation) | variable_extractor_v2.py, adapter.py, graph_service.py, cache_keys.py | phantom dedup prune (`Select` id set), PARTITION walk, EXTRACTOR_VERSION + stamp, node line_start/line_end, prefix bump |
| B (walker) | lineage.py | compute_field_flow + filter_by_field_flow (rules §4), legacy byte-identical, section headers |
| C (builder) | l2_builder.py, dataflow_service.py | switch to filter_by_field_flow, node-line highlights, P1 MOVE→COPY, alias identity (label, line_start) + "label@line" labels, ctx-aware parent refinement, _survive_join_edges gate, Sync 1/2 stmt_idx-aware, _resolve_scope_parent virtual_table, format_version 4 + extractor_version checks, not_in_flow → empty highlights |
| D (verification) | tests/, VERSION, CLAUDE.md, BUG_ANALYSIS.md, this wiki | byte-exact assertions, pinned-count updates, docs, version bump — after integration |

## 7. Verification targets

- pytest suite in container (`docker exec gps-sql-backend python3 -m pytest tests/ -v`).
- Sample probe: closure labels ≈ {data_dt×4 seeds, p1@29, p1@84, bdm_acc_loan_info,
  bdm_acc_loan_info_sup, rollover_loan_info, loan_final, ⟐subq} (~10 raw → ~8 L2 nodes).
- Highlights byte-exact `[[18,18],[43,43],[158,158],[160,160]]`.
