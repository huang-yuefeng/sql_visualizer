# Requirements Implemented

> Detailed log of all features, fixes, and improvements built during development.
> Each entry includes: function description, solution approach, files modified, test coverage.

---

## R1 — Core Variable Extraction & Classification

**Description:** Parse SQL scripts and extract every named variable (table names, column references, aliases, computed expressions). Classify each variable into one of 14 types.

**Solution:** Built `variable_extractor_v2.py` using a **role-based Identifier walking** approach. Instead of checking for every possible SQL syntax structure (the v1 approach), the extractor walks ALL `Identifier` AST nodes produced by sqlglot and classifies based on **parent node role**:

- `Identifier` inside `Column` → `table_column`
- `Identifier` inside `Table` → `database_table`
- `Identifier` inside `TableAlias` → alias (also `database_table`)
- `Identifier` inside `Alias` → check the aliased expression for detailed type

This approach automatically handles any new SQL construct that sqlglot can parse — no code changes needed.

**Files modified:**
- `backend/app/extractor/variable_extractor_v2.py` (611 lines) — core extractor
- `backend/app/extractor/variable_extractor.py` (769 lines) — v1 (kept for reference)
- `backend/app/models/variable.py` (50 lines) — VariableType enum, VariableDefinition model
- `backend/app/extractor/adapter.py` (97 lines) — pipeline orchestration

**Test coverage:** `test_variable_extractor.py` (17 tests) — validates all 14 types across basic SQL patterns

---

## R2 — Dependency Graph Construction

**Description:** Build directed edges between variables to represent data flow (table→column, column→aggregate, alias→original name).

**Solution:** 11-phase edge creation in `dependency_graph.py`. Each phase handles a specific relationship pattern:

| Phase | Edge Type | What it connects |
|---|---|---|
| 1 | AGGREGATION/WINDOW/TRANSFORMATION/COMPUTED_FROM/DIRECT_REFERENCE | source_columns → their consumers |
| 2 | ALIAS_OF | alias → original table name |
| 3 | FEEDS_INTO | table aliases → VIRTUAL_TABLE |
| 4 | BELONGS_TO | table/CTE/VT entries → columns |
| 5 | BELONGS_TO | CTE tables → inner variables |
| 6 | BELONGS_TO | VIRTUAL_TABLE → its output columns |
| 7 | REFERENCES | bare column name → defined variable |
| 8 | OPERATES_ON | column → DML target table |
| 9 | COMPONENT_LINK | cross-scope bridge (safety net) |

Phase 10 was merged into Phase 9. Phase 11 (Union-Find merge) consolidates all disconnected subgraphs.

**Files modified:**
- `backend/app/extractor/dependency_graph.py` (327 lines) — all edge creation logic
- `backend/app/services/graph_service.py` (127 lines) — Cytoscape JSON with edge colors
- `frontend/src/utils/graphStyles.js` (92 lines) — edge color/width/dash styles
- `frontend/src/App.jsx` (257 lines) — edge type filter dropdown + legend

**Test coverage:** `test_dependency_graph.py` (6 tests) — validates edge types, no self-loops, no dupes

---

## R3 — Interactive Graph Visualization (Frontend)

**Description:** Render the dependency graph in a browser as an interactive force-directed graph with click-to-inspect, search, and type filters.

**Solution:** React + Vite + Cytoscape.js single-page application. Three-panel layout:
- **Left sidebar:** Script list, node type filter, edge type filter, legend (14 node types + 9 edge types)
- **Center:** Cytoscape.js canvas with `cose` layout, hover highlighting, click handlers
- **Right:** Slide-out detail panel showing variable metadata, SQL expressions, source tables, dependency lists

Search dims non-matching nodes. Progress bar shows upload/analysis stages.

**Files modified:**
- `frontend/src/App.jsx` (257 lines) — main component
- `frontend/src/main.jsx` (10 lines) — entry point
- `frontend/src/api/client.js` (40 lines) — fetch wrapper
- `frontend/src/utils/graphStyles.js` (92 lines) — Cytoscape stylesheet
- `frontend/src/styles/app.css` (130 lines) — dark-theme UI
- `frontend/index.html` — shell
- `frontend/vite.config.js` (15 lines) — Vite + proxy config
- `frontend/package.json` — dependencies

