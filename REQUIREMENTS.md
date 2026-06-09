# Requirements Implemented

> Chronological log of all features, fixes, and improvements built during development.

---

## R1 — Core Variable Extraction & Classification

**Goal:** Extract every variable from SQL scripts and classify by type.

**Implementation:**
- `variable_extractor_v2.py` — role-based Identifier walking (classify by parent AST node: Column/Table/TableAlias/Alias)
- 14 variable types: `database_table`, `table_column`, `cte_table`, `cte_column`, `intermediate`, `window_result`, `aggregate`, `case_result`, `function_result`, `literal`, `merge_target`, `union_branch`, `subquery_result`, `virtual_table`
- SQL dialect: MySQL (via sqlglot)
- Supported constructs: SELECT, INSERT, UPDATE, DELETE, MERGE, CTE (WITH), UNION/UNION ALL, INTERSECT, EXCEPT, CROSS JOIN LATERAL, subqueries, EXISTS, window functions, GROUP BY, ORDER BY, CUBE, ROLLUP, GROUPING SETS, named WINDOW, FILTER clause

---

## R2 — Dependency Graph Construction

**Goal:** Build directed edges between variables based on data flow.

**Implementation:**
- 11-phase edge creation in `dependency_graph.py`
- 10 edge types: `BELONGS_TO`, `ALIAS_OF`, `FEEDS_INTO`, `DIRECT_REFERENCE`, `AGGREGATION`, `TRANSFORMATION`, `WINDOW`, `COMPUTED_FROM`, `REFERENCES`, `OPERATES_ON`, `COMPONENT_LINK`
- Deduplication: no duplicate nodes, no duplicate edges, no isolated nodes
- Each edge colored by type for visual distinction

---

## R3 — Interactive Graph Visualization (Frontend)

**Goal:** Render the dependency graph in a browser with click-to-inspect.

**Implementation:**
- React + Vite + Cytoscape.js
- Node shapes/colors by variable type (14 distinct visual styles)
- Edge colors by relationship type (10 distinct colors)
- Hover: highlight neighborhood, dim everything else
- Click node → side panel with variable metadata, SQL expression, source tables, related edges
- Click edge → side panel with source/target SQL expressions, relationship, connecting SQL lines
- Search: dim non-matching nodes
- Node type filter dropdown
- Edge type filter dropdown
- Progress bar during upload and analysis
- Full SQL source viewer (toggleable bottom panel)

---

## R4 — File Upload & Auto-Visualization

**Goal:** Upload SQL file → automatic extraction → graph display with progress.

**Implementation:**
- File picker for `.sql` and `.txt` files
- Paste SQL text fallback
- 3-stage progress: Analyzing → Building graph → Done
- Auto-selects uploaded script in sidebar
- Graph renders automatically after analysis completes

---

## R5 — Natural Language Explanation (Claude API)

**Goal:** AI-powered explanations of variables and data flow.

**Implementation:**
- `claude_service.py` — Anthropic SDK with streaming SSE
- System prompt: GPS financial SQL analyst
- 5-part explanation: Business Meaning, Computation, Data Lineage, Dependencies, Business Significance
- Streaming token-by-token to frontend via SSE
- **Status: Disabled** (simplifies debugging; ready to re-enable)

---

## R6 — Offline Deployment Bundle

**Goal:** Deploy without internet access.

**Implementation:**
- Python dependencies pre-downloaded to `vendor/` (31 wheels)
- Frontend pre-built into `backend/app/static/`
- Single `uvicorn` command serves both API and frontend
- `pip install --no-index --find-links=vendor/` for offline install
- Docker support with `start.py` (programmatic uvicorn.Server for clean shutdown)

---

## R7 — Test-Driven Development

**Goal:** 193 tests verifying correctness after every change.

**Implementation:**
- 6 test files covering 22 SQL sample files
- `test_variable_extractor.py` (17) — type classification
- `test_dependency_graph.py` (6) — edge creation
- `test_complex_samples.py` (23) — GPS financial queries
- `test_github_inspired_samples.py` (17) — real-world patterns
- `test_analytical_samples.py` (20) — cohort/RFM/waterfall
- `test_graph_integrity.py` (110) — 5 topological checks × 22 files

---

## R8 — Topological Integrity Checks

**Goal:** Automatic verification that every graph is well-formed.

**Implementation:**
1. **No duplicate nodes** — every `(name, type)` unique
2. **No duplicate edges** — every `(source, target, relationship)` unique
3. **No duplicate table names** — no CTE_TABLE + DATABASE_TABLE overlap
4. **No isolated nodes** — every node has ≥1 edge
5. **Single connected component** — graph is one piece