**Test coverage:** Manual verification with all 22 SQL samples

---

## R4 — File Upload & Auto-Visualization

**Description:** User uploads a SQL file → system analyzes it → graph renders automatically, no manual steps.

**Solution:** File input with `.sql`/`.txt` accept filter. On change, reads file text client-side, POSTs to `/api/analyze`, refreshes script list, auto-selects the new script. The `useEffect` watching `selectedScript` triggers graph loading. Progress bar shows 3 stages: Analyzing SQL (30%) → Loading graph (10%) → Done.

Also supports "Paste SQL" via prompt for quick testing.

**Files modified:**
- `frontend/src/App.jsx` — `handleUpload` and `handlePaste` functions
- `frontend/src/styles/app.css` — progress bar styles

---

## R5 — Natural Language Explanation (Claude API)

**Description:** AI-powered explanations of variables and data flow using Claude Opus 4.8.

**Solution:** `claude_service.py` sends variable metadata to Claude API with a GPS financial domain system prompt. Claude returns structured JSON with: Business Meaning, Computation, Data Lineage, Dependencies, Business Significance. Response streamed token-by-token via SSE to frontend.

**Files modified:**
- `backend/app/services/claude_service.py` (117 lines) — API integration
- `backend/app/routers/variables.py` — `/explain` and `/explain_edge` endpoints

**Status:** **Temporarily disabled** — removed buttons from UI and endpoints to simplify debugging. Ready to re-enable by restoring the router endpoints and button components.

---

## R6 — Offline Deployment Bundle

**Description:** Deploy without internet access — no pip install or npm install at runtime.

**Solution:**
- Python dependencies pre-downloaded to `backend/vendor/` (31 wheels, 7.3 MB) for `pip install --no-index --find-links=vendor/`
- Frontend pre-built into `backend/app/static/` (served by FastAPI `StaticFiles`)
- Single `uvicorn` command serves API + frontend from one process
- `start.py` uses programmatic `uvicorn.Server` for clean Docker shutdown

**Files modified:**
- `backend/vendor/` — 31 pre-downloaded wheels
- `backend/app/static/` — pre-built frontend assets
- `backend/start.py` (31 lines) — production entry point
- `backend/app/main.py` (58 lines) — StaticFiles mount
- `Dockerfile` — container build
- `README.md` — offline install instructions

---

## R7 — Test Suite (193 Tests)

**Description:** Comprehensive automated testing to verify correctness after every change.

**Solution:** 6 test files covering 22 SQL sample files plus TPC-DS queries:

| File | Tests | Focus |
|---|---|---|
| `test_graph_integrity.py` | 110 | 5 topological checks × 22 files |
| `test_variable_extractor.py` | 17 | Variable type classification |
| `test_dependency_graph.py` | 6 | Edge creation + no self-loops |
| `test_complex_samples.py` | 23 | GPS financial queries (fin_query6-8) |
| `test_github_inspired_samples.py` | 17 | GitHub-sourced patterns (fin_query9-10) |
| `test_analytical_samples.py` | 20 | Cohort/RFM/waterfall (fin_query11-13) |

**Files modified:**
- `backend/tests/conftest.py` (65 lines) — shared fixtures
- `backend/tests/test_graph_integrity.py` (117 lines)
- `backend/tests/test_variable_extractor.py` (242 lines)
- `backend/tests/test_dependency_graph.py` (95 lines)
- `backend/tests/test_complex_samples.py` (285 lines)
- `backend/tests/test_github_inspired_samples.py` (192 lines)
- `backend/tests/test_analytical_samples.py` (187 lines)
- `backend/tests/test_data/` — 6 SQL test fixtures

**Run:** `python -m pytest tests/ -q` → 193 passed

---

## R8 — Topological Integrity Checks

**Description:** Automatic verification that every generated graph is well-formed — no structural defects.

**Solution:** 5 parameterized tests run against all 22 SQL files:

1. **No duplicate nodes** — every `(name, variable_type)` pair is unique
2. **No duplicate edges** — every `(source_id, target_id, relationship)` triple is unique
3. **No duplicate table names** — no CTE_TABLE also appearing as DATABASE_TABLE
4. **No isolated nodes** — every node has ≥1 edge (source or target of at least one dependency)
5. **Single connected component** — the entire graph is one piece (no subgraphs)

Each test uses Union-Find for component detection and reports specific offending nodes.

**Files modified:**
- `backend/tests/test_graph_integrity.py` (117 lines)

---

## R9 — ALIAS_OF Edges

**Description:** Explicit edges from table alias to original table name. `FROM users u` → edge `u → users`.

**Solution:** Phase 2 in `dependency_graph.py` iterates all `database_table` variables. Those with `source_tables` populated (aliases) get an ALIAS_OF edge to the original table entry with the matching name.

**Files modified:**
- `backend/app/extractor/dependency_graph.py` — Phase 2
- `backend/app/services/graph_service.py` — color `#1ABC9C`
- `frontend/src/App.jsx` — filter + legend entry

---

## R10 — VIRTUAL_TABLE & FEEDS_INTO

**Description:** Every SELECT creates a virtual output table. Input tables feed into it. Output columns belong to it.

**Solution:** 
- New variable type `VIRTUAL_TABLE` created in `_walk_select()` for every SELECT (including CTE inner SELECTs, subquery SELECTs, main SELECT)
- Phase 3 creates `FEEDS_INTO` edges from table aliases → VIRTUAL_TABLE (only aliases, not original names)
- Phase 6 creates `BELONGS_TO` edges from VIRTUAL_TABLE → its output columns
- Nested VIRTUAL_TABLEs (subqueries → parent) connected via same-context matching

**Files modified:**
- `backend/app/models/variable.py` — added `VIRTUAL_TABLE` type
- `backend/app/extractor/variable_extractor_v2.py` — `_walk_select()` creates VT
- `backend/app/extractor/dependency_graph.py` — Phase 3 + Phase 6
- `backend/app/services/graph_service.py` — color `#2ECC71`, node style
- `frontend/src/App.jsx` — filter + legend entry

---

## R11 — CTE_TABLE Merging

**Description:** CTE tables referenced in FROM clauses should not appear as separate DATABASE_TABLE entries alongside their CTE_TABLE definition.

**Solution:** In `_add()`, when adding a `DATABASE_TABLE`, check if a `CTE_TABLE` with the same name already exists. If so, return None (skip). This eliminated 54 duplicate table nodes.

**Files modified:**
- `backend/app/extractor/variable_extractor_v2.py` — `_add()` method, lines 249-254

---

## R12 — Subquery & EXISTS Table Registration

**Description:** Tables inside subqueries (`SELECT ... FROM payments p`) and EXISTS (`EXISTS(SELECT ... FROM audit_log at3)`) should be registered with their aliases.

**Solution:** 
- `_walk_columns_in_expr()` walks INTO Subquery nodes to extract FROM/JOIN table aliases
- Added `_walk_select_tables()` helper for both `exp.Subquery` and `exp.Exists`
- EXISTS wraps `Select` directly (not `Subquery`), so both node types need explicit handling

**Files modified:**
- `backend/app/extractor/variable_extractor_v2.py` — `_walk_columns_in_expr()`, `_walk_select_tables()`

---

## R13 — CASE & Subquery Source Column Extraction

**Description:** CASE expressions and scalar subqueries must have `source_columns` populated so edges can be created.

**Solution:** Removed `exp.Case` and `exp.Subquery` from the prune list in `_extract_source_columns()`. Previously these were pruned (their inner columns were invisible). Now the walker enters them and extracts all Column references.

**Files modified:**
- `backend/app/extractor/variable_extractor_v2.py` — `_extract_source_columns()`

---

## R14 — COMPUTED_FROM Rename

**Description:** Rename edge type `CASE_BRANCH` → `COMPUTED_FROM` — clearer semantics.

**Solution:** "Computed From" better expresses that the result is derived from input columns. "CASE Branch" was confusing and implied the edge represented a branch of a CASE rather than the derivation relationship.

**Files modified:**
- `backend/app/extractor/dependency_graph.py` — `_classify_relationship()`
- `backend/app/services/graph_service.py` — EDGE_COLORS
- `frontend/src/App.jsx` — EC, ET
- `frontend/src/utils/graphStyles.js` — edge styles

---

## R15 — OPERATES_ON (DML Targets)

**Description:** INSERT/UPDATE/DELETE/MERGE target tables should have edges showing data flow into the operation.