---

## R9 — ALIAS_OF Edges

**Goal:** Explicit alias → original table name edges.

**Implementation:**
- `FROM users u` → edge `u → users` with type `ALIAS_OF`
- BELONGS_TO only from aliases (not original names), avoiding redundant edges
- FEEDS_INTO only from aliases, same principle

---

## R10 — VIRTUAL_TABLE & FEEDS_INTO

**Goal:** Every SELECT creates a virtual output table connecting all input tables.

**Implementation:**
- `virtual_table` node type (green rounded rectangle)
- Created for every SELECT (including CTE inner SELECTs and subqueries)
- Input tables → VIRTUAL_TABLE via `FEEDS_INTO` edges
- VIRTUAL_TABLE → output columns via `BELONGS_TO` edges
- Nested VIRTUAL_TABLEs connected into a tree
- Eliminates the need for COMPONENT_LINK in most same-scope cases

---

## R11 — CTE_TABLE Merging

**Goal:** CTE tables referenced in FROM clauses should not appear as separate DATABASE_TABLE entries.

**Implementation:**
- When adding a DATABASE_TABLE, check if a CTE_TABLE with same name exists → skip
- Eliminated 54 duplicate table nodes across all test cases

---

## R12 — Subquery & EXISTS Table Registration

**Goal:** Tables inside subqueries and EXISTS should be registered with their aliases.

**Implementation:**
- Walk INTO subquery nodes to register FROM/JOIN table aliases
- Handle `EXISTS(SELECT ...)` — Exists wraps Select directly (not Subquery)
- Enables BELONGS_TO edges for subquery-scoped columns

---

## R13 — CASE & Subquery Source Column Extraction

**Goal:** CASE expressions and scalar subqueries should have source_columns populated.

**Implementation:**
- Removed `exp.Case` from prune list in `_extract_source_columns()`
- Removed `exp.Subquery` from prune list in `_extract_source_columns()`
- CASE results now show edges from WHEN/THEN/ELSE columns
- Scalar subqueries now show edges from inner query columns

---

## R14 — COMPUTED_FROM Rename

**Goal:** `CASE_BRANCH` → `COMPUTED_FROM` — clearer meaning.

**Implementation:**
- Renamed in `dependency_graph.py`, `graph_service.py`, `App.jsx`, `graphStyles.js`
- "Computed From" better expresses that the result is derived from input columns

---

## R15 — DML Target Edges (OPERATES_ON)

**Goal:** INSERT/UPDATE/DELETE/MERGE target tables should have edges.

**Implementation:**
- `OPERATES_ON` edge type (red)
- Connects source columns → DML target tables
- Covers INSERT INTO, UPDATE, DELETE FROM, MERGE INTO targets

---

## R16 — Bare Column REFERENCES

**Goal:** Bare column names in HAVING/ORDER BY should reference their SELECT definitions.

**Implementation:**
- `REFERENCES` edge type (steel blue)
- Matches bare column names to defined aggregates/windows/functions with the same name
- Example: `total_orders` in `HAVING total_orders >= 3` → edge from SELECT aggregate `total_orders`

---

## R17 — COMPONENT_LINK Safety Net

**Goal:** Ensure every graph is a single connected component.

**Implementation:**
- Phase 11: Union-Find across all edges
- If multiple components exist, bridge them from the largest component
- `COMPONENT_LINK` edge type (dark orange) — visually distinct from semantic edges
- Only triggers for genuinely separate scopes (different statements, correlated subqueries)

---

## R18 — Global Node Deduplication

**Goal:** Same column = one node, regardless of how many places it's referenced.

**Implementation:**
- Changed dedup key from `(name, type, context)` → `(name, type)`
- Eliminated 157 duplicate nodes across all test cases

---

## R19 — Performance: Large Graph Optimization

**Goal:** Smooth pan/zoom even with thousands of nodes.

**Implementation:**
- **Compound nodes**: Columns assigned as children of parent tables. Collapse/expand.
- **3 view modes**: Full | Compact | Tables (dropdown selector)
- **Compact mode**: Only table nodes visible (~60-80% fewer elements)
- **Tables mode**: Only table/CTE/VT nodes (~90% fewer elements)
- **Render optimizations**: `pixelRatio: 1`, `textureOnViewport: true`, `hideLabelsOnViewport: true`, `hideEdgesOnViewport: true`

---

## R20 — Input-Output Graph (Post-Processing)