**Solution:** Phase 9 identifies DML target tables by their `defined_in` field (INSERT INTO, DELETE FROM, UPDATE, MERGE). For each, finds columns in the same context and creates OPERATES_ON edges from feeding columns to the target table.

**Files modified:**
- `backend/app/extractor/dependency_graph.py` — Phase 9
- `backend/app/services/graph_service.py` — color `#E74C3C`
- `frontend/src/App.jsx` — filter + legend

---

## R16 — REFERENCES (Bare Column Name Resolution)

**Description:** Bare column names in HAVING/ORDER BY (like `total_orders` in `HAVING total_orders >= 3`) should reference their SELECT definition.

**Solution:** Phase 7 matches bare `table_column` variables (no source_columns, no table prefix) against defined variables (aggregates, window results, CASE results, etc.) with the same name. Creates REFERENCES edges from the defined variable → the bare reference.

**Files modified:**
- `backend/app/extractor/dependency_graph.py` — Phase 7
- `backend/app/services/graph_service.py` — color `#5DADE2`
- `frontend/src/App.jsx` — filter + legend

---

## R17 — COMPONENT_LINK Safety Net

**Description:** Ensure every graph is a single connected component, even when SQL has genuinely separate scopes (different statements, correlated subqueries with no shared tables).

**Solution:** Phase 11 runs Union-Find across all edges. If multiple components exist, it bridges each small component to the largest one via COMPONENT_LINK edges. The bridge connects the small component's best anchor node (preferring database_table) to any node in the main component.

**Files modified:**
- `backend/app/extractor/dependency_graph.py` — Phase 11
- `backend/app/services/graph_service.py` — color `#E67E22`
- `frontend/src/App.jsx` — filter + legend

---

## R18 — Global Node Deduplication

**Description:** The same column must appear only once in the graph, regardless of how many places it's referenced (multiple CTE contexts, WHERE + SELECT + GROUP BY).

**Solution:** Changed the dedup key in `_add()` from `(name, variable_type, context)` to `(name, variable_type)`. The first occurrence registers the node; subsequent references update the existing node. Eliminated 157 duplicate nodes across all test cases.

**Files modified:**
- `backend/app/extractor/variable_extractor_v2.py` — `_add()` method, key change

---

## R19 — Large Graph Performance Optimization

**Description:** Graphs with thousands of nodes/edges must remain smooth for pan, zoom, and interaction.

**Solution:** Three-tier approach:
1. **Compound nodes** — columns assigned as children of parent tables (via `parent` field). Collapsible.
2. **3 view modes** — Full (all nodes), Compact (tables visible, columns hidden), Tables (only table/CTE/VT nodes). Dropdown selector in header.
3. **Render optimizations** — `pixelRatio: 1`, `textureOnViewport: true`, `hideLabelsOnViewport: true`, `hideEdgesOnViewport: true`

**Files modified:**
- `backend/app/services/graph_service.py` — `parent` field assignment
- `frontend/src/App.jsx` — view mode state + dropdown
- `frontend/src/utils/graphStyles.js` — render config

---

## R20 — Input-Output Graph (Post-Processing)

**Description:** Show only data flow from input columns (pure table reads) to user-defined output columns. Find all paths between them.

**Solution:** 
- `POST /api/scripts/{id}/io_graph` endpoint accepts CSV (table_name, data_type, column_name, explanation)
- Backend parses CSV → finds input columns (table_column with empty source_columns) → BFS through dependency graph → matches output columns by name → returns simplified graph + path details
- Frontend: "IO Graph" button uploads CSV, "Full Graph" button switches back
- Edge click in IO view shows ordered path nodes with table names in parentheses

**Files modified:**
- `backend/app/services/io_graph_service.py` (240 lines) — BFS path finding
- `backend/app/routers/graph.py` — POST endpoint
- `frontend/src/App.jsx` — IO Graph button + IOPathPanel component
- `samples/financial/io_csv/` — 20 CSV files for existing samples
- `samples/tpcds/io_csv/` — 96 CSV files for TPC-DS queries

---

## R21 — Pipeline Logging

**Description:** Docker-compatible logging to track pipeline execution and debug failures.

**Solution:** `logger.py` outputs to stderr at 5 key checkpoints:
- `PIPELINE START` — script name, byte count
- `extract` — variable, table, CTE counts
- `deps` — edge count, breakdown by type
- `graph` — final node/edge counts
- `PIPELINE DONE` — elapsed milliseconds
- API request logging on each endpoint call

**Files modified:**
- `backend/app/services/logger.py` (50 lines) — structured logging
- `backend/app/extractor/adapter.py` — integrated log calls

---

## R22 — SQL Source Viewer

**Description:** Show the original SQL script alongside the graph for manual comparison.

**Solution:** Toggleable bottom panel (max 40% viewport height) with monospace pre-formatted SQL text. "Show SQL"/"Hide SQL" button in header, appears when a script is loaded.

**Files modified:**
- `frontend/src/App.jsx` — toggle state + panel component
- `frontend/src/styles/app.css` — `.sql-panel` styles

---

## R23 — SQL Sample Library

**Description:** 22 diverse SQL test cases plus 99 TPC-DS benchmark queries covering real-world patterns.

**Basic queries (6):** `query1_select_where.sql`, `query2_joins_complex.sql`, `query3_subqueries_case.sql`, `query4_update_delete.sql`, `query5_nested.sql`, `tables.sql`

**GPS financial queries (16):** `fin_query1_reconciliation.sql` through `fin_query16_lateral_complex.sql`

**TPC-DS benchmark (99):** `q1.sql` through `q99.sql` in `samples/tpcds/`

**Real-world sources:** pg-ledger, Borghi97/fraud-detection-sql, iPay, TheLook Ecommerce, SaaS MRR Retention, RFM Analysis, Apache DataFusion TPC-DS

**Files:**
- `samples/*.sql` — 6 basic queries
- `samples/financial/tables_financial.sql` — 8 GPS tables
- `samples/financial/tables_financial_v2.sql` — enhanced schema with double-entry
- `samples/financial/fin_query1-16.sql` — GPS financial queries
- `samples/tpcds/q1-99.sql` — TPC-DS benchmark queries
- `samples/financial/io_csv/*.csv` — 20 IO CSV files
- `samples/tpcds/io_csv/*.csv` — 96 IO CSV files

---

## Summary

| # | Requirement | Files | Tests |
|---|---|---|---|
| R1 | Core variable extraction | `variable_extractor_v2.py`, `models/variable.py` | 17 |
| R2 | Dependency graph (10 edge types) | `dependency_graph.py`, `graph_service.py` | 6 |
| R3 | Interactive frontend | `App.jsx`, `graphStyles.js`, `app.css` | manual |
| R4 | File upload & auto-visualization | `App.jsx`, `app.css` | manual |
| R5 | Claude NL explanation | `claude_service.py` | (disabled) |
| R6 | Offline deployment | `vendor/`, `static/`, `start.py`, `Dockerfile` | manual |
| R7 | Test suite (193 tests) | 6 test files | 193 |
| R8 | Topological integrity (5 checks) | `test_graph_integrity.py` | 110 |
| R9 | ALIAS_OF edges | `dependency_graph.py` | — |
| R10 | VIRTUAL_TABLE + FEEDS_INTO | `models/variable.py`, `variable_extractor_v2.py`, `dependency_graph.py` | — |
| R11 | CTE_TABLE merging | `variable_extractor_v2.py` | — |
| R12 | Subquery & EXISTS tables | `variable_extractor_v2.py` | — |
| R13 | CASE & Subquery source cols | `variable_extractor_v2.py` | — |
| R14 | COMPUTED_FROM rename | `dependency_graph.py`, `graph_service.py`, `App.jsx` | — |
| R15 | OPERATES_ON (DML targets) | `dependency_graph.py` | — |
| R16 | REFERENCES (bare column refs) | `dependency_graph.py` | — |
| R17 | COMPONENT_LINK safety net | `dependency_graph.py` | — |
| R18 | Global node deduplication | `variable_extractor_v2.py` | — |
| R19 | Large graph performance | `graph_service.py`, `App.jsx`, `graphStyles.js` | — |
| R20 | Input-Output graph | `io_graph_service.py`, `routers/graph.py`, `App.jsx` | — |
| R21 | Pipeline logging | `logger.py`, `adapter.py` | — |
| R22 | SQL source viewer | `App.jsx`, `app.css` | — |
| R23 | SQL sample library | `samples/` (22 + 99 files + 116 CSVs) | — |