**Goal:** Show only the data flow from input columns to user-defined output columns.

**Implementation:**
- CSV upload (4 columns: table_name, data_type, column_name, explanation)
- `POST /api/scripts/{id}/io_graph` endpoint
- BFS path finding from input columns to output columns
- Simplified graph: only nodes on paths
- Path details: ordered node list with table names in parentheses
- "IO Graph" / "Full Graph" toggle buttons

---

## R21 — Pipeline Logging

**Goal:** Docker-compatible pipeline logging for debugging.

**Implementation:**
- `logger.py` — 5 checkpoints to stderr
- `PIPELINE START` → `extract` → `deps` → `graph` → `PIPELINE DONE`
- Variable/edge counts per stage
- API request logging
- Balanced detail: enough to debug, not overwhelming

---

## R22 — SQL Source Viewer

**Goal:** Show the original SQL script alongside the graph for manual verification.

**Implementation:**
- Toggleable bottom panel ("Show SQL" / "Hide SQL")
- Scrollable pre-formatted monospace text
- Max 40% viewport height, scrolls independently
- Useful for comparing graph to source

---

## R23 — SQL Sample Library

**Goal:** 22 diverse SQL test cases covering real-world patterns.

**Basic (6):**
- `query1_select_where.sql` — simple SELECT with WHERE
- `query2_joins_complex.sql` — JOINs, aggregation, HAVING, ORDER BY
- `query3_subqueries_case.sql` — subqueries, CASE, EXISTS
- `query4_update_delete.sql` — UPDATE, DELETE with subqueries
- `query5_nested.sql` — INSERT INTO SELECT, nested subqueries
- `tables.sql` — DDL for 5 sample tables

**Financial GPS (16):**
- `tables_financial.sql` — 8 GPS tables (transactions, accounts, etc.)
- `tables_financial_v2.sql` — Enhanced schema with double-entry, DECIMAL precision
- `fin_query1` — Settlement batch reconciliation (CTE + window)
- `fin_query2` — Multi-currency fee calculation
- `fin_query3` — Account balance snapshot (LAG/LEAD)
- `fin_query4` — MERGE/UPSERT
- `fin_query5` — UNION ALL risk report
- `fin_query6` — Chargeback analysis (scalar subqueries)
- `fin_query7` — Interchange fee optimization (window frames)
- `fin_query8` — Multi-party settlement (5-table JOINs)
- `fin_query9` — Double-entry transfer (balance snapshots)
- `fin_query10` — Fraud detection (PERCENTILE_CONT, LEAD gaps)
- `fin_query11` — Merchant cohort retention
- `fin_query12` — Revenue waterfall / MRR analysis
- `fin_query13` — RFM segmentation (NTILE, CONCAT)
- `fin_query14` — Recursive account hierarchy (WITH RECURSIVE)
- `fin_query15` — Multi-dimensional CUBE/ROLLUP
- `fin_query16` — LATERAL + INTERSECT/EXCEPT

**Real-world sources:** pg-ledger, Borghi97/fraud-detection-sql, iPay, TheLook Ecommerce, SaaS MRR Retention, RFM Analysis

---

## Summary

| # | Requirement | Status |
|---|---|---|
| R1 | Core variable extraction & classification | ✅ |
| R2 | Dependency graph (10 edge types) | ✅ |
| R3 | Interactive frontend (React + Cytoscape) | ✅ |
| R4 | File upload & auto-visualization | ✅ |
| R5 | Claude NL explanation | Disabled |
| R6 | Offline deployment bundle | ✅ |
| R7 | Test suite (193 tests) | ✅ |
| R8 | Topological integrity (5 checks) | ✅ |
| R9 | ALIAS_OF edges | ✅ |
| R10 | VIRTUAL_TABLE + FEEDS_INTO | ✅ |
| R11 | CTE_TABLE merging | ✅ |
| R12 | Subquery & EXISTS table registration | ✅ |
| R13 | CASE & Subquery source columns | ✅ |
| R14 | COMPUTED_FROM rename | ✅ |
| R15 | OPERATES_ON (DML targets) | ✅ |
| R16 | REFERENCES (bare column refs) | ✅ |
| R17 | COMPONENT_LINK safety net | ✅ |
| R18 | Global node deduplication | ✅ |
| R19 | Large graph performance (3 view modes) | ✅ |
| R20 | Input-Output graph (BFS paths) | ✅ |
| R21 | Pipeline logging | ✅ |
| R22 | SQL source viewer | ✅ |
| R23 | SQL sample library (22 files) | ✅ |
